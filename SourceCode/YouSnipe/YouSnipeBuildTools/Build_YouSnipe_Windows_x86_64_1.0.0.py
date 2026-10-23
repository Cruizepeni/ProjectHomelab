from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import venv
import zipfile
from pathlib import Path

BUILDER_VERSION = '1.0.0'
PYINSTALLER_VERSION = '6.22.3'
PILLOW_VERSION = '11.3.0'
WEBSOCKETS_VERSION = '15.0.1'
FOLDER = re.compile(r'^YouSnipe_(\d+\.\d+\.\d+)$')
UPDATER_VERSION = re.compile(r"^\s*CURRENT_VERSION\s*=\s*['\"](\d+\.\d+\.\d+)['\"]", re.M)
ICON_ROOT = 'https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Resources/Icons/Features/YouSnipe/'

WINDOWS_LAUNCHER = "\nimport os\nimport sys\nfrom pathlib import Path\n\n\ndef _replace_stream(fd_number, attr):\n\n    try:\n        import ctypes\n        import msvcrt\n        import io\n        kernel32 = ctypes.windll.kernel32\n        kernel32.GetStdHandle.argtypes = [ctypes.c_uint32]\n        kernel32.GetStdHandle.restype = ctypes.c_void_p\n        handle = kernel32.GetStdHandle(((-11 if fd_number == 1 else -12) & 0xFFFFFFFF))\n        if not handle or handle == ctypes.c_void_p(-1).value:\n            return False\n        process = kernel32.GetCurrentProcess()\n        copied = ctypes.c_void_p()\n        kernel32.DuplicateHandle.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,\n                                              ctypes.POINTER(ctypes.c_void_p),ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]\n        kernel32.DuplicateHandle.restype = ctypes.c_int\n        if not kernel32.DuplicateHandle(process, handle, process, ctypes.byref(copied), 0, 1, 2):\n            return False\n        fileno = msvcrt.open_osfhandle(copied.value, os.O_TEXT)\n        stream = os.fdopen(fileno, 'w', encoding='utf-8', errors='replace', buffering=1)\n        setattr(sys, attr, stream)\n        return True\n    except (OSError, ValueError, AttributeError):\n        return False\n\n\ndef _prepare_cli_streams():\n    import ctypes\n    kernel32 = ctypes.windll.kernel32\n\n\n    if not _replace_stream(1, 'stdout'):\n        kernel32.AttachConsole(0xFFFFFFFF)\n        if not _replace_stream(1, 'stdout'):\n            try:\n                sys.stdout = open('CONOUT$', 'w', encoding='utf-8', buffering=1)\n            except OSError:\n                sys.stdout = open(os.devnull, 'w')\n    if not _replace_stream(2, 'stderr'):\n        try:\n            sys.stderr = open('CONOUT$', 'w', encoding='utf-8', buffering=1)\n        except OSError:\n            sys.stderr = open(os.devnull, 'w')\n    if sys.stdin is None:\n        try:\n            sys.stdin = open('CONIN$', 'r', encoding='utf-8')\n        except OSError:\n            sys.stdin = open(os.devnull, 'r')\n\n\ndef _prepare_gui_streams():\n    if sys.stdout is not None and sys.stderr is not None:\n        return\n    try:\n        from YouSnipePaths import appdata_subdirectory\n        folder = appdata_subdirectory('Logs')\n        folder.mkdir(parents=True, exist_ok=True)\n        stream = (folder / 'YouSnipeGUI.log').open('a', encoding='utf-8', buffering=1)\n    except OSError:\n        stream = open(os.devnull, 'w')\n    if sys.stdout is None:\n        sys.stdout = stream\n    if sys.stderr is None:\n        sys.stderr = stream\n\n\nif __name__ == '__main__':\n    arguments = sys.argv[1:]\n\n    if arguments and '--updated' not in arguments:\n        _prepare_cli_streams()\n    else:\n        _prepare_gui_streams()\n    from YouSnipe import main\n    raise SystemExit(main())\n"


VERBOSE = False


def show(label, value=''):

    print(f'[{label}] {value}' if value else f'[{label}]', flush=True)


def run(command, cwd=None, env=None, capture=False, live=False):

    argv = [str(value) for value in command]
    show('RUN', subprocess.list2cmdline(argv))
    result = subprocess.run(
        argv, cwd=str(cwd) if cwd else None, env=env,
        text=True, capture_output=capture, errors='replace',
    )
    if result.returncode:
        if capture:
            if result.stdout:
                print(result.stdout, end='' if result.stdout.endswith('\n') else '\n', flush=True)
            if result.stderr:
                print(result.stderr, end='' if result.stderr.endswith('\n') else '\n', file=sys.stderr, flush=True)
        raise RuntimeError('Command failed (exit ' + str(result.returncode) + '): '
                           + subprocess.list2cmdline(argv))

    if VERBOSE and capture:
        if result.stdout:
            print(result.stdout, end='' if result.stdout.endswith('\n') else '\n', flush=True)
        if result.stderr:
            print(result.stderr, end='' if result.stderr.endswith('\n') else '\n', file=sys.stderr, flush=True)
    return result



def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def root_and_version():
    root = Path(__file__).resolve().parent
    match = FOLDER.fullmatch(root.name)
    if not match:
        raise RuntimeError('Copy the build script into YouSnipe_X.Y.Z next to YouSnipe.py, then run it.')
    version = match.group(1)
    source = root / 'YouSnipe.py'
    updater = root / 'YouSnipeUpdater.py'
    if not source.is_file() or not updater.is_file():
        raise RuntimeError('Expected YouSnipe.py and YouSnipeUpdater.py beside the build script.')
    declared = UPDATER_VERSION.search(updater.read_text(encoding='utf-8'))
    if not declared:
        raise RuntimeError('YouSnipeUpdater.py must declare CURRENT_VERSION.')
    for module in ('YouSnipeGUI.py', 'YouSnipeServer.py', 'YouSnipePythonDependencies.py'):
        if not (root / module).is_file():
            raise RuntimeError('Required application module is missing: ' + module)
    return root, version, source


def stage_source(root, work, version):

    staged = work / 'source'
    staged.mkdir(parents=True, exist_ok=True)
    for path in root.glob('*.py'):
        shutil.copy2(path, staged / path.name)
    updater = staged / 'YouSnipeUpdater.py'
    original = updater.read_text(encoding='utf-8')
    versioned, count = UPDATER_VERSION.subn("CURRENT_VERSION = '" + version + "'", original, count=1)
    if count != 1:
        raise RuntimeError('Cannot set application version in the staged updater module.')
    updater.write_text(versioned, encoding='utf-8')

    entry = staged / 'YouSnipe.py'
    text = entry.read_text(encoding='utf-8')
    text = re.sub(r'YouSnipe \d+\.\d+\.\d+ CLI-first downloader',
                  'YouSnipe ' + version + ' CLI-first downloader', text)
    entry.write_text(text, encoding='utf-8')
    return entry


def target_architecture(target_os, target_arch):
    system = platform.system()
    machine = platform.machine().lower()
    arch = {'amd64': 'x86_64', 'x64': 'x86_64', 'x86_64': 'x86_64',
            'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine, machine)
    if system != target_os or arch != target_arch:
        raise RuntimeError('Run on native ' + target_os + ' ' + target_arch +
                           ', detected ' + system + ' ' + machine + '. Cross-compiling disabled.')


def prepare(root, target_os, target_arch, args):
    cache = Path.home() / '.cache' / 'ProjectHomelab' / 'YouSnipe' / (target_os + '_' + target_arch)
    work = cache / 'work'
    if args.clean_cache and cache.exists():
        shutil.rmtree(cache)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    return cache, work


def build_python(cache, system):
    envdir = cache / 'venv'
    python_exe = envdir / ('Scripts/python.exe' if system == 'Windows' else 'bin/python')
    if not python_exe.is_file():
        show('SETUP', 'Creating isolated build environment')
        venv.create(str(envdir), with_pip=True)
    run([python_exe, '-m', 'pip', 'install', '--disable-pip-version-check',
         'pyinstaller==' + PYINSTALLER_VERSION,
         'Pillow==' + PILLOW_VERSION,
         'websockets==' + WEBSOCKETS_VERSION], live=True)

    run([python_exe, '-c', 'from PIL import Image, ImageTk; import websockets, tkinter'])
    return python_exe


def icon_path(root, work, suffix):
    name = 'Icon_YouSnipe.' + suffix
    for ancestor in (root, *root.parents):
        for path in (ancestor / name,
                     ancestor / 'Resources' / 'Icons' / 'Features' / 'YouSnipe' / name):
            if path.is_file():
                validate_icon(path, suffix)
                return path
    path = work / name
    request = urllib.request.Request(ICON_ROOT + name, headers={'User-Agent': 'YouSnipeBuild/1.0.0'})
    show('DOWNLOAD', ICON_ROOT + name)
    try:
        with urllib.request.urlopen(request, timeout=45) as remote, path.open('wb') as dest:
            shutil.copyfileobj(remote, dest)
    except Exception as exc:
        raise RuntimeError('Unable to find/download the YouSnipe icon from Resources/Icons/Features/YouSnipe') from exc
    validate_icon(path, suffix)
    return path


def validate_icon(path, suffix):
    with Path(path).open('rb') as handle:
        signature = handle.read(8)
    expected = b'\x00\x00\x01\x00' if suffix == 'ico' else b'\x89PNG\r\n\x1a\n'
    if not signature.startswith(expected):
        raise RuntimeError('Invalid ' + suffix + ' icon: ' + str(path))


def pyinstaller_binary(python, source, work, windows=False, icon=None):
    dist = work / 'dist'
    base = [python, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
            '--windowed' if windows else '--console', '--name', 'YouSnipe', '--distpath', dist,
            '--workpath', work / 'pyinstaller', '--specpath', work / 'spec',
            '--paths', str(source.parent),
            '--hidden-import', 'PIL.Image', '--hidden-import', 'PIL.ImageTk',
            '--hidden-import', 'PIL.ImageOps', '--hidden-import', 'websockets',
            '--hidden-import', 'websockets.exceptions',
            '--collect-submodules', 'websockets',
            '--hidden-import', 'YouSnipeGUI', '--hidden-import', 'YouSnipeServer']
    if windows:


        launcher = work / 'YouSnipeWindowsLauncher.py'
        launcher.write_text(WINDOWS_LAUNCHER, encoding='utf-8')
        base.extend(['--icon', icon, '--add-data', f'{icon}{os.pathsep}.',
                     '--hidden-import', 'YouSnipe'])
        base.append(launcher)
    else:
        base.append(source)
    run(base, cwd=source.parent, live=True)
    result = dist / ('YouSnipe.exe' if windows else 'YouSnipe')
    if not result.is_file() or result.stat().st_size == 0:
        raise RuntimeError('PyInstaller did not produce the expected stable executable.')
    if not windows:
        result.chmod(result.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return result


def smoke_test(binary, cwd, env=None):

    result = run([binary, '--help'], cwd=cwd, env=env, capture=True)
    if '--headless-server' not in (result.stdout or '') or '--install-dependencies' not in (result.stdout or ''):
        raise RuntimeError('Built YouSnipe did not expose the expected CLI modes.')


def create_release_zip(runtime, output, version, system, arch):
    expected = f'YouSnipe_{version}_{system}_{arch}.zip'
    if output.name != expected:
        raise RuntimeError('Release ZIP name does not match the manifest-generator format.')
    temp = output.with_suffix('.zip.tmp')
    temp.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as zf:


            zf.write(runtime, arcname='YouSnipe/' + runtime.name)
        with zipfile.ZipFile(temp) as zf:
            files = [i for i in zf.infolist() if not i.is_dir()]
            if len(files) != 1 or files[0].filename != 'YouSnipe/' + runtime.name or zf.testzip() is not None:
                raise RuntimeError('Release ZIP must contain YouSnipe/' + runtime.name + '.')
            with zf.open(files[0]) as stream:
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
                if digest.hexdigest() != sha256_file(runtime):
                    raise RuntimeError('Release archive executable SHA-256 mismatch.')
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)



def arguments():
    parser = argparse.ArgumentParser(description='Build YouSnipe from the containing version folder (native host only)')
    parser.add_argument('--clean-cache', action='store_true', help='Recreate the local build venv and tool cache')
    parser.add_argument('--keep-work', action='store_true', help='Keep intermediate AppDir/spec/dist files')
    parser.add_argument('--verbose', action='store_true', help='Show detailed commands and diagnostics')
    return parser.parse_args()


def main():
    args = arguments()
    global VERBOSE
    VERBOSE = args.verbose
    root, version, source = root_and_version()
    target_architecture('Windows', 'x86_64')
    cache, work = prepare(root, 'Windows', 'x86_64', args)
    try:
        icon = icon_path(root, work, 'ico')
        release = root / f'YouSnipe_{version}_Windows_x86_64.zip'

        print()
        print(f'YouSnipe Windows x86_64 Build Tool {BUILDER_VERSION}')
        print('=' * 40)
        show('SOURCE', source.name)
        show('VERSION', version)
        show('ICON', icon.name if icon.parent == root else
             ('Local ProjectHomelab' if icon.exists() and icon.parent != work else 'GitHub fallback'))
        show('TARGET', 'Windows_x86_64')
        print()

        python = build_python(cache, 'Windows')

        show('BUILD', 'Preparing versioned source')
        staged_source = stage_source(root, work, version)

        show('BUILD', 'PyInstaller EXE')
        binary = pyinstaller_binary(python, staged_source, work, windows=True, icon=icon)

        show('TEST', 'Compiled YouSnipe.exe')
        smoke_test(binary, work)

        show('BUILD', release.name)
        create_release_zip(binary, release, version, 'Windows', 'x86_64')

        print()
        print('=' * 40)
        print('READY TO REVIEW')
        print('=' * 40)
        print(f'ZIP: {release.name}')
        print()
        print('ZIP SHA-256:')
        print(sha256_file(release))
        print('ZIP bytes:')
        print(release.stat().st_size)
        print()
        print('Contained EXE:')
        print('YouSnipe/' + binary.name)
        print('EXE SHA-256:')
        print(sha256_file(binary))
        print('EXE bytes:')
        print(binary.stat().st_size)
    finally:
        if not args.keep_work and work.exists():
            shutil.rmtree(work)
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nBuild cancelled.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print('\nBUILD FAILED: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
