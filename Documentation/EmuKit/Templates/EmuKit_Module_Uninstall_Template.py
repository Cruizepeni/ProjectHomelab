from __future__ import annotations

from typing import Any

from _ReplaceModuleCommon import ProgressCallback, emit_progress


def result(
    success: bool,
    state: str,
    message: str,
    error: str | None = None,
    details: Any = None,
) -> dict[str, Any]:
    value = {
        "success": success,
        "module": "replace-with-module-id",
        "operation": "uninstall",
        "state": state,
        "message": message,
        "details": details,
    }
    if error:
        value["error"] = error
    return value


def uninstall(progress: ProgressCallback | None = None) -> dict[str, Any]:
    emit_progress(progress, 10, "Preparing Uninstall", "Emulators/ReplaceModule")
    return result(
        False,
        "uninstall_failed",
        "ReplaceModule uninstall template requires an emulator-specific data policy.",
        "template_not_implemented",
    )
