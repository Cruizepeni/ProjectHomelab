from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _data_home() -> Path:
    location = os.environ.get('XDG_DATA_HOME')
    if location:
        return Path(location).expanduser().resolve()
    return Path.home() / '.local' / 'share'


def _runtime_image() -> Path:
    if not sys.platform.startswith('linux') or not getattr(sys, 'frozen', False):
        raise RuntimeError('Desktop registration requires the compiled Linux AppImage.')
    value = os.environ.get('APPIMAGE')
    if not value:
        raise RuntimeError('Run --install-desktop from the YouSnipe.AppImage file.')
    target = Path(value).expanduser().resolve()
    if not target.is_file() or target.suffix != '.AppImage':
        raise RuntimeError('The AppImage executable was not found: ' + str(target))
    return target


def _icon_source() -> Path:
    appdir = os.environ.get('APPDIR')
    bases = []
    if appdir:
        directory = Path(appdir)
        bases.extend((directory, directory / 'usr' / 'share' / 'icons' / 'hicolor' / '256x256' / 'apps'))
    bases.extend((Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)),
                  Path(__file__).resolve().parent))
    for base in bases:
        for name in ('yousnipe.png', 'Icon_YouSnipe.png'):
            path = base / name
            if path.is_file():
                return path
    raise RuntimeError('The AppImage does not contain the YouSnipe PNG icon.')


def _exec_path(path: Path) -> str:
    value = str(path)
    if '\n' in value or '\r' in value:
        raise RuntimeError('Invalid AppImage path for desktop integration.')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    return '"' + value + '"'


def _write_if_changed(path: Path, content: bytes) -> bool:
    try:
        if path.is_file() and path.read_bytes() == content:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    try:
        temporary.write_bytes(content)
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _refresh_desktop(applications: Path, icons: Path) -> None:
    for command in (('update-desktop-database', str(applications)),
                    ('gtk-update-icon-cache', '-f', '-t', str(icons))):
        executable = shutil.which(command[0])
        if not executable:
            continue
        try:
            subprocess.run([executable, *command[1:]], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _register_desktop(image: Path) -> str:
    from PIL import Image
    from io import BytesIO

    destination = _data_home()
    applications = destination / 'applications'
    icon_root = destination / 'icons' / 'hicolor'
    icon = icon_root / '256x256' / 'apps' / 'yousnipe.png'
    desktop = applications / 'yousnipe.desktop'
    with Image.open(_icon_source()) as original:
        original = original.convert('RGBA')
        original.thumbnail((256, 256), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
        canvas.alpha_composite(original, ((256 - original.width) // 2,
                                          (256 - original.height) // 2))
        contents = BytesIO()
        canvas.save(contents, format='PNG')
    changed = _write_if_changed(icon, contents.getvalue())
    entries = ('[Desktop Entry]', 'Type=Application', 'Name=YouSnipe',
               'Comment=ProjectHomelab YouSnipe Downloader',
               'Exec=' + _exec_path(image), 'TryExec=' + str(image),
               'Icon=' + str(icon), 'Terminal=false', 'Categories=AudioVideo;Video;',
               'StartupWMClass=YouSnipe', 'StartupNotify=true', '')
    changed = _write_if_changed(desktop, '\n'.join(entries).encode('utf-8')) or changed
    if changed:
        _refresh_desktop(applications, icon_root)
    return 'YouSnipe desktop entry installed: ' + str(desktop)


def install_desktop() -> str:
    return _register_desktop(_runtime_image())


def ensure_linux_desktop_integration() -> bool:
    if not sys.platform.startswith('linux') or not os.environ.get('APPIMAGE'):
        return False
    try:
        _register_desktop(_runtime_image())
        return True
    except (OSError, RuntimeError, ValueError, ImportError):
        return False


def remove_desktop() -> str:
    if not sys.platform.startswith('linux'):
        raise RuntimeError('Desktop integration is supported on Linux only.')
    directory = _data_home()
    applications = directory / 'applications'
    icons = directory / 'icons' / 'hicolor'
    desktop = applications / 'yousnipe.desktop'
    icon = icons / '256x256' / 'apps' / 'yousnipe.png'
    changed = desktop.is_file() or icon.is_file()
    desktop.unlink(missing_ok=True)
    icon.unlink(missing_ok=True)
    if changed:
        _refresh_desktop(applications, icons)
    return 'YouSnipe desktop entry removed.'
