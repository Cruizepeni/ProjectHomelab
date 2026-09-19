from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import platform as host_platform
import re
import shutil
import stat
import subprocess
import tarfile
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

try:
    from .EmuKitLauncher import EmuKitLauncher
except ImportError:
    from EmuKitLauncher import EmuKitLauncher


class EmuKitManager:
    CORE_VERSION = "1.0.0"
    REGISTRY_VERSION = 2
    MODULE_INFO_VERSION = 1
    REMOTE_MANIFEST_SCHEMAS = {1, 2}
    CATALOGUE_SCHEMA = 1
    MODULE_INFO_PATTERN = "EmuKit*Info.json"

    REPOSITORY = "Cruizepeni/ProjectHomelab"
    REPOSITORY_BRANCH = "main"
    DEVELOPMENT_FEED = "SourceCode/EmuKit"
    RELEASE_FEED = "Releases/EmuKit"

    CORE_DEPENDENCIES = {
        "7zip": {
            "Name": "7-Zip",
            "Version": "26.03",
            "RequiredOn": ["Windows", "Linux", "Mac"],
            "RootManifestURL": (
                "https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/"
                "main/Resources/7Zip/7Zip_Manifest.json"
            ),
            "LocalRootManifest": "Resources/7Zip/7Zip_Manifest.json",
        },
        "vcredist": {
            "Name": "Microsoft Visual C++ v14 Redistributable",
            "Version": "Latest supported",
            "RequiredOn": ["Windows"],
            "URL": "https://aka.ms/vc14/vc_redist.x64.exe",
            "FileName": "vc_redist.x64.exe",
        },
    }

    def __init__(
        self,
        settings,
        project_root: str | Path,
        emukit_root: str | Path,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        *,
        channel: str | None = None,
    ) -> None:
        self.settings = settings
        self.project_root = Path(project_root).resolve()
        self.emukit_root = Path(emukit_root).resolve()
        self.module_root = self.emukit_root / "EmuKitModules"
        self.emulators_root = self.project_root / "Emulators"
        self.dependencies_root = self.project_root / "Dependencies"

        self.registry_path = self.project_root / "Appdata" / "Registry" / "EmuKitRegistry.json"
        self.staging_root = self.project_root / "Appdata" / "Cache" / "EmuKit" / "ModuleStaging"
        self.host_platform = self._canonical_platform()
        self.host_architecture = self._canonical_architecture()
        self.catalogue_cache_path = self.project_root / "Appdata" / "Cache" / "EmuKit" / "Catalogues" / f"EmuKit_{self.host_platform}_Catalogue.json"

        self.channel = self._resolve_channel(channel)
        feed_override = os.environ.get("EMUKIT_FEED_BASE_URL", "").strip()
        if feed_override:
            self.feed_base_url = feed_override.rstrip("/") + "/"
            self.feed_relative_root = "<override>"
        else:
            self.feed_relative_root = (
                self.DEVELOPMENT_FEED if self.channel == "development" else self.RELEASE_FEED
            )
            self.feed_base_url = (
                f"https://raw.githubusercontent.com/{self.REPOSITORY}/"
                f"{self.REPOSITORY_BRANCH}/{self.feed_relative_root}/"
            )

        self.platform_feed_base_url = (
            f"{self.feed_base_url}EmulatorModules/{self.host_platform}/"
        )
        platform_manifest_name = (
            f"EmuKit_{self.host_platform}_Manifest.json"
            if self.channel == "development"
            else f"EmuKit_{self.host_platform}_Release_Manifest.json"
        )
        self.remote_manifest_url = f"{self.platform_feed_base_url}{platform_manifest_name}"

        self.launcher = EmuKitLauncher(settings=self.settings, project_root=self.project_root)

        self._operation_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._registry_document = self._empty_registry_document()
        self._module_import_cache: dict[str, ModuleType] = {}
        self._current_operation: dict[str, Any] | None = None
        self._initialized = False
        self._last_sync_errors: list[dict[str, Any]] = []
        self._core_dependency_status: dict[str, dict[str, Any]] = {}
        self._progress_callback = progress_callback

        self._remote_manifest: dict[str, Any] | None = None
        self._remote_manifest_error: dict[str, Any] | None = None
        self._remote_manifest_loaded = False
        self._remote_catalogue: dict[str, Any] | None = None
        self._remote_catalogue_error: dict[str, Any] | None = None


    @staticmethod
    def _canonical_platform() -> str:
        value = host_platform.system().casefold()
        if value == "windows":
            return "Windows"
        if value == "linux":
            return "Linux"
        if value == "darwin":
            return "Mac"
        return host_platform.system() or "Unknown"

    @staticmethod
    def _canonical_architecture() -> str:
        value = host_platform.machine().casefold()
        if value in {"amd64", "x86_64", "x64"}:
            return "x86_64"
        if value in {"arm64", "aarch64"}:
            return "arm64"
        return value or "unknown"

    @staticmethod
    def _resolve_channel(requested: str | None) -> str:
        value = requested or os.environ.get("EMUKIT_CHANNEL")
        if isinstance(value, str) and value.strip():
            normalized = value.strip().casefold()
            if normalized in {"development", "dev", "source"}:
                return "development"
            if normalized in {"release", "target", "production", "prod"}:
                return "release"
            raise ValueError(f'Unsupported EmuKit channel "{value}".')
        return "release" if getattr(sys, "frozen", False) else "development"


    def set_progress_callback(
        self,
        callback: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        self._progress_callback = callback

    def _emit_progress(
        self,
        module_id: str,
        operation: str,
        percent: int | float | None = None,
        stage: str | None = None,
        message: str | None = None,
    ) -> None:
        callback = self._progress_callback
        if callback is None:
            return
        value: dict[str, Any] = {
            "module": module_id,
            "operation": operation,
            "percent": None,
            "stage": stage,
            "message": message,
        }
        if isinstance(percent, (int, float)):
            value["percent"] = max(0, min(100, int(percent)))
        try:
            callback(value)
        except Exception:
            pass

    @staticmethod
    def _valid_string(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _valid_id(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value) is not None

    @classmethod
    def _valid_aliases(cls, value: Any) -> bool:
        return value is None or (
            isinstance(value, list)
            and all(cls._valid_string(item) for item in value)
        )

    @staticmethod
    def _valid_sha256(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

    @staticmethod
    def _lookup_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.casefold())

    @staticmethod
    def _version_key(value: Any) -> tuple:
        if not isinstance(value, str):
            return ()
        parts: list[tuple[int, Any]] = []
        for part in re.split(r"([0-9]+)", value.casefold()):
            if not part:
                continue
            if part.isdigit():
                parts.append((1, int(part)))
            else:
                parts.append((0, part))
        return tuple(parts)

    def _portable_path(self, path: Path) -> str:
        path = path.resolve()
        try:
            return str(path.relative_to(self.project_root)).replace("\\", "/")
        except ValueError:
            return str(path)

    def _resolve_registered_path(self, configured_path: str) -> Path:
        path = Path(configured_path)
        if path.is_absolute():
            return path.resolve()
        return (self.project_root / path).resolve()


    @staticmethod
    def _read_7zip_version(executable: Path) -> str | None:
        try:
            completed = subprocess.run(
                [str(executable)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            output = f"{completed.stdout}\n{completed.stderr}"
            match = re.search(r"7-Zip\s+([0-9.]+)", output, re.IGNORECASE)
            return match.group(1) if match else None
        except Exception:
            return None

    def _7zip_target_key(self) -> str | None:
        platform_id = {
            "Windows": "windows",
            "Linux": "linux",
            "Mac": "mac",
        }.get(self.host_platform)
        if platform_id is None or self.host_architecture not in {"x86_64", "arm64"}:
            return None
        return f"{platform_id}-{self.host_architecture}"

    def _managed_7zip_executable(self) -> Path:
        executable_name = "7z.exe" if self.host_platform == "Windows" else "7zz"
        return (
            self.dependencies_root
            / "7Zip"
            / self.CORE_DEPENDENCIES["7zip"]["Version"]
            / self.host_platform
            / self.host_architecture
            / executable_name
        )

    def _load_json_document(self, source: str | Path) -> dict[str, Any]:
        if isinstance(source, Path):
            with source.open("r", encoding="utf-8") as handle:
                document = json.load(handle)
        else:
            request = urllib.request.Request(
                source,
                headers={"User-Agent": f"ProjectHomelab-EmuKit/{self.CORE_VERSION}"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                document = json.loads(response.read().decode("utf-8"))
        if not isinstance(document, dict):
            raise ValueError("Resource manifest root must be a JSON object.")
        return document

    def _resolve_7zip_resource(self) -> dict[str, Any]:
        config = self.CORE_DEPENDENCIES["7zip"]
        required_version = config["Version"]
        local_root_manifest = self.project_root / config["LocalRootManifest"]
        root_source: str | Path = (
            local_root_manifest
            if local_root_manifest.is_file()
            else config["RootManifestURL"]
        )
        root_manifest = self._load_json_document(root_source)

        if root_manifest.get("schema_version") != 1:
            raise ValueError("Unsupported 7-Zip root resource manifest schema.")
        if root_manifest.get("resource_id") != "7zip":
            raise ValueError("7-Zip root resource manifest has an invalid resource_id.")

        versions = root_manifest.get("versions")
        if not isinstance(versions, dict):
            raise ValueError("7-Zip root resource manifest has no versions map.")
        version_entry = versions.get(required_version)
        if not isinstance(version_entry, dict):
            raise ValueError(f'7-Zip version "{required_version}" is not available.')
        if str(version_entry.get("status", "")).casefold() != "supported":
            raise ValueError(f'7-Zip version "{required_version}" is not supported.')

        manifest_relative = version_entry.get("manifest")
        if not isinstance(manifest_relative, str) or not manifest_relative.strip():
            raise ValueError("7-Zip version entry does not provide a manifest path.")

        local_version_manifest = (
            local_root_manifest.parent / Path(manifest_relative.replace("/", os.sep))
        )
        raw_base_url = root_manifest.get("raw_base_url")
        if not isinstance(raw_base_url, str) or not raw_base_url.strip():
            raise ValueError("7-Zip root resource manifest has no raw_base_url.")
        version_manifest_url = (
            raw_base_url.rstrip("/") + "/" + manifest_relative.lstrip("/")
        )
        version_source: str | Path = (
            local_version_manifest
            if local_version_manifest.is_file()
            else version_manifest_url
        )
        version_manifest = self._load_json_document(version_source)

        if version_manifest.get("schema_version") != 1:
            raise ValueError("Unsupported 7-Zip version resource manifest schema.")
        if version_manifest.get("resource_id") != "7zip":
            raise ValueError("7-Zip version resource manifest has an invalid resource_id.")
        if str(version_manifest.get("version")) != required_version:
            raise ValueError("7-Zip version resource manifest does not match the pinned version.")

        target_key = self._7zip_target_key()
        if target_key is None:
            raise ValueError(
                f'7-Zip is not defined for {self.host_platform}/{self.host_architecture}.'
            )
        targets = version_manifest.get("targets")
        target = targets.get(target_key) if isinstance(targets, dict) else None
        if not isinstance(target, dict):
            raise ValueError(f'7-Zip target "{target_key}" is not available.')

        artifact = target.get("artifact")
        sha256 = target.get("sha256")
        executable_name = target.get("executable_name")
        install = target.get("install")
        if not isinstance(artifact, str) or not artifact.strip():
            raise ValueError("7-Zip target has no artifact path.")
        if not self._valid_sha256(sha256):
            raise ValueError("7-Zip target has an invalid SHA-256 value.")
        if not isinstance(executable_name, str) or not executable_name.strip():
            raise ValueError("7-Zip target has no executable_name.")
        if not isinstance(install, dict) or not isinstance(install.get("method"), str):
            raise ValueError("7-Zip target has no valid install method.")

        version_directory = manifest_relative.rsplit("/", 1)[0] if "/" in manifest_relative else ""
        artifact_relative = (
            f"{version_directory}/{artifact}" if version_directory else artifact
        )
        artifact_url = raw_base_url.rstrip("/") + "/" + artifact_relative.lstrip("/")
        local_artifact = (
            local_root_manifest.parent
            / Path(artifact_relative.replace("/", os.sep))
        )

        return {
            "root_manifest": root_manifest,
            "version_manifest": version_manifest,
            "target_key": target_key,
            "target": copy.deepcopy(target),
            "artifact_url": artifact_url,
            "local_artifact": local_artifact,
        }

    def _check_7zip(self) -> dict[str, Any]:
        required = self.host_platform in self.CORE_DEPENDENCIES["7zip"]["RequiredOn"]
        if not required:
            return {
                "success": True,
                "dependency": "7zip",
                "state": "not_required",
                "installed": True,
                "message": "7-Zip is not a required EmuKit Core dependency on this host.",
                "details": {
                    "required": False,
                    "resource_version": self.CORE_DEPENDENCIES["7zip"]["Version"],
                },
            }

        candidates: list[Path] = [self._managed_7zip_executable()]
        for command_name in ("7z", "7zz"):
            found = shutil.which(command_name)
            if found:
                candidates.append(Path(found))

        if self.host_platform == "Windows":
            for program_root in (
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramFiles(x86)"),
            ):
                if program_root:
                    candidates.append(Path(program_root) / "7-Zip" / "7z.exe")

        required_version = self.CORE_DEPENDENCIES["7zip"]["Version"]
        seen: set[str] = set()
        incompatible: list[dict[str, str | None]] = []
        for candidate in candidates:
            key = str(candidate).casefold()
            if key in seen:
                continue
            seen.add(key)
            if not candidate.is_file():
                continue
            version = self._read_7zip_version(candidate)
            if version is not None and self._version_key(version) < self._version_key(required_version):
                incompatible.append({"path": str(candidate), "version": version})
                continue
            return {
                "success": True,
                "dependency": "7zip",
                "state": "installed",
                "installed": True,
                "message": f'7-Zip found at "{candidate}".',
                "details": {
                    "required": True,
                    "path": str(candidate),
                    "version": version,
                    "resource_version": required_version,
                },
            }

        return {
            "success": True,
            "dependency": "7zip",
            "state": "missing",
            "installed": False,
            "message": "7-Zip 26.03 or newer is not installed or could not be found.",
            "details": {
                "required": True,
                "resource_version": required_version,
                "incompatible": incompatible,
            },
        }

    def _check_vcredist(self) -> dict[str, Any]:
        required = self.host_platform in self.CORE_DEPENDENCIES["vcredist"]["RequiredOn"]
        if not required:
            return {
                "success": True,
                "dependency": "vcredist",
                "state": "not_required",
                "installed": True,
                "message": "Microsoft Visual C++ v14 Redistributable is not required on this host.",
                "details": {
                    "required": False,
                    "version": self.CORE_DEPENDENCIES["vcredist"]["Version"],
                },
            }

        try:
            import winreg
        except ImportError:
            return {
                "success": True,
                "dependency": "vcredist",
                "state": "missing",
                "installed": False,
                "message": "Microsoft Visual C++ v14 Redistributable could not be detected.",
                "details": {
                    "required": True,
                    "version": self.CORE_DEPENDENCIES["vcredist"]["Version"],
                },
            }

        runtime_arches = ["arm64", "x64"] if self.host_architecture == "arm64" else ["x64"]
        registry_views = [
            getattr(winreg, "KEY_WOW64_64KEY", 0),
            getattr(winreg, "KEY_WOW64_32KEY", 0),
        ]
        seen_views: set[int] = set()

        for view in registry_views:
            if view in seen_views:
                continue
            seen_views.add(view)
            for runtime_arch in runtime_arches:
                path = (
                    "SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\"
                    f"{runtime_arch}"
                )
                try:
                    access = winreg.KEY_READ | view
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, access) as key:
                        installed, _ = winreg.QueryValueEx(key, "Installed")
                        version, _ = winreg.QueryValueEx(key, "Version")
                    if int(installed) == 1:
                        return {
                            "success": True,
                            "dependency": "vcredist",
                            "state": "installed",
                            "installed": True,
                            "message": (
                                "Microsoft Visual C++ v14 Redistributable "
                                f'was found ({version}).'
                            ),
                            "details": {
                                "required": True,
                                "version": str(version),
                                "architecture": runtime_arch,
                            },
                        }
                except (FileNotFoundError, OSError, ValueError, TypeError):
                    continue

        return {
            "success": True,
            "dependency": "vcredist",
            "state": "missing",
            "installed": False,
            "message": "Microsoft Visual C++ v14 Redistributable is not installed.",
            "details": {
                "required": True,
                "version": self.CORE_DEPENDENCIES["vcredist"]["Version"],
            },
        }

    def check_core_dependencies(self) -> dict[str, Any]:
        checks = {
            "7zip": self._check_7zip(),
            "vcredist": self._check_vcredist(),
        }
        missing = [
            dep_id
            for dep_id, result in checks.items()
            if result.get("state") == "missing"
        ]
        with self._state_lock:
            self._core_dependency_status = copy.deepcopy(checks)
        return {
            "success": not missing,
            "operation": "core_dependency_check",
            "state": "missing_dependencies" if missing else "ready",
            "message": (
                "EmuKit is missing one or more required shared dependencies."
                if missing
                else "EmuKit shared dependencies are ready."
            ),
            "details": checks,
            "missing": missing,
        }

    def _core_dependency_cache(self) -> Path:
        return (
            self.project_root
            / "Appdata"
            / "Cache"
            / "EmuKit"
            / "CoreDependencies"
        )

    def _download_core_dependency(
        self,
        url: str,
        destination: Path,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_suffix(destination.suffix + ".download")
        if temp_path.exists():
            temp_path.unlink()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"ProjectHomelab-EmuKit/{self.CORE_VERSION}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                with temp_path.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
            temp_path.replace(destination)
            return destination
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _install_7zip(self) -> dict[str, Any]:
        try:
            resource = self._resolve_7zip_resource()
        except Exception as exc:
            return {
                "success": False,
                "dependency": "7zip",
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "resource_manifest_error",
                "message": "The controlled 7-Zip resource could not be resolved.",
                "details": str(exc),
            }

        target = resource["target"]
        artifact_name = Path(str(target["artifact"])).name
        expected_sha = str(target["sha256"])
        local_artifact = Path(resource["local_artifact"])
        cached_artifact = (
            self._core_dependency_cache()
            / "7Zip"
            / self.CORE_DEPENDENCIES["7zip"]["Version"]
            / resource["target_key"]
            / artifact_name
        )

        artifact: Path | None = None
        if (
            local_artifact.is_file()
            and self._sha256_file(local_artifact) == expected_sha
        ):
            artifact = local_artifact
        elif (
            cached_artifact.is_file()
            and self._sha256_file(cached_artifact) == expected_sha
        ):
            artifact = cached_artifact
        else:
            try:
                artifact = self._download_core_dependency(
                    resource["artifact_url"],
                    cached_artifact,
                )
            except Exception as exc:
                return {
                    "success": False,
                    "dependency": "7zip",
                    "operation": "install_core_dependency",
                    "state": "install_failed",
                    "error": "download_failed",
                    "message": "7-Zip could not be downloaded from the controlled resource repository.",
                    "details": str(exc),
                }

        actual_sha = self._sha256_file(artifact)
        if actual_sha != expected_sha:
            return {
                "success": False,
                "dependency": "7zip",
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "checksum_mismatch",
                "message": "The 7-Zip artifact failed SHA-256 verification.",
                "details": {
                    "expected": expected_sha,
                    "actual": actual_sha,
                },
            }

        install = target["install"]
        method = str(install["method"]).casefold()
        if method == "exe":
            silent_args = install.get("silent_args", [])
            if not isinstance(silent_args, list) or not all(
                isinstance(item, str) for item in silent_args
            ):
                return {
                    "success": False,
                    "dependency": "7zip",
                    "operation": "install_core_dependency",
                    "state": "install_failed",
                    "error": "invalid_install_metadata",
                    "message": "The 7-Zip installer metadata is invalid.",
                    "details": None,
                }
            try:
                completed = subprocess.run([str(artifact), *silent_args], check=False)
            except Exception as exc:
                return {
                    "success": False,
                    "dependency": "7zip",
                    "operation": "install_core_dependency",
                    "state": "install_failed",
                    "error": "installer_exception",
                    "message": "7-Zip could not be installed.",
                    "details": str(exc),
                }
            verified = self._check_7zip()
            if verified.get("installed"):
                return {
                    "success": True,
                    "dependency": "7zip",
                    "operation": "install_core_dependency",
                    "state": (
                        "installed_reboot_required"
                        if completed.returncode == 3010
                        else "installed"
                    ),
                    "message": "7-Zip installed successfully.",
                    "details": verified.get("details"),
                }
            return {
                "success": False,
                "dependency": "7zip",
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "installer_failed",
                "message": "7-Zip installation did not complete successfully.",
                "details": {"returncode": completed.returncode},
            }

        if method == "extract":
            executable_name = str(target["executable_name"])
            managed_executable = self._managed_7zip_executable()
            managed_directory = managed_executable.parent
            try:
                with tarfile.open(artifact, "r:*") as archive:
                    matches = [
                        member
                        for member in archive.getmembers()
                        if member.isfile()
                        and Path(member.name).name == executable_name
                    ]
                    if not matches:
                        raise FileNotFoundError(
                            f'Archive does not contain "{executable_name}".'
                        )
                    member = min(matches, key=lambda value: len(Path(value.name).parts))
                    source = archive.extractfile(member)
                    if source is None:
                        raise OSError(
                            f'Archive entry "{member.name}" could not be read.'
                        )
                    managed_directory.mkdir(parents=True, exist_ok=True)
                    temporary = managed_executable.with_suffix(
                        managed_executable.suffix + ".installing"
                    )
                    if temporary.exists():
                        temporary.unlink()
                    with source, temporary.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    os.chmod(temporary, 0o755)
                    temporary.replace(managed_executable)
            except Exception as exc:
                return {
                    "success": False,
                    "dependency": "7zip",
                    "operation": "install_core_dependency",
                    "state": "install_failed",
                    "error": "extract_failed",
                    "message": "7-Zip could not be extracted into the shared dependency directory.",
                    "details": str(exc),
                }

            verified = self._check_7zip()
            if verified.get("installed"):
                return {
                    "success": True,
                    "dependency": "7zip",
                    "operation": "install_core_dependency",
                    "state": "installed",
                    "message": "7-Zip installed successfully.",
                    "details": verified.get("details"),
                }
            return {
                "success": False,
                "dependency": "7zip",
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "verification_failed",
                "message": "7-Zip was extracted but could not be verified.",
                "details": {"path": str(managed_executable)},
            }

        return {
            "success": False,
            "dependency": "7zip",
            "operation": "install_core_dependency",
            "state": "install_failed",
            "error": "unsupported_install_method",
            "message": f'Unsupported 7-Zip install method "{install["method"]}".',
            "details": None,
        }

    def _install_vcredist(self) -> dict[str, Any]:
        if self.host_platform != "Windows":
            return {
                "success": False,
                "dependency": "vcredist",
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "automatic_install_not_supported",
                "message": (
                    "Microsoft Visual C++ v14 Redistributable installation "
                    "is only defined for Windows."
                ),
                "details": None,
            }

        config = self.CORE_DEPENDENCIES["vcredist"]
        installer = (
            self._core_dependency_cache()
            / "VisualCpp"
            / config["FileName"]
        )

        try:
            installer = self._download_core_dependency(config["URL"], installer)
        except Exception as exc:
            if not installer.is_file():
                return {
                    "success": False,
                    "dependency": "vcredist",
                    "operation": "install_core_dependency",
                    "state": "install_failed",
                    "error": "download_failed",
                    "message": (
                        "Microsoft Visual C++ v14 Redistributable could not "
                        "be downloaded from Microsoft."
                    ),
                    "details": str(exc),
                }

        try:
            completed = subprocess.run(
                [
                    str(installer),
                    "/install",
                    "/quiet",
                    "/norestart",
                ],
                check=False,
            )
            verified = self._check_vcredist()
            if verified.get("installed"):
                return {
                    "success": True,
                    "dependency": "vcredist",
                    "operation": "install_core_dependency",
                    "state": (
                        "installed_reboot_required"
                        if completed.returncode == 3010
                        else "installed"
                    ),
                    "message": (
                        "Microsoft Visual C++ v14 Redistributable "
                        "installed successfully."
                    ),
                    "details": verified.get("details"),
                }
            return {
                "success": False,
                "dependency": "vcredist",
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "installer_failed",
                "message": (
                    "Microsoft Visual C++ v14 Redistributable installation "
                    "did not complete successfully."
                ),
                "details": {"returncode": completed.returncode},
            }
        except Exception as exc:
            return {
                "success": False,
                "dependency": "vcredist",
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "installer_exception",
                "message": (
                    "Microsoft Visual C++ v14 Redistributable could not "
                    "be installed."
                ),
                "details": str(exc),
            }

    def install_core_dependency(self, dependency_id: str) -> dict[str, Any]:
        normalized = dependency_id.strip().casefold()
        if normalized == "7zip":
            return self._install_7zip()
        if normalized in {"vcredist", "visualcpp", "visualc++", "vc++"}:
            return self._install_vcredist()
        return {
            "success": False,
            "operation": "install_core_dependency",
            "state": "install_failed",
            "error": "dependency_not_found",
            "message": f'Unknown EmuKit Core dependency "{dependency_id}".',
            "details": None,
        }

    def install_missing_core_dependencies(self) -> dict[str, Any]:
        before = self.check_core_dependencies()
        missing = list(before.get("missing") or [])
        if not missing:
            return {
                "success": True,
                "operation": "install_core_dependencies",
                "state": "ready",
                "message": "EmuKit shared dependencies are already ready.",
                "details": {
                    "results": [],
                    "check": before,
                },
            }

        results = [
            self.install_core_dependency(dependency_id)
            for dependency_id in missing
        ]
        after = self.check_core_dependencies()
        reboot_required = any(
            result.get("state") == "installed_reboot_required"
            for result in results
        )

        return {
            "success": after.get("state") == "ready",
            "operation": "install_core_dependencies",
            "state": (
                "installed_reboot_required"
                if after.get("state") == "ready" and reboot_required
                else "installed"
                if after.get("state") == "ready"
                else "install_failed"
            ),
            "message": (
                "EmuKit shared dependencies installed successfully."
                if after.get("state") == "ready"
                else "EmuKit could not install all required shared dependencies."
            ),
            "details": {
                "results": results,
                "check": after,
            },
        }

    def _empty_registry_document(self) -> dict[str, Any]:
        return {
            "Version": self.REGISTRY_VERSION,
            "CoreVersion": self.CORE_VERSION,
            "Modules": {},
            "Brands": {},
            "Platforms": {},
            "Systems": {},
        }

    def _backup_corrupt_registry(self) -> None:
        if not self.registry_path.exists():
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.registry_path.with_name(
            f"{self.registry_path.stem}.corrupt-{stamp}{self.registry_path.suffix}"
        )
        index = 1
        while target.exists():
            target = self.registry_path.with_name(
                f"{self.registry_path.stem}.corrupt-{stamp}-{index}{self.registry_path.suffix}"
            )
            index += 1
        self.registry_path.replace(target)

    def _atomic_write_registry(self, document: dict[str, Any]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.registry_path.with_suffix(self.registry_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(self.registry_path)

    @classmethod
    def _validate_identity(cls, value: Any, label: str) -> str | None:
        if not isinstance(value, dict):
            return f'{label} must be an object containing "Id" and "Name".'
        if not cls._valid_id(value.get("Id")):
            return f'{label} must provide a lowercase machine-safe "Id".'
        if not cls._valid_string(value.get("Name")):
            return f'{label} must provide a non-empty "Name".'
        if not cls._valid_aliases(value.get("Aliases")):
            return f'{label} "Aliases" must be a list of non-empty strings.'
        return None

    def _validate_module_info(
        self,
        info: Any,
        *,
        info_path: Path,
    ) -> tuple[bool, str | None]:
        if not isinstance(info, dict):
            return False, "Info file root must be a JSON object."
        if info.get("Version") != self.MODULE_INFO_VERSION:
            return False, f'Module Info "Version" must be {self.MODULE_INFO_VERSION}.'
        if not self._valid_id(info.get("Id")):
            return False, 'Module "Id" must be lowercase and machine-safe.'

        for key in ("Name", "Manager", "DependencyPath", "LaunchPath"):
            if not self._valid_string(info.get(key)):
                return False, f'Missing or invalid required field "{key}".'

        dependency_path = Path(info["DependencyPath"])
        if dependency_path.is_absolute():
            return False, 'Module "DependencyPath" must be relative to the resolved ROOT.'
        resolved_dependency = (self.project_root / dependency_path).resolve()
        try:
            resolved_dependency.relative_to(self.emulators_root.resolve())
        except ValueError:
            return False, (
                'Module "DependencyPath" must resolve inside ROOT/Emulators.'
            )
        if resolved_dependency == self.emulators_root.resolve():
            return False, (
                'Module "DependencyPath" must identify a child directory inside ROOT/Emulators.'
            )

        if not self._valid_aliases(info.get("Aliases")):
            return False, 'Module "Aliases" must be a list of non-empty strings.'

        for key in ("ModuleVersion", "EmulatorVersion"):
            if key in info and not self._valid_string(info.get(key)):
                return False, f'Module "{key}" must be a non-empty string when provided.'

        if "DefaultInstalled" in info and not isinstance(info.get("DefaultInstalled"), bool):
            return False, 'Module "DefaultInstalled" must be a boolean.'

        if "IsolateLaunchConsole" in info and not isinstance(info.get("IsolateLaunchConsole"), bool):
            return False, 'Module "IsolateLaunchConsole" must be a boolean.'

        if "WorkingDirectory" in info and not self._valid_string(info.get("WorkingDirectory")):
            return False, 'Module "WorkingDirectory" must be a non-empty string.'

        emulator_launch_args = info.get("EmulatorLaunchArguments", [])
        if not isinstance(emulator_launch_args, list) or not all(
            isinstance(item, str) for item in emulator_launch_args
        ):
            return False, 'Module "EmulatorLaunchArguments" must be a list of strings.'

        systems = info.get("Systems")
        if not isinstance(systems, dict) or not systems:
            return False, 'Field "Systems" must contain at least one system.'

        for system_id, system_info in systems.items():
            if not self._valid_id(system_id):
                return False, "System ids must be lowercase and machine-safe."
            if not isinstance(system_info, dict):
                return False, f'System "{system_id}" registration must be an object.'
            if not self._valid_string(system_info.get("Name")):
                return False, f'System "{system_id}" must provide a non-empty "Name".'
            if not self._valid_aliases(system_info.get("Aliases")):
                return False, f'System "{system_id}" "Aliases" must be a list of non-empty strings.'

            brand_error = self._validate_identity(
                system_info.get("Brand"),
                f'System "{system_id}" Brand',
            )
            if brand_error:
                return False, brand_error

            platform_error = self._validate_identity(
                system_info.get("Platform"),
                f'System "{system_id}" Platform',
            )
            if platform_error:
                return False, platform_error

            launch_args = system_info.get("LaunchArguments")
            if not isinstance(launch_args, list) or not all(
                isinstance(item, str) for item in launch_args
            ):
                return False, (
                    f'System "{system_id}" must provide "LaunchArguments" as a list of strings.'
                )

            if "LaunchPath" in system_info and not self._valid_string(system_info.get("LaunchPath")):
                return False, f'System "{system_id}" has invalid "LaunchPath".'

            if "WorkingDirectory" in system_info and not self._valid_string(
                system_info.get("WorkingDirectory")
            ):
                return False, f'System "{system_id}" has invalid "WorkingDirectory".'

            fullscreen_arg = system_info.get("FullscreenArgument")
            if fullscreen_arg is not None and not (
                isinstance(fullscreen_arg, str)
                or (
                    isinstance(fullscreen_arg, list)
                    and all(isinstance(item, str) for item in fullscreen_arg)
                )
            ):
                return False, f'System "{system_id}" has invalid "FullscreenArgument".'

            if "IsolateLaunchConsole" in system_info and not isinstance(
                system_info.get("IsolateLaunchConsole"),
                bool,
            ):
                return False, f'System "{system_id}" "IsolateLaunchConsole" must be a boolean.'

        manager_path = info_path.parent / info["Manager"]
        if not manager_path.is_file():
            return False, f'Registered manager entry point was not found: "{manager_path}".'

        return True, None

    def _discover_modules(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        discovered: dict[str, dict[str, Any]] = {}
        errors: list[dict[str, Any]] = []
        duplicate_ids: set[str] = set()

        self.module_root.mkdir(parents=True, exist_ok=True)

        for module_dir in sorted(self.module_root.iterdir()):
            if not module_dir.is_dir():
                continue
            if module_dir.name.startswith("__") or module_dir.name.startswith("."):
                continue

            info_files = sorted(module_dir.glob(self.MODULE_INFO_PATTERN))
            if not info_files:
                continue
            if len(info_files) != 1:
                errors.append({
                    "module": module_dir.name,
                    "error": "multiple_info_files",
                    "message": (
                        f'Module "{module_dir.name}" must contain exactly one '
                        f"{self.MODULE_INFO_PATTERN} file."
                    ),
                })
                continue

            info_path = info_files[0]
            try:
                with info_path.open("r", encoding="utf-8") as handle:
                    info = json.load(handle)
            except (json.JSONDecodeError, OSError) as exc:
                errors.append({
                    "module": module_dir.name,
                    "error": "info_read_failed",
                    "message": f'Module "{module_dir.name}" registration could not be read.',
                    "details": str(exc),
                })
                continue

            valid, reason = self._validate_module_info(info, info_path=info_path)
            if not valid:
                errors.append({
                    "module": module_dir.name,
                    "error": "invalid_registration",
                    "message": f'Module "{module_dir.name}" registration is invalid.',
                    "details": reason,
                })
                continue

            module_id = info["Id"]
            if module_id in discovered:
                duplicate_ids.add(module_id)
                continue

            registration = copy.deepcopy(info)
            registration["Aliases"] = list(registration.get("Aliases") or [])
            registration["DefaultInstalled"] = registration.get("DefaultInstalled", False)
            registration["ModuleVersion"] = registration.get("ModuleVersion", "0.0.0")
            registration["EmulatorVersion"] = registration.get("EmulatorVersion", "unknown")
            registration["EmulatorLaunchArguments"] = list(
                registration.get("EmulatorLaunchArguments") or []
            )

            for system_info in registration["Systems"].values():
                system_info["Aliases"] = list(system_info.get("Aliases") or [])
                system_info["Brand"]["Aliases"] = list(
                    system_info["Brand"].get("Aliases") or []
                )
                system_info["Platform"]["Aliases"] = list(
                    system_info["Platform"].get("Aliases") or []
                )

            registration["ModulePath"] = self._portable_path(info_path.parent)
            registration["InfoPath"] = self._portable_path(info_path)
            discovered[module_id] = registration

        for module_id in duplicate_ids:
            discovered.pop(module_id, None)
            errors.append({
                "module": module_id,
                "error": "duplicate_module_id",
                "message": (
                    f'Multiple EmuKit modules registered module id "{module_id}". '
                    "None were registered."
                ),
            })

        return discovered, errors

    @staticmethod
    def _merge_aliases(existing: list[str], incoming: list[str]) -> list[str]:
        known = {item.casefold() for item in existing}
        result = list(existing)
        for item in incoming:
            if item.casefold() not in known:
                result.append(item)
                known.add(item.casefold())
        return sorted(result, key=str.casefold)

    def _build_catalogue(
        self,
        modules: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        brands: dict[str, dict[str, Any]] = {}
        platforms: dict[str, dict[str, Any]] = {}
        systems: dict[str, dict[str, Any]] = {}
        errors: list[dict[str, Any]] = []

        for module_id, module_info in sorted(modules.items()):
            for system_id, system_info in module_info["Systems"].items():
                brand = system_info["Brand"]
                platform = system_info["Platform"]
                brand_id = brand["Id"]
                platform_id = platform["Id"]

                existing_brand = brands.get(brand_id)
                if existing_brand is None:
                    brands[brand_id] = {
                        "Id": brand_id,
                        "Name": brand["Name"],
                        "Aliases": sorted(brand.get("Aliases", []), key=str.casefold),
                        "Systems": [],
                    }
                elif existing_brand["Name"].casefold() != brand["Name"].casefold():
                    errors.append({
                        "module": module_id,
                        "error": "brand_metadata_conflict",
                        "message": f'Brand id "{brand_id}" has conflicting names.',
                    })
                    continue
                else:
                    existing_brand["Aliases"] = self._merge_aliases(
                        existing_brand["Aliases"],
                        brand.get("Aliases", []),
                    )

                existing_platform = platforms.get(platform_id)
                if existing_platform is None:
                    platforms[platform_id] = {
                        "Id": platform_id,
                        "Name": platform["Name"],
                        "Aliases": sorted(platform.get("Aliases", []), key=str.casefold),
                        "Systems": [],
                    }
                elif existing_platform["Name"].casefold() != platform["Name"].casefold():
                    errors.append({
                        "module": module_id,
                        "error": "platform_metadata_conflict",
                        "message": f'Platform id "{platform_id}" has conflicting names.',
                    })
                    continue
                else:
                    existing_platform["Aliases"] = self._merge_aliases(
                        existing_platform["Aliases"],
                        platform.get("Aliases", []),
                    )

                existing_system = systems.get(system_id)
                if existing_system is None:
                    systems[system_id] = {
                        "Id": system_id,
                        "Name": system_info["Name"],
                        "Aliases": sorted(system_info.get("Aliases", []), key=str.casefold),
                        "BrandId": brand_id,
                        "PlatformId": platform_id,
                        "Modules": [],
                        "DefaultModule": None,
                    }
                else:
                    if existing_system["Name"].casefold() != system_info["Name"].casefold():
                        errors.append({
                            "module": module_id,
                            "error": "system_metadata_conflict",
                            "message": f'System id "{system_id}" has conflicting names.',
                        })
                        continue
                    if (
                        existing_system["BrandId"] != brand_id
                        or existing_system["PlatformId"] != platform_id
                    ):
                        errors.append({
                            "module": module_id,
                            "error": "system_identity_conflict",
                            "message": (
                                f'System id "{system_id}" has conflicting brand/platform identity.'
                            ),
                        })
                        continue
                    existing_system["Aliases"] = self._merge_aliases(
                        existing_system["Aliases"],
                        system_info.get("Aliases", []),
                    )

                if system_id not in brands[brand_id]["Systems"]:
                    brands[brand_id]["Systems"].append(system_id)
                if system_id not in platforms[platform_id]["Systems"]:
                    platforms[platform_id]["Systems"].append(system_id)
                if module_id not in systems[system_id]["Modules"]:
                    systems[system_id]["Modules"].append(module_id)

        for record in brands.values():
            record["Systems"].sort()
        for record in platforms.values():
            record["Systems"].sort()
        recommendations = self._catalogue_recommendations()
        for system_id, record in systems.items():
            record["Modules"].sort()
            recommended = recommendations.get(system_id)
            if recommended in record["Modules"]:
                record["DefaultModule"] = recommended

        return brands, platforms, systems, errors

    def sync_registry(self) -> dict[str, Any]:
        modules, discovery_errors = self._discover_modules()
        brands, platforms, systems, catalogue_errors = self._build_catalogue(modules)
        errors = discovery_errors + catalogue_errors
        document = {
            "Version": self.REGISTRY_VERSION,
            "CoreVersion": self.CORE_VERSION,
            "Modules": modules,
            "Brands": brands,
            "Platforms": platforms,
            "Systems": systems,
        }

        with self._state_lock:
            self._registry_document = copy.deepcopy(document)
            self._last_sync_errors = copy.deepcopy(errors)
            self._module_import_cache = {
                module_id: module
                for module_id, module in self._module_import_cache.items()
                if module_id in modules
            }

        self._atomic_write_registry(document)
        return {
            "success": not errors,
            "operation": "registry_sync",
            "state": "synced" if not errors else "synced_with_errors",
            "message": (
                "EmuKit registry synchronized."
                if not errors
                else "EmuKit registry synchronized with module registration errors."
            ),
            "details": errors,
        }

    def get_registry(self) -> dict[str, Any]:
        with self._state_lock:
            return copy.deepcopy(self._registry_document)

    def get_modules(self) -> dict[str, dict[str, Any]]:
        return self.get_registry()["Modules"]

    def get_local_module_info(self, module_id: str) -> dict[str, Any] | None:
        value = self.get_modules().get(module_id)
        return copy.deepcopy(value) if isinstance(value, dict) else None

    def _resolve_from_records(
        self,
        query: str,
        records: dict[str, dict[str, Any]],
    ) -> str | None:
        target = self._lookup_key(query)
        matches: list[str] = []
        for record_id, record in records.items():
            values = [record_id, record.get("Name", ""), *record.get("Aliases", [])]
            if any(
                self._lookup_key(value) == target
                for value in values
                if isinstance(value, str)
            ):
                matches.append(record_id)
        return matches[0] if len(matches) == 1 else None

    def resolve_local_module_id(self, query: str) -> str | None:
        return self._resolve_from_records(query, self.get_modules())

    def resolve_brand_id(self, query: str) -> str | None:
        return self._resolve_from_records(query, self.get_registry()["Brands"])

    def resolve_platform_id(self, query: str) -> str | None:
        return self._resolve_from_records(query, self.get_registry()["Platforms"])

    def resolve_system_id(self, query: str) -> str | None:
        return self._resolve_from_records(query, self.get_registry()["Systems"])


    def _validate_catalogue_descriptor(self, value: Any) -> tuple[bool, str | None]:
        if not isinstance(value, dict):
            return False, 'Remote manifest "Catalogue" must be an object.'
        if value.get("SchemaVersion") != self.CATALOGUE_SCHEMA:
            return False, f'Remote catalogue descriptor "SchemaVersion" must be {self.CATALOGUE_SCHEMA}.'
        version = value.get("Version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            return False, 'Remote catalogue descriptor "Version" must be a positive integer.'
        if not self._valid_string(value.get("File")):
            return False, 'Remote catalogue descriptor "File" must be a non-empty string.'
        file_path = Path(value["File"])
        if file_path.is_absolute() or ".." in file_path.parts:
            return False, 'Remote catalogue descriptor "File" must be a safe platform-feed-relative path.'
        if not self._valid_sha256(value.get("SHA256")):
            return False, 'Remote catalogue descriptor must provide a lowercase SHA-256.'
        return True, None

    def _validate_remote_manifest(
        self,
        manifest: Any,
    ) -> tuple[bool, str | None]:
        if not isinstance(manifest, dict):
            return False, "Remote manifest root must be an object."
        schema = manifest.get("SchemaVersion")
        if schema not in self.REMOTE_MANIFEST_SCHEMAS:
            allowed = ", ".join(str(value) for value in sorted(self.REMOTE_MANIFEST_SCHEMAS))
            return False, f'Remote manifest "SchemaVersion" must be one of: {allowed}.'
        if manifest.get("Platform") != self.host_platform:
            return False, (
                f'Remote manifest Platform must be "{self.host_platform}" '
                f'on this host.'
            )
        if schema >= 2:
            valid_catalogue, catalogue_reason = self._validate_catalogue_descriptor(manifest.get("Catalogue"))
            if not valid_catalogue:
                return False, catalogue_reason
        modules = manifest.get("Modules")
        if not isinstance(modules, dict):
            return False, 'Remote manifest "Modules" must be an object.'

        for module_id, entry in modules.items():
            if not self._valid_id(module_id):
                return False, f'Remote module id "{module_id}" is invalid.'
            if not isinstance(entry, dict):
                return False, f'Remote module "{module_id}" must be an object.'
            for key in ("Name", "Version", "Package"):
                if not self._valid_string(entry.get(key)):
                    return False, (
                        f'Remote module "{module_id}" has invalid "{key}".'
                    )
            if not self._valid_aliases(entry.get("Aliases")):
                return False, (
                    f'Remote module "{module_id}" "Aliases" must be a list '
                    "of non-empty strings."
                )
            if not self._valid_sha256(entry.get("SHA256")):
                return False, (
                    f'Remote module "{module_id}" must provide a lowercase SHA-256.'
                )
            package = Path(entry["Package"])
            if package.is_absolute() or ".." in package.parts:
                return False, (
                    f'Remote module "{module_id}" Package must be a safe relative path.'
                )
        return True, None

    def _validate_remote_catalogue(
        self,
        catalogue: Any,
        manifest: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        if not isinstance(catalogue, dict):
            return False, "Remote catalogue root must be an object."
        if catalogue.get("SchemaVersion") != self.CATALOGUE_SCHEMA:
            return False, f'Remote catalogue "SchemaVersion" must be {self.CATALOGUE_SCHEMA}.'
        version = catalogue.get("Version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            return False, 'Remote catalogue "Version" must be a positive integer.'
        if catalogue.get("Platform") != self.host_platform:
            return False, f'Remote catalogue Platform must be "{self.host_platform}" on this host.'
        emulators = catalogue.get("Emulators")
        brands = catalogue.get("Brands")
        if not isinstance(emulators, dict) or not isinstance(brands, dict):
            return False, 'Remote catalogue must contain "Emulators" and "Brands" objects.'

        emulator_systems: dict[str, set[str]] = {}
        for emulator_id, emulator in emulators.items():
            if not self._valid_id(emulator_id):
                return False, f'Remote catalogue emulator id "{emulator_id}" is invalid.'
            if not isinstance(emulator, dict) or not self._valid_string(emulator.get("Name")):
                return False, f'Remote catalogue emulator "{emulator_id}" has invalid metadata.'
            if not self._valid_aliases(emulator.get("Aliases")):
                return False, f'Remote catalogue emulator "{emulator_id}" has invalid aliases.'
            supported = emulator.get("Systems")
            if not isinstance(supported, list) or not supported or not all(self._valid_id(item) for item in supported):
                return False, f'Remote catalogue emulator "{emulator_id}" must provide valid systems.'
            if len(set(supported)) != len(supported):
                return False, f'Remote catalogue emulator "{emulator_id}" contains duplicate systems.'
            emulator_systems[emulator_id] = set(supported)

        seen_systems: set[str] = set()
        system_emulators: dict[str, set[str]] = {}
        for brand_id, brand in brands.items():
            if not self._valid_id(brand_id):
                return False, f'Remote catalogue brand id "{brand_id}" is invalid.'
            if not isinstance(brand, dict) or not self._valid_string(brand.get("Name")):
                return False, f'Remote catalogue brand "{brand_id}" has invalid metadata.'
            if not self._valid_aliases(brand.get("Aliases")):
                return False, f'Remote catalogue brand "{brand_id}" has invalid aliases.'
            systems = brand.get("Systems")
            if not isinstance(systems, dict) or not systems:
                return False, f'Remote catalogue brand "{brand_id}" must contain systems.'
            for system_id, system in systems.items():
                if not self._valid_id(system_id):
                    return False, f'Remote catalogue system id "{system_id}" is invalid.'
                if system_id in seen_systems:
                    return False, f'Remote catalogue system "{system_id}" is registered under multiple brands.'
                seen_systems.add(system_id)
                if not isinstance(system, dict) or not self._valid_string(system.get("Name")):
                    return False, f'Remote catalogue system "{system_id}" has invalid metadata.'
                if not self._valid_aliases(system.get("Aliases")):
                    return False, f'Remote catalogue system "{system_id}" has invalid aliases.'
                supporting = system.get("Emulators")
                if not isinstance(supporting, list) or not supporting or not all(self._valid_id(item) for item in supporting):
                    return False, f'Remote catalogue system "{system_id}" must provide valid emulators.'
                if len(set(supporting)) != len(supporting):
                    return False, f'Remote catalogue system "{system_id}" contains duplicate emulators.'
                recommended = system.get("RecommendedPrimary")
                if not self._valid_id(recommended) or recommended not in supporting:
                    return False, f'Remote catalogue system "{system_id}" has an invalid RecommendedPrimary.'
                system_emulators[system_id] = set(supporting)

        for emulator_id, supported in emulator_systems.items():
            for system_id in supported:
                if system_id not in system_emulators:
                    return False, f'Remote catalogue emulator "{emulator_id}" references unknown system "{system_id}".'
                if emulator_id not in system_emulators[system_id]:
                    return False, f'Remote catalogue relationship "{emulator_id}" -> "{system_id}" is not bidirectional.'
        for system_id, supporting in system_emulators.items():
            for emulator_id in supporting:
                if emulator_id not in emulator_systems:
                    return False, f'Remote catalogue system "{system_id}" references unknown emulator "{emulator_id}".'
                if system_id not in emulator_systems[emulator_id]:
                    return False, f'Remote catalogue relationship "{system_id}" -> "{emulator_id}" is not bidirectional.'

        if isinstance(manifest, dict):
            manifest_modules = set(manifest.get("Modules", {}))
            if manifest_modules != set(emulators):
                return False, "Remote catalogue emulator ids must exactly match the Windows module manifest."
            descriptor = manifest.get("Catalogue")
            if isinstance(descriptor, dict):
                if descriptor.get("SchemaVersion") != catalogue.get("SchemaVersion"):
                    return False, "Remote catalogue schema does not match its manifest descriptor."
                if descriptor.get("Version") != catalogue.get("Version"):
                    return False, "Remote catalogue version does not match its manifest descriptor."
        return True, None

    def _catalogue_recommendations(self) -> dict[str, str]:
        with self._state_lock:
            catalogue = copy.deepcopy(self._remote_catalogue)
        if not isinstance(catalogue, dict):
            return {}
        recommendations: dict[str, str] = {}
        for brand in catalogue.get("Brands", {}).values():
            if not isinstance(brand, dict):
                continue
            for system_id, system in brand.get("Systems", {}).items():
                if not isinstance(system, dict):
                    continue
                recommended = system.get("RecommendedPrimary")
                if self._valid_id(system_id) and self._valid_id(recommended):
                    recommendations[system_id] = recommended
        return recommendations

    def _load_cached_catalogue(self, expected_sha256: str | None = None) -> dict[str, Any] | None:
        if not self.catalogue_cache_path.is_file():
            return None
        try:
            raw = self.catalogue_cache_path.read_bytes()
            if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
                return None
            catalogue = json.loads(raw.decode("utf-8"))
            valid, reason = self._validate_remote_catalogue(catalogue)
            if not valid:
                raise ValueError(reason or "Cached catalogue is invalid.")
            return catalogue
        except Exception:
            return None

    def _refresh_remote_catalogue(self, manifest: dict[str, Any]) -> dict[str, Any]:
        descriptor = manifest.get("Catalogue")
        if not isinstance(descriptor, dict):
            cached = self._load_cached_catalogue()
            with self._state_lock:
                self._remote_catalogue = cached
                self._remote_catalogue_error = None
            return {
                "success": True,
                "operation": "remote_catalogue",
                "state": "not_advertised",
                "message": "Remote manifest does not advertise a platform catalogue.",
                "details": None,
            }

        expected_sha = descriptor["SHA256"]
        cached = self._load_cached_catalogue(expected_sha)
        if cached is not None:
            valid, reason = self._validate_remote_catalogue(cached, manifest)
            if valid:
                with self._state_lock:
                    self._remote_catalogue = copy.deepcopy(cached)
                    self._remote_catalogue_error = None
                return {
                    "success": True,
                    "operation": "remote_catalogue",
                    "state": "cached",
                    "message": f'Using cached EmuKit {self.host_platform} catalogue.',
                    "details": {
                        "version": cached["Version"],
                        "sha256": expected_sha,
                        "path": str(self.catalogue_cache_path),
                    },
                }
            raise ValueError(reason or "Cached catalogue is invalid.")

        catalogue_url = urllib.parse.urljoin(self.platform_feed_base_url, descriptor["File"])
        try:
            request = urllib.request.Request(
                catalogue_url,
                headers={"User-Agent": f"ProjectHomelab-EmuKit/{self.CORE_VERSION}"},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != expected_sha:
                raise ValueError(f'Catalogue SHA-256 mismatch: expected {expected_sha}, got {actual_sha}.')
            catalogue = json.loads(raw.decode("utf-8"))
            valid, reason = self._validate_remote_catalogue(catalogue, manifest)
            if not valid:
                raise ValueError(reason or "Remote catalogue is invalid.")
            self.catalogue_cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.catalogue_cache_path.with_suffix(self.catalogue_cache_path.suffix + ".tmp")
            temp_path.write_bytes(raw)
            temp_path.replace(self.catalogue_cache_path)
            with self._state_lock:
                self._remote_catalogue = copy.deepcopy(catalogue)
                self._remote_catalogue_error = None
            return {
                "success": True,
                "operation": "remote_catalogue",
                "state": "downloaded",
                "message": f'Loaded EmuKit {self.host_platform} catalogue version {catalogue["Version"]}.',
                "details": {
                    "version": catalogue["Version"],
                    "sha256": actual_sha,
                    "url": catalogue_url,
                    "path": str(self.catalogue_cache_path),
                },
            }
        except Exception as exc:
            fallback = self._load_cached_catalogue()
            error = {
                "success": False,
                "operation": "remote_catalogue",
                "state": "unavailable",
                "error": "catalogue_unavailable",
                "message": "Remote EmuKit platform catalogue is unavailable.",
                "details": str(exc),
            }
            with self._state_lock:
                self._remote_catalogue = fallback
                self._remote_catalogue_error = copy.deepcopy(error)
            return error

    def refresh_remote_manifest(self) -> dict[str, Any]:
        try:
            request = urllib.request.Request(
                self.remote_manifest_url,
                headers={"User-Agent": f"ProjectHomelab-EmuKit/{self.CORE_VERSION}"},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
            manifest = json.loads(raw)
            valid, reason = self._validate_remote_manifest(manifest)
            if not valid:
                raise ValueError(reason or "Remote manifest is invalid.")

            normalized = copy.deepcopy(manifest)
            for entry in normalized["Modules"].values():
                entry["Aliases"] = list(entry.get("Aliases") or [])

            with self._state_lock:
                self._remote_manifest = normalized
                self._remote_manifest_error = None
                self._remote_manifest_loaded = True

            catalogue = self._refresh_remote_catalogue(normalized)
            return {
                "success": bool(catalogue.get("success", True)),
                "operation": "remote_manifest",
                "state": "loaded" if catalogue.get("success", True) else "loaded_with_catalogue_error",
                "message": (
                    f'Loaded EmuKit {self.host_platform} module manifest '
                    f'from the {self.channel} channel.'
                ),
                "details": {
                    "channel": self.channel,
                    "platform": self.host_platform,
                    "url": self.remote_manifest_url,
                    "module_count": len(normalized["Modules"]),
                    "catalogue": catalogue,
                },
            }
        except Exception as exc:
            cached = self._load_cached_catalogue()
            error = {
                "success": False,
                "operation": "remote_manifest",
                "state": "unavailable",
                "error": "manifest_unavailable",
                "message": (
                    "Remote EmuKit module manifest is unavailable. "
                    "Local installed modules remain usable."
                ),
                "details": str(exc),
            }
            with self._state_lock:
                self._remote_manifest = None
                self._remote_manifest_error = copy.deepcopy(error)
                self._remote_manifest_loaded = True
                self._remote_catalogue = cached
            return error

    def _ensure_remote_manifest(self) -> dict[str, Any] | None:
        with self._state_lock:
            loaded = self._remote_manifest_loaded
            manifest = copy.deepcopy(self._remote_manifest)
        if not loaded:
            self.refresh_remote_manifest()
            with self._state_lock:
                manifest = copy.deepcopy(self._remote_manifest)
        return manifest

    def get_remote_manifest(self, *, refresh: bool = False) -> dict[str, Any] | None:
        if refresh:
            self.refresh_remote_manifest()
        return self._ensure_remote_manifest()

    def get_remote_modules(self) -> dict[str, dict[str, Any]]:
        manifest = self._ensure_remote_manifest()
        if not isinstance(manifest, dict):
            return {}
        modules = manifest.get("Modules", {})
        return copy.deepcopy(modules) if isinstance(modules, dict) else {}

    def resolve_remote_module_id(self, query: str) -> str | None:
        return self._resolve_from_records(query, self.get_remote_modules())

    def resolve_module_id(self, query: str) -> str | None:
        local_id = self.resolve_local_module_id(query)
        if local_id is not None:
            return local_id
        return self.resolve_remote_module_id(query)

    def get_module_info(self, module_id: str) -> dict[str, Any] | None:
        local = self.get_local_module_info(module_id)
        if local is not None:
            remote = self.get_remote_modules().get(module_id)
            local["LocalInstalled"] = True
            local["RemoteAvailable"] = remote is not None
            if isinstance(remote, dict):
                local["RemoteModuleVersion"] = remote.get("Version")
                local["ModuleUpdateAvailable"] = (
                    self._version_key(remote.get("Version"))
                    > self._version_key(local.get("ModuleVersion"))
                )
            else:
                local["RemoteModuleVersion"] = None
                local["ModuleUpdateAvailable"] = False
            return local

        remote = self.get_remote_modules().get(module_id)
        if not isinstance(remote, dict):
            return None
        return {
            "Id": module_id,
            "Name": remote["Name"],
            "Aliases": list(remote.get("Aliases") or []),
            "ModuleVersion": remote["Version"],
            "RemoteModuleVersion": remote["Version"],
            "LocalInstalled": False,
            "RemoteAvailable": True,
            "ModuleUpdateAvailable": False,
            "Distribution": copy.deepcopy(remote),
            "Systems": {},
        }

    def get_available_modules(self) -> list[dict[str, Any]]:
        local = self.get_modules()
        remote = self.get_remote_modules()
        ids = sorted(
            set(local) | set(remote),
            key=lambda module_id: (
                (local.get(module_id) or remote.get(module_id) or {}).get(
                    "Name", module_id
                ).casefold()
            ),
        )
        result: list[dict[str, Any]] = []
        for module_id in ids:
            info = self.get_module_info(module_id)
            if info is not None:
                result.append(info)
        return result


    def get_supported_modules(self) -> list[dict[str, Any]]:
        return self.get_available_modules()

    def get_supported_brands(self) -> list[dict[str, Any]]:
        brands = self.get_registry()["Brands"]
        return [
            copy.deepcopy(brands[brand_id])
            for brand_id in sorted(
                brands,
                key=lambda item: brands[item]["Name"].casefold(),
            )
        ]

    def get_supported_platforms(self) -> list[dict[str, Any]]:
        platforms = self.get_registry()["Platforms"]
        return [
            copy.deepcopy(platforms[platform_id])
            for platform_id in sorted(
                platforms,
                key=lambda item: platforms[item]["Name"].casefold(),
            )
        ]

    def get_supported_systems(
        self,
        *,
        brand: str | None = None,
        platform: str | None = None,
    ) -> list[dict[str, Any]]:
        registry = self.get_registry()
        brand_id = self.resolve_brand_id(brand) if brand is not None else None
        platform_id = (
            self.resolve_platform_id(platform)
            if platform is not None
            else None
        )
        if brand is not None and brand_id is None:
            return []
        if platform is not None and platform_id is None:
            return []

        values: list[dict[str, Any]] = []
        for system in registry["Systems"].values():
            if brand_id is not None and system["BrandId"] != brand_id:
                continue
            if platform_id is not None and system["PlatformId"] != platform_id:
                continue
            item = copy.deepcopy(system)
            brand_info = registry["Brands"].get(item["BrandId"], {})
            item["BrandName"] = brand_info.get("Name", item["BrandId"])
            item["DisplayName"] = f'{item["BrandName"]} {item["Name"]}'
            values.append(item)
        return sorted(values, key=lambda item: item["DisplayName"].casefold())

    def get_brand_info(self, query: str) -> dict[str, Any] | None:
        brand_id = self.resolve_brand_id(query)
        if brand_id is None:
            return None
        registry = self.get_registry()
        result = copy.deepcopy(registry["Brands"][brand_id])
        result["SystemDetails"] = [
            copy.deepcopy(registry["Systems"][system_id])
            for system_id in result["Systems"]
        ]
        return result

    def get_platform_info(self, query: str) -> dict[str, Any] | None:
        platform_id = self.resolve_platform_id(query)
        if platform_id is None:
            return None
        registry = self.get_registry()
        result = copy.deepcopy(registry["Platforms"][platform_id])
        result["SystemDetails"] = [
            copy.deepcopy(registry["Systems"][system_id])
            for system_id in result["Systems"]
        ]
        return result

    def get_system_info(self, query: str) -> dict[str, Any] | None:
        system_id = self.resolve_system_id(query)
        if system_id is None:
            return None
        registry = self.get_registry()
        result = copy.deepcopy(registry["Systems"][system_id])
        result["Brand"] = copy.deepcopy(
            registry["Brands"][result["BrandId"]]
        )
        result["Platform"] = copy.deepcopy(
            registry["Platforms"][result["PlatformId"]]
        )
        result["AssignedModule"] = self.settings.get_system_assignment(system_id)
        result["DisplayName"] = f'{result["Brand"]["Name"]} {result["Name"]}'
        return result

    def sync_settings(self) -> dict[str, Any]:
        registry = self.get_registry()
        modules = registry["Modules"]
        systems = registry["Systems"]

        added_modules: list[str] = []
        removed_modules: list[str] = []
        added_systems: list[str] = []
        removed_systems: list[str] = []
        cleared_assignments: list[str] = []

        for module_id, info in modules.items():
            if self.settings.ensure_module(
                module_id,
                enabled=info.get("DefaultInstalled", False),
            ):
                added_modules.append(module_id)

        snapshot = self.settings.snapshot()
        for module_id in sorted(set(snapshot["Modules"]) - set(modules)):
            if self.settings.remove_module(module_id):
                removed_modules.append(module_id)

        for system_id, info in systems.items():
            if self.settings.ensure_system_assignment(
                system_id,
                info.get("DefaultModule"),
            ):
                added_systems.append(system_id)

        snapshot = self.settings.snapshot()
        for system_id in sorted(
            set(snapshot["SystemAssignments"]) - set(systems)
        ):
            if self.settings.remove_system_assignment(system_id):
                removed_systems.append(system_id)

        snapshot = self.settings.snapshot()
        for system_id, module_id in snapshot["SystemAssignments"].items():
            if module_id is None:
                continue
            supported = systems.get(system_id, {}).get("Modules", [])
            if module_id not in supported:
                self.settings.set_system_assignment(system_id, None)
                cleared_assignments.append(system_id)

        return {
            "success": True,
            "operation": "settings_sync",
            "state": "synced",
            "message": "EmuKit settings synchronized.",
            "details": {
                "added_modules": added_modules,
                "removed_modules": removed_modules,
                "added_systems": added_systems,
                "removed_systems": removed_systems,
                "cleared_assignments": cleared_assignments,
            },
        }


    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_extract_zip(archive: Path, destination: Path) -> None:
        destination = destination.resolve()
        with zipfile.ZipFile(archive, "r") as handle:
            for member in handle.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError(
                        f'Unsafe archive path "{member.filename}".'
                    )

                mode = (member.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise ValueError(
                        f'Symbolic links are not allowed in module packages: '
                        f'"{member.filename}".'
                    )

                target = (destination / member_path).resolve()
                try:
                    target.relative_to(destination)
                except ValueError as exc:
                    raise ValueError(
                        f'Unsafe archive path "{member.filename}".'
                    ) from exc
            handle.extractall(destination)

    def _locate_extracted_module(
        self,
        extract_root: Path,
        expected_module_id: str,
        expected_module_version: str,
    ) -> tuple[Path, dict[str, Any], Path]:
        info_files = sorted(extract_root.rglob(self.MODULE_INFO_PATTERN))
        valid_candidates: list[tuple[Path, dict[str, Any], Path]] = []

        for info_path in info_files:
            try:
                with info_path.open("r", encoding="utf-8") as handle:
                    info = json.load(handle)
            except Exception:
                continue
            valid, _ = self._validate_module_info(info, info_path=info_path)
            if valid:
                valid_candidates.append((info_path.parent, info, info_path))

        if len(valid_candidates) != 1:
            raise ValueError(
                "Module package must contain exactly one valid EmuKit module root."
            )

        module_dir, info, info_path = valid_candidates[0]
        if info["Id"] != expected_module_id:
            raise ValueError(
                f'Package module Id "{info["Id"]}" does not match requested '
                f'manifest module "{expected_module_id}".'
            )

        module_version = info.get("ModuleVersion")
        if (
            isinstance(module_version, str)
            and module_version.strip()
            and module_version != expected_module_version
        ):
            raise ValueError(
                f'Package ModuleVersion "{module_version}" does not match '
                f'manifest Version "{expected_module_version}".'
            )

        return module_dir, info, info_path

    def _module_package_url(self, package: str) -> str:
        normalized = package.replace("\\", "/")
        if normalized.startswith("Resources/"):
            if self.feed_relative_root == "<override>":
                return urllib.parse.urljoin(self.feed_base_url, f"../../{normalized}")
            return (
                f"https://raw.githubusercontent.com/{self.REPOSITORY}/"
                f"{self.REPOSITORY_BRANCH}/{normalized}"
            )
        return urllib.parse.urljoin(self.platform_feed_base_url, normalized)

    def _download_module_package(
        self,
        module_id: str,
        entry: dict[str, Any],
        destination: Path,
    ) -> None:
        package_url = self._module_package_url(entry["Package"])
        request = urllib.request.Request(
            package_url,
            headers={"User-Agent": f"ProjectHomelab-EmuKit/{self.CORE_VERSION}"},
        )
        package_name = Path(entry["Package"]).name
        self._emit_progress(
            module_id,
            "acquire_module",
            0,
            "Downloading Module",
            package_name,
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            total_raw = response.headers.get("Content-Length")
            total = int(total_raw) if total_raw and total_raw.isdigit() else None
            read = 0
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    read += len(chunk)
                    percent = int((read / total) * 55) if total else None
                    self._emit_progress(
                        module_id,
                        "acquire_module",
                        min(55, percent) if percent is not None else None,
                        "Downloading Module",
                        package_name,
                    )
        self._emit_progress(
            module_id,
            "acquire_module",
            55,
            "Downloading Module",
            package_name,
        )

    def acquire_module(
        self,
        module_query: str,
        *,
        force_replace: bool = False,
    ) -> dict[str, Any]:
        remote_id = self.resolve_remote_module_id(module_query)
        if remote_id is None:
            return {
                "success": False,
                "operation": "acquire_module",
                "state": "acquire_failed",
                "error": "module_not_available",
                "message": (
                    f'Module "{module_query}" is not available from the '
                    f'{self.channel} {self.host_platform} manifest.'
                ),
                "details": None,
            }

        remote_modules = self.get_remote_modules()
        entry = remote_modules[remote_id]
        local_id = self.resolve_local_module_id(remote_id)

        if local_id is not None and not force_replace:
            return {
                "success": True,
                "module": remote_id,
                "operation": "acquire_module",
                "state": "already_installed",
                "message": f'Module "{remote_id}" is already installed locally.',
                "details": self.get_local_module_info(remote_id),
            }

        with self._operation_lock:
            self._current_operation = {
                "module": remote_id,
                "operation": "acquire_module",
            }
            try:
                self.staging_root.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(
                    prefix=f"{remote_id}-",
                    dir=self.staging_root,
                ) as temp_name:
                    temp_root = Path(temp_name)
                    package_path = temp_root / "module.zip"
                    extract_root = temp_root / "extract"
                    extract_root.mkdir(parents=True, exist_ok=True)

                    try:
                        self._download_module_package(
                            remote_id,
                            entry,
                            package_path,
                        )
                    except Exception as exc:
                        return {
                            "success": False,
                            "module": remote_id,
                            "operation": "acquire_module",
                            "state": "acquire_failed",
                            "error": "download_failed",
                            "message": f'Module "{remote_id}" could not be downloaded.',
                            "details": str(exc),
                        }

                    self._emit_progress(
                        remote_id,
                        "acquire_module",
                        60,
                        "Validating Module",
                        Path(entry["Package"]).name,
                    )
                    actual_sha = self._sha256_file(package_path)
                    if actual_sha != entry["SHA256"]:
                        return {
                            "success": False,
                            "module": remote_id,
                            "operation": "acquire_module",
                            "state": "acquire_failed",
                            "error": "checksum_mismatch",
                            "message": (
                                f'Module "{remote_id}" package failed SHA-256 verification.'
                            ),
                            "details": {
                                "expected": entry["SHA256"],
                                "actual": actual_sha,
                            },
                        }

                    try:
                        self._emit_progress(
                            remote_id,
                            "acquire_module",
                            70,
                            "Extracting Module",
                            Path(entry["Package"]).name,
                        )
                        self._safe_extract_zip(package_path, extract_root)
                        module_dir, info, _ = self._locate_extracted_module(
                            extract_root,
                            remote_id,
                            entry["Version"],
                        )
                    except Exception as exc:
                        return {
                            "success": False,
                            "module": remote_id,
                            "operation": "acquire_module",
                            "state": "acquire_failed",
                            "error": "invalid_package",
                            "message": (
                                f'Module "{remote_id}" package is not a valid '
                                "EmuKit module package."
                            ),
                            "details": str(exc),
                        }

                    existing = self.get_local_module_info(remote_id)
                    if existing is not None:
                        destination = self._resolve_registered_path(
                            existing["ModulePath"]
                        )
                    else:
                        if module_dir.resolve() == extract_root.resolve():
                            safe_name = re.sub(
                                r"[^A-Za-z0-9._-]+",
                                "",
                                entry["Name"],
                            ) or remote_id
                            destination = self.module_root / safe_name
                        else:
                            destination = self.module_root / module_dir.name

                    try:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination_resolved = destination.resolve()
                        if destination_resolved.parent != self.module_root.resolve():
                            raise ValueError("Module packages must install as direct children of the EmuKit module root.")
                        if destination_resolved == self.module_root.resolve():
                            raise ValueError("Module destination cannot be the EmuKit Core directory.")
                    except Exception:
                        return {
                            "success": False,
                            "module": remote_id,
                            "operation": "acquire_module",
                            "state": "acquire_failed",
                            "error": "unsafe_destination",
                            "message": "Resolved module destination is unsafe.",
                            "details": str(destination),
                        }

                    backup: Path | None = None
                    try:
                        self._emit_progress(
                            remote_id,
                            "acquire_module",
                            85,
                            "Installing Module",
                            entry["Name"],
                        )

                        if destination.exists():
                            backup = temp_root / "previous-module"
                            if backup.exists():
                                shutil.rmtree(backup, ignore_errors=True)
                            shutil.move(str(destination), str(backup))

                        shutil.copytree(module_dir, destination)
                        self._module_import_cache.pop(remote_id, None)

                        registry_result = self.sync_registry()
                        if remote_id not in self.get_modules():
                            raise RuntimeError(
                                "Installed module package was not discoverable "
                                "after registry synchronization."
                            )

                        settings_result = self.sync_settings()
                        if backup is not None and backup.exists():
                            shutil.rmtree(backup, ignore_errors=True)

                        self._emit_progress(
                            remote_id,
                            "acquire_module",
                            100,
                            "Module Installed",
                            f'Module "{remote_id}" installed successfully.',
                        )
                        return {
                            "success": True,
                            "module": remote_id,
                            "operation": "acquire_module",
                            "state": (
                                "updated" if existing is not None else "installed"
                            ),
                            "message": (
                                f'Module "{remote_id}" package installed successfully.'
                            ),
                            "details": {
                                "module_version": entry["Version"],
                                "sha256": actual_sha,
                                "path": str(destination),
                                "registry": registry_result,
                                "settings": settings_result,
                            },
                        }
                    except Exception as exc:
                        try:
                            if destination.exists():
                                shutil.rmtree(destination, ignore_errors=True)
                            if backup is not None and backup.exists():
                                shutil.move(str(backup), str(destination))
                            self.sync_registry()
                            self.sync_settings()
                        except Exception:
                            pass
                        return {
                            "success": False,
                            "module": remote_id,
                            "operation": "acquire_module",
                            "state": "acquire_failed",
                            "error": "module_install_failed",
                            "message": (
                                f'Module "{remote_id}" package could not be installed.'
                            ),
                            "details": str(exc),
                        }
            finally:
                with self._state_lock:
                    self._current_operation = None

    def remove_module(self, module_query: str) -> dict[str, Any]:
        module_id = self.resolve_local_module_id(module_query)
        if module_id is None:
            return {
                "success": False,
                "operation": "remove_module",
                "state": "remove_failed",
                "error": "module_not_installed",
                "message": f'Module "{module_query}" is not installed locally.',
                "details": None,
            }

        with self._operation_lock:
            info = self.get_local_module_info(module_id)
            if info is None:
                return {
                    "success": False,
                    "module": module_id,
                    "operation": "remove_module",
                    "state": "remove_failed",
                    "error": "module_not_registered",
                    "message": f'Module "{module_id}" is not registered.',
                    "details": None,
                }

            module_path = self._resolve_registered_path(info["ModulePath"])
            try:
                module_path.resolve().relative_to(self.module_root.resolve())
            except ValueError:
                return {
                    "success": False,
                    "module": module_id,
                    "operation": "remove_module",
                    "state": "remove_failed",
                    "error": "unsafe_module_path",
                    "message": "Module path is outside the EmuKit module root.",
                    "details": str(module_path),
                }

            if module_path.resolve() == self.module_root.resolve():
                return {
                    "success": False,
                    "module": module_id,
                    "operation": "remove_module",
                    "state": "remove_failed",
                    "error": "unsafe_module_path",
                    "message": "Refusing to remove the EmuKit Core directory.",
                    "details": str(module_path),
                }

            try:
                shutil.rmtree(module_path)
                self._module_import_cache.pop(module_id, None)
                registry = self.sync_registry()
                settings = self.sync_settings()
                return {
                    "success": True,
                    "module": module_id,
                    "operation": "remove_module",
                    "state": "removed",
                    "message": (
                        f'Module "{module_id}" was removed. '
                        "The emulator installation was left untouched."
                    ),
                    "details": {
                        "registry": registry,
                        "settings": settings,
                    },
                }
            except Exception as exc:
                return {
                    "success": False,
                    "module": module_id,
                    "operation": "remove_module",
                    "state": "remove_failed",
                    "error": "remove_exception",
                    "message": f'Module "{module_id}" could not be removed.',
                    "details": str(exc),
                }

    def update_module_package(self, module_query: str) -> dict[str, Any]:
        local_id = self.resolve_local_module_id(module_query)
        remote_id = self.resolve_remote_module_id(module_query)

        if local_id is None:
            if remote_id is None:
                return {
                    "success": False,
                    "operation": "update_module",
                    "state": "update_failed",
                    "error": "module_not_found",
                    "message": f'Module "{module_query}" was not found.',
                    "details": None,
                }
            return self.acquire_module(remote_id)

        if remote_id is None:
            return {
                "success": False,
                "module": local_id,
                "operation": "update_module",
                "state": "update_failed",
                "error": "module_not_available",
                "message": (
                    f'Module "{local_id}" is installed locally but is not '
                    f'published in the active {self.channel} manifest.'
                ),
                "details": None,
            }

        local = self.get_local_module_info(local_id) or {}
        remote = self.get_remote_modules()[remote_id]
        if self._version_key(remote["Version"]) <= self._version_key(
            local.get("ModuleVersion", "0.0.0")
        ):
            return {
                "success": True,
                "module": local_id,
                "operation": "update_module",
                "state": "up_to_date",
                "message": f'Module "{local_id}" is already up to date.',
                "details": {
                    "installed": local.get("ModuleVersion"),
                    "available": remote["Version"],
                },
            }

        return self.acquire_module(remote_id, force_replace=True)


    def _manager_entry_path(self, module_id: str) -> Path:
        info = self.get_modules()[module_id]
        module_path = self._resolve_registered_path(info["ModulePath"])
        return (module_path / info["Manager"]).resolve()

    def _load_python_module_manager(self, module_id: str) -> ModuleType:
        cached = self._module_import_cache.get(module_id)
        if cached is not None:
            return cached

        manager_path = self._manager_entry_path(module_id)
        spec = importlib.util.spec_from_file_location(
            f"_emukit_module_{module_id}",
            manager_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f'Unable to load manager script "{manager_path}".')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._module_import_cache[module_id] = module
        return module

    @staticmethod
    def _fallback_result(
        module_id: str,
        operation: str,
        *,
        message: str,
        details: Any = None,
        error: str = "module_operation_failed",
    ) -> dict[str, Any]:
        return {
            "success": False,
            "module": module_id,
            "operation": operation,
            "state": f"{operation}_failed",
            "error": error,
            "message": message,
            "details": details,
        }

    def _normalize_module_result(
        self,
        module_id: str,
        operation: str,
        result: Any,
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            return self._fallback_result(
                module_id,
                operation,
                message=(
                    f'{module_id} failed during {operation}. '
                    "The module did not provide a valid result."
                ),
                details=f"Returned value: {result!r}",
                error="invalid_module_result",
            )
        normalized = copy.deepcopy(result)
        normalized.setdefault("module", module_id)
        normalized.setdefault("operation", operation)
        if not isinstance(normalized.get("success"), bool):
            normalized["success"] = False
        if not self._valid_string(normalized.get("state")):
            normalized["state"] = (
                f"{operation}_complete"
                if normalized["success"]
                else f"{operation}_failed"
            )
        if not self._valid_string(normalized.get("message")):
            normalized["message"] = (
                f"{module_id} completed {operation}."
                if normalized["success"]
                else f"{module_id} failed during {operation}."
            )
        normalized.setdefault("details", None)
        return normalized

    def _invoke_executable_manager(
        self,
        module_id: str,
        operation: str,
        manager_path: Path,
    ) -> dict[str, Any]:
        process = subprocess.Popen(
            [str(manager_path), operation, "--json"],
            cwd=str(manager_path.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        protocol_state: dict[str, Any] = {
            "result": None,
            "error": None,
            "stdout": [],
        }
        stderr_lines: list[str] = []

        def read_stdout() -> None:
            if process.stdout is None:
                protocol_state["error"] = "Executable manager stdout pipe was not available."
                return
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                protocol_state["stdout"].append(line)
                if protocol_state["error"] is not None:
                    continue
                if not line:
                    protocol_state["error"] = "Executable manager emitted a blank stdout record."
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    protocol_state["error"] = f"Executable manager emitted invalid JSONL: {exc}."
                    continue
                if not isinstance(record, dict):
                    protocol_state["error"] = "Executable manager JSONL records must be objects."
                    continue
                record_type = record.get("type")
                if record_type == "progress":
                    if protocol_state["result"] is not None:
                        protocol_state["error"] = "Executable manager emitted progress after its final result."
                        continue
                    percent = record.get("percent")
                    stage = record.get("stage")
                    message = record.get("message")
                    if percent is not None and (
                        not isinstance(percent, (int, float))
                        or isinstance(percent, bool)
                        or percent < 0
                        or percent > 100
                    ):
                        protocol_state["error"] = "Executable manager progress percent must be between 0 and 100."
                        continue
                    if stage is not None and not isinstance(stage, str):
                        protocol_state["error"] = "Executable manager progress stage must be a string or null."
                        continue
                    if message is not None and not isinstance(message, str):
                        protocol_state["error"] = "Executable manager progress message must be a string or null."
                        continue
                    self._emit_progress(
                        module_id,
                        operation,
                        percent,
                        stage,
                        message,
                    )
                    continue
                if record_type == "result":
                    if protocol_state["result"] is not None:
                        protocol_state["error"] = "Executable manager emitted more than one final result."
                        continue
                    result = record.get("result")
                    if not isinstance(result, dict):
                        protocol_state["error"] = "Executable manager result record must contain an object result."
                        continue
                    protocol_state["result"] = result
                    continue
                protocol_state["error"] = f'Executable manager emitted unsupported JSONL record type "{record_type}".'

        def read_stderr() -> None:
            if process.stderr is None:
                return
            for raw_line in process.stderr:
                stderr_lines.append(raw_line.rstrip("\r\n"))

        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        try:
            returncode = process.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            return self._fallback_result(
                module_id,
                operation,
                message=f'Module "{module_id}" executable manager timed out.',
                details={
                    "stdout": protocol_state["stdout"],
                    "stderr": stderr_lines,
                },
                error="manager_timeout",
            )

        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        if protocol_state["error"] is not None:
            return self._fallback_result(
                module_id,
                operation,
                message=f'Module "{module_id}" executable manager violated the JSONL protocol.',
                details={
                    "returncode": returncode,
                    "protocol_error": protocol_state["error"],
                    "stdout": protocol_state["stdout"],
                    "stderr": stderr_lines,
                },
                error="manager_protocol_error",
            )

        result = protocol_state["result"]
        if result is None:
            return self._fallback_result(
                module_id,
                operation,
                message=f'Module "{module_id}" executable manager did not return a final result record.',
                details={
                    "returncode": returncode,
                    "stdout": protocol_state["stdout"],
                    "stderr": stderr_lines,
                },
                error="missing_manager_result",
            )

        normalized = self._normalize_module_result(
            module_id,
            operation,
            result,
        )
        if returncode != 0 and normalized.get("success"):
            normalized["success"] = False
            normalized["state"] = f"{operation}_failed"
            normalized["error"] = "manager_exit_failure"
            normalized["details"] = {
                "returncode": returncode,
                "result": result,
                "stderr": stderr_lines,
            }
        return normalized

    def _invoke_module_manager_unlocked(
        self,
        module_id: str,
        operation: str,
    ) -> dict[str, Any]:
        if module_id not in self.get_modules():
            return self._fallback_result(
                module_id,
                operation,
                message=f'Module "{module_id}" is not registered.',
                error="module_not_registered",
            )

        try:
            manager_path = self._manager_entry_path(module_id)
            start_stage = {
                "install": "Starting Install",
                "repair": "Starting Repair",
                "update": "Starting Update",
                "uninstall": "Starting Uninstall",
                "check": "Starting Check",
            }.get(operation, operation.replace("_", " ").title())
            self._emit_progress(
                module_id,
                operation,
                0,
                start_stage,
                None,
            )

            if manager_path.suffix.casefold() == ".py":
                module = self._load_python_module_manager(module_id)
                handler = getattr(module, operation, None)
                if not callable(handler):
                    return self._fallback_result(
                        module_id,
                        operation,
                        message=(
                            f'Module "{module_id}" manager does not implement '
                            f'required operation "{operation}()".'
                        ),
                        error="operation_not_implemented",
                    )

                progress = lambda percent=None, stage=None, message=None: self._emit_progress(
                    module_id,
                    operation,
                    percent,
                    stage,
                    message,
                )
                result = handler(progress=progress)
                normalized = self._normalize_module_result(
                    module_id,
                    operation,
                    result,
                )
            else:
                normalized = self._invoke_executable_manager(
                    module_id,
                    operation,
                    manager_path,
                )

            if normalized.get("success"):
                self._emit_progress(
                    module_id,
                    operation,
                    100,
                    str(
                        normalized.get("state", operation)
                    ).replace("_", " ").title(),
                    normalized.get("message"),
                )
            else:
                self._emit_progress(
                    module_id,
                    operation,
                    None,
                    "Failed",
                    normalized.get("message"),
                )
            return normalized
        except Exception as exc:
            return self._fallback_result(
                module_id,
                operation,
                message=f'{module_id} failed during {operation}.',
                details=str(exc),
                error="module_exception",
            )

    def _run_serialized_operation(
        self,
        module_id: str,
        operation: str,
    ) -> dict[str, Any]:
        with self._operation_lock:
            with self._state_lock:
                self._current_operation = {
                    "module": module_id,
                    "operation": operation,
                }
            try:
                return self._invoke_module_manager_unlocked(
                    module_id,
                    operation,
                )
            finally:
                with self._state_lock:
                    self._current_operation = None

    def check_module(self, module_query: str) -> dict[str, Any]:
        module_id = self.resolve_local_module_id(module_query)
        if module_id is None:
            return self._fallback_result(
                module_query,
                "check",
                message=f'Module "{module_query}" is not installed locally.',
                error="module_not_installed",
            )
        return self._run_serialized_operation(module_id, "check")

    def install(self, module_query: str) -> dict[str, Any]:
        module_id = self.resolve_local_module_id(module_query)
        if module_id is None:
            remote_id = self.resolve_remote_module_id(module_query)
            if remote_id is None:
                return self._fallback_result(
                    module_query,
                    "install",
                    message=f'Module "{module_query}" was not found locally or remotely.',
                    error="module_not_found",
                )
            acquired = self.acquire_module(remote_id)
            if not acquired.get("success"):
                return acquired
            module_id = remote_id

        self.settings.set_module_enabled(module_id, True)
        return self._run_serialized_operation(module_id, "install")

    def uninstall(self, module_query: str) -> dict[str, Any]:
        module_id = self.resolve_local_module_id(module_query)
        if module_id is None:
            return self._fallback_result(
                module_query,
                "uninstall",
                message=f'Module "{module_query}" is not installed locally.',
                error="module_not_installed",
            )
        result = self._run_serialized_operation(module_id, "uninstall")
        if result.get("success"):
            self.settings.set_module_enabled(module_id, False)
        return result

    def repair(self, module_query: str) -> dict[str, Any]:
        module_id = self.resolve_local_module_id(module_query)
        if module_id is None:
            return self._fallback_result(
                module_query,
                "repair",
                message=f'Module "{module_query}" is not installed locally.',
                error="module_not_installed",
            )
        return self._run_serialized_operation(module_id, "repair")

    def update(self, module_query: str) -> dict[str, Any]:
        module_id = self.resolve_local_module_id(module_query)
        if module_id is None:
            return self._fallback_result(
                module_query,
                "update",
                message=f'Module "{module_query}" is not installed locally.',
                error="module_not_installed",
            )
        return self._run_serialized_operation(module_id, "update")

    def install_all(self) -> dict[str, Any]:
        remote_modules = self.get_remote_modules()
        if not remote_modules:
            manifest_status = self._remote_manifest_error
            return {
                "success": False if manifest_status else True,
                "operation": "install_all",
                "state": "manifest_unavailable" if manifest_status else "nothing_to_install",
                "message": (
                    "No remote modules are available because the active manifest "
                    "could not be loaded."
                    if manifest_status
                    else "The active module manifest contains no modules."
                ),
                "details": manifest_status,
            }

        results: list[dict[str, Any]] = []
        for module_id in sorted(
            remote_modules,
            key=lambda item: remote_modules[item]["Name"].casefold(),
        ):
            results.append(self.install(module_id))

        failures = [result for result in results if not result.get("success")]
        return {
            "success": not failures,
            "operation": "install_all",
            "state": "complete" if not failures else "complete_with_errors",
            "message": (
                "All advertised modules were installed successfully."
                if not failures
                else "Install All completed with one or more errors."
            ),
            "details": results,
        }

    def get_current_installs(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        modules = self.get_modules()
        with self._operation_lock:
            for module_id in sorted(
                modules,
                key=lambda item: modules[item]["Name"].casefold(),
            ):
                result = self._invoke_module_manager_unlocked(
                    module_id,
                    "check",
                )
                if (
                    not result.get("success")
                    or result.get("state") == "missing"
                ):
                    continue
                details = (
                    result.get("details")
                    if isinstance(result.get("details"), dict)
                    else {}
                )
                values.append({
                    "Id": module_id,
                    "Name": modules[module_id]["Name"],
                    "State": result.get("state"),
                    "Version": details.get("version"),
                    "ModuleVersion": modules[module_id].get("ModuleVersion"),
                })
        return values

    def reconcile(self) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        modules = self.get_modules()

        with self._operation_lock:
            for module_id in sorted(modules):
                desired = self.settings.is_module_enabled(module_id)
                check_result = self._invoke_module_manager_unlocked(
                    module_id,
                    "check",
                )
                results.append(check_result)
                if not check_result.get("success"):
                    continue

                state = check_result.get("state")
                if desired and state == "missing":
                    results.append(
                        self._invoke_module_manager_unlocked(
                            module_id,
                            "install",
                        )
                    )
                elif desired and state == "broken":
                    results.append(
                        self._invoke_module_manager_unlocked(
                            module_id,
                            "repair",
                        )
                    )
                elif not desired and state in {"installed", "broken"}:
                    results.append(
                        self._invoke_module_manager_unlocked(
                            module_id,
                            "uninstall",
                        )
                    )

        failures = [item for item in results if not item.get("success")]
        return {
            "success": not failures,
            "operation": "reconcile",
            "state": "complete" if not failures else "complete_with_errors",
            "message": (
                "EmuKit emulator state is synchronized."
                if not failures
                else "EmuKit emulator reconciliation completed with errors."
            ),
            "details": results,
        }


    def assign_system(
        self,
        system_query: str,
        module_query: str | None,
    ) -> dict[str, Any]:
        system_id = self.resolve_system_id(system_query)
        if system_id is None:
            return {
                "success": False,
                "operation": "assign_system",
                "state": "assignment_failed",
                "error": "system_not_found",
                "message": (
                    f'System "{system_query}" is not registered with EmuKit.'
                ),
                "details": None,
            }

        module_id = None
        if module_query is not None:
            module_id = self.resolve_local_module_id(module_query)
            if module_id is None:
                return {
                    "success": False,
                    "operation": "assign_system",
                    "state": "assignment_failed",
                    "error": "module_not_installed",
                    "message": (
                        f'Module "{module_query}" is not installed locally.'
                    ),
                    "details": None,
                }

            supported = self.get_registry()["Systems"][system_id]["Modules"]
            if module_id not in supported:
                return {
                    "success": False,
                    "module": module_id,
                    "operation": "assign_system",
                    "state": "assignment_failed",
                    "error": "system_not_supported",
                    "message": (
                        f'Module "{module_id}" does not support system "{system_id}".'
                    ),
                    "details": None,
                }

        self.settings.set_system_assignment(system_id, module_id)
        return {
            "success": True,
            "operation": "assign_system",
            "state": "saved",
            "message": f'System "{system_id}" assignment updated.',
            "details": {"system": system_id, "module": module_id},
        }

    def _prepare_emulator_for_launch(
        self,
        module_id: str,
    ) -> dict[str, Any] | None:
        with self._operation_lock:
            check_result = self._invoke_module_manager_unlocked(
                module_id,
                "check",
            )
            if not check_result.get("success"):
                return check_result

            state = check_result.get("state")
            if state == "missing":
                if not self.settings.is_module_enabled(module_id):
                    return {
                        "success": False,
                        "module": module_id,
                        "operation": "launch",
                        "state": "launch_failed",
                        "error": "emulator_missing",
                        "message": (
                            f'Module "{module_id}" is present but its emulator '
                            "is not installed."
                        ),
                        "details": None,
                    }
                install_result = self._invoke_module_manager_unlocked(
                    module_id,
                    "install",
                )
                if not install_result.get("success"):
                    return install_result

            elif state == "broken":
                if not self.settings.is_module_enabled(module_id):
                    return {
                        "success": False,
                        "module": module_id,
                        "operation": "launch",
                        "state": "launch_failed",
                        "error": "emulator_broken",
                        "message": (
                            f'Module "{module_id}" reports a broken emulator '
                            "installation and automatic repair is disabled."
                        ),
                        "details": None,
                    }
                repair_result = self._invoke_module_manager_unlocked(
                    module_id,
                    "repair",
                )
                if not repair_result.get("success"):
                    return repair_result

        return None

    def launch(
        self,
        *,
        system: str,
        game_path: str | Path,
    ) -> dict[str, Any]:
        system_id = self.resolve_system_id(system)
        if system_id is None:
            return {
                "success": False,
                "operation": "launch",
                "state": "launch_failed",
                "error": "system_not_found",
                "message": f'System "{system}" is not registered with EmuKit.',
                "details": None,
            }

        module_id = self.settings.get_system_assignment(system_id)
        if not module_id:
            return {
                "success": False,
                "operation": "launch",
                "state": "launch_failed",
                "error": "system_unassigned",
                "message": (
                    f'System "{system_id}" does not currently have a module assigned.'
                ),
                "details": None,
            }

        if module_id not in self.get_modules():
            return {
                "success": False,
                "module": module_id,
                "operation": "launch",
                "state": "launch_failed",
                "error": "module_not_registered",
                "message": (
                    f'System "{system_id}" is assigned to module "{module_id}", '
                    "but that module is not installed locally."
                ),
                "details": None,
            }

        if module_id not in self.get_registry()["Systems"][system_id]["Modules"]:
            return {
                "success": False,
                "module": module_id,
                "operation": "launch",
                "state": "launch_failed",
                "error": "system_not_supported",
                "message": (
                    f'Module "{module_id}" does not support system "{system_id}".'
                ),
                "details": None,
            }

        preparation_failure = self._prepare_emulator_for_launch(module_id)
        if preparation_failure is not None:
            return preparation_failure

        return self.launcher.launch_game(
            game_path=game_path,
            system_id=system_id,
            module_id=module_id,
            registry=self.get_registry(),
        )

    def launch_emulator(self, module_query: str) -> dict[str, Any]:
        module_id = self.resolve_local_module_id(module_query)
        if module_id is None:
            return {
                "success": False,
                "operation": "launch_emulator",
                "state": "launch_failed",
                "error": "module_not_installed",
                "message": f'Module "{module_query}" is not installed locally.',
                "details": None,
            }

        preparation_failure = self._prepare_emulator_for_launch(module_id)
        if preparation_failure is not None:
            return preparation_failure

        return self.launcher.launch_emulator(
            module_id=module_id,
            registry=self.get_registry(),
        )


    def initialize(self) -> dict[str, Any]:
        self.module_root.mkdir(parents=True, exist_ok=True)
        self.emulators_root.mkdir(parents=True, exist_ok=True)

        core = self.check_core_dependencies()
        if core.get("state") == "missing_dependencies":
            with self._state_lock:
                self._initialized = False
            return {
                "success": False,
                "operation": "initialize",
                "state": "missing_dependencies",
                "message": "EmuKit cannot initialize until required shared dependencies are installed.",
                "details": {
                    "core_dependencies": core,
                    "registry": None,
                    "settings": None,
                    "remote_manifest": None,
                    "reconcile": None,
                },
            }

        remote = self.refresh_remote_manifest()
        registry = self.sync_registry()
        settings = self.sync_settings()
        reconcile = self.reconcile()

        with self._state_lock:
            self._initialized = True

        local_success = bool(
            registry.get("success")
            and settings.get("success")
            and reconcile.get("success")
        )
        state = "ready" if local_success else "ready_with_errors"

        if local_success and not remote.get("success"):
            state = "ready_offline"

        return {
            "success": local_success,
            "operation": "initialize",
            "state": state,
            "message": (
                "EmuKit initialized."
                if local_success
                else "EmuKit initialized with one or more local errors."
            ),
            "details": {
                "core_dependencies": core,
                "registry": registry,
                "settings": settings,
                "remote_manifest": remote,
                "reconcile": reconcile,
            },
        }

    def get_status(self) -> dict[str, Any]:
        with self._state_lock:
            remote_error = copy.deepcopy(self._remote_manifest_error)
            manifest = copy.deepcopy(self._remote_manifest)
            catalogue = copy.deepcopy(self._remote_catalogue)
            catalogue_error = copy.deepcopy(self._remote_catalogue_error)

        registry = self.get_registry()
        return {
            "core_version": self.CORE_VERSION,
            "initialized": self._initialized,
            "project_root": str(self.project_root),
            "emukit_root": str(self.emukit_root),
            "module_root": str(self.module_root),
            "emulators_root": str(self.emulators_root),
            "dependencies_root": str(self.dependencies_root),
            "channel": self.channel,
            "platform": self.host_platform,
            "architecture": self.host_architecture,
            "remote_manifest_url": self.remote_manifest_url,
            "remote_manifest_available": manifest is not None,
            "remote_manifest_error": remote_error,
            "remote_catalogue_available": catalogue is not None,
            "remote_catalogue_version": catalogue.get("Version") if isinstance(catalogue, dict) else None,
            "remote_catalogue_error": catalogue_error,
            "remote_module_count": (
                len(manifest.get("Modules", {}))
                if isinstance(manifest, dict)
                else 0
            ),
            "registered_modules": sorted(registry["Modules"]),
            "registered_count": len(registry["Modules"]),
            "supported_brands": len(registry["Brands"]),
            "supported_platforms": len(registry["Platforms"]),
            "supported_systems": len(registry["Systems"]),
            "current_operation": copy.deepcopy(self._current_operation),
            "registry_sync_errors": copy.deepcopy(self._last_sync_errors),
            "core_dependencies": copy.deepcopy(self._core_dependency_status),
            "settings": self.settings.snapshot(),
        }
