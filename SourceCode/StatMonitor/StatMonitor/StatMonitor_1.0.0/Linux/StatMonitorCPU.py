from __future__ import annotations

import platform
import re
from pathlib import Path

from StatMonitorModuleBase import PollingModule
from Linux.StatMonitorLinuxCommon import hwmon_temperatures, read_number, read_text, root_path

try:
	import psutil
except ImportError:
	psutil = None


class StatMonitorCPU(PollingModule):
	def __init__(self, project_root=None):
		super().__init__()
		self._internal_power_consumers = set()
		self._energy_last = None

	def set_internal_power_request(self, consumer_id, enabled):
		if enabled:
			self._internal_power_consumers.add(str(consumer_id))
		else:
			self._internal_power_consumers.discard(str(consumer_id))

	def get_internal_power_w(self):
		value = self.get_latest().get("live", {}).get("power_w")
		return float(value) if isinstance(value, (int, float)) else None

	def collect(self):
		cpuinfo = read_text("/proc/cpuinfo") or ""
		name = platform.processor() or None
		brand = None
		for pattern in (r"^model name\s*:\s*(.+)$", r"^Hardware\s*:\s*(.+)$", r"^Processor\s*:\s*(.+)$"):
			match = re.search(pattern, cpuinfo, re.MULTILINE)
			if match:
				name = match.group(1).strip()
				break
		if name:
			brand = "Intel" if "intel" in name.casefold() else "AMD" if "amd" in name.casefold() else "ARM" if any(x in name.casefold() for x in ("arm", "cortex", "bcm")) else None
		physical = psutil.cpu_count(logical=False) if psutil else None
		logical = psutil.cpu_count(logical=True) if psutil else None
		base = self._base_clock()
		hardware = {"brand": brand, "name": name, "physical_cores": physical, "logical_processors": logical, "base_clock_mhz": base}
		live = {}
		if psutil:
			live["usage_percent"] = round(float(psutil.cpu_percent(interval=None)), 1)
			freq = psutil.cpu_freq()
			if freq:
				live["clock"] = {"average_mhz": round(float(freq.current), 1), "max_mhz": round(float(freq.max), 1) if freq.max else None}
			try:
				per_core = psutil.cpu_percent(interval=None, percpu=True)
				freqs = []
				for index, usage in enumerate(per_core):
					freq_value = read_number(f"/sys/devices/system/cpu/cpu{index}/cpufreq/scaling_cur_freq", 1000.0)
					freqs.append({"name": f"CPU {index}", "usage_percent": round(float(usage), 1), "clock_mhz": round(freq_value, 1) if freq_value else None})
				live["individual_cores"] = freqs
			except Exception:
				pass
		temps = self._cpu_temperatures()
		if temps:
			live["temperature_c"] = max(item["temperature_c"] for item in temps)
			for index, item in enumerate(live.get("individual_cores", [])):
				if index < len(temps):
					item["temperature_c"] = temps[index]["temperature_c"]
		power = self._power_w()
		if power is not None:
			live["power_w"] = round(power, 2)
		provider = {"name": "psutil+/proc+sysfs", "status": "available"}
		return hardware, live, provider, []

	def _cpu_temperatures(self):
		priority = []
		other = []
		for item in hwmon_temperatures():
			text = f"{item['chip']} {item['name']}".casefold()
			if any(token in text for token in ("coretemp", "k10temp", "zenpower", "cpu", "package", "tctl", "tdie", "soc_thermal")):
				priority.append(item)
			else:
				other.append(item)
		return priority or other[:1]

	def _base_clock(self):
		values = []
		base = root_path("/sys/devices/system/cpu")
		for path in base.glob("cpu[0-9]*/cpufreq/cpuinfo_max_freq") if base.exists() else []:
			value = read_number(path, 1000.0)
			if value:
				values.append(value)
		return round(max(values), 1) if values else None

	def _power_w(self):
		energy_paths = list(root_path("/sys/class/powercap").glob("intel-rapl*/energy_uj")) if root_path("/sys/class/powercap").exists() else []
		if not energy_paths:
			return None
		import time
		now = time.monotonic()
		energy = sum(read_number(path) or 0.0 for path in energy_paths)
		previous = self._energy_last
		self._energy_last = (now, energy)
		if not previous or now <= previous[0] or energy < previous[1]:
			return None
		return (energy - previous[1]) / 1_000_000.0 / (now - previous[0])
