from __future__ import annotations

import copy
import shutil
import threading
import time
from typing import Any, Callable

from StatMonitorDeviceControls import WIFI_COMMANDS
from Linux.StatMonitorLinuxCommon import run


_SETTINGS = (
	"Show WiFi Adapter",
	"Show Current Network",
	"Show Available Networks",
	"Show Saved Networks",
	"Show Signal Strength",
	"Show Link Speed",
)


class StatMonitorWiFi:
	def __init__(self):
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._hardware: dict[str, Any] = {}
		self._live: dict[str, Any] = {}
		self._warnings: list[dict[str, Any]] = []
		self._running = False
		self._thread: threading.Thread | None = None
		self._stop_event = threading.Event()

	def subscribe(self, listener):
		with self._lock:
			if listener not in self._listeners:
				self._listeners.append(listener)

	def unsubscribe(self, listener):
		with self._lock:
			if listener in self._listeners:
				self._listeners.remove(listener)

	def update_settings(self, settings):
		with self._lock:
			self._settings = {key: bool((settings or {}).get(key, False)) for key in _SETTINGS}
		if self._running:
			self._refresh()

	def start(self):
		with self._lock:
			if self._running:
				return
			self._running = True
			self._stop_event.clear()
		self._refresh()
		self._thread = threading.Thread(target=self._loop, name="StatMonitorWiFi", daemon=True)
		self._thread.start()

	def stop(self):
		with self._lock:
			self._running = False
			self._stop_event.set()
			thread = self._thread
			self._thread = None
		if thread and thread is not threading.current_thread():
			thread.join(timeout=5)

	def is_running(self):
		with self._lock:
			return self._running

	def get_latest(self):
		with self._lock:
			return {"hardware": copy.deepcopy(self._hardware), "live": copy.deepcopy(self._live), "provider": {"name": "NetworkManager nmcli", "status": "available" if shutil.which("nmcli") else "unavailable"}, "warnings": copy.deepcopy(self._warnings)}

	def get_metric_snapshot(self):
		return self.get_latest()

	def handle_command(self, command: Any, arguments: dict[str, Any] | None = None) -> dict:
		arguments = dict(arguments or {})
		if command not in WIFI_COMMANDS:
			return {"success": False, "error": "unknown_command", "command": command}
		if not shutil.which("nmcli"):
			return {"success": False, "error": "provider_unavailable", "command": command, "message": "NetworkManager nmcli is unavailable"}
		if command == "GetWiFiStatus":
			self._refresh()
			latest = self.get_latest()
			return {"success": True, "command": command, "hardware": latest["hardware"], "live": latest["live"]}
		if command == "GetWiFiNetworks":
			return {"success": True, "command": command, "networks": self._networks()}
		if command == "GetSavedWiFiNetworks":
			return {"success": True, "command": command, "profiles": self._profiles()}
		if command == "ScanWiFi":
			result = self._run(["nmcli", "device", "wifi", "rescan"])
			time.sleep(0.4)
			self._refresh()
			return {"success": result.returncode == 0, "command": command, "networks": self._networks(), "error_output": result.stderr.strip()}
		if command == "ConnectWiFi":
			profile = str(arguments.get("profile") or "").strip()
			ssid = str(arguments.get("ssid") or "").strip()
			interface = str(arguments.get("interface_id") or arguments.get("interface") or "").strip()
			if profile:
				args = ["nmcli", "connection", "up", "id", profile]
				if interface:
					args += ["ifname", interface]
			elif ssid:
				args = ["nmcli", "device", "wifi", "connect", ssid]
				password = arguments.get("password")
				if password is not None:
					args += ["password", str(password)]
				if interface:
					args += ["ifname", interface]
			else:
				return {"success": False, "error": "ssid_or_profile_required", "command": command}
			result = self._run(args, 45)
			self._refresh()
			return {"success": result.returncode == 0, "command": command, "output": result.stdout.strip(), "error_output": result.stderr.strip()}
		if command == "DisconnectWiFi":
			requested = str(arguments.get("interface_id") or arguments.get("interface") or "").strip()
			interfaces = [requested] if requested else [item["interface_id"] for item in self._adapters()]
			results = []
			for interface in interfaces:
				result = self._run(["nmcli", "device", "disconnect", interface])
				results.append({"interface_id": interface, "status": result.returncode, "output": result.stdout.strip(), "error_output": result.stderr.strip()})
			self._refresh()
			return {"success": bool(results) and all(item["status"] == 0 for item in results), "command": command, "interfaces": results}
		if command == "ForgetWiFiNetwork":
			profile = str(arguments.get("profile") or arguments.get("ssid") or "").strip()
			if not profile:
				return {"success": False, "error": "profile_required", "command": command}
			result = self._run(["nmcli", "connection", "delete", "id", profile])
			self._refresh()
			return {"success": result.returncode == 0, "command": command, "profile": profile, "output": result.stdout.strip(), "error_output": result.stderr.strip()}
		if command in {"WiFiOn", "WiFiOff"}:
			state = "on" if command == "WiFiOn" else "off"
			result = self._run(["nmcli", "radio", "wifi", state])
			self._refresh()
			return {"success": result.returncode == 0, "command": command, "state": state, "error_output": result.stderr.strip()}
		return {"success": False, "error": "unknown_command", "command": command}

	def _loop(self):
		while not self._stop_event.wait(3.0):
			self._refresh()

	def _refresh(self):
		try:
			settings = dict(self._settings)
			hardware, live = {}, {}
			adapters = self._adapters()
			networks = self._networks()
			profiles = self._profiles()
			if settings.get("Show WiFi Adapter"):
				hardware["adapters"] = adapters
			if settings.get("Show Available Networks"):
				hardware["available_networks"] = networks
			if settings.get("Show Saved Networks"):
				hardware["saved_networks"] = profiles
			if settings.get("Show Current Network"):
				live["connections"] = [item for item in networks if item.get("connected")]
			warnings = []
		except Exception as error:
			hardware, live, warnings = {}, {}, [{"code": "wifi_provider_error", "message": str(error)}]
		with self._lock:
			self._hardware, self._live, self._warnings = hardware, live, warnings
		self._notify()

	def _adapters(self):
		result = self._run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
		adapters = []
		for line in result.stdout.splitlines():
			parts = self._split(line, 4)
			if len(parts) >= 3 and parts[1] == "wifi":
				adapters.append({"interface_id": parts[0], "interface_name": parts[0], "name": parts[0], "state": parts[2], "connection": parts[3] if len(parts) > 3 and parts[3] != "--" else None})
		return adapters

	def _networks(self):
		fields = "IN-USE,SSID,SIGNAL,SECURITY,DEVICE,RATE"
		result = self._run(["nmcli", "-t", "-f", fields, "device", "wifi", "list"])
		profiles = {str(item.get("profile_name") or "").casefold() for item in self._profiles()}
		networks = []
		for line in result.stdout.splitlines():
			parts = self._split(line, 6)
			if len(parts) < 5 or not parts[1]:
				continue
			security = parts[3] or None
			rate = _rate_bps(parts[5] if len(parts) > 5 else None)
			networks.append({"connected": parts[0].strip() == "*", "ssid": parts[1], "profile_name": parts[1] if parts[1].casefold() in profiles else None, "has_profile": parts[1].casefold() in profiles, "signal_quality_percent": self._int(parts[2]), "security": security, "security_enabled": bool(security and security != "--"), "authentication": security, "cipher": security, "interface_id": parts[4], "interface_name": parts[4], "receive_rate_bps": rate, "transmit_rate_bps": rate})
		return networks

	def _profiles(self):
		result = self._run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show"])
		profiles = []
		for line in result.stdout.splitlines():
			parts = self._split(line, 3)
			if len(parts) >= 2 and parts[1] == "802-11-wireless":
				profiles.append({"profile_name": parts[0], "interface_id": parts[2] if len(parts) > 2 and parts[2] != "--" else None, "interface_name": parts[2] if len(parts) > 2 and parts[2] != "--" else None})
		return profiles

	@staticmethod
	def _run(args, timeout=20):
		return run(args, timeout)

	@staticmethod
	def _split(line: str, maximum: int):
		parts, current, escaped = [], [], False
		for character in line:
			if escaped:
				current.append(character)
				escaped = False
			elif character == "\\":
				escaped = True
			elif character == ":" and len(parts) < maximum - 1:
				parts.append("".join(current))
				current = []
			else:
				current.append(character)
		parts.append("".join(current))
		return parts

	@staticmethod
	def _int(value):
		try:
			return int(value)
		except Exception:
			return None

	def _notify(self):
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				pass


def _rate_bps(value):
	if not value:
		return None
	text = str(value).strip().casefold().replace(" ", "")
	try:
		if text.endswith("mbit/s"):
			return float(text[:-6]) * 1_000_000
		if text.endswith("mb/s"):
			return float(text[:-4]) * 1_000_000
		if text.endswith("gbit/s"):
			return float(text[:-6]) * 1_000_000_000
		return float(text)
	except Exception:
		return None
