from __future__ import annotations

from typing import Any

from _ReplaceModuleCommon import ProgressCallback, emit_progress, emulator_version, is_supported_host


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
        "operation": "install",
        "state": state,
        "message": message,
        "details": details,
    }
    if error:
        value["error"] = error
    return value


def install(progress: ProgressCallback | None = None) -> dict[str, Any]:
    emit_progress(progress, 5, "Checking Host", "Windows x86_64")
    supported, reason = is_supported_host()
    if not supported:
        return result(False, "unsupported", reason or "ReplaceModule is not supported on this host.", "unsupported_host")
    emit_progress(progress, 10, "Preparing Install", "Emulators/ReplaceModule")
    return result(
        False,
        "install_failed",
        "ReplaceModule installer template requires emulator-specific installation logic.",
        "template_not_implemented",
    )
