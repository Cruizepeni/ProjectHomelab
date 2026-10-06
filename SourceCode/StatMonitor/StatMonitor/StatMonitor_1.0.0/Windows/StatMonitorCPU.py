




from __future__ import annotations

from StatMonitorOutput import print_raw

import copy
import json
import logging
import os
import platform
import re
import subprocess
import threading
import time
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
LHM_RETRY_INTERVAL_SECONDS = 5.0
_ARMOURY_PROCESS_FAMILIES = (
	"armourycrate",
	"armourysocketserver",
	"armouryswagent",
	"rogliveservice",
)
LHM_TYPES: tuple[Any, Any] | None = None
LHM_TYPES_LOCK = threading.Lock()


class StatMonitorCPU:


	def __init__(self, project_root: str | os.PathLike[str] | None = None):
		self.project_root = Path(project_root) if project_root else resolve_project_root()
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._hardware: dict[str, Any] = {}
		self._live: dict[str, Any] = {}
		self._running = False
		self._stop_event: threading.Event | None = None
		self._thread: threading.Thread | None = None
		self._lhm_computer: Any = None
		self._lhm_hardware: list[Any] = []
		self._provider_warnings: set[str] = set()
		self._internal_power_consumers: set[str] = set()
		self._usage_primed = False
		self._logged_first_live_sample = False
		self._armoury_running: bool | None = None
		self._lhm_retry_after = 0.0
		self._lhm_restore_pending = False

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
			self._usage_primed = False
			self._logged_first_live_sample = False
			self._armoury_running = None
			self._lhm_retry_after = 0.0
			self._lhm_restore_pending = False
			settings = dict(self._settings)
		try:
			self._ensure_static_hardware(settings)
			self._configure_providers(settings)
			self._start_sampling_if_needed(settings)
		except Exception:
			with self._lock:
				self._running = False
				self._close_lhm_locked()
			raise
		self._notify()
		if not any(settings.get(key, False) for key in (
			"Show Current Usage", "Show Clock Speed", "Show Temperature",
			"Show Power Usage", "Show Individual Cores",
		)) and not self._internal_power_consumers:
			self._print_cpu_module_block()

	def stop(self) -> None:
		with self._lock:
			if not self._running and self._thread is None and self._lhm_computer is None:
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
			self._close_lhm_locked()
		self._live = {}
		self._notify()

	def is_running(self) -> bool:
		with self._lock:
			return self._running

	def set_internal_power_request(self, consumer_id: str, enabled: bool) -> None:
		with self._lock:
			if enabled:
				self._internal_power_consumers.add(str(consumer_id))
			else:
				self._internal_power_consumers.discard(str(consumer_id))
			running = self._running
			settings = dict(self._settings)
		if running:
			self._configure_providers(settings)
			self._start_sampling_if_needed(settings)

	def get_internal_power_w(self) -> float | None:
		with self._lock:
			value = self._live.get("power_w")
		try:
			value = float(value)
			return value if value >= 0 and value == value else None
		except (TypeError, ValueError):
			return None

	def update_settings(self, settings: dict[str, bool]) -> None:
		if not isinstance(settings, dict):
			raise ValueError("CPU settings must be an object")
		with self._lock:
			self._settings = {key: bool(settings.get(key, False)) for key in (
				"Show CPU Name", "Show Core And Thread Count", "Show Clock Speed",
				"Show Current Usage", "Show Temperature", "Show Power Usage",
				"Show Individual Cores",
			)}
			running = self._running
			current = dict(self._settings)
		if not running:
			return
		self._ensure_static_hardware(current)
		self._configure_providers(current)
		self._start_sampling_if_needed(current)
		self._notify()

	def get_latest(self) -> dict:
		with self._lock:
			settings = dict(self._settings)
			hardware = {}
			live = {}
			if settings.get("Show CPU Name"):
				if self._hardware.get("brand"):
					hardware["brand"] = self._hardware["brand"]
				if self._hardware.get("name"):
					hardware["name"] = self._hardware["name"]
			if settings.get("Show Core And Thread Count"):
				for key in ("physical_cores", "logical_processors"):
					if key in self._hardware:
						hardware[key] = self._hardware[key]
			if settings.get("Show Clock Speed") and "base_clock_mhz" in self._hardware:
				hardware["base_clock_mhz"] = self._hardware["base_clock_mhz"]
			for key in ("usage_percent", "clock", "temperature_c", "power_w", "individual_cores"):
				if key in self._live and self._metric_enabled(key, settings):
					live[key] = copy.deepcopy(self._live[key])
			return {"hardware": hardware, "live": live}

	def get_metric_snapshot(self) -> dict[str, Any]:

		latest = self.get_latest()
		hardware = latest.get("hardware", {})
		live = latest.get("live", {})
		clock = live.get("clock") if isinstance(live.get("clock"), dict) else {}

		individual = []
		for entry in live.get("individual_cores", []) or []:
			if not isinstance(entry, dict):
				continue
			item = {}
			if entry.get("name") is not None:
				item["CPU_Individual_Processor_Name"] = entry.get("name")
			if entry.get("usage_percent") is not None:
				item["CPU_Individual_Processor_Utilisation"] = entry.get("usage_percent")
			if entry.get("clock_mhz") is not None:
				item["CPU_Individual_Processor_Clock_Speed"] = entry.get("clock_mhz")
			if entry.get("temperature_c") is not None:
				item["CPU_Individual_Processor_Temperature"] = entry.get("temperature_c")
			if item:
				individual.append(item)

		return {
			"CPU_Brand": hardware.get("brand"),
			"CPU_Name": hardware.get("name"),
			"CPU_Physical_Core_Count": hardware.get("physical_cores"),
			"CPU_Logical_Processor_Count": hardware.get("logical_processors"),
			"CPU_Base_Clock_Speed": hardware.get("base_clock_mhz"),
			"CPU_Max_Boost_Clock_Speed": self._hardware.get("max_boost_clock_mhz"),
			"CPU_Clock_Speed": clock.get("average_mhz"),
			"CPU_Utilisation": live.get("usage_percent"),
			"CPU_Temperature": live.get("temperature_c"),
			"CPU_Power_Usage": live.get("power_w"),
			"CPU_Individual_Processors": individual,
		}

	def _print_cpu_module_block(self) -> None:
		metrics = self.get_metric_snapshot()

		def format_metric(metric_id: str, value: Any) -> str:
			if value is None:
				return "Unavailable"
			if metric_id in (
				"CPU_Base_Clock_Speed",
				"CPU_Max_Boost_Clock_Speed",
				"CPU_Clock_Speed",
				"CPU_Individual_Processor_Clock_Speed",
			):
				return f"{value} MHz"
			if metric_id in (
				"CPU_Utilisation",
				"CPU_Individual_Processor_Utilisation",
			):
				return f"{value}%"
			if metric_id in (
				"CPU_Temperature",
				"CPU_Individual_Processor_Temperature",
			):
				return f"{value} °C"
			if metric_id == "CPU_Power_Usage":
				return f"{value} W"
			return str(value)

		lines = ["-" * 60, "CPU_Module"]
		for metric_id, value in metrics.items():
			if metric_id != "CPU_Individual_Processors":
				lines.append(f"{metric_id}: {format_metric(metric_id, value)}")
				continue
			processors = value if isinstance(value, list) else []
			lines.append(f"{metric_id}: {len(processors)}")
			for index, processor in enumerate(processors, 1):
				lines.append(f"  [{index}]")
				for child_id, child_value in processor.items():
					lines.append(f"    {child_id}: {format_metric(child_id, child_value)}")
		lines.append("-" * 60)
		print_raw("\n".join(lines))

	def _metric_enabled(self, key: str, settings: dict[str, bool]) -> bool:
		return {
			"usage_percent": settings.get("Show Current Usage", False),
			"clock": settings.get("Show Clock Speed", False),
			"temperature_c": settings.get("Show Temperature", False),
			"power_w": settings.get("Show Power Usage", False),
			"individual_cores": settings.get("Show Individual Cores", False),
		}.get(key, False)

	def _ensure_static_hardware(self, settings: dict[str, bool]) -> None:
		if not (settings.get("Show CPU Name") or settings.get("Show Core And Thread Count") or settings.get("Show Clock Speed")):
			return
		with self._lock:
			if self._hardware:
				return
		hardware = self._query_cim()
		if psutil is not None:
			fallback = {
				"physical_cores": psutil.cpu_count(logical=False),
				"logical_processors": psutil.cpu_count(logical=True),
				"raw_name": self._platform_cpu_name(),
			}
			for key, value in fallback.items():
				if value is not None:
					hardware.setdefault(key, value)

		raw_name = hardware.get("raw_name") or hardware.get("name")
		brand = self._clean_cpu_brand(hardware.get("manufacturer"), raw_name)
		clean_name = self._clean_cpu_name(raw_name, brand)
		if brand:
			hardware["brand"] = brand
		if clean_name:
			hardware["name"] = clean_name
		elif raw_name:
			hardware["name"] = str(raw_name).strip()



		hardware.setdefault("max_boost_clock_mhz", None)

		with self._lock:
			self._hardware = {key: value for key, value in hardware.items() if value is not None}

	def _query_cim(self) -> dict[str, Any]:
		command = (
			"$ErrorActionPreference='Stop'; "
			"Get-CimInstance -ClassName Win32_Processor | "
			"Select-Object Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed | "
			"ConvertTo-Json -Compress"
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
			parsed = json.loads(result.stdout)
			rows = parsed if isinstance(parsed, list) else [parsed]
			rows = [row for row in rows if isinstance(row, dict)]
			if not rows:
				return {}
			physical = self._sum_valid(rows, "NumberOfCores")
			logical = self._sum_valid(rows, "NumberOfLogicalProcessors")
			base_clock = self._max_valid(rows, "MaxClockSpeed")
			result_data: dict[str, Any] = {}
			raw_name = next((str(row["Name"]).strip() for row in rows if row.get("Name")), None)
			manufacturer = next((str(row["Manufacturer"]).strip() for row in rows if row.get("Manufacturer")), None)
			if raw_name:
				result_data["raw_name"] = raw_name
			if manufacturer:
				result_data["manufacturer"] = manufacturer
			if physical is not None:
				result_data["physical_cores"] = physical
			if logical is not None:
				result_data["logical_processors"] = logical
			if base_clock is not None:
				result_data["base_clock_mhz"] = base_clock
			return result_data
		except Exception as error:
			self._warn_once("cim", "CPU CIM discovery unavailable: %s", error)
			return {}

	@staticmethod
	def _sum_valid(rows: list[dict], key: str) -> int | None:
		values = []
		for row in rows:
			try:
				value = int(row.get(key))
				if value > 0:
					values.append(value)
			except (TypeError, ValueError):
				continue
		return sum(values) if values else None

	@staticmethod
	def _max_valid(rows: list[dict], key: str) -> float | None:
		values = []
		for row in rows:
			try:
				value = float(row.get(key))
				if value > 0:
					values.append(value)
			except (TypeError, ValueError):
				continue
		return round(max(values), 1) if values else None

	@staticmethod
	def _platform_cpu_name() -> str | None:
		name = platform.processor().strip()
		return name or None

	@staticmethod
	def _clean_cpu_brand(manufacturer: Any, raw_name: Any) -> str | None:
		manufacturer_text = str(manufacturer or "").strip()
		manufacturer_map = {
			"GenuineIntel": "Intel",
			"AuthenticAMD": "AMD",
			"Apple": "Apple",
		}
		if manufacturer_text in manufacturer_map:
			return manufacturer_map[manufacturer_text]
		for known in ("Intel", "AMD", "Apple", "Qualcomm", "ARM", "Ampere", "IBM"):
			if known.lower() in manufacturer_text.lower():
				return known
		name_text = str(raw_name or "").strip()
		for known in ("Intel", "AMD", "Apple", "Qualcomm", "ARM", "Ampere", "IBM"):
			if re.search(rf"\b{re.escape(known)}\b", name_text, re.IGNORECASE):
				return known
		return manufacturer_text or None

	@staticmethod
	def _clean_cpu_name(raw_name: Any, brand: str | None) -> str | None:
		name = str(raw_name or "").strip()
		if not name:
			return None
		name = re.sub(r"\((?:R|TM|C)\)", "", name, flags=re.IGNORECASE)
		name = re.sub(r"\s+", " ", name).strip()
		if brand:
			name = re.sub(rf"^{re.escape(brand)}\s+", "", name, flags=re.IGNORECASE)
		name = re.sub(r"\s+CPU\s*@\s*.+$", "", name, flags=re.IGNORECASE)
		name = re.sub(r"\s+Processor\s*$", "", name, flags=re.IGNORECASE)
		name = re.sub(r"\s+CPU\s*$", "", name, flags=re.IGNORECASE)
		return name.strip() or None

	def _configure_providers(self, settings: dict[str, bool]) -> None:
		needs_lhm = self._needs_lhm(settings)
		armoury_running = self._is_armoury_running() if needs_lhm else False
		with self._lock:
			if needs_lhm:
				self._update_armoury_state_locked(armoury_running)
				if armoury_running:
					if self._lhm_computer is not None:
						self._close_lhm_locked()
					self._lhm_restore_pending = True
				elif self._lhm_computer is None:
					self._open_lhm_locked()
			else:
				self._armoury_running = None
				self._lhm_restore_pending = False
				if self._lhm_computer is not None:
					self._close_lhm_locked()
			if needs_lhm and settings.get("Show CPU Name") and "name" not in self._hardware:
				for hardware in self._lhm_hardware:
					try:
						name = str(hardware.Name).strip()
						if name:
							self._hardware["name"] = name
							break
					except Exception:
						continue

	def _start_sampling_if_needed(self, settings: dict[str, bool]) -> None:
		needs_sampling = any(settings.get(key, False) for key in (
			"Show Current Usage", "Show Clock Speed", "Show Temperature", "Show Power Usage", "Show Individual Cores"
		)) or bool(self._internal_power_consumers)
		with self._lock:
			if not self._running or not needs_sampling or self._thread is not None:
				return
			if psutil is not None and (settings.get("Show Current Usage") or settings.get("Show Individual Cores")):
				try:
					psutil.cpu_percent(interval=None)
					self._usage_primed = True
				except Exception as error:
					self._warn_once("psutil", "CPU utilization provider unavailable: %s", error)
			self._stop_event = self._stop_event or threading.Event()
			self._thread = threading.Thread(target=self._sample_loop, name="StatMonitorCPU", daemon=True)
			self._thread.start()

	def _sample_loop(self) -> None:
		while True:
			with self._lock:
				stop_event = self._stop_event
				running = self._running
				settings = dict(self._settings)
			if not running or stop_event is None or stop_event.is_set():
				return
			try:
				self._collect_sample(settings)
			except Exception as error:
				self._warn_once("sample", "CPU sample failed: %s", error)
			if stop_event.wait(SAMPLE_INTERVAL_SECONDS):
				return

	def _collect_sample(self, settings: dict[str, bool]) -> None:
		live: dict[str, Any] = {}
		if settings.get("Show Current Usage") or settings.get("Show Individual Cores"):
			if psutil is not None and self._usage_primed:
				try:
					live["usage_percent"] = self._number(psutil.cpu_percent(interval=None))
					if settings.get("Show Individual Cores"):
						per_cpu = psutil.cpu_percent(interval=None, percpu=True)
						live["individual_cores"] = [
							{"name": f"Logical Processor #{index}", "usage_percent": self._number(value)}
							for index, value in enumerate(per_cpu, 1)
						]
				except Exception as error:
					self._warn_once("psutil", "CPU utilization sample unavailable: %s", error)
		if settings.get("Show Clock Speed") and psutil is not None and "clock" not in live:
			try:
				frequency = psutil.cpu_freq()
				if frequency and frequency.current > 0:
					live["clock"] = {"average_mhz": self._number(frequency.current),
						"max_core_mhz": self._number(frequency.current)}
				if settings.get("Show Individual Cores"):
					per_cpu_frequency = psutil.cpu_freq(percpu=True)
					for entry, value in zip(live.get("individual_cores", []), per_cpu_frequency or []):
						if value and value.current > 0:
							entry["clock_mhz"] = self._number(value.current)
			except Exception as error:
				self._warn_once("psutil-frequency", "CPU frequency provider unavailable: %s", error)
		needs_lhm = self._needs_lhm(settings)
		armoury_running = self._is_armoury_running() if needs_lhm else False
		with self._lock:
			if needs_lhm:
				self._update_armoury_state_locked(armoury_running)
				if armoury_running:
					if self._lhm_computer is not None:
						self._close_lhm_locked()
					self._lhm_restore_pending = True
				elif self._lhm_computer is None and time.monotonic() >= self._lhm_retry_after:
					self._open_lhm_locked()
			else:
				self._armoury_running = None
				self._lhm_restore_pending = False
			computer_available = self._lhm_computer is not None
		if computer_available:
			self._collect_lhm(live, settings)
		if not live:
			return
		with self._lock:
			if not self._running:
				return
			self._live = live
			log_first_sample = not self._logged_first_live_sample
			self._logged_first_live_sample = True
		if log_first_sample:
			self._print_cpu_module_block()
		self._notify()

	def _collect_lhm(self, live: dict[str, Any], settings: dict[str, bool]) -> None:
		with self._lock:
			computer = self._lhm_computer
		try:
			for hardware in self._lhm_hardware:
				hardware.Update()
			sensors = [sensor for hardware in self._iter_hardware() for sensor in self._iter_sensors(hardware)]
			clocks = self._sensor_values(sensors, "Clock", self._is_core_clock)
			temperatures = self._sensor_values(sensors, "Temperature", self._is_cpu_temperature)
			powers = self._sensor_values(sensors, "Power", self._is_cpu_power)
			if settings.get("Show Clock Speed") and clocks:
				live["clock"] = {"average_mhz": self._number(sum(value for _, value in clocks) / len(clocks)),
					"max_core_mhz": self._number(max(value for _, value in clocks))}
			if settings.get("Show Temperature"):
				live["temperature_c"] = self._number(self._preferred_temperature(temperatures)) if temperatures else None
			if settings.get("Show Power Usage") or self._internal_power_consumers:
				live["power_w"] = self._number(self._preferred_power(powers)) if powers else None
			if settings.get("Show Individual Cores"):
				self._add_individual_lhm_values(live, clocks, temperatures, settings)
			with self._lock:
				restore_pending = self._lhm_restore_pending
				self._lhm_restore_pending = False
				self._lhm_retry_after = 0.0
			if restore_pending:
				self._print_armoury_provider_block(running=False)
		except Exception as error:
			armoury_running = self._is_armoury_running()
			with self._lock:
				self._update_armoury_state_locked(armoury_running)
				self._lhm_retry_after = time.monotonic() + LHM_RETRY_INTERVAL_SECONDS
				self._lhm_restore_pending = True
				if computer is self._lhm_computer:
					self._close_lhm_locked()
			if armoury_running:
				LOGGER.debug(
					"LibreHardwareMonitor CPU sample interrupted while Armoury Crate is running: %s",
					error,
					exc_info=True,
				)
			else:
				self._warn_once(
					"lhm-sample",
					"CPU hardware sensor access was interrupted. CPU temperature and power readings may be temporarily unavailable while StatMonitor reconnects.",
				)
				LOGGER.debug("LibreHardwareMonitor CPU sample exception: %s", error, exc_info=True)

	@staticmethod
	def _iter_sensors(hardware: Any):
		try:
			return list(hardware.Sensors)
		except Exception:
			return []

	def _iter_hardware(self):
		for hardware in self._lhm_hardware:
			yield hardware
			try:
				children = list(hardware.SubHardware)
			except Exception:
				children = []
			for child in children:
				if str(child.HardwareType) == "Cpu":
					yield child

	@staticmethod
	def _sensor_values(sensors: list[Any], sensor_type: str, predicate: Callable[[str], bool]) -> list[tuple[str, float]]:
		values = []
		for sensor in sensors:
			try:
				if str(sensor.SensorType) != sensor_type or not predicate(str(sensor.Name)):
					continue
				value = float(sensor.Value)
				if value == value:
					values.append((str(sensor.Name), value))
			except (TypeError, ValueError, AttributeError):
				continue
		return values

	@staticmethod
	def _is_core_clock(name: str) -> bool:
		name_lower = name.lower()
		return "clock" in name_lower and "bus" not in name_lower and "bclk" not in name_lower

	@staticmethod
	def _is_cpu_temperature(name: str) -> bool:
		name_lower = name.lower()
		return "distance to tjmax" not in name_lower and any(token in name_lower for token in (
			"package", "tctl", "tdie", "core max", "core average", "cpu"
		))

	@staticmethod
	def _is_cpu_power(name: str) -> bool:
		name_lower = name.lower()
		return any(token in name_lower for token in ("cpu package", "package", "cpu power"))

	@staticmethod
	def _preferred_temperature(values: list[tuple[str, float]]) -> float:
		priorities = ("cpu package", "cpu (tctl/tdie)", "core (tctl/tdie)", "cpu tdie", "core max", "core average")
		return min(values, key=lambda item: next((index for index, token in enumerate(priorities) if token in item[0].lower()), len(priorities)))[1]

	@staticmethod
	def _preferred_power(values: list[tuple[str, float]]) -> float:
		priorities = ("cpu package", "package", "cpu power")
		return min(values, key=lambda item: next((index for index, token in enumerate(priorities) if token in item[0].lower()), len(priorities)))[1]

	def _add_individual_lhm_values(self, live: dict[str, Any], clocks, temperatures, settings) -> None:
		entries = live.setdefault("individual_cores", [])
		by_name = {entry["name"]: entry for entry in entries}
		for name, value in clocks:
			by_name.setdefault(name, {"name": name})["clock_mhz"] = self._number(value)
		for name, value in temperatures:
			by_name.setdefault(name, {"name": name})["temperature_c"] = self._number(value)
		live["individual_cores"] = list(by_name.values())

	@staticmethod
	def _number(value: Any) -> float:
		return round(float(value), 1)

	def _open_lhm_locked(self) -> None:
		global LHM_TYPES
		if self._lhm_computer is not None:
			return
		try:
			with LHM_TYPES_LOCK:
				if LHM_TYPES is None:
					from pythonnet import get_runtime_info, load
					dependency = self.project_root / "Dependencies" / "StatMonitor" / "LibreHardwareMonitor.NET.10"
					runtime_config = dependency / "LibreHardwareMonitor.runtimeconfig.json"
					if get_runtime_info() is None:
						if runtime_config.exists():
							load("coreclr", runtime_config=str(runtime_config))
						else:
							load("coreclr")
					import clr
					clr.AddReference(str(dependency / "LibreHardwareMonitorLib.dll"))
					from LibreHardwareMonitor.Hardware import Computer, HardwareType, SensorType
					LHM_TYPES = (Computer, HardwareType, SensorType)
			Computer, HardwareType, _ = LHM_TYPES
			computer = Computer()
			computer.IsCpuEnabled = True
			computer.IsMotherboardEnabled = False
			computer.IsGpuEnabled = False
			computer.IsMemoryEnabled = False
			computer.IsStorageEnabled = False
			computer.IsNetworkEnabled = False
			computer.IsControllerEnabled = False
			computer.IsPowerMonitorEnabled = False
			computer.Open()
			self._lhm_computer = computer
			self._lhm_hardware = [hardware for hardware in list(computer.Hardware)
				if str(hardware.HardwareType) == "Cpu"]
			if not self._lhm_hardware:
				self._warn_once("lhm-cpu", "LibreHardwareMonitor opened without CPU hardware")
		except Exception as error:
			self._lhm_retry_after = time.monotonic() + LHM_RETRY_INTERVAL_SECONDS
			if self._is_armoury_running():
				LOGGER.debug(
					"LibreHardwareMonitor CPU provider could not open while Armoury Crate is running: %s",
					error,
					exc_info=True,
				)
			else:
				self._warn_once("lhm", "LibreHardwareMonitor CPU provider unavailable: %s", error)
			self._close_lhm_locked()

	def _needs_lhm(self, settings: dict[str, bool]) -> bool:
		return any(settings.get(key, False) for key in (
			"Show Clock Speed", "Show Temperature", "Show Power Usage", "Show Individual Cores"
		)) or bool(self._internal_power_consumers)

	def _is_armoury_running(self) -> bool:
		if os.name != "nt" or psutil is None:
			return False
		try:
			for process in psutil.process_iter(["name"]):
				name = str(process.info.get("name") or "").strip().lower()
				if name and any(family in name for family in _ARMOURY_PROCESS_FAMILIES):
					return True
		except Exception as error:
			self._warn_once("armoury-check", "Armoury Crate process check unavailable: %s", error)
		return False

	def _update_armoury_state_locked(self, running: bool) -> None:
		previous = self._armoury_running
		if previous is running:
			return
		self._armoury_running = running
		if running:
			self._lhm_restore_pending = True
			self._print_armoury_provider_block(running=True)
		elif previous is True:
			self._lhm_retry_after = 0.0

	@staticmethod
	def _print_armoury_provider_block(running: bool) -> None:
		lines = [
			"-" * 60,
			"CPU_Provider",
			f"Armoury_Crate: {'Running' if running else 'Off'}",
			f"LibreHardwareMonitor: {'Paused' if running else 'Active'}",
			f"Sensor_Access: {'Blocked' if running else 'Restored'}",
		]
		if running:
			lines.append("Affected_Metrics: CPU_Temperature, CPU_Power_Usage")
			lines.append("Action: Turn Armoury Crate off to restore sensor access")
		lines.append("-" * 60)
		print_raw("\n".join(lines))

	def _close_lhm_locked(self) -> None:
		computer = self._lhm_computer
		self._lhm_computer = None
		self._lhm_hardware = []
		if computer is not None:
			try:
				computer.Close()
			except Exception as error:
				self._warn_once("lhm-close", "LibreHardwareMonitor CPU provider close failed: %s", error)

	def _notify(self) -> None:
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				LOGGER.exception("StatMonitor CPU listener failed")

	def _warn_once(self, key: str, message: str, *args) -> None:
		with self._lock:
			if key in self._provider_warnings:
				return
			self._provider_warnings.add(key)
		LOGGER.warning(message, *args)
