

from __future__ import annotations

from StatMonitorOutput import print_raw

import copy
import ctypes
import hashlib
import importlib
import json
import logging
import math
import os
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from StatMonitorPaths import resolve_project_root


LOGGER = logging.getLogger(__name__)
SAMPLE_INTERVAL_SECONDS = 1.0
CIM_TIMEOUT_SECONDS = 8.0
_SETTINGS = (
	"Show Integrated Graphics", "Show Dedicated Graphics", "Show GPU Name",
	"Show Current Usage", "Show VRAM Usage", "Show Temperature", "Show Clock Speed",
	"Show Power Usage", "Show Fan Speed", "Show Driver Version",
)
_LIVE_SETTINGS = (
	"Show Current Usage", "Show VRAM Usage", "Show Temperature", "Show Clock Speed",
	"Show Power Usage", "Show Fan Speed",
)
LHM_GPU_TYPES = {"GpuNvidia", "GpuAmd", "GpuIntel"}
LHM_TYPES: tuple[Any, Any] | None = None
LHM_TYPES_LOCK = threading.Lock()


class StatMonitorGPU:


	def __init__(self, project_root: str | os.PathLike[str] | None = None):
		self.project_root = Path(project_root) if project_root else resolve_project_root()
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._gpus: dict[str, dict[str, Any]] = {}
		self._live: dict[str, dict[str, Any]] = {}
		self._running = False
		self._static_loaded = False
		self._thread: threading.Thread | None = None
		self._stop_event: threading.Event | None = None
		self._lhm_computer: Any = None
		self._lhm_hardware: list[Any] = []
		self._provider_warnings: set[str] = set()
		self._internal_power_consumers: set[str] = set()
		self._logged_first_telemetry = False
		self._logged_static_telemetry = False

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
			self._logged_static_telemetry = False
			settings = dict(self._settings)
		self._ensure_static_inventory(settings)
		self._reconcile_provider(settings)
		with self._lock:
			lhm_active = self._lhm_computer is not None
		if not self._needs_lhm(settings) or not lhm_active:
			self._log_first_telemetry(static_only=True)
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
			self._close_lhm_locked()
			self._live = {}
			self._stop_event = None
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
			self._reconcile_provider(settings)

	def get_internal_power_w(self) -> float | None:
		with self._lock:
			values = list(self._live.values())
		powers = []
		for entry in values:
			try:
				value = float(entry.get("power_w"))
				if value >= 0 and value == value:
					powers.append(value)
			except (AttributeError, TypeError, ValueError):
				continue
		return round(sum(powers), 1) if powers else None

	def update_settings(self, settings: dict[str, bool]) -> None:
		if not isinstance(settings, dict):
			raise ValueError("GPU settings must be an object")
		with self._lock:
			self._settings = {key: bool(settings.get(key, False)) for key in _SETTINGS}
			running = self._running
			current = dict(self._settings)
		if not running:
			return
		self._ensure_static_inventory(current)
		self._reconcile_provider(current)
		self._notify()

	def get_latest(self) -> dict:
		with self._lock:
			settings = dict(self._settings)
			visible = [gpu for gpu in self._gpus.values() if self._is_visible(gpu, settings)]
			hardware = {"gpus": [self._hardware_gpu(gpu, settings) for gpu in visible]}
			live = {"gpus": [self._live_gpu(gpu["gpu_id"], settings) for gpu in visible]}
			return {"hardware": hardware, "live": live}

	def _hardware_gpu(self, gpu: dict[str, Any], settings: dict[str, bool]) -> dict[str, Any]:
		entry = {
			"gpu_id": gpu["gpu_id"],
			"availability_state": gpu.get("availability_state")
			or ("not_enumerated" if gpu.get("_capability_only") else "available"),
		}
		for key in ("vendor", "graphics_type"):
			if gpu.get(key):
				entry[key] = gpu[key]
		if settings.get("Show GPU Name") and gpu.get("name"):
			entry["name"] = gpu["name"]
		if settings.get("Show VRAM Usage"):
			for key in ("vram_total_bytes", "shared_memory_total_bytes"):
				if gpu.get(key) is not None:
					entry[key] = int(gpu[key])
		if settings.get("Show Driver Version") and gpu.get("driver_version"):
			entry["driver_version"] = gpu["driver_version"]
		return copy.deepcopy(entry)

	def _live_gpu(self, gpu_id: str, settings: dict[str, bool]) -> dict[str, Any]:
		entry = {"gpu_id": gpu_id}
		values = self._live.get(gpu_id, {})
		for key, setting in (("usage_percent", "Show Current Usage"), ("temperature_c", "Show Temperature"), ("power_w", "Show Power Usage")):
			if settings.get(setting) and key in values:
				entry[key] = values[key]
		if settings.get("Show VRAM Usage"):
			for key in ("vram_used_bytes", "vram_usage_percent", "shared_memory_used_bytes", "shared_memory_usage_percent"):
				if key in values:
					entry[key] = values[key]
		if settings.get("Show Clock Speed") and values.get("clock"):
			entry["clock"] = copy.deepcopy(values["clock"])
		if settings.get("Show Fan Speed") and values.get("fans"):
			entry["fans"] = copy.deepcopy(values["fans"])
		return entry


	def get_metric_snapshot(self) -> dict[str, Any]:

		latest = self.get_latest()
		hardware_entries = latest.get("hardware", {}).get("gpus", []) or []
		live_entries = latest.get("live", {}).get("gpus", []) or []

		live_by_id = {
			entry.get("gpu_id"): entry
			for entry in live_entries
			if isinstance(entry, dict) and entry.get("gpu_id")
		}

		gpus = []
		for hardware in hardware_entries:
			if not isinstance(hardware, dict):
				continue

			gpu_id = hardware.get("gpu_id")
			live = live_by_id.get(gpu_id, {})
			clock = live.get("clock") if isinstance(live.get("clock"), dict) else {}

			fans = []
			for fan in live.get("fans", []) or []:
				if not isinstance(fan, dict):
					continue
				item = {}
				if fan.get("name") is not None:
					item["GPU_Fan_Name"] = fan.get("name")
				if fan.get("rpm") is not None:
					item["GPU_Fan_Speed"] = fan.get("rpm")
				if item:
					fans.append(item)

			item = {
				"GPU_ID": gpu_id,
				"GPU_State": hardware.get("availability_state"),
				"GPU_Vendor": hardware.get("vendor"),
				"GPU_Type": hardware.get("graphics_type"),
				"GPU_Name": hardware.get("name"),
				"GPU_Driver_Version": hardware.get("driver_version"),
				"GPU_VRAM_Total": hardware.get("vram_total_bytes"),
				"GPU_VRAM_Used": live.get("vram_used_bytes"),
				"GPU_VRAM_Utilisation": live.get("vram_usage_percent"),
				"GPU_Shared_Memory_Total": hardware.get("shared_memory_total_bytes"),
				"GPU_Shared_Memory_Used": live.get("shared_memory_used_bytes"),
				"GPU_Shared_Memory_Utilisation": live.get("shared_memory_usage_percent"),
				"GPU_Utilisation": live.get("usage_percent"),
				"GPU_Temperature": live.get("temperature_c"),
				"GPU_Core_Clock_Speed": clock.get("core_mhz"),
				"GPU_Memory_Clock_Speed": clock.get("memory_mhz"),
				"GPU_Power_Usage": live.get("power_w"),
				"GPU_Fans": fans,
			}
			gpus.append(item)

		return {"GPU_Individual_GPUs": gpus}

	def _print_gpu_module_block(self) -> None:
		metrics = self.get_metric_snapshot()
		gpus = metrics.get("GPU_Individual_GPUs", [])
		gpus = gpus if isinstance(gpus, list) else []

		def format_bytes(value: Any) -> str:
			if value is None:
				return "Unavailable"
			try:
				return f"{float(value) / (1024 ** 3):.1f} GiB"
			except (TypeError, ValueError):
				return str(value)

		def format_percent(value: Any) -> str:
			return "Unavailable" if value is None else f"{value}%"

		def format_temperature(value: Any) -> str:
			return "Unavailable" if value is None else f"{value} °C"

		def format_mhz(value: Any) -> str:
			return "Unavailable" if value is None else f"{value} MHz"

		def format_watts(value: Any) -> str:
			return "Unavailable" if value is None else f"{value} W"

		def format_rpm(value: Any) -> str:
			return "Unavailable" if value is None else f"{value} RPM"

		lines = ["-" * 60, "GPU_Module", f"GPU_Individual_GPUs: {len(gpus)}"]

		for index, gpu in enumerate(gpus, 1):
			lines.append(f"  [{index}]")

			if gpu.get("GPU_State") == "not_enumerated":
				for metric_id in (
					"GPU_ID",
					"GPU_State",
					"GPU_Vendor",
					"GPU_Type",
					"GPU_Name",
				):
					value = gpu.get(metric_id)
					if metric_id in ("GPU_Type", "GPU_State") and value is not None:
						display_value = str(value).replace("_", " ").title()
					else:
						display_value = value if value is not None else "Unavailable"
					lines.append(f"    {metric_id}: {display_value}")
				lines.append(
					"    Live_Telemetry: Unavailable - GPU is not currently exposed by Windows"
				)
				continue

			for metric_id, value in gpu.items():
				if metric_id == "GPU_Fans":
					fans = value if isinstance(value, list) else []
					lines.append(f"    {metric_id}: {len(fans)}")
					for fan_index, fan in enumerate(fans, 1):
						lines.append(f"      [{fan_index}]")
						for child_id, child_value in fan.items():
							if child_id == "GPU_Fan_Speed":
								display_value = format_rpm(child_value)
							else:
								display_value = child_value if child_value is not None else "Unavailable"
							lines.append(f"        {child_id}: {display_value}")
					continue

				if metric_id in (
					"GPU_VRAM_Total",
					"GPU_VRAM_Used",
					"GPU_Shared_Memory_Total",
					"GPU_Shared_Memory_Used",
				):
					display_value = format_bytes(value)
				elif metric_id in (
					"GPU_VRAM_Utilisation",
					"GPU_Shared_Memory_Utilisation",
					"GPU_Utilisation",
				):
					display_value = format_percent(value)
				elif metric_id == "GPU_Temperature":
					display_value = format_temperature(value)
				elif metric_id in ("GPU_Core_Clock_Speed", "GPU_Memory_Clock_Speed"):
					display_value = format_mhz(value)
				elif metric_id == "GPU_Power_Usage":
					display_value = format_watts(value)
				elif metric_id in ("GPU_Type", "GPU_State") and value is not None:
					display_value = str(value).replace("_", " ").title()
				else:
					display_value = value if value is not None else "Unavailable"

				lines.append(f"    {metric_id}: {display_value}")

		lines.append("-" * 60)
		print_raw("\n".join(lines))

	@staticmethod
	def _is_visible(gpu: dict[str, Any], settings: dict[str, bool]) -> bool:
		graphics_type = gpu.get("graphics_type") or "unknown"
		if graphics_type == "integrated":
			return settings.get("Show Integrated Graphics", False)
		if graphics_type == "dedicated":
			return settings.get("Show Dedicated Graphics", False)
		return settings.get("Show Integrated Graphics", False) or settings.get("Show Dedicated Graphics", False)

	def _ensure_static_inventory(self, settings: dict[str, bool]) -> None:
		if self._static_loaded:
			return

		cim = self._query_static_cim() if os.name == "nt" else []
		dxgi = self._query_static_dxgi() if os.name == "nt" else []
		static = self._merge_static_inventory(cim, dxgi)

		if (
			os.name == "nt"
			and settings.get("Show Integrated Graphics", False)
			and not any(gpu.get("graphics_type") == "integrated" for gpu in static)
		):
			capability_gpu = self._query_cpu_integrated_graphics_capability()
			if capability_gpu is not None:
				static.append(capability_gpu)

		with self._lock:
			self._gpus = {gpu["gpu_id"]: gpu for gpu in static}
			self._static_loaded = True



	def _query_cpu_integrated_graphics_capability(self) -> dict[str, Any] | None:









		if os.name != "nt":
			return None

		command = (
			"$ErrorActionPreference='Stop'; "
			"Get-CimInstance -ClassName Win32_Processor | "
			"Select-Object -First 1 Manufacturer,Name | "
			"ConvertTo-Json -Compress"
		)
		startupinfo = subprocess.STARTUPINFO()
		startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
		startupinfo.wShowWindow = subprocess.SW_HIDE

		try:
			result = subprocess.run(
				["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "-"],
				input=command,
				capture_output=True,
				text=True,
				timeout=CIM_TIMEOUT_SECONDS,
				startupinfo=startupinfo,
				check=True,
			)
			if not result.stdout.strip():
				return None
			row = json.loads(result.stdout)
			if not isinstance(row, dict):
				return None
		except Exception as error:
			self._warn_once(
				"cpu-graphics-capability",
				"CPU graphics capability discovery unavailable: %s",
				error,
			)
			return None

		manufacturer = self._clean_text(row.get("Manufacturer"))
		cpu_name = self._clean_text(row.get("Name"))
		capability = self._infer_integrated_graphics_capability(
			manufacturer,
			cpu_name,
		)
		if capability is None:
			return None

		gpu_name = capability["name"]
		vendor = capability["vendor"]
		identity = self._normalize_identity(
			f"CPU-GRAPHICS|{manufacturer or vendor}|{cpu_name}|{gpu_name}"
		)
		if not identity:
			return None

		return {
			"gpu_id": self._gpu_id(identity),
			"name": gpu_name,
			"vendor": vendor,
			"graphics_type": "integrated",
			"availability_state": "not_enumerated",
			"_capability_only": True,
			"_capability_source": "cpu_model",
			"_cpu_name": cpu_name,
			"_identity": identity,
			"_source": "cpu-capability",
		}

	@classmethod
	def _infer_integrated_graphics_capability(
		cls,
		manufacturer: str | None,
		cpu_name: str | None,
	) -> dict[str, str] | None:





		if not cpu_name:
			return None

		manufacturer_text = str(manufacturer or "").upper()
		name = " ".join(str(cpu_name).split())
		name_upper = name.upper()

		if "INTEL" not in manufacturer_text and "INTEL" not in name_upper:
			return None



		match = re.search(
			r"\bI([3579])-((?:10)\d{3})([A-Z]{0,2})\b",
			name_upper,
		)
		if match:
			suffix = match.group(3)
			if "F" in suffix:
				return None



			if suffix not in {"", "K", "T", "E", "TE", "S"}:
				return None

			return {
				"vendor": "Intel",
				"name": "Intel UHD Graphics 630",
			}

		return None


	def _query_static_dxgi(self) -> list[dict[str, Any]]:






		if os.name != "nt":
			return []

		try:
			from ctypes import wintypes

			class GUID(ctypes.Structure):
				_fields_ = (
					("Data1", wintypes.DWORD),
					("Data2", wintypes.WORD),
					("Data3", wintypes.WORD),
					("Data4", ctypes.c_ubyte * 8),
				)

			class LUID(ctypes.Structure):
				_fields_ = (
					("LowPart", wintypes.DWORD),
					("HighPart", wintypes.LONG),
				)

			class DXGI_ADAPTER_DESC1(ctypes.Structure):
				_fields_ = (
					("Description", ctypes.c_wchar * 128),
					("VendorId", wintypes.UINT),
					("DeviceId", wintypes.UINT),
					("SubSysId", wintypes.UINT),
					("Revision", wintypes.UINT),
					("DedicatedVideoMemory", ctypes.c_size_t),
					("DedicatedSystemMemory", ctypes.c_size_t),
					("SharedSystemMemory", ctypes.c_size_t),
					("AdapterLuid", LUID),
					("Flags", wintypes.UINT),
				)

			def make_guid(value: str) -> GUID:
				raw = uuid.UUID(value).bytes_le
				return GUID.from_buffer_copy(raw)

			def get_vtable(pointer: ctypes.c_void_p):
				return ctypes.cast(
					pointer,
					ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
				).contents

			def release(pointer: ctypes.c_void_p) -> None:
				if not pointer:
					return
				vtable = get_vtable(pointer)
				func = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
				func(pointer)

			dxgi = ctypes.WinDLL("dxgi")
			create_factory = dxgi.CreateDXGIFactory1
			create_factory.argtypes = (
				ctypes.POINTER(GUID),
				ctypes.POINTER(ctypes.c_void_p),
			)
			create_factory.restype = ctypes.c_long

			IID_IDXGIFactory1 = make_guid("770aae78-f26f-4dba-a829-253c83d1b387")
			factory = ctypes.c_void_p()
			hr = create_factory(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory))
			if hr < 0 or not factory:
				return []

			results: list[dict[str, Any]] = []
			try:
				factory_vtable = get_vtable(factory)
				enum_adapters1 = ctypes.WINFUNCTYPE(
					ctypes.c_long,
					ctypes.c_void_p,
					wintypes.UINT,
					ctypes.POINTER(ctypes.c_void_p),
				)(factory_vtable[12])

				index = 0
				while True:
					adapter = ctypes.c_void_p()
					hr = enum_adapters1(factory, index, ctypes.byref(adapter))
					if (int(hr) & 0xFFFFFFFF) == 0x887A0002:
						break
					if hr < 0 or not adapter:
						break

					try:
						adapter_vtable = get_vtable(adapter)
						get_desc1 = ctypes.WINFUNCTYPE(
							ctypes.c_long,
							ctypes.c_void_p,
							ctypes.POINTER(DXGI_ADAPTER_DESC1),
						)(adapter_vtable[10])

						desc = DXGI_ADAPTER_DESC1()
						if get_desc1(adapter, ctypes.byref(desc)) >= 0:

							if int(desc.Flags) & 0x2:
								index += 1
								continue

							name = self._clean_text(desc.Description)
							vendor_id = int(desc.VendorId)
							device_id = int(desc.DeviceId)
							vendor = self._vendor_from_pci_vendor_id(vendor_id)
							dedicated_video = int(desc.DedicatedVideoMemory)
							shared_system = int(desc.SharedSystemMemory)
							graphics_type = self._classify_graphics_type(
								vendor,
								name,
								dedicated_video,
							)
							luid_key = self._format_luid_key(
								int(desc.AdapterLuid.HighPart),
								int(desc.AdapterLuid.LowPart),
							)
							identity = self._normalize_identity(
								f"DXGI|VEN_{vendor_id:04X}|DEV_{device_id:04X}|"
								f"SUBSYS_{int(desc.SubSysId):08X}|{name or index}"
							)
							if not identity:
								index += 1
								continue

							results.append({
								"gpu_id": self._gpu_id(identity),
								"name": name,
								"vendor": vendor,
								"graphics_type": graphics_type,
								"vram_total_bytes": dedicated_video if dedicated_video > 0 else None,
								"shared_memory_total_bytes": shared_system if shared_system > 0 else None,
								"_dxgi_vendor_id": vendor_id,
								"_dxgi_device_id": device_id,
								"_dxgi_subsys_id": int(desc.SubSysId),
								"_dxgi_luid_key": luid_key,
								"_dxgi_index": index,
								"_identity": identity,
								"_source": "dxgi",
							})
					finally:
						release(adapter)

					index += 1
			finally:
				release(factory)

			return [
				{key: value for key, value in item.items() if value is not None}
				for item in results
			]
		except Exception as error:
			self._warn_once("dxgi", "GPU DXGI inventory unavailable: %s", error)
			return []

	def _merge_static_inventory(
		self,
		cim_items: list[dict[str, Any]],
		dxgi_items: list[dict[str, Any]],
	) -> list[dict[str, Any]]:
		if not dxgi_items:
			return cim_items
		if not cim_items:
			return dxgi_items

		remaining = list(dxgi_items)
		merged: list[dict[str, Any]] = []

		for cim_gpu in cim_items:
			match = self._match_static_dxgi(cim_gpu, remaining)
			if match is None:
				merged.append(cim_gpu)
				continue

			remaining.remove(match)
			item = dict(cim_gpu)



			for key in (
				"vram_total_bytes",
				"shared_memory_total_bytes",
				"_dxgi_vendor_id",
				"_dxgi_device_id",
				"_dxgi_subsys_id",
				"_dxgi_luid_key",
				"_dxgi_index",
			):
				if match.get(key) is not None:
					item[key] = match[key]

			if item.get("graphics_type") in (None, "unknown"):
				item["graphics_type"] = match.get("graphics_type") or "unknown"
			if not item.get("vendor") and match.get("vendor"):
				item["vendor"] = match["vendor"]
			if not item.get("name") and match.get("name"):
				item["name"] = match["name"]

			merged.append(item)

		merged.extend(remaining)
		return merged

	def _match_static_dxgi(
		self,
		cim_gpu: dict[str, Any],
		candidates: list[dict[str, Any]],
	) -> dict[str, Any] | None:
		pnp_vendor, pnp_device = self._pci_ids_from_pnp(cim_gpu.get("_pnp_id"))
		if pnp_vendor is not None and pnp_device is not None:
			matches = [
				item for item in candidates
				if item.get("_dxgi_vendor_id") == pnp_vendor
				and item.get("_dxgi_device_id") == pnp_device
			]
			if len(matches) == 1:
				return matches[0]

		vendor = cim_gpu.get("vendor")
		name = self._normalize_name(cim_gpu.get("name"))
		if vendor and name:
			matches = [
				item for item in candidates
				if item.get("vendor") == vendor
				and self._names_match(name, self._normalize_name(item.get("name")))
			]
			if len(matches) == 1:
				return matches[0]

		return None

	@staticmethod
	def _pci_ids_from_pnp(value: Any) -> tuple[int | None, int | None]:
		if value is None:
			return None, None
		text = str(value).upper()
		vendor_match = re.search(r"VEN_([0-9A-F]{4})", text)
		device_match = re.search(r"DEV_([0-9A-F]{4})", text)
		try:
			vendor = int(vendor_match.group(1), 16) if vendor_match else None
			device = int(device_match.group(1), 16) if device_match else None
			return vendor, device
		except ValueError:
			return None, None

	@staticmethod
	def _vendor_from_pci_vendor_id(vendor_id: int) -> str | None:
		return {
			0x10DE: "NVIDIA",
			0x1002: "AMD",
			0x1022: "AMD",
			0x8086: "Intel",
		}.get(int(vendor_id))

	@staticmethod
	def _classify_graphics_type(
		vendor: str | None,
		name: str | None,
		dedicated_video_bytes: int | None,
	) -> str:
		name_lower = str(name or "").lower()
		dedicated = int(dedicated_video_bytes or 0)

		if vendor == "NVIDIA":
			return "dedicated"

		if vendor == "Intel":
			if "arc" in name_lower:
				return "dedicated"
			return "integrated"

		if vendor == "AMD":
			if (
				"radeon graphics" in name_lower
				or "radeon(tm) graphics" in name_lower
			) and dedicated <= 1024 ** 3:
				return "integrated"
			if dedicated > 0:
				return "dedicated"

		return "unknown"

	@staticmethod
	def _format_luid_key(high_part: int, low_part: int) -> str:
		return (
			f"luid_0x{(int(high_part) & 0xFFFFFFFF):08x}_"
			f"0x{(int(low_part) & 0xFFFFFFFF):08x}"
		)


	def _query_static_cim(self) -> list[dict[str, Any]]:
		command = (
			"$ErrorActionPreference='Stop'; "
			"Get-CimInstance -ClassName Win32_VideoController | "
			"Select-Object Name,AdapterCompatibility,PNPDeviceID,DriverVersion,VideoProcessor,DeviceID,Status | "
			"ConvertTo-Json -Compress -Depth 3"
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
			rows = parsed if isinstance(parsed, list) else [parsed]
			return [gpu for row in rows if isinstance(row, dict) for gpu in [self._normalize_cim_gpu(row)] if gpu is not None]
		except Exception as error:
			self._warn_once("cim", "GPU CIM inventory unavailable: %s", error)
			return []

	def _normalize_cim_gpu(self, row: dict[str, Any]) -> dict[str, Any] | None:
		name = self._clean_text(row.get("Name")) or self._clean_text(row.get("VideoProcessor"))
		pnp_id = self._normalize_identity(row.get("PNPDeviceID"))
		device_id = self._normalize_identity(row.get("DeviceID"))
		identity = pnp_id or device_id or self._normalize_identity(name)
		if not identity:
			return None
		vendor = self._normalize_vendor(row.get("AdapterCompatibility"), pnp_id, name)
		gpu = {
			"gpu_id": self._gpu_id(identity),
			"name": name,
			"vendor": vendor,
			"graphics_type": self._classify_graphics_type(vendor, name, None),
			"driver_version": self._clean_text(row.get("DriverVersion")),
			"_pnp_id": pnp_id,
			"_device_id": device_id,
			"_identity": identity,
			"_source": "cim",
		}
		return {key: value for key, value in gpu.items() if value is not None}

	def _reconcile_provider(self, settings: dict[str, bool]) -> None:
		needs_lhm = self._needs_lhm(settings)
		with self._lock:
			running = self._running
			provider_active = self._lhm_computer is not None
			thread = self._thread
		if not running:
			return
		if not needs_lhm:
			with self._lock:
				stop_event = self._stop_event
				self._thread = None
				if stop_event is not None:
					stop_event.set()
			if thread is not None and thread is not threading.current_thread():
				thread.join(timeout=SAMPLE_INTERVAL_SECONDS + 2)
			with self._lock:
				self._close_lhm_locked()
				self._live = {}
				self._stop_event = None
			return
		if not provider_active:
			with self._lock:
				self._open_lhm_locked()
		with self._lock:
			if self._lhm_computer is None or self._thread is not None or not self._running:
				return
			stop_event = self._stop_event if self._stop_event is not None and not self._stop_event.is_set() else threading.Event()
			self._stop_event = stop_event
			self._thread = threading.Thread(target=self._sample_loop, args=(stop_event,), name="StatMonitorGPU", daemon=True)
			self._thread.start()

	def _needs_lhm(self, settings: dict[str, bool]) -> bool:
		with self._lock:
			return any(settings.get(key, False) for key in _LIVE_SETTINGS) or bool(self._internal_power_consumers)

	def _open_lhm_locked(self) -> None:
		global LHM_TYPES
		if self._lhm_computer is not None:
			return
		try:
			with LHM_TYPES_LOCK:
				if LHM_TYPES is None:
					pythonnet = importlib.import_module("pythonnet")
					dependency = self.project_root / "Dependencies" / "StatMonitor" / "LibreHardwareMonitor.NET.10"
					runtime_config = dependency / "LibreHardwareMonitor.runtimeconfig.json"
					if pythonnet.get_runtime_info() is None:
						if runtime_config.exists():
							pythonnet.load("coreclr", runtime_config=str(runtime_config))
						else:
							pythonnet.load("coreclr")
					clr = importlib.import_module("clr")
					clr.AddReference(str(dependency / "LibreHardwareMonitorLib.dll"))
					hardware_module = importlib.import_module("LibreHardwareMonitor.Hardware")
					Computer = getattr(hardware_module, "Computer")
					HardwareType = getattr(hardware_module, "HardwareType")
					LHM_TYPES = (Computer, HardwareType)
			Computer, _ = LHM_TYPES
			computer = Computer()
			computer.IsGpuEnabled = True
			computer.IsCpuEnabled = self._needs_cpu_for_intel_lhm(self._settings)
			computer.IsMotherboardEnabled = False
			computer.IsMemoryEnabled = False
			computer.IsStorageEnabled = False
			computer.IsNetworkEnabled = False
			computer.IsControllerEnabled = False
			computer.IsPowerMonitorEnabled = False
			if hasattr(computer, "IsBatteryEnabled"):
				computer.IsBatteryEnabled = False
			computer.Open()
			self._lhm_computer = computer
			self._lhm_hardware = [hardware for hardware in self._iter_all_hardware(list(computer.Hardware)) if self._is_gpu_hardware(hardware)]
			self._merge_lhm_inventory_locked(self._lhm_hardware)
			if not self._lhm_hardware:
				self._warn_once("lhm-gpu", "LibreHardwareMonitor opened without GPU hardware")
		except Exception as error:
			self._warn_once("lhm", "LibreHardwareMonitor GPU provider unavailable: %s", error)
			self._close_lhm_locked()

	def _needs_cpu_for_intel_lhm(self, settings: dict[str, bool]) -> bool:
		if settings.get("Show Integrated Graphics", False):
			return True
		with self._lock:
			gpus = list(self._gpus.values())
		return any(gpu.get("vendor") == "Intel" for gpu in gpus)

	def _merge_lhm_inventory_locked(self, hardware_items: list[Any]) -> None:
		available = set(self._gpus)
		for hardware in hardware_items:
			lhm_gpu = self._normalize_lhm_gpu(hardware)
			if lhm_gpu is None:
				continue
			match_id, method = self._match_lhm_gpu(lhm_gpu, available)
			if match_id is None:
				match_id = lhm_gpu["gpu_id"]
				method = "lhm-fallback"
				self._gpus.setdefault(match_id, {})
			gpu = self._gpus[match_id]
			gpu.setdefault("gpu_id", match_id)
			for key in ("name", "vendor", "graphics_type"):
				if lhm_gpu.get(key) and (key != "graphics_type" or gpu.get(key) in (None, "unknown")):
					gpu[key] = lhm_gpu[key]
			gpu["_lhm_key"] = lhm_gpu["_lhm_key"]
			gpu["_lhm_name"] = lhm_gpu.get("name")
			gpu["_lhm_type"] = lhm_gpu.get("_lhm_type")
			gpu["_lhm_provider_type"] = lhm_gpu.get("_lhm_provider_type")
			gpu["_match_method"] = method
			gpu["availability_state"] = "available"
			gpu["_capability_only"] = False
			available.discard(match_id)

	def _normalize_lhm_gpu(self, hardware: Any) -> dict[str, Any] | None:
		name = self._clean_text(getattr(hardware, "Name", None))
		hardware_type = str(getattr(hardware, "HardwareType", ""))
		provider_type = self._provider_type(hardware)
		device_id = self._first_attr(hardware, ("DeviceId", "Identifier"))
		identity = self._normalize_identity(device_id) or self._normalize_identity(f"{hardware_type}|{name}")
		if not identity:
			return None
		vendor = self._vendor_from_lhm(hardware_type, name)
		return {
			"gpu_id": self._gpu_id(identity),
			"name": name,
			"vendor": vendor,
			"graphics_type": self._graphics_type_from_lhm(hardware_type, provider_type),
			"_identity": identity,
			"_lhm_key": identity,
			"_lhm_type": hardware_type,
			"_lhm_provider_type": provider_type,
		}

	def _match_lhm_gpu(self, lhm_gpu: dict[str, Any], available: set[str]) -> tuple[str | None, str | None]:
		identity = lhm_gpu.get("_identity")
		for gpu_id in list(available):
			gpu = self._gpus[gpu_id]
			if identity and identity in {gpu.get("_pnp_id"), gpu.get("_device_id"), gpu.get("_identity")}:
				return gpu_id, "identity"
		vendor = lhm_gpu.get("vendor")
		name = self._normalize_name(lhm_gpu.get("name"))
		if vendor and name:
			for gpu_id in list(available):
				gpu = self._gpus[gpu_id]
				if gpu.get("vendor") == vendor and self._names_match(name, self._normalize_name(gpu.get("name"))):
					return gpu_id, "name-vendor"
		if vendor:
			candidates = [gpu_id for gpu_id in available if self._gpus[gpu_id].get("vendor") == vendor]
			if len(candidates) == 1:
				return candidates[0], "vendor-order"
		return None, None

	def _sample_loop(self, stop_event: threading.Event) -> None:
		try:
			while not stop_event.is_set():
				with self._lock:
					if not self._running or self._stop_event is not stop_event or self._lhm_computer is None:
						return
					settings = dict(self._settings)
				try:
					self._collect_lhm_sample(settings)
				except Exception as error:
					self._warn_once("sample", "GPU sample failed: %s", error)
				if stop_event.wait(SAMPLE_INTERVAL_SECONDS):
					return
		finally:
			with self._lock:
				if self._thread is threading.current_thread():
					self._thread = None

	def _collect_lhm_sample(self, settings: dict[str, bool]) -> None:
		with self._lock:
			hardware_items = list(self._lhm_hardware)
			by_lhm_key = {gpu.get("_lhm_key"): gpu for gpu in self._gpus.values() if gpu.get("_lhm_key")}
		live: dict[str, dict[str, Any]] = {}
		updates: dict[str, dict[str, int]] = {}
		for hardware in hardware_items:
			try:
				hardware.Update()
			except Exception as error:
				self._warn_once(f"update-{self._safe_hardware_name(hardware)}", "GPU hardware update failed for %s: %s", self._safe_hardware_name(hardware), error)
				continue
			lhm_key = self._normalize_identity(self._first_attr(hardware, ("DeviceId", "Identifier"))) or self._normalize_identity(f"{getattr(hardware, 'HardwareType', '')}|{getattr(hardware, 'Name', '')}")
			gpu = by_lhm_key.get(lhm_key)
			if not gpu:
				continue
			sensors = [sensor for item in self._iter_gpu_hardware(hardware) for sensor in self._iter_sensors(item)]
			data, hardware_update = self._normalize_sensors(sensors, settings)
			if data:
				live[gpu["gpu_id"]] = data
			if hardware_update:
				updates[gpu["gpu_id"]] = hardware_update

		if settings.get("Show VRAM Usage"):
			windows_memory = self._collect_windows_adapter_memory_usage()
			with self._lock:
				gpu_inventory = [dict(gpu) for gpu in self._gpus.values()]
			for gpu in gpu_inventory:
				luid_key = gpu.get("_dxgi_luid_key")
				gpu_id = gpu.get("gpu_id")
				if not luid_key or not gpu_id:
					continue
				memory = windows_memory.get(str(luid_key).lower())
				if not memory:
					continue

				entry = live.setdefault(gpu_id, {})
				if entry.get("vram_used_bytes") is None and memory.get("vram_used_bytes") is not None:
					entry["vram_used_bytes"] = int(memory["vram_used_bytes"])

				if memory.get("shared_memory_used_bytes") is not None:
					shared_used = int(memory["shared_memory_used_bytes"])
					entry["shared_memory_used_bytes"] = shared_used
					shared_total = gpu.get("shared_memory_total_bytes")
					if shared_total:
						entry["shared_memory_usage_percent"] = self._number(
							self._clamp(shared_used / int(shared_total) * 100.0, 0.0, 100.0)
						)

		with self._lock:
			if not self._running:
				return
			self._live = live
			for gpu_id, update in updates.items():
				if gpu_id in self._gpus:
					self._gpus[gpu_id].update(update)
			first = bool(live) and not self._logged_first_telemetry
			if first:
				self._logged_first_telemetry = True
		if first:
			self._print_gpu_module_block()
		if live or updates:
			self._notify()


	def _collect_windows_adapter_memory_usage(self) -> dict[str, dict[str, int]]:






		if os.name != "nt":
			return {}

		try:
			from ctypes import wintypes

			class PDH_VALUE_UNION(ctypes.Union):
				_fields_ = (
					("longValue", wintypes.LONG),
					("doubleValue", ctypes.c_double),
					("largeValue", ctypes.c_longlong),
					("AnsiStringValue", ctypes.c_char_p),
					("WideStringValue", ctypes.c_wchar_p),
				)

			class PDH_FMT_COUNTERVALUE(ctypes.Structure):
				_fields_ = (
					("CStatus", wintypes.DWORD),
					("value", PDH_VALUE_UNION),
				)

			class PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
				_fields_ = (
					("szName", ctypes.c_wchar_p),
					("FmtValue", PDH_FMT_COUNTERVALUE),
				)

			pdh = ctypes.WinDLL("pdh")
			query = ctypes.c_void_p()

			pdh.PdhOpenQueryW.argtypes = (
				ctypes.c_wchar_p,
				ctypes.c_size_t,
				ctypes.POINTER(ctypes.c_void_p),
			)
			pdh.PdhOpenQueryW.restype = wintypes.DWORD
			pdh.PdhCloseQuery.argtypes = (ctypes.c_void_p,)
			pdh.PdhCloseQuery.restype = wintypes.DWORD
			pdh.PdhCollectQueryData.argtypes = (ctypes.c_void_p,)
			pdh.PdhCollectQueryData.restype = wintypes.DWORD
			pdh.PdhAddEnglishCounterW.argtypes = (
				ctypes.c_void_p,
				ctypes.c_wchar_p,
				ctypes.c_size_t,
				ctypes.POINTER(ctypes.c_void_p),
			)
			pdh.PdhAddEnglishCounterW.restype = wintypes.DWORD
			pdh.PdhGetFormattedCounterArrayW.argtypes = (
				ctypes.c_void_p,
				wintypes.DWORD,
				ctypes.POINTER(wintypes.DWORD),
				ctypes.POINTER(wintypes.DWORD),
				ctypes.c_void_p,
			)
			pdh.PdhGetFormattedCounterArrayW.restype = wintypes.DWORD

			if pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)) != 0 or not query:
				return {}

			counters: dict[str, ctypes.c_void_p] = {}
			try:
				for key, path in (
					("shared_memory_used_bytes", r"\GPU Adapter Memory(*)\Shared Usage"),
					("vram_used_bytes", r"\GPU Adapter Memory(*)\Dedicated Usage"),
				):
					counter = ctypes.c_void_p()
					status = pdh.PdhAddEnglishCounterW(
						query,
						path,
						0,
						ctypes.byref(counter),
					)
					if status == 0 and counter:
						counters[key] = counter

				if not counters:
					return {}

				if pdh.PdhCollectQueryData(query) != 0:
					return {}

				result: dict[str, dict[str, int]] = {}
				for metric_key, counter in counters.items():
					for instance_name, value in self._read_pdh_counter_array(
						pdh,
						counter,
						PDH_FMT_COUNTERVALUE_ITEM_W,
					):
						luid_key = self._luid_key_from_counter_instance(instance_name)
						if luid_key is None or value < 0:
							continue
						entry = result.setdefault(luid_key, {})
						entry[metric_key] = entry.get(metric_key, 0) + int(value)

				return result
			finally:
				pdh.PdhCloseQuery(query)
		except Exception as error:
			self._warn_once("pdh-gpu-memory", "Windows GPU memory counters unavailable: %s", error)
			return {}

	@staticmethod
	def _read_pdh_counter_array(
		pdh: Any,
		counter: ctypes.c_void_p,
		item_type: Any,
	) -> list[tuple[str, int]]:
		PDH_FMT_LARGE = 0x00000400
		PDH_MORE_DATA = 0x800007D2

		buffer_size = ctypes.c_ulong(0)
		item_count = ctypes.c_ulong(0)
		status = pdh.PdhGetFormattedCounterArrayW(
			counter,
			PDH_FMT_LARGE,
			ctypes.byref(buffer_size),
			ctypes.byref(item_count),
			None,
		)
		if status not in (PDH_MORE_DATA, 0) or buffer_size.value <= 0:
			return []

		buffer = ctypes.create_string_buffer(buffer_size.value)
		status = pdh.PdhGetFormattedCounterArrayW(
			counter,
			PDH_FMT_LARGE,
			ctypes.byref(buffer_size),
			ctypes.byref(item_count),
			buffer,
		)
		if status != 0:
			return []

		items = ctypes.cast(buffer, ctypes.POINTER(item_type))
		result: list[tuple[str, int]] = []
		for index in range(int(item_count.value)):
			item = items[index]

			if int(item.FmtValue.CStatus) not in (0, 1):
				continue
			name = str(item.szName or "")
			value = int(item.FmtValue.value.largeValue)
			result.append((name, value))
		return result

	@staticmethod
	def _luid_key_from_counter_instance(instance_name: str) -> str | None:
		match = re.search(
			r"(luid_0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)(?:_phys_\d+)?",
			str(instance_name),
		)
		return match.group(1).lower() if match else None


	def _normalize_sensors(self, sensors: list[Any], settings: dict[str, bool]) -> tuple[dict[str, Any], dict[str, int]]:
		values = [(str(getattr(sensor, "SensorType", "")), str(getattr(sensor, "Name", "")), self._sensor_value(sensor)) for sensor in sensors]
		values = [(sensor_type, name, value) for sensor_type, name, value in values if value is not None]
		live: dict[str, Any] = {}
		hardware: dict[str, int] = {}
		if settings.get("Show Current Usage"):
			usage = self._preferred_value(values, "Load", self._gpu_load_score)
			if usage is not None:
				live["usage_percent"] = self._number(self._clamp(usage, 0.0, 100.0))
		if settings.get("Show VRAM Usage"):
			memory_live, memory_hardware = self._memory_values(values)
			live.update(memory_live)
			hardware.update(memory_hardware)
		if settings.get("Show Temperature"):
			temperature = self._preferred_value(values, "Temperature", self._temperature_score)
			if temperature is not None and -100 < temperature < 200:
				live["temperature_c"] = self._number(temperature)
		if settings.get("Show Clock Speed"):
			clock = {}
			core = self._preferred_value(values, "Clock", self._core_clock_score)
			memory = self._preferred_value(values, "Clock", self._memory_clock_score)
			if core is not None and core >= 0:
				clock["core_mhz"] = self._number(core)
			if memory is not None and memory >= 0:
				clock["memory_mhz"] = self._number(memory)
			if clock:
				live["clock"] = clock
		if settings.get("Show Power Usage") or self._internal_power_consumers:
			power = self._preferred_value(values, "Power", self._power_score)
			if power is not None and power >= 0:
				live["power_w"] = self._number(power)
		if settings.get("Show Fan Speed"):
			fans = []
			for sensor_type, name, value in values:
				if sensor_type == "Fan" and value >= 0:
					fans.append({"name": self._clean_text(name) or "GPU Fan", "rpm": int(round(value))})
			if fans:
				live["fans"] = fans
		return live, hardware

	def _memory_values(self, values: list[tuple[str, str, float]]) -> tuple[dict[str, Any], dict[str, int]]:
		live: dict[str, Any] = {}
		hardware: dict[str, int] = {}
		memory = [(name, value) for sensor_type, name, value in values if sensor_type == "SmallData"]
		dedicated_total = self._named_value(memory, ("gpu memory total", "memory total"), exclude=("shared", "d3d"))
		dedicated_used = self._named_value(memory, ("gpu memory used", "memory used"), exclude=("shared", "d3d"))
		shared_total = self._named_value(memory, ("shared memory total", "d3d shared memory total"))
		shared_used = self._named_value(memory, ("shared memory used", "d3d shared memory used"))
		if dedicated_total is not None and dedicated_total > 0:
			total_bytes = self._mib_to_bytes(dedicated_total)
			hardware["vram_total_bytes"] = total_bytes
			if dedicated_used is not None and dedicated_used >= 0:
				used_bytes = min(self._mib_to_bytes(dedicated_used), total_bytes)
				live["vram_used_bytes"] = used_bytes
				live["vram_usage_percent"] = self._number(self._clamp(used_bytes / total_bytes * 100.0, 0.0, 100.0))
		elif dedicated_used is not None and dedicated_used >= 0:
			live["vram_used_bytes"] = self._mib_to_bytes(dedicated_used)
		if "vram_usage_percent" not in live:
			memory_load = self._preferred_value(values, "Load", self._memory_load_score)
			if memory_load is not None:
				live["vram_usage_percent"] = self._number(self._clamp(memory_load, 0.0, 100.0))
		if shared_total is not None and shared_total > 0:
			total_bytes = self._mib_to_bytes(shared_total)
			hardware["shared_memory_total_bytes"] = total_bytes
			if shared_used is not None and shared_used >= 0:
				used_bytes = min(self._mib_to_bytes(shared_used), total_bytes)
				live["shared_memory_used_bytes"] = used_bytes
				live["shared_memory_usage_percent"] = self._number(self._clamp(used_bytes / total_bytes * 100.0, 0.0, 100.0))
		return live, hardware

	@staticmethod
	def _named_value(values: list[tuple[str, float]], include: tuple[str, ...], exclude: tuple[str, ...] = ()) -> float | None:
		matches = []
		for name, value in values:
			name_lower = name.lower()
			if any(token in name_lower for token in include) and not any(token in name_lower for token in exclude):
				matches.append((len(name_lower), value))
		return min(matches, key=lambda item: item[0])[1] if matches else None

	@staticmethod
	def _preferred_value(values: list[tuple[str, str, float]], sensor_type: str, score: Callable[[str], int | None]) -> float | None:
		matches = []
		for current_type, name, value in values:
			if current_type != sensor_type:
				continue
			priority = score(name)
			if priority is not None:
				matches.append((priority, name, value))
		return min(matches, key=lambda item: (item[0], item[1]))[2] if matches else None

	@staticmethod
	def _gpu_load_score(name: str) -> int | None:
		name_lower = name.lower()
		if any(token in name_lower for token in ("memory", "video", "decode", "encode", "copy", "bus", "shared")):
			return None
		if "gpu core" in name_lower:
			return 0
		if "gpu total" in name_lower:
			return 1
		if "d3d 3d" in name_lower:
			return 2
		if "render" in name_lower or "compute" in name_lower:
			return 3
		return None

	@staticmethod
	def _memory_load_score(name: str) -> int | None:
		name_lower = name.lower()
		if "memory" in name_lower and "load" not in name_lower:
			return 0
		if "gpu memory" in name_lower:
			return 1
		return None

	@staticmethod
	def _temperature_score(name: str) -> int | None:
		name_lower = name.lower()
		if "gpu core" in name_lower:
			return 0
		if "gpu package" in name_lower:
			return 1
		if "gpu temperature" in name_lower:
			return 2
		if "hot spot" in name_lower or "hotspot" in name_lower:
			return 3
		return None

	@staticmethod
	def _core_clock_score(name: str) -> int | None:
		name_lower = name.lower()
		if "gpu core" in name_lower:
			return 0
		return None

	@staticmethod
	def _memory_clock_score(name: str) -> int | None:
		name_lower = name.lower()
		if "gpu memory" in name_lower or name_lower.strip() == "memory":
			return 0
		return None

	@staticmethod
	def _power_score(name: str) -> int | None:
		name_lower = name.lower()
		if any(token in name_lower for token in ("pcie", "slot", "8-pin", "6-pin", "12vhpwr", "rail")):
			return None
		if "gpu package" in name_lower:
			return 0
		if "gpu total" in name_lower:
			return 1
		if name_lower in {"gpu power", "power"} or "board power" in name_lower:
			return 2
		return None

	def _log_first_telemetry(self, static_only: bool = False) -> None:
		with self._lock:
			if static_only:
				if self._logged_static_telemetry:
					return
				self._logged_static_telemetry = True
			elif self._logged_first_telemetry:
				return
			else:
				self._logged_first_telemetry = True
		self._print_gpu_module_block()

	def _notify(self) -> None:
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				LOGGER.exception("StatMonitor GPU listener failed")

	def _close_lhm_locked(self) -> None:
		computer = self._lhm_computer
		self._lhm_computer = None
		self._lhm_hardware = []
		if computer is not None:
			try:
				computer.Close()
			except Exception as error:
				self._warn_once("lhm-close", "LibreHardwareMonitor GPU provider close failed: %s", error)

	@staticmethod
	def _iter_sensors(hardware: Any) -> list[Any]:
		try:
			return list(hardware.Sensors)
		except Exception:
			return []

	def _iter_gpu_hardware(self, hardware: Any):
		yield hardware
		try:
			children = list(hardware.SubHardware)
		except Exception:
			children = []
		for child in children:
			if self._is_gpu_hardware(child):
				yield child

	def _iter_all_hardware(self, hardware_items: list[Any]):
		for hardware in hardware_items:
			yield hardware
			try:
				children = list(hardware.SubHardware)
			except Exception:
				children = []
			yield from self._iter_all_hardware(children)

	@staticmethod
	def _is_gpu_hardware(hardware: Any) -> bool:
		return str(getattr(hardware, "HardwareType", "")) in LHM_GPU_TYPES

	@staticmethod
	def _sensor_value(sensor: Any) -> float | None:
		try:
			value = float(sensor.Value)
			return value if math.isfinite(value) else None
		except (TypeError, ValueError, AttributeError):
			return None

	@staticmethod
	def _first_attr(obj: Any, names: tuple[str, ...]) -> str | None:
		for name in names:
			try:
				value = getattr(obj, name)
				if value is not None:
					return str(value)
			except Exception:
				continue
		return None

	@staticmethod
	def _safe_hardware_name(hardware: Any) -> str:
		try:
			return str(getattr(hardware, "Name", "GPU"))
		except Exception:
			return "GPU"

	@staticmethod
	def _provider_type(hardware: Any) -> str:
		try:
			return str(hardware.GetType().FullName)
		except Exception:
			return type(hardware).__name__

	@staticmethod
	def _normalize_identity(value: Any) -> str | None:
		if value is None:
			return None
		text = re.sub(r"\s+", " ", str(value).strip().upper())
		return text or None

	@staticmethod
	def _normalize_name(value: Any) -> str | None:
		if value is None:
			return None
		text = re.sub(r"[^A-Z0-9]+", " ", str(value).upper()).strip()
		return text or None

	@classmethod
	def _names_match(cls, left: str | None, right: str | None) -> bool:
		if not left or not right:
			return False
		return left == right or left in right or right in left

	@staticmethod
	def _clean_text(value: Any) -> str | None:
		if value is None:
			return None
		text = " ".join(str(value).split())
		return text or None

	@staticmethod
	def _gpu_id(identity: str) -> str:
		return "gpu-" + hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()[:24]

	@staticmethod
	def _normalize_vendor(*values: Any) -> str | None:
		text = " ".join(str(value or "") for value in values).upper()
		if "VEN_10DE" in text or "NVIDIA" in text:
			return "NVIDIA"
		if "VEN_1002" in text or "VEN_1022" in text or "ADVANCED MICRO DEVICES" in text or "AMD" in text or "ATI" in text:
			return "AMD"
		if "VEN_8086" in text or "INTEL" in text:
			return "Intel"
		return None

	@classmethod
	def _vendor_from_lhm(cls, hardware_type: str, name: str | None) -> str | None:
		if hardware_type == "GpuNvidia":
			return "NVIDIA"
		if hardware_type == "GpuAmd":
			return "AMD"
		if hardware_type == "GpuIntel":
			return "Intel"
		return cls._normalize_vendor(name)

	@staticmethod
	def _graphics_type_from_lhm(hardware_type: str, provider_type: str) -> str:
		provider_lower = provider_type.lower()
		if hardware_type == "GpuNvidia":
			return "dedicated"
		if hardware_type == "GpuIntel":
			if "discrete" in provider_lower:
				return "dedicated"
			if "integrated" in provider_lower or "igpu" in provider_lower:
				return "integrated"
		return "unknown"

	@staticmethod
	def _clamp(value: float, minimum: float, maximum: float) -> float:
		return max(minimum, min(maximum, value))

	@staticmethod
	def _number(value: Any) -> float:
		return round(float(value), 1)

	@staticmethod
	def _mib_to_bytes(value: float) -> int:
		return int(round(float(value) * 1024 * 1024))

	def _warn_once(self, key: str, message: str, *args) -> None:
		with self._lock:
			if key in self._provider_warnings:
				return
			self._provider_warnings.add(key)
		LOGGER.warning(message, *args)
