from __future__ import annotations

import copy
import math
import threading
import time
from typing import Any


CRITICAL_TEMPERATURE_C = 90.0
STALE_SENSOR_SECONDS = 5.0
FAN_TEST_SECONDS = 15.0
MINIMUM_CONTROL_PERCENT = 30.0
FAN_STALL_RPM = 100.0
FAN_STALL_GRACE_SECONDS = 4.0
SPECIAL_TEMPERATURE_SOURCES = {"CPU", "GPU", "Motherboard", "CaseHottest"}
BUILT_IN_PROFILES = {"CPU", "GPU", "Case", "AIO Pump", "Auxiliary"}

FAN_MAP_COMMANDS = {
	"GetFanMaps": {"purpose": "Return built-in and custom fan maps.", "args": {}, "mutates": False},
	"CreateFanMap": {"purpose": "Create, replace, or tune a validated fan map.", "args": {"name": "map name", "points": "temperature/speed points", "hysteresis_c": "optional 1-8"}, "mutates": True},
	"DeleteFanMap": {"purpose": "Delete a custom fan map.", "args": {"name": "map name"}, "mutates": True},
	"GetFanProfiles": {"purpose": "Return built-in and custom fan profiles.", "args": {}, "mutates": False},
	"CreateFanProfile": {"purpose": "Create or replace a custom fan profile.", "args": {"name": "profile name", "map": "default map or Provider", "temperature_source": "temperature source id"}, "mutates": True},
	"DeleteFanProfile": {"purpose": "Delete a custom fan profile.", "args": {"name": "profile name"}, "mutates": True},
	"SetFanProfileMap": {"purpose": "Set the default map and temperature source for a profile.", "args": {"profile": "profile name", "map": "map name or Provider", "temperature_source": "optional source"}, "mutates": True},
	"GetFanAssignments": {"purpose": "Return discovered fans, registration, profile, map, and live control state.", "args": {}, "mutates": False},
	"GetFanTemperatureSensors": {"purpose": "Return every currently detected temperature sensor plus safe automatic sources.", "args": {}, "mutates": False},
	"RegisterFan": {"purpose": "Register a discovered fan using best guess or an explicit profile.", "args": {"fan_number": "1-based fan number", "profile": "optional profile", "friendly_name": "optional friendly name"}, "mutates": True},
	"UnregisterFan": {"purpose": "Remove a registered fan. Owned fans remain at 100% until reboot.", "args": {"fan_number": "1-based fan number"}, "mutates": True},
	"SetFanFriendlyName": {"purpose": "Set a registered fan friendly name.", "args": {"fan_number": "1-based fan number", "name": "friendly name"}, "mutates": True},
	"SetFanProfile": {"purpose": "Apply a fan profile to a registered fan.", "args": {"fan_number": "1-based fan number", "profile": "profile name"}, "mutates": True},
	"SetFanTemperatureSource": {"purpose": "Set or clear an individual fan temperature-source override.", "args": {"fan_number": "1-based fan number", "source": "temperature source id or null for profile default"}, "mutates": True},
	"AssignFanMap": {"purpose": "Apply an individual map override to a registered fan.", "args": {"fan_number": "1-based fan number", "map": "map name", "sensors": "optional source or list"}, "mutates": True},
	"RemoveFanMapAssignment": {"purpose": "Remove an individual map override and return the fan to its profile map.", "args": {"fan_number": "1-based fan number"}, "mutates": True},
	"SetFanMapsEnabled": {"purpose": "Enable or disable StatMonitor fan-map control. Owned fans go to 100% when disabled and require reboot for firmware control.", "args": {"enabled": "Boolean"}, "mutates": True},
	"GetFanMapStatus": {"purpose": "Return fan-map controller status and safety state.", "args": {}, "mutates": False},
	"TestFanSpeed": {"purpose": "Temporarily override one discovered fan for physical identification. The test automatically expires.", "args": {"fan_number": "1-based fan number", "percent": "30-100"}, "mutates": True},
	"StopFanTest": {"purpose": "Stop a temporary fan test and resume the configured map or 100% failsafe.", "args": {"fan_number": "1-based fan number"}, "mutates": True},
}


class StatMonitorFanMaps:
	def __init__(self, manager, driver, settings):
		self.manager = manager
		self.driver = driver
		self.settings = settings
		self._lock = threading.RLock()
		self._running = False
		self._thread: threading.Thread | None = None
		self._stop = threading.Event()
		self._last_valid_temperature: dict[str, tuple[float, float]] = {}
		self._last_temperature_source: dict[str, tuple[str, str]] = {}
		self._last_target: dict[str, float] = {}
		self._last_set_time: dict[str, float] = {}
		self._last_error: dict[str, str] = {}
		self._test_overrides: dict[str, dict[str, float]] = {}

	def start(self) -> None:
		with self._lock:
			if self._running:
				return
		config = self.settings.get_fan_control()
		if config.get("Enabled"):
			channels = self._get_channels_safe()
			if channels and self._auto_register_missing(config, channels):
				self.settings.replace_fan_control(config)
		with self._lock:
			self._running = True
			self._stop.clear()
			self._thread = threading.Thread(target=self._loop, name="StatMonitorFanMaps", daemon=True)
			self._thread.start()

	def stop(self) -> None:
		with self._lock:
			if not self._running:
				return
			self._running = False
			self._stop.set()
			thread = self._thread
			self._thread = None
		if thread and thread is not threading.current_thread():
			thread.join(timeout=3.0)

	def command_names(self) -> set[str]:
		return set(FAN_MAP_COMMANDS)

	def handle_command(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
		request = dict(arguments) if isinstance(arguments, dict) else {}
		try:
			if command == "GetFanMaps":
				return {"success": True, "maps": self.get_maps()}
			if command == "CreateFanMap":
				return {"success": True, "map": self.create_map(request.get("name"), request.get("points"), request.get("hysteresis_c", 3.0))}
			if command == "DeleteFanMap":
				self.delete_map(request.get("name"))
				return {"success": True, "name": request.get("name")}
			if command == "GetFanProfiles":
				return {"success": True, "profiles": self.get_profiles()}
			if command == "CreateFanProfile":
				return {"success": True, "profile": self.create_profile(request.get("name"), request.get("map", "Balanced"), request.get("temperature_source", "CaseHottest"))}
			if command == "DeleteFanProfile":
				self.delete_profile(request.get("name"))
				return {"success": True, "name": request.get("name")}
			if command == "SetFanProfileMap":
				return {"success": True, "profile": self.set_profile_map(request.get("profile"), request.get("map"), request.get("temperature_source"))}
			if command == "GetFanAssignments":
				return {"success": True, "fans": self.get_assignments()}
			if command == "GetFanTemperatureSensors":
				return {"success": True, **self.get_temperature_sensors()}
			if command == "RegisterFan":
				return {"success": True, "fan": self.register_fan(request.get("fan_number"), request.get("profile"), request.get("friendly_name"))}
			if command == "UnregisterFan":
				return self.unregister_fan(request.get("fan_number"))
			if command == "SetFanFriendlyName":
				return {"success": True, "fan": self.set_friendly_name(request.get("fan_number"), request.get("name"))}
			if command == "SetFanProfile":
				return {"success": True, "fan": self.set_fan_profile(request.get("fan_number"), request.get("profile"))}
			if command == "SetFanTemperatureSource":
				return {"success": True, "fan": self.set_temperature_source(request.get("fan_number"), request.get("source"))}
			if command == "AssignFanMap":
				return {"success": True, "fan": self.assign(request.get("fan_number"), request.get("map"), request.get("sensors"))}
			if command == "RemoveFanMapAssignment":
				return {"success": True, "fan": self.remove_map_override(request.get("fan_number"))}
			if command == "SetFanMapsEnabled":
				enabled = request.get("enabled")
				if not isinstance(enabled, bool):
					raise ValueError("enabled must be Boolean")
				restart_required = self.set_enabled(enabled)
				return {"success": True, "enabled": enabled, "restart_required_for_firmware_control": restart_required}
			if command == "GetFanMapStatus":
				return {"success": True, **self.get_status()}
			if command == "TestFanSpeed":
				return {"success": True, "fan": self.test_fan_speed(request.get("fan_number"), request.get("percent"))}
			if command == "StopFanTest":
				return {"success": True, "fan": self.stop_fan_test(request.get("fan_number"))}
			return {"success": False, "error": "unknown_command", "command": command}
		except ValueError as error:
			return {"success": False, "error": "invalid_request", "command": command, "message": str(error)}
		except Exception as error:
			return {"success": False, "error": "request_failed", "command": command, "message": str(error)}

	def get_maps(self) -> list[dict[str, Any]]:
		config = self.settings.get_fan_control()
		return [self._serialize_map(name, value) for name, value in config.get("Maps", {}).items()]

	def get_profiles(self) -> list[dict[str, Any]]:
		config = self.settings.get_fan_control()
		return [self._serialize_profile(name, value) for name, value in config.get("Profiles", {}).items()]

	def create_map(self, name: Any, points: Any, hysteresis_c: Any = 3.0) -> dict[str, Any]:
		clean_name = str(name or "").strip()
		if not clean_name:
			raise ValueError("name is required")
		validated = self._validate_map(points, hysteresis_c)
		config = self.settings.get_fan_control()
		current = config["Maps"].get(clean_name, {})
		validated["BuiltIn"] = bool(current.get("BuiltIn", False))
		config["Maps"][clean_name] = validated
		self.settings.replace_fan_control(config)
		return self._serialize_map(clean_name, validated)

	def delete_map(self, name: Any) -> None:
		clean_name = str(name or "").strip()
		config = self.settings.get_fan_control()
		current = config.get("Maps", {}).get(clean_name)
		if current is None:
			raise ValueError("fan map not found")
		if current.get("BuiltIn"):
			raise ValueError("built-in fan maps cannot be deleted")
		for profile in config.get("Profiles", {}).values():
			if profile.get("DefaultMap") == clean_name:
				raise ValueError("fan map is assigned to a profile")
		for fan in config.get("Fans", {}).values():
			if fan.get("Map") == clean_name:
				raise ValueError("fan map is assigned to a fan")
		config["Maps"].pop(clean_name, None)
		self.settings.replace_fan_control(config)

	def create_profile(self, name: Any, map_name: Any, temperature_source: Any) -> dict[str, Any]:
		clean_name = str(name or "").strip()
		if not clean_name:
			raise ValueError("name is required")
		config = self.settings.get_fan_control()
		if clean_name in BUILT_IN_PROFILES:
			raise ValueError("built-in fan profiles cannot be replaced; use SetFanProfileMap")
		default_map, provider_controlled = self._normalize_profile_map(map_name, config)
		source = self._normalize_sensors(temperature_source or "CaseHottest")[0]
		profile = {"BuiltIn": False, "DefaultMap": default_map, "TemperatureSource": source, "ProviderControlled": provider_controlled}
		config["Profiles"][clean_name] = profile
		self.settings.replace_fan_control(config)
		return self._serialize_profile(clean_name, profile)

	def delete_profile(self, name: Any) -> None:
		clean_name = str(name or "").strip()
		config = self.settings.get_fan_control()
		profile = config.get("Profiles", {}).get(clean_name)
		if profile is None:
			raise ValueError("fan profile not found")
		if profile.get("BuiltIn"):
			raise ValueError("built-in fan profiles cannot be deleted")
		if any(fan.get("Profile") == clean_name for fan in config.get("Fans", {}).values()):
			raise ValueError("fan profile is currently assigned")
		config["Profiles"].pop(clean_name, None)
		self.settings.replace_fan_control(config)

	def set_profile_map(self, profile_name: Any, map_name: Any, temperature_source: Any = None) -> dict[str, Any]:
		name = str(profile_name or "").strip()
		config = self.settings.get_fan_control()
		profile = config.get("Profiles", {}).get(name)
		if profile is None:
			raise ValueError("fan profile not found")
		default_map, provider_controlled = self._normalize_profile_map(map_name, config)
		profile["DefaultMap"] = default_map
		profile["ProviderControlled"] = provider_controlled
		if temperature_source is not None:
			profile["TemperatureSource"] = self._normalize_sensors(temperature_source)[0]
		if default_map is None:
			channels = {self._fan_identifier(fan): fan for fan in self._get_channels_safe()}
			for identifier, registration in config.get("Fans", {}).items():
				if registration.get("Profile") != name or registration.get("Map"):
					continue
				fan = channels.get(identifier)
				if fan and fan.get("owned"):
					self.driver.handle_command("SetFanSpeed", {"fan_number": fan.get("fan_number"), "percent": 100.0})
		self.settings.replace_fan_control(config)
		return self._serialize_profile(name, profile)

	def register_fan(self, fan_number: Any, profile_name: Any = None, friendly_name: Any = None) -> dict[str, Any]:
		number = self._fan_number(fan_number)
		fan = self._get_discovered_fan(number)
		identifier = self._fan_identifier(fan)
		config = self.settings.get_fan_control()
		profile = str(profile_name or "").strip() or self._guess_profile(fan)
		if profile not in config.get("Profiles", {}):
			raise ValueError("fan profile not found")
		reported = self._reported_name(fan)
		name = str(friendly_name or "").strip() or reported
		current = config.get("Fans", {}).get(identifier, {})
		config["Fans"][identifier] = {
			"FriendlyName": name,
			"ReportedName": reported,
			"Profile": profile,
			"Map": current.get("Map"),
			"TemperatureSources": list(current.get("TemperatureSources") or []),
		}
		self.settings.replace_fan_control(config)
		return self._registration_view(identifier, config["Fans"][identifier], fan, config)

	def unregister_fan(self, fan_number: Any) -> dict[str, Any]:
		number = self._fan_number(fan_number)
		fan = self._get_discovered_fan(number)
		identifier = self._fan_identifier(fan)
		config = self.settings.get_fan_control()
		existed = config.get("Fans", {}).pop(identifier, None) is not None
		if fan.get("owned"):
			self.driver.handle_command("SetFanSpeed", {"fan_number": number, "percent": 100.0})
		self.settings.replace_fan_control(config)
		self._clear_runtime(identifier)
		return {"success": True, "fan_number": number, "identifier": identifier, "removed": existed, "restart_required_for_firmware_control": bool(fan.get("owned")), "session_failsafe_percent": 100.0 if fan.get("owned") else None}

	def set_friendly_name(self, fan_number: Any, name: Any) -> dict[str, Any]:
		identifier, registration, fan, config = self._registered_context(fan_number)
		clean_name = str(name or "").strip()
		if not clean_name:
			raise ValueError("friendly name is required")
		registration["FriendlyName"] = clean_name
		self.settings.replace_fan_control(config)
		return self._registration_view(identifier, registration, fan, config)

	def set_fan_profile(self, fan_number: Any, profile_name: Any) -> dict[str, Any]:
		identifier, registration, fan, config = self._registered_context(fan_number)
		profile = str(profile_name or "").strip()
		if profile not in config.get("Profiles", {}):
			raise ValueError("fan profile not found")
		registration["Profile"] = profile
		effective_map = registration.get("Map") or config["Profiles"][profile].get("DefaultMap")
		if fan.get("owned") and effective_map is None:
			self.driver.handle_command("SetFanSpeed", {"fan_number": fan.get("fan_number"), "percent": 100.0})
		self.settings.replace_fan_control(config)
		self._clear_runtime(identifier)
		return self._registration_view(identifier, registration, fan, config)

	def assign(self, fan_number: Any, map_name: Any, sensors: Any = None) -> dict[str, Any]:
		identifier, registration, fan, config = self._registered_context(fan_number, register_if_missing=True)
		name = str(map_name or "").strip()
		if name not in config.get("Maps", {}):
			raise ValueError("fan map not found")
		registration["Map"] = name
		if sensors is not None:
			registration["TemperatureSources"] = self._normalize_sensors(sensors)
		self.settings.replace_fan_control(config)
		self._clear_runtime(identifier)
		return self._registration_view(identifier, registration, fan, config)

	def remove_map_override(self, fan_number: Any) -> dict[str, Any]:
		identifier, registration, fan, config = self._registered_context(fan_number)
		registration["Map"] = None
		profile = config["Profiles"][registration["Profile"]]
		if fan.get("owned") and profile.get("DefaultMap") is None:
			self.driver.handle_command("SetFanSpeed", {"fan_number": fan["fan_number"], "percent": 100.0})
		self.settings.replace_fan_control(config)
		self._clear_runtime(identifier)
		return self._registration_view(identifier, registration, fan, config)

	def set_enabled(self, enabled: bool) -> bool:
		config = self.settings.get_fan_control()
		channels = self._get_channels_safe()
		restart_required = any(bool(fan.get("owned")) for fan in channels)
		if enabled:
			self._auto_register_missing(config, channels)
		else:
			for fan in channels:
				if fan.get("owned"):
					self.driver.handle_command("SetFanSpeed", {"fan_number": fan.get("fan_number"), "percent": 100.0})
		config["Enabled"] = enabled
		self.settings.replace_fan_control(config)
		return restart_required

	def test_fan_speed(self, fan_number: Any, percent: Any) -> dict[str, Any]:
		number = self._fan_number(fan_number)
		try:
			value = float(percent)
		except (TypeError, ValueError) as error:
			raise ValueError("percent must be numeric") from error
		if not math.isfinite(value) or value < MINIMUM_CONTROL_PERCENT or value > 100.0:
			raise ValueError(f"percent must be between {MINIMUM_CONTROL_PERCENT:.0f} and 100")
		fan = self._get_discovered_fan(number)
		identifier = self._fan_identifier(fan)
		snapshot = self.manager.get_latest_snapshot()
		temperature = self._temperature_for(snapshot, ["CaseHottest"])
		if temperature is not None and temperature >= CRITICAL_TEMPERATURE_C:
			self.driver.handle_command("SetFanSpeed", {"fan_number": number, "percent": 100.0})
			raise ValueError(f"system temperature is critical at {temperature:.1f}C; fan test refused")
		result = self.driver.handle_command("SetFanSpeed", {"fan_number": number, "percent": value})
		if not result.get("success"):
			raise ValueError(result.get("message") or result.get("error") or "fan test speed could not be applied")
		now = time.monotonic()
		self._test_overrides[identifier] = {"percent": round(value, 1), "expires_at": now + FAN_TEST_SECONDS}
		self._last_target[identifier] = round(value, 1)
		self._last_set_time[identifier] = now
		self._last_error.pop(identifier, None)
		config = self.settings.get_fan_control()
		registration = config.get("Fans", {}).get(identifier)
		return self._registration_view(identifier, registration, self._get_discovered_fan(number), config) if registration else self._discovered_view(self._get_discovered_fan(number))

	def stop_fan_test(self, fan_number: Any) -> dict[str, Any]:
		number = self._fan_number(fan_number)
		fan = self._get_discovered_fan(number)
		identifier = self._fan_identifier(fan)
		self._test_overrides.pop(identifier, None)
		self._clear_runtime(identifier)
		config = self.settings.get_fan_control()
		registration = config.get("Fans", {}).get(identifier)
		profile = config.get("Profiles", {}).get(registration.get("Profile"), {}) if registration else {}
		has_map = bool(registration and (registration.get("Map") or profile.get("DefaultMap")))
		if not config.get("Enabled") or not has_map:
			result = self.driver.handle_command("SetFanSpeed", {"fan_number": number, "percent": 100.0})
			if not result.get("success"):
				raise ValueError(result.get("message") or result.get("error") or "100% failsafe could not be applied")
		updated = self._get_discovered_fan(number)
		return self._registration_view(identifier, registration, updated, config) if registration else self._discovered_view(updated)

	def is_fan_managed(self, fan_number: int) -> bool:
		try:
			fan = self._get_discovered_fan(fan_number)
		except Exception:
			return False
		config = self.settings.get_fan_control()
		registration = config.get("Fans", {}).get(self._fan_identifier(fan))
		if not config.get("Enabled") or not registration:
			return False
		profile = config.get("Profiles", {}).get(registration.get("Profile"), {})
		return bool(registration.get("Map") or profile.get("DefaultMap"))

	def get_temperature_sensors(self) -> dict[str, Any]:
		snapshot = self.manager.get_latest_snapshot()
		catalog = self._temperature_catalog(snapshot)
		case_temp, case_id, case_label = self._temperature_detail_for(snapshot, ["CaseHottest"])
		gpu_temp, gpu_id, gpu_label = self._temperature_detail_for(snapshot, ["GPU"])
		cpu_temp, cpu_id, cpu_label = self._temperature_detail_for(snapshot, ["CPU"])
		automatic = [
			{"id": "CaseHottest", "label": "Automatic — Hottest CPU/GPU", "temperature_c": case_temp, "active_source_id": case_id, "active_source_label": case_label, "category": "Automatic", "trusted": True},
			{"id": "CPU", "label": "Automatic — CPU", "temperature_c": cpu_temp, "active_source_id": cpu_id, "active_source_label": cpu_label, "category": "Automatic", "trusted": True},
			{"id": "GPU", "label": "Automatic — GPU", "temperature_c": gpu_temp, "active_source_id": gpu_id, "active_source_label": gpu_label, "category": "Automatic", "trusted": True},
		]
		return {"sensors": automatic + [item for item in catalog if item.get("id") != "CPU"]}

	def set_temperature_source(self, fan_number: Any, source: Any) -> dict[str, Any]:
		identifier, registration, fan, config = self._registered_context(fan_number)
		if source is None or not str(source).strip() or str(source).strip().casefold() in {"profile default", "default", "inherit"}:
			registration["TemperatureSources"] = []
		else:
			registration["TemperatureSources"] = self._normalize_sensors(source)
		self.settings.replace_fan_control(config)
		self._clear_runtime(identifier)
		return self._registration_view(identifier, registration, fan, config)

	def get_assignments(self) -> list[dict[str, Any]]:
		config = self.settings.get_fan_control()
		channels = self._get_channels_safe()
		by_identifier = {self._fan_identifier(fan): fan for fan in channels}
		result = []
		seen = set()
		for fan in channels:
			identifier = self._fan_identifier(fan)
			seen.add(identifier)
			registration = config.get("Fans", {}).get(identifier)
			if registration:
				result.append(self._registration_view(identifier, registration, fan, config))
			else:
				result.append(self._discovered_view(fan))
		for identifier, registration in config.get("Fans", {}).items():
			if identifier in seen:
				continue
			result.append(self._registration_view(identifier, registration, None, config))
		return result

	def get_status(self) -> dict[str, Any]:
		config = self.settings.get_fan_control()
		assignments = self.get_assignments()
		registered = [fan for fan in assignments if fan.get("registered")]
		return {
			"enabled": bool(config.get("Enabled")),
			"running": self._running,
			"registered_count": len(registered),
			"assignment_count": len(registered),
			"assignments": registered,
			"fans": assignments,
			"restart_required_for_firmware_control_after_ownership": True,
			"safety": {
				"critical_temperature_c": CRITICAL_TEMPERATURE_C,
				"stale_sensor_seconds": STALE_SENSOR_SECONDS,
				"minimum_control_percent": MINIMUM_CONTROL_PERCENT,
				"sensor_failure_percent": 100.0,
				"shutdown_owned_fan_percent": 100.0,
				"stall_detection_rpm": FAN_STALL_RPM,
				"stall_grace_seconds": FAN_STALL_GRACE_SECONDS,
			},
		}

	def _loop(self) -> None:
		while not self._stop.wait(1.0):
			config = self.settings.get_fan_control()
			if (not config.get("Enabled") or not config.get("Fans")) and not self._test_overrides:
				continue
			channels = self._get_channels_safe()
			if not channels:
				result = self.driver.handle_command("RestoreOwnedFans", {})
				message = "fan discovery unavailable; all owned fans were moved to 100% failsafe" if self._failsafe_result_verified(result) else "fan discovery unavailable and 100% failsafe could not be verified"
				for identifier in set(config.get("Fans", {})) | set(self._test_overrides):
					self._last_error[identifier] = message
				continue
			by_identifier = {self._fan_identifier(fan): fan for fan in channels}
			snapshot = self.manager.get_latest_snapshot()
			now = time.monotonic()
			global_temperature = self._temperature_for(snapshot, ["CaseHottest"])
			active_tests = set()
			for identifier, test in list(self._test_overrides.items()):
				fan = by_identifier.get(identifier)
				if fan is None:
					self._test_overrides.pop(identifier, None)
					continue
				if now >= float(test.get("expires_at", 0.0)):
					self._test_overrides.pop(identifier, None)
					registration = config.get("Fans", {}).get(identifier)
					profile = config.get("Profiles", {}).get(registration.get("Profile"), {}) if registration else {}
					has_map = bool(registration and (registration.get("Map") or profile.get("DefaultMap")))
					if not config.get("Enabled") or not has_map:
						result = self.driver.handle_command("SetFanSpeed", {"fan_number": fan["fan_number"], "percent": 100.0})
						if result.get("success"):
							self._last_target[identifier] = 100.0
							self._last_set_time[identifier] = now
						else:
							self._last_error[identifier] = "fan test expired and 100% failsafe could not be verified"
					continue
				target = float(test.get("percent", 100.0))
				if global_temperature is not None and global_temperature >= CRITICAL_TEMPERATURE_C:
					target = 100.0
					self._last_error[identifier] = f"critical system temperature {global_temperature:.1f}C; fan test forced to 100%"
				result = self.driver.handle_command("SetFanSpeed", {"fan_number": fan["fan_number"], "percent": target})
				if not result.get("success"):
					self._failsafe_fan(fan, identifier, result.get("message") or result.get("error") or "fan test control failed")
				else:
					self._last_target[identifier] = target
					self._last_set_time[identifier] = now
				active_tests.add(identifier)
			if not config.get("Enabled"):
				continue
			for identifier, registration in copy.deepcopy(config.get("Fans", {})).items():
				if identifier in active_tests:
					continue
				fan = by_identifier.get(identifier)
				if fan is None:
					result = self.driver.handle_command("RestoreOwnedFans", {})
					self._last_error[identifier] = "fan channel is unavailable; all owned fans were moved to 100% failsafe" if self._failsafe_result_verified(result) else "fan channel is unavailable and 100% failsafe could not be verified"
					continue
				profile = config.get("Profiles", {}).get(registration.get("Profile"), {})
				map_name = registration.get("Map") or profile.get("DefaultMap")
				if not map_name:
					continue
				fan_map = config.get("Maps", {}).get(map_name)
				if not fan_map:
					self._failsafe_fan(fan, identifier, "fan map is unavailable")
					continue
				sources = registration.get("TemperatureSources") or [profile.get("TemperatureSource") or "CaseHottest"]
				try:
					temperature, active_source_id, active_source_label = self._temperature_detail_for(snapshot, sources)
					if temperature is not None:
						self._last_valid_temperature[identifier] = (temperature, now)
						if active_source_id and active_source_label:
							self._last_temperature_source[identifier] = (active_source_id, active_source_label)
					last = self._last_valid_temperature.get(identifier)
					safety_error = None
					if last is None or now - last[1] > STALE_SENSOR_SECONDS:
						target = 100.0
						safety_error = "temperature source unavailable or stale; 100% failsafe active"
					else:
						target = self._target_for(fan_map, last[0], self._last_target.get(identifier))
					if global_temperature is not None and global_temperature >= CRITICAL_TEMPERATURE_C:
						target = 100.0
						safety_error = f"critical system temperature {global_temperature:.1f}C; 100% failsafe active"
					previous = self._last_target.get(identifier)
					last_set = self._last_set_time.get(identifier, 0.0)
					rpm = fan.get("rpm")
					if fan.get("owned") and previous is not None and isinstance(rpm, (int, float)) and not isinstance(rpm, bool) and now - last_set >= FAN_STALL_GRACE_SECONDS and float(rpm) < FAN_STALL_RPM:
						target = 100.0
						safety_error = f"fan stall detected at {float(rpm):.0f} RPM; 100% failsafe active"
					if previous is None or abs(previous - target) >= 2.0 or now - last_set >= 5.0:
						result = self.driver.handle_command("SetFanSpeed", {"fan_number": fan["fan_number"], "percent": target})
						if not result.get("success"):
							raise RuntimeError(result.get("message") or result.get("error") or "fan control failed")
						self._last_target[identifier] = target
						self._last_set_time[identifier] = now
					if safety_error:
						self._last_error[identifier] = safety_error
					else:
						self._last_error.pop(identifier, None)
				except Exception as error:
					self._failsafe_fan(fan, identifier, str(error))

	def _failsafe_fan(self, fan: dict[str, Any], identifier: str, error: str) -> None:
		try:
			result = self.driver.handle_command("SetFanSpeed", {"fan_number": fan.get("fan_number"), "percent": 100.0})
			if result.get("success"):
				self._last_error[identifier] = f"{error}; 100% failsafe active"
				self._last_target[identifier] = 100.0
				self._last_set_time[identifier] = time.monotonic()
			else:
				self._last_error[identifier] = f"{error}; 100% failsafe could not be verified"
		except Exception:
			self._last_error[identifier] = f"{error}; 100% failsafe could not be applied"

	@staticmethod
	def _failsafe_result_verified(result: Any) -> bool:
		if not isinstance(result, dict):
			return False
		if "failsafe_verified" in result:
			return result.get("failsafe_verified") is True
		return result.get("success") is True

	def _target_for(self, fan_map: dict[str, Any], temperature: float, previous: float | None) -> float:
		points = [(float(point["TemperatureC"]), float(point["SpeedPercent"])) for point in fan_map.get("Points", [])]
		if len(points) < 2:
			return 100.0
		hysteresis = float(fan_map.get("HysteresisC", 3.0))
		adjusted_temperature = temperature
		if previous is not None:
			curve_now = self._interpolate(points, temperature)
			if curve_now < previous:
				adjusted_temperature = temperature + hysteresis
		return round(max(MINIMUM_CONTROL_PERCENT, min(100.0, self._interpolate(points, adjusted_temperature))), 1)

	@staticmethod
	def _interpolate(points: list[tuple[float, float]], temperature: float) -> float:
		if temperature <= points[0][0]:
			return points[0][1]
		for left, right in zip(points, points[1:]):
			if temperature <= right[0]:
				ratio = (temperature - left[0]) / (right[0] - left[0])
				return left[1] + ratio * (right[1] - left[1])
		return points[-1][1]

	@classmethod
	def _temperature_for(cls, snapshot: dict[str, Any], sensors: list[str]) -> float | None:
		value, _, _ = cls._temperature_detail_for(snapshot, sensors)
		return value

	@classmethod
	def _temperature_detail_for(cls, snapshot: dict[str, Any], sensors: list[str]) -> tuple[float | None, str | None, str | None]:
		catalog = cls._temperature_catalog(snapshot)
		requested = sensors or ["CaseHottest"]
		candidates: list[dict[str, Any]] = []
		for source in requested:
			text = cls._normalize_source_name(source)
			if text == "CaseHottest":
				candidates.extend(item for item in catalog if item.get("automatic_case_candidate"))
			elif text == "CPU":
				candidates.extend(item for item in catalog if item.get("id") == "CPU")
			elif text == "GPU":
				candidates.extend(item for item in catalog if item.get("category") == "GPU" and item.get("trusted") and item.get("specific"))
			elif text == "Motherboard":
				candidates.extend(item for item in catalog if item.get("category") == "Motherboard" and item.get("specific"))
			else:
				candidates.extend(item for item in catalog if item.get("id") == text)
		valid = [item for item in candidates if isinstance(item.get("temperature_c"), (int, float)) and not isinstance(item.get("temperature_c"), bool) and math.isfinite(float(item.get("temperature_c")))]
		if not valid:
			return None, None, None
		winner = max(valid, key=lambda item: float(item["temperature_c"]))
		return float(winner["temperature_c"]), str(winner.get("id") or ""), str(winner.get("label") or winner.get("id") or "")

	@classmethod
	def _temperature_catalog(cls, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
		modules = snapshot.get("modules", {}) if isinstance(snapshot, dict) else {}
		items: list[dict[str, Any]] = []
		def add(sensor_id: str, label: str, value: Any, category: str, trusted: bool, specific: bool = True, automatic_case_candidate: bool = False):
			if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
				return
			items.append({"id": sensor_id, "label": label, "temperature_c": round(float(value), 1), "category": category, "trusted": bool(trusted), "specific": bool(specific), "automatic_case_candidate": bool(automatic_case_candidate)})

		cpu = modules.get("CPU", {}) if isinstance(modules.get("CPU"), dict) else {}
		cpu_live = cpu.get("live", {}) if isinstance(cpu.get("live"), dict) else {}
		add("CPU", "CPU — Primary", cpu_live.get("temperature_c"), "CPU", True, False, True)
		for index, core in enumerate(cpu_live.get("individual_cores", []) or []):
			if not isinstance(core, dict):
				continue
			name = str(core.get("name") or f"Core {index + 1}").strip()
			add(f"CPUCore::{index}::{name}", f"CPU — {name}", core.get("temperature_c"), "CPU", True, True, False)

		gpu_module = modules.get("GPU", {}) if isinstance(modules.get("GPU"), dict) else {}
		gpu_live = gpu_module.get("live", {}) if isinstance(gpu_module.get("live"), dict) else {}
		gpu_hardware = gpu_module.get("hardware", {}) if isinstance(gpu_module.get("hardware"), dict) else {}
		gpu_hw_list = gpu_hardware.get("gpus", []) if isinstance(gpu_hardware.get("gpus"), list) else []
		gpu_entries = gpu_live.get("gpus", []) if isinstance(gpu_live.get("gpus"), list) else []
		for index, gpu in enumerate(gpu_entries):
			if not isinstance(gpu, dict):
				continue
			hw = gpu_hw_list[index] if index < len(gpu_hw_list) and isinstance(gpu_hw_list[index], dict) else {}
			name = str(gpu.get("name") or hw.get("name") or hw.get("adapter_name") or f"GPU {index + 1}").strip()
			gpu_id = str(gpu.get("gpu_id") or hw.get("gpu_id") or index).strip()
			add(f"GPUDevice::{gpu_id}", f"GPU — {name}", gpu.get("temperature_c"), "GPU", True, True, True)

		mb = modules.get("Motherboard", {}) if isinstance(modules.get("Motherboard"), dict) else {}
		mb_live = mb.get("live", {}) if isinstance(mb.get("live"), dict) else {}
		for index, sensor in enumerate(mb_live.get("temperatures", []) or []):
			if not isinstance(sensor, dict):
				continue
			name = str(sensor.get("name") or f"Temperature {index + 1}").strip()
			add(f"MotherboardSensor::{index}::{name}", f"Motherboard — {name}", sensor.get("temperature_c"), "Motherboard", False, True, False)
		return items

	@classmethod
	def _normalize_source_name(cls, value: Any) -> str:
		text = str(value or "").strip()
		if text == "SystemMax":
			return "CaseHottest"
		return text

	@staticmethod
	def _validate_map(points: Any, hysteresis_c: Any) -> dict[str, Any]:
		if not isinstance(points, list) or len(points) < 2:
			raise ValueError("points must contain at least two entries")
		clean = []
		for point in points:
			if isinstance(point, dict):
				temperature = point.get("temperature_c", point.get("TemperatureC"))
				speed = point.get("speed_percent", point.get("SpeedPercent"))
			elif isinstance(point, (list, tuple)) and len(point) == 2:
				temperature, speed = point
			else:
				raise ValueError("each point must contain temperature and fan speed")
			if isinstance(temperature, bool) or isinstance(speed, bool):
				raise ValueError("fan map points must be numeric")
			t = float(temperature)
			s = float(speed)
			if not math.isfinite(t) or not math.isfinite(s) or not 20.0 <= t <= 100.0 or not 30.0 <= s <= 100.0:
				raise ValueError("temperature must be 20-100C and fan speed 30-100%")
			if clean and t <= clean[-1]["TemperatureC"]:
				raise ValueError("fan map temperatures must strictly increase")
			if clean and s < clean[-1]["SpeedPercent"]:
				raise ValueError("fan speed may not decrease as temperature rises")
			clean.append({"TemperatureC": t, "SpeedPercent": s})
		if clean[-1]["TemperatureC"] > CRITICAL_TEMPERATURE_C or clean[-1]["SpeedPercent"] != 100.0:
			raise ValueError("safe fan maps must reach 100% by 90C")
		h = float(hysteresis_c)
		if not math.isfinite(h) or not 1.0 <= h <= 8.0:
			raise ValueError("hysteresis_c must be between 1 and 8")
		return {"BuiltIn": False, "HysteresisC": h, "Points": clean}

	@classmethod
	def _normalize_sensors(cls, value: Any) -> list[str]:
		items = [value] if isinstance(value, str) else list(value) if isinstance(value, (list, tuple)) else []
		result = []
		for item in items:
			text = cls._normalize_source_name(item)
			valid = text in SPECIAL_TEMPERATURE_SOURCES or text.startswith(("CPUCore::", "GPUDevice::", "MotherboardSensor::"))
			if not valid:
				raise ValueError(f"unknown temperature source: {item}")
			if text not in result:
				result.append(text)
		return result or ["CaseHottest"]

	@staticmethod
	def _fan_number(value: Any) -> int:
		if isinstance(value, bool):
			raise ValueError("fan_number must be an integer")
		number = int(value)
		if number < 1:
			raise ValueError("fan_number must be at least 1")
		return number

	def _registered_context(self, fan_number: Any, register_if_missing: bool = False):
		number = self._fan_number(fan_number)
		fan = self._get_discovered_fan(number)
		identifier = self._fan_identifier(fan)
		config = self.settings.get_fan_control()
		registration = config.get("Fans", {}).get(identifier)
		if registration is None and register_if_missing:
			self.register_fan(number)
			config = self.settings.get_fan_control()
			registration = config.get("Fans", {}).get(identifier)
		if registration is None:
			raise ValueError("fan is not registered")
		return identifier, registration, fan, config


	def _auto_register_missing(self, config: dict[str, Any], channels: list[dict[str, Any]]) -> bool:
		changed = False
		profiles = config.get("Profiles", {})
		fans = config.setdefault("Fans", {})
		for fan in channels:
			identifier = self._fan_identifier(fan)
			if identifier in fans:
				continue
			profile = self._guess_profile(fan)
			if profile not in profiles:
				profile = "Auxiliary"
			reported = self._reported_name(fan)
			fans[identifier] = {
				"FriendlyName": reported,
				"ReportedName": reported,
				"Profile": profile,
				"Map": None,
				"TemperatureSources": [],
			}
			changed = True
		return changed

	def _get_discovered_fan(self, fan_number: int) -> dict[str, Any]:
		result = self.driver.handle_command("GetFanStatus", {"fan_number": fan_number})
		if not result.get("success") or not isinstance(result.get("fan"), dict):
			raise ValueError("fan channel is unavailable")
		return result["fan"]

	def _get_channels_safe(self) -> list[dict[str, Any]]:
		try:
			result = self.driver.handle_command("GetFanChannels", {})
			fans = result.get("fans") if result.get("success") else []
			return [fan for fan in fans if isinstance(fan, dict)] if isinstance(fans, list) else []
		except Exception:
			return []

	@staticmethod
	def _fan_identifier(fan: dict[str, Any]) -> str:
		identifier = str(fan.get("control_identifier") or "").strip()
		if identifier:
			return identifier
		return f"fan-number:{int(fan.get('fan_number') or 0)}"

	@staticmethod
	def _reported_name(fan: dict[str, Any]) -> str:
		for key in ("fan_name", "control_name", "hardware"):
			value = str(fan.get(key) or "").strip()
			if value:
				return value
		return f"Fan {fan.get('fan_number', '?')}"

	@classmethod
	def _guess_profile(cls, fan: dict[str, Any]) -> str:
		text = " ".join(str(fan.get(key) or "") for key in ("fan_name", "control_name", "hardware", "control_identifier")).casefold()
		if any(token in text for token in ("aio", "pump", "water")):
			return "AIO Pump"
		if "gpu" in text:
			return "GPU"
		if any(token in text for token in ("cpu", "processor")):
			return "CPU"
		if any(token in text for token in ("case", "chassis", "cha_", "system fan", "sys_fan", "front", "rear")):
			return "Case"
		return "Auxiliary"

	@staticmethod
	def _normalize_profile_map(value: Any, config: dict[str, Any]) -> tuple[str | None, bool]:
		text = str(value or "").strip()
		if not text or text.casefold() in {"provider", "provider controlled", "none"}:
			return None, True
		if text not in config.get("Maps", {}):
			raise ValueError("fan map not found")
		return text, False

	def _discovered_view(self, fan: dict[str, Any]) -> dict[str, Any]:
		identifier = self._fan_identifier(fan)
		test = self._test_overrides.get(identifier)
		remaining = max(0.0, float(test.get("expires_at", 0.0)) - time.monotonic()) if test else 0.0
		return {
			"fan_number": fan.get("fan_number"),
			"identifier": identifier,
			"reported_name": self._reported_name(fan),
			"friendly_name": None,
			"registered": False,
			"best_guess_profile": self._guess_profile(fan),
			"rpm": fan.get("rpm"),
			"output_percent": fan.get("output_percent"),
			"target_percent": self._last_target.get(identifier),
			"owned": bool(fan.get("owned")),
			"test_active": bool(test and remaining > 0.0),
			"test_percent": test.get("percent") if test else None,
			"test_remaining_seconds": round(remaining, 1),
		}

	def _registration_view(self, identifier: str, registration: dict[str, Any], fan: dict[str, Any] | None, config: dict[str, Any]) -> dict[str, Any]:
		profile = config.get("Profiles", {}).get(registration.get("Profile"), {})
		map_name = registration.get("Map") or profile.get("DefaultMap")
		override_sources = list(registration.get("TemperatureSources") or [])
		sources = override_sources or [profile.get("TemperatureSource") or "CaseHottest"]
		last = self._last_valid_temperature.get(identifier)
		active_source = self._last_temperature_source.get(identifier)
		test = self._test_overrides.get(identifier)
		remaining = max(0.0, float(test.get("expires_at", 0.0)) - time.monotonic()) if test else 0.0
		return {
			"fan_number": fan.get("fan_number") if fan else None,
			"identifier": identifier,
			"reported_name": registration.get("ReportedName") or (self._reported_name(fan) if fan else ""),
			"friendly_name": registration.get("FriendlyName") or registration.get("ReportedName") or identifier,
			"registered": True,
			"profile": registration.get("Profile"),
			"map": map_name,
			"map_override": registration.get("Map"),
			"temperature_sources": list(sources),
			"temperature_source_override": override_sources[0] if override_sources else None,
			"profile_temperature_source": profile.get("TemperatureSource") or "CaseHottest",
			"provider_controlled": map_name is None,
			"temperature_c": last[0] if last else None,
			"active_temperature_source_id": active_source[0] if active_source else None,
			"active_temperature_source_label": active_source[1] if active_source else None,
			"target_percent": self._last_target.get(identifier),
			"rpm": fan.get("rpm") if fan else None,
			"output_percent": fan.get("output_percent") if fan else None,
			"owned": bool(fan.get("owned")) if fan else False,
			"last_error": self._last_error.get(identifier),
			"test_active": bool(test and remaining > 0.0),
			"test_percent": test.get("percent") if test else None,
			"test_remaining_seconds": round(remaining, 1),
		}

	@staticmethod
	def _serialize_map(name: str, value: dict[str, Any]) -> dict[str, Any]:
		return {"name": name, "built_in": bool(value.get("BuiltIn")), "hysteresis_c": value.get("HysteresisC"), "points": [{"temperature_c": point.get("TemperatureC"), "speed_percent": point.get("SpeedPercent")} for point in value.get("Points", [])]}

	@staticmethod
	def _serialize_profile(name: str, value: dict[str, Any]) -> dict[str, Any]:
		return {"name": name, "built_in": bool(value.get("BuiltIn")), "default_map": value.get("DefaultMap"), "temperature_source": value.get("TemperatureSource"), "provider_controlled": bool(value.get("ProviderControlled"))}

	def _clear_runtime(self, identifier: str) -> None:
		self._last_valid_temperature.pop(identifier, None)
		self._last_temperature_source.pop(identifier, None)
		self._last_target.pop(identifier, None)
		self._last_set_time.pop(identifier, None)
		self._last_error.pop(identifier, None)
