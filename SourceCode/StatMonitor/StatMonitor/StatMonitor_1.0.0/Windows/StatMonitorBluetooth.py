

from __future__ import annotations

from StatMonitorOutput import print_raw

import asyncio
import copy
import hashlib
import logging
import threading
import time
import uuid
from typing import Any, Callable

from StatMonitorDeviceControls import BLUETOOTH_COMMANDS
from .StatMonitorRadioControl import get_radio_state, set_radio_enabled

try:
	from winrt.windows.devices.bluetooth import BluetoothAdapter, BluetoothDevice, BluetoothLEDevice
	try:
		from winrt.windows.devices.bluetooth import BluetoothCacheMode
	except ImportError:
		BluetoothCacheMode = None
	from winrt.windows.devices.bluetooth.advertisement import BluetoothLEAdvertisementWatcher
	from winrt.windows.devices.enumeration import DeviceInformation, DeviceInformationKind
	from winrt.system import unbox_boolean, unbox_guid, unbox_int32, unbox_string, unbox_uint32, unbox_uint64
	try:
		from winrt.system import unbox_uint16
	except ImportError:
		unbox_uint16 = None
	try:
		from winrt.system import unbox_string_array
	except ImportError:
		unbox_string_array = None
	_WINRT_AVAILABLE = True
except ImportError:
	BluetoothAdapter = None
	BluetoothCacheMode = None
	BluetoothDevice = None
	BluetoothLEDevice = None
	BluetoothLEAdvertisementWatcher = None
	DeviceInformation = None
	DeviceInformationKind = None
	unbox_boolean = None
	unbox_guid = None
	unbox_int32 = None
	unbox_string = None
	unbox_uint16 = None
	unbox_uint32 = None
	unbox_uint64 = None
	unbox_string_array = None
	_WINRT_AVAILABLE = False


LOGGER = logging.getLogger(__name__)
CLASSIC_PROTOCOL = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"
BLE_PROTOCOL = "{bb7bb05e-5972-42b5-94fc-76eaa7084d49}"
CLASSIC_PROTOCOL_UUID = uuid.UUID(CLASSIC_PROTOCOL.strip("{}"))
BLE_PROTOCOL_UUID = uuid.UUID(BLE_PROTOCOL.strip("{}"))
PROPERTIES = [
	"System.ItemNameDisplay", "System.Devices.Aep.ContainerId", "System.Devices.Aep.DeviceAddress",
	"System.Devices.Aep.IsConnected", "System.Devices.Aep.IsPaired", "System.Devices.Aep.IsPresent",
	"System.Devices.Aep.ProtocolId", "System.Devices.Aep.Category", "System.Devices.Aep.Manufacturer",
	"System.Devices.Aep.ModelName", "System.Devices.Aep.SignalStrength", "System.Devices.BatteryLife",
	"System.Devices.Aep.Bluetooth.Cod.Major", "System.Devices.Aep.Bluetooth.Cod.Minor",
	"System.Devices.Aep.Bluetooth.Le.Appearance.Category",
	"System.Devices.Aep.Bluetooth.Le.Appearance.Subcategory",
]
AEP_CONTAINER_PROPERTIES = [
	"System.Devices.AepContainer.Categories",
	"System.ItemNameDisplay",
]
AQS = (
	f'System.Devices.Aep.ProtocolId:="{CLASSIC_PROTOCOL}" OR '
	f'System.Devices.Aep.ProtocolId:="{BLE_PROTOCOL}"'
)
_SETTINGS = (
	"Show Bluetooth Adapter", "Show Connected Devices", "Show Paired Devices",
	"Show Device Type", "Show Device Transport", "Show Device Battery Level",
	"Show Signal Strength",
)
SIGNAL_EXPIRY_SECONDS = 25.0


class StatMonitorBluetooth:


	def __init__(self):
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._endpoints: dict[str, dict[str, Any]] = {}
		self._adapter: dict[str, Any] = {}
		self._radio: dict[str, Any] = {}
		self._signals: dict[str, tuple[int, float]] = {}
		self._running = False
		self._thread: threading.Thread | None = None
		self._loop: asyncio.AbstractEventLoop | None = None
		self._stop_event: asyncio.Event | None = None
		self._watcher: Any = None
		self._signal_watcher: Any = None
		self._watcher_tokens: list[tuple[Any, str, Any]] = []
		self._warning_keys: set[str] = set()
		self._device_type_cache: dict[str, tuple[str, int] | None] = {}
		self._device_type_pending: set[str] = set()
		self._logged_first = False
		self._enumeration_complete = False
		self._connections: dict[str, list[Any]] = {}

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
			self._logged_first = False
		if not _WINRT_AVAILABLE:
			self._warn_once("winrt", "Bluetooth provider unavailable: PyWinRT is not installed")
			self._notify()
			return
		self._thread = threading.Thread(target=self._run_loop, name="StatMonitorBluetooth", daemon=True)
		self._thread.start()

	def stop(self) -> None:
		with self._lock:
			if not self._running and self._thread is None:
				return
			self._running = False
			loop = self._loop
			thread = self._thread
			self._thread = None
		if loop is not None and loop.is_running():
			loop.call_soon_threadsafe(self._request_stop)
		if thread is not None and thread is not threading.current_thread():
			thread.join(timeout=5)
		with self._lock:
			self._loop = None
			self._endpoints.clear()
			self._adapter = {}
			self._radio = {}
			self._signals.clear()
			self._device_type_cache.clear()
			self._device_type_pending.clear()
			self._enumeration_complete = False
			self._close_control_connections()
		self._notify()

	def is_running(self) -> bool:
		with self._lock:
			return self._running


	def handle_command(self, command: Any, arguments: dict[str, Any] | None = None) -> dict:
		arguments = dict(arguments or {})
		if command not in BLUETOOTH_COMMANDS:
			return {"success": False, "error": "unknown_command", "command": command}
		if command == "GetBluetoothStatus":
			return {"success": True, "command": command, "adapter": copy.deepcopy(self._adapter), "radio": get_radio_state("bluetooth"), "devices": self._control_devices()}
		if command == "GetBluetoothAdapters":
			return {"success": True, "command": command, "adapters": [{**copy.deepcopy(self._adapter), **get_radio_state("bluetooth")}] if self._adapter or self._radio else []}
		if command == "GetBluetoothDevices":
			return {"success": True, "command": command, "devices": self._control_devices()}
		if command in {"BluetoothOn", "BluetoothOff"}:
			result = set_radio_enabled("bluetooth", command == "BluetoothOn")
			return {"command": command, **result}
		if not _WINRT_AVAILABLE:
			return {"success": False, "error": "provider_unavailable", "command": command}
		loop = self._loop
		if loop is None or not loop.is_running():
			return {"success": False, "error": "provider_not_running", "command": command}
		coroutine = {
			"ScanBluetooth": self._control_scan,
			"PairBluetoothDevice": self._control_pair,
			"UnpairBluetoothDevice": self._control_unpair,
			"ConnectBluetoothDevice": self._control_connect,
			"DisconnectBluetoothDevice": self._control_disconnect,
		}[command](arguments)
		future = asyncio.run_coroutine_threadsafe(coroutine, loop)
		try:
			return future.result(timeout=45)
		except Exception as error:
			return {"success": False, "error": "request_failed", "command": command, "message": str(error)}

	def update_settings(self, settings: dict[str, bool]) -> None:
		if not isinstance(settings, dict):
			raise ValueError("Bluetooth settings must be an object")
		with self._lock:
			self._settings = {key: bool(settings.get(key, False)) for key in _SETTINGS}
			running = self._running
			current = dict(self._settings)
		if running and self._loop and self._loop.is_running() and _WINRT_AVAILABLE:
			asyncio.run_coroutine_threadsafe(self._configure(current), self._loop)
		self._notify()

	def get_latest(self) -> dict:
		with self._lock:
			settings = dict(self._settings)
			hardware: dict[str, Any] = {}
			live: dict[str, Any] = {}
			if settings.get("Show Bluetooth Adapter") and self._adapter:
				hardware["adapter"] = copy.deepcopy(self._adapter)
				if self._radio:
					live["adapter"] = copy.deepcopy(self._radio)
			if settings.get("Show Connected Devices") or settings.get("Show Paired Devices"):
				visible = self._visible_devices(settings)
				if visible:
					hardware["devices"] = [self._hardware_device(item, settings) for item in visible]
					live["devices"] = [self._live_device(item, settings) for item in visible]
			return {"hardware": hardware, "live": live}

	def get_metric_snapshot(self) -> dict[str, Any]:

		latest = self.get_latest()
		hardware = latest.get("hardware", {})
		live = latest.get("live", {})

		adapter_hardware = hardware.get("adapter") if isinstance(hardware.get("adapter"), dict) else {}
		adapter_live = live.get("adapter") if isinstance(live.get("adapter"), dict) else {}

		metrics: dict[str, Any] = {}
		if adapter_hardware.get("name") is not None:
			metrics["Bluetooth_Adapter_Name"] = adapter_hardware.get("name")
		if adapter_live.get("state") is not None:
			metrics["Bluetooth_Adapter_State"] = adapter_live.get("state")
		if adapter_hardware.get("classic_supported") is not None:
			metrics["Bluetooth_Classic_Supported"] = adapter_hardware.get("classic_supported")
		if adapter_hardware.get("low_energy_supported") is not None:
			metrics["Bluetooth_Low_Energy_Supported"] = adapter_hardware.get("low_energy_supported")

		hardware_devices = hardware.get("devices", []) if isinstance(hardware.get("devices"), list) else []
		live_devices = live.get("devices", []) if isinstance(live.get("devices"), list) else []
		live_by_id = {
			item.get("device_id"): item
			for item in live_devices
			if isinstance(item, dict) and item.get("device_id") is not None
		}

		devices = []
		for hardware_device in hardware_devices:
			if not isinstance(hardware_device, dict):
				continue
			device_id = hardware_device.get("device_id")
			live_device = live_by_id.get(device_id, {})
			item: dict[str, Any] = {}

			if device_id is not None:
				item["Bluetooth_Device_ID"] = device_id
			if hardware_device.get("name") is not None:
				item["Bluetooth_Device_Name"] = hardware_device.get("name")
			if hardware_device.get("device_type") is not None:
				item["Bluetooth_Device_Type"] = copy.deepcopy(hardware_device.get("device_type"))
			if hardware_device.get("transports"):
				item["Bluetooth_Device_Transports"] = copy.deepcopy(hardware_device.get("transports"))
			if live_device.get("connected") is not None:
				item["Bluetooth_Device_Connected"] = live_device.get("connected")
			if live_device.get("paired") is not None:
				item["Bluetooth_Device_Paired"] = live_device.get("paired")
			if live_device.get("battery_percent") is not None:
				item["Bluetooth_Device_Battery_Level"] = live_device.get("battery_percent")
			if live_device.get("signal_strength_dbm") is not None:
				item["Bluetooth_Device_Signal_Strength"] = live_device.get("signal_strength_dbm")

			if item:
				devices.append(item)

		metrics["Bluetooth_Individual_Devices"] = devices
		return metrics

	@staticmethod
	def _format_transport(value: Any) -> str:
		return {
			"classic": "Classic",
			"low_energy": "Low Energy",
		}.get(str(value).lower(), str(value).replace("_", " ").title())

	def _print_bluetooth_module_block(self) -> None:
		metrics = self.get_metric_snapshot()
		lines = ["-" * 60, "Bluetooth_Module"]

		for metric_id, value in metrics.items():
			if metric_id != "Bluetooth_Individual_Devices":
				if metric_id == "Bluetooth_Adapter_State" and value is not None:
					display_value = str(value).replace("_", " ").title()
				else:
					display_value = value if value is not None else "Unavailable"
				lines.append(f"{metric_id}: {display_value}")
				continue

			devices = value if isinstance(value, list) else []
			lines.append(f"{metric_id}: {len(devices)}")
			for index, device in enumerate(devices, 1):
				lines.append(f"  [{index}]")
				for child_id, child_value in device.items():
					if child_id == "Bluetooth_Device_Transports":
						transports = child_value if isinstance(child_value, list) else [child_value]
						display_value = ", ".join(self._format_transport(item) for item in transports)
					elif child_id == "Bluetooth_Device_Battery_Level":
						display_value = f"{child_value}%"
					elif child_id == "Bluetooth_Device_Signal_Strength":
						display_value = f"{child_value} dBm"
					else:
						display_value = child_value if child_value is not None else "Unavailable"
					lines.append(f"    {child_id}: {display_value}")

		lines.append("-" * 60)
		print_raw("\n".join(lines))

	def _visible_devices(self, settings: dict[str, bool]) -> list[dict[str, Any]]:
		merged = self._merged_devices()
		return [item for item in merged if (settings.get("Show Connected Devices") and item["connected"])
			or (settings.get("Show Paired Devices") and item["paired"])]

	def _hardware_device(self, item: dict[str, Any], settings: dict[str, bool]) -> dict[str, Any]:
		result = {"device_id": item["device_id"], "name": item["name"]}
		if settings.get("Show Device Type") and item.get("device_type"):
			result["device_type"] = item["device_type"]
		if settings.get("Show Device Transport") and item.get("transports"):
			result["transports"] = sorted(item["transports"])
		return result

	def _live_device(self, item: dict[str, Any], settings: dict[str, bool]) -> dict[str, Any]:
		result = {"device_id": item["device_id"], "connected": item["connected"], "paired": item["paired"]}
		if settings.get("Show Device Battery Level") and item.get("battery_percent") is not None:
			result["battery_percent"] = item["battery_percent"]
		if settings.get("Show Signal Strength"):
			signal = self._signals.get(item["device_id"])
			if signal and signal[1] + SIGNAL_EXPIRY_SECONDS >= time.monotonic():
				result["signal_strength_dbm"] = signal[0]
		return result

	def _merged_devices(self) -> list[dict[str, Any]]:
		groups: dict[str, dict[str, Any]] = {}
		for endpoint in self._endpoints.values():
			group_id = endpoint.get("container_id") or endpoint["device_id"]
			item = groups.setdefault(group_id, {
				"device_id": group_id, "name": endpoint.get("name") or "Bluetooth Device",
				"transports": set(), "connected": False, "paired": False,
			})
			item["connected"] = item["connected"] or endpoint.get("connected", False)
			item["paired"] = item["paired"] or endpoint.get("paired", False)
			if endpoint.get("transport"):
				item["transports"].add(endpoint["transport"])
			if endpoint.get("device_type"):
				endpoint_score = int(endpoint.get("_device_type_score", 0))
				if endpoint_score > int(item.get("_device_type_score", -1)):
					item["device_type"] = endpoint["device_type"]
					item["_device_type_score"] = endpoint_score
			for key in ("name", "battery_percent", "address"):
				if endpoint.get(key) is not None and not item.get(key):
					item[key] = endpoint[key]
		return list(groups.values())

	def _control_devices(self) -> list[dict[str, Any]]:
		devices = []
		for item in self._merged_devices():
			entry = {
				"device_id": item.get("device_id"),
				"name": item.get("name"),
				"connected": bool(item.get("connected")),
				"paired": bool(item.get("paired")),
				"transports": sorted(item.get("transports", [])),
			}
			if item.get("device_type"):
				entry["device_type"] = item.get("device_type")
			if item.get("address") is not None:
				entry["address"] = item.get("address")
			if item.get("battery_percent") is not None:
				entry["battery_percent"] = item.get("battery_percent")
			devices.append(entry)
		return sorted(devices, key=lambda item: (not item["connected"], not item["paired"], str(item.get("name") or "").casefold()))

	def _resolve_control_endpoints(self, value: Any) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
		needle = str(value or "").strip()
		if not needle:
			raise ValueError("device is required")
		needle_fold = needle.casefold()
		with self._lock:
			endpoints = list(self._endpoints.items())
		groups = self._merged_devices()
		group = next((item for item in groups if str(item.get("device_id", "")).casefold() == needle_fold), None)
		if group is None:
			group = next((item for item in groups if str(item.get("name", "")).casefold() == needle_fold), None)
		if group is None:
			compact = "".join(character for character in needle.lower() if character in "0123456789abcdef")
			for item in groups:
				address = item.get("address")
				if address is not None and compact and compact == f"{int(address):012x}":
					group = item
					break
		if group is None:
			raise ValueError(f"Bluetooth device not found: {needle}")
		group_id = group.get("device_id")
		matches = []
		for endpoint_id, endpoint in endpoints:
			endpoint_group = endpoint.get("container_id") or endpoint.get("device_id")
			if endpoint_group == group_id:
				matches.append((endpoint_id, endpoint))
		if not matches:
			raise ValueError(f"Bluetooth endpoints unavailable for: {needle}")
		return group, matches

	async def _control_scan(self, arguments: dict[str, Any]) -> dict:
		await self._close_device_watcher()
		await self._ensure_device_watcher()
		await asyncio.sleep(float(arguments.get("seconds", 2.0)))
		return {"success": True, "command": "ScanBluetooth", "devices": self._control_devices()}

	async def _device_information(self, endpoint_id: str):
		return await DeviceInformation.create_from_id_async(endpoint_id, PROPERTIES, DeviceInformationKind.ASSOCIATION_ENDPOINT)

	@staticmethod
	def _pairing_status(result: Any) -> str:
		status = getattr(result, "status", None)
		name = getattr(status, "name", None)
		return str(name or status or "unknown").lower()

	async def _refresh_endpoint_information(self, matches: list[tuple[str, dict[str, Any]]]) -> None:
		for endpoint_id, _ in matches:
			try:
				info = await self._device_information(endpoint_id)
				if info is not None:
					self._store_endpoint(info, endpoint_id)
			except Exception:
				pass

	async def _control_pair(self, arguments: dict[str, Any]) -> dict:
		group, matches = self._resolve_control_endpoints(arguments.get("device"))
		if group.get("paired"):
			return {"success": True, "command": "PairBluetoothDevice", "device": group, "already_paired": True}
		statuses = []
		for endpoint_id, _ in matches:
			try:
				info = await self._device_information(endpoint_id)
				pairing = getattr(info, "pairing", None) if info is not None else None
				if pairing is None:
					continue
				if bool(getattr(pairing, "is_paired", False)):
					statuses.append("already_paired")
					continue
				if not bool(getattr(pairing, "can_pair", True)):
					statuses.append("not_pairable")
					continue
				result = await pairing.pair_async()
				statuses.append(self._pairing_status(result))
			except Exception as error:
				statuses.append(f"error:{error}")
		await self._refresh_endpoint_information(matches)
		try:
			current = self._resolve_control_endpoints(group.get("device_id"))[0]
		except ValueError:
			current = dict(group)
		success = bool(current.get("paired")) or any(status in {"paired", "already_paired"} for status in statuses)
		return {"success": success, "command": "PairBluetoothDevice", "device": current, "statuses": statuses}

	async def _control_unpair(self, arguments: dict[str, Any]) -> dict:
		group, matches = self._resolve_control_endpoints(arguments.get("device"))
		if not group.get("paired"):
			return {"success": True, "command": "UnpairBluetoothDevice", "device": group, "already_unpaired": True}
		self._release_group_connections(group.get("device_id"))
		statuses = []
		for endpoint_id, _ in matches:
			try:
				info = await self._device_information(endpoint_id)
				pairing = getattr(info, "pairing", None) if info is not None else None
				if pairing is None:
					continue
				if not bool(getattr(pairing, "is_paired", False)):
					statuses.append("already_unpaired")
					continue
				result = await pairing.unpair_async()
				statuses.append(self._pairing_status(result))
			except Exception as error:
				statuses.append(f"error:{error}")
		await asyncio.sleep(0.4)
		await self._refresh_endpoint_information(matches)
		try:
			current = self._resolve_control_endpoints(group.get("device_id"))[0]
		except ValueError:
			current = {**group, "paired": False, "connected": False}
		success = not bool(current.get("paired")) or any(status in {"unpaired", "already_unpaired"} for status in statuses)
		return {"success": success, "command": "UnpairBluetoothDevice", "device": current, "statuses": statuses}

	async def _control_connect(self, arguments: dict[str, Any]) -> dict:
		group, matches = self._resolve_control_endpoints(arguments.get("device"))
		if not group.get("paired"):
			return {"success": False, "error": "device_not_paired", "command": "ConnectBluetoothDevice", "device": group}
		if group.get("connected"):
			return {"success": True, "command": "ConnectBluetoothDevice", "device": group, "already_connected": True, "confirmed": True}
		handles = []
		strategies = []
		for endpoint_id, endpoint in matches:
			transport = endpoint.get("transport")
			try:
				if transport == "low_energy" and BluetoothLEDevice is not None:
					device = await BluetoothLEDevice.from_id_async(endpoint_id)
					if device is not None:
						handles.append(device)
						method = getattr(device, "get_gatt_services_async", None)
						if callable(method):
							if BluetoothCacheMode is not None:
								await method(BluetoothCacheMode.UNCACHED)
							else:
								await method()
						strategies.append("ble_gatt")
				elif transport == "classic" and BluetoothDevice is not None:
					device = await BluetoothDevice.from_id_async(endpoint_id)
					if device is not None:
						handles.append(device)
						method = getattr(device, "get_rfcomm_services_async", None)
						if callable(method):
							if BluetoothCacheMode is not None:
								await method(BluetoothCacheMode.UNCACHED)
							else:
								await method()
						strategies.append("classic_rfcomm")
			except Exception as error:
				strategies.append(f"{transport or 'unknown'}_error:{error}")
		if handles:
			with self._lock:
				self._connections[group.get("device_id")] = handles
		for _ in range(10):
			await asyncio.sleep(0.5)
			await self._refresh_endpoint_information(matches)
			current = self._resolve_control_endpoints(group.get("device_id"))[0]
			if current.get("connected"):
				return {"success": True, "command": "ConnectBluetoothDevice", "device": current, "confirmed": True, "strategies": strategies}
		current = self._resolve_control_endpoints(group.get("device_id"))[0]
		return {"success": bool(handles), "command": "ConnectBluetoothDevice", "device": current, "confirmed": False, "connection_requested": bool(handles), "strategies": strategies, "message": "Windows accepted a Bluetooth connection request but did not report a system-profile connection. Some audio/HID profiles are controlled only by Windows."}

	async def _control_disconnect(self, arguments: dict[str, Any]) -> dict:
		group, matches = self._resolve_control_endpoints(arguments.get("device"))
		released = self._release_group_connections(group.get("device_id"))
		await asyncio.sleep(0.75)
		await self._refresh_endpoint_information(matches)
		current = self._resolve_control_endpoints(group.get("device_id"))[0]
		if not current.get("connected"):
			return {"success": True, "command": "DisconnectBluetoothDevice", "device": current, "confirmed": True, "released_handles": released}
		return {"success": released > 0, "command": "DisconnectBluetoothDevice", "device": current, "confirmed": False, "released_handles": released, "message": "StatMonitor released its Bluetooth connection, but Windows still reports a system-profile connection. Generic forced disconnect is not exposed by WinRT for every Bluetooth profile."}

	def _release_group_connections(self, group_id: Any) -> int:
		with self._lock:
			if group_id is None:
				handles = []
			else:
				handles = self._connections.pop(group_id, [])
				if not handles and not isinstance(group_id, str):
					handles = self._connections.pop(str(group_id), [])
		count = 0
		for handle in handles:
			try:
				close = getattr(handle, "close", None)
				if callable(close):
					close()
				count += 1
			except Exception:
				pass
		return count

	def _close_control_connections(self) -> None:
		with self._lock:
			identifiers = list(self._connections)
		for identifier in identifiers:
			self._release_group_connections(identifier)

	def _run_loop(self) -> None:
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		with self._lock:
			self._loop = loop
			should_stop = not self._running
			settings = dict(self._settings)
		self._stop_event = asyncio.Event()
		if should_stop:
			self._stop_event.set()
		try:
			if not should_stop:
				loop.run_until_complete(self._configure(settings))
			loop.run_until_complete(self._stop_event.wait())
		finally:
			loop.run_until_complete(self._close_watchers())
			loop.close()

	def _request_stop(self) -> None:
		if self._stop_event is not None:
			self._stop_event.set()

	async def _configure(self, settings: dict[str, bool]) -> None:
		try:
			await self._configure_adapter(settings)
			await self._ensure_device_watcher()
			if settings.get("Show Signal Strength"):
				await self._ensure_signal_watcher()
			else:
				await self._close_signal_watcher()
			if settings.get("Show Device Type") and self._enumeration_complete:
				await self._enrich_all_device_types()
		except Exception as error:
			self._warn_once("configure", "Bluetooth provider configuration failed: %s", error)
		self._notify()

	async def _configure_adapter(self, settings: dict[str, bool]) -> None:
		if not settings.get("Show Bluetooth Adapter"):
			return
		adapter = await BluetoothAdapter.get_default_async()
		if adapter is None:
			self._warn_once("adapter", "Bluetooth adapter unavailable")
			return
		data = {}
		for source, target in (("name", "name"), ("is_classic_supported", "classic_supported"), ("is_low_energy_supported", "low_energy_supported")):
			value = getattr(adapter, source, None)
			if value is not None:
				data[target] = value if not callable(value) else value()
		with self._lock:
			self._adapter = data
		try:
			radio = await adapter.get_radio_async()
			raw_state = getattr(radio, "state", None)
			enum_name = getattr(raw_state, "name", None)
			if enum_name:
				state = str(enum_name).lower()
			else:
				try:
					numeric_state = int(raw_state)
				except (TypeError, ValueError):
					numeric_state = None
				state = {
					0: "unknown",
					1: "on",
					2: "off",
					3: "disabled",
				}.get(numeric_state, "unknown")
			radio_name = getattr(radio, "name", None)
			with self._lock:
				if radio_name and not self._adapter.get("name"):
					self._adapter["name"] = str(radio_name).strip()
				self._radio = {"state": state if state in ("on", "off", "disabled") else "unknown"}
		except Exception as error:
			self._warn_once("radio", "Bluetooth radio state unavailable: %s", error)
		self._notify()

	async def _ensure_device_watcher(self) -> None:
		if self._watcher is not None:
			return
		watcher = DeviceInformation.create_watcher_with_kind_aqs_filter_and_additional_properties(
			AQS,
			PROPERTIES,
			DeviceInformationKind.ASSOCIATION_ENDPOINT,
		)
		self._watcher = watcher
		for event_name, callback in (("added", self._on_added), ("updated", self._on_updated), ("removed", self._on_removed), ("enumeration_completed", self._on_enumeration_completed)):
			add = getattr(watcher, f"add_{event_name}", None)
			if add is not None:
				self._watcher_tokens.append((watcher, event_name, add(callback)))
		watcher.start()

	async def _close_device_watcher(self) -> None:
		watcher = self._watcher
		self._watcher = None
		if watcher is not None:
			for registered_watcher, event_name, token in self._watcher_tokens:
				if registered_watcher is watcher:
					remove = getattr(watcher, f"remove_{event_name}", None)
					if remove is not None:
						try:
							remove(token)
						except Exception:
							pass
			try:
				watcher.stop()
			except Exception:
				pass
		self._endpoints.clear()
		self._enumeration_complete = False
		self._watcher_tokens = [item for item in self._watcher_tokens if item[0] is not watcher]

	async def _ensure_signal_watcher(self) -> None:
		if self._signal_watcher is not None:
			return
		watcher = BluetoothLEAdvertisementWatcher()
		add = getattr(watcher, "add_received", None)
		if add is not None:
			self._watcher_tokens.append((watcher, "received", add(self._on_advertisement)))
		self._signal_watcher = watcher
		watcher.start()

	async def _close_signal_watcher(self) -> None:
		watcher = self._signal_watcher
		self._signal_watcher = None
		if watcher is not None:
			for registered_watcher, event_name, token in self._watcher_tokens:
				if registered_watcher is watcher:
					remove = getattr(watcher, f"remove_{event_name}", None)
					if remove is not None:
						try:
							remove(token)
						except Exception:
							pass
			try:
				watcher.stop()
			except Exception:
				pass
		self._signals.clear()
		self._watcher_tokens = [item for item in self._watcher_tokens if item[0] is not watcher]

	async def _close_watchers(self) -> None:
		await self._close_signal_watcher()
		await self._close_device_watcher()

	def _on_added(self, watcher: Any, info: Any) -> None:
		self._store_endpoint(info)

	def _on_updated(self, watcher: Any, update: Any) -> None:
		endpoint_id = getattr(update, "id", None)
		if endpoint_id in self._endpoints:
			self._store_endpoint(update, endpoint_id)

	def _on_removed(self, watcher: Any, update: Any) -> None:
		with self._lock:
			self._endpoints.pop(getattr(update, "id", ""), None)
		self._notify()

	def _on_enumeration_completed(self, watcher: Any, _args: Any) -> None:
		self._enumeration_complete = True
		loop = self._loop
		if loop is not None and loop.is_running():
			asyncio.run_coroutine_threadsafe(self._finish_initial_enumeration(), loop)
		else:
			self._log_first_telemetry()
			self._notify()

	async def _finish_initial_enumeration(self) -> None:
		with self._lock:
			show_device_type = self._settings.get("Show Device Type", False)
		if show_device_type:
			await self._enrich_all_device_types()
		self._log_first_telemetry()
		self._notify()

	def _store_endpoint(self, info: Any, endpoint_id: str | None = None) -> None:
		try:
			endpoint_id = endpoint_id or str(info.id)
			previous = self._endpoints.get(endpoint_id, {})
			raw_protocol = self._property(info, "System.Devices.Aep.ProtocolId")
			protocol_uuid = self._property_guid_value(raw_protocol) or previous.get("protocol_uuid")
			if protocol_uuid == CLASSIC_PROTOCOL_UUID:
				transport = "classic"
			elif protocol_uuid == BLE_PROTOCOL_UUID:
				transport = "low_energy"
			else:
				return
			container_uuid = self._property_guid_value(self._property(info, "System.Devices.Aep.ContainerId"))
			container = self._normalize_container(container_uuid) or self._normalize_container(previous.get("container_id"))
			name = self._first_text(getattr(info, "name", None), self._property_string(info, "System.ItemNameDisplay"), self._property_string(info, "System.Devices.Aep.ModelName"))
			if name == "Bluetooth Device":
				name = previous.get("name", name)
			connected = self._property_bool(info, "System.Devices.Aep.IsConnected")
			paired = self._property_bool(info, "System.Devices.Aep.IsPaired")
			present = self._property_bool(info, "System.Devices.Aep.IsPresent")
			category = self._property_category(info, "System.Devices.Aep.Category")
			classic_major = self._property_int(info, "System.Devices.Aep.Bluetooth.Cod.Major")
			classic_minor = self._property_int(info, "System.Devices.Aep.Bluetooth.Cod.Minor")
			ble_appearance_category = self._property_int(info, "System.Devices.Aep.Bluetooth.Le.Appearance.Category")
			ble_appearance_subcategory = self._property_int(info, "System.Devices.Aep.Bluetooth.Le.Appearance.Subcategory")
			type_candidate = self._resolve_device_type(
				category, transport, classic_major, classic_minor,
				ble_appearance_category, ble_appearance_subcategory,
			)
			battery = self._battery_value(self._property_int(info, "System.Devices.BatteryLife"))
			address_value = self._property_string(info, "System.Devices.Aep.DeviceAddress")
			if address_value is None:
				address_value = self._property_int(info, "System.Devices.Aep.DeviceAddress")
			address = self._address_value(address_value)
			endpoint = {
				"device_id": self._fallback_id(container, endpoint_id), "container_id": container,
				"name": name, "protocol_uuid": protocol_uuid, "transport": transport,
				"connected": previous.get("connected", False) if connected is None else bool(connected),
				"paired": previous.get("paired", False) if paired is None else bool(paired),
				"present": previous.get("present", False) if present is None else bool(present),
				"battery_percent": battery if battery is not None else previous.get("battery_percent"),
				"address": address if address is not None else previous.get("address"),
			}
			if type_candidate is not None:
				label, score = type_candidate
				if score >= int(previous.get("_device_type_score", -1)):
					endpoint["device_type"] = label
					endpoint["_device_type_score"] = score
			elif previous.get("device_type"):
				endpoint["device_type"] = previous.get("device_type")
				endpoint["_device_type_score"] = previous.get("_device_type_score", 0)
			with self._lock:
				self._endpoints[endpoint_id] = {key: value for key, value in {**previous, **endpoint}.items()
					if value is not None and value != ""}
			if container and self._enumeration_complete:
				with self._lock:
					show_device_type = self._settings.get("Show Device Type", False)
				if show_device_type:
					self._schedule_container_type_enrichment(container)
			self._notify()
		except Exception as error:
			self._warn_once("endpoint", "Bluetooth endpoint update failed: %s", error)

	async def _enrich_all_device_types(self) -> None:
		with self._lock:
			containers = sorted({
				endpoint.get("container_id")
				for endpoint in self._endpoints.values()
				if endpoint.get("container_id")
			})
		if not containers:
			return
		await asyncio.gather(*(self._enrich_container_type(container) for container in containers), return_exceptions=True)

	def _schedule_container_type_enrichment(self, container: str) -> None:
		loop = self._loop
		if loop is None or not loop.is_running():
			return
		with self._lock:
			if container in self._device_type_pending:
				return
			if container in self._device_type_cache:
				cached = self._device_type_cache[container]
				if cached is not None:
					self._apply_container_type(container, cached)
				return
			self._device_type_pending.add(container)
		asyncio.run_coroutine_threadsafe(self._enrich_container_type(container), loop)

	async def _enrich_container_type(self, container: str) -> None:
		with self._lock:
			if container in self._device_type_cache:
				cached = self._device_type_cache[container]
				self._device_type_pending.discard(container)
				if cached is not None:
					self._apply_container_type(container, cached)
				return
		try:
			kind = getattr(DeviceInformationKind, "ASSOCIATION_ENDPOINT_CONTAINER", None)
			if kind is None or DeviceInformation is None:
				candidate = None
			else:
				info = await DeviceInformation.create_from_id_async(
					container.strip("{}"),
					AEP_CONTAINER_PROPERTIES,
					kind,
				)
				categories = self._property_category(info, "System.Devices.AepContainer.Categories") if info is not None else None
				candidate = self._device_type_from_categories(categories, source_bonus=5)
		except Exception as error:
			LOGGER.debug("Bluetooth device type container enrichment failed for %s: %s", container, error)
			candidate = None
		with self._lock:
			self._device_type_cache[container] = candidate
			self._device_type_pending.discard(container)
			if candidate is not None:
				self._apply_container_type(container, candidate)
		if candidate is not None:
			self._notify()

	def _apply_container_type(self, container: str, candidate: tuple[str, int]) -> None:
		label, score = candidate
		for endpoint in self._endpoints.values():
			if endpoint.get("container_id") != container:
				continue
			if score > int(endpoint.get("_device_type_score", -1)):
				endpoint["device_type"] = label
				endpoint["_device_type_score"] = score

	@classmethod
	def _resolve_device_type(
		cls,
		categories: Any,
		transport: str,
		classic_major: int | None,
		classic_minor: int | None,
		ble_category: int | None,
		ble_subcategory: int | None,
	) -> tuple[str, int] | None:
		candidates = [cls._device_type_from_categories(categories)]
		if transport == "classic":
			candidates.append(cls._device_type_from_classic_cod(classic_major, classic_minor))
		elif transport == "low_energy":
			candidates.append(cls._device_type_from_ble_appearance(ble_category, ble_subcategory))
		available = [candidate for candidate in candidates if candidate is not None]
		return max(available, key=lambda item: item[1]) if available else None

	@classmethod
	def _device_type_from_categories(cls, categories: Any, source_bonus: int = 0) -> tuple[str, int] | None:
		values = cls._category_values(categories)
		if not values:
			return None
		text = " | ".join(value.lower() for value in values)
		specific_rules = (
			(("audio.headphone", "headphones", "headphone"), "Headphones"),
			(("audio.headset", "headset"), "Headset"),
			(("input.keyboard", "keyboard"), "Keyboard"),
			(("input.mouse", "pointing device", "mouse"), "Mouse"),
			(("input.gaming", "game controller", "gamepad", "gaming"), "Game Controller"),
			(("remote control", "remotecontrol"), "Remote Control"),
			(("audio.speaker", "loudspeaker", "speaker"), "Speaker"),
			(("microphone",), "Microphone"),
			(("digital pen", "stylus"), "Digital Pen"),
			(("digitizer tablet", "tablet input"), "Digitizer Tablet"),
			(("barcode scanner",), "Barcode Scanner"),
			(("scanner",), "Scanner"),
			(("printer",), "Printer"),
			(("camera", "imaging.camera"), "Camera"),
			(("display.monitor", "video monitor", "monitor"), "Monitor"),
			(("communication.phone", "smartphone", " phone"), "Phone"),
			(("computer",), "Computer"),
			(("watch",), "Watch"),
		)
		for needles, label in specific_rules:
			if any(needle in text for needle in needles):
				return label, 100 + source_bonus
		generic_rules = (
			(("audio device", "audio"), "Audio Device"),
			(("human interface device", "input device", "peripheral"), "Input Device"),
			(("wearable",), "Wearable Device"),
			(("health",), "Health Device"),
		)
		for needles, label in generic_rules:
			if any(needle in text for needle in needles):
				return label, 60 + source_bonus
		return None

	@staticmethod
	def _device_type_from_classic_cod(major: int | None, minor: int | None) -> tuple[str, int] | None:
		if major is None:
			return None
		minor = 0 if minor is None else int(minor)
		major = int(major)
		if major == 4:
			label = {
				1: "Headset", 2: "Hands-Free Device", 4: "Microphone", 5: "Speaker",
				6: "Headphones", 7: "Portable Audio Device", 8: "Car Audio",
				9: "Set-top Box", 10: "Hi-Fi Audio Device", 11: "VCR",
				12: "Video Camera", 13: "Camcorder", 14: "Video Monitor",
				15: "Video Display and Speaker", 16: "Video Conferencing Device",
				18: "Game Device",
			}.get(minor)
			return (label, 95) if label else ("Audio/Video Device", 50)
		if major == 5:
			keyboard_pointing = minor & 0x30
			base_minor = minor & 0x0F
			if keyboard_pointing == 0x10 and base_minor == 0:
				return "Keyboard", 95
			if keyboard_pointing == 0x20 and base_minor == 0:
				return "Mouse", 95
			if keyboard_pointing == 0x30 and base_minor == 0:
				return "Keyboard and Mouse", 95
			label = {
				1: "Joystick", 2: "Game Controller", 3: "Remote Control", 4: "Sensor",
				5: "Digitizer Tablet", 6: "Card Reader", 7: "Digital Pen",
				8: "Handheld Scanner", 9: "Gesture Input Device",
			}.get(base_minor)
			if label:
				return label, 95
			if keyboard_pointing == 0x10:
				return "Keyboard", 90
			if keyboard_pointing == 0x20:
				return "Mouse", 90
			if keyboard_pointing == 0x30:
				return "Keyboard and Mouse", 90
			return "Input Device", 50
		if major == 1:
			return ({1: "Desktop Computer", 2: "Server", 3: "Laptop", 4: "Handheld Computer", 5: "Palm-size Computer", 6: "Wearable Computer", 7: "Tablet"}.get(minor, "Computer"), 80)
		if major == 2:
			return ({1: "Cell Phone", 2: "Cordless Phone", 3: "Smartphone", 4: "Modem/Voice Gateway", 5: "ISDN Device"}.get(minor, "Phone"), 80)
		if major == 6:
			return "Imaging Device", 50
		if major == 7:
			return ({1: "Watch", 2: "Pager", 3: "Wearable Jacket", 4: "Wearable Helmet", 5: "Smart Glasses"}.get(minor, "Wearable Device"), 75)
		if major == 8:
			return ({1: "Robot", 2: "Toy Vehicle", 3: "Doll/Action Figure", 4: "Toy Controller", 5: "Game"}.get(minor, "Toy"), 75)
		if major == 9:
			return "Health Device", 50
		return None

	@staticmethod
	def _device_type_from_ble_appearance(category: int | None, subcategory: int | None) -> tuple[str, int] | None:
		if category is None:
			return None
		category = int(category)
		subcategory = 0 if subcategory is None else int(subcategory)
		if category == 15:
			label = {
				1: "Keyboard", 2: "Mouse", 3: "Joystick", 4: "Game Controller",
				5: "Digitizer Tablet", 6: "Card Reader", 7: "Digital Pen",
				8: "Barcode Scanner",
			}.get(subcategory)
			return (label, 95) if label else ("Input Device", 50)
		label = {
			1: "Phone", 2: "Computer", 3: "Watch", 4: "Clock", 5: "Display",
			6: "Remote Control", 7: "Smart Glasses", 8: "Tag", 9: "Keyring",
			10: "Media Player", 11: "Barcode Scanner", 12: "Thermometer",
			13: "Heart Rate Sensor", 14: "Blood Pressure Monitor", 16: "Glucose Meter",
			17: "Running/Walking Sensor", 18: "Cycling Sensor",
		}.get(category)
		return (label, 80) if label else None

	@staticmethod
	def _category_values(value: Any) -> list[str]:
		if value is None:
			return []
		if isinstance(value, str):
			text = value.strip()
			return [text] if text else []
		if isinstance(value, (list, tuple, set)):
			return [str(item).strip() for item in value if item is not None and str(item).strip()]
		text = str(value).strip()
		return [text] if text else []

	@staticmethod
	def _normalize_guid(value: Any) -> uuid.UUID | None:
		if value is None:
			return None
		if isinstance(value, uuid.UUID):
			return value
		try:
			return uuid.UUID(str(value).strip().strip("{}"))
		except (ValueError, TypeError, AttributeError):
			return None

	@staticmethod
	def _property(info: Any, name: str, default: Any = None) -> Any:
		try:
			properties = getattr(info, "properties", None)
			if properties is not None and name in properties:
				return properties[name]
		except Exception:
			pass
		return default

	@classmethod
	def _property_guid_value(cls, raw: Any) -> uuid.UUID | None:
		if raw is None:
			return None
		if isinstance(raw, uuid.UUID):
			return raw
		if unbox_guid is not None:
			try:
				return cls._normalize_guid(unbox_guid(raw))
			except (TypeError, ValueError, RuntimeError):
				pass
		return cls._normalize_guid(raw)

	@staticmethod
	def _property_string(info: Any, name: str) -> str | None:
		raw = StatMonitorBluetooth._property(info, name)
		if raw is None:
			return None
		if isinstance(raw, str):
			return raw
		if unbox_string is not None:
			try:
				value = unbox_string(raw)
				return str(value) if value is not None else None
			except (TypeError, ValueError, RuntimeError):
				return None
		return None

	@staticmethod
	def _property_bool(info: Any, name: str) -> bool | None:
		raw = StatMonitorBluetooth._property(info, name)
		if raw is None:
			return None
		if isinstance(raw, bool):
			return raw
		if unbox_boolean is not None:
			try:
				return bool(unbox_boolean(raw))
			except (TypeError, ValueError, RuntimeError):
				return None
		return None

	@staticmethod
	def _property_int(info: Any, name: str) -> int | None:
		raw = StatMonitorBluetooth._property(info, name)
		if raw is None:
			return None
		if isinstance(raw, int) and not isinstance(raw, bool):
			return raw
		for unboxer in (unbox_uint16, unbox_uint32, unbox_int32, unbox_uint64):
			if unboxer is not None:
				try:
					return int(unboxer(raw))
				except (TypeError, ValueError, RuntimeError):
					continue
		return None

	@staticmethod
	def _property_category(info: Any, name: str) -> Any:
		raw = StatMonitorBluetooth._property(info, name)
		if raw is None:
			return None
		if isinstance(raw, str):
			return raw
		if isinstance(raw, (list, tuple)):
			return [str(value) for value in raw if value is not None]
		if unbox_string_array is not None:
			try:
				return [str(value) for value in unbox_string_array(raw)]
			except (TypeError, ValueError, RuntimeError):
				return None
		return None

	@staticmethod
	def _battery_value(value: Any) -> int | None:
		try:
			value = int(value)
			return value if 0 <= value <= 100 else None
		except (TypeError, ValueError):
			return None

	@staticmethod
	def _address_value(value: Any) -> int | None:
		if value is None:
			return None
		try:
			text = str(value).strip().lower().replace(":", "").replace("-", "")
			return int(text, 16) if text else None
		except (TypeError, ValueError):
			return None

	@staticmethod
	def _normalize_category(value: Any) -> str | None:
		if not value:
			return None
		text = str(value).strip()
		return text or None

	@staticmethod
	def _normalize_container(value: Any) -> str | None:
		if not value:
			return None
		try:
			return "{" + str(uuid.UUID(str(value).strip("{}"))).upper() + "}"
		except (ValueError, AttributeError, TypeError):
			return None

	@staticmethod
	def _fallback_id(container: str | None, endpoint_id: str) -> str:
		if container:
			return container
		return "endpoint-" + hashlib.sha256(endpoint_id.encode("utf-8", "replace")).hexdigest()[:24]

	@staticmethod
	def _first_text(*values: Any) -> str:
		for value in values:
			if value:
				text = str(value).strip()
				if text and not text.startswith(("BluetoothLE#", "BTHENUM\\")):
					return text
		return "Bluetooth Device"

	def _on_advertisement(self, watcher: Any, args: Any) -> None:
		try:
			address = int(args.bluetooth_address)
			strength = int(args.raw_signal_strength_in_dbm)
			with self._lock:
				for endpoint in self._endpoints.values():
					if endpoint.get("address") == address:
						self._signals[endpoint["device_id"]] = (strength, time.monotonic())
		except Exception:
			return

	def _log_first_telemetry(self) -> None:
		with self._lock:
			if self._logged_first or not self._enumeration_complete:
				return
			self._logged_first = True
		self._print_bluetooth_module_block()

	def _notify(self) -> None:
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				LOGGER.exception("StatMonitor Bluetooth listener failed")

	def _warn_once(self, key: str, message: str, *args) -> None:
		with self._lock:
			if key in self._warning_keys:
				return
			self._warning_keys.add(key)
		LOGGER.warning(message, *args)
