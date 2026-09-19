from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


class EmuKitPlatformIntegration:
    """Small host-integration helpers that keep the main Core platform-neutral."""

    @staticmethod
    def apply_core_folder_identity(
        core_directory: str | Path,
        executable_relative: str | Path,
    ) -> dict[str, Any]:
        core_directory = Path(core_directory).resolve()
        executable_relative = Path(executable_relative)

        if os.name != "nt":
            return {
                "success": True,
                "state": "not_applicable",
                "message": "Folder icon integration is only used on Windows.",
            }

        executable = (core_directory / executable_relative).resolve()
        try:
            executable.relative_to(core_directory)
        except ValueError:
            return {
                "success": False,
                "state": "invalid_executable",
                "message": "Core executable must be inside the Core directory.",
            }

        if not executable.is_file():
            return {
                "success": True,
                "state": "executable_not_present",
                "message": "Core executable is not present; folder icon was not applied.",
            }

        desktop_ini = core_directory / "desktop.ini"
        icon_resource = executable_relative.as_posix().replace("/", "\\")
        content = "[.ShellClassInfo]\r\n" f"IconResource={icon_resource},0\r\n"

        try:
            # Explorer handles desktop.ini most reliably as Unicode text.
            desktop_ini.write_text(content, encoding="utf-16")
            subprocess.run(
                ["attrib", "+h", "+s", str(desktop_ini)],
                capture_output=True,
                text=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # Read-only on a Windows folder is the shell customization flag; it
            # does not prevent normal writes to files inside the directory.
            subprocess.run(
                ["attrib", "+r", str(core_directory)],
                capture_output=True,
                text=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return {
                "success": True,
                "state": "applied",
                "message": "EmuKit Core folder icon applied.",
                "details": str(desktop_ini),
            }
        except Exception as exc:
            return {
                "success": False,
                "state": "apply_failed",
                "message": "EmuKit Core folder icon could not be applied.",
                "details": str(exc),
            }
