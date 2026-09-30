from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

TERMINALSS_RELEASE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "Releases/TerminalSS/"
    "TerminalSS_Release_Manifest.json"
)
TERMINALSS_RESOURCES_MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "Resources/FirstParty/TerminalSS/"
    "TerminalSS_Resources_Manifest.json"
)
WAIT_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 0.25


def version_key(value: str) -> tuple[int, int, int]:
    parts = str(value or "").strip().split(".")
    if len(parts) != 3:
        raise RuntimeError(f"Invalid version value: {value}")
    try:
        return tuple(int(part) for part in parts)
    except Exception as exc:
        raise RuntimeError(f"Invalid version value: {value}") from exc


def compatibility_family(version: str) -> str:
    key = version_key(version)
    return f"{key[0]}.{key[1]}"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def fetch_json(url: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "TerminalSS"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except Exception as exc:
        raise RuntimeError(f"Could not download manifest: {url}") from exc
    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Downloaded manifest is not valid JSON: {url}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Manifest root is invalid: {url}")
    return data


def download_verified_file(url: str, destination: Path, expected_sha256: str, expected_size: int) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    remove_path(temporary)
    expected_hash = str(expected_sha256 or "").strip().lower()
    if not expected_hash:
        raise RuntimeError("Manifest does not provide a SHA-256 checksum.")
    try:
        required_size = int(expected_size)
    except Exception as exc:
        raise RuntimeError("Manifest contains an invalid byte size.") from exc
    request = urllib.request.Request(url, headers={"User-Agent": "TerminalSS"})
    try:
        try:
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        except Exception as exc:
            raise RuntimeError("Could not download update package.") from exc
        if not temporary.is_file() or temporary.stat().st_size != required_size:
            raise RuntimeError("Downloaded update package size does not match the manifest.")
        if sha256_file(temporary).lower() != expected_hash:
            raise RuntimeError("Downloaded update package failed SHA-256 verification.")
        os.replace(temporary, destination)
    finally:
        remove_path(temporary)
    return destination


def normalized_platform_name() -> str:
    system = platform.system()
    if system == "Windows":
        return "Windows"
    if system == "Linux":
        return "Linux"
    if system == "Darwin":
        return "macOS"
    raise RuntimeError(f"Unsupported update platform: {system}")


def normalized_architecture() -> str:
    machine = str(platform.machine() or "").strip().lower()
    if machine in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("universal", "universal2"):
        return "Universal"
    return machine or "Unknown"


def release_asset_candidates() -> list[str]:
    system = normalized_platform_name()
    architecture = normalized_architecture()
    candidates = []
    if architecture != "Unknown":
        candidates.append(f"{system}_{architecture}")
    candidates.extend((f"{system}_Universal", "Universal"))
    return candidates


def select_release_asset(release: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    assets = release.get("assets")
    if not isinstance(assets, dict):
        raise RuntimeError("Release manifest entry has no valid assets object.")
    lookup = {str(key).casefold(): (str(key), value) for key, value in assets.items()}
    for candidate in release_asset_candidates():
        selected = lookup.get(candidate.casefold())
        if selected:
            key, asset = selected
            if not isinstance(asset, dict):
                raise RuntimeError("Selected release asset is malformed.")
            return key, asset
    raise RuntimeError("No release asset is available for this system.")


def check_update_available(current_version: str, timeout: int = 20, suppress_errors: bool = False) -> dict[str, Any] | None:
    try:
        manifest = fetch_json(TERMINALSS_RELEASE_MANIFEST_URL, timeout=timeout)
        latest = str(manifest.get("latest_version") or "").strip()
        if not latest or version_key(latest) <= version_key(current_version):
            return None
        releases = manifest.get("releases")
        if not isinstance(releases, dict):
            raise RuntimeError("Release manifest contains an invalid releases object.")
        release = releases.get(latest)
        if not isinstance(release, dict):
            raise RuntimeError("Latest TerminalSS release is missing from the release manifest.")
        asset_key, asset = select_release_asset(release)
        return {"latest_version": latest, "release": release, "asset_key": asset_key, "asset": asset}
    except Exception:
        if suppress_errors:
            return None
        raise


def fetch_verified_json_reference(reference: dict[str, Any], label: str, timeout: int = 20) -> dict[str, Any]:
    if not isinstance(reference, dict):
        raise RuntimeError(f"{label} manifest reference is invalid.")
    url = str(reference.get("download_url") or "").strip()
    expected_hash = str(reference.get("sha256") or "").strip().lower()
    try:
        expected_size = int(reference.get("size_bytes"))
    except Exception as exc:
        raise RuntimeError(f"{label} manifest reference has an invalid size.") from exc
    if not url or not expected_hash or expected_size <= 0:
        raise RuntimeError(f"{label} manifest reference is incomplete.")
    request = urllib.request.Request(url, headers={"User-Agent": "TerminalSS"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except Exception as exc:
        raise RuntimeError(f"Could not download the {label} manifest.") from exc
    if len(payload) != expected_size:
        raise RuntimeError(f"{label} manifest size verification failed.")
    if hashlib.sha256(payload).hexdigest().lower() != expected_hash:
        raise RuntimeError(f"{label} manifest SHA-256 verification failed.")
    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"{label} manifest is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} manifest has an invalid root structure.")
    return data


def nested_manifest_reference(manifest: dict[str, Any], section: str, name: str, label: str) -> dict[str, Any]:
    entries = manifest.get(section)
    if not isinstance(entries, dict):
        raise RuntimeError(f"{label} router does not contain {section}.")
    entry = entries.get(name)
    if not isinstance(entry, dict):
        raise RuntimeError(f"{label} router does not contain {name}.")
    reference = entry.get("manifest")
    if not isinstance(reference, dict):
        raise RuntimeError(f"{label} router has an invalid manifest reference for {name}.")
    return reference


def select_compatible_updater(manifest: dict[str, Any], current_version: str) -> tuple[str, str, dict[str, Any]]:
    versions = manifest.get("versions")
    if not isinstance(versions, dict):
        raise RuntimeError("Updater release manifest contains an invalid versions object.")
    family = compatibility_family(current_version)
    compatible = []
    for version, entry in versions.items():
        if not isinstance(entry, dict):
            continue
        try:
            key = version_key(version)
        except Exception:
            continue
        if f"{key[0]}.{key[1]}" != family:
            continue
        if str(entry.get("compatibility_family") or "").strip() != family:
            continue
        try:
            asset_key, asset = select_release_asset(entry)
        except Exception:
            continue
        compatible.append((key, str(version), asset_key, asset))
    if not compatible:
        raise RuntimeError("No compatible TerminalSSUpdater release is available for this system.")
    compatible.sort(key=lambda item: item[0], reverse=True)
    _, version, asset_key, asset = compatible[0]
    return version, asset_key, asset


def resolve_updater_release(current_version: str) -> tuple[str, str, dict[str, Any]]:
    resources = fetch_json(TERMINALSS_RESOURCES_MANIFEST_URL, timeout=20)
    updater_reference = nested_manifest_reference(resources, "components", "TerminalSSUpdater", "TerminalSS resources")
    updater_manifest = fetch_verified_json_reference(updater_reference, "TerminalSSUpdater releases")
    return select_compatible_updater(updater_manifest, current_version)


def runtime_application_path() -> Path:
    if platform.system() == "Linux":
        appimage_value = str(os.environ.get("APPIMAGE") or "").strip()
        if appimage_value:
            appimage_path = Path(appimage_value).expanduser().resolve()
            if appimage_path.is_file():
                return appimage_path
    return Path(sys.executable).resolve()


def expected_runtime_name() -> str:
    system = platform.system()
    if system == "Windows":
        return "TerminalSS.exe"
    if system == "Linux":
        return "TerminalSS.AppImage"
    raise RuntimeError("Automatic updating is currently available for Windows and Linux releases.")


def expected_updater_name() -> str:
    system = platform.system()
    if system == "Windows":
        return "TerminalSSUpdater.exe"
    if system == "Linux":
        return "TerminalSSUpdater"
    raise RuntimeError("No packaged TerminalSSUpdater is currently available for this operating system.")


def temporary_runtime_name() -> str:
    system = platform.system()
    if system == "Windows":
        return "TerminalSSTemp.exe"
    if system == "Linux":
        return "TerminalSSTemp.AppImage"
    raise RuntimeError("Post-update cleanup is currently available for Windows and Linux releases.")


def remove_path(path: str | Path) -> None:
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)


def normalized_zip_member_name(value: str) -> str:
    normalized = str(value).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized.startswith("/") or "\x00" in normalized:
        raise RuntimeError("Updater archive contains an invalid member path.")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts) or (len(parts[0]) >= 2 and parts[0][1] == ":"):
        raise RuntimeError("Updater archive contains an unsafe member path.")
    return "/".join(parts)


def verify_updater_payload(path: Path, asset: dict[str, Any]) -> Path:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("Extracted TerminalSSUpdater is missing or empty.")
    expected_hash = str(asset.get("executable_sha256") or "").strip().lower()
    try:
        expected_size = int(asset.get("executable_size_bytes"))
    except Exception as exc:
        raise RuntimeError("Updater manifest contains an invalid executable size.") from exc
    if not expected_hash or expected_size <= 0:
        raise RuntimeError("Updater manifest does not provide complete executable verification data.")
    if path.stat().st_size != expected_size:
        raise RuntimeError("Extracted TerminalSSUpdater size does not match the manifest.")
    if sha256_file(path).lower() != expected_hash:
        raise RuntimeError("Extracted TerminalSSUpdater failed SHA-256 verification.")
    return path


def extract_updater_package(archive_path: Path, asset: dict[str, Any], root: Path) -> Path:
    archive_path = Path(archive_path)
    root = Path(root)
    executable_name = str(asset.get("executable") or "").strip()
    if not executable_name or executable_name != expected_updater_name() or "/" in executable_name.replace("\\", "/"):
        raise RuntimeError("Updater manifest contains an invalid executable name.")
    destination = root / executable_name
    staging = root / ("." + executable_name + ".new")
    remove_path(staging)
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            files = [info for info in archive.infolist() if not info.is_dir()]
            if len(files) != 1:
                raise RuntimeError("Updater archive must contain exactly one file.")
            selected = files[0]
            member_name = normalized_zip_member_name(selected.filename)
            if member_name.casefold() != executable_name.casefold():
                raise RuntimeError("Updater archive does not contain the expected updater executable.")
            unix_mode = (selected.external_attr >> 16) & 0xFFFF
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise RuntimeError("Updater archive executable cannot be a symbolic link.")
            with archive.open(selected, "r") as source, staging.open("wb") as target:
                shutil.copyfileobj(source, target)
        verify_updater_payload(staging, asset)
        if platform.system() == "Linux":
            staging.chmod(staging.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(staging, destination)
        return destination
    finally:
        remove_path(staging)
        remove_path(archive_path)


def clean_launch_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("APPIMAGE", "APPDIR", "ARGV0", "OWD", "TERMINALSS_APPIMAGE_TERMINAL", "APPIMAGE_EXTRACT_AND_RUN"):
        environment.pop(name, None)
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if platform.system() == "Linux":
        original_library_path = environment.get("LD_LIBRARY_PATH_ORIG")
        if original_library_path is None:
            environment.pop("LD_LIBRARY_PATH", None)
        else:
            environment["LD_LIBRARY_PATH"] = original_library_path
    return environment


def linux_updater_terminal_command(command: list[str]) -> list[str] | None:
    candidates = (
        ("gnome-terminal", ("--title=TerminalSS Update", "--")),
        ("kgx", ("--",)),
        ("x-terminal-emulator", ("-e",)),
        ("konsole", ("-e",)),
        ("xterm", ("-T", "TerminalSS Update", "-e")),
    )
    for executable, arguments in candidates:
        resolved = shutil.which(executable)
        if resolved:
            return [resolved, *arguments, *command]
    return None


def launch_updater(updater: Path, target_version: str, current_version: str) -> None:
    target = runtime_application_path()
    auto_terminal = platform.system() == "Linux" and str(os.environ.get("TERMINALSS_APPIMAGE_TERMINAL") or "").strip() == "1"
    environment = clean_launch_environment()
    command = [
        str(updater),
        "--parent-pid", str(os.getpid()),
        "--target", str(target),
        "--current-version", current_version,
        "--target-version", target_version,
        "--release-manifest-url", TERMINALSS_RELEASE_MANIFEST_URL,
    ]
    if platform.system() == "Windows":
        creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(command, cwd=str(updater.parent), env=environment, close_fds=True, creationflags=creation_flags)
        return
    if auto_terminal:
        terminal_command = linux_updater_terminal_command(command)
        if terminal_command is None:
            raise RuntimeError("Could not open a terminal for TerminalSSUpdater.")
        subprocess.Popen(terminal_command, cwd=str(updater.parent), env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        return
    subprocess.Popen(command, cwd=str(updater.parent), env=environment, close_fds=True, start_new_session=True)


def start_external_update(current_version: str, requested_version: str | None = None) -> str:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Automatic updating is only available from a packaged TerminalSS release.")
    target = runtime_application_path()
    required_name = expected_runtime_name()
    if target.name.casefold() != required_name.casefold():
        raise RuntimeError("This TerminalSS build does not use the stable runtime filename required by the updater.")
    update_info = check_update_available(current_version, timeout=20, suppress_errors=False)
    if requested_version:
        manifest = fetch_json(TERMINALSS_RELEASE_MANIFEST_URL, timeout=20)
        releases = manifest.get("releases")
        release = releases.get(requested_version) if isinstance(releases, dict) else None
        if not isinstance(release, dict) or version_key(requested_version) <= version_key(current_version):
            raise RuntimeError("Requested TerminalSS update version is not available or is not newer.")
        asset_key, asset = select_release_asset(release)
        update_info = {"latest_version": requested_version, "release": release, "asset_key": asset_key, "asset": asset}
    if not update_info:
        return current_version
    updater_version, _, updater_asset = resolve_updater_release(current_version)
    download_url = str(updater_asset.get("download_url") or "").strip()
    package_name = str(updater_asset.get("file") or "").strip()
    if not download_url or not package_name or "/" in package_name.replace("\\", "/"):
        raise RuntimeError("Updater manifest contains invalid package information.")
    archive_path = target.parent / ("." + package_name)
    remove_path(archive_path)
    download_verified_file(download_url, archive_path, updater_asset.get("sha256"), updater_asset.get("size_bytes"))
    updater = extract_updater_package(archive_path, updater_asset, target.parent)
    print(f"TerminalSSUpdater {updater_version} verified. Starting update to TerminalSS {update_info['latest_version']}...")
    launch_updater(updater, update_info["latest_version"], current_version)
    time.sleep(0.35)
    return str(update_info["latest_version"])


def process_exists_windows(pid: int) -> bool:
    process = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))
    if not process:
        return False
    ctypes.windll.kernel32.CloseHandle(process)
    return True


def process_exists_posix(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_exists(pid: int) -> bool:
    return process_exists_windows(pid) if platform.system() == "Windows" else process_exists_posix(pid)


def wait_for_process_exit(pid: int, timeout: int = WAIT_TIMEOUT_SECONDS) -> None:
    pid = int(pid)
    if pid <= 0:
        raise RuntimeError("Updater process ID is invalid.")
    deadline = time.monotonic() + timeout
    while process_exists(pid):
        if time.monotonic() >= deadline:
            raise RuntimeError("Timed out waiting for TerminalSSUpdater to exit.")
        time.sleep(POLL_INTERVAL_SECONDS)


def remove_path_with_retries(path: Path, attempts: int = 20) -> None:
    for attempt in range(attempts):
        if not path.exists() and not path.is_symlink():
            return
        try:
            remove_path(path)
            return
        except Exception:
            if attempt + 1 >= attempts:
                raise
            time.sleep(POLL_INTERVAL_SECONDS)


def complete_post_update(current_version: str, updater_pid: int, previous_version: str) -> None:
    if not getattr(sys, "frozen", False):
        return
    if version_key(previous_version) > version_key(current_version):
        raise RuntimeError("Previous TerminalSS version is newer than the installed runtime.")
    wait_for_process_exit(updater_pid)
    target = runtime_application_path()
    root = target.parent
    remove_path_with_retries(root / temporary_runtime_name())
    remove_path_with_retries(root / expected_updater_name())
