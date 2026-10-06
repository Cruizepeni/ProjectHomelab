from __future__ import annotations

import json
import subprocess
from typing import Any

from StatMonitorDeviceControls import BLUETOOTH_COMMANDS

from StatMonitorModuleBase import PollingModule


class StatMonitorBluetooth(PollingModule):
	interval_seconds = 5.0


	def handle_command(self, command: Any, arguments: dict[str, Any] | None = None) -> dict:
		arguments = dict(arguments or {})
		if command not in BLUETOOTH_COMMANDS:
			return {"success": False, "error": "unknown_command", "command": command}
		if command in {"GetBluetoothStatus", "GetBluetoothAdapters", "GetBluetoothDevices"}:
			latest = self.get_latest()
			if command == "GetBluetoothAdapters":
				return {"success": True, "command": command, "adapters": latest.get("hardware", {}).get("adapters", [])}
			if command == "GetBluetoothDevices":
				return {"success": True, "command": command, "devices": latest.get("hardware", {}).get("devices", [])}
			return {"success": True, "command": command, "hardware": latest.get("hardware", {}), "live": latest.get("live", {})}
		return {"success": False, "error": "control_provider_pending", "command": command, "message": "Native macOS Bluetooth control provider is not implemented yet."}

	def collect(self):
		devices = []
		adapters = []
		try:
			completed = subprocess.run(["system_profiler", "-json", "SPBluetoothDataType"], capture_output=True, text=True, timeout=10, check=False)
			data = json.loads(completed.stdout or "{}")
			for root in data.get("SPBluetoothDataType", []) or []:
				controller = root.get("controller_properties") or root.get("controllerProperties")
				if isinstance(controller, dict):
					adapters.append(controller)
				for key in ("device_connected", "device_not_connected"):
					groups = root.get(key) or []
					if isinstance(groups, dict):
						groups = [groups]
					for group in groups:
						if not isinstance(group, dict):
							continue
						for name, info in group.items():
							entry = {"name": name, "connected": key == "device_connected"}
							if isinstance(info, dict):
								entry.update(info)
							devices.append(entry)
		except Exception:
			pass
		return {"adapters": adapters, "devices": devices}, {}, {"name": "system_profiler", "status": "partial"}, []
