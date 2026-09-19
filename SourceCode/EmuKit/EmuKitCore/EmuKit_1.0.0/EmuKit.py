from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

try:
    from .EmuKitManager import EmuKitManager
    from .EmuKitSettings import EmuKitSettings
except ImportError:
    from EmuKitManager import EmuKitManager
    from EmuKitSettings import EmuKitSettings


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

        self.settings = EmuKitSettings(project_root=self.project_root)
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

    def initialize(self) -> dict[str, Any]:
        self.initialization_result = self.manager.initialize()
        return self.initialization_result

    def check(self) -> dict[str, Any]:
        return self.manager.reconcile()

    def install(self, module: str) -> dict[str, Any]:
        return self.manager.install(module)

    def install_all(self) -> dict[str, Any]:
        return self.manager.install_all()

    def uninstall(self, module: str) -> dict[str, Any]:
        return self.manager.uninstall(module)

    def remove_module(self, module: str) -> dict[str, Any]:
        return self.manager.remove_module(module)

    def repair(self, module: str) -> dict[str, Any]:
        return self.manager.repair(module)

    def update(self, module: str) -> dict[str, Any]:
        return self.manager.update(module)

    def update_module(self, module: str) -> dict[str, Any]:
        return self.manager.update_module_package(module)

    def check_module(self, module: str) -> dict[str, Any]:
        return self.manager.check_module(module)

    def refresh_modules(self) -> dict[str, Any]:
        return self.manager.refresh_remote_manifest()

    def check_core_dependencies(self) -> dict[str, Any]:
        return self.manager.check_core_dependencies()

    def install_core_dependency(self, dependency_id: str) -> dict[str, Any]:
        return self.manager.install_core_dependency(dependency_id)

    def install_missing_core_dependencies(self) -> dict[str, Any]:
        return self.manager.install_missing_core_dependencies()

    def launch(self, system: str, game_path: str | Path) -> dict[str, Any]:
        return self.manager.launch(system=system, game_path=game_path)

    def launch_emulator(self, module: str) -> dict[str, Any]:
        return self.manager.launch_emulator(module)

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

    def assign_system(self, system: str, module: str | None) -> dict[str, Any]:
        return self.manager.assign_system(system, module)

    def get_registry(self) -> dict[str, Any]:
        return self.manager.get_registry()

    def get_status(self) -> dict[str, Any]:
        return self.manager.get_status()

    def get_current_installs(self) -> list[dict[str, Any]]:
        return self.manager.get_current_installs()

    def get_supported_modules(self) -> list[dict[str, Any]]:
        return self.manager.get_supported_modules()

    def get_supported_brands(self) -> list[dict[str, Any]]:
        return self.manager.get_supported_brands()

    def get_supported_platforms(self) -> list[dict[str, Any]]:
        return self.manager.get_supported_platforms()

    def get_supported_systems(
        self,
        *,
        brand: str | None = None,
        platform: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.manager.get_supported_systems(
            brand=brand,
            platform=platform,
        )

    def get_module_info(self, module: str) -> dict[str, Any] | None:
        module_id = self.manager.resolve_module_id(module)
        return (
            self.manager.get_module_info(module_id)
            if module_id is not None
            else None
        )

    def get_brand_info(self, brand: str) -> dict[str, Any] | None:
        return self.manager.get_brand_info(brand)

    def get_platform_info(self, platform: str) -> dict[str, Any] | None:
        return self.manager.get_platform_info(platform)

    def get_system_info(self, system: str) -> dict[str, Any] | None:
        return self.manager.get_system_info(system)

    def resolve_info(
        self,
        query: str,
    ) -> tuple[str | None, dict[str, Any] | None, list[str]]:
        matches: list[tuple[str, dict[str, Any]]] = []
        for kind, getter in (
            ("Module", self.get_module_info),
            ("Brand", self.get_brand_info),
            ("Platform", self.get_platform_info),
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
    def __init__(self) -> None:
        self.emukit: EmuKit | None = None
        self._progress_active = False
        self._progress_rendered: str | None = None

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
        suffix = f" {percent:3d}%" if isinstance(percent, int) else ""
        message = " ".join(str(event.get("message") or "").split())
        terminal_width = shutil.get_terminal_size(fallback=(100, 24)).columns
        line_width = max(1, terminal_width - 1)
        base = f"{module_name:<24} {stage}{suffix}"
        text = base

        if message and percent != 100:
            remaining = line_width - len(base) - 2
            if remaining > 3:
                detail = message
                if len(detail) > remaining:
                    detail = detail[: remaining - 3] + "..."
                text = f"{base}  {detail}"

        if len(text) > line_width:
            if line_width > 3:
                text = text[: line_width - 3] + "..."
            else:
                text = text[:line_width]

        rendered = text.ljust(line_width)
        if rendered != self._progress_rendered:
            print("\r" + rendered, end="", flush=True)
            self._progress_rendered = rendered
        self._progress_active = True

        if percent == 100:
            print()
            self._progress_active = False
            self._progress_rendered = None

    def _clear_progress(self) -> None:
        if self._progress_active:
            print()
            self._progress_active = False
            self._progress_rendered = None

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
        message = result.get("message")
        if message:
            print(message)
        if not result.get("success", False):
            error = result.get("error")
            if error:
                print(f"Error: {error}")
            details = result.get("details")
            if details is not None and details != "":
                if isinstance(details, (dict, list)):
                    self._json(details)
                else:
                    print(f"Details: {details}")
        elif verbose and result.get("details") is not None:
            self._json(result["details"])

    @staticmethod
    def _name_list(
        title: str,
        values: list[dict[str, Any]],
        *,
        display_key: str = "Name",
    ) -> None:
        print(title)
        if not values:
            print("  None")
            return
        for value in values:
            name = value.get(display_key) or value.get("Name") or value.get("Id", "Unknown")
            suffix = ""
            if title == "Supported Modules":
                if value.get("LocalInstalled"):
                    suffix = " [Installed]"
                elif value.get("RemoteAvailable"):
                    suffix = " [Available]"
                if value.get("ModuleUpdateAvailable"):
                    suffix += " [Update Available]"
            print(f"  {name}{suffix}")

    def _settings(self, settings: dict[str, Any]) -> None:
        print("EmuKit Settings")
        print(f'  Fullscreen: {"On" if settings.get("Fullscreen") else "Off"}')
        print("  Modules:")
        modules = settings.get("Modules", {})
        if not modules:
            print("    None")
        for module_id, value in sorted(modules.items()):
            state = "Enabled" if value.get("Enabled") else "Disabled"
            print(f"    {module_id:<24} {state}")

        print("  System Assignments:")
        assignments = settings.get("SystemAssignments", {})
        if not assignments:
            print("    None")
        for system_id, module_id in sorted(assignments.items()):
            print(f"    {system_id:<24} {module_id or 'Unassigned'}")

    def _module_settings(self, value: dict[str, Any]) -> None:
        print(value["Name"])
        print(f'  Enabled: {"Yes" if value.get("Enabled") else "No"}')

    def _module_info(self, value: dict[str, Any]) -> None:
        print(value["Name"])
        print(f'  Module ID: {value["Id"]}')
        aliases = value.get("Aliases", [])
        if aliases:
            print(f'  Aliases: {", ".join(aliases)}')
        print(f'  Module Installed: {"Yes" if value.get("LocalInstalled") else "No"}')
        print(f'  Remote Available: {"Yes" if value.get("RemoteAvailable") else "No"}')
        if value.get("ModuleVersion"):
            print(f'  Module Version: {value.get("ModuleVersion")}')
        if value.get("EmulatorVersion"):
            print(f'  Emulator Version: {value.get("EmulatorVersion")}')
        if value.get("RemoteModuleVersion"):
            print(f'  Remote Module Version: {value.get("RemoteModuleVersion")}')
        if value.get("ModuleUpdateAvailable"):
            print("  Module Update: Available")
        if value.get("DependencyPath"):
            print(f'  Dependency: {value["DependencyPath"]}')
        if value.get("LaunchPath"):
            print(f'  Launch: {value["LaunchPath"]}')
        systems = value.get("Systems", {})
        if systems:
            print("  Systems:")
            for system_id, system in sorted(
                systems.items(),
                key=lambda item: item[1]["Name"].casefold(),
            ):
                print(f'    {system["Brand"]["Name"]} {system["Name"]} ({system_id})')

    def _brand_info(self, value: dict[str, Any]) -> None:
        print(value["Name"])
        print(f'  Brand ID: {value["Id"]}')
        aliases = value.get("Aliases", [])
        if aliases:
            print(f'  Aliases: {", ".join(aliases)}')
        print("  Systems:")
        for system in sorted(
            value.get("SystemDetails", []),
            key=lambda item: item["Name"].casefold(),
        ):
            print(f'    {system["Name"]}')

    def _platform_info(self, value: dict[str, Any]) -> None:
        print(value["Name"])
        print(f'  Platform ID: {value["Id"]}')
        aliases = value.get("Aliases", [])
        if aliases:
            print(f'  Aliases: {", ".join(aliases)}')
        print("  Systems:")
        for system in sorted(
            value.get("SystemDetails", []),
            key=lambda item: item["Name"].casefold(),
        ):
            print(f'    {system["Name"]}')

    def _system_info(self, value: dict[str, Any]) -> None:
        print(value.get("DisplayName") or value["Name"])
        print(f'  System ID: {value["Id"]}')
        aliases = value.get("Aliases", [])
        if aliases:
            print(f'  Aliases: {", ".join(aliases)}')
        print(f'  Brand: {value["Brand"]["Name"]}')
        print(f'  Platform: {value["Platform"]["Name"]}')
        print(f'  Assigned Module: {value.get("AssignedModule") or "Unassigned"}')
        print(f'  Supported Modules: {", ".join(value.get("Modules", [])) or "None"}')

    def _installs(self, values: list[dict[str, Any]]) -> None:
        print("Emulators Installed")
        if not values:
            print("  None")
            return
        for value in values:
            version = value.get("Version") or "Unknown version"
            state = str(value.get("State", "")).replace("_", " ").title()
            print(f'{value["Name"]:<24} {version:<24} {state}')
        print(
            f"\n{len(values)} emulator module"
            f'{"s" if len(values) != 1 else ""} installed.'
        )

    @staticmethod
    def _filters(tokens: list[str]) -> tuple[str | None, str | None]:
        brand = None
        platform = None
        index = 0
        while index < len(tokens):
            key = tokens[index].casefold()
            if key not in {"brand", "platform"}:
                index += 1
                continue
            end = index + 1
            while (
                end < len(tokens)
                and tokens[end].casefold() not in {"brand", "platform"}
            ):
                end += 1
            value = " ".join(tokens[index + 1:end]).strip()
            if key == "brand":
                brand = value or None
            else:
                platform = value or None
            index = end
        return brand, platform

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

    @staticmethod
    def _help() -> None:
        print(
            "Commands:\n"
            "  Get Settings\n"
            "  Get <Module> Settings\n"
            "  Update Setting <Setting> <Value>\n"
            "  Install <Module>\n"
            "  Install All\n"
            "  Uninstall <Module>\n"
            "  Remove Module <Module>\n"
            "  Repair <Module>\n"
            "  Update <Module>                 (updates emulator)\n"
            "  Update Module <Module>          (updates module package)\n"
            "  Check <Module>\n"
            "  Refresh Modules\n"
            "  Get <Name> Info\n"
            "  Get Module <Name> Info\n"
            "  Get Brand <Name> Info\n"
            "  Get Platform <Name> Info\n"
            "  Get System <Name> Info\n"
            "  Get Current Installs\n"
            "  Get Supported Modules\n"
            "  Get Supported Brands\n"
            "  Get Supported Platforms\n"
            "  Get Supported Systems [Brand <Name>] [Platform <Name>]\n"
            "  Get Status\n"
            "  Get Core Dependencies\n"
            "  Assign System <System> <Module|None>\n"
            "  Launch <GamePath> <System>\n"
            "  Launch Emulator <Module>\n"
            "  Help\n"
            "  Close\n"
            "\nAdd --json for raw output or --verbose for additional operation details."
        )

    def _get(self, tokens: list[str], raw: bool) -> None:
        assert self.emukit is not None
        lowered = [token.casefold() for token in tokens]

        if lowered == ["settings"]:
            value = self.emukit.get_settings()
            self._json(value) if raw else self._settings(value)
            return

        if lowered == ["current", "installs"]:
            value = self.emukit.get_current_installs()
            self._json(value) if raw else self._installs(value)
            return

        if lowered == ["supported", "modules"]:
            value = self.emukit.get_supported_modules()
            self._json(value) if raw else self._name_list(
                "Supported Modules",
                value,
            )
            return

        if lowered == ["supported", "brands"]:
            value = self.emukit.get_supported_brands()
            self._json(value) if raw else self._name_list(
                "Supported Brands",
                value,
            )
            return

        if lowered == ["supported", "platforms"]:
            value = self.emukit.get_supported_platforms()
            self._json(value) if raw else self._name_list(
                "Supported Platforms",
                value,
            )
            return

        if len(tokens) >= 2 and lowered[:2] == ["supported", "systems"]:
            brand, platform = self._filters(tokens[2:])
            value = self.emukit.get_supported_systems(
                brand=brand,
                platform=platform,
            )
            self._json(value) if raw else self._name_list(
                "Supported Systems",
                value,
                display_key="DisplayName",
            )
            return

        if lowered == ["status"]:
            value = self.emukit.get_status()
            if raw:
                self._json(value)
            else:
                print(
                    f'Core {value["core_version"]} | '
                    f'Channel: {value["channel"]} | '
                    f'Platform: {value["platform"]}/{value["architecture"]}'
                )
                print(
                    f'Modules: {value["registered_count"]} local / '
                    f'{value["remote_module_count"]} remote | '
                    f'Brands: {value["supported_brands"]} | '
                    f'Platforms: {value["supported_platforms"]} | '
                    f'Systems: {value["supported_systems"]}'
                )
            return

        if lowered == ["core", "dependencies"]:
            value = self.emukit.check_core_dependencies()
            self._result(value, raw=raw, verbose=True)
            return

        if len(tokens) >= 3 and lowered[0] == "module" and lowered[-1] == "settings":
            query = " ".join(tokens[1:-1])
            value = self.emukit.get_module_settings(query)
            if value is None:
                print(f'Module "{query}" was not found locally.')
            elif raw:
                self._json(value)
            else:
                self._module_settings(value)
            return

        if len(tokens) >= 2 and lowered[-1] == "settings":
            query = " ".join(tokens[:-1])
            value = self.emukit.get_module_settings(query)
            if value is None:
                print(f'Module "{query}" was not found locally.')
            elif raw:
                self._json(value)
            else:
                self._module_settings(value)
            return

        if (
            len(tokens) >= 3
            and lowered[-1] == "info"
            and lowered[0] in {"module", "brand", "platform", "system"}
        ):
            kind = lowered[0]
            query = " ".join(tokens[1:-1])
            getter = {
                "module": self.emukit.get_module_info,
                "brand": self.emukit.get_brand_info,
                "platform": self.emukit.get_platform_info,
                "system": self.emukit.get_system_info,
            }[kind]
            value = getter(query)
            if value is None:
                print(f'{kind.title()} "{query}" was not found.')
            elif raw:
                self._json(value)
            else:
                {
                    "module": self._module_info,
                    "brand": self._brand_info,
                    "platform": self._platform_info,
                    "system": self._system_info,
                }[kind](value)
            return

        if len(tokens) >= 2 and lowered[-1] == "info":
            query = " ".join(tokens[:-1])
            kind, value, matches = self.emukit.resolve_info(query)
            if value is None:
                if matches:
                    print(
                        f'"{query}" is ambiguous. Specify one of: '
                        f'{", ".join(matches)}.'
                    )
                else:
                    print(f'"{query}" was not found.')
                return
            if raw:
                self._json(value)
            else:
                {
                    "Module": self._module_info,
                    "Brand": self._brand_info,
                    "Platform": self._platform_info,
                    "System": self._system_info,
                }[kind](value)
            return

        print("Unknown Get command. Type Help for available commands.")

    def execute(self, command: str) -> bool:
        assert self.emukit is not None
        try:
            tokens = shlex.split(command, posix=False)
            tokens = [
                token[1:-1]
                if (
                    len(token) >= 2
                    and token[0] == token[-1]
                    and token[0] in {'"', "'"}
                )
                else token
                for token in tokens
            ]
        except ValueError as exc:
            print(f"Invalid command: {exc}")
            return True

        tokens, raw, verbose = self._modifiers(tokens)
        if not tokens:
            return True

        action = tokens[0].casefold()
        args = tokens[1:]

        if action in {"close", "exit", "quit"}:
            print("Closing EmuKit.")
            return False

        if action == "help":
            self._help()
            return True

        if action == "get":
            self._get(args, raw)
            return True

        if action == "refresh" and [arg.casefold() for arg in args] == ["modules"]:
            self._result(
                self.emukit.refresh_modules(),
                raw=raw,
                verbose=True,
            )
            return True

        if (
            action == "update"
            and len(args) >= 3
            and args[0].casefold() == "setting"
        ):
            setting = args[1]
            value = self._parse_value(" ".join(args[2:]))
            self._result(
                self.emukit.update_setting(setting, value),
                raw=raw,
                verbose=verbose,
            )
            return True

        if action == "install" and len(args) == 1 and args[0].casefold() == "all":
            self._result(
                self.emukit.install_all(),
                raw=raw,
                verbose=verbose,
            )
            return True

        if action == "remove" and len(args) >= 2 and args[0].casefold() == "module":
            module = " ".join(args[1:])
            self._result(
                self.emukit.remove_module(module),
                raw=raw,
                verbose=verbose,
            )
            return True

        if action == "update" and len(args) >= 2 and args[0].casefold() == "module":
            module = " ".join(args[1:])
            self._result(
                self.emukit.update_module(module),
                raw=raw,
                verbose=verbose,
            )
            return True

        if action in {"install", "uninstall", "repair", "update", "check"}:
            if not args:
                print(f"Usage: {action.title()} <Module>")
                return True

            module = " ".join(args)
            handler = {
                "install": self.emukit.install,
                "uninstall": self.emukit.uninstall,
                "repair": self.emukit.repair,
                "update": self.emukit.update,
                "check": self.emukit.check_module,
            }[action]
            self._result(
                handler(module),
                raw=raw,
                verbose=verbose,
            )
            return True

        if (
            action == "assign"
            and len(args) >= 3
            and args[0].casefold() == "system"
        ):
            system = args[1]
            module = " ".join(args[2:])
            if module.casefold() in {"none", "null", "unassigned"}:
                module = None
            self._result(
                self.emukit.assign_system(system, module),
                raw=raw,
                verbose=verbose,
            )
            return True

        if action == "launch" and len(args) >= 2 and args[0].casefold() == "emulator":
            module = " ".join(args[1:])
            self._result(
                self.emukit.launch_emulator(module),
                raw=raw,
                verbose=verbose,
            )
            return True

        if action == "launch" and len(args) >= 2:
            game_path = " ".join(args[:-1])
            system = args[-1]
            self._result(
                self.emukit.launch(system, game_path),
                raw=raw,
                verbose=verbose,
            )
            return True

        print(f'Unknown command "{command}". Type Help for available commands.')
        return True

    def _dependency_preflight(self) -> bool:
        assert self.emukit is not None
        check = self.emukit.check_core_dependencies()
        missing = list(check.get("missing") or [])
        if not missing:
            return True

        details = check.get("details") if isinstance(check.get("details"), dict) else {}

        print()
        print("EmuKit cannot start because required dependencies are missing:")
        for dependency_id in missing:
            info = self.emukit.manager.CORE_DEPENDENCIES.get(dependency_id, {})
            name = info.get("Name", dependency_id)
            version = info.get("Version")
            if isinstance(version, str) and version.casefold() == "latest supported":
                suffix = " (latest supported)"
            else:
                suffix = f" {version}" if version else ""
            print(f"  - {name}{suffix}")

        print()
        print("EmuKit requires these dependencies to run.")
        print("You can install the required versions manually, or EmuKit can install them automatically.")
        print("If you choose No, EmuKit will close.")

        while True:
            try:
                answer = input(
                    "Would you like EmuKit to install the missing dependencies now? Yes/No: "
                ).strip().casefold()
            except (EOFError, KeyboardInterrupt):
                print("\nClosing EmuKit.")
                return False

            if answer in {"yes", "y"}:
                print()
                print("Installing required dependencies...")
                result = self.emukit.install_missing_core_dependencies()
                result_details = (
                    result.get("details")
                    if isinstance(result.get("details"), dict)
                    else {}
                )
                for item in result_details.get("results", []):
                    if isinstance(item, dict) and item.get("message"):
                        print(f'  {item["message"]}')

                if result.get("success"):
                    if result.get("state") == "installed_reboot_required":
                        print("Required dependencies are installed. A Windows restart may be required.")
                    else:
                        print("Required dependencies are installed.")
                    print()
                    return True

                remaining_check = result_details.get("check")
                remaining = (
                    list(remaining_check.get("missing") or [])
                    if isinstance(remaining_check, dict)
                    else []
                )
                if remaining:
                    print()
                    print("EmuKit could not install all required dependencies:")
                    for dependency_id in remaining:
                        info = self.emukit.manager.CORE_DEPENDENCIES.get(dependency_id, {})
                        print(f'  - {info.get("Name", dependency_id)}')
                print("EmuKit cannot continue and will close.")
                return False

            if answer in {"no", "n"}:
                print("Required dependencies were not installed. EmuKit will close.")
                return False

            print("Please enter Yes or No.")

    def run(self) -> None:
        print("EmuKit starting...")
        self.emukit = EmuKit(
            auto_initialize=False,
            progress_callback=self.progress,
        )

        if not self._dependency_preflight():
            return

        result = self.emukit.initialize()
        self._clear_progress()

        state = result.get("state")
        if state == "ready_with_errors" or not result.get("success"):
            print("EmuKit started with errors.")
        else:
            print("EmuKit started.")

        installs = self.emukit.get_current_installs()
        print()
        self._installs(installs)
        print("\nType Help for commands.\n")

        while True:
            try:
                command = input("EmuKit> ").strip()
            except EOFError:
                print("\nClosing EmuKit.")
                break
            except KeyboardInterrupt:
                print("\nClosing EmuKit.")
                break
            if command and not self.execute(command):
                break


def main() -> None:
    EmuKitConsole().run()


if __name__ == "__main__":
    main()
