from __future__ import annotations

from typing import Any

from _ReplaceModuleCommon import *


def result(success: bool, state: str, message: str, error: str | None = None, details: Any = None) -> dict[str, Any]:
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
    emit_progress(progress, 10, "Preparing uninstall")
    return result(
        False,
        "uninstall_failed",
        "ReplaceUninstall template requires an explicit emulator-specific data policy.",
        "template_not_implemented",
    )
