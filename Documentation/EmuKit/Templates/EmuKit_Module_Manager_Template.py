from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

ProgressCallback = Callable[..., None] | None


def _resolve_root() -> Path:
    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / ".ProjectHomelabRoot").is_file():
            return candidate
    if current.parent.name == "EmuKitModules":
        return current.parent.parent
    return current


ROOT = _resolve_root()
EMULATOR_DIR = ROOT / "Emulators" / "ReplaceModule"


def _result(
    operation: str,
    success: bool,
    state: str,
    message: str,
    *,
    error: str | None = None,
    details: Any = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "success": success,
        "operation": operation,
        "state": state,
        "message": message,
        "details": details,
    }
    if error is not None:
        value["error"] = error
    return value


def check(progress: ProgressCallback = None) -> dict[str, Any]:
    return _result(
        "check",
        True,
        "missing",
        "Example emulator is not installed.",
        details={"version": None},
    )


def install(progress: ProgressCallback = None) -> dict[str, Any]:
    if progress:
        progress(percent=0, stage="Starting", message="Starting installation.")
    EMULATOR_DIR.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(percent=100, stage="Installed", message="Installation complete.")
    return _result(
        "install",
        True,
        "installed",
        "Example emulator installed successfully.",
        details={"version": "replace-with-detected-version"},
    )


def uninstall(progress: ProgressCallback = None) -> dict[str, Any]:
    return _result(
        "uninstall",
        True,
        "missing",
        "Example emulator uninstalled successfully.",
    )


def repair(progress: ProgressCallback = None) -> dict[str, Any]:
    return _result(
        "repair",
        True,
        "installed",
        "Example emulator repaired successfully.",
        details={"version": "replace-with-detected-version"},
    )


def update(progress: ProgressCallback = None) -> dict[str, Any]:
    return _result(
        "update",
        True,
        "installed",
        "Example emulator update completed.",
        details={"version": "replace-with-detected-version"},
    )
