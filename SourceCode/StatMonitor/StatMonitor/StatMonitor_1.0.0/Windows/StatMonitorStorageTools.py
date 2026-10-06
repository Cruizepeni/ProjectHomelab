from __future__ import annotations

import ctypes
import json
import os
import subprocess
import tempfile
from ctypes import wintypes
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
			return self.prepare_disk(
				identifier,
				arguments.get("partition_style"),
				arguments.get("filesystem"),
				arguments.get("label"),
			)
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
			return self.format_partition(
				identifier,
				partition,
				arguments.get("filesystem"),
				arguments.get("label"),
			)
		return {"success": False, "error": "unknown_command", "command": command}

	def get_capabilities(self) -> dict[str, Any]:
		return {
			"available": True,
			"platform": "Windows",
			"partition_styles": ["GPT", "MBR"],
			"filesystems": ["NTFS", "exFAT", "FAT32", "None"],
			"presets": [
				{"name": "Windows Storage", "partition_style": "GPT", "filesystem": "NTFS"},
				{"name": "Portable Storage", "partition_style": "GPT", "filesystem": "exFAT"},
				{"name": "Legacy USB", "partition_style": "MBR", "filesystem": "FAT32"},
				{"name": "Blank GPT Disk", "partition_style": "GPT", "filesystem": "None"},
			],
		}

	def get_disks(self) -> list[dict[str, Any]]:
		script = r'''
$ErrorActionPreference = 'Stop'
$result = @(Get-Disk | Sort-Object Number | ForEach-Object {
    $disk = $_
    $parts = @(Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue | Sort-Object PartitionNumber | ForEach-Object {
        $partition = $_
        $volume = $partition | Get-Volume -ErrorAction SilentlyContinue
        [pscustomobject]@{
            partition_number = [int]$partition.PartitionNumber
            drive_letter = if ($partition.DriveLetter) { [string]$partition.DriveLetter } else { $null }
            size = [int64]$partition.Size
            offset = [int64]$partition.Offset
            type = [string]$partition.Type
            gpt_type = [string]$partition.GptType
            mbr_type = [string]$partition.MbrType
            is_boot = [bool]$partition.IsBoot
            is_system = [bool]$partition.IsSystem
            is_active = [bool]$partition.IsActive
            access_paths = @($partition.AccessPaths | ForEach-Object { [string]$_ })
            filesystem = if ($volume) { [string]$volume.FileSystem } else { $null }
            label = if ($volume) { [string]$volume.FileSystemLabel } else { $null }
            volume_health = if ($volume) { [string]$volume.HealthStatus } else { $null }
            volume_size = if ($volume) { [int64]$volume.Size } else { $null }
            volume_free = if ($volume) { [int64]$volume.SizeRemaining } else { $null }
        }
    })
    [pscustomobject]@{
        disk_number = [int]$disk.Number
        friendly_name = [string]$disk.FriendlyName
        serial_number = [string]$disk.SerialNumber
        bus_type = [string]$disk.BusType
        size = [int64]$disk.Size
        partition_style = [string]$disk.PartitionStyle
        operational_status = @($disk.OperationalStatus | ForEach-Object { [string]$_ })
        health_status = [string]$disk.HealthStatus
        is_boot = [bool]$disk.IsBoot
        is_system = [bool]$disk.IsSystem
        is_read_only = [bool]$disk.IsReadOnly
        is_offline = [bool]$disk.IsOffline
        is_clustered = [bool]$disk.IsClustered
        unique_id = [string]$disk.UniqueId
        location = [string]$disk.Location
        partitions = $parts
    }
})
@($result) | ConvertTo-Json -Depth 7 -Compress
'''
		completed = self._powershell(script, timeout=20)
		if completed.returncode != 0:
			raise RuntimeError(self._powershell_error(completed))
		text = completed.stdout.strip()
		if not text:
			return []
		payload = json.loads(text)
		if isinstance(payload, dict):
			payload = [payload]
		result = []
		project_drive = self._project_drive_letter()
		for item in payload if isinstance(payload, list) else []:
			if not isinstance(item, dict):
				continue
			parts = item.get("partitions")
			if isinstance(parts, dict):
				parts = [parts]
			if not isinstance(parts, list):
				parts = []
			item["partitions"] = [part for part in parts if isinstance(part, dict)]
			reasons = []
			if item.get("is_boot"):
				reasons.append("Windows boot disk")
			if item.get("is_system"):
				reasons.append("Windows system disk")
			if project_drive and any(str(part.get("drive_letter") or "").upper() == project_drive for part in item["partitions"]):
				reasons.append("contains the running ProjectHomelab/StatMonitor files")
			if item.get("is_clustered"):
				reasons.append("cluster-managed disk")
			item["protected"] = bool(reasons)
			item["protected_reasons"] = reasons
			result.append(item)
		return result

	def clean_disk(self, disk_number: Any) -> dict[str, Any]:
		number, disk = self._validated_disk(disk_number)
		if disk.get("protected"):
			return self._protected_result(disk)
		completed = self._diskpart([
			f"select disk {number}",
			"online disk noerr",
			"attributes disk clear readonly noerr",
			"clean",
		], timeout=120)
		if completed.returncode != 0:
			return {"success": False, "error": "clean_failed", "message": self._command_error(completed, "DiskPart clean operation failed")}
		disks = self.get_disks()
		updated = next((item for item in disks if int(item.get("disk_number", -1)) == number), None)
		if updated is None or updated.get("partitions") or str(updated.get("partition_style") or "").upper() != "RAW":
			return {"success": False, "error": "clean_verification_failed", "message": "DiskPart completed but the disk did not verify as blank/RAW."}
		return {"success": True, "disk_number": number, "operation": "clean", "disks": disks}

	def prepare_disk(self, disk_number: Any, partition_style: Any, filesystem: Any, label: Any = None) -> dict[str, Any]:
		number, disk = self._validated_disk(disk_number)
		if disk.get("protected"):
			return self._protected_result(disk)
		style = str(partition_style or "GPT").strip().upper()
		if style not in {"GPT", "MBR"}:
			return {"success": False, "error": "invalid_partition_style", "message": "Partition style must be GPT or MBR."}
		fs = self._normalize_filesystem(filesystem)
		if fs is None:
			return {"success": False, "error": "invalid_filesystem", "message": "Filesystem must be NTFS, exFAT, FAT32, or None."}
		label_text = self._diskpart_label(label or "StatMonitor Drive")
		commands = [
			f"select disk {number}",
			"online disk noerr",
			"attributes disk clear readonly noerr",
			"clean",
			f"convert {style.lower()}",
			"create partition primary",
		]
		if fs != "None":
			commands.append(f'format fs={fs.lower()} label="{label_text}" quick')
		commands.append("assign noerr")
		completed = self._diskpart(commands, timeout=180)
		if completed.returncode != 0:
			return {"success": False, "error": "prepare_failed", "message": self._command_error(completed, "DiskPart prepare operation failed")}
		disks = self.get_disks()
		updated = next((item for item in disks if int(item.get("disk_number", -1)) == number), None)
		parts = updated.get("partitions", []) if isinstance(updated, dict) else []
		verified_fs = True
		if fs != "None":
			verified_fs = any(str(item.get("filesystem") or "").casefold() == fs.casefold() for item in parts if isinstance(item, dict))
		if updated is None or str(updated.get("partition_style") or "").upper() != style or not parts or not verified_fs:
			return {"success": False, "error": "prepare_verification_failed", "message": "DiskPart completed but the rebuilt disk did not match the requested layout."}
		return {"success": True, "disk_number": number, "operation": "prepare", "partition_style": style, "filesystem": fs, "disks": disks}

	def format_partition(self, disk_number: Any, partition_number: Any, filesystem: Any, label: Any = None) -> dict[str, Any]:
		number, disk = self._validated_disk(disk_number)
		if disk.get("protected"):
			return self._protected_result(disk)
		try:
			part_number = int(partition_number)
		except (TypeError, ValueError):
			return {"success": False, "error": "invalid_partition", "message": "A valid partition number is required."}
		partition = next((item for item in disk.get("partitions", []) if int(item.get("partition_number", -1)) == part_number), None)
		if partition is None:
			return {"success": False, "error": "partition_not_found", "message": "The selected partition no longer exists."}
		if partition.get("is_boot") or partition.get("is_system"):
			return {"success": False, "error": "protected_partition", "message": "StatMonitor will not format a boot or system partition."}
		fs = self._normalize_filesystem(filesystem)
		if fs in {None, "None"}:
			return {"success": False, "error": "invalid_filesystem", "message": "Quick format requires NTFS, exFAT, or FAT32."}
		label_text = self._diskpart_label(label or "StatMonitor Drive")
		completed = self._diskpart([
			f"select disk {number}",
			f"select partition {part_number}",
			f'format fs={fs.lower()} label="{label_text}" quick',
			"assign noerr",
		], timeout=180)
		if completed.returncode != 0:
			return {"success": False, "error": "format_failed", "message": self._command_error(completed, "DiskPart format operation failed")}
		disks = self.get_disks()
		updated = next((item for item in disks if int(item.get("disk_number", -1)) == number), None)
		updated_partition = next((item for item in (updated.get("partitions", []) if isinstance(updated, dict) else []) if int(item.get("partition_number", -1)) == part_number), None)
		if updated_partition is None or str(updated_partition.get("filesystem") or "").casefold() != fs.casefold():
			return {"success": False, "error": "format_verification_failed", "message": "DiskPart completed but the partition did not verify with the requested filesystem."}
		return {"success": True, "disk_number": number, "partition_number": part_number, "operation": "format", "filesystem": fs, "disks": disks}

	def _validated_disk(self, value: Any) -> tuple[int, dict[str, Any]]:
		try:
			number = int(value)
		except (TypeError, ValueError):
			raise ValueError("A valid physical disk number is required")
		disk = next((item for item in self.get_disks() if int(item.get("disk_number", -1)) == number), None)
		if disk is None:
			raise ValueError(f"Physical disk {number} was not found")
		return number, disk

	@staticmethod
	def _protected_result(disk: dict[str, Any]) -> dict[str, Any]:
		reasons = disk.get("protected_reasons", []) or []
		return {"success": False, "error": "protected_disk", "message": "StatMonitor will not perform destructive operations on this disk: " + "; ".join(str(item) for item in reasons)}

	@staticmethod
	def _normalize_filesystem(value: Any) -> str | None:
		text = str(value or "None").strip().casefold()
		mapping = {"ntfs": "NTFS", "exfat": "exFAT", "fat32": "FAT32", "none": "None", "raw": "None", "": "None"}
		return mapping.get(text)

	def _project_drive_letter(self) -> str | None:
		try:
			drive = self.project_root.resolve().drive
		except Exception:
			drive = self.project_root.drive
		text = str(drive or "").strip().upper()
		return text[0] if len(text) >= 2 and text[1] == ":" else None

	@staticmethod
	def _diskpart_label(value: Any) -> str:
		return " ".join(str(value or "StatMonitor Drive")[:32].replace('"', "'").splitlines()).strip() or "StatMonitor Drive"

	def _diskpart(self, commands: list[str], timeout: int) -> subprocess.CompletedProcess:
		fd, script_path = tempfile.mkstemp(prefix="StatMonitorDiskPart_", suffix=".txt")
		os.close(fd)
		path = Path(script_path)
		try:
			path.write_text("\r\n".join(commands) + "\r\n", encoding="ascii", errors="replace")
			args = ["diskpart.exe", "/s", str(path)]
			if self._is_admin():
				return subprocess.run(
					args,
					capture_output=True,
					text=True,
					timeout=timeout,
					check=False,
					creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
				)
			return self._run_elevated("diskpart.exe", ["/s", str(path)], timeout)
		finally:
			try:
				path.unlink(missing_ok=True)
			except Exception:
				pass

	@staticmethod
	def _run_elevated(executable: str, arguments: list[str], timeout: int) -> subprocess.CompletedProcess:
		class ShellExecuteInfo(ctypes.Structure):
			_fields_ = [
				("cbSize", wintypes.DWORD),
				("fMask", wintypes.ULONG),
				("hwnd", wintypes.HWND),
				("lpVerb", wintypes.LPCWSTR),
				("lpFile", wintypes.LPCWSTR),
				("lpParameters", wintypes.LPCWSTR),
				("lpDirectory", wintypes.LPCWSTR),
				("nShow", ctypes.c_int),
				("hInstApp", wintypes.HINSTANCE),
				("lpIDList", ctypes.c_void_p),
				("lpClass", wintypes.LPCWSTR),
				("hkeyClass", wintypes.HKEY),
				("dwHotKey", wintypes.DWORD),
				("hIcon", wintypes.HANDLE),
				("hProcess", wintypes.HANDLE),
			]
		parameters = subprocess.list2cmdline(arguments)
		info = ShellExecuteInfo()
		info.cbSize = ctypes.sizeof(info)
		info.fMask = 0x00000040
		info.lpVerb = "runas"
		info.lpFile = executable
		info.lpParameters = parameters
		info.nShow = 0
		shell_execute = ctypes.windll.shell32.ShellExecuteExW
		shell_execute.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
		shell_execute.restype = wintypes.BOOL
		kernel32 = ctypes.windll.kernel32
		kernel32.GetLastError.restype = wintypes.DWORD
		kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
		kernel32.WaitForSingleObject.restype = wintypes.DWORD
		kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
		kernel32.GetExitCodeProcess.restype = wintypes.BOOL
		kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
		kernel32.TerminateProcess.restype = wintypes.BOOL
		kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
		kernel32.CloseHandle.restype = wintypes.BOOL
		if not shell_execute(ctypes.byref(info)):
			error_code = int(kernel32.GetLastError()) or 1
			message = "Windows elevation request was cancelled." if error_code == 1223 else f"Windows elevation failed with error {error_code}."
			return subprocess.CompletedProcess([executable, *arguments], error_code, "", message)
		wait_result = kernel32.WaitForSingleObject(info.hProcess, max(1, int(timeout * 1000)))
		if wait_result == 0x00000102:
			kernel32.TerminateProcess(info.hProcess, 1)
			kernel32.CloseHandle(info.hProcess)
			return subprocess.CompletedProcess([executable, *arguments], 1, "", "Elevated DiskPart operation timed out.")
		if wait_result == 0xFFFFFFFF:
			error_code = int(kernel32.GetLastError()) or 1
			kernel32.CloseHandle(info.hProcess)
			return subprocess.CompletedProcess([executable, *arguments], error_code, "", f"Waiting for elevated DiskPart failed with error {error_code}.")
		exit_code = wintypes.DWORD()
		if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
			kernel32.CloseHandle(info.hProcess)
			return subprocess.CompletedProcess([executable, *arguments], 1, "", "Could not read the elevated DiskPart exit code.")
		kernel32.CloseHandle(info.hProcess)
		return subprocess.CompletedProcess([executable, *arguments], int(exit_code.value), "", "")

	@staticmethod
	def _is_admin() -> bool:
		try:
			return bool(ctypes.windll.shell32.IsUserAnAdmin())
		except Exception:
			return False

	@staticmethod
	def _powershell(script: str, timeout: int) -> subprocess.CompletedProcess:
		return subprocess.run(
			["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"],
			input=script,
			capture_output=True,
			text=True,
			timeout=timeout,
			check=False,
			creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
		)

	@staticmethod
	def _command_error(completed: subprocess.CompletedProcess, fallback: str) -> str:
		message = " ".join(str(completed.stderr or completed.stdout or fallback).split())
		return message[:1200]

	@staticmethod
	def _powershell_error(completed: subprocess.CompletedProcess) -> str:
		return StatMonitorStorageTools._command_error(completed, "PowerShell storage discovery failed")
