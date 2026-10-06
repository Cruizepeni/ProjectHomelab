from __future__ import annotations

from pathlib import Path
from typing import Any


class StatMonitorStorageTools:
	def __init__(self, project_root: Path | None = None):
		self.project_root = Path(project_root) if project_root is not None else Path.cwd()

	def handle_command(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
		if command == "GetStorageToolCapabilities":
			return {"success": True, "capabilities": self.get_capabilities()}
		if command in {"GetStorageToolDisks", "RefreshStorageToolDisks"}:
			return {"success": True, "disks": [], "capabilities": self.get_capabilities()}
		return {"success": False, "error": "control_unavailable", "message": "macOS destructive Drive Tools are not implemented yet."}

	def get_capabilities(self) -> dict[str, Any]:
		return {"available": False, "platform": "MacOS", "partition_styles": [], "filesystems": [], "presets": []}
