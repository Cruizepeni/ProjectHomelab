import argparse
import hashlib
import json
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

BUILD_TOOL_VERSION = "1.0.0"
BASE_RAW_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
)

VERSION_PATTERN = re.compile(
    r"^\d+\.\d+\.\d+$"
)

APPLICATION_RELEASE_PATTERN = re.compile(
    r"^PythoFetch_(\d+\.\d+\.\d+)_(Windows|Linux|macOS)_(.+)\.zip$",
    re.IGNORECASE,
)

UPDATER_RELEASE_PATTERN = re.compile(
    r"^PythoFetchUpdater_(\d+\.\d+\.\d+)_(Windows|Linux|macOS)_(.+)\.zip$",
    re.IGNORECASE,
)

APPLICATION_BUILD_TOOL_PATTERN = re.compile(
    r"^Build_PythoFetch_(Windows|Linux|macOS)_(.+)_(\d+\.\d+\.\d+)\.py$",
    re.IGNORECASE,
)

UPDATER_BUILD_TOOL_PATTERN = re.compile(
    r"^Build_PythoFetchUpdater_(Windows|Linux|macOS)_(.+)_(\d+\.\d+\.\d+)\.py$",
    re.IGNORECASE,
)

ART_DB_BUILD_TOOL_PATTERN = re.compile(
    r"^Build_PythoFetchArtDB_(\d+\.\d+\.\d+)\.py$",
    re.IGNORECASE,
)

MANIFEST_BUILD_TOOL_PATTERN = re.compile(
    r"^Build_PythoFetchManifests_(\d+\.\d+\.\d+)\.py$",
    re.IGNORECASE,
)

ART_DATABASE_PATTERN = re.compile(
    r"^PythoFetchArt_(\d+\.\d+\.\d+)\.db$",
    re.IGNORECASE,
)

SOURCE_APPLICATION_FOLDER_PATTERN = re.compile(
    r"^PythoFetch_(\d+\.\d+\.\d+)$",
    re.IGNORECASE,
)

SOURCE_UPDATER_FOLDER_PATTERN = re.compile(
    r"^PythoFetchUpdater_(\d+\.\d+\.\d+)$",
    re.IGNORECASE,
)


def version_key(value):
    value = str(value).strip()

    if not VERSION_PATTERN.fullmatch(
        value
    ):
        raise RuntimeError(
            f"Invalid version: {value}"
        )

    return tuple(
        int(part)
        for part in value.split(".")
    )


def canonical_system(value):
    lowered = str(value).strip().lower()

    mapping = {
        "windows": "Windows",
        "linux": "Linux",
        "macos": "macOS",
    }

    if lowered not in mapping:
        raise RuntimeError(
            f"Unsupported platform: {value}"
        )

    return mapping[lowered]


def compatibility_family(version):
    parts = str(version).split(".")

    if len(parts) != 3:
        raise RuntimeError(
            f"Invalid version: {version}"
        )

    return ".".join(
        parts[:2]
    )


def sha256_file(path):
    digest = hashlib.sha256()

    with Path(path).open(
        "rb"
    ) as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


def sha256_stream(handle):
    digest = hashlib.sha256()

    while True:
        chunk = handle.read(
            1024 * 1024
        )

        if not chunk:
            break

        digest.update(
            chunk
        )

    return digest.hexdigest()


def write_json(path, payload):
    path = Path(path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_bytes(
        (
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        ).encode(
            "utf-8"
        )
    )

    json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    return path


def load_json(path):
    path = Path(path)

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not read JSON manifest: {path}"
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise RuntimeError(
            f"Manifest root is not an object: {path}"
        )

    return payload


def repo_record(path, repo_path):
    path = Path(path)
    repo_path = (
        str(repo_path)
        .replace("\\", "/")
        .lstrip("/")
    )

    return {
        "file": path.name,
        "path": repo_path,
        "sha256": sha256_file(
            path
        ),
        "size_bytes": (
            path.stat().st_size
        ),
        "download_url": (
            BASE_RAW_URL
            + repo_path
        ),
    }


def file_record(path):
    path = Path(path)

    return {
        "file": path.name,
        "sha256": sha256_file(
            path
        ),
        "size_bytes": (
            path.stat().st_size
        ),
    }


def database_metadata(path):
    path = Path(path)

    connection = sqlite3.connect(
        str(path)
    )

    try:
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if (
            not integrity
            or integrity[0] != "ok"
        ):
            raise RuntimeError(
                "Database integrity check failed: "
                f"{path.name}"
            )

        rows = connection.execute(
            """
            SELECT key, value
            FROM metadata
            """
        ).fetchall()

        metadata = {
            str(key): str(value)
            for key, value in rows
        }

        artwork_count = connection.execute(
            "SELECT COUNT(*) FROM artwork"
        ).fetchone()[0]

    except sqlite3.Error as exc:
        raise RuntimeError(
            "Could not inspect artwork database: "
            f"{path.name}"
        ) from exc

    finally:
        connection.close()

    return (
        metadata,
        int(artwork_count),
    )


def parse_json_object(value):
    if value in (
        None,
        "",
    ):
        return {}

    try:
        payload = json.loads(
            value
        )
    except Exception:
        return {}

    if not isinstance(
        payload,
        dict,
    ):
        return {}

    return payload


def build_art_database_manifest(root):
    database_root = (
        root
        / "PythoFetchArtAssets"
        / "ArtAssetsDB"
    )

    database_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest_path = (
        database_root
        / "PythoFetchArtDB_Manifest.json"
    )

    discovered = []

    for path in database_root.iterdir():
        if not path.is_file():
            continue

        match = ART_DATABASE_PATTERN.fullmatch(
            path.name
        )

        if not match:
            continue

        version = match.group(1)

        discovered.append(
            (
                version_key(version),
                version,
                path,
            )
        )

    discovered.sort(
        reverse=True
    )

    versions = {}

    for _, version, path in discovered:
        metadata, artwork_count = (
            database_metadata(
                path
            )
        )

        declared_name = metadata.get(
            "database_name"
        )

        if (
            declared_name
            and declared_name
            != "PythoFetchArt"
        ):
            raise RuntimeError(
                "Artwork database identity does not "
                f"match PythoFetchArt: {path.name}"
            )

        declared_version = metadata.get(
            "database_version"
        )

        if (
            declared_version
            and declared_version
            != version
        ):
            raise RuntimeError(
                "Artwork database filename version "
                "does not match its metadata: "
                f"{path.name}"
            )

        source_counts = parse_json_object(
            metadata.get(
                "source_counts"
            )
        )

        family_counts = parse_json_object(
            metadata.get(
                "family_counts"
            )
        )

        try:
            schema_version = int(
                metadata.get(
                    "schema_version",
                    "1",
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "Artwork database has an invalid "
                f"schema version: {path.name}"
            ) from exc

        try:
            override_count = int(
                metadata.get(
                    "override_count",
                    "0",
                )
            )
        except Exception:
            override_count = 0

        try:
            pythofetch_count = int(
                source_counts.get(
                    "PythoFetch",
                    0,
                )
            )
        except Exception:
            pythofetch_count = 0

        entry = {
            "file": path.name,
            "download_url": (
                BASE_RAW_URL
                + "SourceCode/PythoFetch/"
                + "PythoFetchArtAssets/"
                + "ArtAssetsDB/"
                + path.name
            ),
            "sha256": sha256_file(
                path
            ),
            "size_bytes": (
                path.stat().st_size
            ),
            "schema_version":
                schema_version,
            "artwork_count":
                artwork_count,
            "added_pythofetch_artworks":
                max(
                    0,
                    pythofetch_count
                    - override_count,
                ),
            "override_count":
                override_count,
            "source_counts":
                source_counts,
            "family_counts":
                family_counts,
        }

        created_utc = metadata.get(
            "created_utc"
        )

        if created_utc:
            entry[
                "created_utc"
            ] = created_utc

        compiler_version = metadata.get(
            "compiler_version"
        )

        if compiler_version:
            entry[
                "compiler_version"
            ] = compiler_version

        versions[
            version
        ] = entry

    latest = (
        discovered[0][1]
        if discovered
        else None
    )

    payload = {
        "schema": 1,
        "database": "PythoFetchArt",
        "latest_version": latest,
        "versions": versions,
    }

    return write_json(
        manifest_path,
        payload,
    )


def build_application_source_manifest(root):
    component_root = (
        root / "PythoFetch"
    )

    if not component_root.is_dir():
        raise RuntimeError(
            "Missing PythoFetch source component folder."
        )

    manifest_path = (
        component_root
        / "PythoFetch_Manifest.json"
    )

    candidates = []

    for path in component_root.iterdir():
        if not path.is_dir():
            continue

        match = (
            SOURCE_APPLICATION_FOLDER_PATTERN
            .fullmatch(
                path.name
            )
        )

        if not match:
            continue

        version = match.group(1)

        candidates.append(
            (
                version_key(version),
                version,
                path,
            )
        )

    candidates.sort(
        reverse=True
    )

    versions = {}

    for _, version, version_dir in candidates:
        source = (
            version_dir
            / f"PythoFetch_{version}.py"
        )

        if not source.is_file():
            raise RuntimeError(
                "Missing canonical source file: "
                f"{source}"
            )

        source_repo = (
            "SourceCode/PythoFetch/"
            "PythoFetch/"
            f"PythoFetch_{version}/"
            f"PythoFetch_{version}.py"
        )

        entry = {
            "source":
                repo_record(
                    source,
                    source_repo,
                ),
        }

        databases = []

        for path in version_dir.iterdir():
            if not path.is_file():
                continue

            match = ART_DATABASE_PATTERN.fullmatch(
                path.name
            )

            if not match:
                continue

            database_version = (
                match.group(1)
            )

            if (
                compatibility_family(
                    database_version
                )
                != compatibility_family(
                    version
                )
            ):
                continue

            databases.append(
                (
                    version_key(
                        database_version
                    ),
                    path,
                )
            )

        if databases:
            databases.sort(
                reverse=True
            )

            database = (
                databases[0][1]
            )

            database_repo = (
                "SourceCode/PythoFetch/"
                "PythoFetch/"
                f"PythoFetch_{version}/"
                + database.name
            )

            entry[
                "art_database"
            ] = repo_record(
                database,
                database_repo,
            )

        versions[
            version
        ] = entry

    latest = (
        candidates[0][1]
        if candidates
        else None
    )

    payload = {
        "schema": 1,
        "application": "PythoFetch",
        "component": "Application Source",
        "latest_version": latest,
        "versions": versions,
    }

    return write_json(
        manifest_path,
        payload,
    )


def build_updater_source_manifest(root):
    component_root = (
        root / "PythoFetchUpdater"
    )

    if not component_root.is_dir():
        raise RuntimeError(
            "Missing PythoFetchUpdater source "
            "component folder."
        )

    manifest_path = (
        component_root
        / "PythoFetchUpdater_Manifest.json"
    )

    candidates = []

    for path in component_root.iterdir():
        if not path.is_dir():
            continue

        match = (
            SOURCE_UPDATER_FOLDER_PATTERN
            .fullmatch(
                path.name
            )
        )

        if not match:
            continue

        version = match.group(1)

        candidates.append(
            (
                version_key(version),
                version,
                path,
            )
        )

    candidates.sort(
        reverse=True
    )

    versions = {}

    for _, version, version_dir in candidates:
        source = (
            version_dir
            / f"PythoFetchUpdater_{version}.py"
        )

        if not source.is_file():
            raise RuntimeError(
                "Missing canonical updater source: "
                f"{source}"
            )

        source_repo = (
            "SourceCode/PythoFetch/"
            "PythoFetchUpdater/"
            f"PythoFetchUpdater_{version}/"
            f"PythoFetchUpdater_{version}.py"
        )

        versions[
            version
        ] = {
            "source":
                repo_record(
                    source,
                    source_repo,
                ),
        }

    latest = (
        candidates[0][1]
        if candidates
        else None
    )

    payload = {
        "schema": 1,
        "application": "PythoFetch",
        "component":
            "PythoFetchUpdater Source",
        "latest_version": latest,
        "versions": versions,
    }

    return write_json(
        manifest_path,
        payload,
    )


def build_art_assets_manifest(root):
    component_root = (
        root / "PythoFetchArtAssets"
    )

    if not component_root.is_dir():
        raise RuntimeError(
            "Missing PythoFetchArtAssets folder."
        )

    manifest_path = (
        component_root
        / "PythoFetchArtAssets_Manifest.json"
    )

    definitions = {
        "ArtAssetsDB": {
            "manifest":
                "PythoFetchArtDB_Manifest.json",
        },
        "ArtAssetsNeofetch": {
            "catalogue":
                "Catalogue.json",
        },
        "ArtAssetsPythoFetch": {
            "catalogue":
                "Catalogue.json",
        },
    }

    folders = {}

    for folder_name, metadata in (
        definitions.items()
    ):
        folder = (
            component_root
            / folder_name
        )

        if not folder.is_dir():
            continue

        record = {
            "path":
                "SourceCode/PythoFetch/"
                "PythoFetchArtAssets/"
                + folder_name,
            "file_count":
                sum(
                    1
                    for path
                    in folder.rglob("*")
                    if path.is_file()
                ),
        }

        manifest_name = metadata.get(
            "manifest"
        )

        if manifest_name:
            target = (
                folder
                / manifest_name
            )

            if target.is_file():
                repo_path = (
                    "SourceCode/PythoFetch/"
                    "PythoFetchArtAssets/"
                    + folder_name
                    + "/"
                    + manifest_name
                )

                record[
                    "manifest"
                ] = repo_record(
                    target,
                    repo_path,
                )

        catalogue_name = metadata.get(
            "catalogue"
        )

        if catalogue_name:
            target = (
                folder
                / catalogue_name
            )

            if target.is_file():
                repo_path = (
                    "SourceCode/PythoFetch/"
                    "PythoFetchArtAssets/"
                    + folder_name
                    + "/"
                    + catalogue_name
                )

                record[
                    "catalogue"
                ] = repo_record(
                    target,
                    repo_path,
                )

        folders[
            folder_name
        ] = record

    payload = {
        "schema": 1,
        "application": "PythoFetch",
        "component": "Artwork Assets",
        "folders": folders,
    }

    return write_json(
        manifest_path,
        payload,
    )


def collect_platform_build_tools(
    component_root,
    pattern,
):
    discovered = {}

    for path in component_root.iterdir():
        if not path.is_file():
            continue

        match = pattern.fullmatch(
            path.name
        )

        if not match:
            continue

        system, architecture, version = (
            match.groups()
        )

        system = canonical_system(
            system
        )

        asset_key = (
            f"{system}_{architecture}"
        )

        discovered.setdefault(
            asset_key,
            []
        ).append(
            (
                version_key(version),
                version,
                path,
                system,
                architecture,
            )
        )

    tools = {}

    for asset_key in sorted(
        discovered
    ):
        entries = sorted(
            discovered[asset_key],
            reverse=True,
        )

        versions = {}

        for (
            _,
            version,
            path,
            system,
            architecture,
        ) in entries:
            record = file_record(
                path
            )

            record[
                "platform"
            ] = system

            record[
                "architecture"
            ] = architecture

            versions[
                version
            ] = record

        tools[
            asset_key
        ] = {
            "latest_version":
                entries[0][1],
            "versions":
                versions,
        }

    return tools


def collect_general_build_tool(
    component_root,
    pattern,
):
    entries = []

    for path in component_root.iterdir():
        if not path.is_file():
            continue

        match = pattern.fullmatch(
            path.name
        )

        if not match:
            continue

        version = match.group(1)

        entries.append(
            (
                version_key(version),
                version,
                path,
            )
        )

    entries.sort(
        reverse=True
    )

    if not entries:
        return None

    versions = {}

    for _, version, path in entries:
        versions[
            version
        ] = file_record(
            path
        )

    return {
        "latest_version":
            entries[0][1],
        "versions": versions,
    }


def build_build_tools_manifest(root):
    component_root = (
        root / "PythoFetchBuildTools"
    )

    if not component_root.is_dir():
        raise RuntimeError(
            "Missing PythoFetchBuildTools folder."
        )

    manifest_path = (
        component_root
        / "PythoFetchBuildTools_Manifest.json"
    )

    platform_tools = {}

    application_tools = (
        collect_platform_build_tools(
            component_root,
            APPLICATION_BUILD_TOOL_PATTERN,
        )
    )

    updater_tools = (
        collect_platform_build_tools(
            component_root,
            UPDATER_BUILD_TOOL_PATTERN,
        )
    )

    if application_tools:
        platform_tools[
            "PythoFetch"
        ] = application_tools

    if updater_tools:
        platform_tools[
            "PythoFetchUpdater"
        ] = updater_tools

    general_tools = {}

    art_db = collect_general_build_tool(
        component_root,
        ART_DB_BUILD_TOOL_PATTERN,
    )

    if art_db:
        general_tools[
            "PythoFetchArtDB"
        ] = art_db

    manifests = (
        collect_general_build_tool(
            component_root,
            MANIFEST_BUILD_TOOL_PATTERN,
        )
    )

    if manifests:
        general_tools[
            "PythoFetchManifests"
        ] = manifests

    payload = {
        "schema": 1,
        "application": "PythoFetch",
        "usage": {
            "application_builds":
                "Copy the required platform "
                "build tool into the matching "
                "application version folder, "
                "run it, then remove the copied "
                "tool.",
            "updater_builds":
                "Copy the required updater "
                "platform build tool into the "
                "matching updater version "
                "folder, run it, then remove "
                "the copied tool.",
            "art_database":
                "Run "
                "Build_PythoFetchArtDB_<version>.py "
                "from PythoFetchBuildTools.",
            "manifests":
                "Copy "
                "Build_PythoFetchManifests_<version>.py "
                "into the PythoFetch SourceCode, "
                "Releases, or Resources root, run it, "
                "then remove the copied tool.",
        },
        "platform_tools":
            platform_tools,
        "general_tools":
            general_tools,
    }

    return write_json(
        manifest_path,
        payload,
    )


def build_source_root_manifest(
    root,
    manifests,
):
    manifest_path = (
        root
        / "PythoFetch_Source_Manifest.json"
    )

    definitions = {
        "PythoFetch": (
            manifests[
                "PythoFetch"
            ],
            "SourceCode/PythoFetch/"
            "PythoFetch/"
            "PythoFetch_Manifest.json",
        ),
        "PythoFetchUpdater": (
            manifests[
                "PythoFetchUpdater"
            ],
            "SourceCode/PythoFetch/"
            "PythoFetchUpdater/"
            "PythoFetchUpdater_Manifest.json",
        ),
        "PythoFetchArtAssets": (
            manifests[
                "PythoFetchArtAssets"
            ],
            "SourceCode/PythoFetch/"
            "PythoFetchArtAssets/"
            "PythoFetchArtAssets_Manifest.json",
        ),
        "PythoFetchBuildTools": (
            manifests[
                "PythoFetchBuildTools"
            ],
            "SourceCode/PythoFetch/"
            "PythoFetchBuildTools/"
            "PythoFetchBuildTools_Manifest.json",
        ),
    }

    components = {}

    for (
        name,
        (
            path,
            repo_path,
        ),
    ) in definitions.items():
        components[
            name
        ] = {
            "manifest":
                repo_record(
                    path,
                    repo_path,
                ),
        }

    payload = {
        "schema": 1,
        "application": "PythoFetch",
        "components": components,
    }

    return write_json(
        manifest_path,
        payload,
    )


def build_source_manifests(root):
    required = (
        "PythoFetch",
        "PythoFetchUpdater",
        "PythoFetchArtAssets",
        "PythoFetchBuildTools",
    )

    missing = [
        name
        for name in required
        if not (
            root / name
        ).is_dir()
    ]

    if missing:
        raise RuntimeError(
            "SourceCode mode is missing required "
            "folders: "
            + ", ".join(
                missing
            )
        )

    paths = []

    art_database_manifest = (
        build_art_database_manifest(
            root
        )
    )

    paths.append(
        art_database_manifest
    )

    application_manifest = (
        build_application_source_manifest(
            root
        )
    )

    paths.append(
        application_manifest
    )

    updater_manifest = (
        build_updater_source_manifest(
            root
        )
    )

    paths.append(
        updater_manifest
    )

    build_tools_manifest = (
        build_build_tools_manifest(
            root
        )
    )

    paths.append(
        build_tools_manifest
    )

    art_assets_manifest = (
        build_art_assets_manifest(
            root
        )
    )

    paths.append(
        art_assets_manifest
    )

    manifests = {
        "PythoFetch":
            application_manifest,
        "PythoFetchUpdater":
            updater_manifest,
        "PythoFetchArtAssets":
            art_assets_manifest,
        "PythoFetchBuildTools":
            build_tools_manifest,
    }

    root_manifest = (
        build_source_root_manifest(
            root,
            manifests,
        )
    )

    paths.insert(
        0,
        root_manifest,
    )

    return paths


def zip_non_directory_members(archive):
    return [
        info
        for info
        in archive.infolist()
        if not info.is_dir()
    ]


def find_single_file_payload(
    archive,
    expected_name,
    label,
):
    infos = zip_non_directory_members(
        archive
    )

    if len(infos) != 1:
        raise RuntimeError(
            f"{label} must contain exactly "
            "one runtime file."
        )

    info = infos[0]
    basename = Path(
        info.filename
    ).name

    if basename != expected_name:
        raise RuntimeError(
            f"{label} must contain "
            f"{expected_name}, not {basename}."
        )

    if (
        info.filename.replace("\\", "/")
        != expected_name
    ):
        raise RuntimeError(
            f"{label} runtime must be stored "
            "at the ZIP root."
        )

    with archive.open(
        info,
        "r",
    ) as handle:
        digest = sha256_stream(
            handle
        )

    return {
        "executable":
            expected_name,
        "executable_sha256":
            digest,
        "executable_size_bytes":
            info.file_size,
    }


def find_macos_payload(
    archive,
    expected_prefix,
    label,
):
    roots = set()

    for info in archive.infolist():
        normalized = (
            info.filename
            .replace("\\", "/")
            .lstrip("/")
        )

        if not normalized:
            continue

        first = normalized.split(
            "/",
            1,
        )[0]

        if first.lower().endswith(
            ".app"
        ):
            roots.add(
                first
            )

    if len(roots) != 1:
        raise RuntimeError(
            f"{label} must contain exactly "
            "one .app bundle."
        )

    executable = next(
        iter(
            roots
        )
    )

    if not executable.startswith(
        expected_prefix
    ):
        raise RuntimeError(
            f"{label} contains an unexpected "
            f"macOS bundle: {executable}"
        )

    return {
        "executable":
            executable,
    }


def application_release_payload(
    archive,
    system,
    label,
):
    if system == "Windows":
        return find_single_file_payload(
            archive,
            "PythoFetch.exe",
            label,
        )

    if system == "Linux":
        return find_single_file_payload(
            archive,
            "PythoFetch.AppImage",
            label,
        )

    return find_macos_payload(
        archive,
        "PythoFetch",
        label,
    )


def updater_release_payload(
    archive,
    system,
    label,
):
    if system == "Windows":
        return find_single_file_payload(
            archive,
            "PythoFetchUpdater.exe",
            label,
        )

    if system == "Linux":
        return find_single_file_payload(
            archive,
            "PythoFetchUpdater.AppImage",
            label,
        )

    return find_macos_payload(
        archive,
        "PythoFetchUpdater",
        label,
    )


def build_application_release_manifest(root):
    parsed = []

    for path in root.iterdir():
        if not path.is_file():
            continue

        match = (
            APPLICATION_RELEASE_PATTERN
            .fullmatch(
                path.name
            )
        )

        if not match:
            continue

        version, system, architecture = (
            match.groups()
        )

        system = canonical_system(
            system
        )

        parsed.append(
            (
                version_key(version),
                version,
                system,
                architecture,
                path,
            )
        )

    if not parsed:
        raise RuntimeError(
            "No PythoFetch release ZIPs were "
            "found in this folder."
        )

    parsed.sort(
        reverse=True
    )

    releases = {}

    for (
        _,
        version,
        system,
        architecture,
        path,
    ) in parsed:
        asset_key = (
            f"{system}_{architecture}"
        )

        release = releases.setdefault(
            version,
            {
                "assets": {}
            },
        )

        if (
            asset_key
            in release["assets"]
        ):
            raise RuntimeError(
                "Duplicate release asset for "
                f"{version} {asset_key}."
            )

        with zipfile.ZipFile(
            path,
            "r",
        ) as archive:
            payload = (
                application_release_payload(
                    archive,
                    system,
                    path.name,
                )
            )

        release[
            "assets"
        ][
            asset_key
        ] = {
            "file":
                path.name,
            "download_url":
                BASE_RAW_URL
                + "Releases/PythoFetch/"
                + path.name,
            "sha256":
                sha256_file(
                    path
                ),
            "size_bytes":
                path.stat().st_size,
            **payload,
        }

    ordered_versions = sorted(
        releases,
        key=version_key,
        reverse=True,
    )

    releases = {
        version:
            releases[version]
        for version
        in ordered_versions
    }

    payload = {
        "schema": 1,
        "application": "PythoFetch",
        "latest_version":
            ordered_versions[0],
        "releases": releases,
    }

    return write_json(
        root
        / "PythoFetch_Release_Manifest.json",
        payload,
    )


def build_updater_release_manifest(root):
    updater_root = (
        root
        / "PythoFetchUpdater"
    )

    updater_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    parsed = []

    for path in updater_root.iterdir():
        if not path.is_file():
            continue

        match = (
            UPDATER_RELEASE_PATTERN
            .fullmatch(
                path.name
            )
        )

        if not match:
            continue

        version, system, architecture = (
            match.groups()
        )

        system = canonical_system(
            system
        )

        parsed.append(
            (
                version_key(version),
                version,
                system,
                architecture,
                path,
            )
        )

    parsed.sort(
        reverse=True
    )

    versions = {}

    for (
        _,
        version,
        system,
        architecture,
        path,
    ) in parsed:
        asset_key = (
            f"{system}_{architecture}"
        )

        entry = versions.setdefault(
            version,
            {
                "compatibility_family":
                    compatibility_family(
                        version
                    ),
                "assets": {},
            },
        )

        if (
            asset_key
            in entry["assets"]
        ):
            raise RuntimeError(
                "Duplicate updater release asset "
                f"for {version} {asset_key}."
            )

        with zipfile.ZipFile(
            path,
            "r",
        ) as archive:
            payload = (
                updater_release_payload(
                    archive,
                    system,
                    path.name,
                )
            )

        entry[
            "assets"
        ][
            asset_key
        ] = {
            "file":
                path.name,
            "download_url":
                BASE_RAW_URL
                + "Resources/FirstParty/"
                + "PythoFetch/"
                + "PythoFetchUpdater/"
                + path.name,
            "sha256":
                sha256_file(
                    path
                ),
            "size_bytes":
                path.stat().st_size,
            **payload,
        }

    ordered_versions = sorted(
        versions,
        key=version_key,
        reverse=True,
    )

    versions = {
        version:
            versions[version]
        for version
        in ordered_versions
    }

    payload = {
        "schema": 1,
        "application": "PythoFetch",
        "component": "PythoFetchUpdater",
        "latest_version": (
            ordered_versions[0]
            if ordered_versions
            else None
        ),
        "versions": versions,
    }

    return write_json(
        updater_root
        / "PythoFetchUpdater_Release_Manifest.json",
        payload,
    )


def build_resources_manifest(
    root,
    updater_manifest,
):
    manifest_path = (
        root
        / "PythoFetch_Resources_Manifest.json"
    )

    repo_path = (
        "Resources/FirstParty/PythoFetch/"
        "PythoFetchUpdater/"
        "PythoFetchUpdater_Release_Manifest.json"
    )

    payload = {
        "schema": 1,
        "application": "PythoFetch",
        "components": {
            "PythoFetchUpdater": {
                "manifest":
                    repo_record(
                        updater_manifest,
                        repo_path,
                    ),
            }
        },
    }

    return write_json(
        manifest_path,
        payload,
    )


def router_manifest_record(
    path,
    repo_path,
):
    path = Path(path)

    repo_path = (
        str(repo_path)
        .replace("\\", "/")
        .lstrip("/")
    )

    return {
        "file": path.name,
        "path": repo_path,
        "download_url":
            BASE_RAW_URL
            + repo_path,
    }


def discover_resource_manifests(
    parent,
    pattern,
    repo_prefix,
):
    discovered = {}

    for child in parent.iterdir():
        if not child.is_dir():
            continue

        candidates = [
            path
            for path in child.iterdir()
            if (
                path.is_file()
                and pattern.fullmatch(
                    path.name
                )
            )
        ]

        if len(candidates) > 1:
            raise RuntimeError(
                "Multiple resource manifests were "
                f"found in {child}."
            )

        if not candidates:
            continue

        manifest = candidates[0]

        discovered[
            child.name
        ] = {
            "manifest":
                router_manifest_record(
                    manifest,
                    repo_prefix
                    + "/"
                    + child.name
                    + "/"
                    + manifest.name,
                )
        }

    return {
        name:
            discovered[name]
        for name
        in sorted(
            discovered,
            key=str.lower,
        )
    }


def rebuild_first_party_router(
    resource_root,
):
    first_party_root = (
        resource_root.parent
    )

    manifest_path = (
        first_party_root
        / "FirstParty_Resources_Manifest.json"
    )

    pattern = re.compile(
        r"^[A-Za-z0-9._+\-]+_Resources_Manifest\.json$",
        re.IGNORECASE,
    )

    resources = (
        discover_resource_manifests(
            first_party_root,
            pattern,
            "Resources/FirstParty",
        )
    )

    payload = {
        "schema": 1,
        "resources": resources,
    }

    return write_json(
        manifest_path,
        payload,
    )


def rebuild_resources_router(
    resource_root,
):
    resources_root = (
        resource_root.parent.parent
    )

    manifest_path = (
        resources_root
        / "Resources_Manifest.json"
    )

    category_pattern = re.compile(
        r"^[A-Za-z0-9._+\-]+_Resources_Manifest\.json$",
        re.IGNORECASE,
    )

    resources = (
        discover_resource_manifests(
            resources_root,
            category_pattern,
            "Resources",
        )
    )

    payload = {
        "schema": 1,
        "resources": resources,
    }

    return write_json(
        manifest_path,
        payload,
    )


def build_resource_manifests(root):
    updater_manifest = (
        build_updater_release_manifest(
            root
        )
    )

    resource_manifest = (
        build_resources_manifest(
            root,
            updater_manifest,
        )
    )

    first_party_manifest = (
        rebuild_first_party_router(
            root
        )
    )

    resources_manifest = (
        rebuild_resources_router(
            root
        )
    )

    return [
        resource_manifest,
        updater_manifest,
        first_party_manifest,
        resources_manifest,
    ]


def detect_mode(root):
    candidates = []

    release_zips = [
        path
        for path in root.iterdir()
        if (
            path.is_file()
            and APPLICATION_RELEASE_PATTERN
            .fullmatch(
                path.name
            )
        )
    ]

    if release_zips:
        candidates.append(
            "releases"
        )

    source_markers = (
        root / "PythoFetch",
        root / "PythoFetchArtAssets",
        root / "PythoFetchBuildTools",
    )

    if all(
        path.is_dir()
        for path in source_markers
    ):
        candidates.append(
            "sourcecode"
        )

    updater_root = (
        root / "PythoFetchUpdater"
    )

    updater_zips = []

    if updater_root.is_dir():
        updater_zips = [
            path
            for path
            in updater_root.iterdir()
            if (
                path.is_file()
                and UPDATER_RELEASE_PATTERN
                .fullmatch(
                    path.name
                )
            )
        ]

    resource_manifest = (
        root
        / "PythoFetch_Resources_Manifest.json"
    )

    if (
        updater_zips
        or resource_manifest.is_file()
    ):
        candidates.append(
            "resources"
        )

    candidates = list(
        dict.fromkeys(
            candidates
        )
    )

    if len(candidates) == 1:
        return candidates[0]

    return None


def normalize_mode(value):
    value = (
        str(value)
        .strip()
        .lower()
    )

    aliases = {
        "source":
            "sourcecode",
        "sourcecode":
            "sourcecode",
        "release":
            "releases",
        "releases":
            "releases",
        "resource":
            "resources",
        "resources":
            "resources",
    }

    return aliases.get(
        value
    )


def ask_mode():
    print()
    print(
        "Auto Detect Failed."
    )
    print(
        "Is this for SourceCode, "
        "Releases or Resources?"
    )

    while True:
        try:
            answer = input(
                "> "
            )
        except EOFError as exc:
            raise RuntimeError(
                "Auto detection failed and no "
                "interactive mode selection "
                "was available."
            ) from exc

        mode = normalize_mode(
            answer
        )

        if mode:
            return mode

        print(
            "Please reply with SourceCode, "
            "Releases or Resources."
        )


def parse_args():
    parser = argparse.ArgumentParser(
        prog=
            "Build_PythoFetchManifests_1.0.0"
    )

    parser.add_argument(
        "--root",
        default=None,
    )

    parser.add_argument(
        "--mode",
        default="auto",
    )

    parser.add_argument(
        "--version",
        action="store_true",
    )

    return parser.parse_args()


def resolve_mode(root, requested_mode):
    requested = (
        str(requested_mode)
        .strip()
        .lower()
    )

    if requested == "auto":
        detected = detect_mode(
            root
        )

        if detected:
            return detected

        return ask_mode()

    normalized = normalize_mode(
        requested
    )

    if normalized is None:
        raise RuntimeError(
            "--mode must be auto, SourceCode, "
            "Releases or Resources."
        )

    return normalized


def relative_display(path, root):
    path = Path(path)

    try:
        return str(
            path.resolve().relative_to(
                root.resolve()
            )
        )
    except Exception:
        return str(
            path
        )


def main():
    args = parse_args()

    if args.version:
        print(
            "PythoFetch Manifest Build Tool "
            f"{BUILD_TOOL_VERSION}"
        )
        return 0

    root = (
        Path(
            args.root
        ).expanduser().resolve()
        if args.root
        else Path(
            __file__
        ).resolve().parent
    )

    if not root.is_dir():
        raise RuntimeError(
            f"Root folder does not exist: {root}"
        )

    mode = resolve_mode(
        root,
        args.mode,
    )

    print()
    print(
        "PythoFetch Manifest Build Tool "
        f"{BUILD_TOOL_VERSION}"
    )
    print(
        "=" * 48
    )
    print(
        f"ROOT: {root}"
    )
    print(
        "MODE: "
        + {
            "sourcecode": "SourceCode",
            "releases": "Releases",
            "resources": "Resources",
        }[
            mode
        ]
    )
    print()

    if mode == "sourcecode":
        paths = build_source_manifests(
            root
        )

    elif mode == "releases":
        paths = [
            build_application_release_manifest(
                root
            )
        ]

    else:
        paths = build_resource_manifests(
            root
        )

    for path in paths:
        print(
            "CREATED: "
            + relative_display(
                path,
                root,
            )
        )

    print()
    print(
        "MANIFEST BUILD COMPLETE"
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )

    except KeyboardInterrupt:
        print()
        print(
            "Manifest build cancelled.",
            file=sys.stderr,
        )
        raise SystemExit(
            130
        )

    except Exception as exc:
        print()
        print(
            "MANIFEST BUILD FAILED: "
            + str(
                exc
            ),
            file=sys.stderr,
        )
        raise SystemExit(
            1
        )
