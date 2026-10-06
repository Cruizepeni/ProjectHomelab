from __future__ import annotations

import socket
import time
from pathlib import Path

from StatMonitorModuleBase import PollingModule
from Linux.StatMonitorLinuxCommon import read_text, root_path

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
		wireless = _wireless_signal()
		hardware, live = [], []
		total_down = total_up = 0.0
		for name, addr_list in addresses.items():
			info = stats.get(name)
			ips, mac = [], None
			for addr in addr_list:
				if addr.family in (socket.AF_INET, socket.AF_INET6):
					ips.append(addr.address.split("%", 1)[0])
				elif getattr(socket, "AF_PACKET", object()) == addr.family or str(addr.family).endswith("AF_LINK"):
					mac = addr.address
			kind = "WiFi" if name in wireless or name.startswith(("wl", "wlan")) else "Loopback" if name == "lo" else "Ethernet" if name.startswith(("en", "eth")) else "Virtual/Other"
			carrier = read_text(f"/sys/class/net/{name}/carrier")
			operstate = read_text(f"/sys/class/net/{name}/operstate")
			connected = bool(info.isup) if info else operstate == "up"
			hardware.append({"adapter_id": name, "name": name, "connection_type": kind, "ip_addresses": ips, "mac_address": mac, "is_up": connected, "connected": connected, "state": operstate, "link_speed_mbps": float(info.speed) if info and info.speed else None, "network_name": _ssid(name) if kind == "WiFi" else None})
			counter = io.get(name)
			previous = self._last_io.get(name)
			entry = {"adapter_id": name}
			if counter:
				entry.update({"total_downloaded_bytes": int(counter.bytes_recv), "total_uploaded_bytes": int(counter.bytes_sent)})
				if previous and elapsed and elapsed > 0:
					down = max(0.0, (counter.bytes_recv - previous.bytes_recv) / elapsed)
					up = max(0.0, (counter.bytes_sent - previous.bytes_sent) / elapsed)
					entry["download_bytes_per_sec"] = down
					entry["upload_bytes_per_sec"] = up
					total_down += down
					total_up += up
			if name in wireless:
				entry["signal_quality_percent"] = wireless[name]
			live.append(entry)
		self._last_io, self._last_time = io, now
		return {"adapters": hardware}, {"adapters": live, "download_bytes_per_sec": total_down, "upload_bytes_per_sec": total_up, "total_received_bytes": sum(int(x.bytes_recv) for x in io.values()), "total_sent_bytes": sum(int(x.bytes_sent) for x in io.values())}, {"name": "psutil+/proc+/sys", "status": "available"}, []


def _wireless_signal():
	result = {}
	try:
		path = root_path("/proc/net/wireless")
		lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[2:]
		for line in lines:
			if ":" not in line:
				continue
			name, rest = line.split(":", 1)
			parts = rest.split()
			if len(parts) >= 3:
				level = float(parts[2].rstrip("."))
				result[name.strip()] = round(max(0.0, min(100.0, 2.0 * (level + 100.0))), 1)
	except Exception:
		pass
	return result


def _ssid(interface):
	try:
		import subprocess
		completed = subprocess.run(["iwgetid", interface, "--raw"], capture_output=True, text=True, timeout=2, check=False)
		return completed.stdout.strip() or None
	except Exception:
		return None
