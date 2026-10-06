

from __future__ import annotations

from StatMonitorOutput import print_raw

import copy
import ctypes
import datetime as dt
import json
import logging
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from StatMonitorPaths import resolve_project_root

try:
	import psutil
except ImportError:
	psutil = None


LOGGER = logging.getLogger(__name__)
SAMPLE_INTERVAL_SECONDS = 1.0
CIM_TIMEOUT_SECONDS = 5.0
_STATIC_SETTINGS = (
	"Show Device Name", "Show Operating System", "Show OS Version",
	"Show Architecture", "Show Last Boot Time",
)
_SETTINGS = _STATIC_SETTINGS + ("Show System Uptime",)


class StatMonitorSystem:


	def __init__(self, project_root: str | os.PathLike[str] | None = None):
		self.project_root = Path(project_root) if project_root else resolve_project_root()
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._static: dict[str, Any] = {}
		self._live: dict[str, Any] = {}
		self._static_loaded = False
		self._running = False
		self._stop_event: threading.Event | None = None
		self._thread: threading.Thread | None = None
		self._provider_warnings: set[str] = set()
		self._last_uptime_seconds: int | None = None
		self._logged_first_telemetry = False
		self._kernel32: Any = None

	def subscribe(self, listener: Callable[[dict], None]) -> None:
		with self._lock:
			if listener not in self._listeners:
				self._listeners.append(listener)

	def unsubscribe(self, listener: Callable[[dict], None]) -> None:
		with self._lock:
			if listener in self._listeners:
				self._listeners.remove(listener)

	def start(self) -> None:
		with self._lock:
			if self._running:
				return
			self._running = True
			self._stop_event = threading.Event()
			self._logged_first_telemetry = False
			self._last_uptime_seconds = None
			settings = dict(self._settings)
		self._ensure_static(settings)
		self._reconcile_uptime(settings)
		if not settings.get("Show System Uptime"):
			self._log_first_telemetry()
		else:
			self._notify()

	def stop(self) -> None:
		with self._lock:
			if not self._running and self._thread is None:
				return
			self._running = False
			stop_event = self._stop_event
			thread = self._thread
			self._thread = None
		if stop_event is not None:
			stop_event.set()
		if thread is not None and thread is not threading.current_thread():
			thread.join(timeout=SAMPLE_INTERVAL_SECONDS + 2)
		with self._lock:
			self._live = {}
			self._stop_event = None
		self._last_uptime_seconds = None
		self._notify()

	def is_running(self) -> bool:
		with self._lock:
			return self._running

	def update_settings(self, settings: dict[str, bool]) -> None:
		if not isinstance(settings, dict):
			raise ValueError("System settings must be an object")
		with self._lock:
			self._settings = {key: bool(settings.get(key, False)) for key in _SETTINGS}
			running = self._running
			current = dict(self._settings)
		if not running:
			return
		self._ensure_static(current)
		self._reconcile_uptime(current)
		self._notify()

	def get_latest(self) -> dict:
		with self._lock:
			settings = dict(self._settings)
			hardware: dict[str, Any] = {}
			live: dict[str, Any] = {}
			if settings.get("Show Device Name") and self._static.get("device_name"):
				hardware["device_name"] = self._static["device_name"]
			if settings.get("Show Operating System") and self._static.get("operating_system"):
				hardware["operating_system"] = self._static["operating_system"]
			if settings.get("Show OS Version"):
				version = {}
				for key in ("version", "build"):
					if self._static.get(key) is not None:
						version[key] = self._static[key]
				if version:
					hardware["os_version"] = version
			if settings.get("Show Architecture") and self._static.get("architecture"):
				hardware["architecture"] = self._static["architecture"]
			if settings.get("Show Last Boot Time") and self._static.get("last_boot_time_utc"):
				hardware["last_boot_time_utc"] = self._static["last_boot_time_utc"]
			if settings.get("Show System Uptime") and "uptime_seconds" in self._live:
				live["uptime_seconds"] = self._live["uptime_seconds"]
			return {"hardware": copy.deepcopy(hardware), "live": copy.deepcopy(live)}

	def get_metric_snapshot(self) -> dict[str, Any]:

		latest = self.get_latest()
		hardware = latest.get("hardware", {})
		live = latest.get("live", {})
		os_version = hardware.get("os_version") if isinstance(hardware.get("os_version"), dict) else {}

		return {
			"System_Device_Name": hardware.get("device_name"),
			"System_OS_Name": hardware.get("operating_system"),
			"System_OS_Version": os_version.get("version"),
			"System_OS_Build": os_version.get("build"),
			"System_Architecture": hardware.get("architecture"),
			"System_Last_Boot_Time": hardware.get("last_boot_time_utc"),
			"System_Uptime": live.get("uptime_seconds"),
		}

	@staticmethod
	def _format_uptime(seconds: Any) -> str:
		if seconds is None:
			return "Unavailable"
		try:
			total_seconds = max(0, int(seconds))
		except (TypeError, ValueError):
			return str(seconds)
		days, remainder = divmod(total_seconds, 86400)
		hours, remainder = divmod(remainder, 3600)
		minutes, secs = divmod(remainder, 60)
		parts = []
		if days:
			parts.append(f"{days}d")
		if days or hours:
			parts.append(f"{hours}h")
		if days or hours or minutes:
			parts.append(f"{minutes}m")
		parts.append(f"{secs}s")
		return " ".join(parts)

	def _print_system_module_block(self) -> None:
		metrics = self.get_metric_snapshot()
		lines = ["-" * 60, "System_Module"]
		for metric_id, value in metrics.items():
			if metric_id == "System_Uptime":
				display_value = self._format_uptime(value)
			else:
				display_value = value if value is not None else "Unavailable"
			lines.append(f"{metric_id}: {display_value}")
		lines.append("-" * 60)
		print_raw("\n".join(lines))

	def _ensure_static(self, settings: dict[str, bool]) -> None:
		if not any(settings.get(key, False) for key in _STATIC_SETTINGS):
			return
		with self._lock:
			if self._static_loaded:
				return
		static = self._query_cim()
		if not static:
			static = {}
		fallback_name = self._clean_text(socket.gethostname())
		if not static.get("device_name") and fallback_name:
			static["device_name"] = fallback_name
		if not static.get("last_boot_time_utc") and psutil is not None:
			try:
				static["last_boot_time_utc"] = self._epoch_to_utc(float(psutil.boot_time()))
			except Exception as error:
				self._warn_once("boot", "System boot-time fallback unavailable: %s", error)
		with self._lock:
			self._static = static
			self._static_loaded = True

	def _query_cim(self) -> dict[str, Any]:
		command = (
			"$ErrorActionPreference='Stop'; "
			"$os = Get-CimInstance -ClassName Win32_OperatingSystem; "
			"[pscustomobject]@{ "
			"DeviceName=$os.CSName; OperatingSystem=$os.Caption; Version=$os.Version; "
			"BuildNumber=$os.BuildNumber; Architecture=$os.OSArchitecture; "
			"LastBootTimeUtc=$os.LastBootUpTime.ToUniversalTime().ToString('o') "
			"} | ConvertTo-Json -Compress"
		)
		startupinfo = None
		if os.name == "nt":
			startupinfo = subprocess.STARTUPINFO()
			startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
			startupinfo.wShowWindow = subprocess.SW_HIDE
		try:
			result = subprocess.run(
				["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "-"],
				input=command,
				capture_output=True, text=True, timeout=CIM_TIMEOUT_SECONDS,
				startupinfo=startupinfo, check=True,
			)
			if not result.stdout.strip():
				return {}
			parsed = json.loads(result.stdout)
			return self._normalize_static(parsed) if isinstance(parsed, dict) else {}
		except Exception as error:
			self._warn_once("cim", "System CIM discovery unavailable: %s", error)
			return {}

	def _normalize_static(self, data: dict[str, Any]) -> dict[str, Any]:
		result: dict[str, Any] = {}
		mapping = {
			"device_name": data.get("DeviceName"),
			"operating_system": data.get("OperatingSystem"),
			"version": data.get("Version"),
			"build": data.get("BuildNumber"),
			"architecture": data.get("Architecture"),
		}
		for key, value in mapping.items():
			cleaned = self._clean_text(value)
			if not cleaned:
				continue
			if key == "operating_system":
				cleaned = self._clean_os_name(cleaned)
			result[key] = cleaned
		boot = self._clean_text(data.get("LastBootTimeUtc"))
		if boot:
			result["last_boot_time_utc"] = self._normalize_utc(boot)
		return result

	def _reconcile_uptime(self, settings: dict[str, bool]) -> None:
		needs_uptime = settings.get("Show System Uptime", False)
		with self._lock:
			if not self._running:
				return
			thread = self._thread
			if needs_uptime and thread is None:
				stop_event = threading.Event()
				self._stop_event = stop_event
				self._thread = threading.Thread(target=self._sample_loop, args=(stop_event,), name="StatMonitorSystem", daemon=True)
				self._thread.start()
			elif not needs_uptime and thread is not None:
				self._thread = None
				if self._stop_event is not None:
					self._stop_event.set()

	def _sample_loop(self, stop_event: threading.Event) -> None:
		try:
			while True:
				with self._lock:
					running = self._running
				if not running or stop_event is None or stop_event.is_set():
					return
				self._collect_uptime()
				if stop_event.wait(SAMPLE_INTERVAL_SECONDS):
					return
		finally:
			with self._lock:
				if self._thread is threading.current_thread():
					self._thread = None

	def _collect_uptime(self) -> None:
		seconds = self._get_uptime_seconds()
		if seconds is None:
			return
		with self._lock:
			if not self._running or seconds == self._last_uptime_seconds:
				return
			self._last_uptime_seconds = seconds
			self._live = {"uptime_seconds": seconds}
		self._log_first_telemetry()
		self._notify()

	def _get_uptime_seconds(self) -> int | None:
		try:
			if self._kernel32 is None and os.name == "nt":
				self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
				self._kernel32.GetTickCount64.restype = ctypes.c_ulonglong
			if self._kernel32 is not None:
				return int(self._kernel32.GetTickCount64() // 1000)
			if psutil is not None:
				return max(0, int(dt.datetime.now(dt.timezone.utc).timestamp() - psutil.boot_time()))
		except Exception as error:
			self._warn_once("uptime", "System uptime provider unavailable: %s", error)
		return None

	def _log_first_telemetry(self) -> None:
		with self._lock:
			if self._logged_first_telemetry:
				return
			self._logged_first_telemetry = True
		self._print_system_module_block()

	def _notify(self) -> None:
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				LOGGER.exception("StatMonitor System listener failed")

	@staticmethod
	def _clean_text(value: Any) -> str | None:
		if value is None:
			return None
		text = str(value).strip()
		return text or None

	@staticmethod
	def _clean_os_name(value: str) -> str:
		text = str(value).strip()
		if text.lower().startswith("microsoft "):
			text = text[len("Microsoft "):].strip()
		return text

	@staticmethod
	def _normalize_utc(value: str) -> str:
		try:
			parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
			if parsed.tzinfo is None:
				parsed = parsed.replace(tzinfo=dt.timezone.utc)
			return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
		except ValueError:
			return value

	@staticmethod
	def _epoch_to_utc(value: float) -> str:
		return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")

	def _warn_once(self, key: str, message: str, *args) -> None:
		with self._lock:
			if key in self._provider_warnings:
				return
			self._provider_warnings.add(key)
		LOGGER.warning(message, *args)
