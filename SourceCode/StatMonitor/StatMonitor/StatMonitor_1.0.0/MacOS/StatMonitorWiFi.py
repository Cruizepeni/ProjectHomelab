from __future__ import annotations

import copy
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable

from StatMonitorDeviceControls import WIFI_COMMANDS


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
		self._settings = {}
		self._hardware = {}
		self._live = {}
		self._warnings = []
		self._running = False
		self._thread = None
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
			return {"hardware": copy.deepcopy(self._hardware), "live": copy.deepcopy(self._live), "provider": {"name": "macOS networksetup", "status": "partial"}, "warnings": copy.deepcopy(self._warnings)}

	def get_metric_snapshot(self):
		return self.get_latest()

	def handle_command(self, command: Any, arguments: dict[str, Any] | None = None) -> dict:
		arguments = dict(arguments or {})
		if command not in WIFI_COMMANDS:
			return {"success": False, "error": "unknown_command", "command": command}
		if not shutil.which("networksetup"):
			return {"success": False, "error": "provider_unavailable", "command": command}
		interfaces = self._interfaces()
		interface = str(arguments.get("interface_id") or arguments.get("interface") or (interfaces[0]["interface_id"] if interfaces else "")).strip()
		if command == "GetWiFiStatus":
			self._refresh()
			latest = self.get_latest()
			return {"success": True, "command": command, "hardware": latest["hardware"], "live": latest["live"]}
		if command == "GetSavedWiFiNetworks":
			return {"success": True, "command": command, "profiles": self._profiles(interface)}
		if command in {"GetWiFiNetworks", "ScanWiFi"}:
			return {"success": False, "error": "scan_provider_pending", "command": command, "networks": [], "message": "A stable native macOS scan provider has not been implemented yet."}
		if command == "ConnectWiFi":
			ssid = str(arguments.get("ssid") or arguments.get("profile") or "").strip()
			if not ssid:
				raise ValueError("ConnectWiFi requires ssid or profile")
			args = ["networksetup", "-setairportnetwork", interface, ssid]
			if arguments.get("password") is not None:
				args.append(str(arguments.get("password")))
			result = self._run(args)
			self._refresh()
			return {"success": result.returncode == 0, "command": command, "output": result.stdout.strip(), "error_output": result.stderr.strip()}
		if command == "DisconnectWiFi":
			return {"success": False, "error": "disconnect_provider_pending", "command": command, "message": "macOS does not expose a reliable generic disconnect-only networksetup operation without changing radio state."}
		if command == "ForgetWiFiNetwork":
			profile = str(arguments.get("profile") or arguments.get("ssid") or "").strip()
			if not profile:
				raise ValueError("ForgetWiFiNetwork requires profile or ssid")
			result = self._run(["networksetup", "-removepreferredwirelessnetwork", interface, profile])
			self._refresh()
			return {"success": result.returncode == 0, "command": command, "profile": profile, "output": result.stdout.strip(), "error_output": result.stderr.strip()}
		if command in {"WiFiOn", "WiFiOff"}:
			state = "on" if command == "WiFiOn" else "off"
			result = self._run(["networksetup", "-setairportpower", interface, state])
			self._refresh()
			return {"success": result.returncode == 0, "command": command, "state": state, "error_output": result.stderr.strip()}
		return {"success": False, "error": "unknown_command", "command": command}

	def _loop(self):
		while not self._stop_event.wait(5.0):
			self._refresh()

	def _refresh(self):
		try:
			interfaces = self._interfaces()
			hardware = {"adapters": interfaces}
			live = {"connections": []}
			for item in interfaces:
				interface = item["interface_id"]
				current = self._run(["networksetup", "-getairportnetwork", interface])
				match = re.search(r"Current Wi-Fi Network:\s*(.+)", current.stdout)
				if match:
					live["connections"].append({"interface_id": interface, "ssid": match.group(1).strip()})
			if self._settings.get("Show Saved Networks"):
				hardware["saved_networks"] = [profile for item in interfaces for profile in self._profiles(item["interface_id"])]
			warnings = []
		except Exception as error:
			hardware, live, warnings = {}, {}, [{"code": "wifi_provider_error", "message": str(error)}]
		with self._lock:
			self._hardware, self._live, self._warnings = hardware, live, warnings
		self._notify()

	def _interfaces(self):
		result = self._run(["networksetup", "-listallhardwareports"])
		rows = []
		blocks = re.split(r"\n\s*\n", result.stdout)
		for block in blocks:
			if not re.search(r"Hardware Port:\s*(Wi-Fi|AirPort)", block, re.I):
				continue
			device = re.search(r"Device:\s*(\S+)", block)
			if device:
				interface = device.group(1)
				power = self._run(["networksetup", "-getairportpower", interface])
				rows.append({"interface_id": interface, "name": "Wi-Fi", "state": "on" if re.search(r":\s*On", power.stdout, re.I) else "off"})
		return rows

	def _profiles(self, interface):
		if not interface:
			return []
		result = self._run(["networksetup", "-listpreferredwirelessnetworks", interface])
		lines = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
		return [{"interface_id": interface, "profile_name": line} for line in lines]

	@staticmethod
	def _run(args):
		return subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)

	def _notify(self):
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				pass
