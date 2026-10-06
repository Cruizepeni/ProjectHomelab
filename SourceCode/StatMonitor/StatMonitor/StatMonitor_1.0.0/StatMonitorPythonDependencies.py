from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import subprocess
import sys
from pathlib import Path


COMMON_DEPENDENCIES = (
	("psutil", "psutil"),
	("websockets", "websockets"),
)

WINDOWS_DEPENDENCIES = (
	("pythonnet", "pythonnet"),
	("winrt-runtime", "winrt.system"),
	("winrt-Windows.Devices.Bluetooth", "winrt.windows.devices.bluetooth"),
	("winrt-Windows.Devices.Bluetooth.Advertisement", "winrt.windows.devices.bluetooth.advertisement"),
	("winrt-Windows.Devices.Enumeration", "winrt.windows.devices.enumeration"),
	("winrt-Windows.Devices.Radios", "winrt.windows.devices.radios"),
)


def _platform_key() -> str:
	system = platform.system() or "Unknown"
	machine = (platform.machine() or "unknown").casefold()
	if machine in {"amd64", "x86_64", "x64"}:
		architecture = "x86_64"
	elif machine in {"arm64", "aarch64"}:
		architecture = "arm64"
	elif machine in {"x86", "i386", "i686"}:
		architecture = "x86"
	else:
		architecture = machine.replace(" ", "_")
	return f"{system}_{architecture}"


def _dependency_directory() -> Path:
	root = Path(__file__).resolve().parent
	current = root
	while True:
		if (current / ".AppRoot").exists():
			root = current
			break
		if current.parent == current:
			break
		current = current.parent
	python_version = f"Python_{sys.version_info.major}.{sys.version_info.minor}"
	return root / "Dependencies" / "StatMonitor" / "Python" / _platform_key() / python_version


def _available(import_name: str) -> bool:
	try:
		return importlib.util.find_spec(import_name) is not None
	except (ImportError, ModuleNotFoundError, ValueError):
		return False


def _run(command: list[str], *, quiet: bool) -> subprocess.CompletedProcess:
	kwargs = {"check": False}
	if quiet:
		kwargs["stdout"] = subprocess.DEVNULL
		kwargs["stderr"] = subprocess.DEVNULL
	if os.name == "nt" and quiet:
		kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
	return subprocess.run(command, **kwargs)


def ensure_python_dependencies(*, quiet: bool = False) -> None:
	if getattr(sys, "frozen", False):
		return
	managed = _dependency_directory()
	if managed.is_dir():
		path = str(managed)
		if path not in sys.path:
			sys.path.insert(0, path)
	dependencies = list(COMMON_DEPENDENCIES)
	if platform.system() == "Windows":
		dependencies.extend(WINDOWS_DEPENDENCIES)
	missing = [(package, import_name) for package, import_name in dependencies if not _available(import_name)]
	if not missing:
		return
	managed.mkdir(parents=True, exist_ok=True)
	packages = [package for package, _ in missing]
	if not quiet:
		print("StatMonitor Python dependencies are missing: " + ", ".join(packages))
		print(f"Installing missing Python dependencies into {managed}...")
	pip_check = _run([sys.executable, "-m", "pip", "--version"], quiet=True)
	if pip_check.returncode != 0:
		ensure = _run([sys.executable, "-m", "ensurepip", "--upgrade"], quiet=quiet)
		if ensure.returncode != 0:
			raise RuntimeError("StatMonitor could not prepare pip for automatic Python dependency installation")
	command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--target", str(managed), *packages]
	result = _run(command, quiet=quiet)
	if result.returncode != 0:
		raise RuntimeError("StatMonitor could not automatically install required Python dependencies")
	importlib.invalidate_caches()
	path = str(managed)
	if path not in sys.path:
		sys.path.insert(0, path)
	failed = [package for package, import_name in missing if not _available(import_name)]
	if failed:
		raise RuntimeError("StatMonitor installed Python dependencies but could not import: " + ", ".join(failed))
	if not quiet:
		print("StatMonitor Python dependencies are ready.")
