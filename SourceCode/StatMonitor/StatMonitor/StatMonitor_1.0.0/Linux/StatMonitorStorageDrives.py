from __future__ import annotations

import json
import time
from pathlib import Path

from StatMonitorModuleBase import PollingModule
from Linux.StatMonitorLinuxCommon import command_available, read_number, root_path, run

try:
	import psutil
except ImportError:
	psutil = None


class StatMonitorStorageDrives(PollingModule):
	def __init__(self, project_root=None):
		super().__init__()
		self._last_io = {}
		self._last_time = None
		self._smart_cache = {}
		self._smart_sampled = 0.0

	def collect(self):
		drives = self._discover()
		now = time.monotonic()
		io = psutil.disk_io_counters(perdisk=True) if psutil else {}
		elapsed = now - self._last_time if self._last_time else None
		if now - self._smart_sampled > 30.0:
			self._smart_cache = {item["physical_device"]: self._smart(item["physical_device"]) for item in drives if item.get("physical_device")}
			self._smart_sampled = now
		live = []
		for drive in drives:
			entry = {"drive_id": drive["drive_id"]}
			mount = drive.get("mount_path")
			if psutil and mount:
				try:
					usage = psutil.disk_usage(mount)
					entry.update({"used_bytes": int(usage.used), "free_bytes": int(usage.free), "usage_percent": round(float(usage.percent), 1)})
				except Exception:
					pass
			disk_name = drive.get("disk_name")
			counter = io.get(disk_name) or io.get(Path(drive.get("physical_device") or "").name)
			previous = self._last_io.get(disk_name)
			if counter and previous and elapsed and elapsed > 0:
				read_bps = max(0.0, (counter.read_bytes - previous.read_bytes) / elapsed)
				write_bps = max(0.0, (counter.write_bytes - previous.write_bytes) / elapsed)
				entry.update({"read_bytes_per_sec": read_bps, "write_bytes_per_sec": write_bps})
				busy_delta = max(0.0, float(counter.busy_time - previous.busy_time))
				entry["activity_percent"] = round(max(0.0, min(100.0, busy_delta / (elapsed * 10.0))), 1)
			smart = self._smart_cache.get(drive.get("physical_device"), {})
			entry.update({key: value for key, value in smart.items() if value is not None})
			live.append(entry)
		self._last_io, self._last_time = io, now
		return {"drives": drives}, {"drives": live}, {"name": "lsblk+psutil+smartctl", "status": "available"}, []

	def _discover(self):
		if not command_available("lsblk"):
			return self._fallback_mounts()
		fields = "NAME,KNAME,PATH,PKNAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL,TRAN,ROTA"
		completed = run(["lsblk", "-J", "-b", "-o", fields], 10)
		if completed.returncode != 0:
			return self._fallback_mounts()
		try:
			payload = json.loads(completed.stdout or "{}")
		except Exception:
			return self._fallback_mounts()
		result = []
		for disk in payload.get("blockdevices", []) or []:
			if not isinstance(disk, dict) or disk.get("type") != "disk":
				continue
			physical = disk.get("path") or f"/dev/{disk.get('name')}"
			children = self._flatten(disk.get("children") or [])
			mounted = [item for item in children if any(x for x in (item.get("mountpoints") or []) if x)]
			if not mounted:
				mounted = [disk] if any(x for x in (disk.get("mountpoints") or []) if x) else []
			if not mounted:
				result.append(self._drive_entry(disk, disk, physical, None))
				continue
			for volume in mounted:
				mounts = [x for x in (volume.get("mountpoints") or []) if x]
				for mount in mounts:
					result.append(self._drive_entry(disk, volume, physical, mount))
		return result

	def _drive_entry(self, disk, volume, physical, mount):
		volume_path = volume.get("path") or physical
		bus = disk.get("tran")
		rotational = disk.get("rota")
		media = "HDD" if rotational in (1, "1", True) else "SSD" if rotational in (0, "0", False) else None
		return {
			"drive_id": f"{volume_path}::{mount or 'unmounted'}",
			"name": mount or volume_path,
			"mount_path": mount,
			"open_path": mount,
			"device": volume_path,
			"physical_device": physical,
			"disk_name": disk.get("name"),
			"model": disk.get("model") or disk.get("name"),
			"serial_number": disk.get("serial"),
			"filesystem": volume.get("fstype"),
			"size_bytes": _int(volume.get("size")) or _int(disk.get("size")),
			"drive_type": {"class": "Physical/Volume", "bus": bus, "media": media},
		}

	@staticmethod
	def _flatten(children):
		result = []
		for child in children:
			if not isinstance(child, dict):
				continue
			result.append(child)
			result.extend(StatMonitorStorageDrives._flatten(child.get("children") or []))
		return result

	def _smart(self, device):
		if not command_available("smartctl") or not device:
			return {}
		completed = run(["smartctl", "-a", "-j", "-n", "standby", device], 12)
		if not completed.stdout.strip():
			return {}
		try:
			data = json.loads(completed.stdout)
		except Exception:
			return {}
		temp = _nested(data, "temperature", "current") or _nested(data, "nvme_smart_health_information_log", "temperature")
		passed = _nested(data, "smart_status", "passed")
		wear = _nested(data, "nvme_smart_health_information_log", "percentage_used")
		return {"temperature_c": _float(temp), "health": "healthy" if passed is True else "warning" if passed is False else None, "wear_used_percent": _float(wear)}

	def _fallback_mounts(self):
		result = []
		if not psutil:
			return result
		for part in psutil.disk_partitions(all=False):
			try:
				usage = psutil.disk_usage(part.mountpoint)
			except Exception:
				continue
			result.append({"drive_id": f"{part.device}::{part.mountpoint}", "name": part.mountpoint, "mount_path": part.mountpoint, "open_path": part.mountpoint, "device": part.device, "physical_device": part.device, "disk_name": Path(part.device).name, "filesystem": part.fstype, "size_bytes": int(usage.total), "drive_type": {"class": "Volume", "bus": None, "media": None}})
		return result


def _nested(value, *keys):
	for key in keys:
		if not isinstance(value, dict):
			return None
		value = value.get(key)
	return value


def _float(value):
	try:
		return round(float(value), 1)
	except Exception:
		return None


def _int(value):
	try:
		return int(value)
	except Exception:
		return None
