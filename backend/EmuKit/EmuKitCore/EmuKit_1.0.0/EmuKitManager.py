from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
import os
import platform as host_platform
import re
import shutil
import stat
import subprocess
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
    REMOTE_MANIFEST_SCHEMA = 1
    MODULE_INFO_PATTERN = "EmuKit*Info.json"

    REPOSITORY = "Cruizepeni/ProjectHomelab"
    REPOSITORY_BRANCH = "main"
    DEVELOPMENT_FEED = "backend/EmuKit"
    RELEASE_FEED = "Releases/EmuKit"

    CORE_DEPENDENCIES = {
        "7zip": {
            "Name": "7-Zip",
            "Version": "26.03",
            "RequiredOn": ["Windows"],
        }
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
        self.module_root = self.emukit_root

        self.registry_path = self.project_root / "appdata" / "registry" / "EmuKitRegistry.json"
        self.dependencies_root = self.project_root / "dependencies" / "EmuKit"
        self.staging_root = self.project_root / "appdata" / "cache" / "EmuKit" / "ModuleStaging"

        self.host_platform = self._canonical_platform()
        self.host_architecture = self._canonical_architecture()

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
        self.remote_manifest_url = (
            f"{self.platform_feed_base_url}EmuKit_{self.host_platform}_Manifest.json"
        )

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

    # ------------------------------------------------------------------
    # Host / channel
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Core dependencies
    # ------------------------------------------------------------------

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

    def _check_7zip(self) -> dict[str, Any]:
        candidates: list[Path] = []
        for command_name in ("7z", "7zz"):
            found = shutil.which(command_name)
            if found:
                candidates.append(Path(found))

        if self.host_platform == "Windows":
            for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
                if root:
                    candidates.append(Path(root) / "7-Zip" / "7z.exe")

        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate).casefold()
            if key in seen:
                continue
            seen.add(key)
            if candidate.is_file():
                return {
                    "success": True,
                    "dependency": "7zip",
                    "state": "installed",
                    "installed": True,
                    "message": f'7-Zip found at "{candidate}".',
                    "details": {
                        "path": str(candidate),
                        "version": self._read_7zip_version(candidate),
                    },
                }

        required = self.host_platform in self.CORE_DEPENDENCIES["7zip"]["RequiredOn"]
        return {
            "success": True,
            "dependency": "7zip",
            "state": "missing" if required else "not_required",
            "installed": not required,
            "message": (
                "7-Zip is not installed or its command-line executable could not be found."
                if required
                else "7-Zip is not a required EmuKit Core dependency on this host."
            ),
            "details": {
                "required": required,
                "resource_version": self.CORE_DEPENDENCIES["7zip"]["Version"],
            },
        }

    def check_core_dependencies(self) -> dict[str, Any]:
        checks = {"7zip": self._check_7zip()}
        missing = [
            dep_id
            for dep_id, result in checks.items()
            if result.get("state") == "missing"
        ]
        with self._state_lock:
            self._core_dependency_status = copy.deepcopy(checks)
        return {
            "success": True,
            "operation": "core_dependency_check",
            "state": "missing_dependencies" if missing else "ready",
            "message": (
                "EmuKit is missing one or more shared dependencies."
                if missing
                else "EmuKit shared dependencies are ready."
            ),
            "details": checks,
            "missing": missing,
        }

    def install_core_dependency(self, dependency_id: str) -> dict[str, Any]:
        if dependency_id.casefold() != "7zip":
            return {
                "success": False,
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "dependency_not_found",
                "message": f'Unknown EmuKit Core dependency "{dependency_id}".',
                "details": None,
            }

        if self.host_platform != "Windows":
            return {
                "success": False,
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "automatic_install_not_supported",
                "message": "Automatic 7-Zip installation is currently defined only for Windows.",
                "details": None,
            }

        arch_folder = "arm64" if self.host_architecture == "arm64" else "x86_64"
        installer_name = "7z2603-arm64.exe" if arch_folder == "arm64" else "7z2603-x64.exe"
        installer = (
            self.project_root
            / "Resources"
            / "7Zip"
            / "26.03"
            / "Windows"
            / arch_folder
            / installer_name
        )

        if not installer.is_file():
            return {
                "success": False,
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "resource_missing",
                "message": "The controlled ProjectHomelab 7-Zip installer resource was not found.",
                "details": {"expected_path": str(installer)},
            }

        try:
            completed = subprocess.run([str(installer), "/S"], check=False)
            if completed.returncode not in {0, 3010}:
                return {
                    "success": False,
                    "operation": "install_core_dependency",
                    "state": "install_failed",
                    "error": "installer_failed",
                    "message": "7-Zip installer returned a failure code.",
                    "details": {"returncode": completed.returncode},
                }
            verified = self._check_7zip()
            self.check_core_dependencies()
            return {
                "success": bool(verified.get("installed")),
                "operation": "install_core_dependency",
                "state": (
                    "installed_reboot_required"
                    if completed.returncode == 3010
                    else "installed"
                ),
                "message": "7-Zip installed successfully.",
                "details": verified.get("details"),
            }
        except Exception as exc:
            return {
                "success": False,
                "operation": "install_core_dependency",
                "state": "install_failed",
                "error": "installer_exception",
                "message": "7-Zip could not be installed.",
                "details": str(exc),
            }

    # ------------------------------------------------------------------
    # Registry and local discovery
    # ------------------------------------------------------------------

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

        if not self._valid_aliases(info.get("Aliases")):
            return False, 'Module "Aliases" must be a list of non-empty strings.'

        for key in ("ModuleVersion", "EmulatorVersion"):
            if key in info and not self._valid_string(info.get(key)):
                return False, f'Module "{key}" must be a non-empty string when provided.'

        if "DefaultInstalled" in info and not isinstance(info.get("DefaultInstalled"), bool):
            return False, 'Module "DefaultInstalled" must be a boolean.'

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

            if "Default" in system_info and not isinstance(system_info.get("Default"), bool):
                return False, f'System "{system_id}" "Default" must be a boolean.'

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
                system_info["Default"] = system_info.get("Default", False)

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
        defaults: dict[str, list[str]] = {}

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
                if system_info.get("Default"):
                    defaults.setdefault(system_id, []).append(module_id)

        for record in brands.values():
            record["Systems"].sort()
        for record in platforms.values():
            record["Systems"].sort()
        for system_id, record in systems.items():
            record["Modules"].sort()
            candidates = defaults.get(system_id, [])
            if len(candidates) == 1:
                record["DefaultModule"] = candidates[0]
            elif len(candidates) > 1:
                errors.append({
                    "system": system_id,
                    "error": "multiple_default_modules",
                    "message": (
                        f'System "{system_id}" has multiple modules marked as default.'
                    ),
                    "details": candidates,
                })

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

    # ------------------------------------------------------------------
    # Remote manifest
    # ------------------------------------------------------------------

    def _validate_remote_manifest(
        self,
        manifest: Any,
    ) -> tuple[bool, str | None]:
        if not isinstance(manifest, dict):
            return False, "Remote manifest root must be an object."
        if manifest.get("SchemaVersion") != self.REMOTE_MANIFEST_SCHEMA:
            return False, (
                f'Remote manifest "SchemaVersion" must be '
                f"{self.REMOTE_MANIFEST_SCHEMA}."
            )
        if manifest.get("Platform") != self.host_platform:
            return False, (
                f'Remote manifest Platform must be "{self.host_platform}" '
                f'on this host.'
            )
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
                    f'Remote module "{module_id}" Package must be a safe '
                    "platform-feed-relative path."
                )
        return True, None

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

            return {
                "success": True,
                "operation": "remote_manifest",
                "state": "loaded",
                "message": (
                    f'Loaded EmuKit {self.host_platform} module manifest '
                    f'from the {self.channel} channel.'
                ),
                "details": {
                    "channel": self.channel,
                    "platform": self.host_platform,
                    "url": self.remote_manifest_url,
                    "module_count": len(normalized["Modules"]),
                },
            }
        except Exception as exc:
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

    # ------------------------------------------------------------------
    # Settings sync and catalogue reads
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Module package acquisition
    # ------------------------------------------------------------------

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

    def _download_module_package(
        self,
        module_id: str,
        entry: dict[str, Any],
        destination: Path,
    ) -> None:
        package_url = urllib.parse.urljoin(
            self.platform_feed_base_url,
            entry["Package"],
        )
        request = urllib.request.Request(
            package_url,
            headers={"User-Agent": f"ProjectHomelab-EmuKit/{self.CORE_VERSION}"},
        )
        self._emit_progress(
            module_id,
            "acquire_module",
            10,
            "Downloading",
            f'Downloading module package from "{package_url}".',
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
                    if total:
                        percent = 10 + int((read / total) * 45)
                        self._emit_progress(
                            module_id,
                            "acquire_module",
                            min(55, percent),
                            "Downloading",
                            None,
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
                        "Verifying",
                        "Verifying module package SHA-256.",
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
                            "Extracting",
                            "Extracting module package.",
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
                            "Installing validated module package.",
                        )

                        if destination.exists():
                            backup = temp_root / "previous-module"
                            if backup.exists():
                                shutil.rmtree(backup, ignore_errors=True)
                            shutil.move(str(destination), str(backup))

                        shutil.move(str(module_dir), str(destination))
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

    # ------------------------------------------------------------------
    # Module lifecycle invocation
    # ------------------------------------------------------------------

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
        completed = subprocess.run(
            [str(manager_path), operation, "--json"],
            cwd=str(manager_path.parent),
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        output = completed.stdout.strip()
        result: Any = None
        if output:
            try:
                result = json.loads(output)
            except json.JSONDecodeError:
                for line in reversed(output.splitlines()):
                    try:
                        result = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
        if result is None:
            return self._fallback_result(
                module_id,
                operation,
                message=(
                    f'Module "{module_id}" executable manager did not return '
                    "a valid JSON result."
                ),
                details={
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                },
                error="invalid_module_result",
            )
        normalized = self._normalize_module_result(
            module_id,
            operation,
            result,
        )
        if completed.returncode != 0 and normalized.get("success"):
            normalized["success"] = False
            normalized["state"] = f"{operation}_failed"
            normalized["error"] = "manager_exit_failure"
            normalized["details"] = {
                "returncode": completed.returncode,
                "result": result,
                "stderr": completed.stderr,
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
            self._emit_progress(
                module_id,
                operation,
                0,
                operation.capitalize(),
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
                parameters = inspect.signature(handler).parameters
                accepts_progress = (
                    "progress" in parameters
                    or any(
                        item.kind == inspect.Parameter.VAR_KEYWORD
                        for item in parameters.values()
                    )
                )
                result = (
                    handler(progress=progress)
                    if accepts_progress
                    else handler()
                )
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
                    # Preserve previous EmuKit desired-state semantics.
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

    # ------------------------------------------------------------------
    # Assignment and launching
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Initialization and status
    # ------------------------------------------------------------------

    def initialize(self) -> dict[str, Any]:
        core = self.check_core_dependencies()
        registry = self.sync_registry()
        settings = self.sync_settings()
        remote = self.refresh_remote_manifest()
        reconcile = self.reconcile()

        with self._state_lock:
            self._initialized = True

        local_success = bool(
            registry.get("success")
            and settings.get("success")
            and reconcile.get("success")
        )
        state = "ready" if local_success else "ready_with_errors"

        if local_success and core.get("state") == "missing_dependencies":
            state = "ready_with_missing_dependencies"
        if local_success and not remote.get("success"):
            state = "ready_offline"
        if (
            local_success
            and core.get("state") == "missing_dependencies"
            and not remote.get("success")
        ):
            state = "ready_offline_with_missing_dependencies"

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

        registry = self.get_registry()
        return {
            "core_version": self.CORE_VERSION,
            "initialized": self._initialized,
            "project_root": str(self.project_root),
            "emukit_root": str(self.emukit_root),
            "channel": self.channel,
            "platform": self.host_platform,
            "architecture": self.host_architecture,
            "remote_manifest_url": self.remote_manifest_url,
            "remote_manifest_available": manifest is not None,
            "remote_manifest_error": remote_error,
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
