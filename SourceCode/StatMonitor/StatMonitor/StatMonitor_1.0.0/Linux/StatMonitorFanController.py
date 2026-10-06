from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from Linux.StatMonitorLinuxCommon import hwmon_devices, read_number, read_text


class StatMonitorFanController:
	def __init__(self, motherboard):
		self.motherboard = motherboard
		self._running = False
		self._lock = threading.RLock()
		self._owned: set[str] = set()

	def start(self):
		with self._lock:
			self._running = True

	def stop(self):
		with self._lock:
			if self._running:
				self._set_all_owned_failsafe()
			self._running = False

	def is_running(self):
		with self._lock:
			return self._running

	def handle_command(self, command, arguments=None):
		arguments = dict(arguments or {})
		if command == "GetFanChannels":
			fans = self.get_channels()
			return {"success": True, "command": command, "count": len(fans), "fans": fans, "provider": "Linux hwmon PWM"}
		if command == "GetFanStatus":
			fans = self.get_channels()
			value = arguments.get("fan_number")
			if value is None:
				return {"success": True, "command": command, "count": len(fans), "fans": fans}
			try:
				number = int(value)
			except Exception:
				return {"success": False, "error": "invalid_fan_number"}
			fan = next((item for item in fans if item.get("fan_number") == number), None)
			return {"success": fan is not None, "command": command, "fan": fan, "error": None if fan else "fan_not_found"}
		if command == "SetFanSpeed":
			return self.set_fan_percent(arguments.get("fan_number"), arguments.get("percent"))
		if command == "SetFanDefault":
			return {"success": False, "error": "restart_required", "command": command, "message": "Reliable firmware fan-control restoration is not assumed after StatMonitor takes ownership. Restart to return control."}
		if command == "RestoreOwnedFans":
			return self._set_all_owned_failsafe()
		return {"success": False, "error": "unknown_command", "command": command}

	def get_channels(self):
		channels = []
		for device in hwmon_devices():
			path = device["path"]
			for pwm_file in sorted(path.glob("pwm[0-9]*")):
				name = pwm_file.name
				if not name[3:].isdigit():
					continue
				index = int(name[3:])
				rpm_file = path / f"fan{index}_input"
				enable_file = path / f"pwm{index}_enable"
				label = read_text(path / f"fan{index}_label") or read_text(path / f"pwm{index}_label") or f"{device['name']} Fan {index}"
				identifier = f"linux-hwmon::{device['device_realpath']}::{device['name']}::pwm{index}"
				pwm = read_number(pwm_file)
				rpm = read_number(rpm_file)
				writable = os.access(pwm_file, os.W_OK) and (not enable_file.exists() or os.access(enable_file, os.W_OK))
				channels.append({
					"fan_number": len(channels) + 1,
					"fan_name": label,
					"control_name": f"pwm{index}",
					"hardware": device["name"],
					"control_identifier": identifier,
					"rpm": round(rpm, 1) if rpm is not None else None,
					"output_percent": round(max(0.0, min(100.0, pwm / 255.0 * 100.0)), 1) if pwm is not None else None,
					"owned": identifier in self._owned,
					"control_available": writable,
					"requires_privilege": not writable,
					"pwm_path": str(pwm_file),
				})
		return channels

	def set_fan_percent(self, fan_number: Any, percent: Any):
		with self._lock:
			if not self._running:
				return {"success": False, "error": "controller_not_running"}
			try:
				number = int(fan_number)
				requested = float(percent)
			except Exception:
				return {"success": False, "error": "invalid_request"}
			if requested < 30.0 or requested > 100.0:
				return {"success": False, "error": "invalid_percent", "message": "Fan speed must be 30-100%."}
			fan = next((item for item in self.get_channels() if item.get("fan_number") == number), None)
			if not fan:
				return {"success": False, "error": "fan_not_found"}
			pwm_file = Path(fan["pwm_path"])
			enable_file = pwm_file.with_name(pwm_file.name + "_enable")
			try:
				if enable_file.exists():
					enable_file.write_text("1\n", encoding="utf-8")
				value = int(round(requested / 100.0 * 255.0))
				pwm_file.write_text(f"{value}\n", encoding="utf-8")
			except PermissionError:
				return {"success": False, "error": "permission_denied", "message": "Linux fan control needs write access to the hwmon PWM channel. Configure udev/polkit permissions or run with suitable privileges."}
			except OSError as error:
				return {"success": False, "error": type(error).__name__, "message": str(error)}
			self._owned.add(fan["control_identifier"])
			updated = next((item for item in self.get_channels() if item.get("control_identifier") == fan["control_identifier"]), fan)
			return {"success": True, "command": "SetFanSpeed", "fan": updated, "requested_percent": round(requested, 1)}

	def _set_all_owned_failsafe(self):
		requested = []
		failed = []
		for fan in self.get_channels():
			if fan.get("control_identifier") not in self._owned:
				continue
			requested.append(fan.get("fan_number"))
			try:
				Path(fan["pwm_path"]).write_text("255\n", encoding="utf-8")
			except Exception as error:
				failed.append({"fan_number": fan.get("fan_number"), "error": str(error)})
		return {"success": not failed, "command": "RestoreOwnedFans", "requested": requested, "restored": [], "failsafe": requested, "failed": failed, "restart_required": bool(requested)}
