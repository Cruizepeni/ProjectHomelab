from __future__ import annotations

import filecmp
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


FEATURE_NAME = "TerminalSS"
ROOT_MARKER = ".AppRoot"
RELOCATION_SOURCE_ARGUMENT = "--approot-relocated-from"
RELOCATION_PID_ARGUMENT = "--approot-relocator-pid"


@dataclass(frozen=True)
class TerminalSSRuntimeContext:
    runtime_path: Path
    runtime_directory: Path
    app_root: Path
    integrated: bool
    packaged: bool


def runtime_application_path(source_entry: str | Path) -> Path:
    if platform.system() == "Linux":
        appimage_value = str(os.environ.get("APPIMAGE") or "").strip()
        if appimage_value:
            appimage_path = Path(appimage_value).expanduser().resolve()
            if appimage_path.is_file():
                return appimage_path
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(source_entry).resolve()


def is_packaged_runtime(runtime_path: Path, source_entry: str | Path) -> bool:
    if getattr(sys, "frozen", False):
        return True
    if platform.system() == "Linux" and str(os.environ.get("APPIMAGE") or "").strip():
        return runtime_path != Path(source_entry).resolve()
    return False


def expected_runtime_name(runtime_path: Path) -> str:
    system = platform.system()
    if system == "Windows":
        return f"{FEATURE_NAME}.exe"
    if system == "Linux":
        return f"{FEATURE_NAME}.AppImage"
    return runtime_path.name


def pid_running(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return completed.returncode == 0 and str(pid) in completed.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def strip_relocation_arguments(arguments: list[str]) -> list[str]:
    cleaned: list[str] = []
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value in {RELOCATION_SOURCE_ARGUMENT, RELOCATION_PID_ARGUMENT}:
            index += 2
            continue
        cleaned.append(value)
        index += 1
    return cleaned


def launch_relocated_runtime(runtime_path: Path, raw_arguments: list[str]) -> Path:
    destination_directory = runtime_path.parent / FEATURE_NAME
    destination_path = destination_directory / expected_runtime_name(runtime_path)
    destination_directory.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        raise RuntimeError(
            f"TerminalSS found an existing runtime at {destination_path}. "
            "The loose runtime was not allowed to overwrite it."
        )
    shutil.copy2(runtime_path, destination_path)
    if os.name != "nt":
        destination_path.chmod(runtime_path.stat().st_mode)
    forwarded = strip_relocation_arguments(raw_arguments)
    command = [
        str(destination_path),
        *forwarded,
        RELOCATION_SOURCE_ARGUMENT,
        str(runtime_path),
        RELOCATION_PID_ARGUMENT,
        str(os.getpid()),
    ]
    subprocess.Popen(command, cwd=str(destination_directory))
    return destination_path


def complete_relocation(runtime_path: Path, source_value: str | None, pid_value: int | None) -> None:
    if not source_value or not isinstance(pid_value, int) or pid_value <= 0:
        return
    source_path = Path(source_value).expanduser().resolve()
    runtime_directory = runtime_path.parent.resolve()
    expected_parent = runtime_directory.parent
    if runtime_directory.name.casefold() != FEATURE_NAME.casefold():
        raise RuntimeError("TerminalSS relocation cleanup was requested from an invalid runtime folder.")
    if source_path.parent != expected_parent or source_path == runtime_path:
        raise RuntimeError("TerminalSS relocation cleanup rejected an invalid source path.")
    if not source_path.is_file() or not runtime_path.is_file():
        raise RuntimeError("TerminalSS relocation cleanup could not validate the runtime files.")
    if not filecmp.cmp(source_path, runtime_path, shallow=False):
        raise RuntimeError("TerminalSS relocation cleanup rejected a source file that does not match the relocated runtime.")
    deadline = time.monotonic() + 20.0
    while pid_running(pid_value) and time.monotonic() < deadline:
        time.sleep(0.1)
    if pid_running(pid_value):
        raise RuntimeError("TerminalSS could not complete relocation because the original process is still running.")
    if source_path.exists():
        source_path.unlink()


def resolve_app_root(runtime_directory: Path) -> tuple[Path, bool]:
    runtime_directory = runtime_directory.resolve()
    for candidate in runtime_directory.parents:
        if (candidate / ROOT_MARKER).is_file():
            return candidate, True
    return runtime_directory, False


def prepare_runtime(
    source_entry: str | Path,
    raw_arguments: list[str],
    relocation_source: str | None = None,
    relocation_pid: int | None = None,
) -> TerminalSSRuntimeContext | None:
    runtime_path = runtime_application_path(source_entry)
    packaged = is_packaged_runtime(runtime_path, source_entry)
    system = platform.system()
    if packaged and system in {"Windows", "Linux"}:
        if runtime_path.parent.name.casefold() != FEATURE_NAME.casefold():
            launch_relocated_runtime(runtime_path, raw_arguments)
            return None
        complete_relocation(runtime_path, relocation_source, relocation_pid)
    runtime_directory = runtime_path.parent.resolve() if packaged else Path(source_entry).resolve().parent
    app_root, integrated = resolve_app_root(runtime_directory)
    return TerminalSSRuntimeContext(
        runtime_path=runtime_path,
        runtime_directory=runtime_directory,
        app_root=app_root,
        integrated=integrated,
        packaged=packaged,
    )
