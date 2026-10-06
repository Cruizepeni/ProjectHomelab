from __future__ import annotations

import datetime as dt
import platform

from StatMonitorModuleBase import PollingModule

try:
	import psutil
except ImportError:
	psutil = None


class StatMonitorSystem(PollingModule):
	def collect(self):
		boot = psutil.boot_time() if psutil else None
		uptime = int(dt.datetime.now().timestamp() - boot) if boot else None
		hardware = {"device_name": platform.node(), "operating_system": "macOS", "os_version": platform.mac_ver()[0] or platform.release(), "architecture": platform.machine(), "last_boot_time": dt.datetime.fromtimestamp(boot, dt.timezone.utc).isoformat() if boot else None}
		live = {"uptime_seconds": uptime, "uptime": _format_uptime(uptime)} if uptime is not None else {}
		return hardware, live, {"name": "platform+psutil", "status": "available"}, []


def _format_uptime(seconds):
	if seconds is None:
		return None
	days, rem = divmod(int(seconds), 86400)
	hours, rem = divmod(rem, 3600)
	minutes, secs = divmod(rem, 60)
	return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
