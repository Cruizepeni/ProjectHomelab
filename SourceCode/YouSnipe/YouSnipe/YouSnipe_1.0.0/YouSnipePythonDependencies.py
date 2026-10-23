from __future__ import annotations

import importlib
import os
import platform
import subprocess
import sys
from pathlib import Path

from YouSnipePaths import APP_ROOT


REQUIREMENTS = {
    'Pillow': ('Pillow>=10,<14', ('PIL.Image', 'PIL.ImageOps', 'PIL.ImageTk')),
    'websockets': ('websockets>=13,<18', ('websockets', 'websockets.exceptions')),
}


def _platform_key() -> str:
    system = platform.system() or 'Unknown'
    machine = (platform.machine() or 'unknown').casefold()
    if machine in ('x86_64', 'amd64', 'x64'):
        architecture = 'x86_64'
    elif machine in ('arm64', 'aarch64'):
        architecture = 'arm64'
    elif machine in ('x86', 'i386', 'i686'):
        architecture = 'x86'
    else:
        architecture = machine.replace(' ', '_')
    return f'{system}_{architecture}'


def python_package_directory() -> Path:
    version = f'Python_{sys.version_info.major}.{sys.version_info.minor}'
    destination = APP_ROOT / 'Dependencies' / 'Python' / _platform_key() / version


    legacy = APP_ROOT / 'Dependencies' / 'YouSnipe' / 'Python' / _platform_key() / version
    if not destination.exists() and legacy.is_dir():
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(destination)

            for parent in (legacy.parent, legacy.parent.parent):
                try:
                    parent.rmdir()
                except OSError:
                    break
        except OSError:


            pass
    return destination


def activate_python_packages() -> Path:
    directory = python_package_directory()
    if getattr(sys, 'frozen', False):
        return directory
    if directory.is_dir():
        path = str(directory)
        if path not in sys.path:
            sys.path.insert(0, path)
    return directory


def package_available(name: str) -> bool:
    if name not in REQUIREMENTS:
        raise ValueError('Unknown Python dependency: ' + str(name))
    activate_python_packages()
    for module in REQUIREMENTS[name][1]:
        try:
            importlib.import_module(module)
        except (ImportError, OSError, RuntimeError):
            return False
    return True


def _refresh_installed_imports(names: list[str]) -> None:
    prefixes = {'Pillow': 'PIL', 'websockets': 'websockets'}
    for name in names:
        prefix = prefixes[name]
        for loaded in tuple(sys.modules):
            if loaded == prefix or loaded.startswith(prefix + '.'):
                sys.modules.pop(loaded, None)
    importlib.invalidate_caches()
    activate_python_packages()


def missing_python_packages(gui: bool = False, server: bool = False, all_packages: bool = False) -> list[str]:
    if getattr(sys, 'frozen', False):
        return []
    packages = list(REQUIREMENTS) if all_packages else (
        (['Pillow'] if gui else []) + (['websockets'] if server else [])
    )
    return [name for name in packages if not package_available(name)]


def _run(command: list[str]) -> subprocess.CompletedProcess:
    kwargs = {'capture_output': True, 'text': True, 'check': False, 'timeout': 300}
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return subprocess.run(command, **kwargs)


def _ensure_pip() -> None:
    check = _run([sys.executable, '-m', 'pip', '--version'])
    if check.returncode == 0:
        return
    ready = _run([sys.executable, '-m', 'ensurepip', '--upgrade'])
    if ready.returncode != 0:
        raise RuntimeError(
            'Python pip is unavailable and ensurepip failed. Install pip for ' + sys.executable +
            '. ' + (ready.stderr or ready.stdout or '').strip()[-1200:]
        )


def install_python_packages(packages: list[str], progress=None) -> list[dict]:
    if not packages or getattr(sys, 'frozen', False):
        return []
    unknown = set(packages) - set(REQUIREMENTS)
    if unknown:
        raise ValueError('Unsupported Python packages: ' + ', '.join(sorted(unknown)))
    missing = [name for name in dict.fromkeys(packages) if not package_available(name)]
    if not missing:
        return []
    destination = python_package_directory()
    destination.mkdir(parents=True, exist_ok=True)
    if progress:
        progress({'dependency': 'Python packages', 'stage': 'installing',
                  'dependencyIndex': 1, 'dependencyCount': 1})
    _ensure_pip()
    command = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
               '--no-input', '--target', str(destination),
               *(REQUIREMENTS[name][0] for name in missing)]
    result = _run(command)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or 'Unknown pip failure').strip()
        raise RuntimeError('YouSnipe could not install Python dependencies: ' + details[-2400:])
    _refresh_installed_imports(missing)
    failed = []
    for name in missing:
        for module in REQUIREMENTS[name][1]:
            try:
                importlib.import_module(module)
            except (ImportError, OSError, RuntimeError) as exc:
                failed.append(f'{name} ({module}): {type(exc).__name__}: {exc}')
                break
    if failed:
        raise RuntimeError('Python dependencies installed but could not import: ' + '; '.join(failed))
    if progress:
        progress({'dependency': 'Python packages', 'stage': 'complete',
                  'dependencyIndex': 1, 'dependencyCount': 1})
    return [{'dependency': name, 'version': 'Python package', 'path': str(destination)} for name in missing]


activate_python_packages()
