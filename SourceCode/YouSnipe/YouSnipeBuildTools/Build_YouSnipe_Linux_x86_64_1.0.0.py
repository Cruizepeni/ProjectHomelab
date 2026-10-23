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



VERBOSE = False


def show(label, value=''):

    print(f'[{label}] {value}' if value else f'[{label}]', flush=True)


def run(command, cwd=None, env=None, capture=False):

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
         'websockets==' + WEBSOCKETS_VERSION])

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
            '--console', '--name', 'YouSnipe', '--distpath', dist,
            '--workpath', work / 'pyinstaller', '--specpath', work / 'spec',
            '--hidden-import', 'PIL.Image', '--hidden-import', 'PIL.ImageTk',
            '--hidden-import', 'PIL.ImageOps', '--hidden-import', 'PIL.JpegImagePlugin',
            '--hidden-import', 'PIL.PngImagePlugin', '--collect-all', 'PIL',
            '--hidden-import', 'websockets',
            '--hidden-import', 'websockets.exceptions',
            '--collect-submodules', 'websockets',
            '--hidden-import', 'YouSnipeGUI', '--hidden-import', 'YouSnipeServer']
    if windows:
        base.extend(['--icon', icon])
    elif icon is not None:
        base.extend(['--add-data', f'{icon}{os.pathsep}.'])
    base.append(source)
    run(base, cwd=source.parent)
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
    result = run([binary, '--check-image-support'], cwd=cwd, env=env, capture=True)
    if 'Pillow JPEG/PNG and ImageTk: OK' not in (result.stdout or ''):
        raise RuntimeError('Bundled Pillow does not support thumbnails: ' + (result.stdout or ''))


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
    parser.add_argument('--verbose', action='store_true', help='Show detailed build-tool output')
    return parser.parse_args()


APPIMAGETOOL_VERSION = '1.9.1'
APPIMAGE_RUNTIME_BUILD = '20251108'


def pinned_appimage_assets(arch):
    assets = {
        'x86_64': {
            'tool': {'url': 'https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage',
                     'sha256': 'ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0',
                     'size_bytes': 15092216},
            'runtime': {'url': 'https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64',
                        'sha256': '2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d',
                        'size_bytes': 944632},
        },
        'arm64': {
            'tool': {'url': 'https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-aarch64.AppImage',
                     'sha256': 'f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158',
                     'size_bytes': 14678536},
            'runtime': {'url': 'https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-aarch64',
                        'sha256': '00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444',
                        'size_bytes': 936456},
        },
    }
    return assets[arch]


def verified_tool(cache, asset, filename, executable=False):
    target = cache / 'tools' / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and (target.stat().st_size != asset['size_bytes'] or
                             sha256_file(target) != asset['sha256']):
        target.unlink()
    if not target.is_file():
        temp = target.with_suffix(target.suffix + '.download')
        temp.unlink(missing_ok=True)
        request = urllib.request.Request(asset['url'], headers={'User-Agent': 'YouSnipeBuild/1.0.0'})
        try:
            show('DOWNLOAD', 'Verified AppImage component: ' + filename)
            with urllib.request.urlopen(request, timeout=120) as remote, temp.open('wb') as output:
                shutil.copyfileobj(remote, output)
            if temp.stat().st_size != asset['size_bytes'] or sha256_file(temp) != asset['sha256']:
                raise RuntimeError('Pinned download checksum or size mismatch: ' + filename)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
    if executable:
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def png_icon(python, original, work):
    output = work / 'Icon_YouSnipe_256.png'
    script = ('from PIL import Image; import sys; '
              'im=Image.open(sys.argv[1]).convert("RGBA"); '
              'im.thumbnail((256,256), Image.Resampling.LANCZOS); '
              'canvas=Image.new("RGBA",(256,256),(0,0,0,0)); '
              'canvas.alpha_composite(im,((256-im.width)//2,(256-im.height)//2)); '
              'canvas.save(sys.argv[2],format="PNG")')
    run([python, '-c', script, original, output])
    validate_icon(output, 'png')
    return output


def appdir_create(binary, icon, work, version):
    folder = work / 'YouSnipe.AppDir'
    if folder.exists():
        shutil.rmtree(folder)
    bindir = folder / 'usr' / 'bin'
    apps = folder / 'usr' / 'share' / 'applications'
    icons = folder / 'usr' / 'share' / 'icons' / 'hicolor' / '256x256' / 'apps'
    for path in (bindir, apps, icons):
        path.mkdir(parents=True, exist_ok=True)
    deployed = bindir / 'YouSnipe'
    shutil.copy2(binary, deployed)
    deployed.chmod(deployed.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    shutil.copy2(icon, folder / 'yousnipe.png')
    shutil.copy2(icon, icons / 'yousnipe.png')
    desktop = '\n'.join(('[Desktop Entry]', 'Type=Application', 'Name=YouSnipe',
                         'Comment=ProjectHomelab YouSnipe downloader', 'Exec=YouSnipe',
                         'Icon=yousnipe', 'Terminal=false', 'Categories=AudioVideo;Video;',
                         'StartupWMClass=YouSnipe', 'StartupNotify=true',
                         f'X-AppImage-Version={version}', ''))
    (folder / 'yousnipe.desktop').write_text(desktop, encoding='utf-8')
    (apps / 'yousnipe.desktop').write_text(desktop, encoding='utf-8')
    (folder / '.DirIcon').symlink_to('yousnipe.png')
    launch = folder / 'AppRun'


    launch.write_text('#!/bin/sh\nexec "$APPDIR/usr/bin/YouSnipe" "$@"\n', encoding='utf-8')
    launch.chmod(launch.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return folder


def appimage_build(cache, work, appdir, version, arch):
    assets = pinned_appimage_assets(arch)
    tool_arch = 'aarch64' if arch == 'arm64' else 'x86_64'
    tool = verified_tool(cache, assets['tool'], f'appimagetool-{tool_arch}.AppImage', executable=True)
    runtime = verified_tool(cache, assets['runtime'], f'runtime-{tool_arch}')
    output = work / 'YouSnipe.AppImage'
    env = dict(os.environ, ARCH=tool_arch, VERSION=version, APPIMAGE_EXTRACT_AND_RUN='1')
    run([tool, '--runtime-file', runtime, '--no-appstream', appdir, output], cwd=work, env=env)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError('AppImage was not created.')
    output.chmod(output.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    offset_result = run([output, '--appimage-offset'], cwd=work, capture=True,
                        env=dict(os.environ, APPIMAGE_EXTRACT_AND_RUN='1'))
    try:
        offset = int(offset_result.stdout.strip())
    except (ValueError, AttributeError) as exc:
        raise RuntimeError('The AppImage runtime did not report a valid filesystem offset.') from exc
    if offset <= 0 or offset + 4 > output.stat().st_size:
        raise RuntimeError('The AppImage filesystem offset is outside the file.')
    with output.open('rb') as image:
        header = image.read(11)
        image.seek(offset)
        squashfs_magic = image.read(4)
    if header[:4] != b'\x7fELF' or header[8:11] != b'AI\x02':
        raise RuntimeError('The built file is not a valid type-2 AppImage runtime.')
    if squashfs_magic != b'hsqs':
        raise RuntimeError('The AppImage filesystem is missing or invalid.')
    return output

TARGET_ARCH = 'x86_64'


def main():
    args = arguments()
    global VERBOSE
    VERBOSE = args.verbose
    root, version, source = root_and_version()
    target_architecture('Linux', TARGET_ARCH)
    cache, work = prepare(root, 'Linux', TARGET_ARCH, args)
    try:
        release = root / f'YouSnipe_{version}_Linux_{TARGET_ARCH}.zip'

        print()
        print(f'YouSnipe Linux {TARGET_ARCH} Build Tool {BUILDER_VERSION}')
        print('=' * 40)
        show('SOURCE', source.name)
        show('VERSION', version)
        show('TARGET', 'Linux_' + TARGET_ARCH)
        print()

        python = build_python(cache, 'Linux')
        icon_source = icon_path(root, work, 'png')
        show('ICON', icon_source.name)
        icon = png_icon(python, icon_source, work)

        show('BUILD', 'Preparing versioned source')
        staged_source = stage_source(root, work, version)

        show('BUILD', 'PyInstaller ELF')
        binary = pyinstaller_binary(python, staged_source, work, icon=icon_source)
        show('TEST', 'PyInstaller ELF')
        smoke_test(binary, work)

        show('BUILD', 'YouSnipe AppImage')
        appdir = appdir_create(binary, icon, work, version)
        image = appimage_build(cache, work, appdir, version, TARGET_ARCH)
        show('TEST', 'YouSnipe AppImage')
        extracted_env = dict(os.environ, APPIMAGE_EXTRACT_AND_RUN='1')
        smoke_test(image, work, extracted_env)

        show('BUILD', release.name)
        create_release_zip(image, release, version, 'Linux', TARGET_ARCH)

        print()
        print('=' * 40)
        print('READY TO REVIEW')
        print('=' * 40)
        print('ZIP: ' + release.name)
        print()
        print('ZIP SHA-256:')
        print(sha256_file(release))
        print('ZIP bytes:')
        print(release.stat().st_size)
        print()
        print('Contained AppImage:')
        print('YouSnipe/' + image.name)
        print('AppImage SHA-256:')
        print(sha256_file(image))
        print('AppImage bytes:')
        print(image.stat().st_size)
    finally:
        if not args.keep_work and work.exists():
            shutil.rmtree(work)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Build cancelled.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print('BUILD FAILED: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
