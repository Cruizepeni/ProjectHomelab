from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from StatMonitorPaths import resolve_project_root


PYTHOFETCH_RELEASE_MANIFEST = "https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Releases/PythoFetch/PythoFetch_Release_Manifest.json"

LINUX_DEPENDENCIES = (
	{"id": "base_storage", "label": "Base storage tools", "group": "core", "commands": ("lsblk", "findmnt", "wipefs", "umount"), "mode": "all", "packages": ("util-linux",)},
	{"id": "privileged_actions", "label": "Per-action administrative elevation", "group": "core", "commands": ("pkexec",), "mode": "all", "packages": ("pkexec",)},
	{"id": "wifi", "label": "Wi-Fi discovery and control", "group": "feature", "commands": ("nmcli",), "mode": "all", "packages": ("network-manager",)},
	{"id": "bluetooth", "label": "Bluetooth discovery and control", "group": "feature", "commands": ("bluetoothctl",), "mode": "all", "packages": ("bluez",)},
	{"id": "smart", "label": "SMART storage health", "group": "feature", "commands": ("smartctl",), "mode": "all", "packages": ("smartmontools",)},
	{"id": "memory_details", "label": "Detailed memory module information", "group": "feature", "commands": ("dmidecode",), "mode": "all", "packages": ("dmidecode",)},
	{"id": "pci", "label": "PCI and GPU discovery", "group": "feature", "commands": ("lspci",), "mode": "all", "packages": ("pciutils",)},
	{"id": "wireless_details", "label": "Wireless SSID details", "group": "feature", "commands": ("iwgetid",), "mode": "all", "packages": ("wireless-tools",)},
	{"id": "microphone", "label": "Microphone control", "group": "feature", "commands": ("wpctl", "pactl"), "mode": "any", "packages": ("pulseaudio-utils",)},
	{"id": "partitioning", "label": "Disk partitioning", "group": "feature", "commands": ("parted", "partprobe"), "mode": "all", "packages": ("parted",)},
	{"id": "ext4", "label": "ext4 formatting", "group": "feature", "commands": ("mkfs.ext4",), "mode": "all", "packages": ("e2fsprogs",)},
	{"id": "exfat", "label": "exFAT formatting", "group": "feature", "commands": ("mkfs.exfat",), "mode": "all", "packages": ("exfatprogs",)},
	{"id": "ntfs", "label": "NTFS formatting", "group": "feature", "commands": ("mkfs.ntfs",), "mode": "all", "packages": ("ntfs-3g",)},
	{"id": "fat32", "label": "FAT32 formatting", "group": "feature", "commands": ("mkfs.vfat",), "mode": "all", "packages": ("dosfstools",)},
	{"id": "nvidia", "label": "NVIDIA telemetry", "group": "hardware", "commands": ("nvidia-smi",), "mode": "all", "packages": ()},
)


class StatMonitorDependencies:
	def __init__(self, project_root=None, interactive=None, quiet=False):
		self.project_root = Path(project_root) if project_root else resolve_project_root()
		self.root = self.project_root / "Dependencies" / "StatMonitor"
		self.pythofetch_directory = self.root / "PythoFetch"
		self.state_path = self.root / "StatMonitorDependencies.json"
		self.interactive = bool(sys.stdin.isatty() and sys.stdout.isatty()) if interactive is None else bool(interactive)
		self.quiet = bool(quiet)

	def ensure(self, force_system_install=False):
		self.root.mkdir(parents=True, exist_ok=True)
		previous = self._read_state()
		try:
			system_dependencies = self._ensure_system_dependencies(previous, force=bool(force_system_install))
		except Exception as error:
			system_dependencies = probe_linux_system_dependencies()
			system_dependencies.update({"status": "limited", "error": str(error)})
		try:
			pythofetch = self._ensure_pythofetch(allow_offline=True)
		except Exception as error:
			pythofetch = {"status": "unavailable", "error": str(error), "releaseManifest": PYTHOFETCH_RELEASE_MANIFEST}
		state = {
			"schemaVersion": 2,
			"platform": "Linux",
			"LinuxSystemDependencies": system_dependencies,
			"PythoFetch": pythofetch,
		}
		self._write_state(state)
		return state

	def ensure_pythofetch(self):
		self.root.mkdir(parents=True, exist_ok=True)
		result = self._ensure_pythofetch(allow_offline=True)
		state = self._read_state()
		state["PythoFetch"] = result
		self._write_state(state)
		return result

	def get_pythofetch_path(self):
		for candidate in self._candidates():
			if candidate and candidate.is_file():
				return candidate
		return None

	def get_pythofetch_art(self):
		path = self.get_pythofetch_path()
		if path is None:
			return ""
		completed = self._run_pythofetch_capture(path, ["--headless", "--art", "--format", "json"], 30)
		if completed is None or completed.returncode != 0:
			return ""
		try:
			payload = json.loads(completed.stdout or "{}")
		except Exception:
			return ""
		if not isinstance(payload, dict):
			return ""
		art = str(payload.get("art") or "")
		palette = payload.get("palette") if isinstance(payload.get("palette"), list) else []
		colors = {}
		for index in range(1, 9):
			if index > len(palette):
				colors[index] = ""
				continue
			try:
				value = int(palette[index - 1])
			except Exception:
				colors[index] = ""
				continue
			if 0 <= value <= 7:
				colors[index] = f"\x1b[1;3{value}m"
			elif 0 <= value <= 255:
				colors[index] = f"\x1b[1;38;5;{value}m"
			else:
				colors[index] = ""
		pattern = re.compile(r"\$\{c([1-8])\}")
		rendered = []
		active = ""
		for raw_line in art.splitlines():
			output = active
			position = 0
			for match in pattern.finditer(raw_line):
				output += raw_line[position:match.start()]
				active = colors.get(int(match.group(1)), "")
				output += active
				position = match.end()
			output += raw_line[position:]
			rendered.append(output + "\x1b[0m")
		return "\n".join(rendered)

	def run_pythofetch(self):
		path = self.get_pythofetch_path()
		if path is None:
			raise RuntimeError("PythoFetch is unavailable")
		completed = self._run_pythofetch_capture(path, [], None)
		if completed is None:
			return 1
		if completed.stdout:
			print(completed.stdout, end="")
		if completed.stderr:
			print(completed.stderr, end="", file=sys.stderr)
		return completed.returncode

	def _run_pythofetch_capture(self, path, arguments, timeout):
		command = [str(path), *arguments]
		kwargs = {"capture_output": True, "text": True, "check": False}
		if timeout is not None:
			kwargs["timeout"] = timeout
		try:
			completed = subprocess.run(command, **kwargs)
		except Exception:
			completed = None
		if completed is not None and completed.returncode == 0:
			return completed
		if Path(path).suffix.casefold() != ".appimage":
			return completed
		environment = os.environ.copy()
		environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"
		try:
			return subprocess.run(command, env=environment, **kwargs)
		except Exception:
			return completed

	def _ensure_system_dependencies(self, previous, force=False):
		report = probe_linux_system_dependencies()
		missing = [item for group in ("core", "feature") for item in report["groups"].get(group, []) if not item["ready"] and item.get("packages")]
		if not missing:
			report["status"] = "ready"
			return report
		fingerprint = _dependency_fingerprint(missing)
		report["fingerprint"] = fingerprint
		prior = previous.get("LinuxSystemDependencies", {}) if isinstance(previous, dict) else {}
		if not force and isinstance(prior, dict) and prior.get("status") == "declined" and prior.get("fingerprint") == fingerprint:
			report["status"] = "declined"
			report["prompt_suppressed"] = True
			return report
		if not report["installer"].get("supported"):
			report["status"] = "limited"
			report["error"] = "Automatic Linux package installation is currently supported on Debian-family systems using apt-get."
			return report
		if not self._confirm_system_install(missing, report):
			report["status"] = "declined"
			return report
		packages = []
		for item in missing:
			for package in item.get("packages", []):
				if package not in packages:
					packages.append(package)
		install = self._install_apt_packages(packages)
		after = probe_linux_system_dependencies()
		after["install"] = install
		after_missing = [item for group in ("core", "feature") for item in after["groups"].get(group, []) if not item["ready"] and item.get("packages")]
		after["fingerprint"] = _dependency_fingerprint(after_missing) if after_missing else None
		after["status"] = "ready" if not after_missing else "limited"
		self._report_system_install_result(after, install, after_missing)
		return after

	def _confirm_system_install(self, missing, report):
		if self.interactive:
			print()
			print("StatMonitor Linux Dependencies")
			print("-" * 60)
			print(f"Detected: {report['distribution'].get('pretty_name') or 'Linux'}")
			print("StatMonitor can install the missing packages required for full feature support:")
			for item in missing:
				print(f"  - {item['label']}: {', '.join(item['packages'])}")
			print()
			try:
				answer = input("Install missing packages now? [Y/n]: ").strip().casefold()
			except Exception:
				return False
			return answer in {"", "y", "yes"}
		if self.quiet:
			return self._confirm_system_install_gui(missing, report)
		return False

	def _confirm_system_install_gui(self, missing, report):
		try:
			import tkinter as tk
			from tkinter import messagebox
			window = tk.Tk()
			window.withdraw()
			packages = []
			for item in missing:
				packages.extend(item.get("packages", []))
			packages = list(dict.fromkeys(packages))
			distro = report["distribution"].get("pretty_name") or "Linux"
			message = "StatMonitor detected missing Linux packages required for full feature support.\n\n"
			message += f"System: {distro}\n\n"
			message += "Packages:\n" + "\n".join(f"• {package}" for package in packages)
			message += "\n\nInstall them automatically now? Administrator authorization will be requested.\n\nChoose No to continue with limited features."
			answer = messagebox.askyesno("StatMonitor Linux dependencies", message, parent=window)
			window.destroy()
			return bool(answer)
		except Exception:
			return False

	def _report_system_install_result(self, report, install, remaining):
		if install.get("success") and not remaining:
			if self.interactive:
				print("Linux dependency installation completed successfully.")
			return
		detail = install.get("error") or "Some Linux dependencies are still unavailable."
		if self.interactive:
			print()
			print("StatMonitor will continue with limited features.")
			print(detail)
			print("Run StatMonitor --diagnostics for the current dependency state.")
		if self.quiet:
			try:
				import tkinter as tk
				from tkinter import messagebox
				window = tk.Tk()
				window.withdraw()
				message = f"StatMonitor could not prepare every Linux dependency.\n\n{detail}\n\nStatMonitor will continue with limited features. Run --diagnostics for details."
				messagebox.showwarning("StatMonitor Linux dependencies", message, parent=window)
				window.destroy()
			except Exception:
				pass

	def _install_apt_packages(self, packages):
		apt_get = shutil.which("apt-get")
		if not apt_get:
			return {"success": False, "error": "apt-get is unavailable", "packages": packages}
		if os.geteuid() != 0 and not shutil.which("pkexec"):
			return {"success": False, "error": "pkexec is required before StatMonitor can install Linux packages automatically", "packages": packages, "manual": f"sudo apt-get install -y {' '.join(packages)}"}
		command = [apt_get, "install", "-y", "--no-install-recommends", *packages]
		first = self._run_privileged(command, 900)
		if first.returncode == 0:
			return {"success": True, "packages": packages, "refreshed_indexes": False}
		update = self._run_privileged([apt_get, "update"], 900)
		if update.returncode != 0:
			return {"success": False, "packages": packages, "stage": "apt-get update", "error": _process_error(update)}
		second = self._run_privileged(command, 900)
		if second.returncode != 0:
			return {"success": False, "packages": packages, "stage": "apt-get install", "error": _process_error(second)}
		return {"success": True, "packages": packages, "refreshed_indexes": True}

	def _run_privileged(self, command, timeout):
		full = list(command) if os.geteuid() == 0 else [shutil.which("pkexec") or "pkexec", *command]
		return subprocess.run(full, capture_output=True, text=True, timeout=timeout, check=False)

	def _ensure_pythofetch(self, allow_offline=True):
		managed = self.pythofetch_directory / "PythoFetch.AppImage"
		try:
			manifest = self._download_json(PYTHOFETCH_RELEASE_MANIFEST)
			target = self._target(manifest)
		except Exception:
			if allow_offline and managed.is_file():
				return {"status": "available", "source": "managed", "executable": str(managed), "offline": True}
			existing = self._existing_any()
			if allow_offline and existing:
				return {"status": "available", "source": "existing", "executable": str(existing), "offline": True}
			raise
		existing = self._matching_existing(target)
		if existing:
			return {"version": target["version"], "status": "available", "source": "existing", "executable": str(existing), "executableSha256": target.get("executable_sha256"), "releaseManifest": PYTHOFETCH_RELEASE_MANIFEST}
		self.pythofetch_directory.mkdir(parents=True, exist_ok=True)
		with tempfile.TemporaryDirectory(prefix="StatMonitor-PythoFetch-") as temp:
			temp_path = Path(temp)
			asset = temp_path / target["file"]
			self._download(target["download_url"], asset)
			if target.get("sha256") and self._sha256(asset) != target["sha256"]:
				raise RuntimeError("PythoFetch download SHA-256 verification failed")
			if asset.suffix.casefold() == ".zip":
				with zipfile.ZipFile(asset) as archive:
					archive.extractall(temp_path / "extract")
				candidates = list((temp_path / "extract").rglob(target.get("executable_name") or "PythoFetch.AppImage"))
				if not candidates:
					raise RuntimeError("PythoFetch archive did not contain its AppImage")
				source = candidates[0]
			else:
				source = asset
			shutil.copy2(source, managed)
		managed.chmod(managed.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
		if target.get("executable_sha256") and self._sha256(managed) != target["executable_sha256"]:
			raise RuntimeError("Installed PythoFetch AppImage verification failed")
		return {"version": target["version"], "status": "installed", "source": "managed", "executable": str(managed), "executableSha256": target.get("executable_sha256"), "releaseManifest": PYTHOFETCH_RELEASE_MANIFEST}

	def _target(self, manifest):
		version = str(manifest.get("latest_version") or "").strip()
		releases = manifest.get("releases") if isinstance(manifest, dict) else None
		if not version or not isinstance(releases, dict) or not isinstance(releases.get(version), dict):
			raise RuntimeError("Invalid PythoFetch release manifest")
		assets = releases[version].get("assets") or {}
		machine = platform.machine().casefold()
		keys = ["Linux_arm64", "Linux_aarch64"] if machine in {"aarch64", "arm64"} else ["Linux_x86_64", "Linux_amd64"]
		asset = next((assets.get(key) for key in keys if isinstance(assets.get(key), dict)), None)
		if not asset:
			raise RuntimeError(f"PythoFetch {version} does not provide a Linux asset for {platform.machine()}")
		url = str(asset.get("download_url") or "").strip()
		if not url.startswith("https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/"):
			raise RuntimeError("Refusing unexpected PythoFetch download host")
		return {"version": version, "file": str(asset.get("file") or Path(url).name), "download_url": url, "sha256": _digest(asset.get("sha256")), "executable_name": str(asset.get("executable") or "PythoFetch.AppImage"), "executable_sha256": _digest(asset.get("executable_sha256"))}

	def _matching_existing(self, target):
		expected = target.get("executable_sha256")
		for candidate in self._candidates():
			try:
				if candidate.is_file() and (not expected or self._sha256(candidate) == expected):
					return candidate
			except Exception:
				pass
		return None

	def _existing_any(self):
		return next((path for path in self._candidates() if path and path.is_file()), None)

	def _candidates(self):
		paths = [self.pythofetch_directory / "PythoFetch.AppImage", self.project_root / "PythoFetch.AppImage", Path.cwd() / "PythoFetch.AppImage"]
		found = shutil.which("PythoFetch") or shutil.which("PythoFetch.AppImage")
		if found:
			paths.insert(0, Path(found))
		state = self._read_state().get("PythoFetch", {})
		if isinstance(state, dict) and state.get("executable"):
			paths.insert(0, Path(str(state["executable"])))
		seen = set()
		result = []
		for path in paths:
			value = str(path)
			if value not in seen:
				seen.add(value)
				result.append(path)
		return result

	@staticmethod
	def _download_json(url):
		with urllib.request.urlopen(url, timeout=15) as response:
			return json.loads(response.read().decode("utf-8"))

	@staticmethod
	def _download(url, destination):
		with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as output:
			shutil.copyfileobj(response, output)

	@staticmethod
	def _sha256(path):
		digest = hashlib.sha256()
		with Path(path).open("rb") as stream:
			for chunk in iter(lambda: stream.read(1024 * 1024), b""):
				digest.update(chunk)
		return digest.hexdigest().lower()

	def _read_state(self):
		try:
			value = json.loads(self.state_path.read_text(encoding="utf-8"))
			return value if isinstance(value, dict) else {}
		except Exception:
			return {}

	def _write_state(self, value):
		self.state_path.parent.mkdir(parents=True, exist_ok=True)
		temp = self.state_path.with_suffix(".tmp")
		temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
		os.replace(temp, self.state_path)


def probe_linux_system_dependencies():
	distribution = _linux_distribution()
	groups = {"core": [], "feature": [], "hardware": []}
	for spec in LINUX_DEPENDENCIES:
		commands = list(spec["commands"])
		found = {command: shutil.which(command) is not None for command in commands}
		ready = all(found.values()) if spec["mode"] == "all" else any(found.values())
		groups[spec["group"]].append({
			"id": spec["id"],
			"label": spec["label"],
			"ready": ready,
			"commands": found,
			"packages": list(spec["packages"]),
			"auto_install": bool(spec["packages"]) and spec["group"] != "hardware",
		})
	apt_get = shutil.which("apt-get")
	family = {str(distribution.get("id") or "").casefold(), *[item.casefold() for item in distribution.get("id_like", [])]}
	debian_family = bool({"debian", "ubuntu", "raspbian"} & family) or Path("/etc/debian_version").exists()
	missing_packages = []
	for group in ("core", "feature"):
		for item in groups[group]:
			if not item["ready"]:
				for package in item["packages"]:
					if package not in missing_packages:
						missing_packages.append(package)
	return {
		"distribution": distribution,
		"groups": groups,
		"missing_packages": missing_packages,
		"installer": {
			"package_manager": "apt-get" if apt_get else None,
			"supported": bool(apt_get and debian_family),
			"elevation": "root" if os.geteuid() == 0 else "pkexec" if shutil.which("pkexec") else None,
		},
	}


def _linux_distribution():
	values = {}
	try:
		for raw in Path("/etc/os-release").read_text(encoding="utf-8", errors="ignore").splitlines():
			if "=" not in raw:
				continue
			key, value = raw.split("=", 1)
			values[key.strip()] = value.strip().strip('"').strip("'")
	except Exception:
		pass
	return {
		"id": values.get("ID") or "linux",
		"id_like": str(values.get("ID_LIKE") or "").split(),
		"version_id": values.get("VERSION_ID"),
		"pretty_name": values.get("PRETTY_NAME") or platform.platform(),
	}


def _dependency_fingerprint(items):
	value = "|".join(sorted(str(item.get("id") or "") for item in items))
	return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _process_error(completed):
	message = str(getattr(completed, "stderr", "") or "").strip() or str(getattr(completed, "stdout", "") or "").strip()
	return message[-4000:] if message else f"exit code {getattr(completed, 'returncode', 'unknown')}"


def _digest(value):
	text = str(value or "").strip().lower()
	return text if len(text) == 64 and all(character in "0123456789abcdef" for character in text) else None
