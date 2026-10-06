from __future__ import annotations

import platform
import subprocess

from StatMonitorModuleBase import PollingModule

try:
	import psutil
except ImportError:
	psutil = None


class StatMonitorCPU(PollingModule):
	def __init__(self, project_root=None):
		super().__init__()
		self._internal_power_consumers = set()

	def set_internal_power_request(self, consumer_id, enabled):
		if enabled:
			self._internal_power_consumers.add(str(consumer_id))
		else:
			self._internal_power_consumers.discard(str(consumer_id))

	def get_internal_power_w(self):
		value = self.get_latest().get("live", {}).get("power_w")
		return float(value) if isinstance(value, (int, float)) else None

	def collect(self):
		name = _sysctl("machdep.cpu.brand_string") or _sysctl("hw.model") or platform.processor() or None
		hardware = {"name": name, "physical_cores": psutil.cpu_count(logical=False) if psutil else None, "logical_processors": psutil.cpu_count(logical=True) if psutil else None}
		live = {}
		if psutil:
			live["usage_percent"] = psutil.cpu_percent(interval=None)
			freq = psutil.cpu_freq()
			if freq:
				live["clock"] = {"average_mhz": round(float(freq.current), 1)}
		return hardware, live, {"name": "sysctl+psutil", "status": "partial"}, []


def _sysctl(key):
	try:
		completed = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=3, check=False)
		value = completed.stdout.strip()
		return value or None
	except Exception:
		return None
