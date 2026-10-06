from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def root_path(path: str | os.PathLike[str]) -> Path:
	value = Path(path)
	test_root = os.environ.get("STATMONITOR_LINUX_TEST_ROOT")
	if not test_root or not value.is_absolute():
		return value
	test_base = Path(test_root)
	try:
		value.relative_to(test_base)
		return value
	except ValueError:
		return test_base / str(value).lstrip("/")


def read_text(path: str | os.PathLike[str]) -> str | None:
	try:
		value = root_path(path).read_text(encoding="utf-8", errors="ignore").strip()
		return value or None
	except Exception:
		return None


def read_number(path: str | os.PathLike[str], divisor: float = 1.0) -> float | None:
	value = read_text(path)
	if value is None:
		return None
	try:
		return float(value) / divisor
	except Exception:
		return None


def executable(name: str) -> str | None:
	return shutil.which(name)


def run(args: list[str], timeout: float = 10.0, input_text: str | None = None) -> subprocess.CompletedProcess:
	return subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout, check=False)


def hwmon_devices() -> list[dict[str, Any]]:
	base = root_path("/sys/class/hwmon")
	result = []
	if not base.exists():
		return result
	for hwmon in sorted(base.glob("hwmon*")):
		name = read_text(hwmon / "name") or hwmon.name
		try:
			real = hwmon.resolve()
		except Exception:
			real = hwmon
		device = hwmon / "device"
		try:
			device_real = device.resolve() if device.exists() else real
		except Exception:
			device_real = real
		result.append({"path": hwmon, "name": name, "realpath": str(real), "device_realpath": str(device_real)})
	return result


def hwmon_temperatures() -> list[dict[str, Any]]:
	items = []
	for device in hwmon_devices():
		path = device["path"]
		for input_file in sorted(path.glob("temp*_input")):
			stem = input_file.name[:-6]
			value = read_number(input_file, 1000.0)
			if value is None or value < -20 or value > 150:
				continue
			label = read_text(path / f"{stem}_label") or f"{device['name']} {stem}"
			items.append({"chip": device["name"], "name": label, "temperature_c": round(value, 1), "source_path": str(input_file), "device_path": device["device_realpath"]})
	return items


def hwmon_fans() -> list[dict[str, Any]]:
	items = []
	for device in hwmon_devices():
		path = device["path"]
		for input_file in sorted(path.glob("fan*_input")):
			stem = input_file.name[:-6]
			value = read_number(input_file)
			if value is None:
				continue
			label = read_text(path / f"{stem}_label") or f"{device['name']} {stem}"
			items.append({"chip": device["name"], "name": label, "rpm": round(value, 1), "source_path": str(input_file), "device_path": device["device_realpath"]})
	return items


def command_available(name: str) -> bool:
	return executable(name) is not None
