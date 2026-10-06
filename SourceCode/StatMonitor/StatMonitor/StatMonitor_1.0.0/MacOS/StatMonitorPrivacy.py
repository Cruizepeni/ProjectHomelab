from __future__ import annotations

from pathlib import Path
from typing import Any


class StatMonitorPrivacy:
	def __init__(self, project_root: Path | None = None):
		self.project_root = Path(project_root) if project_root is not None else Path.cwd()

	def handle_command(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
		if command == "GetPrivacyStatus":
			return {"success": True, "privacy": self.get_status()}
		return {"success": False, "error": "control_unavailable", "message": "macOS privacy switching is not yet available for this provider."}

	def get_status(self) -> dict[str, Any]:
		return {name: {"label": label, "enabled": None, "available": False, "policy_mode": "unsupported", "devices": []} for name, label in (("camera", "Webcam"), ("microphone", "Microphone"), ("location", "Location"))}
