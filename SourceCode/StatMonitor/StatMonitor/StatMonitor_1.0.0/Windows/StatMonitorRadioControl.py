from __future__ import annotations

import asyncio
import threading
from typing import Any

try:
	from winrt.windows.devices.radios import Radio, RadioState
	WINRT_RADIOS_AVAILABLE = True
	WINRT_RADIOS_ERROR = None
except Exception as error:
	Radio = None
	RadioState = None
	WINRT_RADIOS_AVAILABLE = False
	WINRT_RADIOS_ERROR = str(error)


def _enum_name(value: Any) -> str:
	if value is None:
		return "unknown"
	name = getattr(value, "name", None)
	if isinstance(name, str) and name:
		return name.casefold()
	return str(value).split(".")[-1].casefold()


def _kind_matches(value: Any, kind: str) -> bool:
	name = _enum_name(value).replace("_", "")
	return name == kind.casefold().replace("_", "")


async def _find_radio(kind: str):
	radios = await Radio.get_radios_async()
	for radio in radios:
		if _kind_matches(radio.kind, kind):
			return radio
	return None


async def _read_radio(kind: str) -> dict[str, Any]:
	if not WINRT_RADIOS_AVAILABLE:
		return {"success": False, "available": False, "state": False, "radio_state": "unavailable", "error": WINRT_RADIOS_ERROR}
	try:
		radio = await _find_radio(kind)
		if radio is None:
			return {"success": False, "available": False, "state": False, "radio_state": "not_found", "error": f"{kind} radio not found"}
		state_name = _enum_name(radio.state)
		return {
			"success": True,
			"available": True,
			"state": state_name == "on",
			"radio_state": state_name,
			"radio_name": getattr(radio, "name", None),
		}
	except Exception as error:
		return {"success": False, "available": False, "state": False, "radio_state": "error", "error": str(error)}


async def _set_radio(kind: str, enabled: bool) -> dict[str, Any]:
	if not WINRT_RADIOS_AVAILABLE:
		return await _read_radio(kind)
	try:
		access = await Radio.request_access_async()
		access_status = _enum_name(access)
		if access_status != "allowed":
			state = await _read_radio(kind)
			state.update({"success": False, "access_status": access_status, "error": "radio_access_denied"})
			return state
		radio = await _find_radio(kind)
		if radio is None:
			return {"success": False, "available": False, "state": False, "radio_state": "not_found", "access_status": access_status, "error": f"{kind} radio not found"}
		target = getattr(RadioState, "ON") if enabled else getattr(RadioState, "OFF")
		result = await radio.set_state_async(target)
		set_status = _enum_name(result)
		await asyncio.sleep(0.15)
		state = await _read_radio(kind)
		state["access_status"] = set_status
		state["success"] = bool(state.get("available")) and bool(state.get("state")) is enabled
		if not state["success"] and not state.get("error"):
			state["error"] = "radio_state_not_confirmed"
		return state
	except Exception as error:
		state = await _read_radio(kind)
		state.update({"success": False, "error": str(error)})
		return state


def _run(coroutine_factory):
	result = {}
	error = None
	def worker():
		nonlocal result, error
		try:
			result = asyncio.run(coroutine_factory())
		except Exception as caught:
			error = caught
	thread = threading.Thread(target=worker, name="StatMonitorWindowsRadioControl", daemon=True)
	thread.start()
	thread.join(timeout=15.0)
	if thread.is_alive():
		return {"success": False, "available": False, "error": "radio_operation_timeout"}
	if error is not None:
		return {"success": False, "available": False, "error": str(error)}
	return result


def get_radio_state(kind: str) -> dict[str, Any]:
	return _run(lambda: _read_radio(kind))


def set_radio_enabled(kind: str, enabled: bool) -> dict[str, Any]:
	return _run(lambda: _set_radio(kind, enabled))
