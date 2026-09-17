from __future__ import annotations

from typing import Any

from _ReplaceModuleCommon import *


def result(success: bool, state: str, message: str, error: str | None = None, details: Any = None) -> dict[str, Any]:
    value = {
        "success": success,
        "module": "replace-with-module-id",
        "operation": "install",
        "state": state,
        "message": message,
        "details": details,
    }
    if error:
        value["error"] = error
    return value


def install(progress: ProgressCallback | None = None) -> dict[str, Any]:
    emit_progress(progress, 5, "Checking host")
    supported, reason = is_supported_host()
    if not supported:
        return result(False, "unsupported", reason or "ReplaceModule is not supported on this host.", "unsupported_host")
    emit_progress(progress, 10, "Preparing")
    return result(
        False,
        "install_failed",
        "ReplaceInstaller template requires emulator-specific installation logic.",
        "template_not_implemented",
    )
