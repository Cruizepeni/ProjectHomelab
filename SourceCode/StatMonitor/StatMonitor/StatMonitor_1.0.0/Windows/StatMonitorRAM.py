

from __future__ import annotations

from StatMonitorOutput import print_raw

import copy
import json
import logging
import os
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

_SETTINGS = (
	"Show Individual RAM Units", "Show RAM Name", "Show RAM Type",
	"Show RAM Size", "Show RAM Speed", "Show Current RAM Usage",
	"Show Available RAM",
)

_SMBIOS_MEMORY_TYPES = {
	20: "DDR", 21: "DDR2", 22: "DDR2 FB-DIMM", 24: "DDR3",
	26: "DDR4", 27: "LPDDR", 28: "LPDDR2", 29: "LPDDR3",
	30: "LPDDR4", 34: "DDR5", 35: "LPDDR5",
}


class StatMonitorRAM:


	def __init__(self, project_root: str | os.PathLike[str] | None = None):
		self.project_root = Path(project_root) if project_root else resolve_project_root()
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._modules: list[dict[str, Any]] = []
		self._live: dict[str, Any] = {}
		self._inventory_loaded = False
		self._running = False
		self._stop_event: threading.Event | None = None
		self._thread: threading.Thread | None = None
		self._provider_warnings: set[str] = set()
		self._logged_first_telemetry = False

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
			settings = dict(self._settings)
		self._ensure_inventory(settings)
		self._reconcile_sampling(settings)
		if not (
			settings.get("Show Current RAM Usage", False)
			or settings.get("Show Available RAM", False)
		):
			self._log_first_telemetry()
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
		self._notify()

	def is_running(self) -> bool:
		with self._lock:
			return self._running

	def update_settings(self, settings: dict[str, bool]) -> None:
		if not isinstance(settings, dict):
			raise ValueError("RAM settings must be an object")
		with self._lock:
			self._settings = {key: bool(settings.get(key, False)) for key in _SETTINGS}
			running = self._running
			current = dict(self._settings)
		if not running:
			return
		self._ensure_inventory(current)
		self._reconcile_sampling(current)
		self._notify()

	def get_latest(self) -> dict:
		with self._lock:
			settings = dict(self._settings)
			hardware: dict[str, Any] = {}
			live: dict[str, Any] = {}
			if settings.get("Show RAM Size"):
				capacities = [module["capacity_bytes"] for module in self._modules if module.get("capacity_bytes") is not None]
				if capacities:
					hardware["total_installed_bytes"] = sum(capacities)
			if settings.get("Show RAM Name"):
				names = self._unique_values(module.get("name") for module in self._modules)
				if names:
					hardware["names"] = names
			if settings.get("Show RAM Type"):
				types = self._unique_values(module.get("type") for module in self._modules)
				if types:
					hardware["types"] = types
			if settings.get("Show RAM Speed"):
				speeds = self._unique_values(module.get("speed_mhz") for module in self._modules)
				if speeds:
					hardware["speeds_mhz"] = speeds
			if settings.get("Show Individual RAM Units"):
				hardware["modules"] = [self._filtered_module(module, settings) for module in self._modules]
			if settings.get("Show Current RAM Usage"):
				for key in ("usage_percent", "used_bytes"):
					if key in self._live:
						live[key] = self._live[key]
			if settings.get("Show Available RAM") and "available_bytes" in self._live:
				live["available_bytes"] = self._live["available_bytes"]
			return {"hardware": copy.deepcopy(hardware), "live": copy.deepcopy(live)}


	def get_metric_snapshot(self) -> dict[str, Any]:

		latest = self.get_latest()
		hardware = latest.get("hardware", {})
		live = latest.get("live", {})

		units = []
		for module in hardware.get("modules", []) or []:
			if not isinstance(module, dict):
				continue
			item = {}
			if module.get("slot") is not None:
				item["RAM_Unit_Slot"] = module.get("slot")
			if module.get("name") is not None:
				item["RAM_Unit_Name"] = module.get("name")
			if module.get("type") is not None:
				item["RAM_Unit_Type"] = module.get("type")
			if module.get("capacity_bytes") is not None:
				item["RAM_Unit_Size"] = module.get("capacity_bytes")
			if module.get("speed_mhz") is not None:
				item["RAM_Unit_Speed"] = module.get("speed_mhz")
			if item:
				units.append(item)

		return {
			"RAM_Total_Installed": hardware.get("total_installed_bytes"),
			"RAM_Names": copy.deepcopy(hardware.get("names", [])),
			"RAM_Types": copy.deepcopy(hardware.get("types", [])),
			"RAM_Speeds": copy.deepcopy(hardware.get("speeds_mhz", [])),
			"RAM_Utilisation": live.get("usage_percent"),
			"RAM_Used": live.get("used_bytes"),
			"RAM_Available": live.get("available_bytes"),
			"RAM_Individual_Units": units,
		}

	def _print_ram_module_block(self) -> None:
		metrics = self.get_metric_snapshot()
		lines = ["-" * 60, "RAM_Module"]

		def format_bytes(value: Any) -> str:
			if value is None:
				return "Unavailable"
			try:
				return f"{float(value) / (1024 ** 3):.1f} GiB"
			except (TypeError, ValueError):
				return str(value)

		def format_mhz(value: Any) -> str:
			if value is None:
				return "Unavailable"
			return f"{value} MHz"

		def format_percent(value: Any) -> str:
			if value is None:
				return "Unavailable"
			return f"{value}%"

		for metric_id, value in metrics.items():
			if metric_id == "RAM_Total_Installed":
				lines.append(f"{metric_id}: {format_bytes(value)}")
				continue

			if metric_id == "RAM_Speeds":
				speeds = value if isinstance(value, list) else []
				lines.append(
					f"{metric_id}: "
					f"{', '.join(format_mhz(item) for item in speeds) if speeds else 'Unavailable'}"
				)
				continue

			if metric_id == "RAM_Utilisation":
				lines.append(f"{metric_id}: {format_percent(value)}")
				continue

			if metric_id in ("RAM_Used", "RAM_Available"):
				lines.append(f"{metric_id}: {format_bytes(value)}")
				continue

			if metric_id == "RAM_Individual_Units":
				units = value if isinstance(value, list) else []
				lines.append(f"{metric_id}: {len(units)}")
				for index, unit in enumerate(units, 1):
					lines.append(f"  [{index}]")
					for child_id, child_value in unit.items():
						if child_id == "RAM_Unit_Size":
							display_value = format_bytes(child_value)
						elif child_id == "RAM_Unit_Speed":
							display_value = format_mhz(child_value)
						else:
							display_value = child_value if child_value is not None else "Unavailable"
						lines.append(f"    {child_id}: {display_value}")
				continue

			if isinstance(value, list):
				lines.append(
					f"{metric_id}: {', '.join(str(item) for item in value) if value else 'Unavailable'}"
				)
				continue

			lines.append(f"{metric_id}: {value if value is not None else 'Unavailable'}")

		lines.append("-" * 60)
		print_raw("\n".join(lines))

	def _log_first_telemetry(self) -> None:
		with self._lock:
			if self._logged_first_telemetry:
				return
			self._logged_first_telemetry = True
		self._print_ram_module_block()

	def _filtered_module(self, module: dict[str, Any], settings: dict[str, bool]) -> dict[str, Any]:
		filtered = {"slot": module["slot"]}
		if settings.get("Show RAM Name") and module.get("name"):
			filtered["name"] = module["name"]
		if settings.get("Show RAM Type") and module.get("type"):
			filtered["type"] = module["type"]
		if settings.get("Show RAM Size") and module.get("capacity_bytes") is not None:
			filtered["capacity_bytes"] = module["capacity_bytes"]
		if settings.get("Show RAM Speed") and module.get("speed_mhz") is not None:
			filtered["speed_mhz"] = module["speed_mhz"]
		return filtered

	@staticmethod
	def _unique_values(values) -> list[Any]:
		result = []
		for value in values:
			if value is not None and value not in result:
				result.append(value)
		return result

	def _ensure_inventory(self, settings: dict[str, bool]) -> None:
		needs_inventory = any(settings.get(key, False) for key in (
			"Show Individual RAM Units", "Show RAM Name", "Show RAM Type",
			"Show RAM Size", "Show RAM Speed",
		))
		with self._lock:
			if not needs_inventory or self._inventory_loaded:
				return
		rows = self._query_cim()
		modules = [self._normalize_module(row, index) for index, row in enumerate(rows, 1)]
		with self._lock:
			self._inventory_loaded = True
			self._modules = [module for module in modules if module is not None]

	def _query_cim(self) -> list[dict[str, Any]]:
		command = (
			"$ErrorActionPreference='Stop'; "
			"Get-CimInstance -ClassName Win32_PhysicalMemory | "
			"Select-Object Manufacturer,PartNumber,Model,Name,Capacity,ConfiguredClockSpeed,Speed,"
			"SMBIOSMemoryType,MemoryType,DeviceLocator,BankLabel | ConvertTo-Json -Compress"
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
				return []
			parsed = json.loads(result.stdout)
			return parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else []
		except Exception as error:
			self._warn_once("cim", "RAM CIM discovery unavailable: %s", error)
			return []

	def _normalize_module(self, row: dict[str, Any], index: int) -> dict[str, Any] | None:
		if not isinstance(row, dict):
			return None
		capacity = self._positive_int(row.get("Capacity"))
		name = self._module_name(row)
		memory_type = self._memory_type(row.get("SMBIOSMemoryType"), row.get("MemoryType"))
		speed = self._positive_int(row.get("ConfiguredClockSpeed")) or self._positive_int(row.get("Speed"))
		slot = self._clean_text(row.get("DeviceLocator")) or self._clean_text(row.get("BankLabel")) or f"Memory Module #{index}"
		return {
			"slot": slot,
			"name": name,
			"type": memory_type,
			"capacity_bytes": capacity,
			"speed_mhz": speed,
		}

	def _module_name(self, row: dict[str, Any]) -> str | None:
		manufacturer = self._clean_text(row.get("Manufacturer"))
		part_number = self._clean_text(row.get("PartNumber"))
		model = self._clean_text(row.get("Model"))
		firmware_name = self._clean_text(row.get("Name"))
		if manufacturer and part_number:
			return f"{manufacturer} {part_number}"
		for value in (part_number, model, firmware_name, manufacturer):
			if value and value.lower() not in {"physical memory", "unknown", "none"}:
				return value
		return None

	@staticmethod
	def _memory_type(smbios_type: Any, legacy_type: Any) -> str:
		for value in (smbios_type, legacy_type):
			try:
				mapped = _SMBIOS_MEMORY_TYPES.get(int(value))
				if mapped:
					return mapped
			except (TypeError, ValueError):
				continue
		return "Unknown"

	@staticmethod
	def _clean_text(value: Any) -> str | None:
		if value is None:
			return None
		text = str(value).strip()
		return text or None

	@staticmethod
	def _positive_int(value: Any) -> int | None:
		try:
			converted = int(value)
			return converted if converted > 0 else None
		except (TypeError, ValueError):
			return None

	def _reconcile_sampling(self, settings: dict[str, bool]) -> None:
		needs_sampling = settings.get("Show Current RAM Usage", False) or settings.get("Show Available RAM", False)
		with self._lock:
			if not self._running:
				return
			thread = self._thread
			if needs_sampling and thread is None:
				self._stop_event = threading.Event()
				self._thread = threading.Thread(target=self._sample_loop, name="StatMonitorRAM", daemon=True)
				self._thread.start()
			elif not needs_sampling and thread is not None:
				self._thread = None
				if self._stop_event is not None:
					self._stop_event.set()

	def _sample_loop(self) -> None:
		with self._lock:
			stop_event = self._stop_event
		try:
			while True:
				with self._lock:
					running = self._running
					settings = dict(self._settings)
				if not running or stop_event is None or stop_event.is_set():
					return
				self._collect_sample(settings)
				if stop_event.wait(SAMPLE_INTERVAL_SECONDS):
					return
		finally:
			with self._lock:
				if self._thread is threading.current_thread():
					self._thread = None

	def _collect_sample(self, settings: dict[str, bool]) -> None:
		if psutil is None:
			self._warn_once("psutil", "RAM live statistics unavailable: psutil is not installed")
			self._log_first_telemetry()
			return
		try:
			memory = psutil.virtual_memory()
			live = {
				"usage_percent": round(float(memory.percent), 1),
				"used_bytes": int(memory.used),
				"available_bytes": int(memory.available),
			}
		except Exception as error:
			self._warn_once("psutil", "RAM live statistics unavailable: %s", error)
			self._log_first_telemetry()
			return
		with self._lock:
			if not self._running:
				return
			self._live = live
		self._log_first_telemetry()
		self._notify()

	def _notify(self) -> None:
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				LOGGER.exception("StatMonitor RAM listener failed")

	def _warn_once(self, key: str, message: str, *args) -> None:
		with self._lock:
			if key in self._provider_warnings:
				return
			self._provider_warnings.add(key)
		LOGGER.warning(message, *args)
