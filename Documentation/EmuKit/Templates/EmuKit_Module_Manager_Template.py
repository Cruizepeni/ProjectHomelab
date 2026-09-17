from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MODULE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from _ReplaceModuleCommon import *
import ReplaceInstaller
import ReplaceRepair
import ReplaceUninstall

MODULE_ID = "replace-with-module-id"
MODULE_NAME = "Replace With Emulator Name"


def base(success: bool, operation: str, state: str, message: str, error: str | None = None, details: Any = None) -> dict[str, Any]:
    value = {
        "success": success,
        "module": MODULE_ID,
        "operation": operation,
        "state": state,
        "message": message,
        "details": details,
    }
    if error:
        value["error"] = error
    return value


def check(progress: ProgressCallback | None = None) -> dict[str, Any]:
    emit_progress(progress, 10, "Checking host")
    supported, reason = is_supported_host()
    if not supported:
        return base(False, "check", "unsupported", reason or f"{MODULE_NAME} is not supported on this host.", "unsupported_host")
    if not EMULATOR_DIR.exists():
        return base(True, "check", "missing", f"{MODULE_NAME} is not installed.", details={"expected_path": str(EMULATOR_DIR)})
    emit_progress(progress, 50, "Checking executable")
    if not EXECUTABLE_PATH.is_file():
        return base(True, "check", "broken", f"{MODULE_NAME} is missing its managed executable.", details={"expected_executable": str(EXECUTABLE_PATH)})
    emit_progress(progress, 95, "Ready")
    return base(
        True,
        "check",
        "installed",
        f'{MODULE_NAME} "{emulator_version()}" is installed and valid.',
        details={
            "module_version": module_version(),
            "version": emulator_version(),
            "path": str(EXECUTABLE_PATH),
        },
    )


def install(progress: ProgressCallback | None = None) -> dict[str, Any]:
    return ReplaceInstaller.install(progress=progress)


def uninstall(progress: ProgressCallback | None = None) -> dict[str, Any]:
    return ReplaceUninstall.uninstall(progress=progress)


def repair(progress: ProgressCallback | None = None) -> dict[str, Any]:
    return ReplaceRepair.repair(progress=progress)


def update(progress: ProgressCallback | None = None) -> dict[str, Any]:
    current = check(progress=scaled_progress(progress, 0, 20))
    if not current.get("success") and current.get("state") == "unsupported":
        current["operation"] = "update"
        return current
    if current.get("state") == "installed":
        return base(
            True,
            "update",
            "already_current",
            f'{MODULE_NAME} "{emulator_version()}" is already the module-pinned version.',
            details=current.get("details"),
        )
    repaired = ReplaceRepair.repair(progress=scaled_progress(progress, 20, 98))
    repaired["operation"] = "update"
    repaired["state"] = "updated" if repaired.get("success") else "update_failed"
    if repaired.get("success"):
        repaired["message"] = f'{MODULE_NAME} was updated to pinned version "{emulator_version()}".'
    return repaired


def _write_record(record: dict[str, Any]) -> None:
    print(json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":")), flush=True)


def _stream_progress(percent: int | None = None, stage: str | None = None, message: str | None = None) -> None:
    _write_record({"type": "progress", "percent": percent, "stage": stage, "message": message})


def _run_cli() -> int:
    raw_args = sys.argv[1:]
    json_flags = [arg for arg in raw_args if arg.casefold() == "--json"]
    args = [arg for arg in raw_args if arg.casefold() != "--json"]
    operation = args[0].casefold() if len(args) == 1 else ""
    handlers = {
        "check": check,
        "install": install,
        "uninstall": uninstall,
        "repair": repair,
        "update": update,
    }
    handler = handlers.get(operation)
    if len(json_flags) != 1 or handler is None:
        result = base(
            False,
            operation or "manager",
            "invalid_operation",
            f"{MODULE_NAME}Manager requires one lifecycle operation: check, install, uninstall, repair, or update.",
            "invalid_operation",
        )
    else:
        try:
            result = handler(progress=_stream_progress)
        except Exception as exc:
            result = base(
                False,
                operation,
                f"{operation}_failed",
                f"{MODULE_NAME}Manager failed during {operation}.",
                "manager_exception",
                str(exc),
            )
    _write_record({"type": "result", "result": result})
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(_run_cli())
