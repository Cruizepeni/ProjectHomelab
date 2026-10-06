from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from Linux.StatMonitorLinuxCommon import command_available, read_text, root_path, run


class StatMonitorPrivacy:
	def __init__(self, project_root: Path | None = None):
		self.project_root = Path(project_root) if project_root is not None else Path.cwd()

	def handle_command(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
		if command == "GetPrivacyStatus":
			return {"success": True, "privacy": self.get_status()}
		mapping = {"CameraOn": ("camera", True), "CameraOff": ("camera", False), "MicrophoneOn": ("microphone", True), "MicrophoneOff": ("microphone", False), "LocationOn": ("location", True), "LocationOff": ("location", False)}
		if command not in mapping:
			return {"success": False, "error": "unknown_command", "command": command}
		capability, enabled = mapping[command]
		return self.set_enabled(capability, enabled)

	def get_status(self) -> dict[str, Any]:
		camera_devices = self._cameras()
		microphones = self._microphones()
		camera_enabled = any(item.get("enabled") for item in camera_devices) if camera_devices else None
		microphone_enabled = self._microphone_enabled()
		location_enabled = self._location_enabled()
		return {
			"camera": {"label": "Webcam", "enabled": camera_enabled, "available": bool(camera_devices), "policy_mode": "device_control", "devices": camera_devices},
			"microphone": {"label": "Microphone", "enabled": microphone_enabled, "available": bool(microphones) or microphone_enabled is not None, "policy_mode": "audio_server", "devices": microphones},
			"location": {"label": "Location", "enabled": location_enabled, "available": command_available("systemctl"), "policy_mode": "GeoClue service", "devices": []},
		}

	def set_enabled(self, capability: str, enabled: bool) -> dict[str, Any]:
		if capability == "camera":
			return self._set_cameras(enabled)
		if capability == "microphone":
			return self._set_microphone(enabled)
		if capability == "location":
			return self._set_location(enabled)
		return {"success": False, "error": "unknown_capability"}

	def _cameras(self):
		base = root_path("/sys/class/video4linux")
		result = []
		for node in sorted(base.glob("video*")) if base.exists() else []:
			name = read_text(node / "name") or node.name
			authorized = self._usb_authorized(node)
			result.append({"name": name, "id": str(node), "device": f"/dev/{node.name}", "enabled": None if authorized is None else read_text(authorized) != "0", "control_path": str(authorized) if authorized else None})
		return result

	def _usb_authorized(self, node):
		try:
			current = node.resolve()
		except Exception:
			return None
		for parent in [current, *current.parents]:
			candidate = parent / "authorized"
			if candidate.exists():
				return candidate
			if parent == root_path("/sys"):
				break
		return None

	def _set_cameras(self, enabled):
		devices = self._cameras()
		controllable = [item for item in devices if item.get("control_path")]
		if not controllable:
			return {"success": False, "error": "control_unavailable", "message": "No controllable USB webcam authorization switch was exposed by Linux."}
		failed = []
		value = "1\n" if enabled else "0\n"
		for item in controllable:
			path = Path(item["control_path"])
			try:
				path.write_text(value, encoding="utf-8")
				continue
			except PermissionError:
				pass
			except Exception as error:
				failed.append({"device": item.get("name"), "error": str(error)})
				continue
			if command_available("pkexec") and command_available("tee"):
				completed = run(["pkexec", "tee", str(path)], 30, input_text=value)
				if completed.returncode == 0:
					continue
				failed.append({"device": item.get("name"), "error": completed.stderr.strip() or "Administrative authorization failed."})
			else:
				failed.append({"device": item.get("name"), "error": "Write permission is required and pkexec is unavailable."})
		return {"success": not failed, "capability": "camera", "requested_enabled": enabled, "failed": failed, "state": self.get_status().get("camera")}

	def _microphones(self):
		if command_available("pactl"):
			completed = run(["pactl", "list", "short", "sources"], 5)
			return [{"id": parts[0], "name": parts[1], "status": parts[-1] if parts else None} for line in completed.stdout.splitlines() if (parts := line.split("\t")) and len(parts) >= 2]
		return []

	def _microphone_enabled(self):
		if command_available("wpctl"):
			completed = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"], 5)
			if completed.returncode == 0:
				return "MUTED" not in completed.stdout.upper()
		if command_available("pactl"):
			completed = run(["pactl", "get-source-mute", "@DEFAULT_SOURCE@"], 5)
			if completed.returncode == 0:
				return "yes" not in completed.stdout.casefold()
		return None

	def _set_microphone(self, enabled):
		if command_available("wpctl"):
			completed = run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0" if enabled else "1"], 5)
		elif command_available("pactl"):
			completed = run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "0" if enabled else "1"], 5)
		else:
			return {"success": False, "error": "provider_unavailable", "message": "PipeWire wpctl or PulseAudio pactl is required for microphone control."}
		return {"success": completed.returncode == 0, "capability": "microphone", "requested_enabled": enabled, "message": completed.stderr.strip() or None, "state": self.get_status().get("microphone")}

	def _location_enabled(self):
		if not command_available("systemctl"):
			return None
		for service in ("geoclue.service", "geoclue-demo-agent.service"):
			completed = run(["systemctl", "is-active", service], 5)
			if completed.returncode == 0:
				return True
		return False

	def _set_location(self, enabled):
		if not command_available("systemctl"):
			return {"success": False, "error": "provider_unavailable", "message": "systemctl is unavailable."}
		action = "start" if enabled else "stop"
		completed = run(["systemctl", action, "geoclue.service"], 10)
		if completed.returncode != 0 and command_available("pkexec"):
			completed = run(["pkexec", "systemctl", action, "geoclue.service"], 30)
		return {"success": completed.returncode == 0, "capability": "location", "requested_enabled": enabled, "message": completed.stderr.strip() or None, "state": self.get_status().get("location")}
