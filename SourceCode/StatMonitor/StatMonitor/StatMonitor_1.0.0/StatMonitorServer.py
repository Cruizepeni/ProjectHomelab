from __future__ import annotations

import asyncio
import copy
import ipaddress
import json
import logging
import threading
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from StatMonitorDeviceControls import BLUETOOTH_COMMANDS, DEVICE_COMMANDS, PRIVACY_COMMANDS, STORAGE_TOOL_COMMANDS, WIFI_COMMANDS
from StatMonitorFanService import FAN_COMMANDS
from StatMonitorLogger import LOG_COMMANDS
from StatMonitorServerAccess import StatMonitorServerAccess
from StatMonitorSettings import MODULE_NAMES

try:
	import websockets
	from websockets.exceptions import ConnectionClosed
except ImportError as error:
	websockets = None
	ConnectionClosed = Exception
	_WEBSOCKETS_IMPORT_ERROR = error


LOGGER = logging.getLogger(__name__)
AI_ACCESS_DENIED = {"success": False, "error": "access_denied", "message": "Access Denied"}
PROTOCOL_VERSION = 1
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 42300
READ_ACTIONS = {
	"get_current_snapshot",
	"get_settings",
	"get_vendor_tools",
	"get_capabilities",
	"get_server_info",
}
CONTROL_ACTIONS = {
	"update_settings",
	"apply_vendor_tool",
	"device_control_command",
	"fan_controller_command",
	"log_command",
}


class StatMonitorServer:
	def __init__(self, manager, settings, host: str = DEFAULT_SERVER_HOST, port: int = DEFAULT_SERVER_PORT, fan_controller=None, logger=None, device_controller=None, vendor_tools=None, allow_remote: bool = False, allowed_origins=None):
		self.manager = manager
		self.settings = settings
		self.fan_controller = fan_controller
		self.logger = logger
		self.device_controller = device_controller
		self.vendor_tools = vendor_tools
		self.host = host
		self.port = int(port)
		self.allow_remote = bool(allow_remote)
		self.allowed_origins = {str(origin).rstrip("/") for origin in (allowed_origins or []) if str(origin).strip()}
		self.access = StatMonitorServerAccess(settings.root)
		self._loop: asyncio.AbstractEventLoop | None = None
		self._server = None
		self._thread: threading.Thread | None = None
		self._ready = threading.Event()
		self._startup_error: Exception | None = None
		self._clients: set[Any] = set()
		self._clients_lock = threading.Lock()
		self._ai_subscriptions: dict[str, dict[str, Any]] = {}
		self._ai_lock = threading.RLock()
		self._latest_snapshot = manager.get_latest_snapshot()
		manager.subscribe(self._manager_changed)
		settings.subscribe(self._settings_changed)

	def start(self) -> None:
		if websockets is None:
			raise RuntimeError("The 'websockets' package is required") from _WEBSOCKETS_IMPORT_ERROR
		if not self.allow_remote and not self._is_loopback_host(self.host):
			raise RuntimeError("StatMonitor only binds to loopback by default. Use --allow-remote to explicitly permit a non-loopback host.")
		if self._thread and self._thread.is_alive():
			return
		self._startup_error = None
		self._ready.clear()
		self._thread = threading.Thread(target=self._run, name="StatMonitorWebSocket", daemon=True)
		self._thread.start()
		if not self._ready.wait(timeout=10):
			raise RuntimeError("StatMonitor WebSocket server did not start")
		if self._startup_error is not None:
			error = self._startup_error
			self._thread.join(timeout=10)
			self._thread = None
			self._loop = None
			raise RuntimeError(
				f"StatMonitor could not bind WebSocket port {self.host}:{self.port}. "
				"The required port may already be in use by another process."
			) from error

	def stop(self) -> None:
		self._invalidate_ai_subscriptions()
		if not self._loop or not self._thread:
			return
		future = asyncio.run_coroutine_threadsafe(self._stop_async(), self._loop)
		future.result(timeout=10)
		self._thread.join(timeout=10)
		self._thread = None
		self._loop = None

	def publish_snapshot(self, snapshot: dict) -> None:
		self._latest_snapshot = snapshot
		if self._loop and self._loop.is_running():
			asyncio.run_coroutine_threadsafe(self._broadcast(self._event("stat_monitor_snapshot", snapshot)), self._loop)

	def _manager_changed(self, snapshot: dict) -> None:
		self.publish_snapshot(snapshot)
		self._publish_ai_snapshot(snapshot)
		self.broadcast("stat_monitor_module_state", {
			name: entry.get("state") for name, entry in snapshot.get("modules", {}).items()
		})

	def broadcast(self, message_type: str, data: Any) -> None:
		if self._loop and self._loop.is_running():
			asyncio.run_coroutine_threadsafe(self._broadcast(self._event(message_type, data)), self._loop)

	def _settings_changed(self, section: str, changed: dict) -> None:
		if section == "aiEnabled" and not self.settings.is_ai_enabled():
			self._invalidate_ai_subscriptions()
		self.broadcast("stat_monitor_settings", {section: changed})

	def get_server_info(self, include_token: bool = False) -> dict:
		info = {
			"service": "StatMonitor",
			"protocolVersion": PROTOCOL_VERSION,
			"host": self.host,
			"port": self.port,
			"endpoints": {"ui": "/ws", "ai": "/ai"},
			"security": {
				"loopbackDefault": True,
				"remoteEnabled": self.allow_remote,
				"browserOrigins": "loopback_or_explicit",
				"nativeReadWithoutToken": True,
				"nativeControlRequiresToken": True,
				"aiRequiresToken": True,
				"readActions": sorted(READ_ACTIONS),
				"controlActions": sorted(CONTROL_ACTIONS),
			},
		}
		if include_token:
			info["token"] = self.access.get_token()
		return info

	def get_capabilities(self) -> dict:
		states = self.manager.get_module_states()
		return {
			"service": "StatMonitor",
			"protocolVersion": PROTOCOL_VERSION,
			"modules": {
				name: {"state": state, "available": state != "unavailable"}
				for name, state in states.items()
			},
			"controls": {
				"fans": {"available": self.fan_controller is not None, "commands": sorted(FAN_COMMANDS)},
				"logging": {"available": self.logger is not None, "commands": sorted(LOG_COMMANDS)},
				"wifi": {"available": states.get("WiFi") != "unavailable", "commands": sorted(WIFI_COMMANDS)},
				"bluetooth": {"available": states.get("Bluetooth") != "unavailable", "commands": sorted(BLUETOOTH_COMMANDS)},
				"privacy": {"available": self.device_controller is not None and getattr(self.device_controller, "privacy", None) is not None, "commands": sorted(PRIVACY_COMMANDS)},
				"storageTools": {"available": self.device_controller is not None and getattr(self.device_controller, "storage_tools", None) is not None, "commands": sorted(STORAGE_TOOL_COMMANDS)},
				"vendorTools": {"available": self.vendor_tools is not None},
			},
		}

	async def _handler(self, websocket, *args) -> None:
		path = self._connection_path(websocket, args)
		origin = self._connection_origin(websocket)
		if origin is not None and not self._origin_allowed(origin):
			await websocket.close(code=1008, reason="Origin not allowed")
			return
		if path not in {"/", "/ws", "/ai"}:
			await websocket.close(code=1008, reason="Unknown StatMonitor endpoint")
			return
		trusted_browser = origin is not None and self._origin_allowed(origin)
		connection = {"authenticated": False, "trusted_browser": trusted_browser, "origin": origin, "path": path, "remote": not self._is_loopback_host(self.host)}
		if path == "/ai":
			await self._ai_handler(websocket, connection)
			return
		with self._clients_lock:
			self._clients.add(websocket)
		try:
			if connection["remote"]:
				await websocket.send(json.dumps(self._event("stat_monitor_auth_required", {"endpoint": "/ws", "protocolVersion": PROTOCOL_VERSION}), default=str))
			else:
				await websocket.send(json.dumps(self._event("stat_monitor_snapshot", self._latest_snapshot), default=str))
				await websocket.send(json.dumps(self._event("stat_monitor_module_state", self.manager.get_module_states()), default=str))
				await websocket.send(json.dumps(self._event("stat_monitor_capabilities", self.get_capabilities()), default=str))
				if self.vendor_tools is not None:
					await websocket.send(json.dumps(self._event("stat_monitor_vendor_tools", self.vendor_tools.get_status()), default=str))
			async for raw_message in websocket:
				request_id = None
				try:
					request = json.loads(raw_message)
					if isinstance(request, dict):
						request_id = request.get("id")
					response = await self._handle_request(request, connection)
				except (json.JSONDecodeError, TypeError):
					response = self._error_response(request_id, "invalid_json", "Invalid JSON request")
				except Exception as error:
					LOGGER.exception("StatMonitor request failed")
					response = self._error_response(request_id, "request_failed", str(error))
				await websocket.send(json.dumps(response, default=str))
		except ConnectionClosed:
			pass
		finally:
			with self._clients_lock:
				self._clients.discard(websocket)

	async def _ai_handler(self, websocket, connection: dict) -> None:
		subscription_ids: set[str] = set()
		def event_sink(event: dict) -> None:
			if self._loop and self._loop.is_running():
				asyncio.run_coroutine_threadsafe(websocket.send(json.dumps(self._event("stat_monitor_ai_event", event))), self._loop)
		try:
			await websocket.send(json.dumps(self._event("stat_monitor_auth_required", {"endpoint": "/ai", "protocolVersion": PROTOCOL_VERSION})))
			async for raw_message in websocket:
				request_id = None
				try:
					request = json.loads(raw_message)
					if not isinstance(request, dict):
						raise TypeError
					request_id = request.get("id")
					if self._is_auth_request(request):
						response = self._authenticate_request(request, connection)
						await websocket.send(json.dumps(response))
						continue
					if not connection["authenticated"] and self.access.verify(request.get("token")):
						connection["authenticated"] = True
					if not connection["authenticated"]:
						await websocket.send(json.dumps(self._error_response(request_id, "authentication_required", "The StatMonitor AI endpoint requires the local integration token")))
						continue
					if request.get("kind") == "request" or request.get("type") == "ai_request":
						payload = request.get("payload", request.get("data", {}))
						if isinstance(payload, dict) and payload:
							request = dict(payload)
					command = request.get("command") if isinstance(request, dict) else None
					if command in FAN_COMMANDS or command in LOG_COMMANDS:
						result = await asyncio.to_thread(self.handle_ai_request, request, event_sink)
					else:
						result = self.handle_ai_request(request, event_sink)
					if result.get("subscription_id"):
						subscription_ids.add(result["subscription_id"])
					response = self._response(request_id, "stat_monitor_ai_response", result, result.get("success") is not False)
				except Exception:
					response = self._error_response(request_id, "invalid_request", "Invalid AI request")
				await websocket.send(json.dumps(response, default=str))
		except ConnectionClosed:
			pass
		finally:
			for subscription_id in subscription_ids:
				self._remove_ai_subscription(subscription_id)

	async def _handle_request(self, request: dict, connection: dict) -> dict:
		if not isinstance(request, dict):
			return self._error_response(None, "invalid_request", "Request must be an object")
		request_id = request.get("id")
		protocol = request.get("protocol")
		if protocol not in (None, PROTOCOL_VERSION):
			return self._error_response(request_id, "unsupported_protocol", f"Unsupported protocol version: {protocol}")
		if self._is_auth_request(request):
			return self._authenticate_request(request, connection)
		action, payload = self._request_action_payload(request)
		if connection.get("remote") and not connection["authenticated"]:
			return self._error_response(request_id, "authentication_required", "Remote StatMonitor access requires the local integration token")
		if action in CONTROL_ACTIONS and not (connection["trusted_browser"] or connection["authenticated"]):
			return self._error_response(request_id, "authentication_required", "This operation requires the StatMonitor local integration token")
		if action == "get_current_snapshot":
			return self._response(request_id, "stat_monitor_snapshot", self._latest_snapshot)
		if action == "get_settings":
			return self._response(request_id, "stat_monitor_settings", self.settings.get_all())
		if action == "get_capabilities":
			return self._response(request_id, "stat_monitor_capabilities", self.get_capabilities())
		if action == "get_server_info":
			return self._response(request_id, "stat_monitor_server_info", self.get_server_info())
		if action == "update_settings":
			updates = payload.get("settings", payload) if isinstance(payload, dict) else {}
			self.settings.update_settings(updates)
			return self._response(request_id, "stat_monitor_settings", self.settings.get_all())
		if action == "get_vendor_tools":
			return self._response(request_id, "stat_monitor_vendor_tools", self.vendor_tools.get_status() if self.vendor_tools is not None else [])
		if action == "apply_vendor_tool":
			if self.vendor_tools is None:
				return self._response(request_id, "stat_monitor_vendor_tool_response", {"success": False, "error": "vendor_tools_unavailable"}, False)
			identifier = payload.get("tool_id", request.get("tool_id")) if isinstance(payload, dict) else request.get("tool_id")
			confirmed = payload.get("confirmed", request.get("confirmed")) if isinstance(payload, dict) else request.get("confirmed")
			if confirmed is not True:
				return self._response(request_id, "stat_monitor_vendor_tool_response", {"success": False, "error": "confirmation_required", "tool_id": identifier}, False)
			result = await asyncio.to_thread(self.vendor_tools.apply, identifier)
			self.broadcast("stat_monitor_vendor_tools", self.vendor_tools.get_status())
			return self._response(request_id, "stat_monitor_vendor_tool_response", result, result.get("success") is not False)
		if action == "device_control_command":
			command = payload.get("command", request.get("command")) if isinstance(payload, dict) else request.get("command")
			arguments = dict(payload) if isinstance(payload, dict) else {}
			arguments.pop("command", None)
			result = await asyncio.to_thread(self._handle_device_command, command, arguments)
			return self._response(request_id, "device_control_response", result, result.get("success") is not False)
		if action == "fan_controller_command":
			command = payload.get("command", request.get("command")) if isinstance(payload, dict) else request.get("command")
			arguments = dict(payload) if isinstance(payload, dict) else {}
			arguments.pop("command", None)
			result = await asyncio.to_thread(self._handle_fan_command, command, arguments)
			return self._response(request_id, "fan_controller_response", result, result.get("success") is not False)
		if action == "log_command":
			command = payload.get("command", request.get("command")) if isinstance(payload, dict) else request.get("command")
			arguments = dict(payload) if isinstance(payload, dict) else {}
			arguments.pop("command", None)
			result = await asyncio.to_thread(self._handle_log_command, command, arguments)
			return self._response(request_id, "stat_monitor_log_response", result, result.get("success") is not False)
		return self._error_response(request_id, "unknown_action", f"Unknown request action: {action}")

	def _handle_fan_command(self, command: Any, arguments: dict[str, Any] | None = None) -> dict:
		if self.fan_controller is None:
			return {"success": False, "error": "controller_unavailable", "command": command, "message": "StatMonitorFanController is unavailable"}
		return self.fan_controller.handle_command(command, arguments)

	def _handle_log_command(self, command: Any, arguments: dict[str, Any] | None = None) -> dict:
		if self.logger is None:
			return {"success": False, "error": "logger_unavailable", "command": command}
		return self.logger.handle_command(command, arguments)

	def _handle_device_command(self, command: Any, arguments: dict[str, Any] | None = None) -> dict:
		if self.device_controller is None:
			return {"success": False, "error": "controller_unavailable", "command": command}
		handler = getattr(self.device_controller, "handle_device_command", None)
		if not callable(handler):
			return {"success": False, "error": "controller_unavailable", "command": command}
		return handler(command, arguments)

	def handle_ai_request(self, request: Any, event_sink=None) -> dict:
		if not self.settings.is_ai_enabled():
			return dict(AI_ACCESS_DENIED)
		if not isinstance(request, dict):
			return {"success": False, "error": "invalid_request"}
		command = request.get("command")
		if not isinstance(command, str):
			return {"success": False, "error": "unknown_command"}
		try:
			if command == "GetCapabilities":
				return {"success": True, "capabilities": self.get_capabilities()}
			if command == "GetVendorTools":
				return {"success": True, "tools": self.vendor_tools.get_status() if self.vendor_tools is not None else []}
			if command == "ApplyVendorTool":
				if request.get("confirmed") is not True:
					return {"success": False, "error": "confirmation_required", "tool_id": request.get("tool_id")}
				if self.vendor_tools is None:
					return {"success": False, "error": "vendor_tools_unavailable"}
				return self.vendor_tools.apply(request.get("tool_id"))
			if command in DEVICE_COMMANDS:
				arguments = dict(request)
				arguments.pop("command", None)
				return self._handle_device_command(command, arguments)
			if command in FAN_COMMANDS:
				arguments = dict(request)
				arguments.pop("command", None)
				return self._handle_fan_command(command, arguments)
			if command in LOG_COMMANDS:
				arguments = dict(request)
				arguments.pop("command", None)
				return self._handle_log_command(command, arguments)
			if command == "GetStats": return self._ai_get_stats(request)
			if command == "GetModuleStates": return self._ai_get_module_states(request)
			if command == "GetSettings": return self._ai_get_settings(request)
			if command == "SetModuleEnabled": return self._ai_set_module_enabled(request)
			if command == "SetSetting": return self._ai_set_setting(request)
			if command == "SubscribeStats": return self._ai_subscribe(request, event_sink)
			if command == "UnsubscribeStats": return self._ai_unsubscribe(request)
		except ValueError as error:
			return {"success": False, "error": "invalid_request", "message": str(error)}
		except Exception:
			LOGGER.exception("StatMonitor AI gateway request failed")
			return {"success": False, "error": "request_failed"}
		return {"success": False, "error": "unknown_command"}

	@staticmethod
	def _ai_modules(value: Any) -> list[str]:
		if value == "all" or value is None: return list(MODULE_NAMES)
		if not isinstance(value, list): raise ValueError("modules must be 'all' or a list")
		lookup = {name.lower(): name for name in MODULE_NAMES}; result = []
		for item in value:
			name = lookup.get(str(item).lower())
			if name is None: raise ValueError("unknown module")
			if name not in result: result.append(name)
		return result

	@staticmethod
	def _ai_data_mode(value: Any, default: str) -> str:
		mode = default if value is None else value
		if mode not in ("all", "hardware", "live"): raise ValueError("invalid data mode")
		return mode

	def _ai_filter_snapshot(self, snapshot: dict, modules: list[str], mode: str) -> dict:
		result = {}
		for name in modules:
			entry = snapshot.get("modules", {}).get(name, {"state": "unavailable", "hardware": {}, "live": {}})
			filtered = {"state": entry.get("state", "unavailable")}
			if mode in ("all", "hardware"): filtered["hardware"] = copy.deepcopy(entry.get("hardware", {}))
			if mode in ("all", "live"): filtered["live"] = copy.deepcopy(entry.get("live", {}))
			result[name] = filtered
		return result

	def _ai_get_stats(self, request: dict) -> dict:
		modules = self._ai_modules(request.get("modules", "all")); mode = self._ai_data_mode(request.get("data"), "all")
		snapshot = self.manager.get_latest_snapshot()
		return {"success": True, "timestamp": snapshot.get("timestamp"), "modules": self._ai_filter_snapshot(snapshot, modules, mode)}

	def _ai_get_module_states(self, request: dict) -> dict:
		modules = self._ai_modules(request.get("modules", "all")); states = self.manager.get_module_states()
		return {"success": True, "modules": {name: states.get(name, "unavailable") for name in modules}}

	def _ai_get_settings(self, request: dict) -> dict:
		module = request.get("module", "all"); resolved = request.get("resolved", True)
		if not isinstance(resolved, bool): raise ValueError("resolved must be Boolean")
		if module == "all":
			data = {"Modules": self.settings.get_module_settings("Modules", resolved)}
			data.update({name: self.settings.get_module_settings(name, resolved) for name in MODULE_NAMES})
		elif isinstance(module, str) and module.lower() in {name.lower() for name in MODULE_NAMES}:
			name = next(name for name in MODULE_NAMES if name.lower() == module.lower())
			data = {name: self.settings.get_module_settings(name, resolved)}
		else: raise ValueError("unknown module")
		return {"success": True, "settings": data}

	def _ai_set_module_enabled(self, request: dict) -> dict:
		name = self._ai_modules([request.get("module")])[0]; value = request.get("enabled")
		if value not in (True, False, "Default"): raise ValueError("enabled must be true, false, or Default")
		self.settings.update("Modules", name, value)
		return {"success": True, "module": name, "persisted": value, "enabled": self.settings.is_module_enabled(name), "state": self.manager.get_module_states().get(name)}

	def _ai_set_setting(self, request: dict) -> dict:
		module, setting, value = request.get("module"), request.get("setting"), request.get("value")
		if str(module).lower() == "aienabled" or str(setting).lower() == "aienabled":
			return {"success": False, "error": "setting_not_ai_accessible"}
		name = self._ai_modules([module])[0]
		if value not in (True, False, "Default"): raise ValueError("value must be true, false, or Default")
		self.settings.update(name, setting, value)
		return {"success": True, "module": name, "setting": setting, "persisted": value, "resolved": self.settings.get_module_settings(name, True).get(setting)}

	def _ai_subscribe(self, request: dict, event_sink) -> dict:
		if not callable(event_sink): raise ValueError("AI event sink is required")
		modules = self._ai_modules(request.get("modules", "all")); mode = self._ai_data_mode(request.get("data"), "live")
		interval = request.get("interval_seconds", 1)
		if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval < 1: raise ValueError("interval_seconds must be at least 1")
		subscription_id = "stats-" + uuid.uuid4().hex
		with self._ai_lock:
			self._ai_subscriptions[subscription_id] = {"modules": modules, "mode": mode, "interval": float(interval), "last_sent": 0.0, "sink": event_sink}
		self._emit_ai_subscription(subscription_id, self.manager.get_latest_snapshot())
		return {"success": True, "subscription_id": subscription_id}

	def _ai_unsubscribe(self, request: dict) -> dict:
		identifier = request.get("subscription_id")
		if not isinstance(identifier, str) or not self._remove_ai_subscription(identifier): return {"success": False, "error": "subscription_not_found"}
		return {"success": True, "subscription_id": identifier}

	def _remove_ai_subscription(self, identifier: str) -> bool:
		with self._ai_lock: return self._ai_subscriptions.pop(identifier, None) is not None

	def _invalidate_ai_subscriptions(self) -> None:
		with self._ai_lock: subscriptions, self._ai_subscriptions = list(self._ai_subscriptions.values()), {}
		for subscription in subscriptions:
			try: subscription["sink"]({"type": "StatMonitorAccessDenied", **AI_ACCESS_DENIED})
			except Exception: pass

	def _publish_ai_snapshot(self, snapshot: dict) -> None:
		if not self.settings.is_ai_enabled(): return
		with self._ai_lock: identifiers = list(self._ai_subscriptions)
		for identifier in identifiers: self._emit_ai_subscription(identifier, snapshot)

	def _emit_ai_subscription(self, identifier: str, snapshot: dict) -> None:
		if not self.settings.is_ai_enabled():
			self._remove_ai_subscription(identifier)
			return
		with self._ai_lock:
			subscription = self._ai_subscriptions.get(identifier)
			if subscription is None or time.monotonic() - subscription["last_sent"] < subscription["interval"]: return
			subscription["last_sent"] = time.monotonic(); sink = subscription["sink"]
		event = {"type": "StatMonitorStats", "subscription_id": identifier, "timestamp": snapshot.get("timestamp"), "modules": self._ai_filter_snapshot(snapshot, subscription["modules"], subscription["mode"])}
		if not self.settings.is_ai_enabled():
			self._remove_ai_subscription(identifier)
			return
		try: sink(event)
		except Exception: self._remove_ai_subscription(identifier)


	@staticmethod
	def _event(message_type: str, data: Any) -> dict:
		return {"protocol": PROTOCOL_VERSION, "kind": "event", "event": message_type, "type": message_type, "data": data}

	@staticmethod
	def _response(request_id, response_type: str, data: Any, ok: bool = True) -> dict:
		return {"protocol": PROTOCOL_VERSION, "kind": "response", "id": request_id, "ok": bool(ok), "type": response_type, "data": data}

	@staticmethod
	def _error_response(request_id, code: str, message: str) -> dict:
		return {
			"protocol": PROTOCOL_VERSION,
			"kind": "response",
			"id": request_id,
			"ok": False,
			"type": "stat_monitor_error",
			"error": {"code": code, "message": message},
			"data": {"message": message},
		}

	def _authenticate_request(self, request: dict, connection: dict) -> dict:
		payload = request.get("payload", request.get("data", {}))
		if not isinstance(payload, dict):
			payload = {}
		token = payload.get("token", request.get("token"))
		if self.access.verify(token):
			connection["authenticated"] = True
			return self._response(request.get("id"), "stat_monitor_auth", {"authenticated": True})
		connection["authenticated"] = False
		return self._error_response(request.get("id"), "authentication_failed", "Invalid StatMonitor local integration token")

	@staticmethod
	def _is_auth_request(request: dict) -> bool:
		return request.get("action") in {"auth", "authenticate"} or request.get("type") in {"auth", "authenticate"}

	@staticmethod
	def _request_action_payload(request: dict) -> tuple[str | None, dict]:
		action = request.get("action")
		if not action:
			request_type = request.get("type")
			if request_type not in {"request", "auth", "authenticate"}:
				action = request_type
		payload = request.get("payload")
		if not isinstance(payload, dict):
			payload = request.get("data")
		if not isinstance(payload, dict):
			payload = {}
		return action, payload

	@staticmethod
	def _connection_path(websocket, args) -> str:
		path = args[0] if args else getattr(websocket, "path", None)
		if path is None:
			path = getattr(getattr(websocket, "request", None), "path", "")
		return urlsplit(str(path or "/")).path or "/"

	@staticmethod
	def _connection_origin(websocket) -> str | None:
		request = getattr(websocket, "request", None)
		headers = getattr(request, "headers", None)
		if headers is None:
			headers = getattr(websocket, "request_headers", None)
		if headers is None:
			return None
		try:
			origin = headers.get("Origin")
		except Exception:
			return None
		return str(origin).rstrip("/") if origin else None

	def _origin_allowed(self, origin: str) -> bool:
		if origin in self.allowed_origins:
			return True
		try:
			parsed = urlsplit(origin)
		except Exception:
			return False
		return parsed.scheme in {"http", "https"} and self._is_loopback_host(parsed.hostname or "")

	@staticmethod
	def _is_loopback_host(host: str) -> bool:
		text = str(host or "").strip().strip("[]").casefold()
		if text == "localhost":
			return True
		try:
			return ipaddress.ip_address(text).is_loopback
		except ValueError:
			return False

	async def _broadcast(self, message: dict) -> None:
		payload = json.dumps(message, default=str)
		with self._clients_lock:
			clients = list(self._clients)
		failed = []
		for client in clients:
			try:
				await client.send(payload)
			except Exception:
				failed.append(client)
		if failed:
			with self._clients_lock:
				self._clients.difference_update(failed)

	def _run(self) -> None:
		self._loop = asyncio.new_event_loop()
		asyncio.set_event_loop(self._loop)
		try:
			self._server = self._loop.run_until_complete(self._start_async())
			self._ready.set()
			self._loop.run_forever()
		except Exception as error:
			self._startup_error = error
			self._ready.set()
			LOGGER.exception("StatMonitor WebSocket server failed on %s:%s", self.host, self.port)
		finally:
			self._loop.run_until_complete(self._close_clients())
			self._loop.close()

	async def _start_async(self):
		return await websockets.serve(self._handler, self.host, self.port, max_size=1048576, max_queue=32)

	async def _stop_async(self) -> None:
		if self._server:
			self._server.close()
			await self._server.wait_closed()
		self._loop.call_soon(self._loop.stop)

	async def _close_clients(self) -> None:
		with self._clients_lock:
			clients = list(self._clients)
			self._clients.clear()
		if clients:
			await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)
