from __future__ import annotations

from pathlib import Path
from typing import Any


def _dependency_root() -> Path:
    # This is deliberately simplified example code.
    return Path("dependencies/EmuKit/ExampleEmu")


def check(progress=None) -> dict[str, Any]:
    executable = _dependency_root() / "exampleemu.exe"
    if not executable.is_file():
        return {
            "success": True,
            "operation": "check",
            "state": "missing",
            "message": "ExampleEmu is not installed.",
            "details": {"version": None},
        }
    return {
        "success": True,
        "operation": "check",
        "state": "installed",
        "message": "ExampleEmu is installed.",
        "details": {"version": "4.2.0"},
    }


def install(progress=None) -> dict[str, Any]:
    if progress:
        progress(percent=10, stage="Preparing", message="Preparing ExampleEmu installation.")
    # Real modules download, verify, and materialize their emulator here.
    if progress:
        progress(percent=100, stage="Installed", message="ExampleEmu installation complete.")
    return {
        "success": True,
        "operation": "install",
        "state": "installed",
        "message": "ExampleEmu installed successfully.",
        "details": {"version": "4.2.0"},
    }


def uninstall(progress=None) -> dict[str, Any]:
    return {
        "success": True,
        "operation": "uninstall",
        "state": "missing",
        "message": "ExampleEmu uninstalled successfully.",
        "details": None,
    }


def repair(progress=None) -> dict[str, Any]:
    return {
        "success": True,
        "operation": "repair",
        "state": "installed",
        "message": "ExampleEmu repaired successfully.",
        "details": {"version": "4.2.0"},
    }


def update(progress=None) -> dict[str, Any]:
    return {
        "success": True,
        "operation": "update",
        "state": "installed",
        "message": "ExampleEmu is on the module-supported emulator version.",
        "details": {"version": "4.2.0"},
    }
