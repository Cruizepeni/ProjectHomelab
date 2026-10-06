from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path


FEATURE_NAME = "StatMonitor"
APP_ROOT_MARKER = ".AppRoot"


def is_packaged_runtime() -> bool:
	return bool(getattr(sys, "frozen", False) or os.environ.get("APPIMAGE"))


def resolve_runtime_path() -> Path:
	appimage = os.environ.get("APPIMAGE")
	if appimage:
		return Path(appimage).expanduser().resolve()
	if getattr(sys, "frozen", False):
		return Path(sys.executable).resolve()
	return Path(__file__).resolve()


def resolve_feature_root() -> Path:
	if is_packaged_runtime():
		return resolve_runtime_path().parent
	return Path(__file__).resolve().parent


def find_app_root(feature_root: str | os.PathLike[str] | None = None) -> Path | None:
	feature = Path(feature_root).resolve() if feature_root else resolve_feature_root()
	start = feature.parent
	for candidate in (start, *start.parents):
		if (candidate / APP_ROOT_MARKER).is_file():
			return candidate
	return None


def resolve_app_root(feature_root: str | os.PathLike[str] | None = None) -> Path:
	feature = Path(feature_root).resolve() if feature_root else resolve_feature_root()
	return find_app_root(feature) or feature


def resolve_project_root(start: str | os.PathLike[str] | None = None) -> Path:
	return resolve_app_root(start)


def prepare_packaged_containment(arguments: list[str] | None = None) -> bool:
	if not is_packaged_runtime():
		return True
	runtime = resolve_runtime_path()
	if runtime.parent.name.casefold() == FEATURE_NAME.casefold():
		return True
	destination_directory = runtime.parent / FEATURE_NAME
	destination = destination_directory / runtime.name
	if destination.exists():
		raise RuntimeError(f"StatMonitor already exists at {destination}")
	destination_directory.mkdir(parents=True, exist_ok=True)
	shutil.copy2(runtime, destination)
	if os.name != "nt":
		destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
	command = [str(destination), "--containment-handoff", str(os.getpid()), str(runtime)]
	command.extend(list(arguments if arguments is not None else sys.argv[1:]))
	subprocess.Popen(command, cwd=str(destination_directory))
	return False


def finish_packaged_containment(parent_pid: int, source_path: str | os.PathLike[str]) -> None:
	if not is_packaged_runtime():
		return
	source = Path(source_path).resolve()
	destination = resolve_runtime_path()
	if source == destination or not source.exists():
		return
	if _sha256(source) != _sha256(destination):
		raise RuntimeError("StatMonitor containment verification failed")
	_wait_for_process_exit(int(parent_pid), 30.0)
	deadline = time.monotonic() + 30.0
	while source.exists() and time.monotonic() < deadline:
		try:
			source.unlink()
		except (PermissionError, OSError):
			time.sleep(0.2)
	if source.exists():
		raise RuntimeError(f"Unable to remove original StatMonitor runtime: {source}")


def _sha256(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as handle:
		for chunk in iter(lambda: handle.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def _wait_for_process_exit(pid: int, timeout: float) -> None:
	if pid <= 0:
		return
	if os.name == "nt":
		_SYNCHRONIZE = 0x00100000
		handle = ctypes.windll.kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
		if handle:
			try:
				ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
			finally:
				ctypes.windll.kernel32.CloseHandle(handle)
		return
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		try:
			os.kill(pid, 0)
		except ProcessLookupError:
			return
		except PermissionError:
			pass
		time.sleep(0.2)
