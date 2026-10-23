import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

YOUSNIPE_UPDATER_VERSION = "1.0.0"
YOUSNIPE_RELEASE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "Releases/YouSnipe/"
    "YouSnipe_Release_Manifest.json"
)
WAIT_TIMEOUT_SECONDS = 120
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
RESTART_MODES = frozenset({"gui", "headless", "headless-server"})
POLL_INTERVAL_SECONDS = 0.25
HEALTH_TIMEOUT_SECONDS = 180


def version_key(value):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(value or "")):
        raise RuntimeError(f"Invalid version value: {value}")
    parts = str(value).split(".")
    if len(parts) != 3:
        raise RuntimeError(f"Invalid version value: {value}")
    try:
        return tuple(int(part) for part in parts)
    except Exception as exc:
        raise RuntimeError(f"Invalid version value: {value}") from exc


def show(label, value=""):
    print(f"[{label}] {value}" if value else f"[{label}]")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": f"YouSnipeUpdater/{YOUSNIPE_UPDATER_VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(MAX_MANIFEST_BYTES + 1)
            if len(payload) > MAX_MANIFEST_BYTES:
                raise RuntimeError("YouSnipe release manifest exceeds the maximum size.")
    except Exception as exc:
        raise RuntimeError("Could not download the YouSnipe release manifest.") from exc
    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("The downloaded YouSnipe release manifest is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("The YouSnipe release manifest has an invalid root structure.")
    return data


def download_verified_file(url, destination, expected_sha256, expected_size):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    if temporary.exists():
        temporary.unlink()
    expected_hash = str(expected_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise RuntimeError("The release manifest must provide a valid SHA-256 checksum.")
    if not url.startswith("https://"):
        raise RuntimeError("The release package must use HTTPS.")
    try:
        required_size = int(expected_size)
    except Exception as exc:
        raise RuntimeError("The release manifest contains an invalid package size.") from exc
    if required_size <= 0 or required_size > MAX_ARCHIVE_BYTES:
        raise RuntimeError("The release package size is invalid.")
    request = urllib.request.Request(url, headers={"User-Agent": f"YouSnipeUpdater/{YOUSNIPE_UPDATER_VERSION}"})
    try:
        try:
            count = 0
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    count += len(block)
                    if count > required_size:
                        raise RuntimeError("The release download exceeds the declared size.")
                    handle.write(block)
        except Exception as exc:
            raise RuntimeError("Could not download the YouSnipe update package.") from exc
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("The downloaded YouSnipe update package is empty.")
        if temporary.stat().st_size != required_size:
            raise RuntimeError("The downloaded YouSnipe update package size does not match the manifest.")
        if sha256_file(temporary).lower() != expected_hash:
            raise RuntimeError("The downloaded YouSnipe update package failed SHA-256 verification.")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def detect_platform_asset():
    system = platform.system()
    machine = str(platform.machine() or "").strip().lower()
    if system == "Windows":
        if machine in ("amd64", "x86_64", "x64"):
            return "Windows_x86_64", "YouSnipe.exe", "YouSnipeTemp.exe"
        if machine in ("arm64", "aarch64"):
            return "Windows_arm64", "YouSnipe.exe", "YouSnipeTemp.exe"
        raise RuntimeError("Unsupported Windows architecture for YouSnipe updater.")
    if system == "Linux":
        if machine in ("x86_64", "amd64", "x64"):
            return "Linux_x86_64", "YouSnipe.AppImage", "YouSnipeTemp.AppImage"
        if machine in ("aarch64", "arm64"):
            return "Linux_arm64", "YouSnipe.AppImage", "YouSnipeTemp.AppImage"
        raise RuntimeError("Unsupported Linux architecture for YouSnipe updater.")
    raise RuntimeError(f"Unsupported operating system: {system}")


def select_release(manifest, asset_key, current_version, requested_version=None):
    releases = manifest.get("releases")
    if not isinstance(releases, dict):
        raise RuntimeError("The YouSnipe release manifest has an invalid releases object.")
    target_version = str(requested_version or manifest.get("latest_version") or "").strip()
    if not target_version:
        raise RuntimeError("The YouSnipe release manifest does not identify a target version.")
    if version_key(target_version) <= version_key(current_version):
        raise RuntimeError("The requested YouSnipe release is not newer than the installed version.")
    release = releases.get(target_version)
    if not isinstance(release, dict):
        raise RuntimeError(f"YouSnipe release {target_version} is not present in the release manifest.")
    assets = release.get("assets")
    if not isinstance(assets, dict):
        raise RuntimeError(f"YouSnipe release {target_version} has no valid assets object.")
    asset = assets.get(asset_key)
    if not isinstance(asset, dict):
        raise RuntimeError(f"YouSnipe release {target_version} has no {asset_key} asset.")
    return target_version, asset


def validate_release_asset(asset, expected_runtime_name):
    filename = str(asset.get("file") or "").strip()
    download_url = str(asset.get("download_url") or "").strip()
    runtime_name = str(asset.get("executable") or "").strip()
    if not filename.lower().endswith(".zip"):
        raise RuntimeError("The YouSnipe release asset is not a ZIP package.")
    if not download_url.startswith("https://"):
        raise RuntimeError("The YouSnipe release asset requires a HTTPS download URL.")
    if runtime_name.casefold() != expected_runtime_name.casefold():
        raise RuntimeError("The YouSnipe release package does not contain the expected stable runtime name.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(asset.get("sha256") or "").lower()) or asset.get("size_bytes") is None:
        raise RuntimeError("The YouSnipe release package does not provide complete verification data.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(asset.get("executable_sha256") or "").lower()) or asset.get("executable_size_bytes") is None:
        raise RuntimeError("The YouSnipe runtime does not provide complete verification data.")
    return filename, download_url, runtime_name


def process_exists_windows(pid):
    process = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))
    if not process:
        return False
    ctypes.windll.kernel32.CloseHandle(process)
    return True


def process_exists_posix(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_exists(pid):
    return process_exists_windows(pid) if platform.system() == "Windows" else process_exists_posix(pid)


def wait_for_parent(pid):
    pid = int(pid)
    if pid <= 0:
        raise RuntimeError("The parent process ID is invalid.")
    if pid == os.getpid():
        raise RuntimeError("The updater cannot wait for its own process ID.")
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    show("WAIT", f"YouSnipe process {pid}")
    while process_exists(pid):
        if time.monotonic() >= deadline:
            raise RuntimeError("Timed out waiting for YouSnipe to exit.")
        time.sleep(POLL_INTERVAL_SECONDS)


def ensure_target(target, expected_runtime_name):
    target = Path(target).expanduser().resolve()
    if target.name.casefold() != expected_runtime_name.casefold():
        raise RuntimeError("The supplied YouSnipe target does not use the expected stable runtime filename.")
    if not target.parent.is_dir():
        raise RuntimeError("The YouSnipe installation folder does not exist.")
    return target


def remove_path(path):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)


def extract_runtime(archive_path, expected_runtime_name, destination, asset):
    archive_path = Path(archive_path)
    destination = Path(destination)
    remove_path(destination)
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            candidates = []
            for info in archive.infolist():
                if info.is_dir():
                    continue
                normalized = info.filename.replace("\\", "/")
                parts = normalized.split("/")
                if (not normalized or "\x00" in normalized or normalized.startswith("/")
                        or ".." in parts or (parts[0].endswith(":") if parts else False)):
                    raise RuntimeError("The YouSnipe release archive contains an unsafe path.")
                member_name = normalized.rsplit("/", 1)[-1]
                if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
                    raise RuntimeError("The YouSnipe release archive contains a symbolic link.")
                if member_name.casefold() == expected_runtime_name.casefold():
                    if normalized not in (expected_runtime_name, 'YouSnipe/' + expected_runtime_name):
                        raise RuntimeError("Unexpected YouSnipe executable path inside release ZIP.")
                    unix_mode = info.external_attr >> 16
                    if unix_mode and stat.S_ISLNK(unix_mode):
                        raise RuntimeError("The YouSnipe release archive contains an invalid symbolic-link runtime.")
                    candidates.append(info)
            if len(candidates) != 1:
                raise RuntimeError("The YouSnipe release archive must contain exactly one expected runtime.")
            expected_bytes = int(asset.get("executable_size_bytes"))
            if expected_bytes <= 0 or expected_bytes > MAX_ARCHIVE_BYTES or candidates[0].file_size != expected_bytes:
                raise RuntimeError("The declared runtime size does not match the release archive.")
            with archive.open(candidates[0], "r") as source, destination.open("wb") as handle:
                total = 0
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > expected_bytes:
                        raise RuntimeError("Extracted runtime exceeds the declared size.")
                    handle.write(block)
        expected_hash = str(asset.get("executable_sha256") or "").strip().lower()
        try:
            expected_size = int(asset.get("executable_size_bytes"))
        except Exception as exc:
            raise RuntimeError("The YouSnipe runtime size in the release manifest is invalid.") from exc
        if expected_size <= 0 or destination.stat().st_size != expected_size:
            raise RuntimeError("The extracted YouSnipe runtime size does not match the release manifest.")
        if sha256_file(destination).lower() != expected_hash:
            raise RuntimeError("The extracted YouSnipe runtime failed SHA-256 verification.")
        if platform.system() == "Linux":
            destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return destination
    except Exception:
        remove_path(destination)
        raise


def clean_launch_environment():
    environment = os.environ.copy()
    for name in ("APPIMAGE", "APPDIR", "ARGV0", "OWD", "YOUSNIPE_APPIMAGE_TERMINAL", "APPIMAGE_EXTRACT_AND_RUN"):
        environment.pop(name, None)
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if platform.system() == "Linux":
        original_library_path = environment.get("LD_LIBRARY_PATH_ORIG")
        if original_library_path is None:
            environment.pop("LD_LIBRARY_PATH", None)
        else:
            environment["LD_LIBRARY_PATH"] = original_library_path
    return environment


def launch_application(target, arguments, restart_mode="gui"):
    command = [str(target), *[str(value) for value in arguments]]
    if platform.system() == "Windows":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(command, cwd=str(target.parent), env=clean_launch_environment(),
                                close_fds=True, creationflags=creation_flags)
    return subprocess.Popen(command, cwd=str(target.parent), env=clean_launch_environment(),
                            close_fds=True, start_new_session=True)


def wait_for_application_ready(process, marker_path, token, target_version):
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if marker_path.is_file():
            try:
                message = json.loads(marker_path.read_text(encoding='utf-8'))
                if (message.get('token') == token and message.get('pid') == process.pid
                    and message.get('version') == target_version):
                    show('READY', 'Replacement startup verified')
                    return
            except (OSError, ValueError, TypeError):
                pass
        if process.poll() is not None:
            raise RuntimeError(f'The replacement application exited before confirming startup (code {process.returncode})')
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError('The replacement application did not confirm a healthy startup in time')


def terminate_failed_application(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def rollback(target, temporary_target):
    remove_path(target)
    if Path(temporary_target).exists():
        os.replace(temporary_target, target)
        if platform.system() == "Linux":
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return True
    return False


def parse_args():
    parser = argparse.ArgumentParser(prog="YouSnipeUpdater")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--target")
    parser.add_argument("--current-version")
    parser.add_argument("--target-version")
    parser.add_argument("--restart-mode", choices=sorted(RESTART_MODES), default="gui")
    parser.add_argument("--release-manifest-url", default=YOUSNIPE_RELEASE_MANIFEST_URL)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.version:
        print(f"YouSnipeUpdater {YOUSNIPE_UPDATER_VERSION}")
        return 0
    missing = []
    if args.parent_pid is None:
        missing.append("--parent-pid")
    if not args.target:
        missing.append("--target")
    if not args.current_version:
        missing.append("--current-version")
    if missing:
        raise RuntimeError("Missing required updater arguments: " + ", ".join(missing))
    asset_key, runtime_name, temporary_name = detect_platform_asset()
    target = ensure_target(args.target, runtime_name)
    root = target.parent
    temporary_target = root / temporary_name
    if temporary_target.exists():
        raise RuntimeError(f"A previous update backup already exists: {temporary_target.name}")
    manifest = fetch_json(args.release_manifest_url)
    target_version, asset = select_release(manifest, asset_key, args.current_version, args.target_version)
    package_name, package_url, expected_runtime_name = validate_release_asset(asset, runtime_name)
    archive_path = root / (".YouSnipeUpdate_" + target_version + "_" + asset_key + ".zip")
    staging_target = root / ("." + runtime_name + ".new")
    renamed = False
    installed = False
    new_process = None
    health_marker = root / f'.YouSnipeUpdateHealth_{os.getpid()}.json'
    try:
        show("DOWNLOAD", package_name)
        download_verified_file(package_url, archive_path, asset.get("sha256"), asset.get("size_bytes"))
        show("STAGE", expected_runtime_name)
        extract_runtime(archive_path, expected_runtime_name, staging_target, asset)
        remove_path(archive_path)
        wait_for_parent(args.parent_pid)
        if not target.is_file():
            raise RuntimeError(f"The installed YouSnipe runtime is missing: {target.name}")
        show("BACKUP", f"{target.name} -> {temporary_target.name}")
        target.rename(temporary_target)
        renamed = True
        show("INSTALL", expected_runtime_name)
        os.replace(staging_target, target)
        installed = True
        if platform.system() == "Linux":
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        show("START", target.name)
        health_token = secrets.token_hex(16)
        startup_arguments = ["--updated", "--updater-pid", str(os.getpid()),
                             "--previous-version", str(args.current_version), "--updater-path",
                             str(Path(sys.executable).resolve() if getattr(sys, "frozen", False) else Path(__file__).resolve()),
                             "--update-health-token", health_token]
        if args.restart_mode != "gui":
            startup_arguments.insert(0, "--" + args.restart_mode)
        new_process = launch_application(target, startup_arguments, restart_mode=args.restart_mode)
        wait_for_application_ready(new_process, health_marker, health_token, target_version)
        print(f"YouSnipe {target_version} installed and startup verified.")
        return 0
    except Exception:
        terminate_failed_application(new_process)
        remove_path(staging_target)
        remove_path(archive_path)
        if renamed:
            try:
                restored = rollback(target, temporary_target)
            except Exception:
                restored = False
            if restored:
                try:
                    show("ROLLBACK", target.name)
                    recovery_arguments = ["--" + args.restart_mode] if args.restart_mode != "gui" else []
                    launch_application(target, recovery_arguments, restart_mode=args.restart_mode)
                except Exception:
                    pass
        raise
    finally:
        health_marker.unlink(missing_ok=True)
        if not installed and staging_target.exists():
            remove_path(staging_target)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Update cancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print("UPDATE FAILED: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
