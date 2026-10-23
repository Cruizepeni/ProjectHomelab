from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from YouSnipePaths import APP_ROOT, dependency_directories

PROGRAMS = {
    'ffmpeg': ('ffmpeg.exe', 'ffmpeg'),
    'ffprobe': ('ffprobe.exe', 'ffprobe'),
    'yt-dlp': ('yt-dlp.exe', 'yt-dlp'),
    'deno': ('deno.exe', 'deno'),
    'node': ('node.exe', 'node'),
    '7zip': ('7z.exe', '7zz'),
}

RESOURCE_MANIFESTS = {
    '7zip': '7Zip/7Zip_Manifest.json',
    'deno': 'Deno/Deno_Manifest.json',
    'ffmpeg': 'Ffmpeg/Ffmpeg_Manifest.json',
    'yt-dlp': 'Yt-dlp/Yt-dlp_Manifest.json',
}
RESOURCE_ROOT = 'https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Resources/ThirdParty'
REQUIRED_VERSIONS = {
    'yt-dlp': '2026.08.19',
    'ffmpeg': '9.0.1',
    'deno': '2.9.6',
}
MAX_METADATA_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 1024 * 1024 * 1024


def _candidate_score(path: Path, program: str) -> tuple:
    parts = {part.lower() for part in path.parts}
    return (int('yousnipe' in parts), int('bin' in parts), -len(path.parts))


def _installed_7zip() -> str | None:
    if sys.platform != 'win32':
        return shutil.which('7zz') or shutil.which('7z')
    for name in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)'):
        folder = os.environ.get(name)
        if folder:
            candidate = Path(folder) / '7-Zip' / '7z.exe'
            try:
                if candidate.is_file():
                    return str(candidate)
            except OSError:


                continue
    return shutil.which('7z.exe')


def _dependency_version_matches(program: str, version_line: str | None) -> bool:
    required = REQUIRED_VERSIONS.get('ffmpeg' if program == 'ffprobe' else program)
    if not required:
        return bool(version_line)
    first = (str(version_line or '').splitlines() or [''])[0].strip()
    if program == 'yt-dlp':
        return first == required
    if program == 'deno':
        return bool(re.match(r'^deno\s+' + re.escape(required) + r'(?=\s|$)', first, re.I))
    if program in ('ffmpeg', 'ffprobe'):
        return bool(re.match(r'^' + program + r' version n?' + re.escape(required) + r'(?=[-+\s]|$)', first, re.I))
    return False


def _matches_installed_version(path: str, program: str) -> bool:
    if not executable_exists(path):
        return False
    if program in ('7zip', 'node'):
        return True
    version, error = _version(path, ['-version' if program in ('ffmpeg', 'ffprobe') else '--version'])
    return error is None and _dependency_version_matches(program, version)


def resolve_program(program: str, override: str | None = None) -> str:
    if program not in PROGRAMS:
        raise ValueError(f'Unknown dependency: {program}')
    if override and override.strip() and override.strip().lower() != 'default':
        return os.path.expanduser(override.strip())
    exe_name, unix_name = PROGRAMS[program]
    name = exe_name if sys.platform == 'win32' else unix_name
    if program == '7zip':
        return _installed_7zip() or name
    if program == 'node':
        return shutil.which(unix_name) or shutil.which(exe_name) or name
    dependency_name = 'ffmpeg' if program == 'ffprobe' else program
    pinned = REQUIRED_VERSIONS.get(dependency_name)
    family = {'ffmpeg': 'FFmpeg', 'yt-dlp': 'Yt-dlp', 'deno': 'Deno'}.get(dependency_name)
    roots = [APP_ROOT / 'Dependencies', *dependency_directories()]
    seen = set()
    for root in roots:
        candidate = Path(root) / family / pinned / name if family and pinned else None
        if candidate and str(candidate) not in seen:
            seen.add(str(candidate))
            if _matches_installed_version(str(candidate), program):
                return str(candidate)
    for root in roots:
        for prefix in (root, root / 'DownloadHandling', root / 'MediaHandling', root / dependency_name, root / 'bin'):
            for filename in (name, exe_name, unix_name):
                path = Path(prefix) / filename
                if str(path) in seen:
                    continue
                seen.add(str(path))
                if _matches_installed_version(str(path), program):
                    return str(path)
    system = shutil.which(unix_name) or shutil.which(exe_name)
    if system and _matches_installed_version(system, program):
        return system
    return name


def executable_exists(command: str) -> bool:
    if not command:
        return False



    try:
        if Path(command).is_file():
            return True
    except OSError:
        return False
    try:
        return shutil.which(command) is not None
    except OSError:
        return False


def default_js_runtime() -> str:
    deno = resolve_program('deno')
    if executable_exists(deno):
        return f'deno:{deno}'
    node = resolve_program('node')
    if executable_exists(node):
        return f'node:{node}'
    return 'deno'


def _version(command: str, args: list[str]) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run([command, *args], capture_output=True, text=True, timeout=10, check=False,
                                stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        lines = (result.stdout or result.stderr).strip().splitlines()
        if result.returncode == 0:
            return (lines[0][:220] if lines else 'available'), None
        return None, (lines[-1][:220] if lines else f'exit code {result.returncode}')
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)


def dependency_report(runtime: dict) -> dict:
    entries = [('yt-dlp', 'ytdlpBin', ['--version']), ('FFmpeg', 'ffmpegPath', ['-version']),
               ('FFprobe', 'ffprobePath', ['-version'])]
    result = {}
    for name, key, args in entries:
        command = str(runtime.get(key) or '').strip()
        version, error = _version(command, args) if executable_exists(command) else (None, 'Executable not found')
        matched = _dependency_version_matches(name.lower(), version)
        if version and not matched:
            error = f'Installed version does not match required {REQUIRED_VERSIONS["ffmpeg" if name.lower() == "ffprobe" else name.lower()]}: {version}'
        result[name] = {'path': command, 'ok': matched, 'version': version, 'error': error}
    raw = str(runtime.get('ytdlpJsRuntime') or '').strip()
    engine, command = raw.split(':', 1) if ':' in raw else (raw, raw)
    if engine.lower() not in {'deno', 'node', 'bun', 'quickjs'}:
        result['JavaScript runtime'] = {'path': raw, 'ok': False, 'version': None, 'error': 'Unrecognised runtime'}
    else:
        version, error = _version(command, ['--version']) if executable_exists(command) else (None, 'Executable not found')
        matched = _dependency_version_matches(engine.lower(), version)
        if version and not matched:
            error = f'Installed {engine} version does not match the required version.'
        result['JavaScript runtime'] = {'path': raw, 'ok': matched, 'version': version, 'error': error}
    return result


def missing_requirements(runtime: dict) -> list[str]:
    report = dependency_report(runtime)
    requirements = []
    if not report['yt-dlp']['ok']:
        requirements.append('yt-dlp')
    if not report['FFmpeg']['ok'] or not report['FFprobe']['ok']:
        requirements.append('ffmpeg')
    deno = resolve_program('deno')
    if not _matches_installed_version(deno, 'deno') or not report['JavaScript runtime']['ok']:
        requirements.append('deno')
    return requirements


def target_key(system: str | None = None, machine: str | None = None) -> str:
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    systems = {'windows': 'windows', 'linux': 'linux', 'darwin': 'mac', 'macos': 'mac'}
    architectures = {'x86_64': 'x86_64', 'amd64': 'x86_64', 'x64': 'x86_64',
                     'arm64': 'arm64', 'aarch64': 'arm64'}
    if system not in systems or machine not in architectures:
        raise RuntimeError(f'Unsupported dependency platform: {system}/{machine}')
    return f'{systems[system]}-{architectures[machine]}'


def _fetch_manifest(url: str) -> dict:
    parts = urllib.parse.urlparse(url)
    if parts.scheme != 'https' or parts.hostname != 'raw.githubusercontent.com':
        raise RuntimeError('Dependency manifests must come from the ProjectHomelab HTTPS resource repository.')
    request = urllib.request.Request(url, headers={'User-Agent': 'YouSnipe/1.0.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(MAX_METADATA_BYTES + 1)
    if len(payload) > MAX_METADATA_BYTES:
        raise RuntimeError('Dependency manifest is too large.')
    record = json.loads(payload)
    if not isinstance(record, dict):
        raise RuntimeError('Dependency manifest is invalid.')
    return record


def dependency_asset(name: str, key: str | None = None) -> tuple[str, dict]:
    if name not in RESOURCE_MANIFESTS:
        raise ValueError(f'Unknown managed dependency: {name}')
    base = _fetch_manifest(f'{RESOURCE_ROOT}/{RESOURCE_MANIFESTS[name]}')
    version = REQUIRED_VERSIONS.get(name) or str(base.get('latest') or '')
    item = (base.get('versions') or {}).get(version)
    if not isinstance(item, dict) or item.get('status') != 'supported':
        raise RuntimeError(f'No supported {name} dependency release exists.')
    subpath = str(item.get('manifest') or '')
    if not subpath or '..' in Path(subpath).parts or subpath.startswith('/'):
        raise RuntimeError('Dependency version manifest path is invalid.')
    folder = RESOURCE_MANIFESTS[name].rsplit('/', 1)[0]
    manifest = _fetch_manifest(f'{RESOURCE_ROOT}/{folder}/{subpath}')
    if str(manifest.get('version')) != version:
        raise RuntimeError('Dependency version mismatch between manifests.')
    selected = (manifest.get('targets') or {}).get(key or target_key())
    if not isinstance(selected, dict):
        raise RuntimeError(f'{name} has no release for {key or target_key()}.')
    return version, selected


def _lfs_media_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'raw.githubusercontent.com':
        raise RuntimeError('Git LFS fallback requires a ProjectHomelab raw-resource URL.')
    if not parsed.path.startswith('/Cruizepeni/ProjectHomelab/main/Resources/ThirdParty/'):
        raise RuntimeError('Git LFS fallback was refused for an unknown resource path.')
    return 'https://media.githubusercontent.com/media' + parsed.path


def _lfs_pointer(path: Path) -> tuple[str, int] | None:
    if path.stat().st_size > 512:
        return None
    content = path.read_bytes()
    match = re.fullmatch(
        rb'version https://git-lfs\.github\.com/spec/v1\r?\n'
        rb'oid sha256:([0-9a-f]{64})\r?\nsize ([0-9]+)\r?\n?',
        content,
    )
    return (match.group(1).decode('ascii'), int(match.group(2))) if match else None


def _fetch_verified_resource(url: str, target: Path, expected_sha256: str, size: int, progress=None) -> bool:
    checksum = hashlib.sha256()
    count = 0
    request = urllib.request.Request(url, headers={'User-Agent': 'YouSnipe/1.0.0'})
    with urllib.request.urlopen(request, timeout=120) as response, target.open('wb') as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > size:
                raise RuntimeError('Dependency download exceeds the manifest size.')
            checksum.update(chunk)
            handle.write(chunk)
            if progress is not None and count <= size:
                progress({'stage': 'downloading', 'downloadedBytes': count, 'totalBytes': size, 'percent': round(100 * count / size, 1)})
    return count == size and checksum.hexdigest() == expected_sha256


def _verified_download(url: str, target: Path, sha256: str, size: int, progress=None) -> Path:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'raw.githubusercontent.com':
        raise RuntimeError('Dependency download URL must be ProjectHomelab HTTPS.')
    expected_sha256 = str(sha256).strip().lower()
    if len(expected_sha256) != 64 or any(ch not in '0123456789abcdef' for ch in expected_sha256):
        raise RuntimeError('Dependency manifest has an invalid SHA-256 checksum.')
    size = int(size)
    if size < 1 or size > MAX_PACKAGE_BYTES:
        raise RuntimeError('Dependency manifest has an unsupported package size.')
    try:
        if _fetch_verified_resource(url, target, expected_sha256, size, progress):
            if progress is not None:
                progress({'stage': 'verified', 'downloadedBytes': size, 'totalBytes': size, 'percent': 100})
            return target
        pointer = _lfs_pointer(target)
        if pointer is None:
            raise RuntimeError('Dependency download failed size/SHA-256 verification: ' + target.name)
        if pointer != (expected_sha256, size):
            raise RuntimeError('Git LFS pointer does not match the dependency manifest: ' + target.name)
        media_url = _lfs_media_url(url)
        if progress is not None:
            progress({'stage': 'resolving_lfs', 'downloadedBytes': 0, 'totalBytes': size, 'percent': 0})
        try:
            valid = _fetch_verified_resource(media_url, target, expected_sha256, size, progress)
        except Exception as exc:
            raise RuntimeError(
                'Git LFS resource could not be downloaded: ' + target.name +
                '. Confirm repository Git LFS bandwidth and file availability. ' + str(exc)
            ) from exc
        if not valid:
            raise RuntimeError(
                'Git LFS resource failed size/SHA-256 verification: ' + target.name +
                '. Confirm repository Git LFS bandwidth and asset availability.'
            )
        if progress is not None:
            progress({'stage': 'verified', 'downloadedBytes': size, 'totalBytes': size, 'percent': 100})
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _match_member(name: str, wanted: str) -> bool:
    return Path(name.replace('\\', '/')).name.casefold() == wanted.casefold()


def _extract_zip_named(path: Path, folder: Path, wanted: tuple[str, ...]):
    with zipfile.ZipFile(path) as archive:
        for filename in wanted:
            candidates = [info for info in archive.infolist() if not info.is_dir() and _match_member(info.filename, filename)]
            if len(candidates) != 1:
                raise RuntimeError(f'Archive must contain exactly one {filename}.')
            info = candidates[0]
            if info.file_size > MAX_PACKAGE_BYTES:
                raise RuntimeError('Decompressed executable exceeds size limit.')
            if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
                raise RuntimeError('Dependency executable cannot be a symbolic link.')
            with archive.open(info) as source, (folder / filename).open('wb') as dest:
                shutil.copyfileobj(source, dest)


def _extract_tar_named(path: Path, folder: Path, wanted: tuple[str, ...]):
    with tarfile.open(path, 'r:xz') as archive:
        for filename in wanted:
            candidates = [item for item in archive.getmembers() if _match_member(item.name, filename) and item.isfile()]
            if len(candidates) != 1:
                raise RuntimeError(f'Archive must contain exactly one regular {filename}.')
            if candidates[0].size > MAX_PACKAGE_BYTES:
                raise RuntimeError('Decompressed executable exceeds size limit.')
            source = archive.extractfile(candidates[0])
            if source is None:
                raise RuntimeError(f'Missing regular file {filename}.')
            with source, (folder / filename).open('wb') as dest:
                shutil.copyfileobj(source, dest)


def _install_windows_7zip(path: Path):
    if sys.platform != 'win32':
        raise RuntimeError('7-Zip Windows installer cannot run on this operating system.')
    import ctypes.wintypes
    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.wintypes.DWORD), ('fMask', ctypes.c_ulong),
                    ('hwnd', ctypes.wintypes.HWND), ('lpVerb', ctypes.c_wchar_p),
                    ('lpFile', ctypes.c_wchar_p), ('lpParameters', ctypes.c_wchar_p),
                    ('lpDirectory', ctypes.c_wchar_p), ('nShow', ctypes.c_int),
                    ('hInstApp', ctypes.wintypes.HINSTANCE), ('lpIDList', ctypes.c_void_p),
                    ('lpClass', ctypes.c_wchar_p), ('hkeyClass', ctypes.wintypes.HKEY),
                    ('dwHotKey', ctypes.wintypes.DWORD), ('hIcon', ctypes.wintypes.HANDLE),
                    ('hProcess', ctypes.wintypes.HANDLE)]
    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040
    info.lpVerb = 'runas'
    info.lpFile = str(path)
    info.lpParameters = '/S'
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        raise RuntimeError('7-Zip installation was cancelled or blocked by Windows.')
    try:
        wait = ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 120000)
        if wait != 0:
            raise RuntimeError('7-Zip installation timed out.')
        exit_code = ctypes.wintypes.DWORD()
        if not ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)) or exit_code.value:
            raise RuntimeError(f'7-Zip installation failed (code {exit_code.value}).')
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
    if not _installed_7zip():
        raise RuntimeError('7-Zip installer finished but 7z.exe could not be found.')


def _extract_7z_selected(path: Path, folder: Path, wanted: tuple[str, ...]):
    tool = resolve_program('7zip')
    if not executable_exists(tool):
        raise RuntimeError('7-Zip is required to extract the Windows FFmpeg package.')
    command = [tool, 'e', '-y', '-r', f'-o{folder}', str(path), *wanted]
    result = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                            timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('7-Zip could not extract FFmpeg: ' + (result.stderr or result.stdout)[-500:])
    for filename in wanted:
        if not (folder / filename).is_file():
            raise RuntimeError(f'FFmpeg package did not provide {filename}.')


def _install_archive(path: Path, folder: Path, fmt: str, wanted: tuple[str, ...]):
    if fmt == 'zip':
        _extract_zip_named(path, folder, wanted)
    elif fmt == 'tar.xz':
        _extract_tar_named(path, folder, wanted)
    elif fmt == '7z':
        _extract_7z_selected(path, folder, wanted)
    else:
        raise RuntimeError(f'Unsupported dependency archive: {fmt}')



def required_executables(name: str, entry: dict, operating_system: str | None = None) -> tuple[str, ...]:
    system = operating_system or sys.platform
    if name == 'ffmpeg':
        return ('ffmpeg.exe', 'ffprobe.exe') if system == 'win32' else ('ffmpeg', 'ffprobe')
    if name == 'yt-dlp':
        return ('yt-dlp.exe',) if system == 'win32' else ('yt-dlp',)
    if name in ('deno', '7zip'):
        filename = entry.get('executable_name')
        if not isinstance(filename, str) or not filename or '/' in filename or '\\' in filename or filename in ('.', '..'):
            raise RuntimeError(f'{name} manifest has no valid executable name.')
        return (filename,)
    raise ValueError(f'Unknown managed dependency: {name}')


def install_dependency(name: str, progress=None) -> dict:
    def emit(stage: str, **fields):
        if progress is not None:
            progress({'dependency': name, 'stage': stage, 'version': version, **fields})

    def download_package(url, path, sha256, size):
        if progress is None:
            return _verified_download(url, path, sha256, size)
        return _verified_download(url, path, sha256, size, lambda data: emit(**data))

    version, entry = dependency_asset(name)
    emit('manifest_resolved')
    if name == '7zip' and entry.get('install', {}).get('requires_elevation') and sys.platform == 'win32':
        destination = APP_ROOT / 'Dependencies' / '7Zip'
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.7zip-', dir=destination) as work:
            archive = Path(work) / Path(str(entry['artifact'])).name
            download_package(entry['download_url'], archive, entry['sha256'], entry['size_bytes'])
            emit('installing')
            _install_windows_7zip(archive)
        emit('installed')
        return {'dependency': name, 'version': version, 'path': resolve_program('7zip')}
    target_root = APP_ROOT / 'Dependencies' / {'ffmpeg': 'FFmpeg', 'yt-dlp': 'Yt-dlp', 'deno': 'Deno', '7zip': '7Zip'}[name]
    install_dir = target_root / version
    required = required_executables(name, entry)
    if all((install_dir / filename).is_file() for filename in required):
        for filename in required:
            arguments = ['-version'] if filename.startswith('ff') else ['--version']
            if name == '7zip':
                arguments = ['-h']
            result, error = _version(str(install_dir / filename), arguments)
            if result is None or not _dependency_version_matches('ffprobe' if filename.startswith('ffprobe') else 'ffmpeg' if filename.startswith('ffmpeg') else name, result):
                raise RuntimeError(f'Existing {name} executable version is invalid for required {version}: {result or error}')
        emit('installed')
        return {'dependency': name, 'version': version, 'path': str(install_dir)}
    target_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.stage-', dir=target_root) as work:
        temp = Path(work)
        output = temp / 'installed'
        output.mkdir()
        if name == 'ffmpeg':
            artifacts = entry['artifacts']
            for artifact in artifacts:
                package = temp / Path(str(artifact['path'])).name
                download_package(artifact['download_url'], package, artifact['sha256'], artifact['size_bytes'])
                requested = required if artifact['role'] == 'package' else (artifact['role'],)
                emit('extracting')
                _install_archive(package, output, artifact.get('archive_format') or 'zip', requested)
        else:
            package = temp / Path(str(entry['artifact'])).name
            download_package(entry['download_url'], package, entry['sha256'], entry['size_bytes'])
            if entry.get('install', {}).get('method') == 'copy':
                emit('installing')
                shutil.copy2(package, output / required[0])
            else:
                emit('extracting')
                fmt = entry.get('install', {}).get('archive_format') or Path(package).suffix.lstrip('.')
                if str(package).endswith('.tar.xz'):
                    fmt = 'tar.xz'
                _install_archive(package, output, fmt, required)
        if not all((output / filename).is_file() and (output / filename).stat().st_size > 0 for filename in required):
            raise RuntimeError(f'{name} installation did not produce required executables.')
        if sys.platform != 'win32':
            for filename in required:
                binary = output / filename
                binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        emit('validating')
        for filename in required:
            arguments = ['-version'] if filename.startswith('ff') else ['--version']
            if name == '7zip':
                arguments = ['-h']
            result, error = _version(str(output / filename), arguments)
            if result is None or not _dependency_version_matches('ffprobe' if filename.startswith('ffprobe') else 'ffmpeg' if filename.startswith('ffmpeg') else name, result):
                raise RuntimeError(f'Extracted {name} executable version is invalid for required {version}: {result or error}')
        if install_dir.exists():
            raise RuntimeError(f'Incomplete install directory exists and will not be overwritten: {install_dir}')
        output.rename(install_dir)
    emit('installed')
    return {'dependency': name, 'version': version, 'path': str(install_dir)}


def installation_plan(runtime: dict) -> list[str]:
    requirements = missing_requirements(runtime)
    if 'ffmpeg' in requirements and target_key() == 'windows-x86_64' and not executable_exists(resolve_program('7zip')):
        return ['7zip', *requirements]
    return requirements


def install_missing_dependencies(runtime: dict, progress=None) -> list[dict]:
    plan = installation_plan(runtime)
    for key in ('ytdlpBin', 'ffmpegPath', 'ffprobePath'):
        command = str(runtime.get(key) or '').strip()
        program = {'ytdlpBin': 'yt-dlp', 'ffmpegPath': 'ffmpeg', 'ffprobePath': 'ffprobe'}[key]
        if program in plan and command and Path(command).is_absolute():
            if not executable_exists(command):
                raise RuntimeError(f'Custom dependency path does not exist: {command}. Reset it to Default in Settings.')
            if not _matches_installed_version(command, program):
                raise RuntimeError(f'Custom dependency path does not match the required {program} version: {command}. Reset it to Default in Settings.')
    results = []
    for index, name in enumerate(plan, 1):
        def dependency_progress(event, sequence=index):
            if progress is not None:
                progress({'dependencyIndex': sequence, 'dependencyCount': len(plan), **event})
        if progress is not None:
            dependency_progress({'dependency': name, 'stage': 'checking_manifest', 'percent': 0})
        results.append(install_dependency(name, progress=dependency_progress) if progress is not None else install_dependency(name))
    return results
