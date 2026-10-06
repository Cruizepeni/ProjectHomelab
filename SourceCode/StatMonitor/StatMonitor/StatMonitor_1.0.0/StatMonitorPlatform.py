from __future__ import annotations

import importlib
import platform
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlatformModules:
	name: str
	package: str
	CPU: Any
	GPU: Any
	RAM: Any
	StorageDrives: Any
	Network: Any
	WiFi: Any
	Bluetooth: Any
	Power: Any
	Motherboard: Any
	System: Any
	FanController: Any
	Privacy: Any | None
	StorageTools: Any | None
	Dependencies: Any | None


def _import(package: str, module: str, symbol: str):
	loaded = importlib.import_module(f"{package}.{module}")
	return getattr(loaded, symbol)


def _optional_import(package: str, module: str, symbol: str):
	try:
		loaded = importlib.import_module(f"{package}.{module}")
	except ModuleNotFoundError as error:
		if error.name == f"{package}.{module}":
			return None
		raise
	return getattr(loaded, symbol)


def load_platform_modules(system_name: str | None = None) -> PlatformModules:
	system = (system_name or platform.system()).strip()
	if system == "Windows":
		package = "Windows"
		name = "Windows"
	elif system == "Linux":
		package = "Linux"
		name = "Linux"
	elif system == "Darwin":
		package = "MacOS"
		name = "MacOS"
	else:
		raise RuntimeError(f"Unsupported operating system: {system or 'Unknown'}")
	return PlatformModules(
		name=name,
		package=package,
		CPU=_import(package, "StatMonitorCPU", "StatMonitorCPU"),
		GPU=_import(package, "StatMonitorGPU", "StatMonitorGPU"),
		RAM=_import(package, "StatMonitorRAM", "StatMonitorRAM"),
		StorageDrives=_import(package, "StatMonitorStorageDrives", "StatMonitorStorageDrives"),
		Network=_import(package, "StatMonitorNetwork", "StatMonitorNetwork"),
		WiFi=_import(package, "StatMonitorWiFi", "StatMonitorWiFi"),
		Bluetooth=_import(package, "StatMonitorBluetooth", "StatMonitorBluetooth"),
		Power=_import(package, "StatMonitorPower", "StatMonitorPower"),
		Motherboard=_import(package, "StatMonitorMotherboard", "StatMonitorMotherboard"),
		System=_import(package, "StatMonitorSystem", "StatMonitorSystem"),
		FanController=_import(package, "StatMonitorFanController", "StatMonitorFanController"),
		Privacy=_optional_import(package, "StatMonitorPrivacy", "StatMonitorPrivacy"),
		StorageTools=_optional_import(package, "StatMonitorStorageTools", "StatMonitorStorageTools"),
		Dependencies=_optional_import(package, "StatMonitorDependencies", "StatMonitorDependencies"),
	)
