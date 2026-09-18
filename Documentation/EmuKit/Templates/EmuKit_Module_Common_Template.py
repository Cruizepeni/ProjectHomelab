from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

MODULE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
INFO_PATH = MODULE_DIR / "EmuKitReplaceModuleInfo.json"
ROOT_MARKER = ".ProjectHomelabRoot"
ProgressCallback = Callable[[int | None, str | None, str | None], None]


def resolve_root() -> Path:
    current = MODULE_DIR.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ROOT_MARKER).is_file():
            return candidate
    for candidate in (current, *current.parents):
        if (candidate / "EmuKit.py").is_file() and (candidate / "EmuKitModules").is_dir():
            return candidate
    if MODULE_DIR.parent.name.casefold() == "emukitmodules":
        return MODULE_DIR.parent.parent
    return MODULE_DIR.parent


ROOT = resolve_root()
EMULATOR_DIR = ROOT / "Emulators" / "ReplaceModule"
EXECUTABLE_PATH = EMULATOR_DIR / "replace-executable.exe"
RECEIPT_PATH = EMULATOR_DIR / ".emukit_install.json"


def load_info() -> dict[str, Any]:
    return json.loads(INFO_PATH.read_text(encoding="utf-8"))


def module_version(info: dict[str, Any] | None = None) -> str:
    source = info if isinstance(info, dict) else load_info()
    return str(source["ModuleVersion"])


def emulator_version(info: dict[str, Any] | None = None) -> str:
    source = info if isinstance(info, dict) else load_info()
    return str(source["EmulatorVersion"])


def emit_progress(progress: ProgressCallback | None, percent: int | None, stage: str | None, message: str | None = None) -> None:
    if progress is not None:
        progress(percent, stage, message)


def scaled_progress(progress: ProgressCallback | None, start: int, end: int) -> ProgressCallback | None:
    if progress is None:
        return None

    def callback(percent: int | None = None, stage: str | None = None, message: str | None = None) -> None:
        if percent is None:
            mapped = None
        else:
            bounded = max(0, min(100, int(percent)))
            mapped = start + round((end - start) * bounded / 100)
        progress(mapped, stage, message)

    return callback


def is_supported_host() -> tuple[bool, str | None]:
    if platform.system().casefold() != "windows":
        return False, "ReplaceModule 1.0.0 currently supports Windows only."
    if platform.machine().casefold() not in {"amd64", "x86_64"}:
        return False, f'ReplaceModule 1.0.0 requires Windows x86_64. Current architecture: "{platform.machine()}".'
    return True, None


def run_external_process(args: list[str], isolate_console: bool = False, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
    restore_directory: str | None = None
    kernel32 = ctypes.windll.kernel32 if frozen_windows else None
    command = args

    if os.name == "nt" and isolate_console:
        comspec = os.environ.get("ComSpec") or str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe")
        command = [comspec, "/d", "/c", "start", "", "/wait", "/b", *args]
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo

    if kernel32 is not None:
        restore_directory = str(getattr(sys, "_MEIPASS", "")) or None
        kernel32.SetDllDirectoryW(None)

    try:
        return subprocess.run(command, **kwargs)
    finally:
        if kernel32 is not None:
            kernel32.SetDllDirectoryW(restore_directory)


def hash_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_receipt() -> dict[str, Any] | None:
    try:
        value = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def write_receipt(value: dict[str, Any]) -> None:
    RECEIPT_PATH.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
