from __future__ import annotations


WIFI_COMMANDS = {
	"GetWiFiStatus": {"purpose": "Return Wi-Fi adapter and current connection state."},
	"GetWiFiNetworks": {"purpose": "Return visible Wi-Fi networks."},
	"GetSavedWiFiNetworks": {"purpose": "Return saved Wi-Fi profiles."},
	"ScanWiFi": {"purpose": "Request a Wi-Fi scan and return visible networks."},
	"ConnectWiFi": {"purpose": "Connect to a Wi-Fi network or saved profile.", "args": {"ssid": "network SSID", "password": "optional passphrase", "profile": "optional saved profile", "interface_id": "optional interface GUID"}},
	"DisconnectWiFi": {"purpose": "Disconnect a Wi-Fi interface.", "args": {"interface_id": "optional interface GUID"}},
	"ForgetWiFiNetwork": {"purpose": "Delete a saved Wi-Fi profile.", "args": {"profile": "profile name or SSID", "interface_id": "optional interface GUID"}},
	"WiFiOn": {"purpose": "Turn the Windows Wi-Fi radio on or use the platform-equivalent radio control."},
	"WiFiOff": {"purpose": "Turn the Windows Wi-Fi radio off or use the platform-equivalent radio control."},
}

BLUETOOTH_COMMANDS = {
	"GetBluetoothStatus": {"purpose": "Return Bluetooth adapter and device state."},
	"GetBluetoothAdapters": {"purpose": "Return Bluetooth adapter state."},
	"GetBluetoothDevices": {"purpose": "Return discovered Bluetooth devices."},
	"ScanBluetooth": {"purpose": "Refresh Bluetooth discovery and return devices."},
	"PairBluetoothDevice": {"purpose": "Pair a Bluetooth device.", "args": {"device": "device id, address, or name"}},
	"UnpairBluetoothDevice": {"purpose": "Unpair a Bluetooth device.", "args": {"device": "device id, address, or name"}},
	"ConnectBluetoothDevice": {"purpose": "Request a connection to a paired Bluetooth device.", "args": {"device": "device id, address, or name"}},
	"DisconnectBluetoothDevice": {"purpose": "Disconnect or release a Bluetooth device connection.", "args": {"device": "device id, address, or name"}},
	"BluetoothOn": {"purpose": "Turn the Windows Bluetooth radio on or use the platform-equivalent radio control."},
	"BluetoothOff": {"purpose": "Turn the Windows Bluetooth radio off or use the platform-equivalent radio control."},
}

PRIVACY_COMMANDS = {
	"GetPrivacyStatus": {"purpose": "Return webcam, microphone and location privacy state."},
	"CameraOn": {"purpose": "Allow webcam access for the current Windows user or platform equivalent."},
	"CameraOff": {"purpose": "Block webcam access for the current Windows user or platform equivalent."},
	"MicrophoneOn": {"purpose": "Allow microphone access for the current Windows user or platform equivalent."},
	"MicrophoneOff": {"purpose": "Block microphone access for the current Windows user or platform equivalent."},
	"LocationOn": {"purpose": "Allow location access for the current Windows user or platform equivalent."},
	"LocationOff": {"purpose": "Block location access for the current Windows user or platform equivalent."},
}

STORAGE_TOOL_COMMANDS = {
	"GetStorageToolDisks": {"purpose": "Return physical disks and complete partition layouts, including unmounted disks."},
	"RefreshStorageToolDisks": {"purpose": "Rescan physical disks and partition layouts."},
	"GetStorageToolCapabilities": {"purpose": "Return supported partition styles, filesystems and drive-preparation presets."},
	"CleanStorageDisk": {"purpose": "Destructively remove all partitions and partition-table data from a non-system physical disk.", "args": {"disk_number": "physical disk number or platform device id"}},
	"PrepareStorageDisk": {"purpose": "Destructively rebuild a non-system physical disk with one full-size partition and optional filesystem.", "args": {"disk_number": "physical disk number or platform device id", "partition_style": "GPT or MBR", "filesystem": "filesystem name or None", "label": "optional volume label"}},
	"FormatStoragePartition": {"purpose": "Destructively format one non-system partition.", "args": {"disk_number": "physical disk number or platform device id", "partition_number": "partition number or device id", "filesystem": "filesystem name", "label": "optional volume label"}},
}

DEVICE_COMMANDS = {**WIFI_COMMANDS, **BLUETOOTH_COMMANDS, **PRIVACY_COMMANDS, **STORAGE_TOOL_COMMANDS}
