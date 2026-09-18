from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class EmuKitLauncher:
    def __init__(self, settings, project_root: str | Path) -> None:
        self.settings = settings
        self.project_root = Path(project_root).resolve()

    @staticmethod
    def _spawn_external(command: list[str], working_directory: Path, isolate_console: bool = False) -> subprocess.Popen[Any]:
        frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
        kernel32 = ctypes.windll.kernel32 if frozen_windows else None
        restore_directory = str(getattr(sys, "_MEIPASS", "")) or None if frozen_windows else None

        if kernel32 is not None:
            kernel32.SetDllDirectoryW(None)

        try:
            if os.name == "nt" and isolate_console:
                comspec = os.environ.get("ComSpec") or str(Path(os.environ.get("SystemRoot", r"C:\\Windows")) / "System32" / "cmd.exe")
                helper = [comspec, "/d", "/c", "start", "", "/b", *command]
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                return subprocess.Popen(
                    helper,
                    cwd=str(working_directory),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    startupinfo=startupinfo,
                )
            return subprocess.Popen(command, cwd=str(working_directory))
        finally:
            if kernel32 is not None:
                kernel32.SetDllDirectoryW(restore_directory)

    @staticmethod
    def _isolate_launch_console(module_info: dict[str, Any], system_info: dict[str, Any] | None = None) -> bool:
        if isinstance(system_info, dict) and "IsolateLaunchConsole" in system_info:
            return system_info.get("IsolateLaunchConsole") is True
        return module_info.get("IsolateLaunchConsole") is True

    def _resolve_project_path(self, configured_path: str) -> Path:
        path = Path(configured_path)
        if path.is_absolute():
            return path
        return (self.project_root / path).resolve()

    @staticmethod
    def _fullscreen_tokens(system_info: dict[str, Any]) -> list[str]:
        raw = system_info.get("FullscreenArgument")
        if raw is None:
            return []
        if isinstance(raw, str):
            return [raw] if raw else []
        if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
            return [item for item in raw if item]
        return []

    def _build_game_arguments(
        self,
        *,
        game_path: Path,
        system_id: str,
        system_info: dict[str, Any],
    ) -> list[str]:
        raw_args = system_info.get("LaunchArguments", [])
        if not isinstance(raw_args, list) or not all(isinstance(item, str) for item in raw_args):
            raise ValueError(f'System "{system_id}" has invalid LaunchArguments.')

        fullscreen_tokens = self._fullscreen_tokens(system_info) if self.settings.get_fullscreen() else []
        result: list[str] = []

        for token in raw_args:
            if token == "{fullscreen}":
                result.extend(fullscreen_tokens)
                continue

            rendered = token.replace("{game}", str(game_path)).replace("{system}", system_id)

            if "{fullscreen}" in rendered:
                replacement = fullscreen_tokens[0] if fullscreen_tokens else ""
                rendered = rendered.replace("{fullscreen}", replacement)
                if not rendered:
                    continue

            if rendered:
                result.append(rendered)

        return result

    def _resolve_launch_target(
        self,
        *,
        module_id: str,
        module_info: dict[str, Any],
        system_info: dict[str, Any] | None = None,
    ) -> tuple[Path, Path]:
        launch_path_raw = (
            system_info.get("LaunchPath")
            if isinstance(system_info, dict)
            else None
        ) or module_info.get("LaunchPath")

        if not isinstance(launch_path_raw, str) or not launch_path_raw.strip():
            raise ValueError(f'Module "{module_id}" does not declare a valid LaunchPath.')

        executable = self._resolve_project_path(launch_path_raw)
        if not executable.exists():
            raise FileNotFoundError(f'Module "{module_id}" launch executable was not found: "{executable}".')

        working_directory_raw = (
            system_info.get("WorkingDirectory")
            if isinstance(system_info, dict)
            else None
        ) or module_info.get("WorkingDirectory")

        working_directory = (
            self._resolve_project_path(working_directory_raw)
            if isinstance(working_directory_raw, str) and working_directory_raw.strip()
            else executable.parent
        )
        return executable, working_directory

    def launch_game(
        self,
        *,
        game_path: str | Path,
        system_id: str,
        module_id: str,
        registry: dict[str, Any],
    ) -> dict[str, Any]:
        game = Path(game_path).expanduser().resolve()
        if not game.exists():
            return {
                "success": False,
                "operation": "launch",
                "state": "launch_failed",
                "error": "game_not_found",
                "message": f'Game path does not exist: "{game}".',
                "details": None,
            }

        modules = registry.get("Modules", {})
        module_info = modules.get(module_id) if isinstance(modules, dict) else None
        if not isinstance(module_info, dict):
            return {
                "success": False,
                "module": module_id,
                "operation": "launch",
                "state": "launch_failed",
                "error": "module_not_registered",
                "message": f'Assigned module "{module_id}" is not registered with EmuKit.',
                "details": None,
            }

        systems = module_info.get("Systems", {})
        system_info = systems.get(system_id) if isinstance(systems, dict) else None
        if not isinstance(system_info, dict):
            return {
                "success": False,
                "module": module_id,
                "operation": "launch",
                "state": "launch_failed",
                "error": "system_not_supported",
                "message": f'Module "{module_id}" does not declare support for system "{system_id}".',
                "details": None,
            }

        try:
            executable, working_directory = self._resolve_launch_target(
                module_id=module_id,
                module_info=module_info,
                system_info=system_info,
            )
            arguments = self._build_game_arguments(
                game_path=game,
                system_id=system_id,
                system_info=system_info,
            )
            command = [str(executable), *arguments]
            process = self._spawn_external(command, working_directory, self._isolate_launch_console(module_info, system_info))
            return {
                "success": True,
                "module": module_id,
                "system": system_id,
                "operation": "launch",
                "state": "launched",
                "message": f'Launched system "{system_id}" with module "{module_id}".',
                "details": None,
                "pid": process.pid,
                "command": command,
            }
        except FileNotFoundError as exc:
            return {
                "success": False,
                "module": module_id,
                "system": system_id,
                "operation": "launch",
                "state": "launch_failed",
                "error": "module_executable_missing",
                "message": str(exc),
                "details": None,
            }
        except Exception as exc:
            return {
                "success": False,
                "module": module_id,
                "system": system_id,
                "operation": "launch",
                "state": "launch_failed",
                "error": "launch_exception",
                "message": f'Module "{module_id}" failed while launching system "{system_id}".',
                "details": str(exc),
            }

    def launch_emulator(
        self,
        *,
        module_id: str,
        registry: dict[str, Any],
    ) -> dict[str, Any]:
        modules = registry.get("Modules", {})
        module_info = modules.get(module_id) if isinstance(modules, dict) else None
        if not isinstance(module_info, dict):
            return {
                "success": False,
                "module": module_id,
                "operation": "launch_emulator",
                "state": "launch_failed",
                "error": "module_not_registered",
                "message": f'Module "{module_id}" is not registered with EmuKit.',
                "details": None,
            }

        raw_args = module_info.get("EmulatorLaunchArguments", [])
        if raw_args is None:
            raw_args = []
        if not isinstance(raw_args, list) or not all(isinstance(item, str) for item in raw_args):
            return {
                "success": False,
                "module": module_id,
                "operation": "launch_emulator",
                "state": "launch_failed",
                "error": "invalid_launch_arguments",
                "message": f'Module "{module_id}" has invalid EmulatorLaunchArguments.',
                "details": None,
            }

        try:
            executable, working_directory = self._resolve_launch_target(
                module_id=module_id,
                module_info=module_info,
            )
            command = [str(executable), *raw_args]
            process = self._spawn_external(command, working_directory, self._isolate_launch_console(module_info))
            return {
                "success": True,
                "module": module_id,
                "operation": "launch_emulator",
                "state": "launched",
                "message": f'Launched emulator for module "{module_id}".',
                "details": None,
                "pid": process.pid,
                "command": command,
            }
        except FileNotFoundError as exc:
            return {
                "success": False,
                "module": module_id,
                "operation": "launch_emulator",
                "state": "launch_failed",
                "error": "module_executable_missing",
                "message": str(exc),
                "details": None,
            }
        except Exception as exc:
            return {
                "success": False,
                "module": module_id,
                "operation": "launch_emulator",
                "state": "launch_failed",
                "error": "launch_exception",
                "message": f'Module "{module_id}" failed while launching its emulator.',
                "details": str(exc),
            }
