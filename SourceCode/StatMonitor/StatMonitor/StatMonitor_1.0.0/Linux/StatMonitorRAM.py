from __future__ import annotations

from StatMonitorModuleBase import PollingModule
from Linux.StatMonitorLinuxCommon import command_available, run

try:
	import psutil
except ImportError:
	psutil = None


class StatMonitorRAM(PollingModule):
	def collect(self):
		if not psutil:
			return {}, {}, {"name": "psutil", "status": "unavailable"}, []
		memory = psutil.virtual_memory()
		hardware = {"total_bytes": int(memory.total), "modules": self._modules()}
		live = {"used_bytes": int(memory.used), "available_bytes": int(memory.available), "usage_percent": round(float(memory.percent), 1), "cached_bytes": int(getattr(memory, "cached", 0) or 0), "buffers_bytes": int(getattr(memory, "buffers", 0) or 0)}
		return hardware, live, {"name": "psutil+dmidecode", "status": "available"}, []

	def _modules(self):
		if not command_available("dmidecode"):
			return []
		completed = run(["dmidecode", "--type", "17"], 8)
		if completed.returncode != 0:
			return []
		modules = []
		current = {}
		for raw in completed.stdout.splitlines():
			line = raw.strip()
			if line == "Memory Device":
				if current.get("size") and "No Module" not in current.get("size", ""):
					modules.append(current)
				current = {}
			elif ":" in line:
				key, value = [part.strip() for part in line.split(":", 1)]
				mapping = {"Size": "size", "Type": "type", "Speed": "speed", "Configured Memory Speed": "configured_speed", "Manufacturer": "manufacturer", "Part Number": "part_number", "Locator": "locator"}
				if key in mapping:
					current[mapping[key]] = value
		if current.get("size") and "No Module" not in current.get("size", ""):
			modules.append(current)
		return modules
