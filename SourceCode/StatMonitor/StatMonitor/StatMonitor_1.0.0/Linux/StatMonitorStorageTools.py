from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class StatMonitorStorageTools:
	def __init__(self, project_root: Path | None = None):
		self.project_root = Path(project_root) if project_root is not None else Path.cwd()

	def handle_command(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
		arguments = dict(arguments or {})
		if command in {"GetStorageToolDisks", "RefreshStorageToolDisks"}:
			return {"success": True, "disks": self.get_disks(), "capabilities": self.get_capabilities()}
		if command == "GetStorageToolCapabilities":
			return {"success": True, "capabilities": self.get_capabilities()}
		if command == "CleanStorageDisk":
			identifier = arguments.get("disk_number")
			if identifier is None:
				identifier = arguments.get("device")
			expected = f"ERASE DISK {identifier}"
			if str(arguments.get("confirmation") or "").strip() != expected:
				return {"success": False, "error": "confirmation_required", "message": f"Confirmation must exactly match: {expected}"}
			return self.clean_disk(identifier)
		if command == "PrepareStorageDisk":
			identifier = arguments.get("disk_number")
			if identifier is None:
				identifier = arguments.get("device")
			expected = f"ERASE DISK {identifier}"
			if str(arguments.get("confirmation") or "").strip() != expected:
				return {"success": False, "error": "confirmation_required", "message": f"Confirmation must exactly match: {expected}"}
			return self.prepare_disk(identifier, arguments.get("partition_style"), arguments.get("filesystem"), arguments.get("label"))
		if command == "FormatStoragePartition":
			identifier = arguments.get("disk_number")
			if identifier is None:
				identifier = arguments.get("device")
			partition = arguments.get("partition_number")
			if partition is None:
				partition = arguments.get("partition_device")
			expected = f"FORMAT DISK {identifier} PARTITION {partition}"
			if str(arguments.get("confirmation") or "").strip() != expected:
				return {"success": False, "error": "confirmation_required", "message": f"Confirmation must exactly match: {expected}"}
			return self.format_partition(identifier, partition, arguments.get("filesystem"), arguments.get("label"))
		return {"success": False, "error": "unknown_command", "command": command}

	def get_capabilities(self) -> dict[str, Any]:
		return {
			"available": shutil.which("lsblk") is not None,
			"platform": "Linux",
			"partition_styles": ["GPT", "MBR"],
			"filesystems": ["ext4", "exFAT", "NTFS", "FAT32", "None"],
			"requires_root_for_changes": False,
			"requires_elevation_for_changes": os.geteuid() != 0,
			"elevation_available": os.geteuid() == 0 or shutil.which("pkexec") is not None,
			"elevation_method": "root" if os.geteuid() == 0 else "pkexec" if shutil.which("pkexec") else None,
			"presets": [
				{"name": "Linux Storage", "partition_style": "GPT", "filesystem": "ext4"},
				{"name": "Portable Storage", "partition_style": "GPT", "filesystem": "exFAT"},
				{"name": "Windows Storage", "partition_style": "GPT", "filesystem": "NTFS"},
				{"name": "Legacy USB", "partition_style": "MBR", "filesystem": "FAT32"},
				{"name": "Blank GPT Disk", "partition_style": "GPT", "filesystem": "None"},
			],
		}

	def get_disks(self) -> list[dict[str, Any]]:
		if shutil.which("lsblk") is None:
			return []
		fields = "NAME,KNAME,PATH,TYPE,SIZE,MODEL,SERIAL,TRAN,PTTYPE,FSTYPE,LABEL,MOUNTPOINTS,RO,HOTPLUG,PKNAME"
		completed = subprocess.run(["lsblk", "-J", "-b", "-o", fields], capture_output=True, text=True, timeout=12, check=False)
		if completed.returncode != 0:
			raise RuntimeError(" ".join((completed.stderr or "lsblk failed").split()))
		payload = json.loads(completed.stdout or "{}")
		root_source = self._mount_source("/")
		project_source = self._mount_source(str(self.project_root.resolve()))
		root_parent = self._root_device(root_source)
		project_parent = self._root_device(project_source)
		result = []
		for device in payload.get("blockdevices", []) if isinstance(payload, dict) else []:
			if not isinstance(device, dict) or device.get("type") != "disk":
				continue
			parts = []
			for index, child in enumerate(device.get("children", []) or []):
				if not isinstance(child, dict):
					continue
				mounts = child.get("mountpoints") or []
				if isinstance(mounts, str):
					mounts = [mounts]
				parts.append({
					"partition_number": index + 1,
					"path": child.get("path"),
					"name": child.get("name"),
					"size": child.get("size"),
					"filesystem": child.get("fstype"),
					"label": child.get("label"),
					"mountpoints": [item for item in mounts if item],
				})
			path = str(device.get("path") or "")
			reasons = []
			if path and root_parent == path:
				reasons.append("Linux root/system disk")
			if path and project_parent == path:
				reasons.append("contains the running ProjectHomelab/StatMonitor files")
			result.append({
				"disk_number": path,
				"device": path,
				"friendly_name": device.get("model") or device.get("name") or path,
				"serial_number": device.get("serial"),
				"bus_type": device.get("tran"),
				"size": device.get("size"),
				"partition_style": str(device.get("pttype") or "RAW").upper(),
				"operational_status": ["Read Only" if device.get("ro") else "Online"],
				"health_status": None,
				"is_read_only": bool(device.get("ro")),
				"is_offline": False,
				"protected": bool(reasons),
				"protected_reasons": reasons,
				"partitions": parts,
			})
		return result

	def clean_disk(self, value: Any) -> dict[str, Any]:
		device, disk = self._validated_disk(value)
		guard = self._change_guard(disk)
		if guard:
			return guard
		if shutil.which("wipefs") is None:
			return {"success": False, "error": "missing_tool", "message": "wipefs is required for Linux drive cleaning."}
		for part in disk.get("partitions", []):
			for mountpoint in part.get("mountpoints", []) or []:
				completed = self._run_change(["umount", mountpoint], 30)
				if completed.returncode != 0:
					return {"success": False, "error": "unmount_failed", "message": self._error(completed)}
		completed = self._run_change(["wipefs", "-a", "--force", device], 90)
		if completed.returncode != 0:
			return {"success": False, "error": "clean_failed", "message": self._error(completed)}
		if shutil.which("partprobe"):
			self._run_change(["partprobe", device], 20)
		time.sleep(0.5)
		disks = self.get_disks()
		updated = next((item for item in disks if str(item.get("device")) == device), None)
		if updated is not None and updated.get("partitions"):
			return {"success": False, "error": "clean_verification_failed", "message": "Linux completed the clean operation but partitions are still reported on the selected disk.", "disks": disks}
		return {"success": True, "operation": "clean", "device": device, "disks": disks}

	def prepare_disk(self, value: Any, partition_style: Any, filesystem: Any, label: Any = None) -> dict[str, Any]:
		device, disk = self._validated_disk(value)
		guard = self._change_guard(disk)
		if guard:
			return guard
		style = str(partition_style or "GPT").upper()
		if style not in {"GPT", "MBR"}:
			return {"success": False, "error": "invalid_partition_style", "message": "Partition style must be GPT or MBR."}
		fs = self._normalize_filesystem(filesystem)
		if fs is None:
			return {"success": False, "error": "invalid_filesystem", "message": "Unsupported filesystem."}
		for command in ("wipefs", "parted"):
			if shutil.which(command) is None:
				return {"success": False, "error": "missing_tool", "message": f"{command} is required for Linux drive preparation."}
		clean = self.clean_disk(device)
		if not clean.get("success"):
			return clean
		label_type = "gpt" if style == "GPT" else "msdos"
		completed = self._run_change(["parted", "-s", device, "mklabel", label_type, "mkpart", "primary", "1MiB", "100%"], 90)
		if completed.returncode != 0:
			return {"success": False, "error": "partition_failed", "message": self._error(completed)}
		if shutil.which("partprobe"):
			self._run_change(["partprobe", device], 20)
		time.sleep(1.0)
		partition = self._first_partition(device)
		if not partition:
			return {"success": False, "error": "partition_not_found", "message": "Linux created the partition table but the new partition was not detected."}
		if fs != "None":
			formatted = self._format_device(partition, fs, str(label or "StatMonitor Drive"))
			if not formatted.get("success"):
				return formatted
		time.sleep(0.5)
		disks = self.get_disks()
		updated = next((item for item in disks if str(item.get("device")) == device), None)
		if updated is None:
			return {"success": False, "error": "prepare_verification_failed", "message": "The prepared disk could not be rediscovered after the operation.", "disks": disks}
		reported_style = str(updated.get("partition_style") or "").upper()
		style_matches = reported_style == style or style == "MBR" and reported_style in {"DOS", "MBR"}
		if not style_matches:
			return {"success": False, "error": "prepare_verification_failed", "message": f"The disk reports partition style {reported_style or 'Unknown'} instead of {style}.", "disks": disks}
		if fs != "None":
			prepared_partition = next((item for item in updated.get("partitions", []) if str(item.get("path")) == partition), None)
			if prepared_partition is None or not self._filesystem_matches(prepared_partition.get("filesystem"), fs):
				return {"success": False, "error": "prepare_verification_failed", "message": f"The new partition did not verify as {fs}.", "disks": disks}
		return {"success": True, "operation": "prepare", "device": device, "partition_style": style, "filesystem": fs, "disks": disks}

	def format_partition(self, value: Any, partition_value: Any, filesystem: Any, label: Any = None) -> dict[str, Any]:
		device, disk = self._validated_disk(value)
		guard = self._change_guard(disk)
		if guard:
			return guard
		partition = None
		selected = None
		if isinstance(partition_value, str) and partition_value.startswith("/dev/"):
			selected = next((item for item in disk.get("partitions", []) if str(item.get("path")) == partition_value), None)
			partition = selected.get("path") if selected else None
		else:
			try:
				index = int(partition_value)
			except (TypeError, ValueError):
				index = -1
			selected = next((item for item in disk.get("partitions", []) if int(item.get("partition_number", -2)) == index), None)
			partition = selected.get("path") if selected else None
		if selected is not None:
			for mountpoint in selected.get("mountpoints", []) or []:
				completed = self._run_change(["umount", mountpoint], 30)
				if completed.returncode != 0:
					return {"success": False, "error": "unmount_failed", "message": self._error(completed)}
		if not partition:
			return {"success": False, "error": "partition_not_found", "message": "The selected partition no longer exists."}
		fs = self._normalize_filesystem(filesystem)
		if fs in {None, "None"}:
			return {"success": False, "error": "invalid_filesystem", "message": "Quick format requires a filesystem."}
		result = self._format_device(partition, fs, str(label or "StatMonitor Drive"))
		if not result.get("success"):
			return result
		time.sleep(0.5)
		disks = self.get_disks()
		updated = next((item for item in disks if str(item.get("device")) == device), None)
		updated_partition = next((item for item in (updated.get("partitions", []) if isinstance(updated, dict) else []) if str(item.get("path")) == partition), None)
		if updated_partition is None or not self._filesystem_matches(updated_partition.get("filesystem"), fs):
			return {"success": False, "error": "format_verification_failed", "message": f"The partition did not verify as {fs} after formatting.", "disks": disks}
		result.update({"device": device, "partition_device": partition, "disks": disks})
		return result

	def _format_device(self, partition: str, filesystem: str, label: str) -> dict[str, Any]:
		commands = {
			"ext4": (["mkfs.ext4", "-F", "-L", label[:16], partition], "mkfs.ext4"),
			"exFAT": (["mkfs.exfat", "-n", label[:15], partition], "mkfs.exfat"),
			"NTFS": (["mkfs.ntfs", "-F", "-L", label[:32], partition], "mkfs.ntfs"),
			"FAT32": (["mkfs.vfat", "-F", "32", "-n", label[:11], partition], "mkfs.vfat"),
		}
		command, tool = commands[filesystem]
		if shutil.which(tool) is None:
			return {"success": False, "error": "missing_tool", "message": f"{tool} is required to format {filesystem}."}
		completed = self._run_change(command, 180)
		if completed.returncode != 0:
			return {"success": False, "error": "format_failed", "message": self._error(completed)}
		return {"success": True, "operation": "format", "filesystem": filesystem}

	def _validated_disk(self, value: Any) -> tuple[str, dict[str, Any]]:
		text = str(value or "").strip()
		disk = next((item for item in self.get_disks() if text in {str(item.get("device")), str(item.get("disk_number"))}), None)
		if disk is None:
			raise ValueError("The selected physical disk was not found")
		return str(disk.get("device")), disk

	def _change_guard(self, disk: dict[str, Any]) -> dict[str, Any] | None:
		if disk.get("protected"):
			return {"success": False, "error": "protected_disk", "message": "StatMonitor will not perform destructive operations on this disk: " + "; ".join(disk.get("protected_reasons", []))}
		if disk.get("is_read_only"):
			return {"success": False, "error": "read_only_disk", "message": "The selected physical disk is read-only."}
		if os.geteuid() != 0 and shutil.which("pkexec") is None:
			return {"success": False, "error": "elevation_unavailable", "message": "Linux storage changes need temporary administrative authorization, but pkexec is unavailable."}
		return None

	def _first_partition(self, device: str) -> str | None:
		completed = subprocess.run(["lsblk", "-J", "-o", "PATH,TYPE", device], capture_output=True, text=True, timeout=12, check=False)
		try:
			payload = json.loads(completed.stdout or "{}")
		except json.JSONDecodeError:
			return None
		for disk in payload.get("blockdevices", []) or []:
			for child in disk.get("children", []) or []:
				if child.get("type") == "part" and child.get("path"):
					return str(child["path"])
		return None

	def _mount_source(self, path: str) -> str | None:
		if shutil.which("findmnt") is None:
			return None
		completed = subprocess.run(["findmnt", "-n", "-o", "SOURCE", "--target", path], capture_output=True, text=True, timeout=8, check=False)
		return completed.stdout.strip() or None

	def _root_device(self, source: str | None) -> str | None:
		if not source or not source.startswith("/dev/"):
			return None
		current = source
		for _ in range(4):
			completed = subprocess.run(["lsblk", "-n", "-o", "PKNAME", current], capture_output=True, text=True, timeout=8, check=False)
			parent = completed.stdout.strip().splitlines()[0].strip() if completed.stdout.strip() else ""
			if not parent:
				return current
			current = "/dev/" + parent
		return current

	@staticmethod
	def _normalize_filesystem(value: Any) -> str | None:
		mapping = {"ext4": "ext4", "exfat": "exFAT", "ntfs": "NTFS", "fat32": "FAT32", "vfat": "FAT32", "none": "None", "raw": "None", "": "None"}
		return mapping.get(str(value or "None").strip().casefold())

	def _run_change(self, command: list[str], timeout: int) -> subprocess.CompletedProcess:
		if os.geteuid() == 0:
			return self._run(command, timeout)
		pkexec = shutil.which("pkexec")
		if pkexec is None:
			return subprocess.CompletedProcess(command, 126, "", "pkexec is unavailable")
		return self._run([pkexec, *command], timeout)

	@staticmethod
	def _filesystem_matches(reported: Any, requested: str) -> bool:
		aliases = {"exfat": "exfat", "ntfs": "ntfs", "ntfs3": "ntfs", "vfat": "fat32", "fat": "fat32", "fat32": "fat32", "ext4": "ext4"}
		return aliases.get(str(reported or "").casefold(), str(reported or "").casefold()) == aliases.get(str(requested or "").casefold(), str(requested or "").casefold())

	@staticmethod
	def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess:
		return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)

	@staticmethod
	def _error(completed: subprocess.CompletedProcess) -> str:
		return " ".join(str(completed.stderr or completed.stdout or "Storage operation failed").split())[:1200]
