from __future__ import annotations

import re
import shutil
from typing import Any

from StatMonitorDeviceControls import BLUETOOTH_COMMANDS
from StatMonitorModuleBase import PollingModule
from Linux.StatMonitorLinuxCommon import run


class StatMonitorBluetooth(PollingModule):
	interval_seconds = 4.0

	def handle_command(self, command: Any, arguments: dict[str, Any] | None = None) -> dict:
		arguments = dict(arguments or {})
		if command not in BLUETOOTH_COMMANDS:
			return {"success": False, "error": "unknown_command", "command": command}
		if not shutil.which("bluetoothctl"):
			return {"success": False, "error": "provider_unavailable", "command": command, "message": "BlueZ bluetoothctl is unavailable"}
		if command == "GetBluetoothStatus":
			self._collect_safe()
			latest = self.get_latest()
			return {"success": True, "command": command, "hardware": latest.get("hardware", {}), "live": latest.get("live", {})}
		if command == "GetBluetoothAdapters":
			return {"success": True, "command": command, "adapters": self._adapters()}
		if command in {"GetBluetoothDevices", "ScanBluetooth"}:
			if command == "ScanBluetooth":
				seconds = max(1, min(30, int(arguments.get("seconds", 5))))
				run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"], seconds + 5)
			devices = self._devices()
			self._collect_safe()
			return {"success": True, "command": command, "devices": devices}
		device = str(arguments.get("device") or arguments.get("device_id") or arguments.get("address") or "").strip()
		if command not in {"BluetoothOn", "BluetoothOff"} and not device:
			return {"success": False, "error": "device_required", "command": command}
		address = self._resolve_device(device) if device else None
		mapping = {
			"PairBluetoothDevice": ["bluetoothctl", "pair", address],
			"UnpairBluetoothDevice": ["bluetoothctl", "remove", address],
			"ConnectBluetoothDevice": ["bluetoothctl", "connect", address],
			"DisconnectBluetoothDevice": ["bluetoothctl", "disconnect", address],
			"BluetoothOn": ["bluetoothctl", "power", "on"],
			"BluetoothOff": ["bluetoothctl", "power", "off"],
		}
		completed = run(mapping[command], 30)
		self._collect_safe()
		return {"success": completed.returncode == 0, "command": command, "output": completed.stdout.strip(), "error_output": completed.stderr.strip()}

	def collect(self):
		if not shutil.which("bluetoothctl"):
			return {"adapter": {}, "devices": []}, {"adapter": {}, "devices": []}, {"name": "BlueZ bluetoothctl", "status": "unavailable"}, []
		adapters = self._adapters()
		adapter = adapters[0] if adapters else {}
		devices = self._devices()
		hardware_devices = [{key: item.get(key) for key in ("device_id", "address", "name", "device_type", "transports", "paired", "trusted", "blocked")} | {"battery_percent": item.get("battery_percent")} for item in devices]
		live_devices = [{"device_id": item.get("device_id"), "paired": item.get("paired"), "connected": item.get("connected"), "battery_percent": item.get("battery_percent"), "signal_strength_dbm": item.get("signal_strength_dbm")} for item in devices]
		hardware = {"adapter": {"name": adapter.get("name"), "address": adapter.get("address"), "classic_supported": True, "low_energy_supported": True}, "adapters": adapters, "devices": hardware_devices}
		live = {"adapter": {"state": "on" if adapter.get("powered") else "off" if adapter else "unavailable"}, "devices": live_devices}
		return hardware, live, {"name": "BlueZ bluetoothctl", "status": "available"}, []

	def _adapters(self):
		completed = run(["bluetoothctl", "list"], 5)
		result = []
		for line in completed.stdout.splitlines():
			match = re.match(r"Controller\s+([0-9A-Fa-f:]+)\s+(.+?)(?:\s+\[default\])?$", line.strip())
			if not match:
				continue
			address, name = match.groups()
			info = run(["bluetoothctl", "show", address], 5).stdout
			result.append({"adapter_id": address, "address": address, "name": name.strip(), "powered": _yes(info, "Powered"), "discoverable": _yes(info, "Discoverable"), "pairable": _yes(info, "Pairable")})
		if not result:
			info = run(["bluetoothctl", "show"], 5).stdout
			match = re.search(r"Controller\s+([0-9A-Fa-f:]+)\s+(.+)", info)
			if match:
				result.append({"adapter_id": match.group(1), "address": match.group(1), "name": match.group(2).strip(), "powered": _yes(info, "Powered"), "discoverable": _yes(info, "Discoverable"), "pairable": _yes(info, "Pairable")})
		return result

	def _devices(self):
		completed = run(["bluetoothctl", "devices"], 5)
		devices = []
		for line in completed.stdout.splitlines():
			match = re.match(r"Device\s+([0-9A-Fa-f:]+)\s+(.+)", line.strip())
			if not match:
				continue
			address, fallback_name = match.groups()
			info = run(["bluetoothctl", "info", address], 5).stdout
			name = _field(info, "Name") or _field(info, "Alias") or fallback_name
			icon = _field(info, "Icon")
			type_name = _device_type(icon, _field(info, "Class"))
			battery = _battery(info)
			rssi = _int(_field(info, "RSSI"))
			devices.append({"device_id": address, "address": address, "name": name, "device_type": type_name, "transports": ["bluetooth"], "paired": _yes(info, "Paired"), "trusted": _yes(info, "Trusted"), "blocked": _yes(info, "Blocked"), "connected": _yes(info, "Connected"), "battery_percent": battery, "signal_strength_dbm": rssi})
		return devices

	def _resolve_device(self, value):
		needle = value.casefold()
		for item in self._devices():
			if str(item.get("address", "")).casefold() == needle or str(item.get("name", "")).casefold() == needle or str(item.get("device_id", "")).casefold() == needle:
				return str(item.get("address"))
		return value


def _field(text, name):
	match = re.search(rf"^\s*{re.escape(name)}:\s*(.+)$", text, re.MULTILINE | re.I)
	return match.group(1).strip() if match else None


def _yes(text, name):
	value = _field(text, name)
	return str(value or "").casefold() == "yes"


def _int(value):
	try:
		return int(str(value).strip())
	except Exception:
		return None


def _battery(text):
	value = _field(text, "Battery Percentage")
	if not value:
		match = re.search(r"Battery Percentage:\s*0x[0-9a-f]+\s*\(([0-9]+)\)", text, re.I)
		return int(match.group(1)) if match else None
	match = re.search(r"\(([0-9]+)\)", value)
	if match:
		return int(match.group(1))
	return _int(value)


def _device_type(icon, class_value):
	text = str(icon or "").casefold()
	for token, label in (("audio", "Audio"), ("headset", "Headset"), ("input", "Input Device"), ("keyboard", "Keyboard"), ("mouse", "Mouse"), ("phone", "Phone"), ("computer", "Computer"), ("camera", "Camera")):
		if token in text:
			return label
	return "Bluetooth Device"
