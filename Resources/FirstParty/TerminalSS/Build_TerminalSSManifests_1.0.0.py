import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

BUILDER_VERSION = "1.0.0"
RAW_ROOT = "https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main"
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
APP_RELEASE_PATTERN = re.compile(
    r"^TerminalSS_(\d+\.\d+\.\d+)_(Windows|Linux|macOS)_(x86_64|arm64|Universal)\.zip$",
    re.IGNORECASE,
)
UPDATER_RELEASE_PATTERN = re.compile(
    r"^TerminalSSUpdater_(\d+\.\d+\.\d+)_(Windows|Linux|macOS)_(x86_64|arm64|Universal)\.zip$",
    re.IGNORECASE,
)
APP_BUILD_TOOL_PATTERN = re.compile(
    r"^Build_TerminalSS_(Windows|Linux|macOS)_(x86_64|arm64|Universal)_(\d+\.\d+\.\d+)\.py$",
    re.IGNORECASE,
)
UPDATER_BUILD_TOOL_PATTERN = re.compile(
    r"^Build_TerminalSSUpdater_(Windows|Linux|macOS)_(x86_64|arm64|Universal)_(\d+\.\d+\.\d+)\.py$",
    re.IGNORECASE,
)
MANIFEST_BUILD_TOOL_PATTERN = re.compile(
    r"^Build_TerminalSSManifests_(\d+\.\d+\.\d+)\.py$",
    re.IGNORECASE,
)
ASSET_SPECS = (
    {
        "folder": "CharacterIndex",
        "prefix": "CharacterIndex",
        "source_manifest": "CharacterIndex_Manifest.json",
        "release_manifest": "CharacterIndex_Release_Manifest.json",
        "component": "CharacterIndex",
        "router_key": "CharacterIndex",
        "protocol": None,
    },
    {
        "folder": "MatrixProtocol",
        "prefix": "MatrixAssetsPack",
        "source_manifest": "MatrixAssets_Manifest.json",
        "release_manifest": "MatrixAssets_Release_Manifest.json",
        "component": "Matrix Assets",
        "router_key": "MatrixProtocol",
        "protocol": "Matrix",
    },
    {
        "folder": "AlienProtocol",
        "prefix": "AlienAssetsPack",
        "source_manifest": "AlienAssets_Manifest.json",
        "release_manifest": "AlienAssets_Release_Manifest.json",
        "component": "Alien Assets",
        "router_key": "AlienProtocol",
        "protocol": "Alien",
    },
    {
        "folder": "DNAProtocol",
        "prefix": "DNAAssetsPack",
        "source_manifest": "DNAAssets_Manifest.json",
        "release_manifest": "DNAAssets_Release_Manifest.json",
        "component": "DNA Assets",
        "router_key": "DNAProtocol",
        "protocol": "DNA",
    },
    {
        "folder": "HackerProtocol",
        "prefix": "HackerAssetsPack",
        "source_manifest": "HackerAssets_Manifest.json",
        "release_manifest": "HackerAssets_Release_Manifest.json",
        "component": "Hacker Assets",
        "router_key": "HackerProtocol",
        "protocol": "Hacker",
    },
    {
        "folder": "ArcaneProtocol",
        "prefix": "ArcaneAssetsPack",
        "source_manifest": "ArcaneAssets_Manifest.json",
        "release_manifest": "ArcaneAssets_Release_Manifest.json",
        "component": "Arcane Assets",
        "router_key": "ArcaneProtocol",
        "protocol": "Arcane",
    },
)


def show(label, value=""):
    if value:
        print(f"[{label}] {value}")
    else:
        print(f"[{label}]")


def version_key(value):
    value = str(value or "").strip()
    if not VERSION_PATTERN.fullmatch(value):
        raise RuntimeError(f"Invalid version value: {value}")
    return tuple(int(part) for part in value.split("."))


def latest_version(values):
    values = list(values)
    if not values:
        return None
    return max(values, key=version_key)


def compatibility_family(version):
    major, minor, _ = version_key(version)
    return f"{major}.{minor}"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.write_bytes(encoded)
    show("WRITE", path.name)


def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Could not read JSON manifest: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Manifest root must be an object: {path}")
    return data


def raw_url(repo_prefix, relative_path):
    return f"{RAW_ROOT}/{repo_prefix.strip('/')}/{str(relative_path).replace('\\\\', '/').lstrip('/')}"


def relative_record(path, base, repo_prefix):
    path = Path(path)
    relative = path.relative_to(base).as_posix()
    return {
        "file": path.name,
        "path": relative,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "download_url": raw_url(repo_prefix, relative),
    }


def ignored_source_path(path):
    path = Path(path)
    names = {part.casefold() for part in path.parts}
    if "__pycache__" in names:
        return True
    if path.name in (".DS_Store", "Thumbs.db"):
        return True
    if path.suffix.casefold() in (".pyc", ".pyo"):
        return True
    return False


def source_files(folder):
    return sorted(
        (
            path
            for path in Path(folder).rglob("*")
            if path.is_file() and not ignored_source_path(path)
        ),
        key=lambda path: path.as_posix(),
    )


def version_from_folder(name, prefix):
    marker = prefix + "_"
    if not name.startswith(marker):
        return None
    version = name[len(marker):]
    if not VERSION_PATTERN.fullmatch(version):
        return None
    return version


def find_named_ancestor(path, name):
    path = Path(path).resolve()
    for candidate in (path, *path.parents):
        if candidate.name.casefold() == name.casefold():
            return candidate
    return None


def detect_environment(root):
    root = Path(root).resolve()
    resources = find_named_ancestor(root, "Resources")
    first_party = find_named_ancestor(root, "FirstParty")
    source_code = find_named_ancestor(root, "SourceCode")
    releases = find_named_ancestor(root, "Releases")

    if first_party and resources and first_party.parent == resources:
        return "resources"
    if source_code:
        return "source"
    if releases:
        return "releases"

    if (root / "TerminalSSBuildTools").is_dir() and (root / "TerminalSS").is_dir():
        return "source"
    if (root / "TerminalSS_Resources_Manifest.json").is_file():
        return "resources"
    if (root / "TerminalSS_Release_Manifest.json").is_file():
        return "releases"
    if any(root.glob("TerminalSS_*_*.zip")):
        return "releases"

    raise RuntimeError(
        "Could not determine manifest environment. Copy this tool into SourceCode/TerminalSS, Resources/FirstParty/TerminalSS, or Releases/TerminalSS before running it."
    )


def build_source_application_manifest(root):
    application_root = root / "TerminalSS"
    if not application_root.is_dir():
        raise RuntimeError("TerminalSS application source folder is missing.")

    versions = {}
    for folder in sorted(application_root.iterdir(), key=lambda path: path.name.casefold()):
        if not folder.is_dir():
            continue
        version = version_from_folder(folder.name, "TerminalSS")
        if not version:
            continue
        entry_point = folder / "TerminalSS.py"
        if not entry_point.is_file():
            raise RuntimeError(f"{folder.name} does not contain TerminalSS.py.")
        versions[version] = {
            "folder": folder.relative_to(root).as_posix(),
            "entry_point": "TerminalSS.py",
            "files": [
                relative_record(path, root, "SourceCode/TerminalSS")
                for path in source_files(folder)
            ],
        }

    manifest = {
        "schema": 1,
        "application": "TerminalSS",
        "component": "Application Source",
        "latest_version": latest_version(versions),
        "versions": dict(sorted(versions.items(), key=lambda item: version_key(item[0]))),
    }
    path = application_root / "TerminalSS_Manifest.json"
    write_json(path, manifest)
    return path


def build_source_updater_manifest(root):
    updater_root = root / "TerminalSSUpdater"
    if not updater_root.is_dir():
        raise RuntimeError("TerminalSSUpdater source folder is missing.")

    versions = {}
    for folder in sorted(updater_root.iterdir(), key=lambda path: path.name.casefold()):
        if not folder.is_dir():
            continue
        version = version_from_folder(folder.name, "TerminalSSUpdater")
        if not version:
            continue
        source = folder / f"TerminalSSUpdater_{version}.py"
        if not source.is_file():
            raise RuntimeError(f"{folder.name} does not contain {source.name}.")
        versions[version] = {
            "source": relative_record(source, root, "SourceCode/TerminalSS")
        }

    manifest = {
        "schema": 1,
        "application": "TerminalSS",
        "component": "TerminalSSUpdater Source",
        "latest_version": latest_version(versions),
        "versions": dict(sorted(versions.items(), key=lambda item: version_key(item[0]))),
    }
    path = updater_root / "TerminalSSUpdater_Manifest.json"
    write_json(path, manifest)
    return path


def validate_source_asset_folder(spec, folder, version):
    if any(part.name.casefold() == "custom" for part in folder.rglob("*") if part.is_dir()):
        raise RuntimeError(f"Source asset pack contains a Custom folder: {folder}")
    if spec["folder"] == "CharacterIndex":
        expected = folder / f"CharacterIndex_{version}.json"
        if not expected.is_file():
            raise RuntimeError(f"CharacterIndex {version} is missing {expected.name}.")


def build_source_asset_manifests(root):
    assets_root = root / "TerminalSSAssets"
    if not assets_root.is_dir():
        raise RuntimeError("TerminalSSAssets source folder is missing.")

    paths = {}
    for spec in ASSET_SPECS:
        component_root = assets_root / spec["folder"]
        if not component_root.is_dir():
            raise RuntimeError(f"Asset source folder is missing: {component_root}")

        versions = {}
        for folder in sorted(component_root.iterdir(), key=lambda path: path.name.casefold()):
            if not folder.is_dir():
                continue
            version = version_from_folder(folder.name, spec["prefix"])
            if not version:
                continue
            validate_source_asset_folder(spec, folder, version)
            versions[version] = {
                "compatibility_family": compatibility_family(version),
                "folder": folder.relative_to(root).as_posix(),
                "files": [
                    relative_record(path, root, "SourceCode/TerminalSS")
                    for path in source_files(folder)
                ],
            }

        manifest = {
            "schema": 1,
            "application": "TerminalSS",
            "component": spec["component"],
            "latest_version": latest_version(versions),
            "versions": dict(sorted(versions.items(), key=lambda item: version_key(item[0]))),
        }
        if spec["protocol"] is not None:
            manifest["protocol"] = spec["protocol"]

        path = component_root / spec["source_manifest"]
        write_json(path, manifest)
        paths[spec["router_key"]] = path

    router = {
        "schema": 1,
        "application": "TerminalSS",
        "component": "TerminalSS Assets Source",
        "assets": {
            spec["router_key"]: {
                "manifest": relative_record(
                    paths[spec["router_key"]],
                    root,
                    "SourceCode/TerminalSS",
                )
            }
            for spec in ASSET_SPECS
        },
    }
    router_path = assets_root / "TerminalSSAssets_Manifest.json"
    write_json(router_path, router)
    return router_path


def build_tool_record(path, root, platform_name=None, architecture=None):
    record = relative_record(path, root, "SourceCode/TerminalSS")
    if platform_name is not None:
        record["platform"] = platform_name
    if architecture is not None:
        record["architecture"] = architecture
    return record


def canonical_platform(value):
    lowered = value.casefold()
    if lowered == "windows":
        return "Windows"
    if lowered == "linux":
        return "Linux"
    if lowered == "macos":
        return "macOS"
    return value


def canonical_architecture(value):
    lowered = value.casefold()
    if lowered == "universal":
        return "Universal"
    if lowered == "arm64":
        return "arm64"
    return "x86_64"


def add_platform_build_tool(container, component, path, match, root):
    platform_name = canonical_platform(match.group(1))
    architecture = canonical_architecture(match.group(2))
    version = match.group(3)
    target = f"{platform_name}_{architecture}"
    component_map = container.setdefault(component, {})
    target_map = component_map.setdefault(target, {"latest_version": None, "versions": {}})
    target_map["versions"][version] = build_tool_record(
        path,
        root,
        platform_name,
        architecture,
    )
    target_map["latest_version"] = latest_version(target_map["versions"])


def build_build_tools_manifest(root):
    tools_root = root / "TerminalSSBuildTools"
    if not tools_root.is_dir():
        raise RuntimeError("TerminalSSBuildTools folder is missing.")

    platform_tools = {}
    manifest_versions = {}

    for path in sorted(tools_root.glob("*.py"), key=lambda item: item.name.casefold()):
        match = UPDATER_BUILD_TOOL_PATTERN.fullmatch(path.name)
        if match:
            add_platform_build_tool(platform_tools, "TerminalSSUpdater", path, match, root)
            continue

        match = APP_BUILD_TOOL_PATTERN.fullmatch(path.name)
        if match:
            add_platform_build_tool(platform_tools, "TerminalSS", path, match, root)
            continue

        match = MANIFEST_BUILD_TOOL_PATTERN.fullmatch(path.name)
        if match:
            version = match.group(1)
            manifest_versions[version] = build_tool_record(path, root)

    general_tools = {}
    if manifest_versions:
        general_tools["TerminalSSManifests"] = {
            "latest_version": latest_version(manifest_versions),
            "versions": dict(
                sorted(manifest_versions.items(), key=lambda item: version_key(item[0]))
            ),
        }

    for component in platform_tools.values():
        for target in component.values():
            target["versions"] = dict(
                sorted(target["versions"].items(), key=lambda item: version_key(item[0]))
            )

    manifest = {
        "schema": 1,
        "application": "TerminalSS",
        "usage": {
            "application_builds": "Copy the required platform build tool into the matching TerminalSS_X.Y.Z source folder, run it, then remove the copied tool.",
            "updater_builds": "Copy the required updater platform build tool into the matching TerminalSSUpdater_X.Y.Z source folder, run it, then remove the copied tool.",
            "manifests": "Copy Build_TerminalSSManifests_<version>.py into the TerminalSS SourceCode, Releases, or Resources root, run it, then remove the copied tool.",
        },
        "platform_tools": platform_tools,
        "general_tools": general_tools,
    }
    path = tools_root / "TerminalSSBuildTools_Manifest.json"
    write_json(path, manifest)
    return path


def build_source(root):
    show("MODE", "SourceCode")
    application_manifest = build_source_application_manifest(root)
    updater_manifest = build_source_updater_manifest(root)
    assets_manifest = build_source_asset_manifests(root)
    build_tools_manifest = build_build_tools_manifest(root)

    manifest = {
        "schema": 1,
        "application": "TerminalSS",
        "components": {
            "TerminalSS": {
                "manifest": relative_record(application_manifest, root, "SourceCode/TerminalSS")
            },
            "TerminalSSUpdater": {
                "manifest": relative_record(updater_manifest, root, "SourceCode/TerminalSS")
            },
            "TerminalSSAssets": {
                "manifest": relative_record(assets_manifest, root, "SourceCode/TerminalSS")
            },
            "TerminalSSBuildTools": {
                "manifest": relative_record(build_tools_manifest, root, "SourceCode/TerminalSS")
            },
        },
    }
    write_json(root / "TerminalSS_Source_Manifest.json", manifest)


def normalize_zip_member(name):
    value = str(name).replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    if not value or value.startswith("/") or "\x00" in value:
        raise RuntimeError(f"Unsafe ZIP member path: {name}")
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise RuntimeError(f"Unsafe ZIP member path: {name}")
    if len(parts[0]) >= 2 and parts[0][1] == ":":
        raise RuntimeError(f"Unsafe ZIP member path: {name}")
    return "/".join(parts)


def zip_member_is_symlink(info):
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    return bool(unix_mode and stat.S_ISLNK(unix_mode))


def inspect_asset_package(path, expected_root):
    path = Path(path)
    records = []
    seen = set()
    prefix = expected_root.rstrip("/") + "/"

    try:
        archive = zipfile.ZipFile(path, "r")
    except Exception as exc:
        raise RuntimeError(f"Could not open asset package: {path.name}") from exc

    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if not infos:
            raise RuntimeError(f"Asset package is empty: {path.name}")

        for info in infos:
            member = normalize_zip_member(info.filename)
            if zip_member_is_symlink(info):
                raise RuntimeError(f"Asset package contains a symbolic link: {path.name}:{member}")
            if not member.startswith(prefix):
                raise RuntimeError(
                    f"Asset package must contain exactly the {expected_root} root folder: {path.name}"
                )
            relative = member[len(prefix):]
            if not relative:
                continue
            relative_parts = PurePosixPath(relative).parts
            if any(part.casefold() == "custom" for part in relative_parts):
                raise RuntimeError(f"Asset package contains a Custom folder: {path.name}:{relative}")
            key = relative.casefold()
            if key in seen:
                raise RuntimeError(f"Asset package contains duplicate paths: {path.name}:{relative}")
            seen.add(key)
            data = archive.read(info)
            records.append(
                {
                    "file": PurePosixPath(relative).name,
                    "path": relative,
                    "sha256": sha256_bytes(data),
                    "size_bytes": len(data),
                }
            )

    records.sort(key=lambda record: record["path"].casefold())
    return records


def asset_version_from_zip(filename, prefix):
    marker = prefix + "_"
    if not filename.startswith(marker) or not filename.lower().endswith(".zip"):
        return None
    version = filename[len(marker):-4]
    if not VERSION_PATTERN.fullmatch(version):
        return None
    return version


def build_resource_asset_manifests(root):
    assets_root = root / "TerminalSSAssets"
    assets_root.mkdir(parents=True, exist_ok=True)
    paths = {}

    for spec in ASSET_SPECS:
        component_root = assets_root / spec["folder"]
        component_root.mkdir(parents=True, exist_ok=True)
        versions = {}

        for package in sorted(component_root.glob("*.zip"), key=lambda path: path.name.casefold()):
            version = asset_version_from_zip(package.name, spec["prefix"])
            if not version:
                continue
            folder_name = f"{spec['prefix']}_{version}"
            files = inspect_asset_package(package, folder_name)
            if spec["folder"] == "CharacterIndex":
                expected_json = f"CharacterIndex_{version}.json"
                if not any(record["path"] == expected_json for record in files):
                    raise RuntimeError(
                        f"{package.name} does not contain {folder_name}/{expected_json}."
                    )
            relative = package.relative_to(root).as_posix()
            versions[version] = {
                "compatibility_family": compatibility_family(version),
                "folder": folder_name,
                "package": {
                    "file": package.name,
                    "download_url": raw_url("Resources/FirstParty/TerminalSS", relative),
                    "sha256": sha256_file(package),
                    "size_bytes": package.stat().st_size,
                },
                "files": files,
            }

        manifest = {
            "schema": 1,
            "application": "TerminalSS",
            "component": spec["component"],
            "latest_version": latest_version(versions),
            "versions": dict(sorted(versions.items(), key=lambda item: version_key(item[0]))),
        }
        if spec["protocol"] is not None:
            manifest["protocol"] = spec["protocol"]

        path = component_root / spec["release_manifest"]
        write_json(path, manifest)
        paths[spec["router_key"]] = path

    router = {
        "schema": 1,
        "application": "TerminalSS",
        "component": "TerminalSS Assets",
        "assets": {
            spec["router_key"]: {
                "manifest": relative_record(
                    paths[spec["router_key"]],
                    root,
                    "Resources/FirstParty/TerminalSS",
                )
            }
            for spec in ASSET_SPECS
        },
    }
    router_path = assets_root / "TerminalSSAssets_Release_Manifest.json"
    write_json(router_path, router)
    return router_path


def expected_updater_runtime(platform_name):
    if platform_name == "Windows":
        return "TerminalSSUpdater.exe"
    if platform_name == "Linux":
        return "TerminalSSUpdater"
    raise RuntimeError(
        "TerminalSSUpdater release manifests currently support Windows and Linux packages only."
    )


def inspect_single_runtime_zip(path, expected_name):
    try:
        archive = zipfile.ZipFile(path, "r")
    except Exception as exc:
        raise RuntimeError(f"Could not open release package: {path.name}") from exc

    with archive:
        candidates = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = normalize_zip_member(info.filename)
            if zip_member_is_symlink(info):
                raise RuntimeError(f"Release package contains a symbolic link: {path.name}:{member}")
            if PurePosixPath(member).name.casefold() == expected_name.casefold():
                candidates.append((info, member))

        if len(candidates) != 1:
            raise RuntimeError(
                f"{path.name} must contain exactly one {expected_name} runtime."
            )

        info, member = candidates[0]
        data = archive.read(info)
        if not data:
            raise RuntimeError(f"Release runtime is empty: {path.name}:{member}")
        return sha256_bytes(data), len(data)


def build_updater_release_manifest(root):
    updater_root = root / "TerminalSSUpdater"
    updater_root.mkdir(parents=True, exist_ok=True)
    versions = {}

    for package in sorted(updater_root.glob("*.zip"), key=lambda path: path.name.casefold()):
        match = UPDATER_RELEASE_PATTERN.fullmatch(package.name)
        if not match:
            continue
        version = match.group(1)
        platform_name = canonical_platform(match.group(2))
        architecture = canonical_architecture(match.group(3))
        runtime_name = expected_updater_runtime(platform_name)
        runtime_hash, runtime_size = inspect_single_runtime_zip(package, runtime_name)
        asset_key = f"{platform_name}_{architecture}"
        relative = package.relative_to(root).as_posix()

        entry = versions.setdefault(
            version,
            {
                "compatibility_family": compatibility_family(version),
                "assets": {},
            },
        )
        if asset_key in entry["assets"]:
            raise RuntimeError(f"Duplicate updater release asset: {version} {asset_key}")
        entry["assets"][asset_key] = {
            "file": package.name,
            "download_url": raw_url("Resources/FirstParty/TerminalSS", relative),
            "sha256": sha256_file(package),
            "size_bytes": package.stat().st_size,
            "executable": runtime_name,
            "executable_sha256": runtime_hash,
            "executable_size_bytes": runtime_size,
        }

    versions = dict(sorted(versions.items(), key=lambda item: version_key(item[0])))
    manifest = {
        "schema": 1,
        "application": "TerminalSS",
        "component": "TerminalSSUpdater",
        "latest_version": latest_version(versions),
        "versions": versions,
    }
    path = updater_root / "TerminalSSUpdater_Release_Manifest.json"
    write_json(path, manifest)
    return path


def update_shared_resource_routers(root):
    resources_root = find_named_ancestor(root, "Resources")
    if resources_root is None:
        return

    first_party_root = resources_root / "FirstParty"
    first_party_manifest = first_party_root / "FirstParty_Resources_Manifest.json"
    resources_manifest = resources_root / "Resources_Manifest.json"

    if first_party_manifest.is_file():
        data = read_json(first_party_manifest)
        resources = data.setdefault("resources", {})
        if not isinstance(resources, dict):
            raise RuntimeError("FirstParty_Resources_Manifest.json has an invalid resources object.")
        resources["TerminalSS"] = {
            "manifest": {
                "file": "TerminalSS_Resources_Manifest.json",
                "path": "Resources/FirstParty/TerminalSS/TerminalSS_Resources_Manifest.json",
                "download_url": raw_url(
                    "Resources/FirstParty/TerminalSS",
                    "TerminalSS_Resources_Manifest.json",
                ),
            }
        }
        data["resources"] = dict(sorted(resources.items(), key=lambda item: item[0].casefold()))
        write_json(first_party_manifest, data)
        show("ROUTER", "FirstParty_Resources_Manifest.json")

    if resources_manifest.is_file():
        data = read_json(resources_manifest)
        resources = data.setdefault("resources", {})
        if not isinstance(resources, dict):
            raise RuntimeError("Resources_Manifest.json has an invalid resources object.")
        resources["FirstParty"] = {
            "manifest": {
                "file": "FirstParty_Resources_Manifest.json",
                "path": "Resources/FirstParty/FirstParty_Resources_Manifest.json",
                "download_url": raw_url(
                    "Resources/FirstParty",
                    "FirstParty_Resources_Manifest.json",
                ),
            }
        }
        data["resources"] = dict(sorted(resources.items(), key=lambda item: item[0].casefold()))
        write_json(resources_manifest, data)
        show("ROUTER", "Resources_Manifest.json")


def build_resources(root):
    show("MODE", "Resources")
    assets_manifest = build_resource_asset_manifests(root)
    updater_manifest = build_updater_release_manifest(root)

    manifest = {
        "schema": 1,
        "application": "TerminalSS",
        "components": {
            "TerminalSSUpdater": {
                "manifest": relative_record(
                    updater_manifest,
                    root,
                    "Resources/FirstParty/TerminalSS",
                )
            },
            "TerminalSSAssets": {
                "manifest": relative_record(
                    assets_manifest,
                    root,
                    "Resources/FirstParty/TerminalSS",
                )
            },
        },
    }
    write_json(root / "TerminalSS_Resources_Manifest.json", manifest)
    update_shared_resource_routers(root)


def expected_application_runtime(platform_name):
    if platform_name == "Windows":
        return "TerminalSS.exe"
    if platform_name == "Linux":
        return "TerminalSS.AppImage"
    raise RuntimeError(
        "TerminalSS application release manifests currently support Windows and Linux packages only."
    )


def release_readme_record(root):
    path = root / "TerminalSS_README.md"
    if not path.is_file():
        return None
    return {
        "file": path.name,
        "path": "Releases/TerminalSS/TerminalSS_README.md",
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "download_url": raw_url("Releases/TerminalSS", path.name),
    }


def build_releases(root):
    show("MODE", "Releases")
    releases = {}

    for package in sorted(root.glob("*.zip"), key=lambda path: path.name.casefold()):
        match = APP_RELEASE_PATTERN.fullmatch(package.name)
        if not match:
            continue
        version = match.group(1)
        platform_name = canonical_platform(match.group(2))
        architecture = canonical_architecture(match.group(3))
        runtime_name = expected_application_runtime(platform_name)
        runtime_hash, runtime_size = inspect_single_runtime_zip(package, runtime_name)
        asset_key = f"{platform_name}_{architecture}"
        entry = releases.setdefault(version, {"assets": {}})
        if asset_key in entry["assets"]:
            raise RuntimeError(f"Duplicate TerminalSS release asset: {version} {asset_key}")
        entry["assets"][asset_key] = {
            "file": package.name,
            "download_url": raw_url("Releases/TerminalSS", package.name),
            "sha256": sha256_file(package),
            "size_bytes": package.stat().st_size,
            "executable": runtime_name,
            "executable_sha256": runtime_hash,
            "executable_size_bytes": runtime_size,
        }

    releases = dict(sorted(releases.items(), key=lambda item: version_key(item[0])))
    manifest = {
        "schema": 1,
        "application": "TerminalSS",
    }
    readme = release_readme_record(root)
    if readme is not None:
        manifest["readme"] = readme
    manifest["latest_version"] = latest_version(releases)
    manifest["releases"] = releases
    write_json(root / "TerminalSS_Release_Manifest.json", manifest)


def parse_args():
    parser = argparse.ArgumentParser(prog=f"Build_TerminalSSManifests_{BUILDER_VERSION}")
    parser.add_argument("--version", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.version:
        print(f"Build_TerminalSSManifests {BUILDER_VERSION}")
        return 0

    root = Path(__file__).resolve().parent
    environment = detect_environment(root)

    print()
    print(f"TerminalSS Manifest Build Tool {BUILDER_VERSION}")
    print("=" * 48)
    show("ROOT", root)
    show("ENVIRONMENT", environment)
    print()

    if environment == "source":
        build_source(root)
    elif environment == "resources":
        build_resources(root)
    elif environment == "releases":
        build_releases(root)
    else:
        raise RuntimeError(f"Unsupported manifest environment: {environment}")

    print()
    print("=" * 48)
    print("MANIFESTS READY")
    print("=" * 48)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        print("Build cancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print()
        print("BUILD FAILED: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
