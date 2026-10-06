

from __future__ import annotations

from StatMonitorOutput import print_raw

import copy
import ctypes
import ctypes.wintypes as wintypes
import importlib
import logging
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from StatMonitorPaths import resolve_project_root

try:
	import psutil
except ImportError:
	psutil = None


LOGGER = logging.getLogger(__name__)
SAMPLE_INTERVAL_SECONDS = 1.0
BATTERY_DETAILS_INTERVAL_SECONDS = 60.0
_SETTINGS = (
	"Show Power Source", "Show Battery", "Show Battery Percentage", "Show Charging State",
	"Show Time Remaining", "Show Battery Health", "Show Battery Capacity", "Show Battery Cycle Count",
	"Show CPU Power Usage", "Show GPU Power Usage",
)
BATTERY_FLAG_NO_BATTERY = 0x80
BATTERY_FLAG_CHARGING = 0x08
BATTERY_CAPACITY_RELATIVE = 0x40000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
ERROR_NO_MORE_ITEMS = 259
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3
FILE_DEVICE_BATTERY = 0x29


def _ctl_code(function: int) -> int:
	return (FILE_DEVICE_BATTERY << 16) | (function << 2)


IOCTL_BATTERY_QUERY_TAG = _ctl_code(0x10)
IOCTL_BATTERY_QUERY_INFORMATION = _ctl_code(0x11)


class SYSTEM_POWER_STATUS(ctypes.Structure):
	_fields_ = [
		("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
		("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
		("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD),
	]


class GUID(ctypes.Structure):
	_fields_ = [("Data1", wintypes.DWORD), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
	_fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_size_t)]


class BATTERY_QUERY_INFORMATION(ctypes.Structure):
	_fields_ = [("BatteryTag", wintypes.ULONG), ("InformationLevel", wintypes.ULONG), ("AtRate", wintypes.LONG)]


class BATTERY_INFORMATION(ctypes.Structure):
	_fields_ = [
		("Capabilities", wintypes.ULONG), ("Technology", ctypes.c_ubyte), ("Reserved", ctypes.c_ubyte * 3),
		("Chemistry", ctypes.c_ubyte * 4), ("DesignedCapacity", wintypes.ULONG),
		("FullChargedCapacity", wintypes.ULONG), ("DefaultAlert1", wintypes.ULONG),
		("DefaultAlert2", wintypes.ULONG), ("CriticalBias", wintypes.ULONG), ("CycleCount", wintypes.ULONG),
	]


class _WindowsBatteryProvider:
	def __init__(self):
		self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None
		self.setupapi = ctypes.WinDLL("setupapi", use_last_error=True) if os.name == "nt" else None
		if self.kernel32 is not None:
			self.kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
			self.kernel32.GetSystemPowerStatus.restype = wintypes.BOOL
			self.kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
			self.kernel32.CreateFileW.restype = wintypes.HANDLE
			self.kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
			self.kernel32.DeviceIoControl.restype = wintypes.BOOL
			self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
			self.kernel32.CloseHandle.restype = wintypes.BOOL
		if self.setupapi is not None:
			self.setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
			self.setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
			self.setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
			self.setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
			self.setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
			self.setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
			self.setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
			self.setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

	def status(self) -> dict[str, Any] | None:
		if self.kernel32 is None:
			return None
		status = SYSTEM_POWER_STATUS()
		if not self.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
			raise OSError(ctypes.get_last_error(), "GetSystemPowerStatus failed")
		return {
			"ac_line": int(status.ACLineStatus) & 0xFF, "battery_flag": int(status.BatteryFlag) & 0xFF,
			"percentage": int(status.BatteryLifePercent) & 0xFF, "remaining": int(status.BatteryLifeTime),
		}

	def details(self) -> list[dict[str, Any]]:
		if self.kernel32 is None or self.setupapi is None:
			return []
		interface_guid = self._guid("72631E54-78A4-11D0-BCF7-00AA00B7B32A")
		setup = self.setupapi.SetupDiGetClassDevsW(ctypes.byref(interface_guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
		if setup == INVALID_HANDLE_VALUE:
			raise OSError(ctypes.get_last_error(), "SetupDiGetClassDevsW failed")
		try:
			result = []
			index = 0
			while True:
				interface = SP_DEVICE_INTERFACE_DATA(cbSize=ctypes.sizeof(SP_DEVICE_INTERFACE_DATA))
				if not self.setupapi.SetupDiEnumDeviceInterfaces(setup, None, ctypes.byref(interface_guid), index, ctypes.byref(interface)):
					if ctypes.get_last_error() == ERROR_NO_MORE_ITEMS:
						break
					raise OSError(ctypes.get_last_error(), "SetupDiEnumDeviceInterfaces failed")
				index += 1
				path = self._interface_path(setup, interface)
				if path:
					detail = self._battery_information(path)
					if detail:
						result.append(detail)
			return result
		finally:
			self.setupapi.SetupDiDestroyDeviceInfoList(setup)

	def _interface_path(self, setup: Any, interface: SP_DEVICE_INTERFACE_DATA) -> str | None:
		required = wintypes.DWORD()
		self.setupapi.SetupDiGetDeviceInterfaceDetailW(setup, ctypes.byref(interface), None, 0, ctypes.byref(required), None)
		if not required.value:
			return None
		buffer = ctypes.create_string_buffer(required.value)
		ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
		if not self.setupapi.SetupDiGetDeviceInterfaceDetailW(setup, ctypes.byref(interface), buffer, required, None, None):
			return None
		return ctypes.wstring_at(ctypes.addressof(buffer) + ctypes.sizeof(wintypes.DWORD))

	def _battery_information(self, path: str) -> dict[str, Any] | None:
		handle = self.kernel32.CreateFileW(path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
		if handle == INVALID_HANDLE_VALUE:
			return None
		try:
			tag = wintypes.ULONG(); returned = wintypes.DWORD(); timeout = wintypes.ULONG(0)
			if not self.kernel32.DeviceIoControl(handle, IOCTL_BATTERY_QUERY_TAG, ctypes.byref(timeout), ctypes.sizeof(timeout), ctypes.byref(tag), ctypes.sizeof(tag), ctypes.byref(returned), None) or not tag.value:
				return None
			query = BATTERY_QUERY_INFORMATION(BatteryTag=tag.value, InformationLevel=0, AtRate=0)
			info = BATTERY_INFORMATION()
			if not self.kernel32.DeviceIoControl(handle, IOCTL_BATTERY_QUERY_INFORMATION, ctypes.byref(query), ctypes.sizeof(query), ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned), None):
				return None
			return {"relative": bool(info.Capabilities & BATTERY_CAPACITY_RELATIVE), "design": int(info.DesignedCapacity), "full": int(info.FullChargedCapacity), "cycle": int(info.CycleCount)}
		finally:
			self.kernel32.CloseHandle(handle)

	@staticmethod
	def _guid(value: str) -> GUID:
		parsed = uuid.UUID(value)
		return GUID(parsed.time_low, parsed.time_mid, parsed.time_hi_version, (ctypes.c_ubyte * 8).from_buffer_copy(parsed.bytes[8:]))


class _LhmComponentPowerProvider:
	def __init__(self, project_root: Path, warn: Callable[..., None]):
		self.project_root = project_root
		self._warn = warn
		self._computer: Any = None
		self._hardware: list[Any] = []
		self._flags: tuple[bool, bool] = (False, False)

	def configure(self, cpu: bool, gpu: bool) -> None:
		flags = (cpu, gpu)
		if flags == self._flags and self._computer is not None:
			return
		self.close()
		self._flags = flags
		if not any(flags):
			return
		try:
			pythonnet = importlib.import_module("pythonnet")
			dependency = self.project_root / "Dependencies" / "StatMonitor" / "LibreHardwareMonitor.NET.10"
			if pythonnet.get_runtime_info() is None:
				pythonnet.load("coreclr", runtime_config=str(dependency / "LibreHardwareMonitor.runtimeconfig.json"))
			clr = importlib.import_module("clr"); clr.AddReference(str(dependency / "LibreHardwareMonitorLib.dll"))
			Computer = getattr(importlib.import_module("LibreHardwareMonitor.Hardware"), "Computer")
			computer = Computer(); computer.IsCpuEnabled = cpu or gpu; computer.IsGpuEnabled = gpu
			for name in ("IsMotherboardEnabled", "IsMemoryEnabled", "IsStorageEnabled", "IsNetworkEnabled", "IsControllerEnabled", "IsPowerMonitorEnabled", "IsBatteryEnabled"):
				if hasattr(computer, name): setattr(computer, name, False)
			computer.Open(); self._computer = computer
			self._hardware = list(self._walk(list(computer.Hardware)))
		except Exception as error:
			self._warn("fallback-lhm", "Power LibreHardwareMonitor fallback unavailable: %s", error)
			self.close()

	def collect(self) -> dict[str, float]:
		result: dict[str, float] = {}; gpu_values = []
		for hardware in self._hardware:
			kind = str(getattr(hardware, "HardwareType", ""))
			if kind not in ("Cpu", "GpuNvidia", "GpuAmd", "GpuIntel"):
				continue
			try: hardware.Update()
			except Exception: continue
			values = [(str(getattr(sensor, "Name", "")), self._value(sensor)) for sensor in list(getattr(hardware, "Sensors", []))]
			if kind == "Cpu" and self._flags[0] and "cpu_power_w" not in result:
				value = self._preferred(values, ("cpu package", "package", "cpu power"), ())
				if value is not None: result["cpu_power_w"] = value
			elif kind.startswith("Gpu") and self._flags[1]:
				value = self._preferred(values, ("gpu package", "gpu total", "gpu power", "board power"), ("pcie", "slot", "6-pin", "8-pin", "12vhpwr", "rail"))
				if value is not None: gpu_values.append(value)
		if gpu_values: result["gpu_power_w"] = round(sum(gpu_values), 1)
		return result

	def close(self) -> None:
		computer, self._computer, self._hardware = self._computer, None, []
		if computer is not None:
			try: computer.Close()
			except Exception: pass

	@staticmethod
	def _walk(items):
		for item in items:
			yield item
			try: yield from _LhmComponentPowerProvider._walk(list(item.SubHardware))
			except Exception: pass

	@staticmethod
	def _value(sensor: Any) -> float | None:
		try:
			value = float(sensor.Value)
			return round(value, 1) if math.isfinite(value) and value >= 0 else None
		except (AttributeError, TypeError, ValueError): return None

	@staticmethod
	def _preferred(values, priorities, excluded) -> float | None:
		matches = []
		for name, value in values:
			lower = name.lower()
			if value is not None and any(token in lower for token in priorities) and not any(token in lower for token in excluded):
				matches.append((next(index for index, token in enumerate(priorities) if token in lower), name, value))
		return min(matches, key=lambda item: (item[0], item[1]))[2] if matches else None


class StatMonitorPower:


	def __init__(self, cpu_module=None, gpu_module=None, project_root: str | os.PathLike[str] | None = None):
		self.project_root = Path(project_root) if project_root else resolve_project_root()
		self.cpu_module, self.gpu_module = cpu_module, gpu_module
		self._lock = threading.RLock(); self._listeners: list[Callable[[dict], None]] = []; self._settings: dict[str, bool] = {}
		self._hardware: dict[str, Any] = {}; self._live: dict[str, Any] = {}; self._running = False
		self._thread: threading.Thread | None = None; self._stop_event: threading.Event | None = None
		self._windows = _WindowsBatteryProvider(); self._fallback = _LhmComponentPowerProvider(self.project_root, self._warn_once)
		self._last_details = 0.0; self._battery_details: dict[str, Any] = {}; self._warned: set[str] = set(); self._logged_first = False

	def subscribe(self, listener: Callable[[dict], None]) -> None:
		with self._lock:
			if listener not in self._listeners: self._listeners.append(listener)

	def unsubscribe(self, listener: Callable[[dict], None]) -> None:
		with self._lock:
			if listener in self._listeners: self._listeners.remove(listener)

	def start(self) -> None:
		with self._lock:
			if self._running: return
			self._running = True; self._stop_event = threading.Event(); self._logged_first = False; settings = dict(self._settings)
		self._sync_requests(settings); self._thread = threading.Thread(target=self._run, name="StatMonitorPower", daemon=True); self._thread.start()

	def stop(self) -> None:
		with self._lock:
			self._running = False; stop_event, thread = self._stop_event, self._thread; self._thread = None
		if stop_event: stop_event.set()
		if thread and thread is not threading.current_thread(): thread.join(timeout=SAMPLE_INTERVAL_SECONDS + 2)
		self._release_requests(); self._fallback.close()
		with self._lock: self._live = {}; self._stop_event = None
		self._notify()

	def is_running(self) -> bool:
		with self._lock: return self._running

	def update_settings(self, settings: dict[str, bool]) -> None:
		if not isinstance(settings, dict): raise ValueError("Power settings must be an object")
		with self._lock: self._settings = {key: bool(settings.get(key, False)) for key in _SETTINGS}; current = dict(self._settings); running = self._running
		if running: self._sync_requests(current)
		self._notify()

	def get_latest(self) -> dict:
		with self._lock:
			settings, hardware, live = dict(self._settings), copy.deepcopy(self._hardware), copy.deepcopy(self._live)
			result_hardware: dict[str, Any] = {}; result_live: dict[str, Any] = {}
			battery = hardware.get("battery")
			if battery:
				filtered = {}
				if settings.get("Show Battery") and "present" in battery: filtered["present"] = battery["present"]
				for key, enabled in (("health_percent", "Show Battery Health"), ("design_capacity_mwh", "Show Battery Capacity"), ("full_charge_capacity_mwh", "Show Battery Capacity"), ("cycle_count", "Show Battery Cycle Count")):
					if settings.get(enabled) and key in battery: filtered[key] = battery[key]
				if filtered: result_hardware["battery"] = filtered
			if settings.get("Show Power Source") and "power_source" in live: result_live["power_source"] = live["power_source"]
			battery_live = live.get("battery", {}); filtered_live = {}
			for key, enabled in (("percentage", "Show Battery Percentage"), ("charging_state", "Show Charging State"), ("time_remaining_seconds", "Show Time Remaining")):
				if settings.get(enabled) and key in battery_live: filtered_live[key] = battery_live[key]
			if filtered_live: result_live["battery"] = filtered_live
			for key, enabled in (("cpu_power_w", "Show CPU Power Usage"), ("gpu_power_w", "Show GPU Power Usage")):
				if settings.get(enabled) and key in live: result_live[key] = live[key]
			return {"hardware": result_hardware, "live": result_live}


	def get_metric_snapshot(self) -> dict[str, Any]:





		latest = self.get_latest()
		hardware = latest.get("hardware", {})
		live = latest.get("live", {})

		battery_hardware = (
			hardware.get("battery")
			if isinstance(hardware.get("battery"), dict)
			else {}
		)
		battery_live = (
			live.get("battery")
			if isinstance(live.get("battery"), dict)
			else {}
		)

		return {
			"Power_Source": live.get("power_source"),
			"Power_Battery_Present": battery_hardware.get("present"),
			"Power_Battery_Percentage": battery_live.get("percentage"),
			"Power_Battery_Charging_State": battery_live.get("charging_state"),
			"Power_Battery_Time_Remaining": battery_live.get("time_remaining_seconds"),
			"Power_Battery_Health": battery_hardware.get("health_percent"),
			"Power_Battery_Design_Capacity": battery_hardware.get("design_capacity_mwh"),
			"Power_Battery_Full_Charge_Capacity": battery_hardware.get("full_charge_capacity_mwh"),
			"Power_Battery_Cycle_Count": battery_hardware.get("cycle_count"),
		}

	def _print_power_module_block(self) -> None:
		metrics = self.get_metric_snapshot()

		def format_percent(value: Any) -> str:
			return "Unavailable" if value is None else f"{value}%"

		def format_capacity_mwh(value: Any) -> str:
			if value is None:
				return "Unavailable"
			try:
				return f"{float(value) / 1000.0:.1f} Wh"
			except (TypeError, ValueError):
				return str(value)

		def format_duration(seconds: Any) -> str:
			if seconds is None:
				return "Unavailable"
			try:
				total_seconds = max(0, int(seconds))
			except (TypeError, ValueError):
				return str(seconds)

			hours, remainder = divmod(total_seconds, 3600)
			minutes, secs = divmod(remainder, 60)

			if hours:
				return f"{hours}h {minutes}m"
			if minutes:
				return f"{minutes}m {secs}s"
			return f"{secs}s"

		def format_text(value: Any) -> str:
			if value is None:
				return "Unavailable"
			return str(value).replace("_", " ").title()

		lines = ["-" * 60, "Power_Module"]

		source = metrics.get("Power_Source")
		lines.append(f"Power_Source: {str(source).upper() if source is not None else 'Unavailable'}")

		present = metrics.get("Power_Battery_Present")
		lines.append(
			f"Power_Battery_Present: "
			f"{present if present is not None else 'Unavailable'}"
		)




		if present is True:
			lines.append(
				f"Power_Battery_Percentage: "
				f"{format_percent(metrics.get('Power_Battery_Percentage'))}"
			)
			lines.append(
				f"Power_Battery_Charging_State: "
				f"{format_text(metrics.get('Power_Battery_Charging_State'))}"
			)
			lines.append(
				f"Power_Battery_Time_Remaining: "
				f"{format_duration(metrics.get('Power_Battery_Time_Remaining'))}"
			)
			lines.append(
				f"Power_Battery_Health: "
				f"{format_percent(metrics.get('Power_Battery_Health'))}"
			)
			lines.append(
				f"Power_Battery_Design_Capacity: "
				f"{format_capacity_mwh(metrics.get('Power_Battery_Design_Capacity'))}"
			)
			lines.append(
				f"Power_Battery_Full_Charge_Capacity: "
				f"{format_capacity_mwh(metrics.get('Power_Battery_Full_Charge_Capacity'))}"
			)
			lines.append(
				f"Power_Battery_Cycle_Count: "
				f"{metrics.get('Power_Battery_Cycle_Count') if metrics.get('Power_Battery_Cycle_Count') is not None else 'Unavailable'}"
			)

		lines.append("-" * 60)
		print_raw("\n".join(lines))


	def _run(self) -> None:
		while True:
			with self._lock:
				if not self._running or self._stop_event is None: return
				stop_event, settings = self._stop_event, dict(self._settings)
			self._sync_requests(settings); hardware, live = self._collect_system(settings)
			live.update(self._collect_component_power(settings))
			with self._lock: self._hardware = hardware; self._live = live; first = not self._logged_first and bool(hardware or live); self._logged_first = self._logged_first or first
			if first: self._print_power_module_block()
			if hardware or live: self._notify()
			if stop_event.wait(SAMPLE_INTERVAL_SECONDS): return

	def _collect_system(self, settings: dict[str, bool]) -> tuple[dict[str, Any], dict[str, Any]]:
		status = None
		try: status = self._windows.status()
		except Exception as error: self._warn_once("system-status", "Windows system power status unavailable: %s", error)
		if status is None and psutil is not None:
			battery = psutil.sensors_battery(); status = {"ac_line": 1 if battery and battery.power_plugged else 0 if battery else 255, "battery_flag": 0 if battery else BATTERY_FLAG_NO_BATTERY, "percentage": int(battery.percent) if battery else 255, "remaining": int(battery.secsleft) if battery and battery.secsleft >= 0 else 0xFFFFFFFF}
		return self._normalize_system(status, settings)

	def _normalize_system(self, status: dict[str, Any] | None, settings: dict[str, bool]) -> tuple[dict[str, Any], dict[str, Any]]:
		if status is None: return {}, {}
		present = not (int(status.get("battery_flag", BATTERY_FLAG_NO_BATTERY)) & BATTERY_FLAG_NO_BATTERY)
		hardware = {"battery": {"present": present}}; live: dict[str, Any] = {}
		ac_line, percent, remaining, flags = int(status.get("ac_line", 255)), int(status.get("percentage", 255)), int(status.get("remaining", 0xFFFFFFFF)), int(status.get("battery_flag", 0))
		live["power_source"] = "ac" if ac_line == 1 else "battery" if ac_line == 0 and present else "unknown"
		if not present: return hardware, live
		battery = {}
		if 0 <= percent <= 100: battery["percentage"] = float(percent)
		if settings.get("Show Charging State"):
			battery["charging_state"] = "charging" if flags & BATTERY_FLAG_CHARGING else "discharging" if ac_line == 0 else "full" if ac_line == 1 and percent == 100 else "not_charging" if ac_line == 1 else "unknown"
		if remaining != 0xFFFFFFFF and remaining >= 0: battery["time_remaining_seconds"] = remaining
		if battery: live["battery"] = battery
		if time.monotonic() - self._last_details >= BATTERY_DETAILS_INTERVAL_SECONDS:
			self._last_details = time.monotonic(); self._battery_details = self._read_battery_details()
		hardware["battery"].update(self._battery_details)
		return hardware, live

	def _read_battery_details(self) -> dict[str, Any]:
		try: details = self._windows.details()
		except Exception as error: self._warn_once("battery-details", "Windows detailed battery information unavailable: %s", error); return {}
		absolute = [item for item in details if not item.get("relative") and item.get("design", 0) > 0 and item.get("full", 0) > 0]
		if len(absolute) != len(details) or not absolute: return {}
		design, full = sum(item["design"] for item in absolute), sum(item["full"] for item in absolute)
		battery = {"design_capacity_mwh": design, "full_charge_capacity_mwh": full, "health_percent": round(full / design * 100, 1)}
		cycles = {item.get("cycle") for item in absolute if item.get("cycle", 0) > 0}
		if len(absolute) == 1 and len(cycles) == 1: battery["cycle_count"] = cycles.pop()
		return battery

	def _sync_requests(self, settings: dict[str, bool]) -> None:
		for module, key in ((self.cpu_module, "Show CPU Power Usage"), (self.gpu_module, "Show GPU Power Usage")):
			method = getattr(module, "set_internal_power_request", None)
			if callable(method): method("Power", settings.get(key, False))

	def _release_requests(self) -> None:
		for module in (self.cpu_module, self.gpu_module):
			method = getattr(module, "set_internal_power_request", None)
			if callable(method): method("Power", False)

	def _collect_component_power(self, settings: dict[str, bool]) -> dict[str, float]:
		cpu_needed, gpu_needed = settings.get("Show CPU Power Usage", False), settings.get("Show GPU Power Usage", False)
		cpu_running, gpu_running = bool(getattr(self.cpu_module, "is_running", lambda: False)()), bool(getattr(self.gpu_module, "is_running", lambda: False)())
		self._fallback.configure(cpu_needed and not cpu_running, gpu_needed and not gpu_running)
		result = {}
		if cpu_needed and cpu_running:
			value = getattr(self.cpu_module, "get_internal_power_w", lambda: None)()
			if value is not None: result["cpu_power_w"] = value
		if gpu_needed and gpu_running:
			value = getattr(self.gpu_module, "get_internal_power_w", lambda: None)()
			if value is not None: result["gpu_power_w"] = value
		result.update(self._fallback.collect())
		return result

	def _notify(self) -> None:
		latest = self.get_latest()
		with self._lock: listeners = list(self._listeners)
		for listener in listeners:
			try: listener(latest)
			except Exception: LOGGER.exception("StatMonitor Power listener failed")

	def _warn_once(self, key: str, message: str, *args) -> None:
		with self._lock:
			if key in self._warned: return
			self._warned.add(key)
		LOGGER.warning(message, *args)
