from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


DOTNET_MAJOR = 10
DOTNET_PACKAGE = "Microsoft.DotNet.DesktopRuntime.10"
DOTNET_MANUAL_URL = "https://dotnet.microsoft.com/en-us/download/dotnet/10.0"
LIBRE_HARDWARE_MONITOR_VERSION = "0.9.6"
SMARTMONTOOLS_VERSION = "7.5"
PYTHOFETCH_RELEASE_MANIFEST = "https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Releases/PythoFetch/PythoFetch_Release_Manifest.json"
PYTHOFETCH_ASSET_KEY = "Windows_x86_64"
LIBRE_HARDWARE_MONITOR_MANIFEST = f"https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Resources/ThirdParty/LibreHardwareMonitor/{LIBRE_HARDWARE_MONITOR_VERSION}/LibreHardwareMonitor_{LIBRE_HARDWARE_MONITOR_VERSION}_Manifest.json"
SMARTMONTOOLS_MANIFEST = f"https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Resources/ThirdParty/SmartMonTools/{SMARTMONTOOLS_VERSION}/SmartMonTools_{SMARTMONTOOLS_VERSION}_Manifest.json"
TARGET_KEY = "windows-x86_64"
USER_AGENT = "ProjectHomelab-StatMonitor/1.0.0"
DOWNLOAD_TIMEOUT = 60


class StatMonitorDependencies:
	def __init__(self, project_root: str | os.PathLike[str], *, interactive: bool | None = None, quiet: bool = False):
		self.project_root = Path(project_root).resolve()
		self.root = self.project_root / "Dependencies" / "StatMonitor"
		self.lhm_directory = self.root / "LibreHardwareMonitor.NET.10"
		self.smartmontools_directory = self.root / "smartmontools"
		self.pythofetch_directory = self.root / "PythoFetch"
		self.state_path = self.root / "StatMonitorDependencies.json"
		self.interactive = bool(sys.stdin.isatty() and sys.stdout.isatty()) if interactive is None else bool(interactive)
		self.quiet = bool(quiet)

	def _run(self, command: list[str], **kwargs):
		if self.quiet and os.name == "nt":
			kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
		if self.quiet and not kwargs.get("capture_output"):
			kwargs.setdefault("stdout", subprocess.DEVNULL)
			kwargs.setdefault("stderr", subprocess.DEVNULL)
		return subprocess.run(command, **kwargs)

	def ensure(self) -> dict[str, Any]:
		if os.name != "nt":
			return {"platform": "non-windows", "required": False}
		self.root.mkdir(parents=True, exist_ok=True)
		print()
		print("StatMonitor Windows Dependencies")
		print("-" * 60)
		dotnet = self._ensure_dotnet()
		lhm = self._ensure_lhm()
		smartmontools = self._ensure_smartmontools()
		try:
			pythofetch = self._ensure_pythofetch()
		except Exception as error:
			pythofetch = {"status": "unavailable", "error": str(error), "releaseManifest": PYTHOFETCH_RELEASE_MANIFEST}
			print(f"PythoFetch artwork unavailable: {error}")
			print("StatMonitor will continue and display Art Unavailable.")
			print()
		state = {
			"schemaVersion": 1,
			"platform": "Windows",
			"dependencies": {
				"DotNet": dotnet,
				"LibreHardwareMonitor": lhm,
				"SmartMonTools": smartmontools,
				"PythoFetch": pythofetch,
			},
		}
		self._write_json_atomic(self.state_path, state)
		print("-" * 60)
		print("Windows dependency preparation complete.")
		print()
		return state

	def _ensure_dotnet(self) -> dict[str, Any]:
		print(f"[.NET {DOTNET_MAJOR} Desktop Runtime]")
		print("Checking installed runtimes...")
		installed = self._find_dotnet_runtime()
		if installed is not None:
			desktop = installed.get("Microsoft.WindowsDesktop.App", "Unknown")
			core = installed.get("Microsoft.NETCore.App", "Unknown")
			print(f"Found Microsoft.WindowsDesktop.App {desktop}")
			print(f"Found Microsoft.NETCore.App {core}")
			print("Status: Ready")
			print()
			return {"requiredMajor": DOTNET_MAJOR, "status": "available", "runtimes": installed}
		print(f"Microsoft .NET {DOTNET_MAJOR} Desktop Runtime was not found.")
		if not self.interactive:
			if not self.quiet or not self._confirm_dotnet_install_gui():
				raise RuntimeError(
					f"Microsoft .NET {DOTNET_MAJOR} Desktop Runtime is required by StatMonitor on Windows. Install it from {DOTNET_MANUAL_URL} and start StatMonitor again."
				)
		else:
			print()
			print(f"Microsoft .NET {DOTNET_MAJOR} Desktop Runtime is required by StatMonitor on Windows.")
			print("Press Enter to install it automatically from Microsoft.")
			print("Press Esc to exit StatMonitor and install it manually.")
			key = self._read_enter_or_escape()
			if key == "escape":
				print()
				print(f"Manual .NET {DOTNET_MAJOR} Runtime download:")
				print(DOTNET_MANUAL_URL)
				raise SystemExit(1)
		print()
		winget = shutil.which("winget.exe") or shutil.which("winget")
		if winget is None:
			raise RuntimeError(
				f"Windows Package Manager was not found. Install Microsoft .NET {DOTNET_MAJOR} Desktop Runtime manually from {DOTNET_MANUAL_URL}."
			)
		print()
		print("Automatic installation selected.")
		print("Starting Microsoft Windows Package Manager...")
		print(f"Installing {DOTNET_PACKAGE}...")
		completed = self._run(
			[
				winget,
				"install",
				"--id",
				DOTNET_PACKAGE,
				"--exact",
				"--source",
				"winget",
				"--silent",
				"--accept-package-agreements",
				"--accept-source-agreements",
				"--disable-interactivity",
			],
			check=False,
		)
		if completed.returncode != 0:
			raise RuntimeError(
				f"Microsoft .NET {DOTNET_MAJOR} Desktop Runtime installation failed with exit code {completed.returncode}. Install it manually from {DOTNET_MANUAL_URL}."
			)
		print("Microsoft installer completed successfully.")
		print("Verifying installed runtime...")
		installed = self._find_dotnet_runtime()
		if installed is None:
			raise RuntimeError(
				f"Microsoft .NET {DOTNET_MAJOR} Desktop Runtime installation completed but StatMonitor could not detect it. Restart StatMonitor after confirming the runtime is installed."
			)
		print("Verification successful.")
		print(f"Microsoft .NET {DOTNET_MAJOR} Desktop Runtime installed successfully.")
		print("Status: Ready")
		print()
		return {"requiredMajor": DOTNET_MAJOR, "status": "installed", "runtimes": installed}

	def _confirm_dotnet_install_gui(self) -> bool:
		try:
			import tkinter as tk
			from tkinter import messagebox
			window = tk.Tk()
			window.withdraw()
			answer = messagebox.askyesno(
				"StatMonitor dependency",
				f"Microsoft .NET {DOTNET_MAJOR} Desktop Runtime is required.\n\nInstall it automatically from Microsoft now?",
				parent=window,
			)
			window.destroy()
			return bool(answer)
		except Exception:
			return False

	def _ensure_lhm(self) -> dict[str, Any]:
		print(f"[LibreHardwareMonitor {LIBRE_HARDWARE_MONITOR_VERSION}]")
		print("Checking local dependency...")
		existing = self._existing_lhm()
		if existing is not None:
			print(f"Found LibreHardwareMonitor {LIBRE_HARDWARE_MONITOR_VERSION}.")
			print("Integrity check successful.")
			print("Status: Ready")
			print()
			return existing
		print("Dependency is missing or requires repair.")
		print("Downloading dependency manifest from ProjectHomelab...")
		target = self._fetch_target(
			LIBRE_HARDWARE_MONITOR_MANIFEST,
			resource_id="librehardwaremonitor",
			version=LIBRE_HARDWARE_MONITOR_VERSION,
		)
		print("Manifest loaded successfully.")
		print(f"Download size: {self._format_bytes(int(target['size_bytes']))}")
		with tempfile.TemporaryDirectory(prefix="StatMonitor-LHM-") as temporary:
			temporary_path = Path(temporary)
			archive = temporary_path / "LibreHardwareMonitor.NET.10.zip"
			print("Downloading LibreHardwareMonitor from ProjectHomelab...")
			self._download_verified(target, archive)
			print("Download complete.")
			print("File size verification successful.")
			print("SHA-256 verification successful.")
			staging = temporary_path / "extract"
			staging.mkdir()
			print("Extracting LibreHardwareMonitor...")
			self._safe_extract_zip(archive, staging, "LibreHardwareMonitor")
			print("Extraction complete.")
			source = self._find_payload_root(staging, "LibreHardwareMonitorLib.dll")
			if source is None or not (source / "LibreHardwareMonitor.runtimeconfig.json").is_file():
				raise RuntimeError("LibreHardwareMonitor archive does not contain the expected .NET 10 runtime files")
			print("Installing LibreHardwareMonitor into Dependencies/StatMonitor...")
			self._replace_directory(source, self.lhm_directory)
		print("Verifying installed files...")
		if self._existing_lhm(require_state=False) is None:
			raise RuntimeError("LibreHardwareMonitor installation could not be verified")
		files = self._dependency_file_hashes(
			self.lhm_directory,
			("LibreHardwareMonitorLib.dll", "LibreHardwareMonitor.runtimeconfig.json"),
		)
		print("Installation verification successful.")
		print(f"LibreHardwareMonitor {LIBRE_HARDWARE_MONITOR_VERSION} installed successfully.")
		print("Status: Ready")
		print()
		return {
			"version": LIBRE_HARDWARE_MONITOR_VERSION,
			"status": "installed",
			"artifactSha256": target["sha256"],
			"files": files,
		}

	def _ensure_smartmontools(self) -> dict[str, Any]:
		print(f"[SmartMonTools {SMARTMONTOOLS_VERSION}]")
		print("Checking local dependency...")
		existing = self._existing_smartmontools()
		if existing is not None:
			print(f"Found SmartMonTools {SMARTMONTOOLS_VERSION}.")
			print("smartctl version and integrity check successful.")
			print("Status: Ready")
			print()
			return existing
		print("Dependency is missing or requires repair.")
		print("Downloading dependency manifest from ProjectHomelab...")
		target = self._fetch_target(
			SMARTMONTOOLS_MANIFEST,
			resource_id="smartmontools",
			version=SMARTMONTOOLS_VERSION,
		)
		print("Manifest loaded successfully.")
		print(f"Download size: {self._format_bytes(int(target['size_bytes']))}")
		with tempfile.TemporaryDirectory(prefix="StatMonitor-SMART-") as temporary:
			installer = Path(temporary) / "smartmontools-setup.exe"
			print("Downloading SmartMonTools from ProjectHomelab...")
			self._download_verified(target, installer)
			print("Download complete.")
			print("File size verification successful.")
			print("SHA-256 verification successful.")
			if self.smartmontools_directory.exists():
				shutil.rmtree(self.smartmontools_directory)
			self.smartmontools_directory.mkdir(parents=True, exist_ok=True)
			print("Installing SmartMonTools x64 smartctl component...")
			completed = self._run(
				[
					str(installer),
					"/S",
					"/SO",
					"x64,smartctl",
					f"/D={self.smartmontools_directory}",
				],
				check=False,
			)
			if completed.returncode != 0:
				raise RuntimeError(f"SmartMonTools installer failed with exit code {completed.returncode}")
			print("SmartMonTools installer completed successfully.")
		print("Verifying smartctl installation...")
		smartctl = self._find_smartctl()
		if smartctl is None:
			raise RuntimeError("SmartMonTools installation completed but smartctl.exe was not found")
		version_text = self._smartctl_version(smartctl)
		if SMARTMONTOOLS_VERSION not in version_text:
			raise RuntimeError(f"SmartMonTools version verification failed: {version_text or 'no version output'}")
		print(f"smartctl {SMARTMONTOOLS_VERSION} verified successfully.")
		print(f"SmartMonTools {SMARTMONTOOLS_VERSION} installed successfully.")
		print("Status: Ready")
		print()
		return {
			"version": SMARTMONTOOLS_VERSION,
			"status": "installed",
			"artifactSha256": target["sha256"],
			"executable": self._display_dependency_path(smartctl),
			"executableSha256": self._sha256(smartctl),
		}


	def ensure_pythofetch(self) -> dict[str, Any]:
		if os.name != "nt":
			raise RuntimeError("PythoFetch dependency resolution is not implemented for this StatMonitor platform build")
		self.root.mkdir(parents=True, exist_ok=True)
		print()
		print("StatMonitor PythoFetch Dependency")
		print("-" * 60)
		pythofetch = self._ensure_pythofetch()
		state = self._read_state()
		if not isinstance(state, dict):
			state = {"schemaVersion": 1, "platform": "Windows", "dependencies": {}}
		dependencies = state.get("dependencies")
		if not isinstance(dependencies, dict):
			dependencies = {}
			state["dependencies"] = dependencies
		dependencies["PythoFetch"] = pythofetch
		self._write_json_atomic(self.state_path, state)
		print("-" * 60)
		print("PythoFetch is ready.")
		print()
		return pythofetch

	def get_pythofetch_path(self) -> Path | None:
		state = self._read_state_dependency("PythoFetch") or {}
		raw = str(state.get("executable") or "").strip()
		if raw:
			candidate = Path(raw)
			if not candidate.is_absolute():
				candidate = self.root / candidate
			if candidate.is_file():
				return candidate.resolve()
		managed = self.pythofetch_directory / "PythoFetch.exe"
		return managed.resolve() if managed.is_file() else None

	def get_pythofetch_art(self) -> str:
		executable = self.get_pythofetch_path()
		if executable is None:
			return ""
		try:
			completed = self._run(
				[str(executable), "--headless", "--art", "--format", "json"],
				capture_output=True,
				text=True,
				timeout=30,
				check=False,
			)
		except (OSError, subprocess.TimeoutExpired):
			return ""
		if completed.returncode != 0:
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

	def run_pythofetch(self) -> int:
		executable = self.get_pythofetch_path()
		if executable is None:
			self.ensure_pythofetch()
			executable = self.get_pythofetch_path()
		if executable is None:
			raise RuntimeError("PythoFetch is unavailable after dependency resolution")
		return self._run([str(executable)], check=False).returncode

	def _ensure_pythofetch(self) -> dict[str, Any]:
		print("[PythoFetch latest]")
		print("Checking current ProjectHomelab release manifest...")
		try:
			manifest = self._download_json(PYTHOFETCH_RELEASE_MANIFEST)
			target = self._pythofetch_target(manifest)
		except RuntimeError as error:
			fallback = self._existing_pythofetch_from_state()
			if fallback is None:
				raise
			print(f"Latest-release check unavailable: {error}")
			print(f"Using previously verified PythoFetch {fallback['version']} while offline.")
			print("Status: Ready")
			print()
			return fallback
		version = target["version"]
		print(f"Latest PythoFetch release: {version}")
		print("Searching for an existing compatible PythoFetch.exe...")
		existing = self._find_existing_pythofetch(target)
		if existing is not None:
			print(f"Found PythoFetch {version}: {existing}")
			print("Executable SHA-256 verification successful.")
			print("Status: Ready")
			print()
			return {
				"version": version,
				"status": "available",
				"source": "existing",
				"executable": self._display_dependency_path(existing),
				"executableSha256": target["executable_sha256"],
				"releaseManifest": PYTHOFETCH_RELEASE_MANIFEST,
			}
		print(f"PythoFetch {version} was not found on this machine.")
		print(f"Download size: {self._format_bytes(int(target['size_bytes']))}")
		with tempfile.TemporaryDirectory(prefix="StatMonitor-PythoFetch-") as temporary:
			temporary_path = Path(temporary)
			archive = temporary_path / target["file"]
			print("Downloading latest PythoFetch from ProjectHomelab Releases...")
			self._download_verified(target, archive)
			print("Download complete.")
			print("File size verification successful.")
			print("SHA-256 verification successful.")
			staging = temporary_path / "extract"
			staging.mkdir()
			print("Extracting PythoFetch...")
			self._safe_extract_zip(archive, staging, "PythoFetch")
			print("Extraction complete.")
			source = self._find_payload_root(staging, target["executable_name"])
			if source is None:
				raise RuntimeError("PythoFetch release archive does not contain the expected executable")
			executable = source / target["executable_name"]
			if executable.stat().st_size != target["executable_size_bytes"]:
				raise RuntimeError("PythoFetch executable size verification failed")
			if self._sha256(executable).lower() != target["executable_sha256"]:
				raise RuntimeError("PythoFetch executable SHA-256 verification failed")
			print("PythoFetch executable verification successful.")
			print("Installing PythoFetch into Dependencies/StatMonitor/PythoFetch...")
			self._replace_directory(source, self.pythofetch_directory)
		managed = self.pythofetch_directory / target["executable_name"]
		print("Verifying installed PythoFetch...")
		if not managed.is_file():
			raise RuntimeError("PythoFetch installation completed but PythoFetch.exe was not found")
		if managed.stat().st_size != target["executable_size_bytes"] or self._sha256(managed).lower() != target["executable_sha256"]:
			raise RuntimeError("Installed PythoFetch executable verification failed")
		if self._pythofetch_version(managed) != version:
			raise RuntimeError("Installed PythoFetch version verification failed")
		print(f"PythoFetch {version} installed successfully.")
		print("Status: Ready")
		print()
		return {
			"version": version,
			"status": "installed",
			"source": "managed",
			"artifactSha256": target["sha256"],
			"executable": self._display_dependency_path(managed),
			"executableSha256": target["executable_sha256"],
			"releaseManifest": PYTHOFETCH_RELEASE_MANIFEST,
		}

	def _pythofetch_target(self, manifest: dict[str, Any]) -> dict[str, Any]:
		if int(manifest.get("schema", 0)) != 1:
			raise RuntimeError("Unsupported PythoFetch release manifest schema")
		if str(manifest.get("application") or "").casefold() != "pythofetch":
			raise RuntimeError("Unexpected PythoFetch release manifest")
		version = str(manifest.get("latest_version") or "").strip()
		releases = manifest.get("releases")
		if not version or not isinstance(releases, dict) or version not in releases:
			raise RuntimeError("PythoFetch release manifest does not define a valid latest release")
		release = releases[version]
		assets = release.get("assets") if isinstance(release, dict) else None
		asset = assets.get(PYTHOFETCH_ASSET_KEY) if isinstance(assets, dict) else None
		if not isinstance(asset, dict):
			raise RuntimeError(f"PythoFetch {version} does not provide {PYTHOFETCH_ASSET_KEY}")
		url = str(asset.get("download_url") or "").strip()
		sha256 = str(asset.get("sha256") or "").strip().lower()
		executable_sha256 = str(asset.get("executable_sha256") or "").strip().lower()
		file_name = str(asset.get("file") or "").strip()
		executable_name = str(asset.get("executable") or "").strip()
		size_bytes = int(asset.get("size_bytes") or 0)
		executable_size_bytes = int(asset.get("executable_size_bytes") or 0)
		if not url.startswith("https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/"):
			raise RuntimeError("Refusing unexpected PythoFetch download host")
		for digest in (sha256, executable_sha256):
			if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
				raise RuntimeError("Invalid PythoFetch SHA-256 metadata")
		if not file_name or executable_name != "PythoFetch.exe" or size_bytes <= 0 or executable_size_bytes <= 0:
			raise RuntimeError("Invalid PythoFetch Windows release metadata")
		return {
			"version": version,
			"file": file_name,
			"download_url": url,
			"sha256": sha256,
			"size_bytes": size_bytes,
			"executable_name": executable_name,
			"executable_sha256": executable_sha256,
			"executable_size_bytes": executable_size_bytes,
		}

	def _existing_pythofetch_from_state(self) -> dict[str, Any] | None:
		state = self._read_state_dependency("PythoFetch")
		if not isinstance(state, dict):
			return None
		version = str(state.get("version") or "").strip()
		expected_hash = str(state.get("executableSha256") or "").strip().lower()
		raw = str(state.get("executable") or "").strip()
		if not version or len(expected_hash) != 64 or not raw:
			return None
		path = Path(raw)
		if not path.is_absolute():
			path = self.root / path
		if not path.is_file():
			return None
		try:
			if self._sha256(path).lower() != expected_hash:
				return None
			if self._pythofetch_version(path) != version:
				return None
		except OSError:
			return None
		return dict(state, status="available", offline=True)

	def _find_existing_pythofetch(self, target: dict[str, Any]) -> Path | None:
		for candidate in self._pythofetch_candidates():
			try:
				if candidate.stat().st_size != target["executable_size_bytes"]:
					continue
				if self._sha256(candidate).lower() != target["executable_sha256"]:
					continue
				if self._pythofetch_version(candidate) != target["version"]:
					continue
			except OSError:
				continue
			return candidate.resolve()
		return None

	def _pythofetch_candidates(self):
		seen: set[str] = set()
		def resolve(value: str | os.PathLike[str] | None) -> Path | None:
			if not value:
				return None
			try:
				path = Path(value).expanduser().resolve()
			except (OSError, RuntimeError):
				return None
			key = str(path).casefold()
			if key in seen or not path.is_file() or path.name.casefold() != "pythofetch.exe":
				return None
			seen.add(key)
			return path
		direct = [
			os.environ.get("PYTHOFETCH_PATH"),
			shutil.which("PythoFetch.exe"),
			self.project_root / "PythoFetch.exe",
			self.project_root / "PythoFetch" / "PythoFetch.exe",
			self.pythofetch_directory / "PythoFetch.exe",
			Path.cwd() / "PythoFetch.exe",
			Path(sys.executable).resolve().parent / "PythoFetch.exe",
		]
		state = self._read_state_dependency("PythoFetch") or {}
		raw = str(state.get("executable") or "").strip()
		if raw:
			path = Path(raw)
			direct.append(path if path.is_absolute() else self.root / path)
		for value in direct:
			path = resolve(value)
			if path is not None:
				yield path
		for base in self._pythofetch_search_roots():
			for match in self._limited_find(base, "PythoFetch.exe", max_depth=4, max_directories=5000):
				path = resolve(match)
				if path is not None:
					yield path

	def _pythofetch_search_roots(self) -> list[Path]:
		roots = [self.project_root]
		home = Path.home()
		for name in ("Desktop", "Downloads", "Documents"):
			candidate = home / name
			if candidate.is_dir():
				roots.append(candidate)
		result = []
		seen = set()
		for root in roots:
			try:
				resolved = root.resolve()
			except OSError:
				continue
			key = str(resolved).casefold()
			if key not in seen and resolved.is_dir():
				seen.add(key)
				result.append(resolved)
		return result

	def _limited_find(self, root: Path, filename: str, *, max_depth: int, max_directories: int):
		root_depth = len(root.parts)
		visited = 0
		for current, directories, files in os.walk(root):
			visited += 1
			if visited > max_directories:
				break
			current_path = Path(current)
			depth = len(current_path.parts) - root_depth
			directories[:] = [name for name in directories if not name.startswith(".") and name not in {"node_modules", "__pycache__", ".git"}]
			if depth >= max_depth:
				directories[:] = []
			if filename in files:
				yield current_path / filename

	def _pythofetch_version(self, executable: Path) -> str | None:
		try:
			completed = self._run(
				[str(executable), "--version"],
				capture_output=True,
				text=True,
				timeout=20,
				check=False,
			)
		except (OSError, subprocess.TimeoutExpired):
			return None
		text = "\n".join((completed.stdout or "", completed.stderr or ""))
		match = re.search(r"\b(\d+\.\d+\.\d+)\b", text)
		return match.group(1) if match else None

	def _existing_lhm(self, *, require_state: bool = True) -> dict[str, Any] | None:
		dll = self.lhm_directory / "LibreHardwareMonitorLib.dll"
		runtime_config = self.lhm_directory / "LibreHardwareMonitor.runtimeconfig.json"
		if not dll.is_file() or not runtime_config.is_file():
			return None
		state = self._read_state_dependency("LibreHardwareMonitor")
		if state is not None and str(state.get("version")) == LIBRE_HARDWARE_MONITOR_VERSION:
			files = state.get("files")
			if isinstance(files, dict) and self._file_hashes_match(self.lhm_directory, files):
				return dict(state, status="available")
		if require_state:
			version = self._lhm_version_from_deps()
			if version != LIBRE_HARDWARE_MONITOR_VERSION:
				return None
		files = self._dependency_file_hashes(
			self.lhm_directory,
			("LibreHardwareMonitorLib.dll", "LibreHardwareMonitor.runtimeconfig.json"),
		)
		return {"version": LIBRE_HARDWARE_MONITOR_VERSION, "status": "available", "files": files}

	def _existing_smartmontools(self) -> dict[str, Any] | None:
		smartctl = self._find_smartctl()
		if smartctl is None:
			return None
		version_text = self._smartctl_version(smartctl)
		if SMARTMONTOOLS_VERSION not in version_text:
			return None
		state = self._read_state_dependency("SmartMonTools") or {}
		expected_hash = str(state.get("executableSha256") or "").strip().lower()
		actual_hash = self._sha256(smartctl)
		if expected_hash and expected_hash != actual_hash:
			return None
		return {
			"version": SMARTMONTOOLS_VERSION,
			"status": "available",
			"artifactSha256": state.get("artifactSha256"),
			"executable": self._display_dependency_path(smartctl),
			"executableSha256": actual_hash,
		}

	def _fetch_target(self, manifest_url: str, *, resource_id: str, version: str) -> dict[str, Any]:
		manifest = self._download_json(manifest_url)
		if int(manifest.get("schema_version", 0)) != 1:
			raise RuntimeError(f"Unsupported {resource_id} resource manifest schema")
		if str(manifest.get("resource_id", "")).casefold() != resource_id.casefold():
			raise RuntimeError(f"Unexpected resource manifest returned for {resource_id}")
		if str(manifest.get("version", "")) != version:
			raise RuntimeError(f"Expected {resource_id} {version}, received manifest for {manifest.get('version')}")
		targets = manifest.get("targets")
		if not isinstance(targets, dict) or TARGET_KEY not in targets:
			raise RuntimeError(f"{resource_id} {version} does not provide {TARGET_KEY}")
		target = targets[TARGET_KEY]
		if not isinstance(target, dict):
			raise RuntimeError(f"Invalid {resource_id} target metadata")
		if str(target.get("os")) != "Windows" or str(target.get("architecture")) != "x86_64":
			raise RuntimeError(f"Unexpected {resource_id} platform target")
		url = str(target.get("download_url") or "").strip()
		sha256 = str(target.get("sha256") or "").strip().lower()
		size_bytes = int(target.get("size_bytes") or 0)
		if not url.startswith("https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/"):
			raise RuntimeError(f"Refusing unexpected {resource_id} download host")
		if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
			raise RuntimeError(f"Invalid {resource_id} SHA-256 metadata")
		if size_bytes <= 0:
			raise RuntimeError(f"Invalid {resource_id} size metadata")
		return {"download_url": url, "sha256": sha256, "size_bytes": size_bytes}

	def _download_json(self, url: str) -> dict[str, Any]:
		request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
		try:
			with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
				payload = response.read()
		except Exception as error:
			raise RuntimeError(f"Unable to download dependency manifest: {error}") from error
		try:
			result = json.loads(payload.decode("utf-8"))
		except Exception as error:
			raise RuntimeError(f"Dependency manifest is not valid JSON: {error}") from error
		if not isinstance(result, dict):
			raise RuntimeError("Dependency manifest root must be an object")
		return result

	def _download_verified(self, target: dict[str, Any], destination: Path) -> None:
		request = urllib.request.Request(str(target["download_url"]), headers={"User-Agent": USER_AGENT})
		digest = hashlib.sha256()
		size = 0
		try:
			with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response, destination.open("wb") as output:
				while True:
					chunk = response.read(1024 * 1024)
					if not chunk:
						break
					output.write(chunk)
					digest.update(chunk)
					size += len(chunk)
		except Exception as error:
			destination.unlink(missing_ok=True)
			raise RuntimeError(f"Dependency download failed: {error}") from error
		if size != int(target["size_bytes"]):
			destination.unlink(missing_ok=True)
			raise RuntimeError(f"Dependency download size mismatch: expected {target['size_bytes']} bytes, received {size}")
		if digest.hexdigest().lower() != str(target["sha256"]).lower():
			destination.unlink(missing_ok=True)
			raise RuntimeError("Dependency download SHA-256 verification failed")

	def _find_dotnet_runtime(self) -> dict[str, str] | None:
		for executable in self._dotnet_candidates():
			try:
				completed = self._run(
					[executable, "--list-runtimes"],
					capture_output=True,
					text=True,
					timeout=15,
					check=False,
				)
			except (OSError, subprocess.TimeoutExpired):
				continue
			if completed.returncode != 0:
				continue
			versions: dict[str, str] = {}
			for line in completed.stdout.splitlines():
				parts = line.strip().split()
				if len(parts) < 2 or parts[1].split(".", 1)[0] != str(DOTNET_MAJOR):
					continue
				if parts[0] in {"Microsoft.NETCore.App", "Microsoft.WindowsDesktop.App"}:
					versions[parts[0]] = parts[1]
			if {"Microsoft.NETCore.App", "Microsoft.WindowsDesktop.App"}.issubset(versions):
				return versions
		return None

	def _dotnet_candidates(self) -> list[str]:
		candidates: list[str] = []
		path = shutil.which("dotnet.exe") or shutil.which("dotnet")
		if path:
			candidates.append(path)
		for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
			if base:
				candidate = str(Path(base) / "dotnet" / "dotnet.exe")
				if candidate not in candidates and Path(candidate).is_file():
					candidates.append(candidate)
		return candidates

	def _read_enter_or_escape(self) -> str:
		import msvcrt
		while True:
			key = msvcrt.getwch()
			if key in {"\r", "\n"}:
				return "enter"
			if key == "\x1b":
				return "escape"

	def _find_smartctl(self) -> Path | None:
		for candidate in (
			self.smartmontools_directory / "bin64" / "smartctl.exe",
			self.smartmontools_directory / "bin" / "smartctl.exe",
			self.root / "smartctl.exe",
		):
			if candidate.is_file():
				return candidate
		path = shutil.which("smartctl.exe") or shutil.which("smartctl")
		return Path(path).resolve() if path else None

	def _display_dependency_path(self, path: Path) -> str:
		try:
			return str(path.relative_to(self.root)).replace("\\", "/")
		except ValueError:
			return str(path)

	def _smartctl_version(self, executable: Path) -> str:
		try:
			completed = self._run(
				[str(executable), "--version"],
				capture_output=True,
				text=True,
				timeout=15,
				check=False,
			)
		except (OSError, subprocess.TimeoutExpired):
			return ""
		return "\n".join((completed.stdout or "", completed.stderr or "")).strip()

	def _lhm_version_from_deps(self) -> str | None:
		path = self.lhm_directory / "LibreHardwareMonitor.deps.json"
		if not path.is_file():
			return None
		try:
			payload = json.loads(path.read_text(encoding="utf-8"))
		except Exception:
			return None
		libraries = payload.get("libraries")
		if not isinstance(libraries, dict):
			return None
		for key in libraries:
			if str(key).startswith("LibreHardwareMonitor/"):
				return str(key).split("/", 1)[1]
		return None

	def _read_state(self) -> dict[str, Any] | None:
		if not self.state_path.is_file():
			return None
		try:
			payload = json.loads(self.state_path.read_text(encoding="utf-8"))
		except Exception:
			return None
		return payload if isinstance(payload, dict) else None

	def _read_state_dependency(self, name: str) -> dict[str, Any] | None:
		payload = self._read_state()
		if payload is None:
			return None
		dependencies = payload.get("dependencies")
		if not isinstance(dependencies, dict):
			return None
		value = dependencies.get(name)
		return value if isinstance(value, dict) else None

	def _dependency_file_hashes(self, root: Path, relative_paths: tuple[str, ...]) -> dict[str, str]:
		return {relative: self._sha256(root / relative) for relative in relative_paths}

	def _file_hashes_match(self, root: Path, expected: dict[str, Any]) -> bool:
		for relative, sha256 in expected.items():
			path = root / str(relative)
			if not path.is_file() or self._sha256(path).lower() != str(sha256).lower():
				return False
		return bool(expected)

	def _safe_extract_zip(self, archive: Path, destination: Path, label: str = "Dependency") -> None:
		base = destination.resolve()
		with zipfile.ZipFile(archive, "r") as bundle:
			for member in bundle.infolist():
				name = member.filename.replace("\\", "/")
				if not name or name.startswith("/") or "\x00" in name:
					raise RuntimeError(f"{label} archive contains an unsafe path")
				parts = [part for part in name.split("/") if part not in {"", "."}]
				if any(part == ".." for part in parts):
					raise RuntimeError(f"{label} archive contains parent traversal")
				target = destination.joinpath(*parts)
				try:
					target.resolve().relative_to(base)
				except ValueError as error:
					raise RuntimeError(f"{label} archive escapes its staging directory") from error
			bundle.extractall(destination)

	def _find_payload_root(self, staging: Path, required_file: str) -> Path | None:
		if (staging / required_file).is_file():
			return staging
		matches = [path.parent for path in staging.rglob(required_file) if path.is_file()]
		return matches[0] if len(matches) == 1 else None

	def _replace_directory(self, source: Path, destination: Path) -> None:
		backup = destination.with_name(destination.name + ".old")
		if backup.exists():
			shutil.rmtree(backup)
		if destination.exists():
			destination.replace(backup)
		try:
			shutil.copytree(source, destination)
		except Exception:
			if destination.exists():
				shutil.rmtree(destination)
			if backup.exists():
				backup.replace(destination)
			raise
		if backup.exists():
			shutil.rmtree(backup)

	def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
		path.parent.mkdir(parents=True, exist_ok=True)
		temporary = path.with_suffix(path.suffix + ".tmp")
		temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
		os.replace(temporary, path)

	@staticmethod
	def _format_bytes(size: int) -> str:
		value = float(size)
		for unit in ("B", "KiB", "MiB", "GiB"):
			if value < 1024.0 or unit == "GiB":
				return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
			value /= 1024.0
		return f"{size} B"

	@staticmethod
	def _sha256(path: Path) -> str:
		digest = hashlib.sha256()
		with path.open("rb") as handle:
			for chunk in iter(lambda: handle.read(1024 * 1024), b""):
				digest.update(chunk)
		return digest.hexdigest()
