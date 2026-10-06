from __future__ import annotations

from StatMonitorModuleBase import PollingModule
from Linux.StatMonitorLinuxCommon import hwmon_devices, hwmon_fans, hwmon_temperatures, read_number, read_text


class StatMonitorMotherboard(PollingModule):
	def collect(self):
		hardware = {
			"manufacturer": read_text("/sys/devices/virtual/dmi/id/board_vendor") or read_text("/sys/firmware/devicetree/base/model"),
			"motherboard_name": read_text("/sys/devices/virtual/dmi/id/board_name") or read_text("/sys/firmware/devicetree/base/model"),
			"bios_version": read_text("/sys/devices/virtual/dmi/id/bios_version") or read_text("/sys/firmware/devicetree/base/system/linux,revision"),
			"chipset": None,
		}
		temperatures = hwmon_temperatures()
		fans = hwmon_fans()
		voltages = []
		for device in hwmon_devices():
			path = device["path"]
			for input_file in sorted(path.glob("in*_input")):
				value = read_number(input_file, 1000.0)
				if value is None:
					continue
				stem = input_file.name[:-6]
				label = read_text(path / f"{stem}_label") or f"{device['name']} {stem}"
				voltages.append({"name": label, "voltage_v": round(value, 3)})
		live = {"temperatures": temperatures, "fans": fans, "voltages": voltages}
		return hardware, live, {"name": "DMI/device-tree+hwmon", "status": "available"}, []
