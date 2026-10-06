from __future__ import annotations


class StatMonitorFanController:
	def __init__(self, motherboard):
		self.motherboard = motherboard
		self._running = False

	def start(self):
		self._running = True

	def stop(self):
		self._running = False

	def is_running(self):
		return self._running

	def handle_command(self, command, arguments=None):
		if command in ("GetFanChannels", "GetFanStatus"):
			return {"success": True, "command": command, "count": 0, "fans": [], "provider": "macOS fan control not implemented"}
		if command == "RestoreOwnedFans":
			return {"success": True, "command": command, "requested": [], "restored": [], "failed": []}
		return {"success": False, "error": "controller_unavailable", "command": command, "message": "macOS fan control provider has not been implemented yet."}
