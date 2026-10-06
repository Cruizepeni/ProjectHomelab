from __future__ import annotations

import copy
import ctypes
import ctypes.wintypes as wintypes
import html
import threading
import time
import uuid
from typing import Any, Callable

from StatMonitorDeviceControls import WIFI_COMMANDS
from .StatMonitorRadioControl import get_radio_state, set_radio_enabled


SAMPLE_INTERVAL_SECONDS = 3.0
WLAN_MAX_NAME_LENGTH = 256
WLAN_MAX_PHY_TYPE_NUMBER = 8
WLAN_AVAILABLE_NETWORK_CONNECTED = 0x00000001
WLAN_AVAILABLE_NETWORK_HAS_PROFILE = 0x00000002
WLAN_PROFILE_USER = 0x00000002
WLAN_CONNECTION_MODE_PROFILE = 0
DOT11_BSS_TYPE_INFRASTRUCTURE = 1
WLAN_INTF_OPCODE_CURRENT_CONNECTION = 7
WLAN_INTERFACE_STATE_CONNECTED = 1
ERROR_SUCCESS = 0
_SETTINGS = (
	"Show WiFi Adapter",
	"Show Current Network",
	"Show Available Networks",
	"Show Saved Networks",
	"Show Signal Strength",
	"Show Link Speed",
)

class GUID(ctypes.Structure):
	_fields_ = [
		("Data1", wintypes.ULONG),
		("Data2", ctypes.c_ushort),
		("Data3", ctypes.c_ushort),
		("Data4", ctypes.c_ubyte * 8),
	]


class WLAN_INTERFACE_INFO(ctypes.Structure):
	_fields_ = [
		("InterfaceGuid", GUID),
		("strInterfaceDescription", wintypes.WCHAR * WLAN_MAX_NAME_LENGTH),
		("isState", wintypes.DWORD),
	]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
	_fields_ = [
		("dwNumberOfItems", wintypes.DWORD),
		("dwIndex", wintypes.DWORD),
		("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
	]


class DOT11_SSID(ctypes.Structure):
	_fields_ = [
		("uSSIDLength", wintypes.ULONG),
		("ucSSID", ctypes.c_ubyte * 32),
	]


class WLAN_AVAILABLE_NETWORK(ctypes.Structure):
	_fields_ = [
		("strProfileName", wintypes.WCHAR * WLAN_MAX_NAME_LENGTH),
		("dot11Ssid", DOT11_SSID),
		("dot11BssType", wintypes.ULONG),
		("uNumberOfBssids", wintypes.ULONG),
		("bNetworkConnectable", wintypes.BOOL),
		("wlanNotConnectableReason", wintypes.ULONG),
		("uNumberOfPhyTypes", wintypes.ULONG),
		("dot11PhyTypes", wintypes.ULONG * WLAN_MAX_PHY_TYPE_NUMBER),
		("bMorePhyTypes", wintypes.BOOL),
		("wlanSignalQuality", wintypes.ULONG),
		("bSecurityEnabled", wintypes.BOOL),
		("dot11DefaultAuthAlgorithm", wintypes.ULONG),
		("dot11DefaultCipherAlgorithm", wintypes.ULONG),
		("dwFlags", wintypes.DWORD),
		("dwReserved", wintypes.DWORD),
	]


class WLAN_AVAILABLE_NETWORK_LIST(ctypes.Structure):
	_fields_ = [
		("dwNumberOfItems", wintypes.DWORD),
		("dwIndex", wintypes.DWORD),
		("Network", WLAN_AVAILABLE_NETWORK * 1),
	]


class WLAN_PROFILE_INFO(ctypes.Structure):
	_fields_ = [
		("strProfileName", wintypes.WCHAR * WLAN_MAX_NAME_LENGTH),
		("dwFlags", wintypes.DWORD),
	]


class WLAN_PROFILE_INFO_LIST(ctypes.Structure):
	_fields_ = [
		("dwNumberOfItems", wintypes.DWORD),
		("dwIndex", wintypes.DWORD),
		("ProfileInfo", WLAN_PROFILE_INFO * 1),
	]


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
	_fields_ = [
		("dot11Ssid", DOT11_SSID),
		("dot11BssType", wintypes.ULONG),
		("dot11Bssid", ctypes.c_ubyte * 6),
		("dot11PhyType", wintypes.ULONG),
		("uDot11PhyIndex", wintypes.ULONG),
		("wlanSignalQuality", wintypes.ULONG),
		("ulRxRate", wintypes.ULONG),
		("ulTxRate", wintypes.ULONG),
	]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
	_fields_ = [
		("bSecurityEnabled", wintypes.BOOL),
		("bOneXEnabled", wintypes.BOOL),
		("dot11AuthAlgorithm", wintypes.ULONG),
		("dot11CipherAlgorithm", wintypes.ULONG),
	]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
	_fields_ = [
		("isState", wintypes.ULONG),
		("wlanConnectionMode", wintypes.ULONG),
		("strProfileName", wintypes.WCHAR * WLAN_MAX_NAME_LENGTH),
		("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
		("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES),
	]


class WLAN_CONNECTION_PARAMETERS(ctypes.Structure):
	_fields_ = [
		("wlanConnectionMode", wintypes.ULONG),
		("strProfile", wintypes.LPCWSTR),
		("pDot11Ssid", ctypes.POINTER(DOT11_SSID)),
		("pDesiredBssidList", ctypes.c_void_p),
		("dot11BssType", wintypes.ULONG),
		("dwFlags", wintypes.DWORD),
	]


class StatMonitorWiFi:
	def __init__(self):
		self._lock = threading.RLock()
		self._listeners: list[Callable[[dict], None]] = []
		self._settings: dict[str, bool] = {}
		self._running = False
		self._thread: threading.Thread | None = None
		self._stop_event = threading.Event()
		self._hardware: dict[str, Any] = {}
		self._live: dict[str, Any] = {}
		self._warnings: list[dict[str, Any]] = []

	def subscribe(self, listener: Callable[[dict], None]) -> None:
		with self._lock:
			if listener not in self._listeners:
				self._listeners.append(listener)

	def unsubscribe(self, listener: Callable[[dict], None]) -> None:
		with self._lock:
			if listener in self._listeners:
				self._listeners.remove(listener)

	def update_settings(self, settings: dict[str, bool]) -> None:
		with self._lock:
			self._settings = {key: bool((settings or {}).get(key, False)) for key in _SETTINGS}
		if self._running:
			self._refresh_safe()


	def start(self) -> None:
		with self._lock:
			if self._running:
				return
			self._running = True
			self._stop_event.clear()
		self._refresh_safe()
		self._thread = threading.Thread(target=self._loop, name="StatMonitorWiFi", daemon=True)
		self._thread.start()

	def stop(self) -> None:
		with self._lock:
			self._running = False
			self._stop_event.set()
			thread = self._thread
			self._thread = None
		if thread and thread is not threading.current_thread():
			thread.join(timeout=SAMPLE_INTERVAL_SECONDS + 2.0)

	def is_running(self) -> bool:
		with self._lock:
			return self._running

	def get_latest(self) -> dict:
		with self._lock:
			return {
				"hardware": copy.deepcopy(self._hardware),
				"live": copy.deepcopy(self._live),
				"provider": {"name": "Windows Native Wi-Fi", "status": "available" if not self._warnings else "degraded"},
				"warnings": copy.deepcopy(self._warnings),
			}

	def get_metric_snapshot(self) -> dict[str, Any]:
		return self.get_latest()

	def handle_command(self, command: Any, arguments: dict[str, Any] | None = None) -> dict:
		arguments = dict(arguments or {})
		if command not in WIFI_COMMANDS:
			return {"success": False, "error": "unknown_command", "command": command}
		if command == "GetWiFiStatus":
			self._refresh_safe()
			latest = self.get_latest()
			return {"success": True, "command": command, "radio": get_radio_state("wifi"), "hardware": latest["hardware"], "live": latest["live"], "warnings": latest.get("warnings", [])}
		if command == "GetWiFiNetworks":
			return {"success": True, "command": command, "networks": self._read_visible_networks(arguments.get("interface_id"))}
		if command == "GetSavedWiFiNetworks":
			return {"success": True, "command": command, "profiles": self._read_saved_profiles(arguments.get("interface_id"))}
		if command == "ScanWiFi":
			return self._scan(arguments.get("interface_id"))
		if command == "ConnectWiFi":
			return self._connect(arguments)
		if command == "DisconnectWiFi":
			return self._disconnect(arguments.get("interface_id"))
		if command == "ForgetWiFiNetwork":
			return self._forget(arguments)
		if command in {"WiFiOn", "WiFiOff"}:
			result = set_radio_enabled("wifi", command == "WiFiOn")
			return {"command": command, **result}
		return {"success": False, "error": "unknown_command", "command": command}

	def _loop(self) -> None:
		while not self._stop_event.wait(SAMPLE_INTERVAL_SECONDS):
			self._refresh_safe()

	def _refresh_safe(self) -> None:
		try:
			hardware, live = self._collect()
			warnings = []
		except Exception as error:
			hardware, live = {}, {}
			warnings = [{"code": "wifi_provider_error", "message": str(error)}]
		with self._lock:
			self._hardware = hardware
			self._live = live
			self._warnings = warnings
		self._notify()

	def _collect(self) -> tuple[dict[str, Any], dict[str, Any]]:
		settings = dict(self._settings)
		interfaces = self._read_interfaces()
		hardware: dict[str, Any] = {}
		live: dict[str, Any] = {}
		if settings.get("Show WiFi Adapter"):
			hardware["adapters"] = interfaces
		connections = self._read_connections()
		if settings.get("Show Current Network"):
			live["connections"] = connections
		if settings.get("Show Available Networks"):
			hardware["available_networks"] = self._read_visible_networks()
		if settings.get("Show Saved Networks"):
			hardware["saved_networks"] = self._read_saved_profiles()
		return hardware, live

	def _notify(self) -> None:
		latest = self.get_latest()
		with self._lock:
			listeners = list(self._listeners)
		for listener in listeners:
			try:
				listener(latest)
			except Exception:
				pass

	@staticmethod
	def _wlan_api():
		api = ctypes.WinDLL("wlanapi.dll")
		api.WlanOpenHandle.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.HANDLE)]
		api.WlanOpenHandle.restype = wintypes.DWORD
		api.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
		api.WlanCloseHandle.restype = wintypes.DWORD
		api.WlanFreeMemory.argtypes = [ctypes.c_void_p]
		api.WlanFreeMemory.restype = None
		return api

	@classmethod
	def _open(cls):
		api = cls._wlan_api()
		handle = wintypes.HANDLE()
		version = wintypes.DWORD()
		status = api.WlanOpenHandle(2, None, ctypes.byref(version), ctypes.byref(handle))
		if status != ERROR_SUCCESS:
			raise OSError(status, "WlanOpenHandle failed")
		return api, handle

	@staticmethod
	def _interface_state(value: int) -> str:
		return {
			0: "not_ready",
			1: "connected",
			2: "ad_hoc_network_formed",
			3: "disconnecting",
			4: "disconnected",
			5: "associating",
			6: "discovering",
			7: "authenticating",
		}.get(int(value), f"state-{int(value)}")

	@staticmethod
	def _guid_string(guid: GUID) -> str:
		raw = ctypes.string_at(ctypes.byref(guid), ctypes.sizeof(GUID))
		return "{" + str(uuid.UUID(bytes_le=raw)).upper() + "}"

	@staticmethod
	def _ssid(value: DOT11_SSID) -> str:
		length = max(0, min(int(value.uSSIDLength), 32))
		return bytes(value.ucSSID[:length]).decode("utf-8", "replace")

	@staticmethod
	def _auth_name(value: int) -> str:
		return {
			1: "open",
			2: "shared",
			3: "WPA-Enterprise",
			4: "WPA-Personal",
			5: "WPA-None",
			6: "WPA2-Enterprise",
			7: "WPA2-Personal",
			8: "WPA3-Enterprise-192",
			9: "WPA3-Personal",
			10: "OWE",
			11: "WPA3-Enterprise",
		}.get(int(value), f"auth-{int(value)}")

	@staticmethod
	def _cipher_name(value: int) -> str:
		return {
			0x00: "none",
			0x01: "WEP40",
			0x02: "TKIP",
			0x04: "AES",
			0x05: "WEP104",
			0x06: "BIP",
			0x08: "GCMP",
			0x09: "GCMP-256",
			0x0A: "CCMP-256",
		}.get(int(value), f"cipher-{int(value)}")

	@classmethod
	def _enum_interfaces(cls, api, handle) -> list[tuple[GUID, dict[str, Any]]]:
		api.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(WLAN_INTERFACE_INFO_LIST))]
		api.WlanEnumInterfaces.restype = wintypes.DWORD
		pointer = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
		status = api.WlanEnumInterfaces(handle, None, ctypes.byref(pointer))
		if status != ERROR_SUCCESS:
			raise OSError(status, "WlanEnumInterfaces failed")
		try:
			count = int(pointer.contents.dwNumberOfItems)
			base = ctypes.addressof(pointer.contents) + WLAN_INTERFACE_INFO_LIST.InterfaceInfo.offset
			rows = (WLAN_INTERFACE_INFO * count).from_address(base) if count else []
			result = []
			for row in rows:
				raw_guid = ctypes.string_at(ctypes.byref(row.InterfaceGuid), ctypes.sizeof(GUID))
				guid = GUID.from_buffer_copy(raw_guid)
				result.append((guid, {"interface_id": cls._guid_string(guid), "name": str(row.strInterfaceDescription), "state": cls._interface_state(row.isState)}))
			return result
		finally:
			api.WlanFreeMemory(pointer)

	@classmethod
	def _select_interfaces(cls, rows: list[tuple[GUID, dict[str, Any]]], requested: Any) -> list[tuple[GUID, dict[str, Any]]]:
		if requested in (None, "", "all"):
			return rows
		needle = str(requested).strip().casefold()
		selected = [row for row in rows if row[1]["interface_id"].casefold() == needle or row[1]["name"].casefold() == needle]
		if not selected:
			raise ValueError(f"Wi-Fi interface not found: {requested}")
		return selected

	@classmethod
	def _available_for_interface(cls, api, handle, guid: GUID, info: dict[str, Any]) -> list[dict[str, Any]]:
		api.WlanGetAvailableNetworkList.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(WLAN_AVAILABLE_NETWORK_LIST))]
		api.WlanGetAvailableNetworkList.restype = wintypes.DWORD
		pointer = ctypes.POINTER(WLAN_AVAILABLE_NETWORK_LIST)()
		status = api.WlanGetAvailableNetworkList(handle, ctypes.byref(guid), 0, None, ctypes.byref(pointer))
		if status != ERROR_SUCCESS:
			raise OSError(status, "WlanGetAvailableNetworkList failed")
		try:
			count = int(pointer.contents.dwNumberOfItems)
			base = ctypes.addressof(pointer.contents) + WLAN_AVAILABLE_NETWORK_LIST.Network.offset
			rows = (WLAN_AVAILABLE_NETWORK * count).from_address(base) if count else []
			result = []
			for row in rows:
				ssid = cls._ssid(row.dot11Ssid)
				if not ssid:
					continue
				result.append({
					"interface_id": info["interface_id"],
					"interface_name": info["name"],
					"ssid": ssid,
					"profile_name": str(row.strProfileName).strip() or None,
					"signal_quality_percent": int(row.wlanSignalQuality),
					"security_enabled": bool(row.bSecurityEnabled),
					"authentication": cls._auth_name(row.dot11DefaultAuthAlgorithm),
					"authentication_code": int(row.dot11DefaultAuthAlgorithm),
					"cipher": cls._cipher_name(row.dot11DefaultCipherAlgorithm),
					"cipher_code": int(row.dot11DefaultCipherAlgorithm),
					"connected": bool(int(row.dwFlags) & WLAN_AVAILABLE_NETWORK_CONNECTED),
					"has_profile": bool(int(row.dwFlags) & WLAN_AVAILABLE_NETWORK_HAS_PROFILE),
					"connectable": bool(row.bNetworkConnectable),
				})
			return result
		finally:
			api.WlanFreeMemory(pointer)

	@classmethod
	def _profiles_for_interface(cls, api, handle, guid: GUID, info: dict[str, Any]) -> list[dict[str, Any]]:
		api.WlanGetProfileList.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(WLAN_PROFILE_INFO_LIST))]
		api.WlanGetProfileList.restype = wintypes.DWORD
		pointer = ctypes.POINTER(WLAN_PROFILE_INFO_LIST)()
		status = api.WlanGetProfileList(handle, ctypes.byref(guid), None, ctypes.byref(pointer))
		if status != ERROR_SUCCESS:
			raise OSError(status, "WlanGetProfileList failed")
		try:
			count = int(pointer.contents.dwNumberOfItems)
			base = ctypes.addressof(pointer.contents) + WLAN_PROFILE_INFO_LIST.ProfileInfo.offset
			rows = (WLAN_PROFILE_INFO * count).from_address(base) if count else []
			return [{"interface_id": info["interface_id"], "interface_name": info["name"], "profile_name": str(row.strProfileName), "flags": int(row.dwFlags)} for row in rows]
		finally:
			api.WlanFreeMemory(pointer)

	@classmethod
	def _connection_for_interface(cls, api, handle, guid: GUID, info: dict[str, Any]) -> dict[str, Any] | None:
		api.WlanQueryInterface.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
		api.WlanQueryInterface.restype = wintypes.DWORD
		size = wintypes.DWORD()
		buffer = ctypes.c_void_p()
		opcode_type = wintypes.DWORD()
		status = api.WlanQueryInterface(handle, ctypes.byref(guid), WLAN_INTF_OPCODE_CURRENT_CONNECTION, None, ctypes.byref(size), ctypes.byref(buffer), ctypes.byref(opcode_type))
		if status != ERROR_SUCCESS:
			return None
		try:
			attributes = ctypes.cast(buffer, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)).contents
			if int(attributes.isState) != WLAN_INTERFACE_STATE_CONNECTED:
				return None
			association = attributes.wlanAssociationAttributes
			security = attributes.wlanSecurityAttributes
			return {
				"interface_id": info["interface_id"],
				"interface_name": info["name"],
				"ssid": cls._ssid(association.dot11Ssid),
				"profile_name": str(attributes.strProfileName).strip() or None,
				"signal_quality_percent": int(association.wlanSignalQuality),
				"receive_rate_bps": int(association.ulRxRate) * 1000,
				"transmit_rate_bps": int(association.ulTxRate) * 1000,
				"authentication": cls._auth_name(security.dot11AuthAlgorithm),
				"cipher": cls._cipher_name(security.dot11CipherAlgorithm),
				"security_enabled": bool(security.bSecurityEnabled),
			}
		finally:
			api.WlanFreeMemory(buffer)

	def _read_interfaces(self) -> list[dict[str, Any]]:
		api, handle = self._open()
		try:
			return [info for _, info in self._enum_interfaces(api, handle)]
		finally:
			api.WlanCloseHandle(handle, None)

	def _read_visible_networks(self, interface_id: Any = None) -> list[dict[str, Any]]:
		api, handle = self._open()
		try:
			rows = self._select_interfaces(self._enum_interfaces(api, handle), interface_id)
			result = []
			for guid, info in rows:
				result.extend(self._available_for_interface(api, handle, guid, info))
			result.sort(key=lambda item: (not item.get("connected", False), -int(item.get("signal_quality_percent", 0)), str(item.get("ssid", "")).casefold()))
			return result
		finally:
			api.WlanCloseHandle(handle, None)

	def _read_saved_profiles(self, interface_id: Any = None) -> list[dict[str, Any]]:
		api, handle = self._open()
		try:
			rows = self._select_interfaces(self._enum_interfaces(api, handle), interface_id)
			result = []
			for guid, info in rows:
				result.extend(self._profiles_for_interface(api, handle, guid, info))
			return result
		finally:
			api.WlanCloseHandle(handle, None)

	def _read_connections(self) -> list[dict[str, Any]]:
		api, handle = self._open()
		try:
			result = []
			for guid, info in self._enum_interfaces(api, handle):
				connection = self._connection_for_interface(api, handle, guid, info)
				if connection:
					result.append(connection)
			return result
		finally:
			api.WlanCloseHandle(handle, None)

	def _scan(self, interface_id: Any = None) -> dict:
		api, handle = self._open()
		try:
			api.WlanScan.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.POINTER(DOT11_SSID), ctypes.c_void_p, ctypes.c_void_p]
			api.WlanScan.restype = wintypes.DWORD
			rows = self._select_interfaces(self._enum_interfaces(api, handle), interface_id)
			statuses = []
			for guid, info in rows:
				status = int(api.WlanScan(handle, ctypes.byref(guid), None, None, None))
				statuses.append({"interface_id": info["interface_id"], "status": status})
		finally:
			api.WlanCloseHandle(handle, None)
		time.sleep(1.5)
		self._refresh_safe()
		return {"success": all(item["status"] == ERROR_SUCCESS for item in statuses), "command": "ScanWiFi", "interfaces": statuses, "networks": self._read_visible_networks(interface_id)}

	@classmethod
	def _profile_xml(cls, ssid: str, password: str | None, auth_code: int, cipher_code: int, hidden: bool) -> str:
		name = html.escape(ssid, quote=False)
		non_broadcast = "<nonBroadcast>true</nonBroadcast>" if hidden else ""
		if auth_code == 1:
			auth = "open"
			encryption = "none"
			shared = ""
		elif auth_code in (4, 7, 9):
			if not password:
				raise ValueError("password is required for this network")
			if not 8 <= len(password) <= 63:
				raise ValueError("Wi-Fi passphrase must be 8 to 63 characters")
			auth = {4: "WPAPSK", 7: "WPA2PSK", 9: "WPA3SAE"}[auth_code]
			encryption = "TKIP" if cipher_code == 2 else "AES"
			key = html.escape(password, quote=False)
			shared = f"<sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>{key}</keyMaterial></sharedKey>"
		else:
			raise ValueError("Creating a new profile for this Wi-Fi authentication type is not supported; connect using an existing Windows profile")
		transition = '<transitionMode xmlns="http://www.microsoft.com/networking/WLAN/profile/v4">true</transitionMode>' if auth_code == 9 else ""
		return f'<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1"><name>{name}</name><SSIDConfig><SSID><name>{name}</name></SSID>{non_broadcast}</SSIDConfig><connectionType>ESS</connectionType><connectionMode>auto</connectionMode><autoSwitch>false</autoSwitch><MSM><security><authEncryption><authentication>{auth}</authentication><encryption>{encryption}</encryption><useOneX>false</useOneX>{transition}</authEncryption>{shared}</security></MSM></WLANProfile>'

	def _connect(self, arguments: dict[str, Any]) -> dict:
		ssid = str(arguments.get("ssid") or "").strip()
		profile_requested = str(arguments.get("profile") or "").strip()
		if not ssid and not profile_requested:
			raise ValueError("ConnectWiFi requires ssid or profile")
		api, handle = self._open()
		try:
			api.WlanConnect.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.POINTER(WLAN_CONNECTION_PARAMETERS), ctypes.c_void_p]
			api.WlanConnect.restype = wintypes.DWORD
			api.WlanSetProfile.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.BOOL, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
			api.WlanSetProfile.restype = wintypes.DWORD
			rows = self._select_interfaces(self._enum_interfaces(api, handle), arguments.get("interface_id"))
			guid, info = rows[0]
			profiles = self._profiles_for_interface(api, handle, guid, info)
			profile_names = [item["profile_name"] for item in profiles]
			profile = profile_requested or next((name for name in profile_names if name.casefold() == ssid.casefold()), "")
			visible = self._available_for_interface(api, handle, guid, info)
			network = next((item for item in visible if item.get("ssid", "").casefold() == ssid.casefold()), None) if ssid else None
			if not profile and network and network.get("profile_name"):
				profile = network["profile_name"]
			if not profile:
				if network is None:
					raise ValueError("Wi-Fi network is not visible and no saved profile was supplied")
				xml = self._profile_xml(ssid, arguments.get("password"), int(network.get("authentication_code", 0)), int(network.get("cipher_code", 0)), bool(arguments.get("hidden", False)))
				reason = wintypes.DWORD()
				status = int(api.WlanSetProfile(handle, ctypes.byref(guid), WLAN_PROFILE_USER, xml, None, True, None, ctypes.byref(reason)))
				if status != ERROR_SUCCESS:
					raise OSError(status, f"WlanSetProfile failed; reason={int(reason.value)}")
				profile = ssid
			parameters = WLAN_CONNECTION_PARAMETERS(WLAN_CONNECTION_MODE_PROFILE, profile, None, None, DOT11_BSS_TYPE_INFRASTRUCTURE, 0)
			status = int(api.WlanConnect(handle, ctypes.byref(guid), ctypes.byref(parameters), None))
			if status != ERROR_SUCCESS:
				return {"success": False, "command": "ConnectWiFi", "error": "connect_failed", "status": status, "profile": profile, "interface_id": info["interface_id"]}
		finally:
			api.WlanCloseHandle(handle, None)
		for _ in range(12):
			time.sleep(0.5)
			connections = self._read_connections()
			matching = next((item for item in connections if item.get("profile_name", "").casefold() == profile.casefold() or (ssid and item.get("ssid", "").casefold() == ssid.casefold())), None)
			if matching:
				self._refresh_safe()
				return {"success": True, "command": "ConnectWiFi", "profile": profile, "connection": matching}
		self._refresh_safe()
		return {"success": True, "command": "ConnectWiFi", "profile": profile, "connection_requested": True, "confirmed": False}

	def _disconnect(self, interface_id: Any = None) -> dict:
		api, handle = self._open()
		try:
			api.WlanDisconnect.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.c_void_p]
			api.WlanDisconnect.restype = wintypes.DWORD
			rows = self._select_interfaces(self._enum_interfaces(api, handle), interface_id)
			results = []
			for guid, info in rows:
				status = int(api.WlanDisconnect(handle, ctypes.byref(guid), None))
				results.append({"interface_id": info["interface_id"], "status": status})
		finally:
			api.WlanCloseHandle(handle, None)
		time.sleep(0.5)
		self._refresh_safe()
		return {"success": all(item["status"] == ERROR_SUCCESS for item in results), "command": "DisconnectWiFi", "interfaces": results}

	def _forget(self, arguments: dict[str, Any]) -> dict:
		profile = str(arguments.get("profile") or arguments.get("ssid") or "").strip()
		if not profile:
			raise ValueError("ForgetWiFiNetwork requires profile or ssid")
		api, handle = self._open()
		try:
			api.WlanDeleteProfile.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.LPCWSTR, ctypes.c_void_p]
			api.WlanDeleteProfile.restype = wintypes.DWORD
			rows = self._select_interfaces(self._enum_interfaces(api, handle), arguments.get("interface_id"))
			results = []
			for guid, info in rows:
				profiles = self._profiles_for_interface(api, handle, guid, info)
				matching = [item["profile_name"] for item in profiles if item["profile_name"].casefold() == profile.casefold()]
				for name in matching:
					status = int(api.WlanDeleteProfile(handle, ctypes.byref(guid), name, None))
					results.append({"interface_id": info["interface_id"], "profile_name": name, "status": status})
		finally:
			api.WlanCloseHandle(handle, None)
		self._refresh_safe()
		if not results:
			return {"success": False, "command": "ForgetWiFiNetwork", "error": "profile_not_found", "profile": profile}
		return {"success": all(item["status"] == ERROR_SUCCESS for item in results), "command": "ForgetWiFiNetwork", "profiles": results}
