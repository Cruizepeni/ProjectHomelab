from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

try:
    from .EmuKitManager import EmuKitManager
    from .EmuKitSettings import EmuKitSettings
    from .EmuKitMigration import EmuKitMigrationManager
    from .EmuKitPlatformIntegration import EmuKitPlatformIntegration
    from .EmuKitTerminalUI import EmuKitTerminalUI
except ImportError:
    from EmuKitManager import EmuKitManager
    from EmuKitSettings import EmuKitSettings
    from EmuKitMigration import EmuKitMigrationManager
    from EmuKitPlatformIntegration import EmuKitPlatformIntegration
    from EmuKitTerminalUI import EmuKitTerminalUI


class EmuKit:
    ROOT_MARKER = ".AppRoot"

    def __init__(
        self,
        project_root: str | Path | None = None,
        *,
        emukit_root: str | Path | None = None,
        channel: str | None = None,
        auto_initialize: bool = True,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.emukit_root = (
            Path(emukit_root).resolve()
            if emukit_root is not None
            else self._runtime_directory()
        )
        self.project_root = (
            Path(project_root).resolve()
            if project_root is not None
            else self._resolve_project_root(self.emukit_root)
        )

        if getattr(sys, "frozen", False):
            try:
                executable = Path(sys.executable).resolve()
                if executable.parent == self.emukit_root:
                    EmuKitPlatformIntegration.apply_core_folder_identity(
                        self.emukit_root, executable.name
                    )
            except Exception:
                pass

        self.settings = EmuKitSettings(project_root=self.project_root)
        self.migration = EmuKitMigrationManager(self.settings)
        self.manager = EmuKitManager(
            settings=self.settings,
            project_root=self.project_root,
            emukit_root=self.emukit_root,
            progress_callback=progress_callback,
            channel=channel,
        )

        self.initialization_result: dict[str, Any] | None = None
        if auto_initialize:
            self.initialization_result = self.manager.initialize()

    @staticmethod
    def _runtime_directory() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    @classmethod
    def _resolve_project_root(cls, start: Path) -> Path:
        current = start.resolve()
        for candidate in (current, *current.parents):
            if (candidate / cls.ROOT_MARKER).is_file():
                return candidate
        return current

    @staticmethod
    def _pid_running(pid: int) -> bool:
        if not isinstance(pid, int) or pid <= 0:
            return False
        if os.name == "nt":
            try:
                completed = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return completed.returncode == 0 and str(pid) in completed.stdout
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False

    def complete_fresh_update(self, handoff: dict[str, Any]) -> dict[str, Any]:
        from_version = str(handoff.get("from_version") or "unknown")
        migration = self.migration.migrate(from_version, self.manager.CORE_VERSION)
        if not migration.get("success"):
            return migration

        updater_pid = handoff.get("updater_pid")
        if isinstance(updater_pid, int) and updater_pid > 0:
            deadline = time.monotonic() + 20.0
            while self._pid_running(updater_pid) and time.monotonic() < deadline:
                time.sleep(0.1)

        removed: list[str] = []
        errors: list[dict[str, str]] = []

        runtime_name = Path(sys.executable).name if getattr(sys, "frozen", False) else "EmuKit.py"
        runtime_path = Path(runtime_name)
        old_name = f"{runtime_path.stem}Old{runtime_path.suffix}"
        old_executable = self.emukit_root / old_name
        candidates: list[Path] = [old_executable]
        updater_path_raw = handoff.get("updater_path")
        if isinstance(updater_path_raw, str) and updater_path_raw.strip():
            updater_path = Path(updater_path_raw).resolve()
            cache_root = (self.project_root / "Appdata" / "Cache" / "EmuKit").resolve()
            allowed = updater_path.parent == self.emukit_root.parent
            if not allowed:
                try:
                    updater_path.relative_to(cache_root)
                    allowed = True
                except ValueError:
                    pass
            if allowed:
                candidates.append(updater_path)
        staging_raw = handoff.get("staging_path")
        if isinstance(staging_raw, str) and staging_raw.strip():
            staging_path = Path(staging_raw).resolve()
            cache_root = (self.project_root / "Appdata" / "Cache" / "EmuKit").resolve()
            try:
                staging_path.relative_to(cache_root)
                candidates.append(staging_path)
            except ValueError:
                pass

        for path in candidates:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                    removed.append(str(path))
                elif path.exists():
                    path.unlink()
                    removed.append(str(path))
            except Exception as exc:
                errors.append({"path": str(path), "error": str(exc)})

        return {
            "success": not errors,
            "operation": "fresh_update_cleanup",
            "state": "complete" if not errors else "complete_with_errors",
            "message": (
                "EmuKit update migration and cleanup completed."
                if not errors else
                "EmuKit update migration completed, but some cleanup items could not be removed."
            ),
            "details": {"migration": migration, "removed": removed, "errors": errors},
        }

    def initialize(self) -> dict[str, Any]:
        self.initialization_result = self.manager.initialize()
        return self.initialization_result

    def check(self) -> dict[str, Any]:
        return self.manager.reconcile()

    def install(self, module: str) -> dict[str, Any]:
        return self.manager.install(module)

    def install_all(self) -> dict[str, Any]:
        return self.manager.install_all()

    def uninstall_all(self) -> dict[str, Any]:
        return self.manager.uninstall_all()

    def remove_all(self) -> dict[str, Any]:
        return self.manager.remove_all()

    def install_many(self, modules: list[str]) -> dict[str, Any]:
        return self.manager.install_many(modules)

    def uninstall_many(self, modules: list[str]) -> dict[str, Any]:
        return self.manager.uninstall_many(modules)

    def repair_many(self, modules: list[str]) -> dict[str, Any]:
        return self.manager.repair_many(modules)

    def update_many(self, modules: list[str]) -> dict[str, Any]:
        return self.manager.update_many(modules)

    def remove_many(self, modules: list[str]) -> dict[str, Any]:
        return self.manager.remove_many(modules)

    def uninstall(self, module: str) -> dict[str, Any]:
        return self.manager.uninstall(module)

    def remove_module(self, module: str) -> dict[str, Any]:
        return self.manager.remove_module(module)

    def repair(self, module: str) -> dict[str, Any]:
        return self.manager.repair(module)

    def update(self, module: str) -> dict[str, Any]:
        return self.manager.update(module)

    def check_core_dependencies(self) -> dict[str, Any]:
        return self.manager.check_core_dependencies()

    def install_core_dependency(self, dependency_id: str) -> dict[str, Any]:
        return self.manager.install_core_dependency(dependency_id)

    def install_missing_core_dependencies(self) -> dict[str, Any]:
        return self.manager.install_missing_core_dependencies()

    def launch(
        self,
        system: str,
        game_path: str | Path,
        module: str | None = None,
    ) -> dict[str, Any]:
        return self.manager.launch(system=system, game_path=game_path, module=module)

    def launch_emulator(self, module: str) -> dict[str, Any]:
        return self.manager.launch_emulator(module)

    def close_emulator(self, query: str) -> dict[str, Any]:
        return self.manager.close_emulator(query)

    def restart_emulator(self, query: str) -> dict[str, Any]:
        return self.manager.restart_emulator(query)

    def is_emulator_running(self, query: str) -> dict[str, Any]:
        return self.manager.is_emulator_running(query)

    def get_running_emulators(self) -> list[dict[str, Any]]:
        return self.manager.get_running_emulators()

    def get_catalogue(self) -> dict[str, Any] | None:
        return self.manager.get_catalogue()

    def get_brand_catalogue(self) -> dict[str, Any] | None:
        return self.manager.get_brand_catalogue()

    def get_system_catalogue(self) -> dict[str, Any] | None:
        return self.manager.get_system_catalogue()

    def get_emulator_catalogue(self) -> dict[str, Any] | None:
        return self.manager.get_emulator_catalogue()

    def get_brand_entity_catalogue(self, brand: str) -> dict[str, Any] | None:
        return self.manager.get_brand_entity_catalogue(brand)

    def get_system_entity_catalogue(self, system: str) -> dict[str, Any] | None:
        return self.manager.get_system_entity_catalogue(system)

    def get_emulator_entity_catalogue(self, emulator: str) -> dict[str, Any] | None:
        return self.manager.get_emulator_entity_catalogue(emulator)

    def resolve_entity_catalogue(
        self,
        query: str,
    ) -> tuple[str | None, dict[str, Any] | None, list[str]]:
        return self.manager.resolve_entity_catalogue(query)

    def set_system_primary(self, system: str, module: str) -> dict[str, Any]:
        return self.manager.set_system_primary(system, module)

    def restore_system_primary(self, system: str) -> dict[str, Any]:
        return self.manager.restore_system_primary(system)

    def restore_all_system_primaries(self) -> dict[str, Any]:
        return self.manager.restore_all_system_primaries()

    def get_updates(self, *, refresh: bool = True) -> dict[str, Any]:
        return self.manager.get_updates(refresh=refresh)

    def update_core(self) -> dict[str, Any]:
        return self.manager.update_core()

    def get_settings(self) -> dict[str, Any]:
        return self.settings.snapshot()

    def reload_settings(self) -> dict[str, Any]:
        return self.settings.reload()

    def update_setting(self, setting_name: str, value: Any) -> dict[str, Any]:
        try:
            saved = self.settings.update_global_setting(setting_name, value)
        except KeyError:
            return self._not_found("setting", setting_name, "update_setting")
        except (TypeError, ValueError) as exc:
            return {
                "success": False,
                "operation": "update_setting",
                "state": "update_failed",
                "error": "invalid_setting_value",
                "message": str(exc),
                "details": None,
            }
        return {
            "success": True,
            "operation": "update_setting",
            "state": "saved",
            "message": f'Setting "{setting_name}" updated.',
            "details": {"setting": setting_name, "value": saved},
        }

    def get_module_settings(self, module: str) -> dict[str, Any] | None:
        module_id = self.manager.resolve_local_module_id(module)
        if module_id is None:
            return None
        value = self.settings.get_module_settings(module_id)
        if value is None:
            return None
        info = self.manager.get_module_info(module_id) or {"Name": module_id}
        return {"Id": module_id, "Name": info["Name"], **value}

    def get_registry(self) -> dict[str, Any]:
        return self.manager.get_registry()

    def get_status(self) -> dict[str, Any]:
        return self.manager.get_status()

    def get_current_installs(self) -> list[dict[str, Any]]:
        return self.manager.get_current_installs()

    def get_current_modules(self) -> list[dict[str, Any]]:
        return self.manager.get_current_modules()

    def get_module_info(self, module: str) -> dict[str, Any] | None:
        module_id = self.manager.resolve_module_id(module)
        return (
            self.manager.get_module_info(module_id)
            if module_id is not None
            else None
        )

    def get_brand_info(self, brand: str) -> dict[str, Any] | None:
        return self.manager.get_brand_info(brand)

    def get_system_info(self, system: str) -> dict[str, Any] | None:
        return self.manager.get_system_info(system)

    def resolve_info(
        self,
        query: str,
    ) -> tuple[str | None, dict[str, Any] | None, list[str]]:
        matches: list[tuple[str, dict[str, Any]]] = []
        for kind, getter in (
            ("Emulator", self.get_module_info),
            ("Brand", self.get_brand_info),
            ("System", self.get_system_info),
        ):
            value = getter(query)
            if value is not None:
                matches.append((kind, value))
        if len(matches) == 1:
            return matches[0][0], matches[0][1], []
        return None, None, [kind for kind, _ in matches]

    @staticmethod
    def _not_found(
        kind: str,
        value: str,
        operation: str,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "operation": operation,
            "state": f"{operation}_failed",
            "error": f"{kind}_not_found",
            "message": f'{kind.title()} "{value}" was not found.',
            "details": None,
        }


class EmuKitConsole:
    def __init__(self, *, fresh_update_handoff: dict[str, Any] | None = None) -> None:
        self.emukit: EmuKit | None = None
        self.fresh_update_handoff = fresh_update_handoff
        self._progress_active = False
        self._progress_rendered: str | None = None
        self._progress_completed_line = False
        self.ui = EmuKitTerminalUI()

    def progress(self, event: dict[str, Any]) -> None:
        operation = str(event.get("operation", ""))
        if operation not in {
            "install",
            "repair",
            "update",
            "uninstall",
            "acquire_module",
        }:
            return

        module_id = str(event.get("module", ""))
        module_name = module_id
        if self.emukit is not None:
            info = self.emukit.manager.get_module_info(module_id)
            if info is not None:
                module_name = info["Name"]

        stage = str(event.get("stage") or operation.replace("_", " ").title())
        percent = event.get("percent")
        message = " ".join(str(event.get("message") or "").split())
        if self._progress_completed_line:
            print()
            self._progress_completed_line = False

        rendered = self.ui.progress_line(
            module_name,
            stage,
            percent if isinstance(percent, int) else None,
            message,
        )
        if rendered != self._progress_rendered:
            print("\r" + rendered, end="", flush=True)
            self._progress_rendered = rendered
        self._progress_active = True

        if percent == 100 or stage.casefold().endswith("failed"):
            print()
            self._progress_active = False
            self._progress_rendered = None
            self._progress_completed_line = True

    def _clear_progress(self) -> None:
        if self._progress_active:
            print()
            self._progress_active = False
            self._progress_rendered = None
        self._progress_completed_line = False

    @staticmethod
    def _json(value: Any) -> None:
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str))

    @staticmethod
    def _parse_value(value: str) -> Any:
        lowered = value.casefold()
        if lowered in {"true", "yes", "on", "enabled"}:
            return True
        if lowered in {"false", "no", "off", "disabled"}:
            return False
        if lowered in {"none", "null"}:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _result(
        self,
        result: dict[str, Any],
        *,
        raw: bool = False,
        verbose: bool = False,
    ) -> None:
        self._clear_progress()
        if raw:
            self._json(result)
            return

        message = str(result.get("message") or "").strip()
        if result.get("success", False):
            if message:
                self.ui.success(message)
            if verbose and result.get("details") is not None:
                self._json(result["details"])
            return

        if message:
            self.ui.error(message)
        error = result.get("error")
        if error:
            self.ui.warning(f"Error code: {error}")
        details = result.get("details")
        if details is not None and details != "":
            if isinstance(details, (dict, list)):
                self._json(details)
            else:
                self.ui.warning(f"Details: {details}")

    def _settings(self, settings: dict[str, Any]) -> None:
        self.ui.key_value_panel(
            "EmuKit Settings",
            [("Fullscreen", "On" if settings.get("Fullscreen") else "Off")],
        )
        modules = settings.get("Modules", {})
        self.ui.table(
            "Modules",
            ["Module", "State"],
            [
                [module_id, "Enabled" if value.get("Enabled") else "Disabled"]
                for module_id, value in sorted(modules.items())
            ],
        )
        overrides = settings.get("SystemPrimaryOverrides", {})
        self.ui.table(
            "System Primary Overrides",
            ["System", "Primary Emulator"],
            [[system_id, module_id] for system_id, module_id in sorted(overrides.items())],
            summary=(
                None
                if overrides
                else "Catalogue recommendations are currently in control."
            ),
        )

    def _module_settings(self, value: dict[str, Any]) -> None:
        self.ui.key_value_panel(
            value["Name"],
            [("Enabled", "Yes" if value.get("Enabled") else "No")],
        )

    def _public_links(self, value: dict[str, Any]) -> list[tuple[str, Any]]:
        links = value.get("Links")
        if not isinstance(links, dict):
            return []
        fields = [
            ("Website", "Website"),
            ("Repository", "Repository"),
            ("Wiki", "Wiki"),
            ("Documentation", "Documentation"),
            ("EmuKit Module Documentation", "EmuKitModuleDocumentation"),
        ]
        rows: list[tuple[str, Any]] = []
        for label, key in fields:
            link = links.get(key)
            if isinstance(link, str) and link.strip():
                rows.append((label, link))
        return rows

    def _module_info(self, value: dict[str, Any]) -> None:
        rows: list[tuple[str, Any]] = [
            ("Emulator ID", value["Id"]),
            ("Module Installed", "Yes" if value.get("LocalInstalled") else "No"),
            ("Module Available", "Yes" if value.get("RemoteAvailable") else "No"),
        ]
        aliases = value.get("Aliases", [])
        if aliases:
            rows.append(("Aliases", ", ".join(aliases)))
        if value.get("ModuleVersion"):
            rows.append(("Module Version", value.get("ModuleVersion")))
        if value.get("EmulatorVersion"):
            rows.append(("Emulator Version", value.get("EmulatorVersion")))
        if value.get("Channel"):
            rows.append(("Channel", value.get("Channel")))
        if value.get("DependencyPath"):
            rows.append(("Dependency Path", value["DependencyPath"]))
        if value.get("LaunchPath"):
            rows.append(("Launch Path", value["LaunchPath"]))
        self.ui.key_value_panel(value["Name"], rows)
        description = value.get("Description")
        if isinstance(description, str) and description.strip():
            self.ui.panel("Description", [description.strip()])
        link_rows = self._public_links(value)
        if link_rows:
            self.ui.key_value_panel("Links", link_rows)
        license_info = value.get("License")
        if isinstance(license_info, dict):
            license_rows: list[tuple[str, Any]] = []
            if license_info.get("Name"):
                license_rows.append(("License", license_info["Name"]))
            if license_info.get("Url"):
                license_rows.append(("License Information", license_info["Url"]))
            if license_rows:
                self.ui.key_value_panel("License", license_rows)
        source = value.get("Source")
        if isinstance(source, dict):
            source_rows: list[tuple[str, Any]] = []
            if source.get("Provider"):
                source_rows.append(("Provider", source["Provider"]))
            if source.get("ReleaseTag"):
                source_rows.append(("Release Tag", source["ReleaseTag"]))
            if source.get("ReleaseName"):
                source_rows.append(("Release Name", source["ReleaseName"]))
            if source_rows:
                self.ui.key_value_panel("Pinned Source", source_rows)
        host_support = value.get("HostSupport")
        if isinstance(host_support, dict):
            host_rows = []
            for host_name, support in host_support.items():
                if not isinstance(support, dict):
                    continue
                supported = "Yes" if support.get("Supported") else "No"
                architectures = ", ".join(support.get("Architectures") or [])
                host_rows.append([host_name, supported, architectures or "-"])
            if host_rows:
                self.ui.table("Host Support", ["Host", "Supported", "Architectures"], host_rows)
        systems = value.get("Systems", {})
        if systems:
            self.ui.table(
                "Supported Systems",
                ["Brand", "System", "System ID"],
                [[system["Brand"]["Name"], system["Name"], system_id] for system_id, system in sorted(
                    systems.items(), key=lambda item: item[1]["Name"].casefold()
                )],
            )

    def _brand_info(self, value: dict[str, Any]) -> None:
        rows: list[tuple[str, Any]] = [("Brand ID", value["Id"])]
        aliases = value.get("Aliases", [])
        if aliases:
            rows.append(("Aliases", ", ".join(aliases)))
        self.ui.key_value_panel(value["Name"], rows)
        description = value.get("Description")
        if isinstance(description, str) and description.strip():
            self.ui.panel("Description", [description.strip()])
        links = self._public_links(value)
        if links:
            self.ui.key_value_panel("Links", links)
        self.ui.table(
            "Systems",
            ["System"],
            [[system.get("DisplayName") or system["Name"]] for system in sorted(
                value.get("SystemDetails", []),
                key=lambda item: (item.get("DisplayName") or item["Name"]).casefold(),
            )],
        )

    def _platform_info(self, value: dict[str, Any]) -> None:
        rows: list[tuple[str, Any]] = [("Platform ID", value["Id"])]
        aliases = value.get("Aliases", [])
        if aliases:
            rows.append(("Aliases", ", ".join(aliases)))
        self.ui.key_value_panel(value["Name"], rows)
        self.ui.table(
            "Systems",
            ["System"],
            [[system["Name"]] for system in sorted(
                value.get("SystemDetails", []), key=lambda item: item["Name"].casefold()
            )],
        )

    def _system_info(self, value: dict[str, Any]) -> None:
        rows: list[tuple[str, Any]] = [("System ID", value["Id"])]
        aliases = value.get("Aliases", [])
        if aliases:
            rows.append(("Aliases", ", ".join(aliases)))
        brand = value.get("Brand", {})
        if brand:
            rows.append(("Brand", brand.get("Name", value.get("BrandId", "Unknown"))))
        platform = value.get("Platform")
        if isinstance(platform, dict) and platform.get("Name"):
            rows.append(("Platform", platform["Name"]))
        primary = value.get("PrimaryEmulator")
        if isinstance(primary, dict):
            rows.extend([
                ("Primary Emulator", primary.get("Name", primary.get("Id", "None"))),
                ("Primary Source", primary.get("Source", "Recommended")),
                ("Primary Module Installed", "Yes" if primary.get("Installed") else "No"),
            ])
        else:
            rows.append(("Primary Emulator", "None"))
        self.ui.key_value_panel(value.get("DisplayName") or value["Name"], rows)
        description = value.get("Description")
        if isinstance(description, str) and description.strip():
            self.ui.panel("Description", [description.strip()])
        links = self._public_links(value)
        if links:
            self.ui.key_value_panel("Links", links)
        emulator_details = value.get("EmulatorDetails")
        if isinstance(emulator_details, list) and emulator_details:
            names = [str(item.get("Name") or item.get("Id")) for item in emulator_details if isinstance(item, dict)]
        else:
            names = [str(item) for item in (value.get("Emulators") or value.get("Modules") or [])]
        self.ui.table("Supported Emulators", ["Emulator"], [[name] for name in names])

    def _installs(self, values: list[dict[str, Any]]) -> None:
        rows = []
        for value in values:
            version = value.get("Version") or "Unknown version"
            state = str(value.get("State", "")).replace("_", " ").title() or "Ready"
            rows.append([value["Name"], version, state])
        count = len(values)
        self.ui.table(
            "Installed Emulators",
            ["Emulator", "Version", "Status"],
            rows,
            summary=f"{count} emulator{'s' if count != 1 else ''} installed.",
        )

    def _modules(self, values: list[dict[str, Any]]) -> None:
        rows = []
        for value in values:
            rows.append([value["Name"], value.get("ModuleVersion") or "Unknown", value.get("EmulatorVersion") or "Unknown"])
        count = len(values)
        self.ui.table(
            "Installed Modules",
            ["Module", "Module Version", "Emulator Version"],
            rows,
            summary=f"{count} EmuKit module{'s' if count != 1 else ''} installed.",
        )

    @staticmethod
    def _modifiers(
        tokens: list[str],
    ) -> tuple[list[str], bool, bool]:
        raw = any(token.casefold() == "--json" for token in tokens)
        verbose = any(token.casefold() == "--verbose" for token in tokens)
        clean = [
            token
            for token in tokens
            if token.casefold() not in {"--json", "--verbose"}
        ]
        return clean, raw, verbose

    def _catalogue_view(self, value: dict[str, Any] | None, kind: str) -> None:
        if not isinstance(value, dict):
            self.ui.error("Platform catalogue is unavailable.")
            return
        platform = value.get("Platform", "Platform")
        version = value.get("Version", "?")
        brands = value.get("Brands", {})
        systems = value.get("Systems", {})
        emulators = value.get("Emulators", {})
        if kind == "all":
            source_brands = brands if isinstance(brands, dict) else {}
            source_emulators = emulators if isinstance(emulators, dict) else {}
            source_systems: dict[str, dict[str, Any]] = {}
            for brand_id, brand in source_brands.items():
                if not isinstance(brand, dict):
                    continue
                brand_name = brand.get("Name", brand_id)
                for system_id, system in (brand.get("Systems") or {}).items():
                    if not isinstance(system, dict):
                        continue
                    item = dict(system)
                    item["DisplayName"] = f'{brand_name} {system.get("Name", system_id)}'
                    source_systems[system_id] = item
            self.ui.key_value_panel(
                f"EmuKit {platform} Catalogue",
                [("Catalogue Version", version), ("Brands", len(source_brands)), ("Systems", len(source_systems)), ("Emulators", len(source_emulators))],
            )
            self.ui.table("Brands", ["Brand"], [[brand.get("Name", brand_id)] for brand_id, brand in sorted(source_brands.items(), key=lambda item: item[1].get("Name", item[0]).casefold())])
            self.ui.table("Systems", ["System"], [[system["DisplayName"]] for system in sorted(source_systems.values(), key=lambda item: item["DisplayName"].casefold())])
            self.ui.table("Emulators", ["Emulator"], [[emulator.get("Name", emulator_id)] for emulator_id, emulator in sorted(source_emulators.items(), key=lambda item: item[1].get("Name", item[0]).casefold())])
            return
        if kind == "brands":
            source = brands if isinstance(brands, dict) else {}
            self.ui.table("Brand Catalogue", ["Brand"], [[brand.get("Name", brand_id)] for brand_id, brand in sorted(source.items(), key=lambda item: item[1].get("Name", item[0]).casefold())], summary=f"{len(source)} brands.")
            return
        if kind == "systems":
            source = systems if isinstance(systems, dict) else {}
            self.ui.table("System Catalogue", ["System"], [[system.get("DisplayName") or system.get("Name", system_id)] for system_id, system in sorted(source.items(), key=lambda item: (item[1].get("DisplayName") or item[1].get("Name", item[0])).casefold())], summary=f"{len(source)} systems.")
            return
        source = emulators if isinstance(emulators, dict) else {}
        self.ui.table("Emulator Catalogue", ["Emulator"], [[emulator.get("Name", emulator_id)] for emulator_id, emulator in sorted(source.items(), key=lambda item: item[1].get("Name", item[0]).casefold())], summary=f"{len(source)} emulators.")

    def _entity_catalogue_view(self, kind: str, value: dict[str, Any]) -> None:
        if kind == "Brand":
            brand = value["Brand"]
            systems = value.get("Systems", {})
            self.ui.table(
                f'{brand["Name"]} Catalogue',
                ["System"],
                [[system.get("DisplayName") or system.get("Name", system_id)] for system_id, system in sorted(systems.items(), key=lambda item: (item[1].get("DisplayName") or item[1].get("Name", item[0])).casefold())],
                summary=f"{len(systems)} systems.",
            )
            return
        if kind == "System":
            system = value["System"]
            emulators = value.get("Emulators", {})
            rows = [[emulator.get("Name", emulator_id), "Recommended" if emulator.get("RecommendedPrimary") else "Alternative"] for emulator_id, emulator in sorted(emulators.items(), key=lambda item: item[1].get("Name", item[0]).casefold())]
            self.ui.table(f'{system.get("DisplayName") or system["Name"]} Catalogue', ["Emulator", "Role"], rows, summary=f"{len(emulators)} emulators.")
            return
        emulator = value["Emulator"]
        systems = value.get("Systems", {})
        self.ui.table(
            f'{emulator["Name"]} Catalogue',
            ["System"],
            [[system.get("DisplayName") or system.get("Name", system_id)] for system_id, system in sorted(systems.items(), key=lambda item: (item[1].get("DisplayName") or item[1].get("Name", item[0])).casefold())],
            summary=f"{len(systems)} systems.",
        )

    def _running(self, values: list[dict[str, Any]]) -> None:
        rows = []
        for value in values:
            processes = value.get("Processes", [])
            pids = ", ".join(str(item.get("pid")) for item in processes if item.get("pid"))
            rows.append([
                value.get("Name", value.get("Id", "Unknown")),
                pids or "-",
                "Running",
            ])
        count = len(values)
        self.ui.table(
            "Running Emulators",
            ["Emulator", "PID", "State"],
            rows,
            summary=f"{count} emulator{'s' if count != 1 else ''} running.",
        )

    def _updates_view(self, result: dict[str, Any]) -> None:
        if not result.get("success"):
            self._result(result)
            return
        details = result.get("details", {})
        core = details.get("core", {}) if isinstance(details, dict) else {}
        core_details = core.get("details", {}) if isinstance(core, dict) else {}
        rows = []
        installed_core = core_details.get("installed", "Unknown")
        latest_core = core_details.get("latest", installed_core)
        rows.append([
            "EmuKit Core",
            installed_core,
            latest_core,
            "Update Available" if core.get("state") == "update_available" else "Current",
        ])
        modules = details.get("modules", []) if isinstance(details, dict) else []
        for item in modules:
            rows.append([
                item.get("Name", item.get("Id")),
                item.get("Installed", "Unknown"),
                item.get("Available", "Unknown"),
                "Update Available",
            ])
        self.ui.table(
            "EmuKit Updates",
            ["Component", "Installed", "Available", "Status"],
            rows,
            summary=(
                f"{len(modules)} emulator module update{'s' if len(modules) != 1 else ''} available."
                if modules else "Emulator modules are up to date."
            ),
        )

    def _resolve_module_sequence(self, tokens: list[str]) -> list[str] | None:
        assert self.emukit is not None
        if not tokens:
            return []
        result: list[str] = []
        index = 0
        while index < len(tokens):
            matched = None
            matched_end = None
            for end in range(len(tokens), index, -1):
                candidate = " ".join(tokens[index:end]).strip().strip(",")
                candidate = candidate.rstrip(",")
                if not candidate:
                    continue
                module_id = self.emukit.manager.resolve_module_id(candidate)
                if module_id is not None:
                    matched = module_id
                    matched_end = end
                    break
            if matched is None or matched_end is None:
                return None
            result.append(matched)
            index = matched_end
        return result

    def _split_system_suffix(self, tokens: list[str]) -> tuple[list[str], str] | None:
        assert self.emukit is not None
        for index in range(1, len(tokens)):
            candidate = " ".join(tokens[index:])
            if self.emukit.manager.resolve_system_id(candidate) is not None:
                return tokens[:index], candidate
        return None

    def _split_explicit_module_prefix(self, tokens: list[str]) -> tuple[str, list[str]] | None:
        assert self.emukit is not None
        if len(tokens) < 2:
            return None
        for end in range(len(tokens) - 1, 0, -1):
            candidate = " ".join(tokens[:end])
            module_id = self.emukit.manager.resolve_module_id(candidate)
            if module_id is not None:
                return module_id, tokens[end:]
        return None

    def _help(self) -> None:
        rows = [
            ["Discovery", "Get Catalogue", "Complete catalogue"],
            ["Discovery", "Get Brand Catalogue", "All supported brands"],
            ["Discovery", "Get System Catalogue", "All supported systems"],
            ["Discovery", "Get Emulator Catalogue", "All supported emulators"],
            ["Discovery", "Get <Brand|System|Emulator> Catalogue", "Relationships for one catalogue entity"],
            ["Discovery", "Get <Brand|System|Emulator> Info", "Detailed information for one entity"],
            ["Local State", "Get Current Installs | Get Installed Emulators", "Installed emulator applications"],
            ["Local State", "Get Current Modules | Get Installed Modules", "Local EmuKit module packages"],
            ["Runtime", "Get Running Emulators", "Detected emulator processes"],
            ["Launch", "Launch <Emulator>", "Open an emulator"],
            ["Launch", "Launch <GamePath> <System>", "Launch a game with the primary emulator"],
            ["Launch", "Launch <Emulator> <GamePath> <System>", "Launch with a specific emulator"],
            ["Lifecycle", "Close <Emulator|System>", "Close a running emulator"],
            ["Lifecycle", "Restart <Emulator|System>", "Restart a running emulator"],
            ["Lifecycle", "Is <Emulator|System> Running", "Check running state"],
            ["Modules", "Install <Emulator(s)> | Install All", "Install emulator applications"],
            ["Modules", "Uninstall <Emulator(s)> | Uninstall All", "Uninstall emulator applications"],
            ["Modules", "Repair <Emulator(s)>", "Repair emulator applications"],
            ["Modules", "Remove <Emulator(s)> | Remove All", "Remove local module packages"],
            ["Modules", "Update <Emulator(s)>", "Update emulator applications"],
            ["Updates", "Updates | Check Updates | Check for Updates | Get Updates", "Check updates"],
            ["Updates", "Update EmuKit", "Update EmuKit Core"],
            ["Primary", "Set <Emulator> as <System> Primary", "Set user primary"],
            ["Primary", "Restore <System> Primary", "Restore recommended primary"],
            ["Primary", "Restore Systems Primary", "Restore all recommendations"],
            ["Settings", "Get Settings", "Show global and module settings"],
            ["Settings", "Set Feature Fullscreen True|False", "Change feature fullscreen"],
            ["Utility", "Get Status", "Show EmuKit status"],
            ["Utility", "Get Core Dependencies", "Check shared dependencies"],
            ["Utility", "Help", "Show this command list"],
            ["Utility", "Close", "Exit EmuKit"],
        ]
        self.ui.table("EmuKit Commands", ["Group", "Command", "Description"], rows, summary="Append --json for machine-readable output or --verbose for lifecycle details.")

    def _get(self, tokens: list[str], raw: bool) -> None:
        assert self.emukit is not None
        lowered = [token.casefold() for token in tokens]
        if lowered == ["catalogue"]:
            value = self.emukit.get_catalogue()
            self._json(value) if raw else self._catalogue_view(value, "all")
            return
        if lowered == ["brand", "catalogue"]:
            value = self.emukit.get_brand_catalogue()
            self._json(value) if raw else self._catalogue_view(value, "brands")
            return
        if lowered == ["system", "catalogue"]:
            value = self.emukit.get_system_catalogue()
            self._json(value) if raw else self._catalogue_view(value, "systems")
            return
        if lowered == ["emulator", "catalogue"]:
            value = self.emukit.get_emulator_catalogue()
            self._json(value) if raw else self._catalogue_view(value, "emulators")
            return
        if lowered == ["settings"]:
            value = self.emukit.get_settings()
            self._json(value) if raw else self._settings(value)
            return
        if lowered == ["running", "emulators"]:
            value = self.emukit.get_running_emulators()
            self._json(value) if raw else self._running(value)
            return
        if lowered in (["current", "installs"], ["installed", "emulators"]):
            value = self.emukit.get_current_installs()
            self._json(value) if raw else self._installs(value)
            return
        if lowered in (["current", "modules"], ["installed", "modules"]):
            value = self.emukit.get_current_modules()
            self._json(value) if raw else self._modules(value)
            return
        if lowered == ["updates"]:
            value = self.emukit.get_updates(refresh=True)
            self._json(value) if raw else self._updates_view(value)
            return
        if lowered == ["status"]:
            value = self.emukit.get_status()
            if raw:
                self._json(value)
            else:
                self.ui.key_value_panel(
                    "EmuKit Status",
                    [("Core", value["core_version"]), ("Channel", value["channel"]), ("Platform", f'{value["platform"]} {value["architecture"]}'), ("Modules", f'{value["registered_count"]} local / {value["remote_module_count"]} remote'), ("Brands", value["supported_brands"]), ("Systems", value["supported_systems"])],
                )
            return
        if lowered == ["core", "dependencies"]:
            self._result(self.emukit.check_core_dependencies(), raw=raw, verbose=True)
            return
        if len(tokens) >= 2 and lowered[-1] == "catalogue":
            query_tokens = tokens[:-1]
            explicit_kind = None
            if query_tokens and query_tokens[0].casefold() in {"brand", "system", "emulator"}:
                explicit_kind = query_tokens[0].casefold()
                query_tokens = query_tokens[1:]
            query = " ".join(query_tokens).strip()
            if not query:
                self.ui.usage("Get <Brand|System|Emulator> Catalogue")
                return
            if explicit_kind == "brand":
                value = self.emukit.get_brand_entity_catalogue(query); kind = "Brand"
            elif explicit_kind == "system":
                value = self.emukit.get_system_entity_catalogue(query); kind = "System"
            elif explicit_kind == "emulator":
                value = self.emukit.get_emulator_entity_catalogue(query); kind = "Emulator"
            else:
                kind, value, matches = self.emukit.resolve_entity_catalogue(query)
                if value is None:
                    if matches:
                        self.ui.warning(f'"{query}" is ambiguous. Specify one of: ' + ", ".join(f"{match} {query}" for match in matches) + ".")
                    else:
                        self.ui.error(f'"{query}" was not found.')
                    return
            if value is None:
                self.ui.error(f'{kind} "{query}" was not found.')
            elif raw:
                self._json(value)
            else:
                self._entity_catalogue_view(kind, value)
            return
        if len(tokens) >= 2 and lowered[-1] == "info":
            query_tokens = tokens[:-1]
            explicit_kind = None
            if query_tokens and query_tokens[0].casefold() in {"emulator", "brand", "system"}:
                explicit_kind = query_tokens[0].casefold()
                query_tokens = query_tokens[1:]
            query = " ".join(query_tokens).strip()
            if not query:
                self.ui.usage("Get <Brand|System|Emulator> Info")
                return
            if explicit_kind == "emulator":
                value = self.emukit.get_module_info(query); kind = "Emulator"
            elif explicit_kind == "brand":
                value = self.emukit.get_brand_info(query); kind = "Brand"
            elif explicit_kind == "system":
                value = self.emukit.get_system_info(query); kind = "System"
            else:
                kind, value, matches = self.emukit.resolve_info(query)
                if value is None:
                    if matches:
                        self.ui.warning(f'"{query}" is ambiguous. Specify one of: ' + ", ".join(f"{match} {query}" for match in matches) + ".")
                    else:
                        self.ui.error(f'"{query}" was not found.')
                    return
            if value is None:
                self.ui.error(f'{kind} "{query}" was not found.')
            elif raw:
                self._json(value)
            else:
                {"Emulator": self._module_info, "Brand": self._brand_info, "System": self._system_info}[kind](value)
            return
        self.ui.warning("Unknown Get command. Type Help for available commands.")

    def execute(self, command: str) -> bool:
        assert self.emukit is not None
        try:
            tokens = shlex.split(command, posix=False)
            tokens = [
                token[1:-1]
                if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
                else token
                for token in tokens
            ]
        except ValueError as exc:
            self.ui.error(f"Invalid command: {exc}")
            return True

        tokens, raw, verbose = self._modifiers(tokens)
        if not tokens:
            return True
        action = tokens[0].casefold()
        args = tokens[1:]
        lowered_args = [arg.casefold() for arg in args]

        if action in {"exit", "quit"} or (action == "close" and not args):
            self.ui.info("Closing EmuKit")
            return False
        if action == "help":
            self._help()
            return True
        if action == "get":
            self._get(args, raw)
            return True

        if action == "updates":
            value = self.emukit.get_updates(refresh=True)
            self._json(value) if raw else self._updates_view(value)
            return True
        if action == "check" and lowered_args in (["updates"], ["for", "updates"]):
            value = self.emukit.get_updates(refresh=True)
            self._json(value) if raw else self._updates_view(value)
            return True

        if action == "update" and lowered_args == ["emukit"]:
            result = self.emukit.update_core()
            self._result(result, raw=raw, verbose=True)
            return False if result.get("success") and result.get("state") == "handoff_started" else True

        if action == "set" and len(args) >= 3 and lowered_args[:2] == ["feature", "fullscreen"]:
            value = self._parse_value(" ".join(args[2:]))
            self._result(self.emukit.update_setting("Fullscreen", value), raw=raw, verbose=verbose)
            return True

        if action == "set" and len(args) >= 4 and lowered_args[-1] == "primary" and "as" in lowered_args:
            as_index = lowered_args.index("as")
            emulator = " ".join(args[:as_index]).strip()
            system = " ".join(args[as_index + 1:-1]).strip()
            if not emulator or not system:
                self.ui.usage("Set <Emulator> as <System> Primary")
                return True
            self._result(self.emukit.set_system_primary(system, emulator), raw=raw, verbose=verbose)
            return True

        if action == "restore" and lowered_args == ["systems", "primary"]:
            self._result(self.emukit.restore_all_system_primaries(), raw=raw, verbose=verbose)
            return True
        if action == "restore" and len(args) >= 2 and lowered_args[-1] == "primary":
            system = " ".join(args[:-1]).strip()
            self._result(self.emukit.restore_system_primary(system), raw=raw, verbose=verbose)
            return True

        if action == "close" and args:
            self._result(self.emukit.close_emulator(" ".join(args)), raw=raw, verbose=verbose)
            return True
        if action == "restart" and args:
            self._result(self.emukit.restart_emulator(" ".join(args)), raw=raw, verbose=verbose)
            return True
        if action == "is" and len(args) >= 2 and lowered_args[-1] == "running":
            target = " ".join(args[:-1])
            self._result(self.emukit.is_emulator_running(target), raw=raw, verbose=True)
            return True

        if action == "install" and lowered_args == ["all"]:
            self._result(self.emukit.install_all(), raw=raw, verbose=verbose)
            return True
        if action == "uninstall" and lowered_args == ["all"]:
            self._result(self.emukit.uninstall_all(), raw=raw, verbose=verbose)
            return True
        if action == "remove" and lowered_args == ["all"]:
            self._result(self.emukit.remove_all(), raw=raw, verbose=verbose)
            return True

        if action in {"install", "uninstall", "repair", "remove", "update"}:
            if not args:
                self.ui.usage(f"{action.title()} <Emulator(s)>")
                return True
            modules = self._resolve_module_sequence(args)
            if modules is None:
                modules = [" ".join(args)]
            handler = {
                "install": self.emukit.install_many,
                "uninstall": self.emukit.uninstall_many,
                "repair": self.emukit.repair_many,
                "remove": self.emukit.remove_many,
                "update": self.emukit.update_many,
            }[action]
            self._result(handler(modules), raw=raw, verbose=verbose)
            return True

        if action == "launch" and args:
            whole = " ".join(args)
            local_module = self.emukit.manager.resolve_local_module_id(whole)
            if local_module is not None:
                self._result(self.emukit.launch_emulator(local_module), raw=raw, verbose=verbose)
                return True

            split = self._split_system_suffix(args)
            if split is None:
                self.ui.usage("Launch <Emulator> OR Launch <GamePath> <System> OR Launch <Emulator> <GamePath> <System>")
                return True
            prefix, system = split
            explicit = self._split_explicit_module_prefix(prefix)
            if explicit is not None:
                module, game_tokens = explicit
                game_path = " ".join(game_tokens)
                self._result(self.emukit.launch(system, game_path, module=module), raw=raw, verbose=verbose)
            else:
                game_path = " ".join(prefix)
                self._result(self.emukit.launch(system, game_path), raw=raw, verbose=verbose)
            return True

        self.ui.warning(f'Unknown command "{command}". Type Help for available commands.')
        return True

    def _dependency_preflight(self) -> bool:
        assert self.emukit is not None
        check = self.emukit.check_core_dependencies()
        missing = list(check.get("missing") or [])
        if not missing:
            self.ui.success("Core dependencies verified")
            return True

        dependency_lines = []
        for dependency_id in missing:
            info = self.emukit.manager.CORE_DEPENDENCIES.get(dependency_id, {})
            name = info.get("Name", dependency_id)
            version = info.get("Version")
            if isinstance(version, str) and version.casefold() == "latest supported":
                version_text = "Latest supported"
            else:
                version_text = str(version or "Required")
            dependency_lines.append(f"✗ {name} — {version_text}")

        self.ui.panel(
            "Required Dependencies",
            [
                "EmuKit requires the following components before it can start.",
                "",
                *dependency_lines,
                "",
                "EmuKit can install the required versions automatically.",
            ],
        )

        while True:
            try:
                answer = input(self.ui.yes_no_prompt("Install missing dependencies?", default_yes=True)).strip().casefold()
            except (EOFError, KeyboardInterrupt):
                print()
                self.ui.warning("Closing EmuKit")
                return False

            if answer in {"", "yes", "y"}:
                self.ui.info("Installing required dependencies...")
                result = self.emukit.install_missing_core_dependencies()
                result_details = result.get("details") if isinstance(result.get("details"), dict) else {}
                for item in result_details.get("results", []):
                    if isinstance(item, dict) and item.get("message"):
                        self.ui.info(str(item["message"]))

                if result.get("success"):
                    if result.get("state") == "installed_reboot_required":
                        self.ui.warning("Required dependencies installed; a Windows restart may be required")
                    else:
                        self.ui.success("Required dependencies installed")
                    return True

                remaining_check = result_details.get("check")
                remaining = list(remaining_check.get("missing") or []) if isinstance(remaining_check, dict) else []
                if remaining:
                    names = []
                    for dependency_id in remaining:
                        info = self.emukit.manager.CORE_DEPENDENCIES.get(dependency_id, {})
                        names.append(str(info.get("Name", dependency_id)))
                    self.ui.error("Could not install all required dependencies")
                    self.ui.panel("Still Missing", names)
                self.ui.error("EmuKit cannot continue")
                return False

            if answer in {"no", "n"}:
                self.ui.warning("Required dependencies were not installed; EmuKit will close")
                return False

            self.ui.warning("Please enter Yes or No")

    def run(self) -> None:
        self.ui.set_title("ProjectHomelab - EmuKit")
        self.emukit = EmuKit(
            auto_initialize=False,
            progress_callback=self.progress,
        )

        mode = "HomeLab" if self.emukit.project_root != self.emukit.emukit_root else "Standalone"
        self.ui.banner("EMUKIT")
        print()
        self.ui.runtime_panel([
            ("Mode", mode),
            ("Version", self.emukit.manager.CORE_VERSION),
            ("Platform", f"{self.emukit.manager.host_platform} {self.emukit.manager.host_architecture}"),
            ("Channel", self.emukit.manager.channel.title()),
            ("Status", "Starting..."),
        ])
        print()

        if not self._dependency_preflight():
            return

        self.ui.info("Initialising EmuKit...")
        result = self.emukit.initialize()
        self._clear_progress()

        if result.get("success") and isinstance(self.fresh_update_handoff, dict):
            cleanup = self.emukit.complete_fresh_update(self.fresh_update_handoff)
            if not cleanup.get("success"):
                self.ui.warning(cleanup.get("message") or "EmuKit update cleanup completed with errors")

        state = result.get("state")
        if state == "ready_with_errors" or not result.get("success"):
            self.ui.error("EmuKit started with errors")
        elif state == "ready_offline":
            self.ui.warning("EmuKit started with a remote-data warning")
            details = result.get("details") if isinstance(result.get("details"), dict) else {}
            remote = details.get("remote_manifest") if isinstance(details, dict) else None
            if isinstance(remote, dict):
                message = remote.get("message")
                if message:
                    self.ui.warning(str(message))
                remote_details = remote.get("details")
                if isinstance(remote_details, str) and remote_details.strip():
                    self.ui.warning(remote_details.strip())
        else:
            self.ui.success("EmuKit ready")

        installs = self.emukit.get_current_installs()
        print()
        self._installs(installs)
        print()
        self.ui.info("Type Help for commands")
        print()

        while True:
            try:
                command = input(self.ui.prompt()).strip()
            except EOFError:
                print()
                self.ui.warning("Closing EmuKit")
                break
            except KeyboardInterrupt:
                print()
                self.ui.warning("Closing EmuKit")
                break
            if command and not self.execute(command):
                break


def _fresh_update_handoff_from_argv(argv: list[str]) -> dict[str, Any] | None:
    if "--fresh-update" not in argv:
        return None
    result: dict[str, Any] = {}
    pairs = {
        "--from-version": "from_version",
        "--updater-pid": "updater_pid",
        "--updater-path": "updater_path",
        "--staging-path": "staging_path",
    }
    for flag, key in pairs.items():
        if flag not in argv:
            continue
        index = argv.index(flag)
        if index + 1 >= len(argv):
            continue
        value: Any = argv[index + 1]
        if key == "updater_pid":
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        result[key] = value
    return result


def main() -> None:
    handoff = _fresh_update_handoff_from_argv(sys.argv[1:])
    EmuKitConsole(fresh_update_handoff=handoff).run()


if __name__ == "__main__":
    main()
