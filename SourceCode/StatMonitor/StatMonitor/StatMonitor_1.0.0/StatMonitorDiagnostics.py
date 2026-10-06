from __future__ import annotations

import inspect
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from StatMonitorPaths import find_app_root, resolve_feature_root


class StatMonitorDiagnostics:
	def __init__(self, project_root: Path, platform_modules, version: str):
		self.project_root = Path(project_root).resolve()
		self.platform = platform_modules
		self.version = str(version)

	def collect(self) -> dict[str, Any]:
		feature_root = resolve_feature_root()
		app_root = find_app_root(feature_root)
		report = {
			"statmonitor": {"version": self.version},
			"platform": {
				"name": self.platform.name,
				"system": platform.system(),
				"release": platform.release(),
				"architecture": platform.machine(),
				"python": platform.python_version(),
			},
			"projecthomelab": {
				"feature_root": str(feature_root),
				"app_root": str(self.project_root),
				"integrated": app_root is not None,
				"app_root_marker": str(app_root / ".AppRoot") if app_root is not None else None,
			},
			"providers": self._providers(),
			"pythofetch": self._pythofetch(),
			"warnings": [],
		}
		if self.platform.name == "Linux":
			report["linux"] = self._linux_details()
			report["warnings"].extend(self._linux_warnings(report["linux"]))
		if report["pythofetch"].get("status") != "ready":
			report["warnings"].append("PythoFetch art is unavailable; the GUI will display Art Unavailable.")
		for name, provider in report["providers"].items():
			if provider.get("status") not in {"ready", "available"}:
				reason = provider.get("reason") or provider.get("provider_status") or "provider unavailable"
				report["warnings"].append(f"{name}: {reason}")
		return report

	def render(self, report: dict[str, Any]) -> str:
		lines = ["STATMONITOR DIAGNOSTICS", ""]
		platform_data = report["platform"]
		lines.extend([
			"Platform",
			f"  OS: {platform_data.get('system')} {platform_data.get('release')}",
			f"  Architecture: {platform_data.get('architecture')}",
			f"  Python: {platform_data.get('python')}",
			f"  StatMonitor: {report['statmonitor'].get('version')}",
			"",
		])
		root = report["projecthomelab"]
		lines.extend([
			"ProjectHomelab",
			f"  Feature Root: {root.get('feature_root')}",
			f"  AppRoot: {root.get('app_root')}",
			f"  Integrated: {'Yes' if root.get('integrated') else 'No'}",
			"",
			"Providers",
		])
		for name, item in report["providers"].items():
			status = str(item.get("status") or "unknown").upper()
			provider = item.get("provider") or "Unknown"
			reason = item.get("reason")
			suffix = f" - {provider}" + (f" ({reason})" if reason else "")
			lines.append(f"  {name:<15} {status:<11}{suffix}")
		pythofetch = report["pythofetch"]
		lines.extend(["", "PythoFetch", f"  Status: {str(pythofetch.get('status') or 'unknown').upper()}"])
		if pythofetch.get("path"):
			lines.append(f"  Path: {pythofetch['path']}")
		if pythofetch.get("reason"):
			lines.append(f"  Detail: {pythofetch['reason']}")
		linux = report.get("linux")
		if isinstance(linux, dict):
			dependencies = linux.get("dependencies", {})
			distribution = dependencies.get("distribution", {})
			installer = dependencies.get("installer", {})
			lines.extend([
				"",
				"Linux Dependencies",
				f"  Distribution: {distribution.get('pretty_name') or 'Unknown'}",
				f"  Package manager: {installer.get('package_manager') or 'Unavailable'}",
				f"  Automatic install: {'READY' if installer.get('supported') else 'UNAVAILABLE'}",
				f"  Elevation: {installer.get('elevation') or 'Unavailable'}",
			])
			for group, title in (("core", "Core"), ("feature", "Feature"), ("hardware", "Hardware-specific")):
				lines.append(f"  {title}:")
				for item in dependencies.get("groups", {}).get(group, []):
					status = "READY" if item.get("ready") else "MISSING"
					package_text = ", ".join(item.get("packages", []))
					suffix = f" [{package_text}]" if package_text else ""
					lines.append(f"    {item.get('label')}: {status}{suffix}")
			lines.extend(["", "Linux Tools"])
			for name, available in linux.get("tools", {}).items():
				lines.append(f"  {name:<18} {'READY' if available else 'MISSING'}")
			lines.extend(["", "Linux Services"])
			for name, state in linux.get("services", {}).items():
				lines.append(f"  {name:<18} {str(state).upper()}")
			hardware = linux.get("hardware_interfaces", {})
			lines.extend([
				"",
				"Hardware Interfaces",
				f"  hwmon devices: {hardware.get('hwmon_devices', 0)}",
				f"  temperature sensors: {hardware.get('temperature_sensors', 0)}",
				f"  fan inputs: {hardware.get('fan_inputs', 0)}",
				f"  PWM controls: {hardware.get('pwm_controls', 0)}",
				f"  DRM devices: {hardware.get('drm_devices', 0)}",
				f"  video devices: {hardware.get('video_devices', 0)}",
				"",
				"Permissions",
			])
			for name, value in linux.get("permissions", {}).items():
				lines.append(f"  {name:<18} {str(value)}")
		warnings = report.get("warnings", [])
		lines.extend(["", "Warnings"])
		if warnings:
			for warning in warnings:
				lines.append(f"  - {warning}")
		else:
			lines.append("  None")
		return "\n".join(lines)

	@staticmethod
	def write_json(report: dict[str, Any], path: str | os.PathLike[str]) -> Path:
		destination = Path(path).expanduser().resolve()
		destination.parent.mkdir(parents=True, exist_ok=True)
		destination.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
		return destination

	def _providers(self) -> dict[str, dict[str, Any]]:
		instances = {}
		result = {}
		order = [
			("CPU", self.platform.CPU, {}),
			("GPU", self.platform.GPU, {}),
			("RAM", self.platform.RAM, {}),
			("System", self.platform.System, {}),
			("Network", self.platform.Network, {}),
			("WiFi", self.platform.WiFi, {}),
			("Motherboard", self.platform.Motherboard, {}),
			("Bluetooth", self.platform.Bluetooth, {}),
			("Storage", self.platform.StorageDrives, {}),
		]
		for name, cls, kwargs in order:
			try:
				module = self._construct(cls, **kwargs)
				instances[name] = module
				result[name] = self._probe_module(module)
			except Exception as error:
				result[name] = {"status": "degraded", "provider": getattr(cls, "__name__", name), "reason": str(error)}
		try:
			power = self._construct(self.platform.Power, cpu_module=instances.get("CPU"), gpu_module=instances.get("GPU"))
			result["Power"] = self._probe_module(power)
		except Exception as error:
			result["Power"] = {"status": "degraded", "provider": "Power", "reason": str(error)}
		if self.platform.Privacy is not None:
			try:
				privacy = self._construct(self.platform.Privacy)
				status = privacy.get_status() if hasattr(privacy, "get_status") else {}
				available = any(bool(item.get("available")) for item in status.values() if isinstance(item, dict))
				result["Privacy"] = {"status": "ready" if available else "unavailable", "provider": "platform privacy controls"}
			except Exception as error:
				result["Privacy"] = {"status": "degraded", "provider": "platform privacy controls", "reason": str(error)}
		if self.platform.StorageTools is not None:
			try:
				storage_tools = self._construct(self.platform.StorageTools)
				caps = storage_tools.get_capabilities()
				result["Drive Tools"] = {"status": "ready" if caps.get("available") else "unavailable", "provider": self.platform.name + " storage tools"}
			except Exception as error:
				result["Drive Tools"] = {"status": "degraded", "provider": self.platform.name + " storage tools", "reason": str(error)}
		try:
			motherboard = instances.get("Motherboard") or self._construct(self.platform.Motherboard)
			fan = self.platform.FanController(motherboard)
			channels = fan.get_channels() if hasattr(fan, "get_channels") else []
			result["Fans"] = {"status": "ready" if channels else "unavailable", "provider": type(fan).__module__.split(".", 1)[0] + " fan control", "channels": len(channels)}
		except Exception as error:
			result["Fans"] = {"status": "degraded", "provider": "fan control", "reason": str(error)}
		return result

	def _probe_module(self, module) -> dict[str, Any]:
		provider = None
		warnings = []
		collect = getattr(module, "collect", None)
		if callable(collect):
			value = collect()
			if isinstance(value, tuple) and len(value) >= 3:
				provider = value[2]
				warnings = value[3] if len(value) >= 4 and isinstance(value[3], list) else []
		else:
			refresh = getattr(module, "_refresh", None)
			if callable(refresh):
				refresh()
			latest = module.get_latest() if hasattr(module, "get_latest") else {}
			provider = latest.get("provider") if isinstance(latest, dict) else None
			warnings = latest.get("warnings", []) if isinstance(latest, dict) else []
		provider = provider if isinstance(provider, dict) else {"name": type(module).__name__, "status": "available"}
		provider_status = str(provider.get("status") or "available").casefold()
		status = "ready" if provider_status == "available" else "degraded" if provider_status == "degraded" else "unavailable"
		entry = {"status": status, "provider": provider.get("name") or type(module).__name__, "provider_status": provider_status}
		if provider.get("reason"):
			entry["reason"] = str(provider["reason"])
		if warnings:
			entry["warnings"] = warnings
		return entry

	def _construct(self, cls, **kwargs):
		signature = inspect.signature(cls)
		if "project_root" in signature.parameters:
			kwargs["project_root"] = self.project_root
		return cls(**kwargs)

	def _pythofetch(self) -> dict[str, Any]:
		extension = ".exe" if self.platform.name == "Windows" else ".AppImage" if self.platform.name == "Linux" else ""
		name = "PythoFetch" + extension
		candidates = [
			self.project_root / "Dependencies" / "StatMonitor" / "PythoFetch" / name,
			self.project_root / name,
			resolve_feature_root() / name,
		]
		found = shutil.which("PythoFetch") or shutil.which(name)
		if found:
			candidates.insert(0, Path(found))
		path = next((candidate for candidate in candidates if candidate.is_file()), None)
		if path is None:
			return {"status": "unavailable", "path": None, "reason": "PythoFetch executable was not found."}
		command = [str(path), "--headless", "--art", "--format", "json"]
		try:
			completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
			fallback = False
			if completed.returncode != 0 and self.platform.name == "Linux" and path.suffix.casefold() == ".appimage":
				environment = os.environ.copy()
				environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"
				completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False, env=environment)
				fallback = completed.returncode == 0
			if completed.returncode != 0:
				reason = completed.stderr.strip() or "PythoFetch was found but its art query failed."
				return {"status": "unavailable", "path": str(path), "reason": reason}
			payload = json.loads(completed.stdout or "{}")
			if not isinstance(payload, dict) or not str(payload.get("art") or "").strip():
				return {"status": "unavailable", "path": str(path), "reason": "PythoFetch returned no artwork."}
			return {"status": "ready", "path": str(path), "appimage_extract_fallback": fallback}
		except Exception as error:
			return {"status": "unavailable", "path": str(path), "reason": str(error)}

	def _linux_details(self) -> dict[str, Any]:
		from Linux.StatMonitorDependencies import probe_linux_system_dependencies
		from Linux.StatMonitorLinuxCommon import hwmon_devices, hwmon_fans, hwmon_temperatures, root_path

		tool_names = ["nmcli", "bluetoothctl", "smartctl", "dmidecode", "lspci", "nvidia-smi", "iwgetid", "wpctl", "pactl", "systemctl", "pkexec", "lsblk", "findmnt", "wipefs", "parted", "partprobe", "umount", "mkfs.ext4", "mkfs.exfat", "mkfs.ntfs", "mkfs.vfat"]
		tools = {name: shutil.which(name) is not None for name in tool_names}
		services = {}
		if tools["systemctl"]:
			for label, units in {
				"NetworkManager": ("NetworkManager.service",),
				"BlueZ": ("bluetooth.service",),
				"GeoClue": ("geoclue.service", "geoclue-demo-agent.service"),
			}.items():
				services[label] = self._service_state(units)
		else:
			services = {"NetworkManager": "unknown", "BlueZ": "unknown", "GeoClue": "unknown"}
		devices = hwmon_devices()
		pwm_paths = []
		for device in devices:
			for path in device["path"].glob("pwm[0-9]*"):
				if re.fullmatch(r"pwm\d+", path.name):
					pwm_paths.append(path)
		drm = root_path("/sys/class/drm")
		drm_devices = len([path for path in drm.glob("card*") if re.fullmatch(r"card\d+", path.name)]) if drm.exists() else 0
		video = root_path("/sys/class/video4linux")
		video_devices = len(list(video.glob("video*"))) if video.exists() else 0
		storage_read = False
		if tools["lsblk"]:
			try:
				storage_read = subprocess.run(["lsblk", "-J"], capture_output=True, text=True, timeout=8, check=False).returncode == 0
			except Exception:
				storage_read = False
		permissions = {
			"fan_read": "READY" if hwmon_fans() or pwm_paths else "NO CHANNELS",
			"fan_control": "READY" if any(os.access(path, os.W_OK) for path in pwm_paths) else "PERMISSION REQUIRED" if pwm_paths else "NO PWM CHANNELS",
			"storage_read": "READY" if storage_read else "UNAVAILABLE",
			"storage_modify": "READY (root)" if os.geteuid() == 0 else "ELEVATION AVAILABLE" if tools["pkexec"] else "PKEXEC MISSING",
		}
		return {
			"dependencies": probe_linux_system_dependencies(),
			"tools": tools,
			"services": services,
			"hardware_interfaces": {
				"hwmon_devices": len(devices),
				"temperature_sensors": len(hwmon_temperatures()),
				"fan_inputs": len(hwmon_fans()),
				"pwm_controls": len(pwm_paths),
				"drm_devices": drm_devices,
				"video_devices": video_devices,
			},
			"permissions": permissions,
		}

	def _service_state(self, units: tuple[str, ...]) -> str:
		for unit in units:
			try:
				completed = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5, check=False)
			except Exception:
				continue
			state = completed.stdout.strip()
			if completed.returncode == 0:
				return state or "active"
		return "inactive"

	@staticmethod
	def _linux_warnings(linux: dict[str, Any]) -> list[str]:
		warnings = []
		dependencies = linux.get("dependencies", {})
		for group in ("core", "feature"):
			for item in dependencies.get("groups", {}).get(group, []):
				if not item.get("ready"):
					packages = ", ".join(item.get("packages", [])) or "manual setup"
					warnings.append(f"{item.get('label')}: unavailable until {packages} is installed/configured.")
		if dependencies.get("missing_packages") and not dependencies.get("installer", {}).get("supported"):
			warnings.append("Automatic Linux dependency installation is unavailable on this distribution; install missing packages with the system package manager.")
		return warnings
