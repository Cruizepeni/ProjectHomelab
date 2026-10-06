from __future__ import annotations

from typing import Any

from StatMonitorFanMaps import FAN_MAP_COMMANDS, StatMonitorFanMaps


LOW_LEVEL_FAN_COMMANDS = {
	"GetFanChannels": {"purpose": "Return controllable fan channels and current state.", "args": {}, "mutates": False},
	"GetFanStatus": {"purpose": "Return current fan state for one fan or all fans.", "args": {"fan_number": "optional 1-based fan number"}, "mutates": False},
	"SetFanSpeed": {"purpose": "Set one fan to a fixed software percentage. Taking ownership may require reboot before firmware control returns.", "args": {"fan_number": "1-based fan number", "percent": "30-100"}, "mutates": True},
	"SetFanDefault": {"purpose": "Report that reliable firmware restoration is unavailable after ownership; restart is required.", "args": {"fan_number": "1-based fan number"}, "mutates": True},
	"RestoreOwnedFans": {"purpose": "Place every owned fan at 100% failsafe. Restart is required to return firmware control.", "args": {}, "mutates": True},
}

FAN_COMMANDS = {**LOW_LEVEL_FAN_COMMANDS, **FAN_MAP_COMMANDS}


class StatMonitorFanService:
	def __init__(self, manager, driver, settings):
		self.manager = manager
		self.driver = driver
		self.maps = StatMonitorFanMaps(manager, driver, settings)

	def start_driver(self) -> None:
		self.driver.start()

	def start_maps(self) -> None:
		self.maps.start()

	def stop_maps(self) -> None:
		self.maps.stop()

	def stop_driver(self) -> None:
		self.driver.stop()

	def is_running(self) -> bool:
		return bool(self.driver.is_running())

	def handle_command(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
		if command in FAN_MAP_COMMANDS:
			return self.maps.handle_command(command, arguments)
		if command == "SetFanSpeed":
			request = dict(arguments) if isinstance(arguments, dict) else {}
			try:
				number = int(request.get("fan_number"))
			except Exception:
				number = -1
			if self.maps.is_fan_managed(number):
				return {"success": False, "error": "fan_map_active", "command": command, "message": "Remove or change the active fan-map configuration before using fixed manual speed control."}
		return self.driver.handle_command(command, arguments)
