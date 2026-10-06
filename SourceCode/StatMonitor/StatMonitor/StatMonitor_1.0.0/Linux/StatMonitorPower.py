from __future__ import annotations

from StatMonitorModuleBase import PollingModule
from Linux.StatMonitorLinuxCommon import read_number, read_text, root_path

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
		details = self._battery_details()
		hardware = {"has_battery": battery is not None or bool(details)}
		hardware.update({key: details.get(key) for key in ("manufacturer", "model", "technology", "design_capacity_wh", "full_charge_capacity_wh", "cycle_count") if details.get(key) is not None})
		live = {}
		if battery is not None:
			live.update({"battery_percent": round(float(battery.percent), 1), "plugged_in": bool(battery.power_plugged), "charging": bool(battery.power_plugged and float(battery.percent) < 100), "seconds_left": None if battery.secsleft is None or battery.secsleft < 0 else int(battery.secsleft), "power_source": "AC" if battery.power_plugged else "Battery"})
		else:
			live["power_source"] = "AC/Unknown"
		if details.get("health_percent") is not None:
			live["battery_health_percent"] = details["health_percent"]
		if details.get("power_w") is not None:
			live["battery_power_w"] = details["power_w"]
		if self.cpu_module and hasattr(self.cpu_module, "get_internal_power_w"):
			live["cpu_power_w"] = self.cpu_module.get_internal_power_w()
		if self.gpu_module and hasattr(self.gpu_module, "get_internal_power_w"):
			live["gpu_power_w"] = self.gpu_module.get_internal_power_w()
		return hardware, live, {"name": "psutil+/sys/class/power_supply", "status": "available"}, []

	def _battery_details(self):
		base = root_path("/sys/class/power_supply")
		if not base.exists():
			return {}
		battery_path = next((path for path in sorted(base.iterdir()) if (read_text(path / "type") or "").casefold() == "battery"), None)
		if battery_path is None:
			return {}
		design_uwh = read_number(battery_path / "energy_full_design")
		full_uwh = read_number(battery_path / "energy_full")
		if design_uwh is None:
			design_uah = read_number(battery_path / "charge_full_design")
			voltage = read_number(battery_path / "voltage_min_design") or read_number(battery_path / "voltage_now")
			if design_uah is not None and voltage is not None:
				design_uwh = design_uah * voltage / 1_000_000.0
		if full_uwh is None:
			full_uah = read_number(battery_path / "charge_full")
			voltage = read_number(battery_path / "voltage_now")
			if full_uah is not None and voltage is not None:
				full_uwh = full_uah * voltage / 1_000_000.0
		power_uw = read_number(battery_path / "power_now")
		if power_uw is None:
			current_ua = read_number(battery_path / "current_now")
			voltage_uv = read_number(battery_path / "voltage_now")
			if current_ua is not None and voltage_uv is not None:
				power_uw = current_ua * voltage_uv / 1_000_000.0
		health = full_uwh / design_uwh * 100.0 if full_uwh and design_uwh else None
		return {
			"manufacturer": read_text(battery_path / "manufacturer"),
			"model": read_text(battery_path / "model_name"),
			"technology": read_text(battery_path / "technology"),
			"cycle_count": _int(read_number(battery_path / "cycle_count")),
			"design_capacity_wh": round(design_uwh / 1_000_000.0, 2) if design_uwh is not None else None,
			"full_charge_capacity_wh": round(full_uwh / 1_000_000.0, 2) if full_uwh is not None else None,
			"health_percent": round(health, 1) if health is not None else None,
			"power_w": round(power_uw / 1_000_000.0, 2) if power_uw is not None else None,
		}


def _int(value):
	try:
		return int(value)
	except Exception:
		return None
