from __future__ import annotations

import os
import sys
from pathlib import Path


def _runtime_directory() -> Path:
    if getattr(sys, 'frozen', False):
        appimage = os.environ.get('APPIMAGE') if sys.platform.startswith('linux') else None
        executable = Path(appimage or sys.executable).expanduser().resolve()
        return executable.parent
    return Path(__file__).resolve().parent


SOURCE_DIR = _runtime_directory()
FEATURE_DIR = SOURCE_DIR


def find_project_root() -> Path | None:
    for directory in FEATURE_DIR.parents:
        if (directory / '.AppRoot').is_file():
            return directory
    return None


PROJECT_ROOT = find_project_root()
APP_ROOT = PROJECT_ROOT if PROJECT_ROOT is not None else FEATURE_DIR


def get_application_root() -> Path:
    return APP_ROOT


def _contains_yousnipe_data(path: Path) -> bool:
    return any((path / relative).is_file() for relative in (
        Path('Settings') / 'YouSnipeSettingsConfig.json',
        Path('settings') / 'YouSnipeSettingsConfig.json',
        Path('Database') / 'YouSnipe.db',
        Path('database') / 'YouSnipe.db',
    ))


def get_appdata_directory() -> Path:
    canonical = APP_ROOT / 'Appdata' / 'YouSnipe'
    if _contains_yousnipe_data(canonical):
        return canonical
    for legacy in (
        APP_ROOT / 'appdata' / 'YouSnipe',
        APP_ROOT / 'appdata',
        APP_ROOT / 'Appdata',
    ):
        if not _contains_yousnipe_data(legacy):
            continue
        if legacy.name == 'YouSnipe' and not canonical.exists():
            try:
                canonical.parent.mkdir(parents=True, exist_ok=True)
                legacy.rename(canonical)
                return canonical
            except OSError:
                return legacy
        return legacy
    return canonical


APPDATA_DIR = get_appdata_directory()


def appdata_subdirectory(name: str, parent: Path | None = None) -> Path:
    if not name or not name[0].isupper() or not name.isalpha():
        raise ValueError('Appdata subdirectory must have a capitalised name.')
    directory = Path(parent) if parent is not None else APPDATA_DIR
    canonical = directory / name
    previous = directory / name.lower()
    if canonical.is_dir():
        return canonical
    if previous.is_dir():
        try:
            previous.rename(canonical)
            return canonical
        except OSError:
            return previous
    return canonical


def _existing_workspace_dependencies() -> list[Path]:





    parents = [FEATURE_DIR, *list(FEATURE_DIR.parents)[:4], Path.home()]
    for key in ('PROJECTHOMELAB_ROOT', 'YOUSNIPE_ROOT'):
        raw = os.environ.get(key)
        if raw:
            parents.append(Path(raw).expanduser())
    home = Path.home()
    parents.extend((home / 'Desktop', home / 'Documents', home / 'Downloads'))
    for key in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial', 'USERPROFILE'):
        raw = os.environ.get(key)
        if raw:
            folder = Path(raw).expanduser()
            parents.extend((folder, folder / 'Desktop', folder / 'Documents'))

    found = []
    seen = set()
    for base in parents:
        candidates = (
            base, base / 'ProjectHomelab', base / 'YouSnipe',
            base / 'YouSnipe' / 'YouSnipe_1.0.0',
            base / 'YouSnipe' / 'YouSnipe' / 'YouSnipe_1.0.0',
            base / 'ProjectHomelab' / 'SourceCode' / 'YouSnipe' / 'YouSnipe' / 'YouSnipe_1.0.0',
        )
        for candidate in candidates:
            for directory in (candidate / 'Dependencies', candidate / 'dependencies'):
                identity = os.path.normcase(str(directory))
                if identity in seen:
                    continue
                seen.add(identity)
                try:
                    if directory.is_dir():
                        found.append(directory)
                except OSError:

                    continue
    return found


def dependency_directories() -> list[Path]:
    locations = [
        FEATURE_DIR / 'dependencies',
        FEATURE_DIR / 'Dependencies',
        FEATURE_DIR.parent / 'dependencies',
        FEATURE_DIR.parent / 'Dependencies',
        APP_ROOT / 'Dependencies' / 'YouSnipe',
        APP_ROOT / 'Dependencies',
        APP_ROOT / 'dependencies',
        APP_ROOT / 'Resources' / 'ThirdParty',
        APP_ROOT / 'Resources' / 'VendorTools',
        *_existing_workspace_dependencies(),
    ]
    return list(dict.fromkeys(locations))
