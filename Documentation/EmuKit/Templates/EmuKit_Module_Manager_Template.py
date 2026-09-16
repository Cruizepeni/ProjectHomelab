from __future__ import annotations

from typing import Any, Callable

ProgressCallback = Callable[..., None] | None


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
    # Inspect emulator state only. Do not install or repair as a side effect.
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
    # Download/verify/install the emulator and its module-owned requirements.
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
    # Remove the managed emulator according to this module's data policy.
    return _result(
        "uninstall",
        True,
        "missing",
        "Example emulator uninstalled successfully.",
    )


def repair(progress: ProgressCallback = None) -> dict[str, Any]:
    # Restore the emulator to the module's known-good managed state.
    return _result(
        "repair",
        True,
        "installed",
        "Example emulator repaired successfully.",
        details={"version": "replace-with-detected-version"},
    )


def update(progress: ProgressCallback = None) -> dict[str, Any]:
    # Update the emulator itself. Core separately updates the module package.
    return _result(
        "update",
        True,
        "installed",
        "Example emulator update completed.",
        details={"version": "replace-with-detected-version"},
    )
