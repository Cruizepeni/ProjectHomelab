from __future__ import annotations

import copy
import json
import shlex
import sys
import threading
from typing import Any, Callable

from StatMonitorLogger import StatMonitorLogger


DATA_MODES = {"all", "hardware", "live"}
_COMMAND_ALIASES = {
	"help": "Help",
	"commands": "Help",
	"exit": "Exit",
	"quit": "Exit",
	"getfanchannels": "GetFanChannels",
	"getfanstatus": "GetFanStatus",
	"setfanspeed": "SetFanSpeed",
	"setfandefault": "SetFanDefault",
	"restoreownedfans": "RestoreOwnedFans",
	"getfanmaps": "GetFanMaps",
	"createfanmap": "CreateFanMap",
	"deletefanmap": "DeleteFanMap",
	"getfanprofiles": "GetFanProfiles",
	"createfanprofile": "CreateFanProfile",
	"deletefanprofile": "DeleteFanProfile",
	"setfanprofilemap": "SetFanProfileMap",
	"getfanassignments": "GetFanAssignments",
	"getfantemperaturesensors": "GetFanTemperatureSensors",
	"registerfan": "RegisterFan",
	"unregisterfan": "UnregisterFan",
	"setfanfriendlyname": "SetFanFriendlyName",
	"setfanname": "SetFanFriendlyName",
	"setfanprofile": "SetFanProfile",
	"setfantemperaturesource": "SetFanTemperatureSource",
	"assignfanmap": "AssignFanMap",
	"removefanmapassignment": "RemoveFanMapAssignment",
	"setfanmapsenabled": "SetFanMapsEnabled",
	"getfanmapstatus": "GetFanMapStatus",
	"log": "Log",
	"startlog": "Log",
	"stoplog": "StopLog",
	"getlogstatus": "GetLogStatus",
	"logstatus": "GetLogStatus",
	"getvendortools": "GetVendorTools",
	"applyvendortool": "ApplyVendorTool",
	"getwifistatus": "GetWiFiStatus",
	"getwifinetworks": "GetWiFiNetworks",
	"getsavedwifinetworks": "GetSavedWiFiNetworks",
	"scanwifi": "ScanWiFi",
	"connectwifi": "ConnectWiFi",
	"disconnectwifi": "DisconnectWiFi",
	"forgetwifinetwork": "ForgetWiFiNetwork",
	"wifion": "WiFiOn",
	"wifioff": "WiFiOff",
	"getbluetoothstatus": "GetBluetoothStatus",
	"getbluetoothadapters": "GetBluetoothAdapters",
	"getbluetoothdevices": "GetBluetoothDevices",
	"scanbluetooth": "ScanBluetooth",
	"pairbluetoothdevice": "PairBluetoothDevice",
	"unpairbluetoothdevice": "UnpairBluetoothDevice",
	"connectbluetoothdevice": "ConnectBluetoothDevice",
	"disconnectbluetoothdevice": "DisconnectBluetoothDevice",
	"bluetoothon": "BluetoothOn",
	"bluetoothoff": "BluetoothOff",
	"getprivacystatus": "GetPrivacyStatus",
	"cameraon": "CameraOn",
	"cameraoff": "CameraOff",
	"microphoneon": "MicrophoneOn",
	"microphoneoff": "MicrophoneOff",
	"locationon": "LocationOn",
	"locationoff": "LocationOff",
	"getstoragetooldisks": "GetStorageToolDisks",
	"refreshstoragetooldisks": "RefreshStorageToolDisks",
	"getstoragetoolcapabilities": "GetStorageToolCapabilities",
	"getstats": "GetStats",
	"getmodulestates": "GetModuleStates",
	"getsettings": "GetSettings",
	"setmoduleenabled": "SetModuleEnabled",
	"setsetting": "SetSetting",
	"getwarnings": "GetWarnings",
	"getserverinfo": "GetServerInfo",
	"getservertoken": "GetServerToken",
	"getcapabilities": "GetCapabilities",
}


class StatMonitorTerminal:
	def __init__(self, stat_monitor: Any, *, request_stop: Callable[[], None]):
		self.stat_monitor = stat_monitor
		self.manager = stat_monitor.manager
		self.settings = stat_monitor.settings
		self.fan_controller = stat_monitor.fan_controller
		self.logger = stat_monitor.logger
		self._request_stop = request_stop
		self._thread: threading.Thread | None = None
		self._stopping = threading.Event()

	def start(self) -> bool:
		if not self.is_available():
			return False
		if self._thread is not None and self._thread.is_alive():
			return True
		self._stopping.clear()
		self._thread = threading.Thread(target=self.run, name="StatMonitorTerminal", daemon=True)
		self._thread.start()
		return True

	def stop(self) -> None:
		self._stopping.set()

	@staticmethod
	def is_available() -> bool:
		stdin = getattr(sys, "stdin", None)
		return bool(stdin is not None and hasattr(stdin, "isatty") and stdin.isatty())

	def run(self) -> None:
		self._print_banner()
		while not self._stopping.is_set():
			try:
				raw = input("\nStatMonitor> ").strip()
			except (EOFError, KeyboardInterrupt):
				print()
				self._request_stop()
				return
			if not raw:
				continue
			try:
				result = self.execute_line(raw)
				if result is not None:
					self._print_result(result)
			except Exception as error:
				print(f"Command Error: {type(error).__name__}: {error}")

	def execute_line(self, raw: str) -> Any:
		command, arguments = self._parse_command(raw)
		if command == "Exit":
			self._request_stop()
			return {"success": True, "command": "Exit"}
		return self._execute(command, arguments)

	def _execute(self, command: str, arguments: list[str]) -> Any:
		if command == "Help":
			return {"success": True, "commands": self._help_lines()}
		if command in {"GetFanChannels", "RestoreOwnedFans", "GetFanMaps", "GetFanProfiles", "GetFanAssignments", "GetFanTemperatureSensors", "GetFanMapStatus"}:
			self._require_arg_count(arguments, 0, 0, command)
			return self.fan_controller.handle_command(command)
		if command == "Log":
			return self._start_log(arguments)
		if command == "StopLog":
			self._require_arg_count(arguments, 0, 0, "Stop Log")
			return self.logger.handle_command("StopLog")
		if command == "GetLogStatus":
			self._require_arg_count(arguments, 0, 0, "GetLogStatus")
			return self.logger.handle_command("GetLogStatus")
		if command == "GetFanStatus":
			self._require_arg_count(arguments, 0, 1, "GetFanStatus [fan_number]")
			request = {"fan_number": int(arguments[0])} if arguments else {}
			return self.fan_controller.handle_command(command, request)
		if command == "SetFanSpeed":
			self._require_arg_count(arguments, 2, 2, "SetFanSpeed <fan_number> <percent>")
			return self.fan_controller.handle_command(command, {"fan_number": int(arguments[0]), "percent": float(arguments[1])})
		if command == "SetFanDefault":
			self._require_arg_count(arguments, 1, 1, "SetFanDefault <fan_number>")
			return self.fan_controller.handle_command(command, {"fan_number": int(arguments[0])})
		if command == "RegisterFan":
			self._require_arg_count(arguments, 1, 3, 'RegisterFan <fan_number> [profile] ["friendly name"]')
			payload = {"fan_number": int(arguments[0])}
			if len(arguments) > 1:
				payload["profile"] = arguments[1]
			if len(arguments) > 2:
				payload["friendly_name"] = arguments[2]
			return self.fan_controller.handle_command(command, payload)
		if command == "UnregisterFan":
			self._require_arg_count(arguments, 1, 1, "UnregisterFan <fan_number>")
			return self.fan_controller.handle_command(command, {"fan_number": int(arguments[0])})
		if command == "SetFanFriendlyName":
			if len(arguments) < 2:
				raise ValueError('Use: SetFanName <fan_number> "friendly name"')
			return self.fan_controller.handle_command(command, {"fan_number": int(arguments[0]), "name": " ".join(arguments[1:])})
		if command == "SetFanProfile":
			self._require_arg_count(arguments, 2, 2, "SetFanProfile <fan_number> <profile>")
			return self.fan_controller.handle_command(command, {"fan_number": int(arguments[0]), "profile": arguments[1]})
		if command == "SetFanTemperatureSource":
			self._require_arg_count(arguments, 1, 2, "SetFanTemperatureSource <fan_number> [source|default]")
			source = None if len(arguments) == 1 or arguments[1].casefold() in {"default", "inherit"} else arguments[1]
			return self.fan_controller.handle_command(command, {"fan_number": int(arguments[0]), "source": source})
		if command == "AssignFanMap":
			self._require_arg_count(arguments, 2, 3, "AssignFanMap <fan_number> <map> [temperature_source]")
			payload = {"fan_number": int(arguments[0]), "map": arguments[1]}
			if len(arguments) > 2:
				payload["sensors"] = arguments[2].split(",")
			return self.fan_controller.handle_command(command, payload)
		if command == "RemoveFanMapAssignment":
			self._require_arg_count(arguments, 1, 1, "RemoveFanMapAssignment <fan_number>")
			return self.fan_controller.handle_command(command, {"fan_number": int(arguments[0])})
		if command == "SetFanMapsEnabled":
			self._require_arg_count(arguments, 1, 1, "SetFanMapsEnabled <true|false>")
			value = self._parse_bool(arguments[0])
			return self.fan_controller.handle_command(command, {"enabled": value})
		if command == "CreateFanMap":
			if len(arguments) < 3:
				raise ValueError("Use: CreateFanMap <name> <hysteresis_c> <temp:percent,temp:percent,...>")
			name = arguments[0]
			hysteresis = float(arguments[1])
			points = []
			for token in "".join(arguments[2:]).split(","):
				temperature, percent = token.split(":", 1)
				points.append({"temperature_c": float(temperature), "speed_percent": float(percent)})
			return self.fan_controller.handle_command(command, {"name": name, "hysteresis_c": hysteresis, "points": points})
		if command == "DeleteFanMap":
			self._require_arg_count(arguments, 1, 1, "DeleteFanMap <name>")
			return self.fan_controller.handle_command(command, {"name": arguments[0]})
		if command == "CreateFanProfile":
			self._require_arg_count(arguments, 1, 3, 'CreateFanProfile <name> [map|Provider] [temperature_source]')
			payload = {"name": arguments[0]}
			if len(arguments) > 1:
				payload["map"] = arguments[1]
			if len(arguments) > 2:
				payload["temperature_source"] = arguments[2]
			return self.fan_controller.handle_command(command, payload)
		if command == "DeleteFanProfile":
			self._require_arg_count(arguments, 1, 1, "DeleteFanProfile <name>")
			return self.fan_controller.handle_command(command, {"name": arguments[0]})
		if command == "SetFanProfileMap":
			self._require_arg_count(arguments, 2, 3, "SetFanProfileMap <profile> <map|Provider> [temperature_source]")
			payload = {"profile": arguments[0], "map": arguments[1]}
			if len(arguments) > 2:
				payload["temperature_source"] = arguments[2]
			return self.fan_controller.handle_command(command, payload)
		if command in {"GetWiFiStatus", "GetWiFiNetworks", "GetSavedWiFiNetworks", "ScanWiFi", "WiFiOn", "WiFiOff", "GetBluetoothStatus", "GetBluetoothAdapters", "GetBluetoothDevices", "BluetoothOn", "BluetoothOff", "GetPrivacyStatus", "CameraOn", "CameraOff", "MicrophoneOn", "MicrophoneOff", "LocationOn", "LocationOff", "GetStorageToolDisks", "RefreshStorageToolDisks", "GetStorageToolCapabilities"}:
			self._require_arg_count(arguments, 0, 0, command)
			return self.stat_monitor.handle_device_command(command, {})
		if command == "ScanBluetooth":
			self._require_arg_count(arguments, 0, 1, "ScanBluetooth [seconds]")
			payload = {"seconds": float(arguments[0])} if arguments else {}
			return self.stat_monitor.handle_device_command(command, payload)
		if command == "ConnectWiFi":
			self._require_arg_count(arguments, 1, 3, "ConnectWiFi <ssid> [password] [interface]")
			payload = {"ssid": arguments[0]}
			if len(arguments) > 1:
				payload["password"] = arguments[1]
			if len(arguments) > 2:
				payload["interface_id"] = arguments[2]
			return self.stat_monitor.handle_device_command(command, payload)
		if command == "DisconnectWiFi":
			self._require_arg_count(arguments, 0, 1, "DisconnectWiFi [interface]")
			payload = {"interface_id": arguments[0]} if arguments else {}
			return self.stat_monitor.handle_device_command(command, payload)
		if command == "ForgetWiFiNetwork":
			self._require_arg_count(arguments, 1, 2, "ForgetWiFiNetwork <profile> [interface]")
			payload = {"profile": arguments[0]}
			if len(arguments) > 1:
				payload["interface_id"] = arguments[1]
			return self.stat_monitor.handle_device_command(command, payload)
		if command in {"PairBluetoothDevice", "UnpairBluetoothDevice", "ConnectBluetoothDevice", "DisconnectBluetoothDevice"}:
			self._require_arg_count(arguments, 1, 1, f"{command} <device>")
			return self.stat_monitor.handle_device_command(command, {"device": arguments[0]})
		if command == "GetVendorTools":
			self._require_arg_count(arguments, 0, 0, "GetVendorTools")
			return {"success": True, "tools": self.stat_monitor.vendor_tools.get_status()}
		if command == "ApplyVendorTool":
			self._require_arg_count(arguments, 1, 1, "ApplyVendorTool <tool_id>")
			return self.stat_monitor.vendor_tools.apply(arguments[0])
		if command == "GetStats":
			return self._get_stats(arguments)
		if command == "GetModuleStates":
			return self._get_module_states(arguments)
		if command == "GetSettings":
			return self._get_settings(arguments)
		if command == "SetModuleEnabled":
			return self._set_module_enabled(arguments)
		if command == "SetSetting":
			return self._set_setting(arguments)
		if command == "GetWarnings":
			self._require_arg_count(arguments, 0, 0, "GetWarnings")
			return {"success": True, "warnings": copy.deepcopy(self.manager.get_latest_snapshot().get("warnings", []))}
		if command == "GetServerInfo":
			self._require_arg_count(arguments, 0, 0, "GetServerInfo")
			return {"success": True, "server": self.stat_monitor.server.get_server_info()}
		if command == "GetServerToken":
			self._require_arg_count(arguments, 0, 0, "GetServerToken")
			return {"success": True, "token": self.stat_monitor.server.access.get_token()}
		if command == "GetCapabilities":
			self._require_arg_count(arguments, 0, 0, "GetCapabilities")
			return {"success": True, "capabilities": self.stat_monitor.server.get_capabilities()}
		raise ValueError(f"Unknown terminal command: {command}")

	def _start_log(self, arguments: list[str]) -> dict[str, Any]:
		path = None
		interval = None
		remaining = []
		index = 0
		while index < len(arguments):
			item = arguments[index]
			if item == "--path":
				if index + 1 >= len(arguments):
					raise ValueError("--path requires a directory or .jsonl file")
				path = arguments[index + 1]
				index += 2
				continue
			if item.startswith("--path="):
				path = item.split("=", 1)[1]
				index += 1
				continue
			if item == "--interval":
				if index + 1 >= len(arguments):
					raise ValueError("--interval requires a duration such as 500ms, 1s, or 5s")
				interval = StatMonitorLogger.parse_duration(arguments[index + 1])
				index += 2
				continue
			if item.startswith("--interval="):
				interval = StatMonitorLogger.parse_duration(item.split("=", 1)[1])
				index += 1
				continue
			remaining.append(item)
			index += 1
		duration = None
		modules = []
		for item in remaining:
			if duration is None and StatMonitorLogger.looks_like_duration(item):
				duration = StatMonitorLogger.parse_duration(item)
			else:
				modules.extend(token for token in item.split(",") if token.strip())
		payload = {"modules": modules or "all"}
		if duration is not None:
			payload["duration_seconds"] = duration
		if path is not None:
			payload["path"] = path
		if interval is not None:
			payload["interval_seconds"] = interval
		return self.logger.handle_command("StartLog", payload)

	def _get_stats(self, arguments: list[str]) -> dict[str, Any]:
		mode = "all"
		module_tokens = list(arguments)
		if module_tokens and module_tokens[-1].lower() in DATA_MODES:
			mode = module_tokens.pop().lower()
		modules = self._parse_modules(module_tokens)
		snapshot = self.manager.get_latest_snapshot()
		result = {}
		for name in modules:
			entry = snapshot.get("modules", {}).get(name, {"state": "unavailable", "hardware": {}, "live": {}})
			filtered = {"state": entry.get("state", "unavailable")}
			if mode in ("all", "hardware"):
				filtered["hardware"] = copy.deepcopy(entry.get("hardware", {}))
			if mode in ("all", "live"):
				filtered["live"] = copy.deepcopy(entry.get("live", {}))
			result[name] = filtered
		return {"success": True, "timestamp": snapshot.get("timestamp"), "modules": result}

	def _get_module_states(self, arguments: list[str]) -> dict[str, Any]:
		modules = self._parse_modules(arguments)
		states = self.manager.get_module_states()
		return {"success": True, "modules": {name: states.get(name, "unavailable") for name in modules}}

	def _get_settings(self, arguments: list[str]) -> dict[str, Any]:
		self._require_arg_count(arguments, 0, 1, "GetSettings [module|all|aiEnabled]")
		if not arguments or arguments[0].lower() == "all":
			return {"success": True, "settings": self.settings.get_all()}
		if self._normalize(arguments[0]) == "aienabled":
			return {"success": True, "settings": {"aiEnabled": self.settings.is_ai_enabled()}}
		module = self._canonical_module(arguments[0])
		return {"success": True, "settings": {module: self.settings.get_module_settings(module, False)}}

	def _set_module_enabled(self, arguments: list[str]) -> dict[str, Any]:
		self._require_arg_count(arguments, 2, 2, "SetModuleEnabled <module> <true|false|Default>")
		module = self._canonical_module(arguments[0])
		value = self._parse_setting_value(arguments[1])
		changed = self.settings.update("Modules", module, value)
		return {"success": True, "command": "SetModuleEnabled", "module": module, "persisted": value, "changed": changed, "enabled": self.settings.is_module_enabled(module), "state": self.manager.get_module_states().get(module)}

	def _set_setting(self, arguments: list[str]) -> dict[str, Any]:
		if len(arguments) < 3:
			raise ValueError("Use: SetSetting <module> <setting name> <true|false|Default>")
		module = self._canonical_module(arguments[0])
		value = self._parse_setting_value(arguments[-1])
		requested = " ".join(arguments[1:-1]).strip()
		current = self.settings.get_module_settings(module, False)
		setting = {key.casefold(): key for key in current}.get(requested.casefold())
		if setting is None:
			raise ValueError(f"Unknown setting: {module}.{requested}")
		changed = self.settings.update(module, setting, value)
		return {"success": True, "command": "SetSetting", "module": module, "setting": setting, "persisted": value, "changed": changed, "current": self.settings.get_module_settings(module, False).get(setting)}

	def _parse_modules(self, arguments: list[str]) -> list[str]:
		if not arguments or (len(arguments) == 1 and arguments[0].strip().lower() == "all"):
			return list(self.manager.get_module_states())
		result = []
		for argument in arguments:
			for token in argument.split(","):
				if token.strip():
					name = self._canonical_module(token.strip())
					if name not in result:
						result.append(name)
		return result

	def _canonical_module(self, value: str) -> str:
		lookup = {name.casefold(): name for name in self.manager.get_module_states()}
		module = lookup.get(str(value).strip().casefold())
		if module is None:
			raise ValueError(f"Unknown module: {value}")
		return module

	@classmethod
	def _parse_command(cls, raw: str) -> tuple[str, list[str]]:
		tokens = shlex.split(raw)
		if not tokens:
			raise ValueError("Command is empty")
		for prefix_length in range(min(4, len(tokens)), 0, -1):
			prefix = " ".join(tokens[:prefix_length])
			command = _COMMAND_ALIASES.get(cls._normalize(prefix))
			if command is not None:
				return command, tokens[prefix_length:]
		raise ValueError(f"Unknown command: {tokens[0]}")

	@staticmethod
	def _normalize(value: str) -> str:
		return "".join(character for character in str(value).casefold() if character.isalnum())

	@staticmethod
	def _parse_setting_value(value: str):
		if str(value).strip().casefold() == "default":
			return "Default"
		return StatMonitorTerminal._parse_bool(value)

	@staticmethod
	def _parse_bool(value: str) -> bool:
		text = str(value).strip().casefold()
		if text in {"true", "on", "yes", "1"}:
			return True
		if text in {"false", "off", "no", "0"}:
			return False
		raise ValueError("Value must be true or false")

	@staticmethod
	def _require_arg_count(arguments, minimum, maximum, usage):
		if not minimum <= len(arguments) <= maximum:
			raise ValueError(f"Use: {usage}")

	@staticmethod
	def _print_result(result):
		if isinstance(result, (dict, list)):
			print(json.dumps(result, indent=2, default=str))
		else:
			print(result)

	@staticmethod
	def _print_banner():
		print("-" * 72)
		print("StatMonitor Terminal")
		print("Type Help to list commands. Type Exit to stop StatMonitor.")
		print("-" * 72)

	def _help_lines(self):
		commands = [
			"GetStats [all|module ...] [all|hardware|live]",
			"GetModuleStates [all|module ...]",
			"GetSettings [all|module|aiEnabled]",
			"GetWarnings",
			"GetServerInfo",
			"GetServerToken",
			"GetCapabilities",
			"SetModuleEnabled <module> <true|false|Default>",
			"SetSetting <module> <setting name> <true|false|Default>",
			"GetFanChannels",
			"GetFanStatus [fan_number]",
			"SetFanSpeed <fan_number> <percent>",
			"SetFanDefault <fan_number>  (100% failsafe; restart required)",
			"RestoreOwnedFans  (100% failsafe; restart required)",
			"GetFanMaps",
			"CreateFanMap <name> <hysteresis_c> <temp:percent,temp:percent,...>",
			"DeleteFanMap <name>",
			"GetFanProfiles",
			"CreateFanProfile <name> [map|Provider] [temperature_source]",
			"DeleteFanProfile <name>",
			"SetFanProfileMap <profile> <map|Provider> [temperature_source]",
			"GetFanAssignments",
			"GetFanTemperatureSensors",
			"RegisterFan <fan_number> [profile] [\"friendly name\"]",
			"UnregisterFan <fan_number>",
			"SetFanName <fan_number> <friendly name>",
			"SetFanProfile <fan_number> <profile>",
			"AssignFanMap <fan_number> <map> [temperature_source]",
			"RemoveFanMapAssignment <fan_number>",
			"SetFanMapsEnabled <true|false>",
			"GetFanMapStatus",
			"Log [duration] [all|module,module...] [--path <directory|file.jsonl>] [--interval <500ms|1s|...>]",
			"Stop Log",
			"GetLogStatus",
			"GetWiFiStatus",
			"GetWiFiNetworks",
			"GetSavedWiFiNetworks",
			"ScanWiFi",
			"ConnectWiFi <ssid> [password] [interface]",
			"DisconnectWiFi [interface]",
			"ForgetWiFiNetwork <profile> [interface]",
			"WiFiOn | WiFiOff",
			"GetBluetoothStatus",
			"GetBluetoothAdapters",
			"GetBluetoothDevices",
			"ScanBluetooth [seconds]",
			"PairBluetoothDevice <device>",
			"UnpairBluetoothDevice <device>",
			"ConnectBluetoothDevice <device>",
			"DisconnectBluetoothDevice <device>",
			"BluetoothOn | BluetoothOff",
			"GetPrivacyStatus",
			"CameraOn | CameraOff",
			"MicrophoneOn | MicrophoneOff",
			"LocationOn | LocationOff",
			"GetStorageToolDisks",
			"RefreshStorageToolDisks",
			"GetStorageToolCapabilities",
		]
		commands.extend(["GetVendorTools", "ApplyVendorTool <tool_id>"])
		commands.append("Exit")
		return commands

	def _print_help(self):
		for line in self._help_lines():
			print(line)
