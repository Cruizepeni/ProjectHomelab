from __future__ import annotations

import json
import subprocess

from StatMonitorModuleBase import PollingModule


class StatMonitorGPU(PollingModule):
	interval_seconds = 5.0

	def __init__(self, project_root=None):
		super().__init__()
		self._internal_power_consumers = set()

	def set_internal_power_request(self, consumer_id, enabled):
		if enabled:
			self._internal_power_consumers.add(str(consumer_id))
		else:
			self._internal_power_consumers.discard(str(consumer_id))

	def get_internal_power_w(self):
		return None

	def collect(self):
		gpus = []
		try:
			completed = subprocess.run(["system_profiler", "-json", "SPDisplaysDataType"], capture_output=True, text=True, timeout=10, check=False)
			data = json.loads(completed.stdout or "{}")
			for index, item in enumerate(data.get("SPDisplaysDataType", []) or []):
				name = item.get("sppci_model") or item.get("_name")
				vendor = item.get("spdisplays_vendor")
				vram = item.get("spdisplays_vram") or item.get("spdisplays_vram_shared")
				gpus.append({"gpu_id": f"display-{index}", "name": name, "vendor": vendor, "graphics_type": "Integrated" if "shared" in str(vram).lower() else "Unknown", "vram_text": vram, "availability_state": "available"})
		except Exception:
			pass
		return {"gpus": gpus}, {"gpus": [{"gpu_id": gpu["gpu_id"]} for gpu in gpus]}, {"name": "system_profiler", "status": "partial"}, []
