

from __future__ import annotations

from typing import Any, Callable

from StatMonitorFanService import FAN_COMMANDS
from StatMonitorLogger import LOG_COMMANDS
from StatMonitorDeviceControls import DEVICE_COMMANDS


COMMANDS = {
	"GetCapabilities": {"purpose": "Return StatMonitor module and control capabilities.", "args": {}},
	"GetStats": {"purpose": "Return normalized StatMonitor data.", "args": {"modules": "all or module list", "data": "all|hardware|live"}},
	"GetModuleStates": {"purpose": "Return current module states.", "args": {"modules": "all or module list"}},
	"GetSettings": {"purpose": "Return normal StatMonitor settings.", "args": {"module": "all or module", "resolved": "Boolean"}},
	"SubscribeStats": {"purpose": "Subscribe to normalized telemetry updates.", "args": {"modules": "all or module list", "data": "all|hardware|live", "interval_seconds": "minimum 1"}},
	"UnsubscribeStats": {"purpose": "Remove a telemetry subscription.", "args": {"subscription_id": "opaque subscription ID"}},
	"SetModuleEnabled": {"purpose": "Enable or disable a module through settings.", "args": {"module": "module", "enabled": "true|false|Default"}},
	"SetSetting": {"purpose": "Change a normal module setting through settings.", "args": {"module": "module", "setting": "setting", "value": "true|false|Default"}},
	"GetVendorTools": {"purpose": "Return vendor-specific workarounds currently available or required.", "args": {}},
	"ApplyVendorTool": {"purpose": "Apply a detected vendor workaround after explicit confirmation.", "args": {"tool_id": "vendor tool ID", "confirmed": "must be true"}},
}

COMMANDS.update(FAN_COMMANDS)
COMMANDS.update(LOG_COMMANDS)
COMMANDS.update(DEVICE_COMMANDS)


class StatMonitorAITool:


	def __init__(self, server):
		self._server = server
		self._subscriptions: set[str] = set()

	def handle_command(self, command: str, arguments: dict[str, Any] | None = None, event_sink: Callable[[dict], None] | None = None) -> dict:
		request = dict(arguments) if isinstance(arguments, dict) else {}
		request["command"] = command
		response = self._server.handle_ai_request(request, event_sink)
		if response.get("success") and response.get("subscription_id"):
			self._subscriptions.add(response["subscription_id"])
		if command == "UnsubscribeStats" and response.get("success"):
			self._subscriptions.discard(request.get("subscription_id"))
		return response

	def stop(self) -> None:
		for subscription_id in list(self._subscriptions):
			self._server.handle_ai_request({"command": "UnsubscribeStats", "subscription_id": subscription_id})
		self._subscriptions.clear()
