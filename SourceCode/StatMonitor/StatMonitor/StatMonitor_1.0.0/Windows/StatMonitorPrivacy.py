from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import winreg


_CONSENT_ROOT = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
_POLICY_CAMERA = (r"SOFTWARE\Policies\Microsoft\Camera", "AllowCamera")
_POLICY_APP_PRIVACY = r"SOFTWARE\Policies\Microsoft\Windows\AppPrivacy"
_CAPABILITIES = {
	"camera": {"label": "Webcam", "consent": "webcam", "policy": _POLICY_CAMERA, "deny": 0, "allow": 1},
	"microphone": {"label": "Microphone", "consent": "microphone", "policy": (_POLICY_APP_PRIVACY, "LetAppsAccessMicrophone"), "deny": 2, "allow": 1},
	"location": {"label": "Location", "consent": "location", "policy": (_POLICY_APP_PRIVACY, "LetAppsAccessLocation"), "deny": 2, "allow": 1},
}


class StatMonitorPrivacy:
	def __init__(self, project_root: Path | None = None):
		self.project_root = Path(project_root) if project_root is not None else Path.cwd()
		self._device_cache: dict[str, Any] = {"sampled_at": 0.0, "camera": [], "microphone": []}

	def handle_command(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
		arguments = dict(arguments or {})
		if command == "GetPrivacyStatus":
			return {"success": True, "privacy": self.get_status()}
		mapping = {
			"CameraOn": ("camera", True),
			"CameraOff": ("camera", False),
			"MicrophoneOn": ("microphone", True),
			"MicrophoneOff": ("microphone", False),
			"LocationOn": ("location", True),
			"LocationOff": ("location", False),
		}
		if command in mapping:
			capability, enabled = mapping[command]
			return self.set_enabled(capability, enabled)
		return {"success": False, "error": "unknown_command", "command": command}

	def get_status(self) -> dict[str, Any]:
		devices = self._enumerate_devices()
		result = {}
		for capability in ("camera", "microphone", "location"):
			state = self._state(capability)
			if capability in devices:
				state["devices"] = devices[capability]
			result[capability] = state
		return result

	def set_enabled(self, capability: str, enabled: bool) -> dict[str, Any]:
		if capability not in _CAPABILITIES:
			return {"success": False, "error": "unknown_capability", "capability": capability}
		try:
			state_before = self._state(capability)
			if state_before.get("policy_mode") != "user_control" and self._is_admin():
				self._clear_policy_override(capability)
			self._write_consent(capability, enabled)
			state = self._state(capability)
			effective = bool(state.get("enabled")) == bool(enabled)
			return {
				"success": effective,
				"capability": capability,
				"requested_enabled": bool(enabled),
				"state": state,
				"error": None if effective else "policy_override",
				"message": None if effective else "Windows policy is overriding the requested privacy state.",
			}
		except PermissionError:
			return {"success": False, "error": "permission_denied", "message": "Windows denied the privacy setting change."}
		except OSError as error:
			return {"success": False, "error": type(error).__name__, "message": str(error)}

	def _state(self, capability: str) -> dict[str, Any]:
		definition = _CAPABILITIES[capability]
		policy_value = self._read_dword(winreg.HKEY_LOCAL_MACHINE, *definition["policy"])
		consent_value = self._read_string(winreg.HKEY_CURRENT_USER, f"{_CONSENT_ROOT}\\{definition['consent']}", "Value")
		policy_mode = "user_control"
		if policy_value == definition["deny"]:
			policy_mode = "force_deny"
		elif policy_value == definition["allow"]:
			policy_mode = "force_allow"
		if policy_mode == "force_deny":
			enabled = False
		elif policy_mode == "force_allow":
			enabled = True
		else:
			enabled = str(consent_value or "Allow").casefold() != "deny"
		return {
			"label": definition["label"],
			"enabled": bool(enabled),
			"policy_mode": policy_mode,
			"policy_value": policy_value,
			"consent_value": consent_value or "Allow",
			"is_admin": self._is_admin(),
			"available": True,
		}

	def _write_consent(self, capability: str, enabled: bool) -> None:
		definition = _CAPABILITIES[capability]
		path = f"{_CONSENT_ROOT}\\{definition['consent']}"
		with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
			winreg.SetValueEx(key, "Value", 0, winreg.REG_SZ, "Allow" if enabled else "Deny")

	def _clear_policy_override(self, capability: str) -> None:
		definition = _CAPABILITIES[capability]
		path, name = definition["policy"]
		try:
			with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as key:
				winreg.DeleteValue(key, name)
		except FileNotFoundError:
			pass

	@staticmethod
	def _read_dword(root: Any, path: str, name: str) -> int | None:
		try:
			with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
				value, _ = winreg.QueryValueEx(key, name)
				return int(value)
		except (FileNotFoundError, OSError, ValueError, TypeError):
			return None

	@staticmethod
	def _read_string(root: Any, path: str, name: str) -> str | None:
		try:
			with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
				value, _ = winreg.QueryValueEx(key, name)
				return str(value)
		except (FileNotFoundError, OSError):
			return None

	@staticmethod
	def _is_admin() -> bool:
		try:
			return bool(ctypes.windll.shell32.IsUserAnAdmin())
		except Exception:
			return False

	def _enumerate_devices(self) -> dict[str, list[dict[str, Any]]]:
		now = time.monotonic()
		if now - float(self._device_cache.get("sampled_at", 0.0)) < 10.0:
			return {"camera": list(self._device_cache.get("camera", [])), "microphone": list(self._device_cache.get("microphone", []))}
		script = r'''
$camera = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.Class -in @('Camera','Image') } | ForEach-Object { [pscustomobject]@{ name=$_.FriendlyName; status=$_.Status; id=$_.InstanceId } })
$microphone = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.Class -eq 'AudioEndpoint' -and $_.FriendlyName -match '(?i)microphone|\bmic\b|input' } | ForEach-Object { [pscustomobject]@{ name=$_.FriendlyName; status=$_.Status; id=$_.InstanceId } })
[pscustomobject]@{ camera=$camera; microphone=$microphone } | ConvertTo-Json -Depth 4 -Compress
'''
		try:
			completed = subprocess.run(
				["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"],
				input=script,
				capture_output=True,
				text=True,
				timeout=8,
				check=False,
				creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
			)
			payload = json.loads(completed.stdout.strip()) if completed.returncode == 0 and completed.stdout.strip() else {}
		except Exception:
			payload = {}
		camera = payload.get("camera", []) if isinstance(payload, dict) else []
		microphone = payload.get("microphone", []) if isinstance(payload, dict) else []
		if isinstance(camera, dict):
			camera = [camera]
		if isinstance(microphone, dict):
			microphone = [microphone]
		self._device_cache = {
			"sampled_at": now,
			"camera": [item for item in camera if isinstance(item, dict)],
			"microphone": [item for item in microphone if isinstance(item, dict)],
		}
		return {"camera": list(self._device_cache["camera"]), "microphone": list(self._device_cache["microphone"])}
