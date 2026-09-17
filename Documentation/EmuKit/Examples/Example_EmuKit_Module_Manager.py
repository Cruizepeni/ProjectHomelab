from __future__ import annotations

from pathlib import Path
from typing import Any


def _resolve_root() -> Path:
    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / ".ProjectHomelabRoot").is_file():
            return candidate
    if current.parent.name == "EmuKitModules":
        return current.parent.parent
    return current


ROOT = _resolve_root()
EMULATOR_DIR = ROOT / "Emulators" / "ExampleEmu"
EXECUTABLE = EMULATOR_DIR / "exampleemu.exe"


def check(progress=None) -> dict[str, Any]:
    if not EXECUTABLE.is_file():
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
    EMULATOR_DIR.mkdir(parents=True, exist_ok=True)
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
