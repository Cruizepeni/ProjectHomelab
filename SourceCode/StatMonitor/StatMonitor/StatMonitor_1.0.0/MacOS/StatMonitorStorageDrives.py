from __future__ import annotations

from StatMonitorModuleBase import PollingModule

try:
	import psutil
except ImportError:
	psutil = None


class StatMonitorStorageDrives(PollingModule):
	def collect(self):
		if not psutil:
			return {"drives": []}, {"drives": []}, {"name": "psutil", "status": "unavailable"}, []
		drives = []
		live = []
		for part in psutil.disk_partitions(all=False):
			try:
				usage = psutil.disk_usage(part.mountpoint)
			except Exception:
				continue
			entry = {"drive_id": part.device or part.mountpoint, "device": part.device, "mount": part.mountpoint, "filesystem": part.fstype, "size_bytes": int(usage.total)}
			drives.append(entry)
			live.append({"drive_id": entry["drive_id"], "used_bytes": int(usage.used), "free_bytes": int(usage.free), "usage_percent": float(usage.percent)})
		return {"drives": drives}, {"drives": live}, {"name": "psutil", "status": "available"}, []
