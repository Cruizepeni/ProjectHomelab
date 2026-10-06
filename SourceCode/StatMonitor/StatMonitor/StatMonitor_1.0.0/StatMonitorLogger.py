from __future__ import annotations

import copy
import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from StatMonitorSettings import MODULE_NAMES


LOG_MODULE_NAMES = (*MODULE_NAMES, "Fans")


LOG_COMMANDS = {
	"StartLog": {"purpose": "Start a graph-friendly telemetry log.", "args": {"modules": "all or module list", "duration_seconds": "optional duration", "path": "optional directory or .jsonl file", "interval_seconds": "optional sample interval"}, "mutates": True},
	"StopLog": {"purpose": "Stop the active telemetry log.", "args": {}, "mutates": True},
	"GetLogStatus": {"purpose": "Return current telemetry logging state.", "args": {}, "mutates": False},
}


class StatMonitorLogger:
	def __init__(self, manager, project_root, fan_controller=None):
		self.manager = manager
		self.fan_controller = fan_controller
		self.root = Path(project_root).resolve()
		self.default_directory = self.root / "Appdata" / "Logs" / "StatMonitor"
		self._lock = threading.RLock()
		self._thread: threading.Thread | None = None
		self._stop = threading.Event()
		self._active = False
		self._path: Path | None = None
		self._modules: list[str] = []
		self._duration_seconds: float | None = None
		self._interval_seconds = 1.0
		self._started_monotonic: float | None = None
		self._ended_monotonic: float | None = None
		self._started_utc: str | None = None
		self._ended_utc: str | None = None
		self._samples = 0
		self._last_error: str | None = None
		self._stop_reason = "stopped"

	def handle_command(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
		request = dict(arguments) if isinstance(arguments, dict) else {}
		try:
			if command == "StartLog":
				return self.start(request.get("modules", "all"), request.get("duration_seconds"), request.get("path"), request.get("interval_seconds", 1.0))
			if command == "StopLog":
				return self.stop()
			if command == "GetLogStatus":
				return {"success": True, **self.get_status()}
			return {"success": False, "error": "unknown_command", "command": command}
		except ValueError as error:
			return {"success": False, "error": "invalid_request", "command": command, "message": str(error)}
		except Exception as error:
			return {"success": False, "error": "request_failed", "command": command, "message": str(error)}

	def start(self, modules: Any = "all", duration_seconds: Any = None, path: Any = None, interval_seconds: Any = 1.0) -> dict[str, Any]:
		selected = self._normalize_modules(modules)
		duration = self._normalize_duration(duration_seconds)
		interval = self._normalize_interval(interval_seconds)
		output = self._resolve_path(path)
		with self._lock:
			if self._active:
				raise ValueError("a StatMonitor log is already running")
			output.parent.mkdir(parents=True, exist_ok=True)
			self._path = output
			self._modules = selected
			self._duration_seconds = duration
			self._interval_seconds = interval
			self._started_monotonic = time.monotonic()
			self._ended_monotonic = None
			self._started_utc = datetime.now(timezone.utc).isoformat()
			self._ended_utc = None
			self._samples = 0
			self._last_error = None
			self._stop_reason = "stopped"
			self._stop.clear()
			self._active = True
			self._thread = threading.Thread(target=self._run, name="StatMonitorLogger", daemon=True)
			self._thread.start()
		return {"success": True, "command": "StartLog", **self.get_status()}

	def stop(self) -> dict[str, Any]:
		with self._lock:
			was_active = self._active
			self._stop_reason = "stopped"
			self._stop.set()
			thread = self._thread
		if thread and thread is not threading.current_thread():
			thread.join(timeout=5.0)
		with self._lock:
			if self._active:
				self._active = False
				self._ended_monotonic = time.monotonic()
				self._ended_utc = datetime.now(timezone.utc).isoformat()
			self._thread = None
			status = self._status_locked()
		return {"success": True, "command": "StopLog", "stopped": was_active, **status}

	def get_status(self) -> dict[str, Any]:
		with self._lock:
			return self._status_locked()

	def _status_locked(self) -> dict[str, Any]:
		elapsed = None
		if self._started_monotonic is not None:
			end = time.monotonic() if self._active else self._ended_monotonic or time.monotonic()
			elapsed = round(max(0.0, end - self._started_monotonic), 3)
		return {
			"active": self._active,
			"path": str(self._path) if self._path else None,
			"modules": list(self._modules),
			"duration_seconds": self._duration_seconds,
			"elapsed_seconds": elapsed,
			"sample_interval_seconds": self._interval_seconds,
			"samples": self._samples,
			"started_utc": self._started_utc,
			"ended_utc": self._ended_utc,
			"format": "jsonl",
			"graph_series": True,
			"last_error": self._last_error,
		}

	def _run(self) -> None:
		path = self._path
		if path is None:
			return
		reason = "stopped"
		try:
			with path.open("x", encoding="utf-8") as handle:
				self._write_metadata(handle)
				next_sample = time.monotonic()
				while not self._stop.is_set():
					now = time.monotonic()
					with self._lock:
						started = self._started_monotonic or now
						duration = self._duration_seconds
						interval = self._interval_seconds
					elapsed = max(0.0, now - started)
					if duration is not None and elapsed >= duration and self._samples > 0:
						reason = "duration_complete"
						break
					if now >= next_sample:
						self._write_sample(handle, elapsed)
						next_sample += interval
						if next_sample <= now:
							next_sample = now + interval
					wait_for = max(0.02, min(0.25, next_sample - time.monotonic()))
					self._stop.wait(wait_for)
				if self._stop.is_set():
					reason = self._stop_reason
				self._write_end(handle, reason)
		except FileExistsError:
			with self._lock:
				self._last_error = "log file already exists"
			reason = "error"
		except Exception as error:
			with self._lock:
				self._last_error = str(error)
			reason = "error"
		finally:
			with self._lock:
				self._active = False
				self._ended_monotonic = time.monotonic()
				self._ended_utc = datetime.now(timezone.utc).isoformat()
				self._thread = None
				self._stop_reason = reason

	def _write_metadata(self, handle) -> None:
		snapshot = self.manager.get_latest_snapshot()
		modules = {}
		for name in self._modules:
			if name == "Fans":
				modules[name] = self._fan_metadata()
				continue
			entry = snapshot.get("modules", {}).get(name, {})
			modules[name] = {"state": entry.get("state", "unavailable"), "hardware": copy.deepcopy(entry.get("hardware", {}))}
		record = {
			"type": "metadata",
			"format": "StatMonitorTelemetryJSONL",
			"format_version": 1,
			"started_utc": self._started_utc,
			"sample_interval_seconds": self._interval_seconds,
			"duration_seconds": self._duration_seconds,
			"selected_modules": list(self._modules),
			"modules": modules,
		}
		handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
		handle.flush()

	def _write_sample(self, handle, elapsed: float) -> None:
		snapshot = self.manager.get_latest_snapshot()
		modules = {}
		series = {}
		for name in self._modules:
			if name == "Fans":
				modules[name] = self._fan_sample()
				self._flatten_numeric(modules[name].get("live", {}), name, series)
				continue
			entry = snapshot.get("modules", {}).get(name, {})
			live = copy.deepcopy(entry.get("live", {}))
			modules[name] = {"state": entry.get("state", "unavailable"), "live": live}
			self._flatten_numeric(live, name, series)
		record = {
			"type": "sample",
			"timestamp_utc": snapshot.get("timestamp") or datetime.now(timezone.utc).isoformat(),
			"elapsed_seconds": round(elapsed, 3),
			"series": series,
			"modules": modules,
		}
		handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
		handle.flush()
		with self._lock:
			self._samples += 1

	def _write_end(self, handle, reason: str) -> None:
		with self._lock:
			started = self._started_monotonic
			samples = self._samples
		elapsed = max(0.0, time.monotonic() - started) if started is not None else 0.0
		record = {
			"type": "end",
			"ended_utc": datetime.now(timezone.utc).isoformat(),
			"elapsed_seconds": round(elapsed, 3),
			"samples": samples,
			"reason": reason,
		}
		handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
		handle.flush()

	def _fan_status(self) -> dict[str, Any]:
		if self.fan_controller is None:
			return {}
		try:
			result = self.fan_controller.handle_command("GetFanMapStatus", {})
		except Exception:
			return {}
		return result if isinstance(result, dict) and result.get("success") else {}

	def _fan_metadata(self) -> dict[str, Any]:
		status = self._fan_status()
		if not status:
			return {"state": "unavailable", "hardware": {}}
		fans = []
		for fan in status.get("fans", []) or []:
			if not isinstance(fan, dict):
				continue
			fans.append({key: copy.deepcopy(fan.get(key)) for key in ("fan_number", "identifier", "reported_name", "friendly_name", "registered", "best_guess_profile", "profile", "map", "map_override", "temperature_sources", "provider_controlled") if key in fan})
		return {
			"state": "running",
			"hardware": {
				"control_enabled": bool(status.get("enabled")),
				"registered_count": status.get("registered_count", 0),
				"fans": fans,
				"safety": copy.deepcopy(status.get("safety", {})),
			},
		}

	def _fan_sample(self) -> dict[str, Any]:
		status = self._fan_status()
		if not status:
			return {"state": "unavailable", "live": {}}
		fans = []
		for fan in status.get("fans", []) or []:
			if not isinstance(fan, dict):
				continue
			fans.append({key: copy.deepcopy(fan.get(key)) for key in ("fan_number", "identifier", "friendly_name", "profile", "map", "temperature_c", "target_percent", "rpm", "output_percent", "owned", "provider_controlled", "last_error") if key in fan})
		return {
			"state": "running",
			"live": {
				"control_enabled": bool(status.get("enabled")),
				"registered_count": status.get("registered_count", 0),
				"fans": fans,
			},
		}

	@classmethod
	def _flatten_numeric(cls, value: Any, prefix: str, output: dict[str, float]) -> None:
		if isinstance(value, bool) or value is None:
			return
		if isinstance(value, (int, float)):
			try:
				number = float(value)
			except (TypeError, ValueError):
				return
			if math.isfinite(number):
				output[prefix] = number
			return
		if isinstance(value, dict):
			for key, child in value.items():
				name = f"{prefix}.{key}" if prefix else str(key)
				cls._flatten_numeric(child, name, output)
			return
		if isinstance(value, (list, tuple)):
			for index, child in enumerate(value):
				cls._flatten_numeric(child, f"{prefix}.{index}", output)

	@staticmethod
	def parse_duration(value: str) -> float:
		text = str(value).strip().casefold()
		if not text:
			raise ValueError("duration is empty")
		units = {
			"milliseconds": 0.001,
			"millisecond": 0.001,
			"msecs": 0.001,
			"msec": 0.001,
			"ms": 0.001,
			"seconds": 1.0,
			"second": 1.0,
			"secs": 1.0,
			"sec": 1.0,
			"s": 1.0,
			"minutes": 60.0,
			"minute": 60.0,
			"mins": 60.0,
			"min": 60.0,
			"m": 60.0,
			"hours": 3600.0,
			"hour": 3600.0,
			"hrs": 3600.0,
			"hr": 3600.0,
			"h": 3600.0,
		}
		for unit in sorted(units, key=len, reverse=True):
			if text.endswith(unit):
				number = float(text[:-len(unit)].strip())
				if number <= 0 or not math.isfinite(number):
					raise ValueError("duration must be greater than zero")
				return number * units[unit]
		number = float(text)
		if number <= 0 or not math.isfinite(number):
			raise ValueError("duration must be greater than zero")
		return number

	@staticmethod
	def looks_like_duration(value: str) -> bool:
		try:
			StatMonitorLogger.parse_duration(value)
			return any(character.isdigit() for character in str(value))
		except Exception:
			return False

	@staticmethod
	def _normalize_duration(value: Any) -> float | None:
		if value is None:
			return None
		if isinstance(value, bool):
			raise ValueError("duration must be numeric")
		if isinstance(value, (int, float)):
			duration = float(value)
		else:
			duration = StatMonitorLogger.parse_duration(str(value))
		if duration <= 0 or not math.isfinite(duration):
			raise ValueError("duration must be greater than zero")
		return duration

	@staticmethod
	def _normalize_interval(value: Any) -> float:
		if isinstance(value, bool):
			raise ValueError("interval must be numeric")
		if isinstance(value, (int, float)):
			interval = float(value)
		else:
			interval = StatMonitorLogger.parse_duration(str(value))
		if not math.isfinite(interval) or not 0.5 <= interval <= 3600.0:
			raise ValueError("log interval must be between 500ms and 1h")
		return interval

	@staticmethod
	def _normalize_modules(value: Any) -> list[str]:
		if value is None or value == "all":
			return list(LOG_MODULE_NAMES)
		items = [value] if isinstance(value, str) else list(value) if isinstance(value, (list, tuple, set)) else []
		lookup = {name.casefold(): name for name in LOG_MODULE_NAMES}
		result = []
		for item in items:
			for token in str(item).split(","):
				text = token.strip()
				if not text:
					continue
				if text.casefold() == "all":
					return list(LOG_MODULE_NAMES)
				name = lookup.get(text.casefold())
				if name is None:
					raise ValueError(f"unknown log module: {text}")
				if name not in result:
					result.append(name)
		if not result:
			raise ValueError("at least one module is required")
		return result

	def _resolve_path(self, value: Any) -> Path:
		stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
		filename = f"StatMonitor_Log_{stamp}.jsonl"
		if value is None or not str(value).strip():
			candidate = self.default_directory / filename
		else:
			requested = Path(str(value).strip()).expanduser()
			if requested.suffix:
				if requested.suffix.casefold() != ".jsonl":
					raise ValueError("custom log file paths must use the .jsonl extension")
				candidate = requested
			else:
				candidate = requested / filename
		if not candidate.is_absolute():
			candidate = (Path.cwd() / candidate).resolve()
		else:
			candidate = candidate.resolve()
		if not candidate.exists():
			return candidate
		base = candidate.stem
		suffix = candidate.suffix
		parent = candidate.parent
		index = 2
		while True:
			alternate = parent / f"{base}_{index}{suffix}"
			if not alternate.exists():
				return alternate
			index += 1
