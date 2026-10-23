from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
import zipfile
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from YouSnipePaths import appdata_subdirectory

CURRENT_VERSION = '1.0.0'
RELEASE_MANIFEST_URL = 'https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Releases/YouSnipe/YouSnipe_Release_Manifest.json'
RESOURCES_MANIFEST_URL = 'https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Resources/FirstParty/YouSnipe/YouSnipe_Resources_Manifest.json'
UPDATER_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024


def _version_key(value):
    if not re.fullmatch(r'\d+\.\d+\.\d+', str(value)):
        raise ValueError('Release manifest has an invalid X.Y.Z version')
    return tuple(map(int, str(value).split('.')))


def _load_manifest(source: str) -> dict:
    parsed = urlparse(source)
    if parsed.scheme not in ('', 'https'):
        raise ValueError('Manifest must be a local JSON path or HTTPS URL')
    if parsed.scheme == 'https':
        with urlopen(Request(source, headers={'User-Agent': 'YouSnipe/1.0.0'}), timeout=20) as response:
            raw = response.read(MAX_MANIFEST_BYTES + 1)
    else:
        raw = Path(source).expanduser().read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('Manifest exceeds size limit')
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError('Release manifest must be an object')
    if 'releases' not in obj:
        _version_key(str(obj.get('version') or ''))
    return obj


def _platform_key():
    system = platform.system()
    if system not in {'Windows', 'Linux'}:
        raise RuntimeError(f'YouSnipe updates are not yet supported for {system}.')
    machine = platform.machine().lower()
    arch = {'amd64': 'x86_64', 'x86_64': 'x86_64', 'x64': 'x86_64',
            'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine)
    if not arch:
        raise RuntimeError(f'Unsupported update architecture: {machine}')
    return f'{system}_{arch}'


def check_update(source: str = RELEASE_MANIFEST_URL) -> dict:
    obj = _load_manifest(source)
    if isinstance(obj.get('releases'), dict):
        version = str(obj.get('latest_version') or CURRENT_VERSION)
        available = _version_key(version) > _version_key(CURRENT_VERSION)
        asset = obj['releases'].get(version, {}).get('assets', {}).get(_platform_key(), {}) if available else {}
        if available and not asset:
            raise RuntimeError('The latest YouSnipe release does not provide an update for this OS/architecture.')
        return {'currentVersion': CURRENT_VERSION, 'releaseVersion': version,
                'updateAvailable': available, 'url': asset.get('download_url', ''),
                'sha256': asset.get('sha256', ''), 'sizeBytes': asset.get('size_bytes'),
                'source': source}
    version = str(obj['version'])
    return {'currentVersion': CURRENT_VERSION, 'releaseVersion': version,
            'updateAvailable': _version_key(version) > _version_key(CURRENT_VERSION),
            'url': obj.get('url') or '', 'sha256': obj.get('sha256') or '',
            'sizeBytes': obj.get('size_bytes'), 'source': source}


def stage_update(source: str = RELEASE_MANIFEST_URL, destination: Path | None = None) -> dict:
    info = check_update(source)
    if not info['updateAvailable']:
        raise ValueError('No newer release is available')
    url = str(info['url'])
    digest = str(info['sha256']).strip().lower()
    if urlparse(url).scheme != 'https' or not urlparse(url).path.lower().endswith('.zip'):
        raise ValueError('Archive must be an HTTPS ZIP URL')
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('A SHA-256 checksum is mandatory for staging')
    expected_size = info.get('sizeBytes')
    if expected_size is not None and not (1 <= int(expected_size) <= MAX_ARCHIVE_BYTES):
        raise ValueError('Release manifest has an invalid ZIP size')
    target_dir = destination or appdata_subdirectory('Staged', appdata_subdirectory('Updates'))
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f'YouSnipe_{info["releaseVersion"]}.zip'
    temp = target_dir / (target.name + '.downloading')
    hasher = hashlib.sha256()
    total = 0
    try:
        with urlopen(Request(url, headers={'User-Agent': 'YouSnipe/1.0.0'}), timeout=120) as response, temp.open('wb') as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError('Archive exceeds size limit')
                hasher.update(chunk)
                handle.write(chunk)
        if expected_size is not None and total != int(expected_size):
            raise ValueError('Archive size does not match the release manifest')
        if hasher.hexdigest() != digest:
            raise ValueError('Archive SHA-256 mismatch')
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return {**info, 'stagedPath': str(target), 'verifiedSha256': digest,
            'applied': False, 'note': 'Staged only. Applying a verified update requires YouSnipeUpdater.'}


RESTART_MODES = frozenset({'gui', 'headless', 'headless-server'})


def runtime_application_path() -> Path:
    if platform.system() == 'Linux' and os.environ.get('APPIMAGE'):
        return Path(os.environ['APPIMAGE']).expanduser().resolve()
    return Path(sys.executable).resolve()


def expected_runtime_name() -> str:
    return 'YouSnipe.exe' if platform.system() == 'Windows' else 'YouSnipe.AppImage'


def expected_updater_name() -> str:
    return 'YouSnipeUpdater.exe' if platform.system() == 'Windows' else 'YouSnipeUpdater'


def _verified_json(reference: dict, label: str) -> dict:
    if not isinstance(reference, dict):
        raise RuntimeError(f'{label} manifest reference is missing')
    url = str(reference.get('download_url') or '')
    digest = str(reference.get('sha256') or '').lower()
    try:
        size = int(reference.get('size_bytes'))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f'{label} manifest size is invalid') from exc
    if urlparse(url).scheme != 'https' or not re.fullmatch(r'[0-9a-f]{64}', digest) or not 0 < size <= MAX_MANIFEST_BYTES:
        raise RuntimeError(f'{label} manifest reference is incomplete or unsafe')
    with urlopen(Request(url, headers={'User-Agent': 'YouSnipe/1.0.0'}), timeout=30) as response:
        raw = response.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise RuntimeError(f'{label} manifest verification failed')
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise RuntimeError(f'{label} manifest must be a JSON object')
    return obj


def _updater_release(current_version: str) -> tuple[str, dict]:
    resources = _load_manifest(RESOURCES_MANIFEST_URL)
    components = resources.get('components')
    entry = components.get('YouSnipeUpdater') if isinstance(components, dict) else None
    updater_manifest = _verified_json((entry or {}).get('manifest'), 'YouSnipeUpdater')
    versions = updater_manifest.get('versions')
    if not isinstance(versions, dict):
        raise RuntimeError('YouSnipeUpdater release manifest has no versions')
    family = '.'.join(current_version.split('.')[:2])
    key = _platform_key()
    found = []
    for version, entry in versions.items():
        if not isinstance(entry, dict) or entry.get('compatibility_family') != family:
            continue
        try:
            if '.'.join(str(version).split('.')[:2]) != family:
                continue
            candidate = entry.get('assets', {}).get(key)
            if isinstance(candidate, dict):
                found.append((_version_key(version), version, candidate))
        except (ValueError, TypeError, AttributeError):
            continue
    if not found:
        raise RuntimeError('No compatible YouSnipeUpdater is available for this platform and application version')
    found.sort(key=lambda item: item[0], reverse=True)
    return found[0][1], found[0][2]


def _download_verified(url: str, path: Path, digest: str, size: int) -> Path:
    if urlparse(url).scheme != 'https' or not re.fullmatch('[0-9a-f]{64}', str(digest).lower()):
        raise RuntimeError('Updater requires a HTTPS download and SHA-256 checksum')
    size = int(size)
    if size <= 0 or size > UPDATER_MAX_ARCHIVE_BYTES:
        raise RuntimeError('Updater package size is invalid')
    temp = path.with_name(path.name + '.downloading')
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    hasher = hashlib.sha256()
    try:
        with urlopen(Request(url, headers={'User-Agent': 'YouSnipe/1.0.0'}), timeout=120) as response, temp.open('wb') as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > size:
                    raise RuntimeError('Updater package exceeds manifest size')
                hasher.update(block)
                output.write(block)
        if total != size or hasher.hexdigest() != digest.lower():
            raise RuntimeError('Updater package size or SHA-256 verification failed')
        os.replace(temp, path)
        return path
    finally:
        temp.unlink(missing_ok=True)


def _extract_updater(archive_path: Path, entry: dict, destination: Path) -> Path:
    runtime_name = expected_updater_name()
    if entry.get('executable') != runtime_name:
        raise RuntimeError('Updater manifest executable name does not match the platform')
    digest = str(entry.get('executable_sha256') or '').lower()
    try:
        size = int(entry.get('executable_size_bytes'))
    except (ValueError, TypeError) as exc:
        raise RuntimeError('Updater executable size missing') from exc
    if not re.fullmatch('[0-9a-f]{64}', digest) or size <= 0:
        raise RuntimeError('Updater executable verification data missing')
    pending = destination.with_name('.' + destination.name + '.new')
    try:
        with zipfile.ZipFile(archive_path) as package:
            files = [item for item in package.infolist() if not item.is_dir()]
            if len(files) != 1 or files[0].filename != runtime_name:
                raise RuntimeError('Updater ZIP must contain the stable executable at its root')
            info = files[0]
            unix_mode = (info.external_attr >> 16) & 0xffff
            if stat.S_ISLNK(unix_mode) or info.file_size != size:
                raise RuntimeError('Invalid updater ZIP runtime')
            hasher = hashlib.sha256()
            total = 0
            with package.open(info) as inp, pending.open('wb') as out:
                while True:
                    chunk = inp.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > size:
                        raise RuntimeError('Updater executable exceeds manifest size')
                    hasher.update(chunk)
                    out.write(chunk)
            if total != size or hasher.hexdigest() != digest:
                raise RuntimeError('Updater executable size or SHA-256 verification failed')
        if platform.system() == 'Linux':
            pending.chmod(pending.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if destination.exists():
            raise RuntimeError('An updater executable already exists in the application folder; refusing to replace it')
        os.replace(pending, destination)
        return destination
    finally:
        pending.unlink(missing_ok=True)


def _clean_launch_environment() -> dict:
    environment = os.environ.copy()
    for key in ('APPIMAGE', 'APPDIR', 'ARGV0', 'OWD', 'APPIMAGE_EXTRACT_AND_RUN'):
        environment.pop(key, None)
    environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    if platform.system() == 'Linux':
        original = environment.get('LD_LIBRARY_PATH_ORIG')
        if original is None:
            environment.pop('LD_LIBRARY_PATH', None)
        else:
            environment['LD_LIBRARY_PATH'] = original
    return environment


def _launch_updater(executable: Path, target: Path, new_version: str, launch_mode: str) -> None:
    arguments = [str(executable), '--parent-pid', str(os.getpid()), '--target', str(target),
                 '--current-version', CURRENT_VERSION, '--target-version', new_version,
                 '--restart-mode', launch_mode, '--release-manifest-url', RELEASE_MANIFEST_URL]
    options = {'cwd': str(executable.parent), 'env': _clean_launch_environment(), 'close_fds': True}
    if platform.system() == 'Windows':
        options['creationflags'] = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    else:
        options['start_new_session'] = True
        options['stdin'] = subprocess.DEVNULL
    subprocess.Popen(arguments, **options)


def start_external_update(launch_mode: str = 'gui') -> dict:
    if launch_mode not in RESTART_MODES:
        raise ValueError('Unsupported update restart mode')
    if not getattr(sys, 'frozen', False):
        raise RuntimeError('Automatic updating requires a packaged YouSnipe.exe or YouSnipe.AppImage; source builds can only check updates')
    target = runtime_application_path()
    if target.name != expected_runtime_name():
        raise RuntimeError('This YouSnipe installation is not using the stable runtime filename')
    info = check_update()
    if not info['updateAvailable']:
        raise RuntimeError('No newer YouSnipe release is available')
    version = info['releaseVersion']
    updater_version, asset = _updater_release(CURRENT_VERSION)
    name = str(asset.get('file') or '')
    if not re.fullmatch(r'YouSnipeUpdater_\d+\.\d+\.\d+_(Windows|Linux)_(x86_64|arm64)\.zip', name):
        raise RuntimeError('Updater package name is invalid')
    updater = target.parent / expected_updater_name()
    if updater.exists():
        raise RuntimeError('A prior YouSnipeUpdater exists; resolve that update before starting another')
    package = target.parent / ('.' + name)
    try:
        _download_verified(str(asset.get('download_url') or ''), package, str(asset.get('sha256') or ''), asset.get('size_bytes'))
        _extract_updater(package, asset, updater)
    finally:
        package.unlink(missing_ok=True)
    try:
        _launch_updater(updater, target, version, launch_mode)
    except Exception:
        updater.unlink(missing_ok=True)
        raise
    time.sleep(0.2)
    return {'updateStarted': True, 'currentVersion': CURRENT_VERSION, 'targetVersion': version,
            'updaterVersion': updater_version, 'restartMode': launch_mode, 'applicationMustExit': True}
