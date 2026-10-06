from __future__ import annotations

import copy
import importlib
from typing import Any


class StatMonitorVendorTools:
	def __init__(self, platform_package: str):
		self.platform_package = platform_package
		self._tools = self._load_tools()

	def _load_tools(self) -> dict[str, dict[str, Any]]:
		try:
			module = importlib.import_module(f"{self.platform_package}.VendorTools")
		except ModuleNotFoundError:
			return {}
		result = {}
		for raw in getattr(module, "TOOLS", ()):
			if not isinstance(raw, dict):
				continue
			identifier = str(raw.get("id") or "").strip()
			if identifier:
				result[identifier] = dict(raw)
		return result

	def get_status(self) -> list[dict[str, Any]]:
		result = []
		for identifier in sorted(self._tools):
			tool = self._tools[identifier]
			detection = self._detect(tool)
			result.append({
				"id": identifier,
				"vendor": tool.get("vendor"),
				"name": tool.get("name"),
				"description": tool.get("description"),
				"action": tool.get("action"),
				"restore": tool.get("restore"),
				"confirmation_required": bool(tool.get("confirmation_required", True)),
				"restart_required_to_restore": bool(tool.get("restart_required_to_restore", False)),
				"available": bool(detection.get("available", True)),
				"active": bool(detection.get("active", False)),
				"details": copy.deepcopy(detection),
			})
		return result

	def get_pending(self) -> list[dict[str, Any]]:
		return [tool for tool in self.get_status() if tool.get("available") and tool.get("active")]

	def apply(self, identifier: str) -> dict[str, Any]:
		tool = self._tools.get(str(identifier or "").strip())
		if tool is None:
			return {"success": False, "error": "vendor_tool_not_found", "tool_id": identifier}
		before = self._detect(tool)
		if not before.get("available", True):
			return {"success": False, "error": "vendor_tool_unavailable", "tool_id": identifier, "details": before}
		apply = tool.get("apply")
		if not callable(apply):
			return {"success": False, "error": "vendor_tool_unavailable", "tool_id": identifier}
		try:
			success = bool(apply())
		except Exception as error:
			return {"success": False, "error": "vendor_tool_failed", "tool_id": identifier, "message": str(error)}
		after = self._detect(tool)
		return {
			"success": success and not bool(after.get("active", False)),
			"tool_id": identifier,
			"vendor": tool.get("vendor"),
			"name": tool.get("name"),
			"restart_required_to_restore": bool(tool.get("restart_required_to_restore", False)),
			"details": after,
		}

	def prompt_interactive(self) -> list[dict[str, Any]]:
		results = []
		for tool in self.get_pending():
			print()
			print(tool.get("description") or tool.get("name") or tool.get("id"))
			if tool.get("action"):
				print(tool["action"])
			if tool.get("restore"):
				print(tool["restore"])
			try:
				answer = input(f"{tool.get('name') or 'Apply workaround'}? [y/N]: ").strip().casefold()
			except (EOFError, KeyboardInterrupt):
				answer = ""
			if answer in {"y", "yes"}:
				result = self.apply(tool["id"])
				results.append(result)
				print("Vendor workaround applied." if result.get("success") else "Vendor workaround failed.")
		return results

	@staticmethod
	def _detect(tool: dict[str, Any]) -> dict[str, Any]:
		detect = tool.get("detect")
		if not callable(detect):
			return {"active": False, "available": True}
		try:
			result = detect()
			return dict(result) if isinstance(result, dict) else {"active": bool(result), "available": True}
		except Exception as error:
			return {"active": False, "available": False, "reason": str(error)}
