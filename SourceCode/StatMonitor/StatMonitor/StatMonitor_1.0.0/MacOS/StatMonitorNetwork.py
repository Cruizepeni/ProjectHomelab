from __future__ import annotations

import socket
import time

from StatMonitorModuleBase import PollingModule

try:
	import psutil
except ImportError:
	psutil = None


class StatMonitorNetwork(PollingModule):
	def __init__(self, project_root=None):
		super().__init__()
		self._last_io = {}
		self._last_time = None

	def collect(self):
		if not psutil:
			return {"adapters": []}, {"adapters": []}, {"name": "psutil", "status": "unavailable"}, []
		addresses = psutil.net_if_addrs()
		stats = psutil.net_if_stats()
		io = psutil.net_io_counters(pernic=True)
		now = time.monotonic()
		elapsed = now - self._last_time if self._last_time else None
		hardware = []
		live = []
		for name, addr_list in addresses.items():
			info = stats.get(name)
			ips = [addr.address.split("%", 1)[0] for addr in addr_list if addr.family in (socket.AF_INET, socket.AF_INET6)]
			hardware.append({"adapter_id": name, "name": name, "ip_addresses": ips, "is_up": bool(info.isup) if info else None, "link_speed_mbps": float(info.speed) if info and info.speed else None})
			counter = io.get(name)
			previous = self._last_io.get(name)
			entry = {"adapter_id": name}
			if counter:
				entry.update({"total_downloaded_bytes": int(counter.bytes_recv), "total_uploaded_bytes": int(counter.bytes_sent)})
				if previous and elapsed and elapsed > 0:
					entry["download_bytes_per_second"] = max(0.0, (counter.bytes_recv - previous.bytes_recv) / elapsed)
					entry["upload_bytes_per_second"] = max(0.0, (counter.bytes_sent - previous.bytes_sent) / elapsed)
			live.append(entry)
		self._last_io = io
		self._last_time = now
		return {"adapters": hardware}, {"adapters": live}, {"name": "psutil", "status": "available"}, []
