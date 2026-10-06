from __future__ import annotations

import datetime as dt
import platform
from pathlib import Path

from StatMonitorModuleBase import PollingModule

try:
	import psutil
except ImportError:
	psutil = None


class StatMonitorSystem(PollingModule):
	def collect(self):
		os_name = platform.system()
		version = platform.release()
		try:
			values = {}
			for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
				if "=" in line:
					key, value = line.split("=", 1)
					values[key] = value.strip().strip('"')
			os_name = values.get("PRETTY_NAME") or values.get("NAME") or os_name
			version = values.get("VERSION_ID") or version
		except Exception:
			pass
		boot = psutil.boot_time() if psutil else None
		uptime = int(dt.datetime.now().timestamp() - boot) if boot else None
		hardware = {"device_name": platform.node(), "operating_system": os_name, "os_version": version, "architecture": platform.machine(), "last_boot_time": dt.datetime.fromtimestamp(boot, dt.timezone.utc).isoformat() if boot else None}
		live = {"uptime_seconds": uptime, "uptime": _format_uptime(uptime)} if uptime is not None else {}
		return hardware, live, {"name": "platform+psutil", "status": "available"}, []


def _format_uptime(seconds):
	if seconds is None:
		return None
	days, rem = divmod(int(seconds), 86400)
	hours, rem = divmod(rem, 3600)
	minutes, secs = divmod(rem, 60)
	return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
