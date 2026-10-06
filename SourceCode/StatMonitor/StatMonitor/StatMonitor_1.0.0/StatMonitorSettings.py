from __future__ import annotations

import copy
import json
import logging
import math
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from StatMonitorPaths import resolve_app_root


LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1
MODULE_NAMES = ("CPU", "GPU", "RAM", "Drives", "Network", "WiFi", "Bluetooth", "Power", "Motherboard", "System")
DEFAULT_TOKEN = "Default"


def _default_maps() -> dict[str, dict[str, Any]]:
	return {
		"Silent": {
			"BuiltIn": True,
			"HysteresisC": 4.0,
			"Points": [
				{"TemperatureC": 30.0, "SpeedPercent": 30.0},
				{"TemperatureC": 50.0, "SpeedPercent": 30.0},
				{"TemperatureC": 60.0, "SpeedPercent": 40.0},
				{"TemperatureC": 70.0, "SpeedPercent": 60.0},
				{"TemperatureC": 80.0, "SpeedPercent": 80.0},
				{"TemperatureC": 88.0, "SpeedPercent": 100.0},
			],
		},
		"Balanced": {
			"BuiltIn": True,
			"HysteresisC": 3.0,
			"Points": [
				{"TemperatureC": 30.0, "SpeedPercent": 50.0},
				{"TemperatureC": 45.0, "SpeedPercent": 55.0},
				{"TemperatureC": 55.0, "SpeedPercent": 65.0},
				{"TemperatureC": 65.0, "SpeedPercent": 80.0},
				{"TemperatureC": 75.0, "SpeedPercent": 90.0},
				{"TemperatureC": 85.0, "SpeedPercent": 100.0},
			],
		},
		"Cool": {
			"BuiltIn": True,
			"HysteresisC": 3.0,
			"Points": [
				{"TemperatureC": 30.0, "SpeedPercent": 60.0},
				{"TemperatureC": 40.0, "SpeedPercent": 70.0},
				{"TemperatureC": 50.0, "SpeedPercent": 80.0},
				{"TemperatureC": 60.0, "SpeedPercent": 90.0},
				{"TemperatureC": 75.0, "SpeedPercent": 100.0},
			],
		},
		"Aggressive": {
			"BuiltIn": True,
			"HysteresisC": 2.0,
			"Points": [
				{"TemperatureC": 30.0, "SpeedPercent": 75.0},
				{"TemperatureC": 40.0, "SpeedPercent": 85.0},
				{"TemperatureC": 50.0, "SpeedPercent": 95.0},
				{"TemperatureC": 60.0, "SpeedPercent": 100.0},
			],
		},
		"Full Speed": {
			"BuiltIn": True,
			"HysteresisC": 1.0,
			"Points": [
				{"TemperatureC": 20.0, "SpeedPercent": 100.0},
				{"TemperatureC": 90.0, "SpeedPercent": 100.0},
			],
		},
	}


def _default_profiles() -> dict[str, dict[str, Any]]:
	return {
		"CPU": {"BuiltIn": True, "DefaultMap": "Balanced", "TemperatureSource": "CPU", "ProviderControlled": False},
		"GPU": {"BuiltIn": True, "DefaultMap": None, "TemperatureSource": "GPU", "ProviderControlled": True},
		"Case": {"BuiltIn": True, "DefaultMap": "Balanced", "TemperatureSource": "CaseHottest", "ProviderControlled": False},
		"AIO Pump": {"BuiltIn": True, "DefaultMap": "Full Speed", "TemperatureSource": "CPU", "ProviderControlled": False},
		"Auxiliary": {"BuiltIn": True, "DefaultMap": "Balanced", "TemperatureSource": "CaseHottest", "ProviderControlled": False},
	}


def default_fan_control() -> dict[str, Any]:
	return {
		"Enabled": False,
		"Profiles": _default_profiles(),
		"Maps": _default_maps(),
		"Fans": {},
	}


def _default_settings() -> dict[str, dict[str, Any]]:
	return {
		"Modules": {name: True for name in MODULE_NAMES},
		"CPU": {
			"Show CPU Name": True,
			"Show Core And Thread Count": True,
			"Show Clock Speed": True,
			"Show Current Usage": True,
			"Show Temperature": True,
			"Show Power Usage": True,
			"Show Individual Cores": True,
		},
		"GPU": {
			"Show Integrated Graphics": True,
			"Show Dedicated Graphics": True,
			"Show GPU Name": True,
			"Show Current Usage": True,
			"Show VRAM Usage": True,
			"Show Temperature": True,
			"Show Clock Speed": True,
			"Show Power Usage": True,
			"Show Fan Speed": True,
			"Show Driver Version": True,
		},
		"RAM": {
			"Show Individual RAM Units": True,
			"Show RAM Name": True,
			"Show RAM Type": True,
			"Show RAM Size": True,
			"Show RAM Speed": True,
			"Show Current RAM Usage": True,
			"Show Available RAM": True,
		},
		"Drives": {
			"Show Internal Drives": True,
			"Show External USB Drives": True,
			"Show Network Drives": True,
			"Show Removable Drives": True,
			"Show Custom User Drive Name": True,
			"Show Drive Model": True,
			"Show Drive Letter": True,
			"Show Drive Type": True,
			"Show Drive Size": True,
			"Show Free Space": True,
			"Show Drive Temperature": True,
			"Show Drive Health": True,
			"Show Drive Wear": True,
			"Show Current Drive Usage": True,
			"Show Read Write Speed": True,
			"Open Drive In File Manager": True,
		},
		"Network": {
			"Show Individual Network Adapters": True,
			"Show Disconnected Network Adapters": True,
			"Show Virtual Network Adapters": True,
			"Show Adapter Name": True,
			"Show Connection Type": True,
			"Show Network Name": True,
			"Show IP Address": True,
			"Show Link Speed": True,
			"Show Current Download Speed": True,
			"Show Current Upload Speed": True,
			"Show Total Downloaded": True,
			"Show Total Uploaded": True,
			"Show WiFi Signal Strength": True,
		},
		"WiFi": {
			"Show WiFi Adapter": True,
			"Show Current Network": True,
			"Show Available Networks": True,
			"Show Saved Networks": True,
			"Show Signal Strength": True,
			"Show Link Speed": True,
		},
		"Bluetooth": {
			"Show Bluetooth Adapter": True,
			"Show Connected Devices": True,
			"Show Paired Devices": True,
			"Show Device Type": True,
			"Show Device Transport": True,
			"Show Device Battery Level": True,
			"Show Signal Strength": True,
		},
		"Power": {
			"Show Power Source": True,
			"Show Battery": True,
			"Show Battery Percentage": True,
			"Show Charging State": True,
			"Show Time Remaining": True,
			"Show Battery Health": True,
			"Show Battery Capacity": True,
			"Show Battery Cycle Count": True,
			"Show CPU Power Usage": True,
			"Show GPU Power Usage": True,
		},
		"Motherboard": {
			"Show Motherboard Name": True,
			"Show Manufacturer": True,
			"Show Chipset": True,
			"Show BIOS Version": True,
			"Show Temperature": True,
			"Show Fan Speeds": True,
			"Show Voltages": True,
			"Show Vendor Workaround Warnings": True,
		},
		"System": {
			"Show Device Name": True,
			"Show Operating System": True,
			"Show OS Version": True,
			"Show Architecture": True,
			"Show System Uptime": True,
			"Show Last Boot Time": True,
		},
	}


SETTING_ALIASES = {
	("Drives", "Click To Show Drive In Explorer"): "Open Drive In File Manager",
	("Motherboard", "Show Armoury Crate Warning"): "Show Vendor Workaround Warnings",
}


def _is_setting_value(value: Any) -> bool:
	return isinstance(value, bool) or value == DEFAULT_TOKEN


def _resolve_value(value: Any, default: bool) -> bool:
	if value == DEFAULT_TOKEN:
		return bool(default)
	return bool(value) if isinstance(value, bool) else bool(default)


def _finite_number(value: Any) -> float | None:
	if isinstance(value, bool):
		return None
	try:
		result = float(value)
	except (TypeError, ValueError):
		return None
	return result if math.isfinite(result) else None


def _valid_map_value(name: str, value: Any, built_in: bool) -> dict[str, Any] | None:
	if not isinstance(value, dict):
		return None
	hysteresis = _finite_number(value.get("HysteresisC"))
	points = value.get("Points")
	if hysteresis is None or not 1.0 <= hysteresis <= 8.0 or not isinstance(points, list) or len(points) < 2:
		return None
	clean_points = []
	for point in points:
		if not isinstance(point, dict):
			return None
		temperature = _finite_number(point.get("TemperatureC"))
		speed = _finite_number(point.get("SpeedPercent"))
		if temperature is None or speed is None or not 20.0 <= temperature <= 100.0 or not 30.0 <= speed <= 100.0:
			return None
		if clean_points and temperature <= clean_points[-1]["TemperatureC"]:
			return None
		if clean_points and speed < clean_points[-1]["SpeedPercent"]:
			return None
		clean_points.append({"TemperatureC": temperature, "SpeedPercent": speed})
	if clean_points[-1]["TemperatureC"] > 90.0 or clean_points[-1]["SpeedPercent"] != 100.0:
		return None
	return {"BuiltIn": bool(built_in), "HysteresisC": hysteresis, "Points": clean_points}



def _normalize_temperature_source(value: Any) -> str | None:
	text = str(value or "").strip()
	if not text:
		return None
	if text == "SystemMax":
		return "CaseHottest"
	if text in {"CPU", "GPU", "Motherboard", "CaseHottest"}:
		return text
	if text.startswith(("CPUCore::", "GPUDevice::", "MotherboardSensor::")):
		return text
	return None

def _valid_profile_value(name: str, value: Any, built_in: bool, maps: dict[str, Any]) -> dict[str, Any] | None:
	if not isinstance(value, dict):
		return None
	default_map = value.get("DefaultMap")
	if default_map is not None:
		default_map = str(default_map).strip()
		if not default_map or default_map not in maps:
			return None
	source = _normalize_temperature_source(value.get("TemperatureSource") or "CaseHottest")
	if source is None:
		return None
	provider_controlled = value.get("ProviderControlled", False)
	if not isinstance(provider_controlled, bool):
		provider_controlled = False
	return {"BuiltIn": bool(built_in), "DefaultMap": default_map, "TemperatureSource": source, "ProviderControlled": provider_controlled}


def _merge_fan_control(loaded: Any) -> tuple[dict[str, Any], bool]:
	defaults = default_fan_control()
	changed = not isinstance(loaded, dict)
	loaded = copy.deepcopy(loaded) if isinstance(loaded, dict) else {}
	result = {"Enabled": loaded.get("Enabled") if isinstance(loaded.get("Enabled"), bool) else defaults["Enabled"], "Profiles": {}, "Maps": {}, "Fans": {}}
	if result["Enabled"] != loaded.get("Enabled"):
		changed = True
	loaded_maps = loaded.get("Maps") if isinstance(loaded.get("Maps"), dict) else {}
	for name, default in defaults["Maps"].items():
		candidate = _valid_map_value(name, loaded_maps.get(name), True)
		if candidate is None:
			candidate = copy.deepcopy(default)
			changed = True
		result["Maps"][name] = candidate
	for name, value in loaded_maps.items():
		if name in result["Maps"]:
			continue
		clean_name = str(name).strip()
		candidate = _valid_map_value(clean_name, value, False)
		if clean_name and candidate is not None:
			result["Maps"][clean_name] = candidate
		else:
			changed = True
	loaded_profiles = loaded.get("Profiles") if isinstance(loaded.get("Profiles"), dict) else {}
	for name, default in defaults["Profiles"].items():
		candidate = _valid_profile_value(name, loaded_profiles.get(name), True, result["Maps"])
		if candidate is None:
			candidate = copy.deepcopy(default)
			changed = True
		result["Profiles"][name] = candidate
	for name, value in loaded_profiles.items():
		if name in result["Profiles"]:
			continue
		clean_name = str(name).strip()
		candidate = _valid_profile_value(clean_name, value, False, result["Maps"])
		if clean_name and candidate is not None:
			result["Profiles"][clean_name] = candidate
		else:
			changed = True
	loaded_fans = loaded.get("Fans") if isinstance(loaded.get("Fans"), dict) else {}
	for identifier, value in loaded_fans.items():
		if not isinstance(value, dict):
			changed = True
			continue
		key = str(identifier).strip()
		profile = str(value.get("Profile") or "Auxiliary").strip()
		if not key or profile not in result["Profiles"]:
			changed = True
			continue
		map_name = value.get("Map")
		if map_name is not None:
			map_name = str(map_name).strip()
			if map_name not in result["Maps"]:
				map_name = None
				changed = True
		friendly_name = str(value.get("FriendlyName") or "").strip()
		reported_name = str(value.get("ReportedName") or "").strip()
		sources = value.get("TemperatureSources")
		if isinstance(sources, str):
			sources = [sources]
		if not isinstance(sources, list):
			sources = []
		clean_sources = []
		for source in sources:
			text = _normalize_temperature_source(source)
			if text is not None and text not in clean_sources:
				clean_sources.append(text)
		result["Fans"][key] = {
			"FriendlyName": friendly_name,
			"ReportedName": reported_name,
			"Profile": profile,
			"Map": map_name,
			"TemperatureSources": clean_sources,
		}
	return result, changed or result != loaded



def _first_difference(current: Any, expected: Any, path: str = "") -> str | None:
	if isinstance(current, dict) and isinstance(expected, dict):
		for key in expected:
			child = f"{path}.{key}" if path else str(key)
			if key not in current:
				return child
			difference = _first_difference(current[key], expected[key], child)
			if difference is not None:
				return difference
		for key in current:
			if key not in expected:
				return f"{path}.{key}" if path else str(key)
		return None
	if isinstance(current, list) and isinstance(expected, list):
		if len(current) != len(expected):
			return path or "root"
		for index, (left, right) in enumerate(zip(current, expected)):
			child = f"{path}[{index}]" if path else f"[{index}]"
			difference = _first_difference(left, right, child)
			if difference is not None:
				return difference
		return None
	return None if current == expected else (path or "root")

def _merge_and_validate(defaults: dict[str, dict[str, Any]], loaded: Any) -> tuple[dict, bool]:
	changed = not isinstance(loaded, dict)
	loaded = copy.deepcopy(loaded) if isinstance(loaded, dict) else {}
	for (section, old_key), new_key in SETTING_ALIASES.items():
		section_data = loaded.get(section)
		if isinstance(section_data, dict) and old_key in section_data and new_key not in section_data:
			section_data[new_key] = section_data[old_key]
			changed = True
	result: dict[str, Any] = {"schemaVersion": SCHEMA_VERSION}
	if loaded.get("schemaVersion") != SCHEMA_VERSION:
		changed = True
	ai_enabled = loaded.get("aiEnabled", False)
	if not isinstance(ai_enabled, bool):
		ai_enabled = False
		changed = True
	result["aiEnabled"] = ai_enabled
	for section, values in defaults.items():
		result[section] = {}
		loaded_section = loaded.get(section)
		if not isinstance(loaded_section, dict):
			loaded_section = {}
			changed = True
		for key, default in values.items():
			if key not in loaded_section:
				result[section][key] = default
				changed = True
				continue
			value = loaded_section.get(key)
			if not _is_setting_value(value):
				value = default
				changed = True
			result[section][key] = value
	fan_control, fan_changed = _merge_fan_control(loaded.get("FanControl"))
	result["FanControl"] = fan_control
	return result, changed or fan_changed


class StatMonitorSettings:
	def __init__(self, project_root: str | os.PathLike[str] | None = None):
		self.root = Path(project_root).resolve() if project_root else resolve_app_root()
		self.path = self.root / "Appdata" / "Settings" / "StatMonitorSettingsConfig.json"
		self._legacy_paths = (
			self.root / "appdata" / "settings" / "StatMonitorSettingsConfig.json",
			self.root / "Appdata" / "settings" / "StatMonitorSettingsConfig.json",
		)
		self._lock = threading.RLock()
		self._listeners: list[Callable[[str, dict[str, Any]], None]] = []
		self._settings: dict[str, Any] = {}
		self.load()

	def load(self) -> dict:
		with self._lock:
			loaded = self._load_file()
			self._settings, changed = _merge_and_validate(_default_settings(), loaded)
			if changed or not self.path.exists():
				self._save_locked()
			return copy.deepcopy(self._settings)

	def _load_file(self) -> dict:
		paths = (self.path, *self._legacy_paths)
		for path in paths:
			try:
				with path.open("r", encoding="utf-8") as file:
					loaded = json.load(file)
				if isinstance(loaded, dict):
					return loaded
			except (OSError, json.JSONDecodeError):
				continue
		return {}

	def subscribe(self, listener: Callable[[str, dict[str, Any]], None]) -> None:
		with self._lock:
			if listener not in self._listeners:
				self._listeners.append(listener)

	def unsubscribe(self, listener: Callable) -> None:
		with self._lock:
			if listener in self._listeners:
				self._listeners.remove(listener)

	def get_all(self, resolved: bool = False) -> dict:
		with self._lock:
			if not resolved:
				return copy.deepcopy(self._settings)
			result = {"schemaVersion": SCHEMA_VERSION, "aiEnabled": self._settings.get("aiEnabled") is True}
			for section in _default_settings():
				result[section] = self._resolved_section_locked(section)
			result["FanControl"] = copy.deepcopy(self._settings.get("FanControl", default_fan_control()))
			return result


	def validate_all(self, value: dict[str, Any]) -> dict[str, Any]:
		if not isinstance(value, dict):
			raise ValueError("Settings JSON must contain one object at the root")
		validated, changed = _merge_and_validate(_default_settings(), value)
		if changed or validated != value:
			difference = _first_difference(value, validated) or "root"
			raise ValueError(f"Invalid, missing, or unsupported setting at {difference}")
		return copy.deepcopy(validated)

	def replace_all(self, value: dict[str, Any]) -> bool:
		validated = self.validate_all(value)
		with self._lock:
			if validated == self._settings:
				return False
			previous = copy.deepcopy(self._settings)
			self._settings = copy.deepcopy(validated)
			self._save_locked()
			listeners = list(self._listeners)
		changed_sections = [key for key in validated if previous.get(key) != validated.get(key)]
		for section in changed_sections:
			if section == "schemaVersion":
				continue
			payload = copy.deepcopy(validated.get(section))
			if not isinstance(payload, dict):
				payload = {"value": payload}
			for listener in listeners:
				try:
					listener(section, copy.deepcopy(payload))
				except Exception:
					LOGGER.exception("StatMonitor settings listener failed")
		return True

	def reset_defaults(self) -> dict[str, Any]:
		defaults, _ = _merge_and_validate(_default_settings(), {})
		with self._lock:
			previous = copy.deepcopy(self._settings)
			self._settings = defaults
			self._save_locked()
			listeners = list(self._listeners)
		for section in defaults:
			if section == "schemaVersion" or previous.get(section) == defaults.get(section):
				continue
			payload = copy.deepcopy(defaults.get(section))
			if not isinstance(payload, dict):
				payload = {"value": payload}
			for listener in listeners:
				try:
					listener(section, copy.deepcopy(payload))
				except Exception:
					LOGGER.exception("StatMonitor settings listener failed")
		return copy.deepcopy(defaults)

	def get_module_settings(self, module_name: str, resolved: bool = False) -> dict:
		with self._lock:
			if module_name not in _default_settings():
				return {}
			if resolved:
				return self._resolved_section_locked(module_name)
			return copy.deepcopy(self._settings.get(module_name, {}))

	def get_fan_control(self) -> dict[str, Any]:
		with self._lock:
			return copy.deepcopy(self._settings.get("FanControl", default_fan_control()))

	def replace_fan_control(self, value: dict[str, Any]) -> bool:
		validated, _ = _merge_fan_control(value)
		with self._lock:
			if validated == self._settings.get("FanControl"):
				return False
			self._settings["FanControl"] = validated
			self._save_locked()
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener("FanControl", copy.deepcopy(validated))
			except Exception:
				LOGGER.exception("StatMonitor settings listener failed")
		return True

	def _resolved_section_locked(self, section: str) -> dict[str, bool]:
		defaults = _default_settings()[section]
		stored = self._settings.get(section, {})
		return {key: _resolve_value(stored.get(key, DEFAULT_TOKEN), default) for key, default in defaults.items()}

	@staticmethod
	def resolve(value: Any, application_default: bool = False) -> bool:
		return _resolve_value(value, application_default)

	def is_module_enabled(self, module_name: str) -> bool:
		with self._lock:
			defaults = _default_settings()["Modules"]
			value = self._settings.get("Modules", {}).get(module_name, DEFAULT_TOKEN)
			return _resolve_value(value, defaults.get(module_name, False))

	def is_ai_enabled(self) -> bool:
		with self._lock:
			return self._settings.get("aiEnabled") is True

	def set_ai_enabled(self, enabled: bool) -> bool:
		if not isinstance(enabled, bool):
			raise ValueError("aiEnabled must be a Boolean")
		with self._lock:
			if self._settings.get("aiEnabled") is enabled:
				return False
			self._settings["aiEnabled"] = enabled
			self._save_locked()
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener("aiEnabled", {"enabled": enabled})
			except Exception:
				LOGGER.exception("StatMonitor settings listener failed")
		return True

	def update(self, section: str, key: str, value: Any) -> bool:
		return self.update_settings({section: {key: value}})

	def update_settings(self, updates: dict[str, dict[str, Any]]) -> bool:
		if not isinstance(updates, dict):
			raise ValueError("Settings update must be an object")
		if "aiEnabled" in updates or "schemaVersion" in updates or "FanControl" in updates:
			raise ValueError("Reserved setting")
		notifications: list[tuple[str, dict[str, Any]]] = []
		with self._lock:
			candidate = copy.deepcopy(self._settings)
			for section, values in updates.items():
				if section not in _default_settings() or not isinstance(values, dict):
					raise ValueError(f"Unknown settings section: {section}")
				for key, value in values.items():
					if key not in _default_settings()[section]:
						raise ValueError(f"Unknown setting: {section}.{key}")
					if not _is_setting_value(value):
						raise ValueError(f"Invalid setting value for {section}.{key}")
					candidate[section][key] = value
			if candidate == self._settings:
				return False
			for section in _default_settings():
				changed = {key: candidate[section][key] for key in candidate[section] if candidate[section][key] != self._settings[section][key]}
				if changed:
					notifications.append((section, changed))
			self._settings = candidate
			self._save_locked()
			listeners = list(self._listeners)
		for section, changed in notifications:
			for listener in listeners:
				try:
					listener(section, copy.deepcopy(changed))
				except Exception:
					LOGGER.exception("StatMonitor settings listener failed")
		return True

	def _save_locked(self) -> None:
		self.path.parent.mkdir(parents=True, exist_ok=True)
		descriptor, temporary_name = tempfile.mkstemp(prefix=f"{self.path.name}.", suffix=".tmp", dir=self.path.parent)
		try:
			with os.fdopen(descriptor, "w", encoding="utf-8") as file:
				json.dump(self._settings, file, indent=2)
				file.write("\n")
				file.flush()
				os.fsync(file.fileno())
			os.replace(temporary_name, self.path)
		finally:
			if os.path.exists(temporary_name):
				os.unlink(temporary_name)
