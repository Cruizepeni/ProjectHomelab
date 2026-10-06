from __future__ import annotations

from StatMonitorModuleBase import PollingModule

try:
	import psutil
except ImportError:
	psutil = None


class StatMonitorPower(PollingModule):
	def __init__(self, cpu_module=None, gpu_module=None, project_root=None):
		super().__init__()
		self.cpu_module = cpu_module
		self.gpu_module = gpu_module
		for module in (cpu_module, gpu_module):
			if module and hasattr(module, "set_internal_power_request"):
				module.set_internal_power_request("StatMonitorPower", True)

	def collect(self):
		battery = None
		if psutil:
			try:
				battery = psutil.sensors_battery()
			except Exception:
				battery = None
		hardware = {"has_battery": battery is not None}
		live = {}
		if battery is not None:
			live.update({"battery_percent": float(battery.percent), "plugged_in": bool(battery.power_plugged), "seconds_left": None if battery.secsleft is None or battery.secsleft < 0 else int(battery.secsleft), "power_source": "AC" if battery.power_plugged else "Battery"})
		else:
			live["power_source"] = "AC/Unknown"
		if self.cpu_module and hasattr(self.cpu_module, "get_internal_power_w"):
			live["cpu_power_w"] = self.cpu_module.get_internal_power_w()
		if self.gpu_module and hasattr(self.gpu_module, "get_internal_power_w"):
			live["gpu_power_w"] = self.gpu_module.get_internal_power_w()
		return hardware, live, {"name": "psutil", "status": "partial"}, []
