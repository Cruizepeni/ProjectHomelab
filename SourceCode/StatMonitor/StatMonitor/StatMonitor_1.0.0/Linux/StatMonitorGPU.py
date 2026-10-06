from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from StatMonitorModuleBase import PollingModule
from Linux.StatMonitorLinuxCommon import command_available, hwmon_temperatures, read_number, read_text, root_path, run


class StatMonitorGPU(PollingModule):
	def __init__(self, project_root=None):
		super().__init__()
		self._internal_power_consumers = set()

	def set_internal_power_request(self, consumer_id, enabled):
		if enabled:
			self._internal_power_consumers.add(str(consumer_id))
		else:
			self._internal_power_consumers.discard(str(consumer_id))

	def get_internal_power_w(self):
		values = [g.get("power_w") for g in self.get_latest().get("live", {}).get("gpus", [])]
		values = [float(v) for v in values if isinstance(v, (int, float))]
		return round(sum(values), 2) if values else None

	def collect(self):
		gpus, live, provider = self._nvidia()
		if not gpus:
			gpus, live, provider = self._drm()
		return {"gpus": gpus}, {"gpus": live}, provider, []

	def _nvidia(self):
		if not command_available("nvidia-smi"):
			return [], [], {"name": "Linux GPU", "status": "partial"}
		fields = "index,pci.bus_id,name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw,clocks.current.graphics,fan.speed"
		completed = run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"], 8)
		if completed.returncode != 0:
			return [], [], {"name": "nvidia-smi", "status": "degraded", "reason": completed.stderr.strip()}
		gpus, live = [], []
		for row in csv.reader(io.StringIO(completed.stdout)):
			if len(row) < 11:
				continue
			idx, bus, name, driver, total, used, util, temp, power, clock, fan = [x.strip() for x in row[:11]]
			gpu_id = f"nvidia::{bus or idx}"
			gpus.append({"gpu_id": gpu_id, "name": name, "vendor": "NVIDIA", "graphics_type": "Dedicated", "driver_version": driver, "vram_total_bytes": _mib(total), "pci_bus_id": bus})
			live.append({"gpu_id": gpu_id, "vram_used_bytes": _mib(used), "usage_percent": _num(util), "temperature_c": _num(temp), "power_w": _num(power), "clock": {"core_mhz": _num(clock)}, "fans": [{"name": "GPU Fan", "percent": _num(fan)}]})
		return gpus, live, {"name": "nvidia-smi", "status": "available"}

	def _drm(self):
		base = root_path("/sys/class/drm")
		gpus, live = [], []
		cards = [path for path in sorted(base.glob("card[0-9]*")) if (path / "device").exists()] if base.exists() else []
		for card in cards:
			device = card / "device"
			vendor_id = (read_text(device / "vendor") or "").casefold()
			vendor = {"0x1002": "AMD", "0x8086": "Intel", "0x10de": "NVIDIA"}.get(vendor_id, vendor_id or None)
			device_id = read_text(device / "device")
			name = self._pci_name(card.name, vendor, device_id)
			gpu_id = f"drm::{card.name}::{vendor_id}:{device_id or ''}"
			vram_total = read_number(device / "mem_info_vram_total")
			vram_used = read_number(device / "mem_info_vram_used")
			busy = read_number(device / "gpu_busy_percent")
			power = None
			for candidate in list(device.glob("hwmon/hwmon*/power1_average")) + list(device.glob("hwmon/hwmon*/power1_input")):
				value = read_number(candidate, 1_000_000.0)
				if value is not None:
					power = value
					break
			temps = []
			for candidate in device.glob("hwmon/hwmon*/temp*_input"):
				value = read_number(candidate, 1000.0)
				if value is not None and -20 < value < 150:
					temps.append(value)
			clock = self._drm_clock(device)
			gpus.append({"gpu_id": gpu_id, "name": name, "vendor": vendor, "graphics_type": "Integrated" if vendor == "Intel" else "Dedicated", "vram_total_bytes": int(vram_total) if vram_total is not None else None, "device": str(device)})
			live.append({"gpu_id": gpu_id, "vram_used_bytes": int(vram_used) if vram_used is not None else None, "usage_percent": round(busy, 1) if busy is not None else None, "temperature_c": round(max(temps), 1) if temps else None, "power_w": round(power, 2) if power is not None else None, "clock": {"core_mhz": clock} if clock is not None else {}})
		if not gpus and command_available("lspci"):
			completed = run(["lspci", "-nn"], 5)
			for line in completed.stdout.splitlines():
				lower = line.casefold()
				if not any(token in lower for token in ("vga compatible controller", "3d controller", "display controller")):
					continue
				vendor = "NVIDIA" if "nvidia" in lower else "AMD" if any(x in lower for x in ("amd", "ati")) else "Intel" if "intel" in lower else None
				gpu_id = f"pci::{line.split()[0]}"
				gpus.append({"gpu_id": gpu_id, "name": line.split(":", 2)[-1].strip(), "vendor": vendor, "graphics_type": "Unknown"})
				live.append({"gpu_id": gpu_id})
		return gpus, live, {"name": "DRM sysfs", "status": "available" if gpus else "unavailable"}

	def _pci_name(self, card, vendor, device_id):
		if command_available("lspci"):
			try:
				completed = run(["lspci", "-D"], 5)
				card_path = root_path(f"/sys/class/drm/{card}/device")
				address = card_path.resolve().name
				for line in completed.stdout.splitlines():
					if line.startswith(address):
						return line.split(": ", 1)[-1].strip()
			except Exception:
				pass
		return " ".join(item for item in (vendor, device_id) if item) or card

	@staticmethod
	def _drm_clock(device: Path):
		text = read_text(device / "pp_dpm_sclk")
		if not text:
			return None
		for line in text.splitlines():
			if "*" in line:
				match = re.search(r"([0-9.]+)\s*Mhz", line, re.I)
				if match:
					return round(float(match.group(1)), 1)
		return None


def _num(value):
	try:
		text = str(value).strip()
		if not text or text.casefold() in {"n/a", "[not supported]", "not supported"}:
			return None
		return round(float(text), 1)
	except Exception:
		return None


def _mib(value):
	value = _num(value)
	return int(value * 1024 * 1024) if value is not None else None
