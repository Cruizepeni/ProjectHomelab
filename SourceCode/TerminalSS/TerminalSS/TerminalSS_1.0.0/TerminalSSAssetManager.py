from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


class TerminalSSAssetManager:
    APP_VERSION = "1.0.0"
    PROTOCOLS = {
        "Matrix": ("MatrixProtocol", "MatrixAssetsPack"),
        "Alien": ("AlienProtocol", "AlienAssetsPack"),
        "DNA": ("DNAProtocol", "DNAAssetsPack"),
        "Hacker": ("HackerProtocol", "HackerAssetsPack"),
        "Arcane": ("ArcaneProtocol", "ArcaneAssetsPack"),
    }
    CHARACTER_INDEX_PREFIX = "CharacterIndex"
    PYTHOFETCH_SOURCE_MANIFEST_URL = "https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/SourceCode/PythoFetch/PythoFetch/PythoFetch_Manifest.json"
    PYTHOFETCH_RELEASE_MANIFEST_URL = "https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Releases/PythoFetch/PythoFetch_Release_Manifest.json"

    def __init__(self, project_root: str | Path, runtime_directory: str | Path):
        self.runtime_directory = Path(runtime_directory).resolve()
        self.project_root = Path(project_root).resolve()
        self.assets_root = self.project_root / "Appdata" / "Assets" / "TerminalSS"
        self.legacy_assets_root = self.project_root / "Appdata" / "Assets" / "EnterTheMatrix"
        self.cache_root = self.project_root / "Appdata" / "Cache" / "TerminalSS"
        if not self.assets_root.exists() and self.legacy_assets_root.is_dir():
            shutil.copytree(self.legacy_assets_root, self.assets_root, dirs_exist_ok=True)
        self.source_mode = not getattr(sys, "frozen", False)
        self.source_feature_root = self._find_source_feature_root() if self.source_mode else None
        self.source_assets_root = self.source_feature_root / "TerminalSSAssets" if self.source_feature_root else None
        self.pythofetch_runtime = self._discover_cached_pythofetch()
        self.pythofetch_version: str | None = None

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"JSON root must be an object: {path}")
        return data

    @staticmethod
    def _fetch_json(url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": "TerminalSS/1.0.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Remote JSON root must be an object: {url}")
        return data

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_extract(archive: Path, destination: Path) -> None:
        destination = destination.resolve()
        with zipfile.ZipFile(archive, "r") as bundle:
            for member in bundle.infolist():
                target = (destination / member.filename).resolve()
                try:
                    target.relative_to(destination)
                except ValueError as exc:
                    raise ValueError("Asset archive contains an unsafe path.") from exc
            bundle.extractall(destination)

    @staticmethod
    def _version_key(value: str) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in str(value).split("."))
        except Exception:
            return (0,)

    @classmethod
    def _compatibility_family(cls) -> str:
        parts = cls.APP_VERSION.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else cls.APP_VERSION

    @staticmethod
    def _version_from_folder(name: str, prefix: str) -> str | None:
        marker = prefix + "_"
        if not name.startswith(marker):
            return None
        value = name[len(marker):]
        parts = value.split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            return None
        return value

    @classmethod
    def _compatible_version(cls, version: str) -> bool:
        return ".".join(version.split(".")[:2]) == cls._compatibility_family()

    def _find_source_feature_root(self) -> Path | None:
        current = self.runtime_directory
        for candidate in (current, *current.parents):
            if (candidate / "TerminalSS_Source_Manifest.json").is_file():
                return candidate
            if (candidate / "TerminalSSAssets").is_dir() and (candidate / "TerminalSS").is_dir():
                return candidate
        return None

    @staticmethod
    def _pack_candidates(root: Path, prefix: str) -> list[tuple[str, Path]]:
        if not root.is_dir():
            return []
        result = []
        for path in root.iterdir():
            if not path.is_dir():
                continue
            version = TerminalSSAssetManager._version_from_folder(path.name, prefix)
            if version is not None:
                result.append((version, path))
        return result

    def _latest_compatible_pack(self, root: Path, prefix: str) -> tuple[str, Path] | None:
        candidates = [item for item in self._pack_candidates(root, prefix) if self._compatible_version(item[0])]
        if not candidates:
            return None
        return max(candidates, key=lambda item: self._version_key(item[0]))

    def protocol_root(self, protocol: str) -> Path:
        spec = self.PROTOCOLS.get(protocol)
        if spec is None:
            return self.assets_root / f"{protocol}Protocol"
        return self.assets_root / spec[0]

    def protocol_path(self, protocol: str) -> Path:
        return self.protocol_root(protocol)

    def protocol_custom_path(self, protocol: str) -> Path:
        return self.protocol_root(protocol) / "Custom"

    def _ensure_custom_layout(self, protocol: str) -> Path:
        custom = self.protocol_custom_path(protocol)
        custom.mkdir(parents=True, exist_ok=True)
        if protocol == "Matrix":
            (custom / "Custom_Art").mkdir(parents=True, exist_ok=True)
        return custom

    def active_protocol_pack(self, protocol: str) -> tuple[str, Path] | None:
        spec = self.PROTOCOLS.get(protocol)
        if spec is None:
            return None
        return self._latest_compatible_pack(self.protocol_root(protocol), spec[1])

    def source_protocol_pack(self, protocol: str) -> tuple[str, Path] | None:
        if self.source_assets_root is None:
            return None
        spec = self.PROTOCOLS.get(protocol)
        if spec is None:
            return None
        return self._latest_compatible_pack(self.source_assets_root / spec[0], spec[1])

    def _copy_pack(self, source: Path, destination: Path, replace: bool) -> None:
        if replace and destination.exists():
            shutil.rmtree(destination)
        if not destination.exists():
            shutil.copytree(source, destination)

    def install_protocol(self, protocol: str, replace: bool = False) -> str:
        spec = self.PROTOCOLS.get(protocol)
        if spec is None:
            raise KeyError(f"TerminalSS has no managed asset protocol named {protocol}.")
        protocol_root = self.protocol_root(protocol)
        protocol_root.mkdir(parents=True, exist_ok=True)
        self._ensure_custom_layout(protocol)
        if self.source_mode:
            source_record = self.source_protocol_pack(protocol)
            if source_record is None:
                raise FileNotFoundError(f"No compatible local source asset pack was found for {protocol}.")
            version, source = source_record
            destination = protocol_root / source.name
            self._copy_pack(source, destination, replace)
            return version
        installed = self.active_protocol_pack(protocol)
        if installed is not None:
            return installed[0]
        raise FileNotFoundError(f"No installed {protocol} asset pack is available. Release-manifest provisioning has not been configured yet.")

    def ensure_protocol(self, protocol: str) -> str | None:
        if protocol not in self.PROTOCOLS:
            return None
        self.protocol_root(protocol).mkdir(parents=True, exist_ok=True)
        self._ensure_custom_layout(protocol)
        installed = self.active_protocol_pack(protocol)
        if self.source_mode:
            source_record = self.source_protocol_pack(protocol)
            if source_record is not None:
                source_version, source_path = source_record
                if installed is None or self._version_key(source_version) > self._version_key(installed[0]):
                    destination = self.protocol_root(protocol) / source_path.name
                    self._copy_pack(source_path, destination, False)
                    return source_version
        if installed is not None:
            return installed[0]
        return self.install_protocol(protocol, replace=False)

    def protocol_asset_roots(self, protocol: str) -> list[Path]:
        self.ensure_protocol(protocol)
        result = []
        active = self.active_protocol_pack(protocol)
        if active is not None:
            result.append(active[1])
        custom = self._ensure_custom_layout(protocol)
        result.append(custom)
        return result

    def protocol_text_files(self, protocol: str) -> list[Path]:
        files = []
        seen = set()
        for root in self.protocol_asset_roots(protocol):
            for path in sorted(root.rglob("*.txt")):
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    files.append(path)
        return files

    def repair_protocol(self, protocol: str) -> str:
        if self.source_mode:
            return self.install_protocol(protocol, replace=True)
        raise FileNotFoundError("Release-manifest asset repair has not been configured yet.")

    def rebuild_protocol(self, protocol: str) -> str:
        return self.repair_protocol(protocol)

    def rebuild_all(self, protocols: list[str] | tuple[str, ...]) -> dict[str, str]:
        return {protocol: self.rebuild_protocol(protocol) for protocol in protocols if protocol in self.PROTOCOLS}

    def character_index_root(self) -> Path:
        return self.assets_root / "CharacterIndex"

    def source_character_index(self) -> tuple[str, Path] | None:
        if self.source_assets_root is None:
            return None
        return self._latest_compatible_pack(self.source_assets_root / "CharacterIndex", self.CHARACTER_INDEX_PREFIX)

    def active_character_index(self) -> tuple[str, Path] | None:
        return self._latest_compatible_pack(self.character_index_root(), self.CHARACTER_INDEX_PREFIX)

    def ensure_shared_assets(self) -> None:
        self.assets_root.mkdir(parents=True, exist_ok=True)
        installed = self.active_character_index()
        if self.source_mode:
            source = self.source_character_index()
            if source is not None and (installed is None or self._version_key(source[0]) > self._version_key(installed[0])):
                destination = self.character_index_root() / source[1].name
                destination.parent.mkdir(parents=True, exist_ok=True)
                self._copy_pack(source[1], destination, False)
                installed = (source[0], destination)
        if installed is None and not self.source_mode:
            raise FileNotFoundError("CharacterIndex is not installed. Release-manifest provisioning has not been configured yet.")

    def character_set(self, name: str, fallback: str = "") -> tuple[str, ...]:
        self.ensure_shared_assets()
        record = self.active_character_index()
        if record is None:
            return tuple(fallback)
        path = record[1] / f"CharacterIndex_{record[0]}.json"
        if not path.is_file():
            return tuple(fallback)
        try:
            document = self._read_json(path)
        except Exception:
            return tuple(fallback)
        sets = document.get("Curated Protocol Sets")
        value = sets.get(name) if isinstance(sets, dict) else None
        pool = []
        if isinstance(value, str):
            pool.extend(value)
        elif isinstance(value, dict):
            glyphs = value.get("Glyphs", "")
            tokens = value.get("Tokens", [])
            if isinstance(glyphs, str):
                pool.extend(glyphs)
            if isinstance(tokens, list):
                pool.extend(str(token) for token in tokens if isinstance(token, str))
        unique = []
        seen = set()
        for token in pool:
            if token and token not in seen:
                seen.add(token)
                unique.append(token)
        return tuple(unique) or tuple(fallback)

    @staticmethod
    def _verified_size(path: Path, expected_size: Any) -> bool:
        if expected_size in (None, ""):
            return True
        try:
            return path.stat().st_size == int(expected_size)
        except Exception:
            return False

    def _verified_file(self, path: Path, checksum: Any, size: Any = None) -> bool:
        if not path.is_file() or not self._verified_size(path, size):
            return False
        expected = str(checksum or "").strip().lower()
        if not expected:
            return True
        return self._sha256(path).lower() == expected

    @staticmethod
    def _fetch_bytes(url: str, timeout: int = 60) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "TerminalSS/1.0.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    def _download_verified_file(self, record: dict[str, Any], destination: Path) -> Path:
        url = record.get("download_url")
        if not isinstance(url, str) or not url:
            raise ValueError("Download record has no URL.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".download")
        if temporary.exists():
            temporary.unlink()
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "TerminalSS/1.0.0"})
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as handle:
                shutil.copyfileobj(response, handle)
            if not self._verified_file(temporary, record.get("sha256"), record.get("size_bytes")):
                raise ValueError(f"Downloaded file failed verification: {destination.name}")
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        return destination

    @staticmethod
    def _normalized_platform() -> str:
        system = platform.system()
        if system == "Windows":
            return "Windows"
        if system == "Linux":
            return "Linux"
        if system == "Darwin":
            return "macOS"
        return system

    @staticmethod
    def _normalized_architecture() -> str:
        machine = str(platform.machine() or "").strip().lower()
        if machine in {"x86_64", "amd64", "x64"}:
            return "x86_64"
        if machine in {"arm64", "aarch64"}:
            return "arm64"
        if machine in {"universal", "universal2"}:
            return "Universal"
        return machine or "Unknown"

    def pythofetch_path(self) -> Path:
        return self.assets_root / "PythoFetchProtocol"

    def _discover_cached_pythofetch(self) -> Path | None:
        directory = self.pythofetch_path()
        if not directory.is_dir():
            return None
        if self.source_mode:
            candidate = directory / "PythoFetch.py"
            return candidate if candidate.is_file() else None
        system = platform.system()
        names = {
            "Windows": "PythoFetch.exe",
            "Linux": "PythoFetch.AppImage",
            "Darwin": "PythoFetch.app",
        }
        name = names.get(system)
        if not name:
            return None
        candidate = directory / name
        return candidate if candidate.exists() else None

    def _ensure_pythofetch_source(self, force: bool = False) -> str:
        manifest = self._fetch_json(self.PYTHOFETCH_SOURCE_MANIFEST_URL)
        version = str(manifest.get("latest_version") or "").strip()
        versions = manifest.get("versions")
        release = versions.get(version) if isinstance(versions, dict) else None
        source = release.get("source") if isinstance(release, dict) else None
        database = release.get("art_database") if isinstance(release, dict) else None
        if not version or not isinstance(source, dict) or not isinstance(database, dict):
            raise ValueError("PythoFetch source manifest has no valid latest source/database pair.")
        directory = self.pythofetch_path()
        directory.mkdir(parents=True, exist_ok=True)
        runtime = directory / "PythoFetch.py"
        database_name = str(database.get("file") or f"PythoFetchArt_{version}.db")
        database_path = directory / database_name
        if force or not self._verified_file(runtime, source.get("sha256"), source.get("size_bytes")):
            self._download_verified_file(source, runtime)
        if force or not self._verified_file(database_path, database.get("sha256"), database.get("size_bytes")):
            self._download_verified_file(database, database_path)
        for path in directory.glob("PythoFetchArt_*.db"):
            if path != database_path and path.is_file():
                path.unlink()
        self.pythofetch_runtime = runtime
        self.pythofetch_version = version
        return version

    def _select_pythofetch_release_asset(self, release: dict[str, Any]) -> dict[str, Any]:
        assets = release.get("assets")
        if not isinstance(assets, dict):
            raise ValueError("PythoFetch release has no assets map.")
        system = self._normalized_platform()
        arch = self._normalized_architecture()
        candidates = []
        if arch != "Unknown":
            candidates.append(f"{system}_{arch}")
        candidates.extend((f"{system}_Universal", "Universal"))
        lookup = {str(key).casefold(): value for key, value in assets.items()}
        for candidate in candidates:
            record = lookup.get(candidate.casefold())
            if isinstance(record, dict):
                return record
        raise RuntimeError(f"PythoFetch has no release asset for {system} {arch}.")

    def _ensure_pythofetch_release(self, force: bool = False) -> str:
        manifest = self._fetch_json(self.PYTHOFETCH_RELEASE_MANIFEST_URL)
        version = str(manifest.get("latest_version") or "").strip()
        releases = manifest.get("releases")
        release = releases.get(version) if isinstance(releases, dict) else None
        if not version or not isinstance(release, dict):
            raise ValueError("PythoFetch release manifest has no valid latest release.")
        asset = self._select_pythofetch_release_asset(release)
        executable = asset.get("executable")
        if not isinstance(executable, str) or not executable:
            raise ValueError("PythoFetch release asset does not identify its executable.")
        destination = self.pythofetch_path() / executable
        executable_hash = asset.get("executable_sha256")
        executable_size = asset.get("executable_size_bytes")
        if not force and self._verified_file(destination, executable_hash, executable_size):
            self.pythofetch_runtime = destination
            self.pythofetch_version = version
            return version
        self.cache_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.cache_root) as temp_name:
            temp = Path(temp_name)
            package = self._download_verified_file(asset, temp / str(asset.get("file") or f"PythoFetch_{version}.zip"))
            extract = temp / "extract"
            extract.mkdir(parents=True, exist_ok=True)
            self._safe_extract(package, extract)
            matches = [path for path in extract.rglob(executable) if path.is_file()]
            if len(matches) != 1:
                raise ValueError("PythoFetch release package does not contain exactly one expected executable.")
            source = matches[0]
            if executable_hash and self._sha256(source).lower() != str(executable_hash).strip().lower():
                raise ValueError("Extracted PythoFetch executable failed SHA-256 verification.")
            if executable_size not in (None, "") and source.stat().st_size != int(executable_size):
                raise ValueError("Extracted PythoFetch executable size does not match the release manifest.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if os.name != "nt":
            destination.chmod(destination.stat().st_mode | 0o111)
        self.pythofetch_runtime = destination
        self.pythofetch_version = version
        return version

    def ensure_pythofetch(self, force: bool = False) -> str:
        cached = self._discover_cached_pythofetch()
        try:
            if self.source_mode:
                return self._ensure_pythofetch_source(force)
            return self._ensure_pythofetch_release(force)
        except Exception:
            if cached is None:
                raise
            self.pythofetch_runtime = cached
            return self.pythofetch_version or "cached"

    def pythofetch_command(self) -> list[str]:
        runtime = self.pythofetch_runtime or self._discover_cached_pythofetch()
        if runtime is None:
            raise FileNotFoundError("PythoFetch is not installed in the TerminalSS PythoFetchProtocol asset folder.")
        self.pythofetch_runtime = runtime
        if runtime.suffix.casefold() == ".py":
            return [sys.executable, str(runtime)]
        if runtime.suffix.casefold() == ".app":
            return ["open", "-W", str(runtime), "--args"]
        return [str(runtime)]

    def ensure_all(self, protocols: list[str] | tuple[str, ...]) -> dict[str, str | None]:
        self.ensure_shared_assets()
        return {protocol: self.ensure_protocol(protocol) for protocol in protocols if protocol in self.PROTOCOLS}

    def status(self) -> dict[str, Any]:
        packs = {}
        for protocol in self.PROTOCOLS:
            record = self.active_protocol_pack(protocol)
            packs[protocol] = {"Version": record[0], "Path": str(record[1])} if record else None
        character_index = self.active_character_index()
        return {
            "RuntimeDirectory": str(self.runtime_directory),
            "ProjectRoot": str(self.project_root),
            "AssetsRoot": str(self.assets_root),
            "SourceMode": self.source_mode,
            "SourceFeatureRoot": str(self.source_feature_root) if self.source_feature_root else None,
            "CharacterIndex": {"Version": character_index[0], "Path": str(character_index[1])} if character_index else None,
            "ProtocolPacks": packs,
            "PythoFetchRuntime": str(self.pythofetch_runtime) if self.pythofetch_runtime else None,
            "PythoFetchVersion": self.pythofetch_version,
        }
