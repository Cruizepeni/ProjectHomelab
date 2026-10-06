

from __future__ import annotations

from StatMonitorOutput import print_raw

import copy
import json
import logging
import math
import os
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from StatMonitorPaths import resolve_project_root

try:
	import psutil
except ImportError:
	psutil = None


LOGGER = logging.getLogger(__name__)
SAMPLE_INTERVAL_SECONDS = 2.0
CIM_TIMEOUT_SECONDS = 8.0
_STATIC_SETTINGS = ("Show Motherboard Name", "Show Manufacturer", "Show Chipset", "Show BIOS Version")
_LIVE_SETTINGS = ("Show Temperature", "Show Fan Speeds", "Show Voltages")
_WARNING_SETTING = "Show Vendor Workaround Warnings"
_SETTINGS = _STATIC_SETTINGS + _LIVE_SETTINGS + (_WARNING_SETTING,)
ARMOURY_WARNING_ID = "Motherboard_Armoury_Crate_Warning"
ARMOURY_WARNING_MESSAGE = (
	"Armoury Crate is currently blocking Motherboard sensor information from being accessed. "
	"StatMonitor can turn Armoury Crate off after user confirmation to restore sensor access."
)

_ARMOURY_PROCESS_FAMILIES = (
	"armourycrate",
	"armourysocketserver",
	"armouryswagent",
	"rogliveservice",
)


def _known_armoury_install_paths() -> tuple[Path, ...]:
	program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
	program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
	return (
		program_files / "ASUS" / "Armoury Crate Service" / "ArmouryCrate.Service.exe",
		program_files / "ASUS" / "ROG Live Service" / "ROGLiveService.exe",
		program_files_x86 / "ASUS" / "ArmouryDevice" / "asus_framework.exe",
		program_files_x86 / "ASUS" / "ArmouryDevice" / "dll" / "ArmourySocketServer" / "ArmourySocketServer.exe",
	)

class StatMonitorMotherboard:


	def __init__(self, project_root: str | os.PathLike[str] | None = None):
		self.project_root = Path(project_root) if project_root else resolve_project_root()
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._static: dict[str, Any] = {}
		self._live: dict[str, list[dict[str, Any]]] = {}
		self._static_loaded = False
		self._running = False
		self._thread: threading.Thread | None = None
		self._stop_event: threading.Event | None = None
		self._lhm_computer: Any = None
		self._lhm_hardware: list[Any] = []
		self._lhm_clients: set[str] = set()
		self._lhm_pre_close_handlers: list[Callable[[str], None]] = []
		self._provider_state = "not_required"
		self._provider_reason = None
		self._provider_reason_code = None
		self._active_warning: dict[str, Any] | None = None
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

	def register_lhm_pre_close_handler(self, handler: Callable[[str], None]) -> None:
		if not callable(handler):
			raise TypeError("LHM pre-close handler must be callable")
		with self._lock:
			if handler not in self._lhm_pre_close_handlers:
				self._lhm_pre_close_handlers.append(handler)

	def unregister_lhm_pre_close_handler(self, handler: Callable[[str], None]) -> None:
		with self._lock:
			if handler in self._lhm_pre_close_handlers:
				self._lhm_pre_close_handlers.remove(handler)

	def acquire_lhm_client(self, client_id: str) -> None:
		client = str(client_id).strip()
		if not client:
			raise ValueError("LHM client id must not be empty")
		with self._lock:
			self._lhm_clients.add(client)
			running = self._running
			settings = dict(self._settings)
		if running:
			self._reconcile_provider(settings)

	def release_lhm_client(self, client_id: str) -> None:
		client = str(client_id).strip()
		with self._lock:
			self._lhm_clients.discard(client)
			running = self._running
			settings = dict(self._settings)
		if running:
			self._reconcile_provider(settings)

	@contextmanager
	def lhm_access(self):







		with self._lock:
			if self._lhm_computer is None:
				if not self._running:
					raise RuntimeError("Motherboard module is not running")
				self._open_lhm_locked()
			if self._lhm_computer is None:
				reason = self._provider_reason or "motherboard LHM provider is unavailable"
				raise RuntimeError(reason)
			yield self._lhm_computer, tuple(self._lhm_hardware)

	def start(self) -> None:
		with self._lock:
			if self._running:
				return
			self._running = True
			self._stop_event = threading.Event()
			self._logged_first_telemetry = False
			self._active_warning = None
			self._provider_reason_code = None
			settings = dict(self._settings)
		self._ensure_static(settings)
		self._reconcile_provider(settings)
		if self._lhm_computer is None:
			self._log_first_telemetry()
		self._notify()

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
			self._close_lhm_locked("module_stop")
			self._live = {}
			self._stop_event = None
			self._provider_state = "not_required"
			self._provider_reason = None
			self._provider_reason_code = None
			self._active_warning = None
		self._notify()

	def is_running(self) -> bool:
		with self._lock:
			return self._running

	def update_settings(self, settings: dict[str, bool]) -> None:
		if not isinstance(settings, dict):
			raise ValueError("Motherboard settings must be an object")
		with self._lock:
			self._settings = {key: bool(settings.get(key, False)) for key in _SETTINGS}
			running = self._running
			current = dict(self._settings)
		if not running:
			return
		self._ensure_static(current)
		with self._lock:
			self._refresh_armoury_warning_locked()
		self._reconcile_provider(current)
		self._notify()

	def get_latest(self) -> dict:
		with self._lock:
			settings = dict(self._settings)
			hardware = {}
			live = {}
			if settings.get("Show Motherboard Name") and self._static.get("motherboard_name"):
				hardware["motherboard_name"] = self._static["motherboard_name"]
			if settings.get("Show Manufacturer") and self._static.get("manufacturer"):
				hardware["manufacturer"] = self._static["manufacturer"]
			if settings.get("Show Chipset") and self._static.get("chipset"):
				hardware["chipset"] = self._static["chipset"]
			if settings.get("Show BIOS Version") and self._static.get("bios_version"):
				hardware["bios_version"] = self._static["bios_version"]
			for key, setting in (("temperatures", "Show Temperature"), ("fans", "Show Fan Speeds"), ("voltages", "Show Voltages")):
				if settings.get(setting) and self._live.get(key):
					live[key] = copy.deepcopy(self._live[key])

			provider = {
				"name": "LibreHardwareMonitor",
				"status": self._provider_state,
			}
			if self._provider_reason_code:
				provider["reason_code"] = self._provider_reason_code
			if self._provider_reason:
				provider["reason"] = self._provider_reason

			warnings = []
			if self._active_warning is not None and settings.get(_WARNING_SETTING, True):
				warnings.append(copy.deepcopy(self._active_warning))

			return {
				"hardware": copy.deepcopy(hardware),
				"live": live,
				"provider": provider,
				"warnings": warnings,
			}


	def get_metric_snapshot(self) -> dict[str, Any]:

		latest = self.get_latest()
		hardware = latest.get("hardware", {})
		live = latest.get("live", {})

		temperatures = []
		for entry in live.get("temperatures", []) or []:
			if not isinstance(entry, dict):
				continue
			item = {}
			if entry.get("name") is not None:
				item["Motherboard_Temperature_Name"] = entry.get("name")
			if entry.get("temperature_c") is not None:
				item["Motherboard_Temperature"] = entry.get("temperature_c")
			if item:
				temperatures.append(item)

		fans = []
		for entry in live.get("fans", []) or []:
			if not isinstance(entry, dict):
				continue
			item = {}
			if entry.get("name") is not None:
				item["Motherboard_Fan_Name"] = entry.get("name")
			if entry.get("rpm") is not None:
				item["Motherboard_Fan_Speed"] = entry.get("rpm")
			if item:
				fans.append(item)

		voltages = []
		for entry in live.get("voltages", []) or []:
			if not isinstance(entry, dict):
				continue
			item = {}
			if entry.get("name") is not None:
				item["Motherboard_Voltage_Name"] = entry.get("name")
			if entry.get("volts") is not None:
				item["Motherboard_Voltage"] = entry.get("volts")
			if item:
				voltages.append(item)

		return {
			"Motherboard_Brand": self._clean_motherboard_brand(hardware.get("manufacturer")),
			"Motherboard_Name": hardware.get("motherboard_name"),
			"Motherboard_Chipset": hardware.get("chipset"),
			"Motherboard_BIOS_Version": hardware.get("bios_version"),
			"Motherboard_Temperatures": temperatures,
			"Motherboard_Fans": fans,
			"Motherboard_Voltages": voltages,
		}

	def _print_motherboard_module_block(self) -> None:
		metrics = self.get_metric_snapshot()

		def format_metric(metric_id: str, value: Any) -> str:
			if value is None:
				return "Unavailable"
			if metric_id == "Motherboard_Temperature":
				return f"{value} °C"
			if metric_id == "Motherboard_Fan_Speed":
				return f"{value} RPM"
			if metric_id == "Motherboard_Voltage":
				return f"{value} V"
			return str(value)

		lines = ["-" * 60, "Motherboard_Module"]
		for metric_id, value in metrics.items():
			if metric_id not in (
				"Motherboard_Temperatures",
				"Motherboard_Fans",
				"Motherboard_Voltages",
			):
				lines.append(f"{metric_id}: {format_metric(metric_id, value)}")
				continue
			items = value if isinstance(value, list) else []
			lines.append(f"{metric_id}: {len(items)}")
			for index, item in enumerate(items, 1):
				lines.append(f"  [{index}]")
				for child_id, child_value in item.items():
					lines.append(f"    {child_id}: {format_metric(child_id, child_value)}")
		lines.append("-" * 60)
		print_raw("\n".join(lines))

	def _ensure_static(self, settings: dict[str, bool]) -> None:
		if not any(settings.get(key, False) for key in _STATIC_SETTINGS):
			return
		with self._lock:
			if self._static_loaded:
				return
		static = self._query_static_cim()
		with self._lock:
			self._static = static
			self._static_loaded = True

	def _query_static_cim(self) -> dict[str, Any]:
		command = (
			"$board = Get-CimInstance Win32_BaseBoard | Select-Object -First 1 Manufacturer,Product,Model,Name; "
			"$bios = Get-CimInstance Win32_BIOS | Select-Object -First 1 SMBIOSBIOSVersion,Version; "
			"$devices = @(Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -and ($_.Name -match 'Chipset|PCH|LPC Controller|SMBus Controller') } | Select-Object Name,PNPClass,Status); "
			"[pscustomobject]@{ Board=$board; Bios=$bios; Devices=$devices } | ConvertTo-Json -Compress -Depth 4"
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
			data = json.loads(result.stdout) if result.stdout.strip() else {}
			board = data.get("Board") or {}
			bios = data.get("Bios") or {}
			if isinstance(board, list):
				board = board[0] if board else {}
			if isinstance(bios, list):
				bios = bios[0] if bios else {}
			manufacturer = self._clean_text(board.get("Manufacturer"))
			product = self._first_meaningful(board.get("Product"), board.get("Model"), board.get("Name"))
			static = {}
			if product:
				static["motherboard_name"] = product
			if manufacturer:
				static["manufacturer"] = manufacturer
			bios_version = self._first_meaningful(bios.get("SMBIOSBIOSVersion"), bios.get("Version"))
			if bios_version:
				static["bios_version"] = bios_version
			chipset = self._select_chipset(data.get("Devices"))
			if chipset:
				static["chipset"] = chipset
			return static
		except Exception as error:
			self._warn_once("cim", "Motherboard CIM discovery unavailable: %s", error)
			return {}

	def _select_chipset(self, devices: Any) -> str | None:
		if isinstance(devices, dict):
			devices = [devices]
		if not isinstance(devices, list):
			return None
		candidates = []
		for device in devices:
			if not isinstance(device, dict):
				continue
			name = self._clean_text(device.get("Name"))
			if not name:
				continue
			lower = name.lower()
			score = 0
			if "chipset" in lower:
				score += 100
			if "pch" in lower:
				score += 80
			if "lpc controller" in lower:
				score += 60
			if "smbus controller" in lower:
				score += 50
			if score:
				candidates.append((score, name))
		if not candidates:
			return None
		return self._normalize_chipset(max(candidates, key=lambda item: (item[0], item[1]))[1])

	@staticmethod
	def _normalize_chipset(value: str) -> str:
		value = value.strip()
		for suffix in (" LPC Controller", " SMBus Controller"):
			if value.lower().endswith(suffix.lower()):
				return value[:-len(suffix)].strip()
		return value

	def _reconcile_provider(self, settings: dict[str, bool]) -> None:
		needs_live_sampling = any(settings.get(key, False) for key in _LIVE_SETTINGS)
		with self._lock:
			running = self._running
			needs_provider = needs_live_sampling or bool(self._lhm_clients)
		if not running:
			return

		if not needs_provider:
			with self._lock:
				stop_event = self._stop_event
				thread = self._thread
				self._thread = None
				if stop_event is not None:
					stop_event.set()
			if thread is not None and thread is not threading.current_thread():
				thread.join(timeout=SAMPLE_INTERVAL_SECONDS + 2)
			with self._lock:
				self._close_lhm_locked("provider_not_required")
				self._live = {}
				self._provider_state = "not_required"
				self._provider_reason = None
				self._provider_reason_code = None
				self._active_warning = None
			return



		with self._lock:
			if self._lhm_computer is None:
				self._open_lhm_locked()

		if not needs_live_sampling:

			with self._lock:
				stop_event = self._stop_event
				thread = self._thread
				self._thread = None
				if stop_event is not None:
					stop_event.set()
			if thread is not None and thread is not threading.current_thread():
				thread.join(timeout=SAMPLE_INTERVAL_SECONDS + 2)
			return

		with self._lock:
			if self._thread is None:
				stop_event = threading.Event()
				self._stop_event = stop_event
				self._thread = threading.Thread(
					target=self._sample_loop,
					args=(stop_event,),
					name="StatMonitorMotherboard",
					daemon=True,
				)
				self._thread.start()

	def _open_lhm_locked(self) -> None:
		restoring_from_armoury = self._provider_reason_code == "armoury_crate_conflict"



		if self._is_asus():
			armoury = self._get_armoury_status()
			if armoury.get("running"):
				self._set_armoury_blocked_state_locked(armoury)
				return

		self._active_warning = None
		self._provider_state = "starting"
		self._provider_reason = None
		self._provider_reason_code = None
		try:
			dependency = self.project_root / "Dependencies" / "StatMonitor" / "LibreHardwareMonitor.NET.10"
			runtime_config = dependency / "LibreHardwareMonitor.runtimeconfig.json"
			from pythonnet import get_runtime_info, load
			if get_runtime_info() is None:
				if runtime_config.exists():
					load("coreclr", runtime_config=str(runtime_config))
				else:
					load("coreclr")
			import clr
			clr.AddReference(str(dependency / "LibreHardwareMonitorLib.dll"))
			from LibreHardwareMonitor.Hardware import Computer
			computer = Computer()
			self._set_lhm_flag(computer, "IsMotherboardEnabled", True)
			for flag in ("IsCpuEnabled", "IsGpuEnabled", "IsMemoryEnabled", "IsNetworkEnabled", "IsStorageEnabled", "IsControllerEnabled", "IsPowerMonitorEnabled", "IsBatteryEnabled"):
				self._set_lhm_flag(computer, flag, False)
			computer.Open()
			hardware = [item for item in list(computer.Hardware) if str(item.HardwareType).lower().endswith("motherboard")]
			if not hardware:
				computer.Close()
				self._provider_state = "unavailable"
				self._provider_reason = "No motherboard hardware returned"
				self._provider_reason_code = "no_motherboard_hardware"
				self._warn_once("lhm-hardware", "LibreHardwareMonitor returned no motherboard hardware")
				return
			self._lhm_computer = computer
			self._lhm_hardware = hardware
			self._provider_state = "active"
			self._provider_reason = None
			self._provider_reason_code = None
			self._active_warning = None
			self._logged_first_telemetry = False
			self._print_provider_active_block(
				hardware,
				restored_from_armoury=restoring_from_armoury,
			)
		except Exception as error:
			self._provider_state = "unavailable"
			self._provider_reason = str(error)
			self._provider_reason_code = "provider_unavailable"
			self._warn_once("lhm", "Motherboard live sensor provider unavailable: %s", error)
			self._close_lhm_locked()

	@staticmethod
	def _set_lhm_flag(computer: Any, name: str, value: bool) -> None:
		try:
			setattr(computer, name, value)
		except (AttributeError, TypeError):
			pass

	def _sample_loop(self, stop_event: threading.Event) -> None:
		try:
			while not stop_event.is_set():
				with self._lock:
					if not self._running or self._stop_event is not stop_event:
						return
					settings = dict(self._settings)
				if not any(settings.get(key, False) for key in _LIVE_SETTINGS):
					return

				notify = False
				with self._lock:
					armoury_running = False
					if self._is_asus():
						armoury = self._get_armoury_status()
						armoury_running = bool(armoury.get("running"))
						if armoury_running:
							if self._lhm_computer is not None:
								self._close_lhm_locked("armoury_crate_conflict")
								self._live = {}
							before = (self._provider_state, self._provider_reason_code, self._provider_reason, self._active_warning)
							self._set_armoury_blocked_state_locked(armoury)
							after = (self._provider_state, self._provider_reason_code, self._provider_reason, self._active_warning)
							notify = notify or before != after
						else:
							self._active_warning = None

					if self._lhm_computer is None and not armoury_running:
						before = (self._provider_state, self._provider_reason_code, self._provider_reason)
						self._open_lhm_locked()
						after = (self._provider_state, self._provider_reason_code, self._provider_reason)
						notify = notify or before != after
					provider_active = self._lhm_computer is not None

				if provider_active:
					try:
						live = self._collect_sensors()
						with self._lock:
							if self._running and self._stop_event is stop_event:
								self._live = live
						self._log_first_telemetry()
						self._notify()
					except Exception as error:
						self._warn_once("sample", "Motherboard sensor sample failed: %s", error)
						with self._lock:
							self._close_lhm_locked("sample_failed")
							self._live = {}
							self._provider_state = "error"
							self._provider_reason = str(error)
							self._provider_reason_code = "sample_failed"
						notify = True
				elif notify:
					self._log_first_telemetry()
					self._notify()

				if stop_event.wait(SAMPLE_INTERVAL_SECONDS):
					return
		finally:
			with self._lock:
				if self._thread is threading.current_thread():
					self._thread = None

	def _collect_sensors(self) -> dict[str, list[dict[str, Any]]]:


		with self._lock:
			for hardware in self._iter_hardware():
				hardware.Update()
			values = {"temperatures": [], "fans": [], "voltages": []}
			for hardware in self._iter_hardware():
				for sensor in self._sensors(hardware):
					try:
						sensor_type = str(sensor.SensorType).split(".")[-1]
						if sensor_type not in ("Temperature", "Fan", "Voltage"):
							continue
						value = float(sensor.Value)
						if not math.isfinite(value) or (sensor_type == "Fan" and value < 0):
							continue
						sensor_name = self._clean_text(getattr(sensor, "Name", "")) or "Unnamed"
						source_name = self._clean_text(getattr(hardware, "Name", "")) or "Motherboard"
						if sensor_type == "Temperature":
							if value < -40 or value > 150:
								continue
							if sensor_name.lower().startswith("temperature #") and value <= 0:
								continue
						entry = {"name": sensor_name, "source": source_name}
						if sensor_type == "Temperature":
							entry["temperature_c"] = round(value, 1)
							values["temperatures"].append(entry)
						elif sensor_type == "Fan":
							entry["rpm"] = round(value, 1)
							values["fans"].append(entry)
						else:
							entry["volts"] = round(value, 3)
							values["voltages"].append(entry)
					except (AttributeError, TypeError, ValueError):
						continue
			return {key: value for key, value in values.items() if value}

	def _iter_hardware(self):
		stack = list(self._lhm_hardware)
		while stack:
			hardware = stack.pop(0)
			yield hardware
			try:
				stack.extend(list(hardware.SubHardware))
			except Exception:
				continue

	@staticmethod
	def _sensors(hardware: Any) -> list[Any]:
		try:
			return list(hardware.Sensors)
		except Exception:
			return []

	def _close_lhm_locked(self, reason: str = "provider_close") -> None:
		computer = self._lhm_computer
		if computer is None:
			self._lhm_hardware = []
			return



		for handler in list(self._lhm_pre_close_handlers):
			try:
				handler(reason)
			except Exception as error:
				LOGGER.exception("Motherboard LHM pre-close handler failed: %s", error)

		self._lhm_computer = None
		self._lhm_hardware = []
		try:
			computer.Close()
		except Exception:
			pass

	def _is_asus(self) -> bool:
		return "asus" in self._static.get("manufacturer", "").lower()

	def _set_armoury_blocked_state_locked(self, armoury: dict[str, Any]) -> None:
		was_blocked = self._provider_reason_code == "armoury_crate_conflict"
		self._provider_state = "blocked"
		self._provider_reason_code = "armoury_crate_conflict"
		self._provider_reason = "Blocked by Armoury Crate"
		self._refresh_armoury_warning_locked(armoury)
		if not was_blocked:
			self._print_armoury_provider_block(running=True)

	@staticmethod
	def _print_provider_active_block(
		hardware: list[Any],
		*,
		restored_from_armoury: bool,
	) -> None:
		hardware_names = [
			str(getattr(item, "Name", "Motherboard"))
			for item in hardware
		]
		lines = [
			"-" * 60,
			"Motherboard_Provider",
		]
		if restored_from_armoury:
			lines.append("Armoury_Crate: Off")
		lines.extend([
			"LibreHardwareMonitor: Active",
			f"Sensor_Access: {'Restored' if restored_from_armoury else 'Available'}",
			f"Hardware: {', '.join(hardware_names) if hardware_names else 'Motherboard'}",
			"-" * 60,
		])
		print_raw("\n".join(lines))

	@staticmethod
	def _print_armoury_provider_block(running: bool) -> None:
		lines = [
			"-" * 60,
			"Motherboard_Provider",
			f"Armoury_Crate: {'Running' if running else 'Off'}",
			f"LibreHardwareMonitor: {'Paused' if running else 'Active'}",
			f"Sensor_Access: {'Blocked' if running else 'Restored'}",
		]
		if running:
			lines.append(
				"Affected_Metrics: Motherboard_Temperatures, Motherboard_Fans, Motherboard_Voltages"
			)
			lines.append("Action: StatMonitor can turn Armoury Crate off after confirmation")
		lines.append("-" * 60)
		print_raw("\n".join(lines))

	def _refresh_armoury_warning_locked(self, armoury: dict[str, Any] | None = None) -> None:
		if not self._settings.get(_WARNING_SETTING, True):
			self._active_warning = None
			return
		if self._provider_reason_code != "armoury_crate_conflict":
			self._active_warning = None
			return
		armoury = armoury or self._get_armoury_status()
		self._active_warning = {
			"id": ARMOURY_WARNING_ID,
			"module": "Motherboard",
			"severity": "warning",
			"title": "Motherboard sensor information blocked",
			"message": ARMOURY_WARNING_MESSAGE,
			"reason_code": "armoury_crate_conflict",
			"vendor_tool_id": "ASUS.ArmouryCrateOff",
			"confirmation_required": True,
			"restart_required_to_restore": True,
			"processes": copy.deepcopy(armoury.get("processes", [])),
			"dismissible": True,
			"dismiss_setting": {
				"section": "Motherboard",
				"key": _WARNING_SETTING,
				"value": False,
			},
		}

	def _get_armoury_status(self) -> dict[str, Any]:

		if os.name != "nt":
			return {
				"supported": False,
				"installed": False,
				"running": False,
				"processes": [],
			}

		processes = self._running_armoury_processes()
		installed = bool(processes) or any(path.exists() for path in _known_armoury_install_paths())
		return {
			"supported": True,
			"installed": installed,
			"running": bool(processes),
			"processes": processes,
		}

	def _running_armoury_processes(self) -> list[str]:
		if psutil is None:
			self._warn_once(
				"armoury-check-psutil",
				"Armoury Crate process check unavailable because psutil is not installed",
			)
			return []

		matches: set[str] = set()
		try:
			for process in psutil.process_iter(["name"]):
				name = str(process.info.get("name") or "").strip()
				lower = name.lower()
				if lower and any(family in lower for family in _ARMOURY_PROCESS_FAMILIES):
					matches.add(name)
		except Exception as error:
			self._warn_once("armoury-check", "Armoury Crate process check unavailable: %s", error)
		return sorted(matches, key=str.lower)

	def _log_first_telemetry(self) -> None:
		with self._lock:
			if self._logged_first_telemetry:
				return
			self._logged_first_telemetry = True
		self._print_motherboard_module_block()

	def _notify(self) -> None:
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				LOGGER.exception("StatMonitor Motherboard listener failed")


	@staticmethod
	def _clean_motherboard_brand(value: Any) -> str | None:
		text = " ".join(str(value or "").split()).strip()
		if not text:
			return None

		lower = text.lower()
		brand_aliases = (
			(("asustek", "asus"), "ASUS"),
			(("micro-star", "msi"), "MSI"),
			(("gigabyte",), "Gigabyte"),
			(("asrock",), "ASRock"),
			(("supermicro",), "Supermicro"),
			(("biostar",), "Biostar"),
			(("evga",), "EVGA"),
			(("intel",), "Intel"),
			(("dell",), "Dell"),
			(("hewlett-packard", "hewlett packard", "hp"), "HP"),
			(("lenovo",), "Lenovo"),
			(("acer",), "Acer"),
		)

		for aliases, canonical in brand_aliases:
			if any(alias in lower for alias in aliases):
				return canonical

		return text

	@staticmethod
	def _clean_text(value: Any) -> str | None:
		if value is None:
			return None
		text = " ".join(str(value).split())
		return text or None

	@classmethod
	def _first_meaningful(cls, *values: Any) -> str | None:
		for value in values:
			cleaned = cls._clean_text(value)
			if cleaned and cleaned.lower() not in {"unknown", "base board", "motherboard"}:
				return cleaned
		return None

	@staticmethod
	def _hardware_names(hardware: list[Any]) -> list[str]:
		return [str(getattr(item, "Name", "Motherboard")) for item in hardware]

	def _warn_once(self, key: str, message: str, *args) -> None:
		with self._lock:
			if key in self._provider_warnings:
				return
			self._provider_warnings.add(key)
		LOGGER.warning(message, *args)
