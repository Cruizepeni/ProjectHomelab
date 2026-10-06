

from __future__ import annotations

from StatMonitorOutput import print_raw

import ctypes
import ctypes.wintypes as wintypes
import copy
import hashlib
import json
import logging
import os
import re
import shutil
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
SAMPLE_INTERVAL = 1.0
TOPOLOGY_INTERVAL = 5.0
SMART_FAST_INTERVAL = 30.0
SMART_SLOW_INTERVAL = 300.0
SETTINGS = (
	"Show Internal Drives", "Show External USB Drives", "Show Network Drives", "Show Removable Drives",
	"Show Custom User Drive Name", "Show Drive Model", "Show Drive Letter", "Show Drive Type",
	"Show Drive Size", "Show Free Space", "Show Drive Temperature", "Show Drive Health", "Show Drive Wear",
	"Show Current Drive Usage", "Show Read Write Speed", "Open Drive In File Manager",
)


def normalize_mount_root(path: str) -> str:
	value = str(path).replace("/", "\\").strip()
	if len(value) == 2 and value[1] == ":":
		value += "\\"
	if len(value) > 3:
		value = value.rstrip("\\")
	return value.lower()

DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE = 2, 3, 4
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
PROPERTY_STANDARD_QUERY = 0
STORAGE_DEVICE_PROPERTY = 0
STORAGE_SEEK_PENALTY_PROPERTY = 7
PDH_FMT_DOUBLE = 0x200
ERROR_SUCCESS = 0
PDH_CSTATUS_VALID_DATA = 0x0
PDH_CSTATUS_NEW_DATA = 0x1
DWORD_PTR = ctypes.c_size_t


class DISK_EXTENT(ctypes.Structure):
	_fields_ = [("DiskNumber", wintypes.DWORD), ("StartingOffset", ctypes.c_longlong), ("ExtentLength", ctypes.c_longlong)]


class VOLUME_DISK_EXTENTS(ctypes.Structure):
	_fields_ = [("NumberOfDiskExtents", wintypes.DWORD), ("Extents", DISK_EXTENT * 1)]


class STORAGE_PROPERTY_QUERY(ctypes.Structure):
	_fields_ = [("PropertyId", wintypes.DWORD), ("QueryType", wintypes.DWORD), ("AdditionalParameters", ctypes.c_ubyte * 1)]


class STORAGE_DEVICE_DESCRIPTOR(ctypes.Structure):
	_fields_ = [
		("Version", wintypes.DWORD), ("Size", wintypes.DWORD), ("DeviceType", ctypes.c_ubyte),
		("DeviceTypeModifier", ctypes.c_ubyte), ("RemovableMedia", ctypes.c_ubyte),
		("CommandQueueing", ctypes.c_ubyte), ("VendorIdOffset", wintypes.DWORD),
		("ProductIdOffset", wintypes.DWORD), ("ProductRevisionOffset", wintypes.DWORD),
		("SerialNumberOffset", wintypes.DWORD), ("BusType", wintypes.DWORD),
		("RawPropertiesLength", wintypes.DWORD), ("RawDeviceProperties", ctypes.c_ubyte * 1),
	]


class DEVICE_SEEK_PENALTY_DESCRIPTOR(ctypes.Structure):
	_fields_ = [("Version", wintypes.DWORD), ("Size", wintypes.DWORD), ("IncursSeekPenalty", wintypes.BOOL)]


class PDH_FMT_COUNTERVALUE(ctypes.Structure):
	_fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class SmartctlProvider:
	def __init__(self, project_root: Path):
		self.project_root = project_root
		self._path: str | None = None
		self._warned: set[str] = set()
		self._cache: dict[int, dict[str, Any]] = {}
		self.search_locations = [
			str(self.project_root / "Dependencies" / "StatMonitor" / "smartctl.exe"),
			str(self.project_root / "Dependencies" / "StatMonitor" / "smartctl"),
			str(self.project_root / "Dependencies" / "StatMonitor" / "smartmontools" / "bin64" / "smartctl.exe"),
			str(self.project_root / "Dependencies" / "StatMonitor" / "smartmontools" / "bin" / "smartctl.exe"),
			str(self.project_root / "Dependencies" / "StatMonitor" / "smartmontools" / "bin" / "smartctl"),
			"PATH:smartctl",
		]

	def _locate(self) -> str | None:
		if self._path is not None:
			return self._path
		for candidate in (
			self.project_root / "Dependencies" / "StatMonitor" / "smartctl.exe",
			self.project_root / "Dependencies" / "StatMonitor" / "smartctl",
			self.project_root / "Dependencies" / "StatMonitor" / "smartmontools" / "bin64" / "smartctl.exe",
			self.project_root / "Dependencies" / "StatMonitor" / "smartmontools" / "bin" / "smartctl.exe",
			self.project_root / "Dependencies" / "StatMonitor" / "smartmontools" / "bin" / "smartctl",
		):
			if candidate.is_file():
				self._path = str(candidate)
				return self._path
		self._path = shutil.which("smartctl")
		if self._path is None:
			self._warn_once("missing-executable", "SMART provider unavailable: smartctl executable was not found")
		return self._path

	def collect(self, targets: list[dict[str, Any]], settings: dict[str, bool], now: float | None = None) -> dict[int, dict[str, Any]]:
		if not any(settings.get(key, False) for key in ("Show Drive Temperature", "Show Drive Health", "Show Drive Wear")):
			return {}
		path = self._locate()
		if path is None:
			return {}
		now = time.monotonic() if now is None else now
		result = {}
		seen: set[int] = set()

		for target in targets:
			disk_number = self._positive_disk_number(target.get("disk_number"))
			if disk_number is None or disk_number in seen:
				continue
			seen.add(disk_number)

			bus = str(target.get("bus") or "").lower()
			last_returncode = 0
			last_stderr = ""
			last_json_error: json.JSONDecodeError | None = None
			handled_low_power = False

			for command in self._commands(path, target):
				try:
					completed = subprocess.run(
						command,
						capture_output=True,
						text=True,
						timeout=12,
						check=False,
						creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
					)
				except subprocess.TimeoutExpired as error:
					self._warn_once(
						f"timeout-{disk_number}",
						"SMART query timed out for physical disk %s: %s",
						disk_number,
						error,
					)
					break
				except OSError as error:
					self._warn_once(
						f"os-{disk_number}-{type(error).__name__}",
						"SMART query could not run for physical disk %s: %s",
						disk_number,
						error,
					)
					break

				last_returncode = int(completed.returncode)
				last_stderr = completed.stderr
				stdout = completed.stdout.strip()
				if not stdout:
					continue

				try:
					payload = json.loads(stdout)
				except json.JSONDecodeError as error:
					last_json_error = error
					continue

				data = self._normalize_payload(payload)
				if data:
					data["sampled_at"] = now
					self._cache[disk_number] = data
					result[disk_number] = data
					self._clear_device_warnings(disk_number)
					break

				if self._is_low_power_skip(payload, completed.returncode):
					cached = self._cache.get(disk_number)
					if cached:
						result[disk_number] = cached
					handled_low_power = True
					break

			if disk_number in result or handled_low_power:
				continue

			if bus == "usb":
				self._warn_once(
					f"usb-unavailable-{disk_number}",
					"SMART telemetry unavailable for physical disk %s through the current USB bridge",
					disk_number,
				)
			elif last_json_error is not None:
				self._warn_once(
					f"json-{disk_number}",
					"SMART query returned malformed JSON for physical disk %s: %s",
					disk_number,
					last_json_error,
				)
			elif last_returncode:
				if last_stderr.strip():
					self._handle_no_json(disk_number, last_returncode, last_stderr)
				else:
					self._warn_once(
						f"status-{disk_number}-{last_returncode}",
						"SMART telemetry unavailable for physical disk %s",
						disk_number,
					)

		return result

	def _commands(self, path: str, target: dict[str, Any]) -> list[list[str]]:
		base = [path, "-a", "-j"]
		if self._use_standby_guard(target):
			base.extend(["-n", "standby"])

		device = f"/dev/pd{int(target['disk_number'])}"
		commands = [base + [device]]

		if str(target.get("bus") or "").lower() == "usb":
			commands.append([path, "-a", "-j", "-d", "sat", device])
			commands.append([path, "-a", "-j", "-d", "scsi", device])

		return commands

	def _command(self, path: str, target: dict[str, Any]) -> list[str]:

		return self._commands(path, target)[0]

	@staticmethod
	def _use_standby_guard(target: dict[str, Any]) -> bool:
		bus = str(target.get("bus") or "").lower()
		media = str(target.get("media") or "").lower()
		return media == "hdd" and bus in {"sata", "sas", "scsi"}

	@staticmethod
	def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
		data = {}
		temperature = payload.get("temperature", {}).get("current")
		passed = payload.get("smart_status", {}).get("passed")
		wear = payload.get("endurance_used", {}).get("current_percent")
		if isinstance(temperature, (int, float)) and not isinstance(temperature, bool): data["temperature_c"] = temperature
		if isinstance(passed, bool): data["health"] = "passed" if passed else "failed"
		if isinstance(wear, (int, float)) and not isinstance(wear, bool): data["wear_used_percent"] = wear
		return data

	@staticmethod
	def _is_low_power_skip(payload: dict[str, Any], returncode: int) -> bool:
		messages = payload.get("smartctl", {}).get("messages", [])
		text = " ".join(str(item.get("string", "")) for item in messages if isinstance(item, dict)).lower()
		return bool(returncode) and any(token in text for token in ("standby", "sleep", "low-power", "low power"))

	def _handle_no_json(self, disk_number: int, returncode: int, stderr: str) -> None:
		if returncode:
			message = " ".join(stderr.split())[:240] if stderr else f"smartctl status bitmask {returncode}"
			self._warn_once(f"no-json-{disk_number}-{returncode}", "SMART query for physical disk %s produced no JSON: %s", disk_number, message)

	@staticmethod
	def _positive_disk_number(value: Any) -> int | None:
		try:
			number = int(value)
			return number if number >= 0 else None
		except (TypeError, ValueError):
			return None

	def _clear_device_warnings(self, disk_number: int) -> None:
		prefixes = (f"timeout-{disk_number}", f"json-{disk_number}", f"os-{disk_number}", f"no-json-{disk_number}", f"status-{disk_number}")
		self._warned = {key for key in self._warned if not key.startswith(prefixes)}

	def _warn_once(self, key: str, message: str, *args) -> None:
		if key in self._warned:
			return
		self._warned.add(key)
		LOGGER.warning(message, *args)


class WindowsDrivesProvider:
	def __init__(self):
		self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None
		self._pdh = ctypes.WinDLL("pdh.dll") if os.name == "nt" else None
		self._query = None
		self._counters: dict[str, tuple[Any, Any, Any]] = {}
		self._pdh_primed = False
		self._metadata_cache: dict[int, dict[str, Any]] = {}
		self._bind_kernel32()
		self._bind_pdh()

	def _bind_kernel32(self) -> None:
		if self._kernel32 is None:
			return
		self._kernel32.GetLogicalDriveStringsW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
		self._kernel32.GetLogicalDriveStringsW.restype = wintypes.DWORD
		self._kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
		self._kernel32.GetDriveTypeW.restype = wintypes.UINT
		self._kernel32.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
		self._kernel32.GetVolumeInformationW.restype = wintypes.BOOL
		self._kernel32.GetVolumeNameForVolumeMountPointW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
		self._kernel32.GetVolumeNameForVolumeMountPointW.restype = wintypes.BOOL
		self._kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
		self._kernel32.CreateFileW.restype = wintypes.HANDLE
		self._kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
		self._kernel32.DeviceIoControl.restype = wintypes.BOOL
		self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
		self._kernel32.CloseHandle.restype = wintypes.BOOL

	def _bind_pdh(self) -> None:
		if self._pdh is None:
			return
		self._pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, DWORD_PTR, ctypes.POINTER(ctypes.c_void_p)]; self._pdh.PdhOpenQueryW.restype = wintypes.LONG
		self._pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, DWORD_PTR, ctypes.POINTER(ctypes.c_void_p)]; self._pdh.PdhAddEnglishCounterW.restype = wintypes.LONG
		self._pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]; self._pdh.PdhCollectQueryData.restype = wintypes.LONG
		self._pdh.PdhGetFormattedCounterValue.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(PDH_FMT_COUNTERVALUE)]; self._pdh.PdhGetFormattedCounterValue.restype = wintypes.LONG
		self._pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]; self._pdh.PdhCloseQuery.restype = wintypes.LONG

	def discover(self) -> list[dict[str, Any]]:
		if self._kernel32 is None:
			return []
		buffer = ctypes.create_unicode_buffer(32768)
		length = self._kernel32.GetLogicalDriveStringsW(len(buffer), buffer)
		return [self._read_volume(root) for root in buffer[:length].split("\0") if root]

	def get_volume(self, root: str) -> dict[str, Any] | None:
		if self._kernel32 is None:
			return None
		return self._read_volume(normalize_mount_root(root))

	def _read_volume(self, root: str) -> dict[str, Any]:
		drive_type = int(self._kernel32.GetDriveTypeW(root))
		label = ctypes.create_unicode_buffer(261); filesystem = ctypes.create_unicode_buffer(261)
		serial = wintypes.DWORD(); component = wintypes.DWORD(); flags = wintypes.DWORD()
		self._kernel32.GetVolumeInformationW(root, label, len(label), ctypes.byref(serial), ctypes.byref(component), ctypes.byref(flags), filesystem, len(filesystem))
		volume_guid = ctypes.create_unicode_buffer(50)
		has_guid = bool(self._kernel32.GetVolumeNameForVolumeMountPointW(root, volume_guid, len(volume_guid)))
		drive_id = self._normalize_volume_guid(volume_guid.value) if has_guid else "volume-" + root.rstrip("\\").lower().replace(":", "")
		if drive_type == DRIVE_REMOTE: drive_class = "network"
		elif drive_type == DRIVE_REMOVABLE: drive_class = "removable"
		elif drive_type == DRIVE_FIXED: drive_class = "unknown_local"
		else: drive_class = None
		return {"drive_id": drive_id, "mountpoint": root, "drive_letter": root[:2].upper(), "filesystem": filesystem.value, "name": label.value or None, "drive_class": drive_class, "physical_disks": self._volume_disk_numbers(root)}

	def enrich(self, volume: dict[str, Any]) -> dict[str, Any]:
		metadata = [self.disk_metadata(number) for number in volume.get("physical_disks", [])]
		metadata = [item for item in metadata if item]
		if not metadata:
			return {}
		result = {}
		for key in ("model", "bus", "media"):
			values = {item.get(key) for item in metadata if item.get(key)}
			if len(values) == 1: result[key] = values.pop()
		if volume.get("drive_class") == "unknown_local":
			if any(item.get("removable") for item in metadata): result["drive_class"] = "removable"
			elif any(item.get("bus") == "usb" for item in metadata): result["drive_class"] = "external_usb"
			elif all(item.get("bus") and item.get("bus") != "usb" for item in metadata): result["drive_class"] = "internal"
		return result

	def disk_metadata(self, number: int) -> dict[str, Any]:
		try:
			disk_number = int(number)
		except (TypeError, ValueError):
			return {}
		if disk_number not in self._metadata_cache:
			metadata = self._disk_metadata(disk_number)
			if metadata:
				metadata["disk_number"] = disk_number
			self._metadata_cache[disk_number] = metadata
		return dict(self._metadata_cache.get(disk_number, {}))

	def clear_disk_metadata_cache(self) -> None:
		self._metadata_cache.clear()

	def _volume_disk_numbers(self, root: str) -> list[int]:
		handle = self._kernel32.CreateFileW("\\\\.\\" + root.rstrip("\\"), 0, 3, None, 3, 0, None)
		if handle == INVALID_HANDLE_VALUE: return []
		try:
			buffer = ctypes.create_string_buffer(4096); returned = wintypes.DWORD()
			if not self._kernel32.DeviceIoControl(handle, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, None, 0, buffer, len(buffer), ctypes.byref(returned), None): return []
			count = int(ctypes.cast(buffer, ctypes.POINTER(VOLUME_DISK_EXTENTS)).contents.NumberOfDiskExtents)
			array = (DISK_EXTENT * max(1, min(count, 128))).from_address(ctypes.addressof(buffer) + VOLUME_DISK_EXTENTS.Extents.offset)
			return [int(item.DiskNumber) for item in array[:count]]
		finally: self._kernel32.CloseHandle(handle)

	def _disk_metadata(self, number: int) -> dict[str, Any]:
		handle = self._kernel32.CreateFileW(f"\\\\.\\PhysicalDrive{number}", 0, 3, None, 3, 0, None)
		if handle == INVALID_HANDLE_VALUE: return {}
		try:
			result = self._storage_descriptor(handle); seek = self._seek_penalty(handle)
			if seek is not None: result["media"] = "hdd" if seek else "ssd"
			return result
		finally: self._kernel32.CloseHandle(handle)

	def _storage_descriptor(self, handle: Any) -> dict[str, Any]:
		query = STORAGE_PROPERTY_QUERY(PropertyId=STORAGE_DEVICE_PROPERTY, QueryType=PROPERTY_STANDARD_QUERY)
		buffer = ctypes.create_string_buffer(4096); returned = wintypes.DWORD()
		if not self._kernel32.DeviceIoControl(handle, IOCTL_STORAGE_QUERY_PROPERTY, ctypes.byref(query), ctypes.sizeof(query), buffer, len(buffer), ctypes.byref(returned), None): return {}
		descriptor = ctypes.cast(buffer, ctypes.POINTER(STORAGE_DEVICE_DESCRIPTOR)).contents
		model = None
		if descriptor.ProductIdOffset and descriptor.ProductIdOffset < returned.value:
			model = re.sub(r"\s+", " ", buffer[descriptor.ProductIdOffset:].split(b"\0", 1)[0].decode("ascii", "ignore").strip())
		bus = {1: "scsi", 7: "usb", 8: "raid", 9: "iscsi", 10: "sas", 11: "sata", 12: "sd", 13: "mmc", 14: "virtual", 15: "file_backed_virtual", 16: "storage_spaces", 17: "nvme"}.get(int(descriptor.BusType))
		return {key: value for key, value in (("model", model), ("bus", bus), ("removable", bool(descriptor.RemovableMedia))) if value is not None}

	def _seek_penalty(self, handle: Any) -> bool | None:
		query = STORAGE_PROPERTY_QUERY(PropertyId=STORAGE_SEEK_PENALTY_PROPERTY, QueryType=PROPERTY_STANDARD_QUERY)
		buffer = ctypes.create_string_buffer(ctypes.sizeof(DEVICE_SEEK_PENALTY_DESCRIPTOR)); returned = wintypes.DWORD()
		if not self._kernel32.DeviceIoControl(handle, IOCTL_STORAGE_QUERY_PROPERTY, ctypes.byref(query), ctypes.sizeof(query), buffer, len(buffer), ctypes.byref(returned), None): return None
		return bool(ctypes.cast(buffer, ctypes.POINTER(DEVICE_SEEK_PENALTY_DESCRIPTOR)).contents.IncursSeekPenalty)

	def configure_pdh(self, drives: list[dict[str, Any]]) -> None:
		self.close_pdh()
		if self._pdh is None: return
		query = ctypes.c_void_p()
		if self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)) != ERROR_SUCCESS: return
		counters = {}
		for drive in drives:
			letter = drive.get("drive_letter")
			if not letter: continue
			handles = []
			for path in (f"\\LogicalDisk({letter})\\% Idle Time", f"\\LogicalDisk({letter})\\Disk Read Bytes/sec", f"\\LogicalDisk({letter})\\Disk Write Bytes/sec"):
				handle = ctypes.c_void_p()
				if self._pdh.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(handle)) == ERROR_SUCCESS: handles.append(handle)
			if len(handles) == 3: counters[drive["drive_id"]] = tuple(handles)
		self._query, self._counters, self._pdh_primed = query, counters, False

	def has_pdh_counters(self) -> bool:
		return bool(self._query is not None and self._counters)

	def is_pdh_primed(self) -> bool:
		return bool(self._pdh_primed)

	def collect_pdh(self) -> dict[str, dict[str, Any]]:
		if self._pdh is None or self._query is None or self._pdh.PdhCollectQueryData(self._query) != ERROR_SUCCESS: return {}
		if not self._pdh_primed:
			self._pdh_primed = True
			return {}
		result = {}
		for drive_id, handles in self._counters.items():
			values = []
			for handle in handles:
				status = wintypes.DWORD(); value = PDH_FMT_COUNTERVALUE()
				if self._pdh.PdhGetFormattedCounterValue(handle, PDH_FMT_DOUBLE, ctypes.byref(status), ctypes.byref(value)) != ERROR_SUCCESS: break
				if int(value.CStatus) not in (PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA): break
				values.append(value.doubleValue)
			if len(values) == 3: result[drive_id] = {"activity_percent": max(0.0, min(100.0, 100.0 - values[0])), "read_bytes_per_sec": max(0.0, values[1]), "write_bytes_per_sec": max(0.0, values[2])}
		return result

	def close_pdh(self) -> None:
		if self._pdh is not None and self._query is not None: self._pdh.PdhCloseQuery(self._query)
		self._query, self._counters, self._pdh_primed = None, {}, False

	def close(self) -> None: self.close_pdh()

	@staticmethod
	def _normalize_volume_guid(value: str) -> str:
		match = re.search(r"volume\{([^}]+)\}", value.strip().lower())
		return "{" + match.group(1).upper() + "}" if match else value.strip()


class StatMonitorStorageDrives:


	def __init__(self, project_root: str | os.PathLike[str] | None = None):
		self.project_root = Path(project_root) if project_root else resolve_project_root()
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._drives: dict[str, dict[str, Any]] = {}
		self._live: dict[str, dict[str, Any]] = {}
		self._running = False
		self._thread: threading.Thread | None = None
		self._stop_event: threading.Event | None = None
		self._provider = WindowsDrivesProvider() if os.name == "nt" else None
		self._smartctl = SmartctlProvider(self.project_root)
		self._last_topology = 0.0
		self._last_space = 0.0
		self._last_smart = 0.0
		self._logged_first = False
		self._started_at = 0.0
		self._pdh_startup_ready = False
		self._warned: set[str] = set()
		self._topology_signature: tuple = ()

	def subscribe(self, listener: Callable[[dict], None]) -> None:
		with self._lock:
			if listener not in self._listeners: self._listeners.append(listener)

	def unsubscribe(self, listener: Callable[[dict], None]) -> None:
		with self._lock:
			if listener in self._listeners: self._listeners.remove(listener)

	def start(self) -> None:
		with self._lock:
			if self._running: return
			self._running = True
			self._stop_event = threading.Event()
			self._logged_first = False
			self._started_at = time.monotonic()
			self._pdh_startup_ready = False
			self._thread = threading.Thread(target=self._run, name="StatMonitorStorageDrives", daemon=True)
			self._thread.start()

	def stop(self) -> None:
		with self._lock:
			if not self._running and self._thread is None: return
			self._running = False
			stop_event, thread = self._stop_event, self._thread
			self._thread = None
		if stop_event: stop_event.set()
		if thread and thread is not threading.current_thread(): thread.join(timeout=4)
		if self._provider: self._provider.close()
		with self._lock:
			self._live = {}
			self._stop_event = None
		self._notify()

	def is_running(self) -> bool:
		with self._lock: return self._running

	def update_settings(self, settings: dict[str, bool]) -> None:
		if not isinstance(settings, dict): raise ValueError("Drives settings must be an object")
		with self._lock:
			self._settings = {key: bool(settings.get(key, False)) for key in SETTINGS}
			if self._running: self._notify()

	def get_latest(self) -> dict:
		with self._lock:
			settings = dict(self._settings); hardware = {"drives": []}; live = {"drives": []}
			for drive in self._visible_drives(settings):
				hardware_drive = {"drive_id": str(drive["drive_id"]), "mount_path": drive["mountpoint"]}
				if settings.get("Show Custom User Drive Name") and drive.get("name"): hardware_drive["name"] = drive["name"]
				if settings.get("Show Drive Letter") and drive.get("drive_letter"): hardware_drive["drive_letter"] = drive["drive_letter"]
				if settings.get("Show Drive Type") and drive.get("drive_type"): hardware_drive["drive_type"] = copy.deepcopy(drive["drive_type"])
				if settings.get("Show Drive Size") and drive.get("size_bytes") is not None: hardware_drive["size_bytes"] = int(drive["size_bytes"])
				if settings.get("Show Drive Model") and drive.get("model"): hardware_drive["model"] = drive["model"]
				if settings.get("Open Drive In File Manager"): hardware_drive["open_path"] = drive["mountpoint"]
				hardware["drives"].append(hardware_drive)
				live_drive = {"drive_id": str(drive["drive_id"])}; values = self._live.get(drive["drive_id"], {})
				for key, setting in (("free_bytes", "Show Free Space"), ("activity_percent", "Show Current Drive Usage"), ("read_bytes_per_sec", "Show Read Write Speed"), ("write_bytes_per_sec", "Show Read Write Speed"), ("temperature_c", "Show Drive Temperature"), ("health", "Show Drive Health"), ("wear_used_percent", "Show Drive Wear")):
					if settings.get(setting) and key in values: live_drive[key] = values[key]
				live["drives"].append(live_drive)
			return {"hardware": hardware, "live": live}


	@staticmethod
	def _derive_drive_health(
		health_check: Any,
		wear_used_percent: Any,
	) -> tuple[str | None, float | None]:

		check = str(health_check).strip().lower() if health_check is not None else None



		if check == "failed":
			remaining = None
			if isinstance(wear_used_percent, (int, float)) and not isinstance(wear_used_percent, bool):
				remaining = max(0.0, min(100.0, 100.0 - float(wear_used_percent)))
			return "critical", remaining

		if not isinstance(wear_used_percent, (int, float)) or isinstance(wear_used_percent, bool):
			return None, None

		remaining = max(0.0, min(100.0, 100.0 - float(wear_used_percent)))

		if remaining >= 90.0:
			condition = "healthy"
		elif remaining >= 75.0:
			condition = "good"
		elif remaining >= 50.0:
			condition = "average"
		elif remaining >= 25.0:
			condition = "below_average"
		elif remaining >= 10.0:
			condition = "poor"
		else:
			condition = "critical"

		return condition, remaining

	def get_metric_snapshot(self) -> dict[str, Any]:

		latest = self.get_latest()
		hardware_drives = latest.get("hardware", {}).get("drives", [])
		live_drives = latest.get("live", {}).get("drives", [])

		live_by_id = {
			str(item.get("drive_id")): item
			for item in live_drives
			if isinstance(item, dict) and item.get("drive_id") is not None
		}



		with self._lock:
			settings = dict(self._settings)
			raw_live_by_id = {
				str(drive_id): copy.deepcopy(values)
				for drive_id, values in self._live.items()
			}

		result = []
		for hardware in hardware_drives:
			if not isinstance(hardware, dict):
				continue

			drive_id = str(hardware.get("drive_id"))
			live = live_by_id.get(drive_id, {})
			raw_live = raw_live_by_id.get(drive_id, {})
			drive_type = hardware.get("drive_type")
			drive_type = drive_type if isinstance(drive_type, dict) else {}

			health_check = raw_live.get("health") if settings.get("Show Drive Health") else None
			wear_used = raw_live.get("wear_used_percent")
			health, health_remaining = (
				self._derive_drive_health(health_check, wear_used)
				if settings.get("Show Drive Health")
				else (None, None)
			)

			result.append({
				"Drive_ID": drive_id,
				"Drive_Name": hardware.get("name"),
				"Drive_Model": hardware.get("model"),
				"Drive_Letter": hardware.get("drive_letter"),
				"Drive_Mount_Path": hardware.get("mount_path"),
				"Drive_Open_Path": hardware.get("open_path"),
				"Drive_Class": drive_type.get("class"),
				"Drive_Bus": drive_type.get("bus"),
				"Drive_Media_Type": drive_type.get("media"),
				"Drive_Size": hardware.get("size_bytes"),
				"Drive_Free_Space": live.get("free_bytes"),
				"Drive_Activity": live.get("activity_percent"),
				"Drive_Read_Speed": live.get("read_bytes_per_sec"),
				"Drive_Write_Speed": live.get("write_bytes_per_sec"),
				"Drive_Temperature": live.get("temperature_c"),
				"Drive_Health_Check": health_check,
				"Drive_Health": health,
				"Drive_Health_Remaining": health_remaining,
				"Drive_Wear": (
					wear_used
					if settings.get("Show Drive Wear")
					else None
				),
			})

		return {"Drive_Individual_Drives": result}

	def _print_storage_module_block(self) -> None:
		metrics = self.get_metric_snapshot()
		drives = metrics.get("Drive_Individual_Drives", [])
		drives = drives if isinstance(drives, list) else []

		def format_bytes(value: Any) -> str:
			if value is None:
				return "Unavailable"
			try:
				number = float(value)
			except (TypeError, ValueError):
				return str(value)
			units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
			index = 0
			while abs(number) >= 1024.0 and index < len(units) - 1:
				number /= 1024.0
				index += 1
			return f"{number:.1f} {units[index]}"

		def format_speed(value: Any) -> str:
			return "Unavailable" if value is None else f"{format_bytes(value)}/s"

		def format_percent(value: Any) -> str:
			return "Unavailable" if value is None else f"{float(value):.1f}%"

		def format_temperature(value: Any) -> str:
			return "Unavailable" if value is None else f"{value} °C"

		def format_class(value: Any) -> str:
			if value is None:
				return "Unavailable"

			value = str(value)
			return {
				"internal": "Internal",
				"external_usb": "External USB",
				"removable": "Removable",
				"network": "Network",
				"unknown_local": "Unknown Local",
			}.get(value.lower(), value.replace("_", " ").title())

		def format_bus(value: Any) -> str:
			if value is None:
				return "Unavailable"
			value = str(value)
			return {
				"nvme": "NVMe",
				"sata": "SATA",
				"sas": "SAS",
				"scsi": "SCSI",
				"usb": "USB",
				"raid": "RAID",
				"iscsi": "iSCSI",
				"sd": "SD",
				"mmc": "MMC",
			}.get(value.lower(), value.replace("_", " ").title())

		def format_media(value: Any) -> str:
			if value is None:
				return "Unavailable"
			value = str(value)
			return {"ssd": "SSD", "hdd": "HDD"}.get(
				value.lower(),
				value.replace("_", " ").title(),
			)

		lines = ["-" * 60, "StorageDrives_Module"]
		lines.append(f"Drive_Individual_Drives: {len(drives)}")

		for index, drive in enumerate(drives, 1):
			lines.append(f"  [{index}]")

			for metric_id in (
				"Drive_ID",
				"Drive_Name",
				"Drive_Model",
				"Drive_Letter",
				"Drive_Mount_Path",
			):
				value = drive.get(metric_id)
				if value is not None:
					lines.append(f"    {metric_id}: {value}")

			for metric_id, formatter in (
				("Drive_Class", format_class),
				("Drive_Bus", format_bus),
				("Drive_Media_Type", format_media),
				("Drive_Size", format_bytes),
				("Drive_Free_Space", format_bytes),
				("Drive_Activity", format_percent),
				("Drive_Read_Speed", format_speed),
				("Drive_Write_Speed", format_speed),
				("Drive_Temperature", format_temperature),
			):
				value = drive.get(metric_id)
				if value is not None:
					lines.append(f"    {metric_id}: {formatter(value)}")

			with self._lock:
				settings = dict(self._settings)

			if settings.get("Show Drive Health"):
				health_check = drive.get("Drive_Health_Check")
				lines.append(
					"    Drive_Health_Check: "
					+ (
						str(health_check).replace("_", " ").title()
						if health_check is not None
						else "Unavailable"
					)
				)

				health = drive.get("Drive_Health")
				lines.append(
					"    Drive_Health: "
					+ (
						str(health).replace("_", " ").title()
						if health is not None
						else "Unavailable"
					)
				)

				remaining = drive.get("Drive_Health_Remaining")
				lines.append(
					"    Drive_Health_Remaining: "
					+ (
						format_percent(remaining)
						if remaining is not None
						else "Unavailable"
					)
				)

			if settings.get("Show Drive Wear"):
				wear = drive.get("Drive_Wear")
				lines.append(
					"    Drive_Wear: "
					+ (
						f"{format_percent(wear)} Used"
						if wear is not None
						else "Unavailable"
					)
				)

		lines.append("-" * 60)
		print_raw("\n".join(lines))


	def _visible_drives(self, settings: dict[str, bool]) -> list[dict[str, Any]]:
		allowed = {"internal": settings.get("Show Internal Drives", False), "unknown_local": settings.get("Show Internal Drives", False), "external_usb": settings.get("Show External USB Drives", False), "removable": settings.get("Show Removable Drives", False), "network": settings.get("Show Network Drives", False)}
		return [drive for drive in self._drives.values() if allowed.get(drive.get("drive_class"), False)]

	def _run(self) -> None:
		while True:
			with self._lock:
				if not self._running or self._stop_event is None: return
				stop_event, settings = self._stop_event, dict(self._settings)
			now = time.monotonic()
			if now - self._last_topology >= TOPOLOGY_INTERVAL:
				self._refresh_topology(); self._last_topology = now
			if now - self._last_space >= TOPOLOGY_INTERVAL:
				self._refresh_space(); self._last_space = now
			self._refresh_pdh(settings); self._refresh_smart(settings, now)
			self._log_first()
			if stop_event.wait(SAMPLE_INTERVAL): return

	def _portable_partitions(self) -> list[dict[str, Any]]:
		if psutil is None: return []
		result = []
		for partition in psutil.disk_partitions(all=False):
			identity = f"{partition.device}|{partition.mountpoint}"
			result.append({"drive_id": "volume-" + hashlib.sha256(identity.encode()).hexdigest()[:24], "mountpoint": partition.mountpoint, "normalized_mountpoint": normalize_mount_root(partition.mountpoint), "filesystem": partition.fstype, "name": None, "drive_letter": None, "drive_class": "unknown_local", "physical_disks": []})
		return result

	def _refresh_topology(self) -> None:
		try:
			portable = self._portable_partitions()
			if self._provider: self._provider.clear_disk_metadata_cache()
			records = []
			for record in portable:
				enrichment = self._provider.get_volume(record["mountpoint"]) if self._provider else None
				if enrichment:
					record["drive_id"] = enrichment.get("drive_id", record["drive_id"])
					record.update({key: value for key, value in enrichment.items() if key != "mountpoint"})
				if self._provider: record.update(self._provider.enrich(record))
				record["drive_type"] = {key: value for key, value in (("class", record.get("drive_class")), ("bus", record.get("bus")), ("media", record.get("media"))) if value}
				records.append(record)
			signature = tuple(sorted((str(record["drive_id"]), record.get("normalized_mountpoint", normalize_mount_root(record["mountpoint"])), record.get("drive_letter"), record.get("drive_class"), tuple(record.get("physical_disks", []))) for record in records))
			with self._lock:
				changed = signature != self._topology_signature
				self._topology_signature = signature
				self._drives = {str(record["drive_id"]): record for record in records}; self._live = {key: value for key, value in self._live.items() if key in self._drives}
			if changed:
				if self._provider:
					self._provider.configure_pdh(list(self._drives.values()))
					with self._lock:
						self._pdh_startup_ready = False
				self._notify()
		except Exception as error: self._warn_once("topology", "Drive topology refresh failed: %s", error)

	def _refresh_space(self) -> None:
		if psutil is None: return
		with self._lock: drives = list(self._drives.values())
		for drive in drives:
			try:
				usage = psutil.disk_usage(drive["mountpoint"])
				with self._lock:
					drive["size_bytes"] = int(usage.total); self._live.setdefault(drive["drive_id"], {})["free_bytes"] = int(usage.free)
			except (OSError, PermissionError): pass
		self._notify()

	def _refresh_pdh(self, settings: dict[str, bool]) -> None:
		needs_pdh = settings.get("Show Current Drive Usage") or settings.get("Show Read Write Speed")
		if not self._provider or not needs_pdh:
			with self._lock:
				self._pdh_startup_ready = True
			return

		was_primed = self._provider.is_pdh_primed()
		values = self._provider.collect_pdh()

		with self._lock:
			for drive_id, data in values.items():
				self._live.setdefault(drive_id, {}).update(data)




			if not self._provider.has_pdh_counters() or was_primed:
				self._pdh_startup_ready = True

		if values:
			self._notify()

	def _refresh_smart(self, settings: dict[str, bool], now: float) -> None:
		if not any(settings.get(key, False) for key in ("Show Drive Temperature", "Show Drive Health", "Show Drive Wear")): return
		interval = SMART_FAST_INTERVAL if settings.get("Show Drive Temperature") else SMART_SLOW_INTERVAL
		if now - self._last_smart < interval: return
		with self._lock: drives = list(self._drives.values())
		targets = self._smart_targets(drives)
		results = self._smartctl.collect(targets, settings, now)
		with self._lock:
			for drive in self._drives.values():
				live = self._live.setdefault(drive["drive_id"], {})
				for key in ("temperature_c", "health", "wear_used_percent"):
					live.pop(key, None)
				live.update(self._filtered_smart(self._aggregate_smart_values(drive, results), settings))
		self._last_smart = now
		self._notify()

	def _smart_targets(self, drives: list[dict[str, Any]]) -> list[dict[str, Any]]:
		targets: dict[int, dict[str, Any]] = {}
		for drive in drives:
			if drive.get("drive_class") == "network":
				continue
			for number in drive.get("physical_disks", []):
				try:
					disk_number = int(number)
				except (TypeError, ValueError):
					continue
				metadata = self._provider.disk_metadata(disk_number) if self._provider else {}
				targets[disk_number] = {"disk_number": disk_number, "bus": metadata.get("bus"), "media": metadata.get("media")}
		return [targets[number] for number in sorted(targets)]

	@staticmethod
	def _aggregate_smart_values(drive: dict[str, Any], results: dict[int, dict[str, Any]]) -> dict[str, Any]:
		disk_numbers = []
		for number in drive.get("physical_disks", []):
			try:
				disk_numbers.append(int(number))
			except (TypeError, ValueError):
				continue
		if len(disk_numbers) == 1:
			return {key: value for key, value in results.get(disk_numbers[0], {}).items() if key != "sampled_at"}
		if len(disk_numbers) <= 1:
			return {}
		aggregated = {}
		for key in ("temperature_c", "health", "wear_used_percent"):
			values = [results[number][key] for number in disk_numbers if key in results.get(number, {})]
			if len(values) == len(disk_numbers) and all(value == values[0] for value in values):
				aggregated[key] = values[0]
		return aggregated

	@staticmethod
	def _filtered_smart(values: dict[str, Any], settings: dict[str, bool]) -> dict[str, Any]:
		result = {}

		if settings.get("Show Drive Temperature") and "temperature_c" in values:
			result["temperature_c"] = values["temperature_c"]

		if settings.get("Show Drive Health") and "health" in values:
			result["health"] = values["health"]




		if (
			(settings.get("Show Drive Health") or settings.get("Show Drive Wear"))
			and "wear_used_percent" in values
		):
			result["wear_used_percent"] = values["wear_used_percent"]

		return result


	def _log_first(self) -> None:
		with self._lock:
			if self._logged_first or not self._drives:
				return

			settings = dict(self._settings)
			visible = self._visible_drives(settings)
			if not visible:
				return

			if settings.get("Show Free Space") and not any(
				"free_bytes" in self._live.get(drive["drive_id"], {})
				for drive in visible
			):
				return

			needs_pdh = settings.get("Show Current Drive Usage") or settings.get("Show Read Write Speed")
			if needs_pdh and not self._pdh_startup_ready:
				return

			needs_smart = any(
				settings.get(key, False)
				for key in ("Show Drive Temperature", "Show Drive Health", "Show Drive Wear")
			)
			if needs_smart and self._last_smart <= 0:
				return

			self._logged_first = True

		self._print_storage_module_block()

	def _notify(self) -> None:
		latest = self.get_latest()
		with self._lock: listeners = list(self._listeners)
		for listener in listeners:
			try: listener(latest)
			except Exception: LOGGER.exception("StatMonitor Drives listener failed")

	def _warn_once(self, key: str, message: str, *args) -> None:
		with self._lock:
			if key in self._warned: return
			self._warned.add(key)
		LOGGER.warning(message, *args)
