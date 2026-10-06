from __future__ import annotations

import json
import subprocess

from StatMonitorModuleBase import PollingModule


class StatMonitorMotherboard(PollingModule):
	def collect(self):
		hardware = {}
		try:
			completed = subprocess.run(["system_profiler", "-json", "SPHardwareDataType"], capture_output=True, text=True, timeout=10, check=False)
			data = json.loads(completed.stdout or "{}")
			items = data.get("SPHardwareDataType", []) or []
			if items:
				item = items[0]
				hardware = {"manufacturer": "Apple", "motherboard_name": item.get("machine_model") or item.get("machine_name") or item.get("_name"), "chipset": item.get("chip_type"), "bios_version": item.get("boot_rom_version")}
		except Exception:
			pass
		return hardware, {}, {"name": "system_profiler", "status": "partial"}, []
