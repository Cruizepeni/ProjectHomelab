

from __future__ import annotations

from StatMonitorOutput import print_raw

import copy
import ctypes
import ctypes.wintypes as wintypes
import json
import logging
import os
import re
import socket
import threading
import time
import uuid
from typing import Any, Callable

try:
	import psutil
except ImportError:
	psutil = None


LOGGER = logging.getLogger(__name__)
SAMPLE_INTERVAL_SECONDS = 1.0
TOPOLOGY_INTERVAL_SECONDS = 5.0

_SETTINGS = (
	"Show Individual Network Adapters", "Show Disconnected Network Adapters",
	"Show Virtual Network Adapters", "Show Adapter Name", "Show Connection Type",
	"Show Network Name", "Show IP Address", "Show Link Speed",
	"Show Current Download Speed", "Show Current Upload Speed", "Show Total Downloaded",
	"Show Total Uploaded", "Show WiFi Signal Strength",
)

IF_TYPE_ETHERNET = 6
IF_TYPE_LOOPBACK = 24
IF_TYPE_BLUETOOTH = 32
IF_TYPE_IEEE80211 = 71
IF_TYPE_TUNNEL = 131
IF_TYPE_WWANPP = 243
IF_TYPE_WWANPP2 = 244
MEDIA_WIRELESS_LAN = 1
OPER_UP = 1
MEDIA_CONNECTED = 1
FLAG_HARDWARE = 0x01
FLAG_FILTER = 0x02
FLAG_CONNECTOR = 0x04
FLAG_NOT_MEDIA_CONNECTED = 0x10
FLAG_ENDPOINT = 0x80
LOCAL_CONNECTION_PATTERN = re.compile(r"^Local Area Connection\*\s+\d+$", re.IGNORECASE)



INTERNAL_ADAPTER_HINTS = (
	"wfp native mac layer lightweight filter",
	"wfp 802.3 mac layer lightweight filter",
	"qos packet scheduler",
	"native wifi filter driver",
	"virtual wifi filter driver",
	"kernel debugger",
	"loopback pseudo-interface",
	"teredo tunneling pseudo-interface",
	"microsoft ip-https platform interface",
	"6to4 adapter",
	"isatap",
)



VIRTUAL_ADAPTER_HINTS = (
	"wi-fi direct",
	"wifi direct",
	"hosted network",
	"hyper-v",
	"vmware",
	"virtualbox",
	"wireguard",
	"openvpn",
	"tailscale",
	"zerotier",
	"vpn",
	"tap adapter",
	"tap-windows",
	"tun adapter",
)


class GUID(ctypes.Structure):
	_fields_ = [
		("Data1", wintypes.ULONG),
		("Data2", ctypes.c_ushort),
		("Data3", ctypes.c_ushort),
		("Data4", ctypes.c_ubyte * 8),
	]


class NET_LUID(ctypes.Union):
	_fields_ = [("Value", ctypes.c_ulonglong)]


class MIB_IF_ROW2(ctypes.Structure):
	_fields_ = [
		("InterfaceLuid", NET_LUID), ("InterfaceIndex", wintypes.ULONG), ("InterfaceGuid", GUID),
		("Alias", wintypes.WCHAR * 257), ("Description", wintypes.WCHAR * 257),
		("PhysicalAddressLength", wintypes.ULONG), ("PhysicalAddress", ctypes.c_ubyte * 32),
		("PermanentPhysicalAddress", ctypes.c_ubyte * 32), ("Mtu", wintypes.ULONG),
		("Type", wintypes.ULONG), ("TunnelType", wintypes.ULONG), ("MediaType", wintypes.ULONG),
		("PhysicalMediumType", wintypes.ULONG), ("AccessType", wintypes.ULONG),
		("DirectionType", wintypes.ULONG), ("InterfaceAndOperStatusFlags", ctypes.c_ubyte),
		("OperStatus", wintypes.ULONG), ("AdminStatus", wintypes.ULONG),
		("MediaConnectState", wintypes.ULONG), ("NetworkGuid", GUID), ("ConnectionType", wintypes.ULONG),
		("TransmitLinkSpeed", ctypes.c_ulonglong), ("ReceiveLinkSpeed", ctypes.c_ulonglong),
		("InOctets", ctypes.c_ulonglong), ("InUcastPkts", ctypes.c_ulonglong),
		("InNUcastPkts", ctypes.c_ulonglong), ("InDiscards", ctypes.c_ulonglong),
		("InErrors", ctypes.c_ulonglong), ("InUnknownProtos", ctypes.c_ulonglong),
		("InUcastOctets", ctypes.c_ulonglong), ("InMulticastOctets", ctypes.c_ulonglong),
		("InBroadcastOctets", ctypes.c_ulonglong), ("OutOctets", ctypes.c_ulonglong),
		("OutUcastPkts", ctypes.c_ulonglong), ("OutNUcastPkts", ctypes.c_ulonglong),
		("OutDiscards", ctypes.c_ulonglong), ("OutErrors", ctypes.c_ulonglong),
		("OutUcastOctets", ctypes.c_ulonglong), ("OutMulticastOctets", ctypes.c_ulonglong),
		("OutBroadcastOctets", ctypes.c_ulonglong), ("OutQLen", ctypes.c_ulonglong),
	]


class MIB_IF_TABLE2(ctypes.Structure):
	_fields_ = [("NumEntries", wintypes.ULONG), ("Table", MIB_IF_ROW2 * 1)]


class WLAN_INTERFACE_INFO(ctypes.Structure):
	_fields_ = [("InterfaceGuid", GUID), ("strInterfaceDescription", wintypes.WCHAR * 256), ("isState", wintypes.DWORD)]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
	_fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD), ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]


class DOT11_SSID(ctypes.Structure):
	_fields_ = [("uSSIDLength", wintypes.ULONG), ("ucSSID", ctypes.c_ubyte * 32)]


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
	_fields_ = [
		("dot11Ssid", DOT11_SSID), ("dot11BssType", wintypes.ULONG),
		("dot11Bssid", ctypes.c_ubyte * 6), ("dot11PhyType", wintypes.ULONG),
		("uDot11PhyIndex", wintypes.ULONG), ("wlanSignalQuality", wintypes.ULONG),
		("ulRxRate", wintypes.ULONG), ("ulTxRate", wintypes.ULONG),
	]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
	_fields_ = [
		("isState", wintypes.ULONG), ("wlanConnectionMode", wintypes.ULONG),
		("strProfileName", wintypes.WCHAR * 256), ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
	]


class StatMonitorNetwork:


	def __init__(self):
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._adapters: dict[str, dict[str, Any]] = {}
		self._live: dict[str, dict[str, Any]] = {}
		self._baselines: dict[str, tuple[int, int, float]] = {}
		self._running = False
		self._stop_event: threading.Event | None = None
		self._thread: threading.Thread | None = None
		self._last_topology_refresh = 0.0
		self._provider_warnings: set[str] = set()
		self._logged_first_telemetry = False
		self._wlan_handle: Any = None

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
			self._baselines = {}
			self._live = {}
			self._logged_first_telemetry = False
			settings = dict(self._settings)
		self._refresh_topology(settings)
		self._reconcile_wlan(settings)
		self._reconcile_worker(settings)
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
			self._baselines = {}
			self._stop_event = None
			self._close_wlan_locked()
		self._notify()

	def is_running(self) -> bool:
		with self._lock:
			return self._running

	def update_settings(self, settings: dict[str, bool]) -> None:
		if not isinstance(settings, dict):
			raise ValueError("Network settings must be an object")
		with self._lock:
			self._settings = {key: bool(settings.get(key, False)) for key in _SETTINGS}
			running = self._running
			current = dict(self._settings)
		if not running:
			return
		self._reconcile_wlan(current)
		self._reconcile_worker(current)
		self._notify()

	def get_latest(self) -> dict:
		with self._lock:
			settings = dict(self._settings)



			display_adapters = [
				self._filtered_adapter(adapter, settings)
				for adapter in self._eligible_adapters(settings)
			]





			physical_adapters = [
				self._filtered_adapter(adapter, settings)
				for adapter in self._adapters.values()
				if adapter.get("adapter_class") == "physical"
				and adapter.get("connected", False)
			]

			hardware: dict[str, Any] = {}
			live: dict[str, Any] = {}

			if settings.get("Show Individual Network Adapters"):
				hardware["adapters"] = [item[0] for item in display_adapters]
			else:
				hardware.update(self._combined_hardware(display_adapters, settings))

			live.update(self._combined_live(physical_adapters, settings))

			if settings.get("Show Individual Network Adapters"):
				live["adapters"] = [item[1] for item in display_adapters]

			return {
				"hardware": copy.deepcopy(hardware),
				"live": copy.deepcopy(live),
			}


	def get_metric_snapshot(self) -> dict[str, Any]:

		latest = self.get_latest()
		hardware = latest.get("hardware", {})
		live = latest.get("live", {})

		hardware_adapters = hardware.get("adapters") if isinstance(hardware.get("adapters"), list) else []
		live_adapters = live.get("adapters") if isinstance(live.get("adapters"), list) else []
		live_by_id = {
			entry.get("adapter_id"): entry
			for entry in live_adapters
			if isinstance(entry, dict) and entry.get("adapter_id")
		}

		adapters = []
		for hardware_entry in hardware_adapters:
			if not isinstance(hardware_entry, dict):
				continue
			adapter_id = hardware_entry.get("adapter_id")
			live_entry = live_by_id.get(adapter_id, {})

			ip_addresses = []
			for address in hardware_entry.get("ip_addresses", []) or []:
				if not isinstance(address, dict):
					continue
				item = {}
				if address.get("family") is not None:
					item["Network_IP_Family"] = address.get("family")
				if address.get("address") is not None:
					item["Network_IP_Address"] = address.get("address")
				if item:
					ip_addresses.append(item)

			link_speed = hardware_entry.get("link_speed") if isinstance(hardware_entry.get("link_speed"), dict) else {}
			adapters.append({
				"Network_Adapter_ID": adapter_id,
				"Network_Adapter_Name": hardware_entry.get("name"),
				"Network_Adapter_State": "connected" if hardware_entry.get("connected") else "disconnected",
				"Network_Adapter_Type": hardware_entry.get("connection_type"),
				"Network_Adapter_Is_Virtual": bool(hardware_entry.get("is_virtual", False)),
				"Network_Adapter_Network_Name": hardware_entry.get("network_name"),
				"Network_Adapter_IP_Addresses": ip_addresses,
				"Network_Adapter_Receive_Link_Speed": link_speed.get("receive_bps"),
				"Network_Adapter_Transmit_Link_Speed": link_speed.get("transmit_bps"),
				"Network_Adapter_Download_Speed": live_entry.get("download_bytes_per_sec"),
				"Network_Adapter_Upload_Speed": live_entry.get("upload_bytes_per_sec"),
				"Network_Adapter_Total_Downloaded": live_entry.get("total_received_bytes"),
				"Network_Adapter_Total_Uploaded": live_entry.get("total_sent_bytes"),
				"Network_Adapter_WiFi_Signal_Strength": live_entry.get("signal_quality_percent"),
			})

		return {
			"Network_Download_Speed": live.get("download_bytes_per_sec"),
			"Network_Upload_Speed": live.get("upload_bytes_per_sec"),
			"Network_Total_Downloaded": live.get("total_received_bytes"),
			"Network_Total_Uploaded": live.get("total_sent_bytes"),
			"Network_WiFi_Signal_Strength": live.get("signal_quality_percent"),
			"Network_Individual_Adapters": adapters,
		}

	def _print_network_module_block(self) -> None:
		metrics = self.get_metric_snapshot()
		with self._lock:
			settings = dict(self._settings)

		def format_bytes(value: Any) -> str:
			if value is None:
				return "Unavailable"
			try:
				number = float(value)
			except (TypeError, ValueError):
				return str(value)
			units = ("B", "KiB", "MiB", "GiB", "TiB")
			index = 0
			while abs(number) >= 1024.0 and index < len(units) - 1:
				number /= 1024.0
				index += 1
			return f"{number:.1f} {units[index]}"

		def format_bytes_per_second(value: Any) -> str:
			return "Unavailable" if value is None else f"{format_bytes(value)}/s"

		def format_bits_per_second(value: Any) -> str:
			if value is None:
				return "Unavailable"
			try:
				number = float(value)
			except (TypeError, ValueError):
				return str(value)
			units = ("bps", "Kbps", "Mbps", "Gbps", "Tbps")
			index = 0
			while abs(number) >= 1000.0 and index < len(units) - 1:
				number /= 1000.0
				index += 1
			return f"{int(number)} {units[index]}" if index == 0 else f"{number:.1f} {units[index]}"

		def format_percent(value: Any) -> str:
			return "Unavailable" if value is None else f"{value}%"

		lines = ["-" * 60, "Network_Module"]
		for metric_id, formatter in (
			("Network_Download_Speed", format_bytes_per_second),
			("Network_Upload_Speed", format_bytes_per_second),
			("Network_Total_Downloaded", format_bytes),
			("Network_Total_Uploaded", format_bytes),
			("Network_WiFi_Signal_Strength", format_percent),
		):
			value = metrics.get(metric_id)
			if value is not None:
				lines.append(f"{metric_id}: {formatter(value)}")

		if settings.get("Show Individual Network Adapters", False):
			adapters = metrics.get("Network_Individual_Adapters", [])
			adapters = adapters if isinstance(adapters, list) else []
			lines.append(f"Network_Individual_Adapters: {len(adapters)}")

			for index, adapter in enumerate(adapters, 1):
				lines.append(f"  [{index}]")
				for metric_id in (
					"Network_Adapter_ID",
					"Network_Adapter_Name",
					"Network_Adapter_State",
					"Network_Adapter_Type",
					"Network_Adapter_Is_Virtual",
					"Network_Adapter_Network_Name",
				):
					value = adapter.get(metric_id)
					if value is None:
						continue
					if metric_id == "Network_Adapter_State":
						value = str(value).replace("_", " ").title()
					lines.append(f"    {metric_id}: {value}")

				ip_addresses = adapter.get("Network_Adapter_IP_Addresses", [])
				if ip_addresses:
					lines.append(f"    Network_Adapter_IP_Addresses: {len(ip_addresses)}")
					for ip_index, address in enumerate(ip_addresses, 1):
						lines.append(f"      [{ip_index}]")
						if address.get("Network_IP_Family") is not None:
							lines.append(f"        Network_IP_Family: {address['Network_IP_Family']}")
						if address.get("Network_IP_Address") is not None:
							lines.append(f"        Network_IP_Address: {address['Network_IP_Address']}")

				for metric_id, formatter in (
					("Network_Adapter_Receive_Link_Speed", format_bits_per_second),
					("Network_Adapter_Transmit_Link_Speed", format_bits_per_second),
					("Network_Adapter_Download_Speed", format_bytes_per_second),
					("Network_Adapter_Upload_Speed", format_bytes_per_second),
					("Network_Adapter_Total_Downloaded", format_bytes),
					("Network_Adapter_Total_Uploaded", format_bytes),
					("Network_Adapter_WiFi_Signal_Strength", format_percent),
				):
					value = adapter.get(metric_id)
					if value is not None:
						lines.append(f"    {metric_id}: {formatter(value)}")

		lines.append("-" * 60)
		print_raw("\n".join(lines))


	def _eligible_adapters(self, settings: dict[str, bool]) -> list[dict[str, Any]]:
		return [
			adapter
			for adapter in self._adapters.values()
			if adapter.get("adapter_class") != "internal"
			and (
				settings.get("Show Virtual Network Adapters")
				or adapter.get("adapter_class") != "virtual"
			)
			and (
				settings.get("Show Disconnected Network Adapters")
				or adapter.get("connected", False)
			)
		]

	def _filtered_adapter(self, adapter: dict[str, Any], settings: dict[str, bool]) -> tuple[dict, dict]:
		hardware = {
			"adapter_id": adapter["adapter_id"],
			"connected": adapter["connected"],
			"is_virtual": adapter.get("adapter_class") == "virtual",
		}
		if settings.get("Show Adapter Name"):
			hardware["name"] = adapter["name"]
		if settings.get("Show Connection Type"):
			hardware["connection_type"] = adapter["connection_type"]
		if settings.get("Show Network Name") and adapter.get("network_name"):
			hardware["network_name"] = adapter["network_name"]
		if settings.get("Show IP Address") and adapter.get("ip_addresses"):
			hardware["ip_addresses"] = copy.deepcopy(adapter["ip_addresses"])
		if settings.get("Show Link Speed"):
			hardware["link_speed"] = {"receive_bps": adapter["receive_bps"], "transmit_bps": adapter["transmit_bps"]}
		live = {"adapter_id": adapter["adapter_id"]}
		values = self._live.get(adapter["adapter_id"], {})
		for key, setting in (("download_bytes_per_sec", "Show Current Download Speed"),
				("upload_bytes_per_sec", "Show Current Upload Speed"),
				("total_received_bytes", "Show Total Downloaded"),
				("total_sent_bytes", "Show Total Uploaded"),
				("signal_quality_percent", "Show WiFi Signal Strength")):
			if settings.get(setting) and key in values:
				live[key] = values[key]
		return hardware, live

	def _combined_hardware(self, adapters: list[tuple[dict, dict]], settings: dict[str, bool]) -> dict[str, Any]:
		result = {}
		if settings.get("Show Adapter Name"):
			result["adapter_names"] = self._unique(item[0].get("name") for item in adapters)
		if settings.get("Show Connection Type"):
			result["connection_types"] = self._unique(item[0].get("connection_type") for item in adapters)
		if settings.get("Show Network Name"):
			result["network_names"] = self._unique(item[0].get("network_name") for item in adapters)
		if settings.get("Show IP Address"):
			result["ip_addresses"] = self._unique_dicts(item[0].get("ip_addresses", []))
		if settings.get("Show Link Speed"):
			result["link_speeds"] = [{"adapter_id": item[0]["adapter_id"], "receive_bps": item[0]["link_speed"]["receive_bps"], "transmit_bps": item[0]["link_speed"]["transmit_bps"]} for item in adapters]
		return result

	def _combined_live(self, adapters: list[tuple[dict, dict]], settings: dict[str, bool]) -> dict[str, Any]:






		result = {}
		for key, setting in (("download_bytes_per_sec", "Show Current Download Speed"), ("upload_bytes_per_sec", "Show Current Upload Speed"), ("total_received_bytes", "Show Total Downloaded"), ("total_sent_bytes", "Show Total Uploaded")):
			if settings.get(setting):
				values = [item[1].get(key, 0) for item in adapters]
				if values and (key not in ("download_bytes_per_sec", "upload_bytes_per_sec") or any(key in item[1] for item in adapters)):
					result[key] = sum(values)
		if settings.get("Show WiFi Signal Strength"):
			signals = [item[1]["signal_quality_percent"] for item in adapters if "signal_quality_percent" in item[1]]
			if signals:
				result["signal_quality_percent"] = max(signals)
		return result

	def _refresh_topology(self, settings: dict[str, bool]) -> None:
		adapters = self._read_native_adapters()
		if adapters is None:
			adapters = self._read_psutil_adapters()
		addresses = self._read_addresses()
		for adapter in adapters:
			adapter["ip_addresses"] = addresses.get(adapter["name"], [])
		with self._lock:
			previous = self._adapters
			self._adapters = {adapter["adapter_id"]: adapter for adapter in adapters}
			self._last_topology_refresh = time.monotonic()
			for adapter_id in list(self._baselines):
				if adapter_id not in self._adapters:
					del self._baselines[adapter_id]
		if previous != self._adapters:
			self._notify()

	@staticmethod
	def _guid_string(guid: GUID) -> str:
		return "{" + str(uuid.UUID(fields=(
			int(guid.Data1), int(guid.Data2), int(guid.Data3),
			int(guid.Data4[0]), int(guid.Data4[1]),
			int.from_bytes(bytes(guid.Data4[2:]), "big"),
		))).upper() + "}"

	def _read_native_adapters(self) -> list[dict[str, Any]] | None:
		if os.name != "nt":
			return None
		try:
			iphlpapi = ctypes.WinDLL("iphlpapi.dll")
			get_table = iphlpapi.GetIfTable2
			get_table.argtypes = [ctypes.POINTER(ctypes.POINTER(MIB_IF_TABLE2))]
			get_table.restype = wintypes.ULONG
			free_table = iphlpapi.FreeMibTable
			free_table.argtypes = [ctypes.c_void_p]
			free_table.restype = None
			table_pointer = ctypes.POINTER(MIB_IF_TABLE2)()
			status = get_table(ctypes.byref(table_pointer))
			if status != 0:
				self._warn_once("iphelper", "Windows IP Helper GetIfTable2 failed: %s", status)
				return None
			try:
				count = table_pointer.contents.NumEntries
				row_address = ctypes.addressof(table_pointer.contents) + MIB_IF_TABLE2.Table.offset
				rows = (MIB_IF_ROW2 * count).from_address(row_address)
				normalized = [self._normalize_row(row) for row in rows]
				if any(not self._is_sane_adapter(adapter) for adapter in normalized):
					self._warn_once("iphelper-invalid", "Windows IP Helper returned unusable adapter data; using psutil fallback")
					return None
				return normalized
			finally:
				free_table(table_pointer)
		except Exception as error:
			self._warn_once("iphelper", "Windows IP Helper unavailable; using psutil fallback: %s", error)
			return None

	def _normalize_row(self, row: MIB_IF_ROW2) -> dict[str, Any]:
		adapter_id = self._guid_string(row.InterfaceGuid)
		flags = int(row.InterfaceAndOperStatusFlags)
		alias = str(row.Alias).strip()
		description = str(row.Description).strip()
		adapter_class = self._adapter_class_from_values(alias, description, int(row.Type), int(row.TunnelType), flags)
		connected = int(row.OperStatus) == OPER_UP and int(row.MediaConnectState) != 2 and not (flags & FLAG_NOT_MEDIA_CONNECTED)
		connection_type = self._connection_type(int(row.Type), int(row.PhysicalMediumType), int(row.TunnelType))
		if "bluetooth" in f"{alias} {description}".lower():
			connection_type = "Bluetooth PAN"
		return {
			"adapter_id": adapter_id, "name": alias or description or adapter_id,
			"description": description, "type": int(row.Type), "physical_medium": int(row.PhysicalMediumType),
			"adapter_class": adapter_class, "is_virtual": adapter_class == "virtual",
			"is_hardware": adapter_class == "physical", "connected": connected,
			"connection_type": connection_type,
			"receive_bps": int(row.ReceiveLinkSpeed), "transmit_bps": int(row.TransmitLinkSpeed),
			"received_bytes": int(row.InOctets), "sent_bytes": int(row.OutOctets),
		}

	@staticmethod
	def _is_sane_adapter(adapter: dict[str, Any]) -> bool:
		return bool(adapter.get("adapter_id") and adapter.get("name") and isinstance(adapter.get("type"), int)
			and isinstance(adapter.get("connected"), bool) and adapter.get("receive_bps", -1) >= 0
			and adapter.get("transmit_bps", -1) >= 0 and adapter.get("received_bytes", -1) >= 0
			and adapter.get("sent_bytes", -1) >= 0)

	@staticmethod
	def _adapter_class_from_values(alias: str, description: str, interface_type: int, tunnel_type: int, flags: int) -> str:
		combined = f"{alias} {description}".lower()



		if flags & (FLAG_FILTER | FLAG_ENDPOINT):
			return "internal"
		if any(hint in combined for hint in INTERNAL_ADAPTER_HINTS):
			return "internal"
		if interface_type == IF_TYPE_LOOPBACK:
			return "internal"



		if any(hint in combined for hint in VIRTUAL_ADAPTER_HINTS):
			return "virtual"




		if interface_type == IF_TYPE_TUNNEL or tunnel_type:
			return "internal"


		if LOCAL_CONNECTION_PATTERN.fullmatch(alias):
			return "virtual"

		return "physical"

	@staticmethod
	def _connection_type(interface_type: int, physical_medium: int, tunnel_type: int) -> str:
		if interface_type == IF_TYPE_IEEE80211 or physical_medium == MEDIA_WIRELESS_LAN:
			return "Wi-Fi"
		if interface_type == IF_TYPE_ETHERNET:
			return "Ethernet"
		if interface_type == IF_TYPE_BLUETOOTH:
			return "Bluetooth PAN"
		if interface_type == IF_TYPE_LOOPBACK:
			return "Loopback"
		if interface_type == IF_TYPE_TUNNEL or tunnel_type:
			return "Tunnel"
		if interface_type in (IF_TYPE_WWANPP, IF_TYPE_WWANPP2):
			return "Cellular"
		return "Other"

	def _read_psutil_adapters(self) -> list[dict[str, Any]]:
		if psutil is None:
			self._warn_once("psutil", "Network providers unavailable: psutil is not installed")
			return []
		try:
			stats = psutil.net_if_stats()
			counters = psutil.net_io_counters(pernic=True, nowrap=True)
			result = []
			for name, stat in stats.items():
				counter = counters.get(name)
				adapter_id = "psutil:" + name
				adapter_class = self._adapter_class_from_values(name, name, 0, 0, 0)
				connection_type = "Bluetooth PAN" if "bluetooth" in name.lower() else "Other"
				result.append({
					"adapter_id": adapter_id, "name": name, "description": name, "type": 0, "physical_medium": 0,
					"adapter_class": adapter_class, "is_virtual": adapter_class == "virtual",
					"is_hardware": adapter_class == "physical", "connected": bool(stat.isup), "connection_type": connection_type,
					"receive_bps": max(0, int(stat.speed) * 1_000_000), "transmit_bps": max(0, int(stat.speed) * 1_000_000),
					"received_bytes": int(counter.bytes_recv) if counter else 0, "sent_bytes": int(counter.bytes_sent) if counter else 0,
				})
			return result
		except Exception as error:
			self._warn_once("psutil", "Network psutil fallback unavailable: %s", error)
			return []

	@staticmethod
	def _read_addresses() -> dict[str, list[dict[str, str]]]:
		if psutil is None:
			return {}
		try:
			result = {}
			for name, addresses in psutil.net_if_addrs().items():
				values = []
				for address in addresses:
					family = "IPv4" if address.family == socket.AF_INET else "IPv6" if address.family == socket.AF_INET6 else None
					if family and address.address and not any(item["address"] == address.address for item in values):
						values.append({"family": family, "address": address.address.split("%", 1)[0]})
				result[name] = values
			return result
		except Exception:
			return {}

	def _reconcile_wlan(self, settings: dict[str, bool]) -> None:
		needs_wlan = settings.get("Show Network Name", False) or settings.get("Show WiFi Signal Strength", False)
		with self._lock:
			if needs_wlan and self._wlan_handle is None:
				self._open_wlan_locked()
			elif not needs_wlan:
				self._close_wlan_locked()
		if needs_wlan and self._wlan_handle is not None:
			self._refresh_wlan()

	def _open_wlan_locked(self) -> None:
		if os.name != "nt":
			return
		try:
			wlanapi = ctypes.WinDLL("wlanapi.dll")
			handle = wintypes.HANDLE()
			version = wintypes.DWORD()
			status = wlanapi.WlanOpenHandle(2, None, ctypes.byref(version), ctypes.byref(handle))
			if status != 0:
				self._warn_once("wlan", "Windows WLAN provider unavailable: %s", status)
				return
			self._wlan_handle = (wlanapi, handle)
		except Exception as error:
			self._warn_once("wlan", "Windows WLAN provider unavailable: %s", error)

	def _close_wlan_locked(self) -> None:
		handle_data = self._wlan_handle
		self._wlan_handle = None
		if handle_data:
			try:
				handle_data[0].WlanCloseHandle(handle_data[1], None)
			except Exception:
				pass

	def _refresh_wlan(self) -> None:
		if not self._wlan_handle:
			return
		wlanapi, handle = self._wlan_handle
		interface_list = ctypes.c_void_p()
		try:
			wlanapi.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
			wlanapi.WlanEnumInterfaces.restype = wintypes.DWORD
			status = wlanapi.WlanEnumInterfaces(handle, None, ctypes.byref(interface_list))
			if status != 0:
				return
			items = ctypes.cast(interface_list, ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)).contents
			count = int(items.dwNumberOfItems)
			interface_array_type = WLAN_INTERFACE_INFO * max(1, count)
			interface_array = interface_array_type.from_address(ctypes.addressof(items.InterfaceInfo))
			for index in range(count):
				info = interface_array[index]
				adapter_id = self._guid_string(info.InterfaceGuid)
				if adapter_id not in self._adapters:
					continue
				attributes = ctypes.c_void_p()
				data_size = wintypes.DWORD()
				opcode = 7
				wlanapi.WlanQueryInterface.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
				wlanapi.WlanQueryInterface.restype = wintypes.DWORD
				query_status = wlanapi.WlanQueryInterface(handle, ctypes.byref(info.InterfaceGuid), opcode, None, ctypes.byref(data_size), ctypes.byref(attributes), None)
				if query_status == 5:
					self._warn_once("wlan-privacy", "Wi-Fi connection details unavailable due to Windows privacy/location permission")
					continue
				if query_status != 0 or not attributes:
					continue
				try:
					connection = ctypes.cast(attributes, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)).contents
					ssid = bytes(connection.wlanAssociationAttributes.dot11Ssid.ucSSID[:connection.wlanAssociationAttributes.dot11Ssid.uSSIDLength]).decode("utf-8", "replace")
					quality = int(connection.wlanAssociationAttributes.wlanSignalQuality)
					with self._lock:
						if ssid:
							self._adapters[adapter_id]["network_name"] = ssid
						if 0 <= quality <= 100:
							self._live.setdefault(adapter_id, {})["signal_quality_percent"] = quality
				finally:
					wlanapi.WlanFreeMemory(attributes)
		finally:
			if interface_list:
				wlanapi.WlanFreeMemory(interface_list)

	def _reconcile_worker(self, settings: dict[str, bool]) -> None:
		needs_live = any(settings.get(key, False) for key in (
			"Show Current Download Speed", "Show Current Upload Speed", "Show Total Downloaded",
			"Show Total Uploaded", "Show WiFi Signal Strength"))
		needs_topology = any(settings.get(key, False) for key in (
			"Show Individual Network Adapters", "Show Disconnected Network Adapters",
			"Show Virtual Network Adapters", "Show Adapter Name", "Show Connection Type",
			"Show Network Name", "Show IP Address", "Show Link Speed"))
		needs_worker = needs_live or needs_topology
		with self._lock:
			if not self._running:
				return
			if needs_worker and self._thread is None:
				stop_event = threading.Event()
				self._stop_event = stop_event
				self._thread = threading.Thread(target=self._sample_loop, args=(stop_event,), name="StatMonitorNetwork", daemon=True)
				self._thread.start()
			elif not needs_worker and self._thread is not None:
				self._thread = None
				if self._stop_event is not None:
					self._stop_event.set()

	def _sample_loop(self, stop_event: threading.Event) -> None:
		while not stop_event.is_set():
			with self._lock:
				if not self._running or self._stop_event is not stop_event:
					return
				settings = dict(self._settings)
			if time.monotonic() - self._last_topology_refresh >= TOPOLOGY_INTERVAL_SECONDS:
				self._refresh_topology(settings)
			if settings.get("Show Network Name") or settings.get("Show WiFi Signal Strength"):
				self._refresh_wlan()
			if any(settings.get(key, False) for key in ("Show Current Download Speed", "Show Current Upload Speed", "Show Total Downloaded", "Show Total Uploaded", "Show WiFi Signal Strength")):
				self._sample_counters(settings)
			wait_seconds = SAMPLE_INTERVAL_SECONDS if any(settings.get(key, False) for key in ("Show Current Download Speed", "Show Current Upload Speed", "Show Total Downloaded", "Show Total Uploaded", "Show WiFi Signal Strength")) else TOPOLOGY_INTERVAL_SECONDS
			if stop_event.wait(wait_seconds):
				return

	def _sample_counters(self, settings: dict[str, bool]) -> None:
		now = time.monotonic()
		adapters = self._read_native_adapters()
		if adapters is None:
			adapters = self._read_psutil_adapters()

		has_counter_delta = False
		with self._lock:
			for current in adapters:
				adapter_id = current["adapter_id"]
				previous = self._baselines.get(adapter_id)
				self._adapters[adapter_id] = {**self._adapters.get(adapter_id, {}), **current}

				if (
					previous is None
					or current["received_bytes"] < previous[0]
					or current["sent_bytes"] < previous[1]
					or now <= previous[2]
				):
					self._baselines[adapter_id] = (
						current["received_bytes"],
						current["sent_bytes"],
						now,
					)
					continue

				delta = now - previous[2]
				self._baselines[adapter_id] = (
					current["received_bytes"],
					current["sent_bytes"],
					now,
				)
				self._live.setdefault(adapter_id, {}).update({
					"download_bytes_per_sec": max(
						0,
						int((current["received_bytes"] - previous[0]) / delta),
					),
					"upload_bytes_per_sec": max(
						0,
						int((current["sent_bytes"] - previous[1]) / delta),
					),
					"total_received_bytes": current["received_bytes"],
					"total_sent_bytes": current["sent_bytes"],
				})
				has_counter_delta = True

			should_notify = bool(self._live)




		if has_counter_delta:
			self._log_first_telemetry()

		if should_notify:
			self._notify()

	def _log_first_telemetry(self) -> None:
		with self._lock:
			if self._logged_first_telemetry:
				return
			eligible_count = len(self._eligible_adapters(self._settings))
			if eligible_count == 0:
				self._warn_once("no-eligible", "Network telemetry has no eligible adapters after current filters")
				return
			self._logged_first_telemetry = True
		self._print_network_module_block()

	def _notify(self) -> None:
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				LOGGER.exception("StatMonitor Network listener failed")

	@staticmethod
	def _unique(values) -> list[Any]:
		result = []
		for value in values:
			if value is not None and value not in result:
				result.append(value)
		return result

	@staticmethod
	def _unique_dicts(values) -> list[dict]:
		result = []
		for value in values:
			if value not in result:
				result.append(value)
		return result

	def _warn_once(self, key: str, message: str, *args) -> None:
		with self._lock:
			if key in self._provider_warnings:
				return
			self._provider_warnings.add(key)
		LOGGER.warning(message, *args)
