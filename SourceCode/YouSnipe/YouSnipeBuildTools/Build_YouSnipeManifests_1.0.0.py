import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

BUILDER_VERSION = '1.0.0'
RAW_BASE = 'https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main'
VERSION = re.compile(r'^\d+\.\d+\.\d+$')
PACKAGE = re.compile(r'^YouSnipe_(\d+\.\d+\.\d+)_(Windows|Linux)_(x86_64|arm64)\.zip$', re.IGNORECASE)
UPDATER_PACKAGE = re.compile(r'^YouSnipeUpdater_(\d+\.\d+\.\d+)_(Windows|Linux)_(x86_64|arm64)\.zip$', re.IGNORECASE)


def version_key(version):
    if not VERSION.fullmatch(str(version)):
        raise RuntimeError(f'Invalid version: {version}')
    return tuple(int(piece) for piece in str(version).split('.'))


def latest_versions(entries):
    return dict(sorted(entries.items(), key=lambda item: version_key(item[0]), reverse=True))


def hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('[WRITE]', path)


def record(path, directory, prefix):
    relative = path.relative_to(directory).as_posix()
    return {'file': path.name, 'path': relative, 'sha256': hash_file(path),
            'size_bytes': path.stat().st_size, 'download_url': f'{RAW_BASE}/{prefix}/{relative}'}


def source_files(folder):


    def is_source_file(entry):
        if not entry.is_file() or any(part.startswith('.') or part == '__pycache__'
                                     for part in entry.relative_to(folder).parts[:-1]):
            return False
        if entry.suffix in {'.pyc', '.pyo'}:
            return False
        name = entry.name
        if PACKAGE.fullmatch(name) or UPDATER_PACKAGE.fullmatch(name):
            return False
        if re.fullmatch(r'YouSnipe_\d+\.\d+\.\d+_(Windows|Linux)_(x86_64|arm64)_Build\.json', name, re.I):
            return False
        return True
    return sorted((entry for entry in folder.rglob('*') if is_source_file(entry)),
                  key=lambda entry: entry.as_posix().lower())


def build_application_source(root):
    folder = root / 'YouSnipe'
    if not folder.is_dir():
        raise RuntimeError('YouSnipe application source directory not found.')
    versions = {}
    for subfolder in sorted(folder.glob('YouSnipe_*')):
        if not subfolder.is_dir() or not VERSION.fullmatch(subfolder.name.removeprefix('YouSnipe_')):
            continue
        version = subfolder.name.removeprefix('YouSnipe_')
        if not (subfolder / 'YouSnipe.py').is_file():
            raise RuntimeError(f'{subfolder} is missing YouSnipe.py')
        versions[version] = {'folder': subfolder.relative_to(root).as_posix(), 'entry_point': 'YouSnipe.py',
                             'files': [record(path, root, 'SourceCode/YouSnipe') for path in source_files(subfolder)]}
    manifest = {'schema': 1, 'application': 'YouSnipe', 'component': 'Application Source',
                'latest_version': next(iter(latest_versions(versions)), None), 'versions': latest_versions(versions)}
    path = folder / 'YouSnipe_Manifest.json'
    save_json(path, manifest)
    return path


def build_updater_source(root):
    folder = root / 'YouSnipeUpdater'
    if not folder.is_dir():
        raise RuntimeError('YouSnipeUpdater source directory not found.')
    versions = {}
    for subfolder in sorted(folder.glob('YouSnipeUpdater_*')):
        if not subfolder.is_dir() or not VERSION.fullmatch(subfolder.name.removeprefix('YouSnipeUpdater_')):
            continue
        version = subfolder.name.removeprefix('YouSnipeUpdater_')
        source = subfolder / f'YouSnipeUpdater_{version}.py'
        if not source.is_file():
            raise RuntimeError(f'Missing updater source: {source.name}')
        versions[version] = {'compatibility_family': '.'.join(version.split('.')[:2]),
                             'source': record(source, root, 'SourceCode/YouSnipe')}
    path = folder / 'YouSnipeUpdater_Manifest.json'
    save_json(path, {'schema': 1, 'application': 'YouSnipe', 'component': 'YouSnipeUpdater Source',
                     'latest_version': next(iter(latest_versions(versions)), None), 'versions': latest_versions(versions)})
    return path


def build_tools_source(root):
    folder = root / 'YouSnipeBuildTools'
    if not folder.is_dir():
        raise RuntimeError('YouSnipeBuildTools source directory not found.')
    paths = sorted(folder.glob('*.py'))
    files = [record(path, root, 'SourceCode/YouSnipe') for path in paths]
    path = folder / 'YouSnipeBuildTools_Manifest.json'
    save_json(path, {'schema': 1, 'application': 'YouSnipe', 'component': 'YouSnipe Build Tools', 'files': files})
    return path


def build_source(root):
    elements = {'YouSnipe': build_application_source(root),
                'YouSnipeUpdater': build_updater_source(root),
                'YouSnipeBuildTools': build_tools_source(root)}
    save_json(root / 'YouSnipe_Source_Manifest.json', {
        'schema': 1, 'application': 'YouSnipe',
        'components': {key: {'manifest': record(value, root, 'SourceCode/YouSnipe')}
                       for key, value in elements.items()}})


def check_archive_runtime(package, runtime, updater=False):
    with zipfile.ZipFile(package) as archive:
        seen = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = str(info.filename).replace('\\', '/')
            parts = name.split('/')
            if (not name or name.startswith('/') or '\x00' in name or '..' in parts
                    or (parts[0].endswith(':') if parts else False)):
                raise RuntimeError(f'Unsafe archive path in {package.name}: {name}')
            if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
                raise RuntimeError(f'Archive contains a symlink: {package.name}')
            if PurePosixPath(name).name.casefold() == runtime.casefold():
                allowed = (runtime,) if updater else (runtime, 'YouSnipe/' + runtime)
                if name not in allowed:
                    raise RuntimeError(f"Release executable path is invalid: {name}.")
                seen.append(info)
        if len(seen) != 1:
            raise RuntimeError(f'{package.name} must contain exactly one {runtime} runtime.')
        digest = hashlib.sha256()
        total = 0
        with archive.open(seen[0]) as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                total += len(chunk)
        if not total:
            raise RuntimeError(f'Empty release executable in {package.name}')
        return digest.hexdigest(), total


def build_release_assets(root, pattern, updater=False):
    releases = {}
    for path in sorted(root.glob('*.zip')):
        match = pattern.fullmatch(path.name)
        if not match:
            continue
        version, system, architecture = match.groups()
        system = system.capitalize()
        architecture = architecture.lower()
        binary = ('YouSnipeUpdater' if updater else 'YouSnipe') + ('.exe' if system == 'Windows' else ('' if updater else '.AppImage'))
        binary_hash, binary_size = check_archive_runtime(path, binary, updater=updater)
        key = f'{system}_{architecture}'
        entry = releases.setdefault(version, {'compatibility_family': '.'.join(version.split('.')[:2]), 'assets': {}})
        if key in entry['assets']:
            raise RuntimeError(f'Duplicate release package: {key} {version}')
        asset = record(path, root, 'Resources/FirstParty/YouSnipe/YouSnipeUpdater' if updater else 'Releases/YouSnipe')
        entry['assets'][key] = {'file': asset['file'], 'download_url': asset['download_url'],
                                'sha256': asset['sha256'], 'size_bytes': asset['size_bytes'],
                                'executable': binary, 'executable_sha256': binary_hash,
                                'executable_size_bytes': binary_size}
    return latest_versions(releases)


def build_releases(root):
    releases = build_release_assets(root, PACKAGE)
    save_json(root / 'YouSnipe_Release_Manifest.json', {
        'schema': 1, 'application': 'YouSnipe',
        'latest_version': next(iter(releases), None), 'releases': releases})


def build_resources(root):
    folder = root / 'YouSnipeUpdater'
    folder.mkdir(parents=True, exist_ok=True)
    versions = build_release_assets(folder, UPDATER_PACKAGE, updater=True)
    save_json(folder / 'YouSnipeUpdater_Release_Manifest.json', {
        'schema': 1, 'application': 'YouSnipe', 'component': 'YouSnipeUpdater',
        'latest_version': next(iter(versions), None), 'versions': versions})
    path = root / 'YouSnipe_Resources_Manifest.json'
    save_json(path, {'schema': 1, 'application': 'YouSnipe', 'components': {'YouSnipeUpdater': {
        'manifest': record(folder / 'YouSnipeUpdater_Release_Manifest.json', root,
                           'Resources/FirstParty/YouSnipe')}}})


def main():
    parser = argparse.ArgumentParser(prog='Build_YouSnipeManifests')
    parser.add_argument('--version', action='store_true')
    args = parser.parse_args()
    if args.version:
        print('Build_YouSnipeManifests ' + BUILDER_VERSION)
        return 0
    root = Path(__file__).resolve().parent
    if (root / 'YouSnipe').is_dir() and (root / 'YouSnipeUpdater').is_dir() and (root / 'YouSnipeBuildTools').is_dir():
        build_source(root)
    elif root.name == 'YouSnipe' and root.parent.name == 'Releases':
        build_releases(root)
    elif root.name == 'YouSnipe' and root.parent.name == 'FirstParty' and root.parent.parent.name == 'Resources':
        build_resources(root)
    else:
        raise RuntimeError('Copy this build tool into SourceCode/YouSnipe, Releases/YouSnipe or Resources/FirstParty/YouSnipe.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('MANIFEST BUILD FAILED: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
