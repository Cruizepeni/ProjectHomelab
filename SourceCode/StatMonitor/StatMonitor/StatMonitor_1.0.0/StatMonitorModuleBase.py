from __future__ import annotations

import copy
import threading
from typing import Any, Callable


class PollingModule:
	interval_seconds = 1.0

	def __init__(self, *args, **kwargs):
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._hardware: dict[str, Any] = {}
		self._live: dict[str, Any] = {}
		self._warnings: list[dict[str, Any]] = []
		self._provider_name = type(self).__module__.split(".", 1)[0]
		self._provider: dict[str, Any] = {"name": self._provider_name, "status": "available"}
		self._running = False
		self._thread: threading.Thread | None = None
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
			self._settings = dict(settings or {})
		if self._running:
			self._collect_safe()

	def start(self):
		with self._lock:
			if self._running:
				return
			self._running = True
			self._stop_event.clear()
		self._collect_safe()
		self._thread = threading.Thread(target=self._loop, name=type(self).__name__, daemon=True)
		self._thread.start()

	def stop(self):
		with self._lock:
			self._running = False
			self._stop_event.set()
			thread = self._thread
			self._thread = None
		if thread and thread is not threading.current_thread():
			thread.join(timeout=self.interval_seconds + 2.0)

	def is_running(self):
		with self._lock:
			return self._running

	def get_latest(self):
		with self._lock:
			return {
				"hardware": copy.deepcopy(self._hardware),
				"live": copy.deepcopy(self._live),
				"provider": copy.deepcopy(self._provider),
				"warnings": copy.deepcopy(self._warnings),
			}

	def get_metric_snapshot(self):
		return self.get_latest()

	def _loop(self):
		while not self._stop_event.wait(self.interval_seconds):
			self._collect_safe()

	def _collect_safe(self):
		try:
			hardware, live, provider, warnings = self.collect()
			with self._lock:
				self._hardware = hardware or {}
				self._live = live or {}
				self._provider = provider or {"name": self._provider_name, "status": "available"}
				self._warnings = warnings or []
		except Exception as error:
			with self._lock:
				self._provider = {"name": self._provider_name, "status": "degraded", "reason": str(error)}
				self._warnings = [{"code": "provider_error", "message": str(error)}]
		self._notify()

	def _notify(self):
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				pass

	def collect(self):
		return {}, {}, None, []
