

from __future__ import annotations

import copy
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from StatMonitorSettings import MODULE_NAMES, StatMonitorSettings


LOGGER = logging.getLogger(__name__)

class StatMonitorManager:
	def __init__(self, settings: StatMonitorSettings):
		self.settings = settings
		self._modules: dict[str, Any] = {}
		self._module_listeners: dict[str, Callable[[Any], None]] = {}
		self._states = {name: "unavailable" for name in MODULE_NAMES}
		self._data: dict[str, dict[str, Any]] = {}
		self._listeners: list[Callable[[dict], None]] = []
		self._lock = threading.RLock()
		self._running = False
		settings.subscribe(self._on_settings_changed)

	def subscribe(self, listener: Callable[[dict], None]) -> None:
		with self._lock:
			if listener not in self._listeners:
				self._listeners.append(listener)

	def register_module(self, name: str, module: Any) -> None:
		if name not in MODULE_NAMES:
			raise ValueError(f"Unknown StatMonitor module: {name}")
		with self._lock:
			old_module = self._modules.get(name)
			old_listener = self._module_listeners.pop(name, None)
			self._modules[name] = module
			self._states[name] = "stopped"
			should_start = self._running and self.settings.is_module_enabled(name)
		if old_module is not None and old_listener is not None:
			self._unsubscribe_module(old_module, old_listener)
		listener = self._make_module_listener(name)
		if listener is not None:
			with self._lock:
				self._module_listeners[name] = listener
			self._subscribe_module(module, listener)
		if should_start:
			self._reconcile(name)

	def unregister_module(self, name: str) -> None:
		with self._lock:
			module = self._modules.pop(name, None)
			listener = self._module_listeners.pop(name, None)
		if module is not None and listener is not None:
			self._unsubscribe_module(module, listener)
		if module is not None:
			self._stop_module(name, module)
		with self._lock:
			self._states[name] = "unavailable"
			self._data.pop(name, None)
		self._notify()

	def start(self) -> None:
		with self._lock:
			self._running = True
			names = list(self._modules)
		for name in names:
			self._reconcile(name)

	def stop(self) -> None:
		with self._lock:
			self._running = False
			modules = list(self._modules.items())
		for name, module in modules:
			self._stop_module(name, module)

	def is_running(self) -> bool:
		with self._lock:
			return self._running

	def get_latest_snapshot(self) -> dict:
		with self._lock:
			modules = {}
			warnings = []
			for name, module in self._modules.items():
				state = self._states[name]
				entry = {"state": state, "hardware": {}, "live": {}}
				if state == "running":
					try:
						latest = module.get_latest() or {}
						entry["hardware"] = copy.deepcopy(latest.get("hardware", {}))
						entry["live"] = copy.deepcopy(latest.get("live", {}))

						provider = latest.get("provider")
						if isinstance(provider, dict) and provider:
							entry["provider"] = copy.deepcopy(provider)

						module_warnings = latest.get("warnings")
						if isinstance(module_warnings, list):
							for warning in module_warnings:
								if not isinstance(warning, dict):
									continue
								item = copy.deepcopy(warning)
								item.setdefault("module", name)
								warnings.append(item)
					except Exception as error:
						self._states[name] = "error"
						LOGGER.exception("Failed to read %s module data: %s", name, error)
						entry["state"] = "error"
				modules[name] = entry
			return {
				"timestamp": datetime.now(timezone.utc).isoformat(),
				"modules": modules,
				"warnings": warnings,
			}

	def get_module_states(self) -> dict[str, str]:
		with self._lock:
			return dict(self._states)

	def _on_settings_changed(self, section: str, changed: dict[str, Any]) -> None:
		if section == "Modules":
			for name in changed:
				if name in self._modules:
					self._reconcile(name)
		elif section in self._modules:
			module = self._modules[section]
			handler = getattr(module, "update_settings", None)
			if handler:
				try:
					handler(self.settings.get_module_settings(section, resolved=True))
				except Exception:
					self._states[section] = "error"
					LOGGER.exception("Failed to update %s module settings", section)
			self._notify()

	def _make_module_listener(self, name: str) -> Callable[[Any], None] | None:
		if not callable(getattr(self._modules.get(name), "subscribe", None)):
			return None

		def module_updated(_latest=None):
			with self._lock:
				if name not in self._modules or not self._running:
					return
			self._notify()

		return module_updated

	def _subscribe_module(self, module: Any, listener: Callable[[Any], None]) -> None:
		try:
			module.subscribe(listener)
		except Exception:
			LOGGER.exception("Failed to subscribe to StatMonitor %s updates", type(module).__name__)

	def _unsubscribe_module(self, module: Any, listener: Callable[[Any], None]) -> None:
		try:
			unsubscribe = getattr(module, "unsubscribe", None)
			if callable(unsubscribe):
				unsubscribe(listener)
		except Exception:
			LOGGER.exception("Failed to unsubscribe from StatMonitor %s updates", type(module).__name__)

	def _reconcile(self, name: str) -> None:
		with self._lock:
			module = self._modules.get(name)
			should_run = self._running and self.settings.is_module_enabled(name)
			state = self._states.get(name)
		if module is None:
			return
		if should_run and state not in ("running", "starting"):
			self._start_module(name, module)
		elif not should_run and state in ("running", "starting"):
			self._stop_module(name, module)

	def _start_module(self, name: str, module: Any) -> None:
		with self._lock:
			self._states[name] = "starting"
		self._notify()
		try:
			update = getattr(module, "update_settings", None)
			if update:
				update(self.settings.get_module_settings(name, resolved=True))
			module.start()
			with self._lock:
				self._states[name] = "running" if getattr(module, "is_running", lambda: True)() else "stopped"
		except Exception:
			with self._lock:
				self._states[name] = "error"
			LOGGER.exception("Failed to start %s module", name)
		self._notify()

	def _stop_module(self, name: str, module: Any) -> None:
		try:
			module.stop()
			state = "stopped"
		except Exception:
			state = "error"
			LOGGER.exception("Failed to stop %s module", name)
		with self._lock:
			self._states[name] = state
			self._data.pop(name, None)
		self._notify()

	def _notify(self) -> None:
		snapshot = self.get_latest_snapshot()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(snapshot)
			except Exception:
				LOGGER.exception("StatMonitor manager listener failed")
