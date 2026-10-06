from __future__ import annotations

from StatMonitorModuleBase import PollingModule

try:
	import psutil
except ImportError:
	psutil = None


class StatMonitorRAM(PollingModule):
	def collect(self):
		if not psutil:
			return {}, {}, {"name": "psutil", "status": "unavailable"}, []
		memory = psutil.virtual_memory()
		return {"total_bytes": int(memory.total)}, {"used_bytes": int(memory.used), "available_bytes": int(memory.available), "usage_percent": float(memory.percent)}, {"name": "psutil", "status": "available"}, []
