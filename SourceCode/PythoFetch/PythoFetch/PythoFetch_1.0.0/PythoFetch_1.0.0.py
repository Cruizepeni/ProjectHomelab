import argparse
import ctypes
import getpass
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import sqlite3
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import timedelta
from pathlib import Path

PYTHOFETCH_VERSION = "1.0.0"
ART_DATABASE_SCHEMA_VERSION = 1
NARROW_ART_WIDTH = 80

ART_DATABASE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "SourceCode/PythoFetch/"
    "PythoFetchArtAssets/ArtAssetsDB/"
    "PythoFetchArtDB_Manifest.json"
)

RELEASE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "Releases/PythoFetch/"
    "PythoFetch_Release_Manifest.json"
)


def version_key(value):
    try:
        return tuple(
            int(part)
            for part in str(value).split(".")
        )
    except Exception as exc:
        raise RuntimeError(
            f"Invalid version value: {value}"
        ) from exc


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                f"PythoFetch/{PYTHOFETCH_VERSION}",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            payload = response.read()
    except Exception as exc:
        raise RuntimeError(
            "Could not download manifest."
        ) from exc

    try:
        data = json.loads(
            payload.decode("utf-8")
        )
    except Exception as exc:
        raise RuntimeError(
            "Downloaded manifest is not "
            "valid JSON."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            "Downloaded manifest has an "
            "invalid root structure."
        )

    return data


def sha256_file(path):
    digest = hashlib.sha256()

    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def download_verified_file(
    url,
    destination,
    expected_sha256,
    expected_size=None,
):
    destination = Path(destination)
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = destination.with_name(
        destination.name + ".download"
    )

    if temporary.exists():
        temporary.unlink()

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                f"PythoFetch/{PYTHOFETCH_VERSION}",
        },
    )

    try:
        try:
            with urllib.request.urlopen(
                request,
                timeout=60,
            ) as response:
                with temporary.open(
                    "wb"
                ) as handle:
                    shutil.copyfileobj(
                        response,
                        handle,
                    )
        except Exception as exc:
            raise RuntimeError(
                "Download failed."
            ) from exc

        if (
            not temporary.is_file()
            or temporary.stat().st_size == 0
        ):
            raise RuntimeError(
                "Downloaded file is empty."
            )

        if expected_size is not None:
            try:
                required_size = int(
                    expected_size
                )
            except Exception as exc:
                raise RuntimeError(
                    "Manifest contains an "
                    "invalid file size."
                ) from exc

            if (
                temporary.stat().st_size
                != required_size
            ):
                raise RuntimeError(
                    "Downloaded file size "
                    "does not match the "
                    "manifest."
                )

        expected_hash = str(
            expected_sha256 or ""
        ).strip().lower()

        if not expected_hash:
            raise RuntimeError(
                "Manifest does not provide "
                "a SHA-256 checksum."
            )

        actual_hash = sha256_file(
            temporary
        ).lower()

        if actual_hash != expected_hash:
            raise RuntimeError(
                "Downloaded file failed "
                "SHA-256 verification."
            )

        os.replace(
            temporary,
            destination,
        )

    finally:
        if temporary.exists():
            temporary.unlink()

    return destination


def run_command(command, timeout=6):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=isinstance(command, str),
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def run_powershell(script, timeout=8):
    return run_command(
        [
            "powershell",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        timeout=timeout,
    )


def compact_spaces(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def format_uptime(seconds):
    seconds = max(0, int(seconds))
    delta = timedelta(seconds=seconds)

    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} min")

    return ", ".join(parts)


def mib(value):
    return int(round(value / 1024 / 1024))


def get_memory_snapshot():
    system = platform.system()

    if system == "Windows":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        try:
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(status)

            if ctypes.windll.kernel32.GlobalMemoryStatusEx(
                ctypes.byref(status)
            ):
                total = int(status.ullTotalPhys)
                available = int(status.ullAvailPhys)
                used = max(0, total - available)
                percent = used / total * 100 if total else 0

                return {
                    "used": used,
                    "total": total,
                    "percent": percent,
                }
        except Exception:
            pass

    if system == "Linux":
        values = {}

        try:
            with open(
                "/proc/meminfo",
                "r",
                encoding="utf-8",
                errors="replace",
            ) as handle:
                for raw in handle:
                    if ":" not in raw:
                        continue

                    key, value = raw.split(":", 1)
                    match = re.search(r"\d+", value)

                    if match:
                        values[key.strip()] = int(match.group(0)) * 1024
        except Exception:
            values = {}

        total = values.get("MemTotal")
        available = values.get("MemAvailable")

        if available is None:
            available = sum(
                values.get(name, 0)
                for name in (
                    "MemFree",
                    "Buffers",
                    "Cached",
                    "SReclaimable",
                )
            )

        if total:
            used = max(0, total - int(available or 0))

            return {
                "used": used,
                "total": total,
                "percent": used / total * 100,
            }

    if system == "Darwin":
        total_text = run_command(
            ["sysctl", "-n", "hw.memsize"]
        )
        vm_text = run_command(["vm_stat"])

        try:
            total = int(total_text)
        except Exception:
            total = 0

        page_size = 4096
        match = re.search(
            r"page size of\s+(\d+)\s+bytes",
            vm_text,
            re.IGNORECASE,
        )

        if match:
            page_size = int(match.group(1))

        page_values = {}

        for raw in vm_text.splitlines():
            match = re.match(
                r"([^:]+):\s+(\d+)",
                raw.strip(),
            )

            if not match:
                continue

            page_values[match.group(1).strip()] = int(match.group(2))

        available_pages = sum(
            page_values.get(name, 0)
            for name in (
                "Pages free",
                "Pages inactive",
                "Pages speculative",
                "Pages purgeable",
            )
        )

        if total:
            available = available_pages * page_size
            used = max(0, min(total, total - available))

            return {
                "used": used,
                "total": total,
                "percent": used / total * 100,
            }

    return {
        "used": 0,
        "total": 0,
        "percent": 0,
    }


def get_cpu_counts():
    logical = os.cpu_count() or None
    physical = None
    system = platform.system()

    if system == "Windows":
        script = (
            "$cpus = @(Get-CimInstance Win32_Processor); "
            "$physical = ($cpus | Measure-Object -Property "
            "NumberOfCores -Sum).Sum; "
            "$logical = ($cpus | Measure-Object -Property "
            "NumberOfLogicalProcessors -Sum).Sum; "
            "[pscustomobject]@{Physical=$physical;Logical=$logical} "
            "| ConvertTo-Json -Compress"
        )

        output = run_powershell(
            script,
            timeout=4,
        )

        try:
            data = json.loads(output)
            physical = int(data.get("Physical"))
            logical = int(data.get("Logical"))
        except Exception:
            pass

    elif system == "Linux":
        core_pairs = set()
        current_physical = None
        current_core = None

        try:
            with open(
                "/proc/cpuinfo",
                "r",
                encoding="utf-8",
                errors="replace",
            ) as handle:
                rows = list(handle)

            for raw in rows + ["\n"]:
                line = raw.strip()

                if not line:
                    if (
                        current_physical is not None
                        and current_core is not None
                    ):
                        core_pairs.add(
                            (
                                current_physical,
                                current_core,
                            )
                        )

                    current_physical = None
                    current_core = None
                    continue

                if ":" not in line:
                    continue

                key, value = line.split(":", 1)
                key = key.strip().lower()
                value = value.strip()

                if key == "physical id":
                    current_physical = value
                elif key == "core id":
                    current_core = value

            if core_pairs:
                physical = len(core_pairs)
        except Exception:
            pass

        if physical is None:
            output = run_command(
                ["lscpu", "-p=core"]
            )

            core_ids = {
                line.strip()
                for line in output.splitlines()
                if line.strip() and not line.startswith("#")
            }

            if core_ids:
                physical = len(core_ids)

    elif system == "Darwin":
        physical_text = run_command(
            ["sysctl", "-n", "hw.physicalcpu"]
        )
        logical_text = run_command(
            ["sysctl", "-n", "hw.logicalcpu"]
        )

        try:
            physical = int(physical_text)
        except Exception:
            pass

        try:
            logical = int(logical_text)
        except Exception:
            pass

    return physical, logical


def get_boot_time():
    system = platform.system()

    if system == "Windows":
        try:
            uptime_ms = ctypes.windll.kernel32.GetTickCount64()
            return time.time() - float(uptime_ms) / 1000.0
        except Exception:
            pass

    if system == "Linux":
        try:
            uptime = float(
                Path("/proc/uptime")
                .read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                .split()[0]
            )
            return time.time() - uptime
        except Exception:
            pass

    if system == "Darwin":
        output = run_command(
            ["sysctl", "-n", "kern.boottime"]
        )

        match = re.search(
            r"sec\s*=\s*(\d+)",
            output,
        )

        if match:
            return float(match.group(1))

    return time.time()


def get_linux_cpu_max_mhz():
    values = []
    cpu_root = Path("/sys/devices/system/cpu")

    try:
        for path in cpu_root.glob(
            "cpu[0-9]*/cpufreq/cpuinfo_max_freq"
        ):
            try:
                value = float(
                    path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ).strip()
                )

                if value > 0:
                    values.append(value / 1000.0)
            except Exception:
                pass
    except Exception:
        pass

    if values:
        return max(values)

    output = run_command(["lscpu"])

    for raw in output.splitlines():
        if raw.lower().startswith("cpu max mhz:"):
            try:
                return float(
                    raw.split(":", 1)[1].strip()
                )
            except Exception:
                pass

    return None



def format_cpu_display(cpu_name, logical_cores=None, max_mhz=None):
    name = compact_spaces(cpu_name) or "Unknown"
    embedded_frequency = None

    match = re.search(r"\s+@\s+([0-9.]+\s*[GMK]?Hz)\s*$", name, re.IGNORECASE)
    if match:
        embedded_frequency = match.group(1).replace(" ", "")
        name = name[:match.start()].rstrip()

    display = name

    if logical_cores:
        display += f" ({logical_cores})"

    if embedded_frequency:
        display += f" @ {embedded_frequency}"
    elif max_mhz:
        display += f" @ {float(max_mhz) / 1000:.2f}GHz"

    return display


def get_parent_process_names():
    if platform.system() == "Windows":
        return []

    names = []
    pid = os.getppid()

    for _ in range(8):
        if not pid or pid <= 1:
            break

        name = run_command(
            [
                "ps",
                "-o",
                "comm=",
                "-p",
                str(pid),
            ],
            timeout=2,
        )

        if name:
            names.append(
                os.path.basename(name.strip())
            )

        parent = run_command(
            [
                "ps",
                "-o",
                "ppid=",
                "-p",
                str(pid),
            ],
            timeout=2,
        )

        try:
            next_pid = int(parent.strip())
        except Exception:
            break

        if next_pid == pid:
            break

        pid = next_pid

    return names


def get_shell():
    parent_names = get_parent_process_names()

    shell_map = {
        "pwsh.exe": "PowerShell",
        "powershell.exe": "PowerShell",
        "cmd.exe": "cmd",
        "bash.exe": "bash",
        "zsh.exe": "zsh",
        "fish.exe": "fish",
        "nu.exe": "nushell",
    }

    for name in parent_names:
        detected = shell_map.get(name.lower())
        if detected:
            if detected == "PowerShell":
                exe = "pwsh" if name.lower() == "pwsh.exe" else "powershell"
                version = run_command(
                    [exe, "-NoLogo", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
                    timeout=3,
                )
                return f"PowerShell {version}" if version else "PowerShell"
            return detected

    if platform.system() == "Windows":
        return "cmd"

    shell = os.environ.get("SHELL")
    if shell:
        return os.path.basename(shell)

    return None


def get_terminal():
    if os.environ.get("WT_SESSION"):
        return "Windows Terminal"

    term_program = os.environ.get("TERM_PROGRAM")
    if term_program:
        version = os.environ.get("TERM_PROGRAM_VERSION")
        return f"{term_program} {version}".strip() if version else term_program

    if os.environ.get("ConEmuANSI") == "ON":
        return "ConEmu"

    if os.environ.get("ANSICON"):
        return "ANSICON"

    if platform.system() == "Windows":
        parents = [name.lower() for name in get_parent_process_names()]
        if "windowsterminal.exe" in parents:
            return "Windows Terminal"
        return "Windows Console Host"

    return os.environ.get("TERM") or None


def get_resolution():
    if platform.system() == "Windows":
        try:
            user32 = ctypes.windll.user32
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    user32.SetProcessDPIAware()
                except Exception:
                    pass

            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            if width and height:
                return f"{width}x{height}"
        except Exception:
            pass

    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.destroy()
        if width and height:
            return f"{width}x{height}"
    except Exception:
        pass

    return None


def get_windows_theme():
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            apps, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "Light" if int(apps) else "Dark"
    except Exception:
        return None


def get_windows_packages():
    parts = []

    scoop_root = Path(os.environ.get("USERPROFILE", "")) / "scoop" / "apps"
    try:
        if scoop_root.is_dir():
            apps = [
                p for p in scoop_root.iterdir()
                if p.is_dir() and p.name.lower() not in {"scoop"}
            ]
            if apps:
                parts.append(f"{len(apps)} (scoop)")
    except Exception:
        pass

    choco_root = Path(os.environ.get("ChocolateyInstall", r"C:\ProgramData\chocolatey")) / "lib"
    try:
        if choco_root.is_dir():
            packages = [p for p in choco_root.iterdir() if p.is_dir()]
            if packages:
                parts.append(f"{len(packages)} (choco)")
    except Exception:
        pass

    return ", ".join(parts) if parts else None


def get_windows_cim_snapshot():
    script = r'''
$cs = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })

[pscustomobject]@{
    Manufacturer = $cs.Manufacturer
    Model        = $cs.Model
    OSCaption    = $os.Caption
    OSVersion    = $os.Version
    BuildNumber  = $os.BuildNumber
    CPUName      = $cpu.Name
    CPUMaxMHz    = $cpu.MaxClockSpeed
    GPUs         = $gpus
} | ConvertTo-Json -Depth 4 -Compress
'''
    output = run_powershell(script)
    if not output:
        return {}

    try:
        data = json.loads(output)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_linux_os_release():
    try:
        if hasattr(platform, "freedesktop_os_release"):
            return platform.freedesktop_os_release()
    except Exception:
        pass

    values = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    values[key] = value.strip().strip('"')
            if values:
                break
        except Exception:
            pass
    return values


def get_linux_cpu_name():
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if key.strip().lower() in ("model name", "hardware"):
                    value = value.strip()
                    if value:
                        return value
    except Exception:
        pass

    output = run_command(["lscpu"])
    for line in output.splitlines():
        if line.lower().startswith("model name:"):
            return line.split(":", 1)[1].strip()

    return platform.processor() or None


def get_linux_gpus():
    output = run_command(["lspci"])
    gpus = []

    for line in output.splitlines():
        lower = line.lower()
        if (
            "vga compatible controller" in lower
            or "3d controller" in lower
            or "display controller" in lower
        ):
            value = line.split(": ", 1)[1].strip() if ": " in line else line.strip()
            if value and value not in gpus:
                gpus.append(value)

    return gpus


def get_linux_machine_model():
    model = None
    manufacturer = None

    for path in (
        "/sys/devices/virtual/dmi/id/product_name",
        "/sys/firmware/devicetree/base/model",
    ):
        try:
            model = Path(path).read_text(encoding="utf-8", errors="replace").strip("\x00\n ")
            if model:
                break
        except Exception:
            pass

    for path in (
        "/sys/devices/virtual/dmi/id/sys_vendor",
        "/sys/devices/virtual/dmi/id/board_vendor",
    ):
        try:
            manufacturer = Path(path).read_text(encoding="utf-8", errors="replace").strip("\x00\n ")
            if manufacturer:
                break
        except Exception:
            pass

    value = compact_spaces(f"{manufacturer or ''} {model or ''}")
    return value or None


def get_macos_snapshot():
    hardware = run_command(["system_profiler", "SPHardwareDataType"])
    displays = run_command(["system_profiler", "SPDisplaysDataType"])

    model = None
    cpu = None
    gpus = []

    for line in hardware.splitlines():
        stripped = line.strip()
        if stripped.startswith("Model Name:"):
            model = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Model Identifier:") and not model:
            model = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Chip:"):
            cpu = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Processor Name:") and not cpu:
            cpu = stripped.split(":", 1)[1].strip()

    for line in displays.splitlines():
        stripped = line.strip()
        if stripped.startswith("Chipset Model:"):
            value = stripped.split(":", 1)[1].strip()
            if value and value not in gpus:
                gpus.append(value)

    if not cpu:
        cpu = run_command(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor() or None

    return {"model": model, "cpu": cpu, "gpus": gpus}


def get_primary_disk():
    target = (os.environ.get("SystemDrive", "C:") + "\\") if platform.system() == "Windows" else "/"

    try:
        usage = shutil.disk_usage(target)
        return {
            "mount": target,
            "used": usage.used,
            "total": usage.total,
            "percent": usage.used / usage.total * 100 if usage.total else 0,
        }
    except Exception:
        return None


def collect_windows_snapshot():
    cim = get_windows_cim_snapshot()
    memory = get_memory_snapshot()
    disk = get_primary_disk()

    os_caption = compact_spaces(cim.get("OSCaption"))
    if os_caption.lower().startswith("microsoft "):
        os_caption = os_caption[10:]

    version = compact_spaces(cim.get("OSVersion"))
    build = compact_spaces(cim.get("BuildNumber"))
    kernel = version or platform.version()

    manufacturer = compact_spaces(cim.get("Manufacturer"))
    model = compact_spaces(cim.get("Model"))
    host_model = compact_spaces(f"{manufacturer} {model}") or None

    cpu_name = compact_spaces(cim.get("CPUName")) or platform.processor() or "Unknown"
    max_mhz = cim.get("CPUMaxMHz")

    try:
        max_mhz = int(max_mhz) if max_mhz is not None else None
    except Exception:
        max_mhz = None

    gpus = cim.get("GPUs") or []
    if isinstance(gpus, str):
        gpus = [gpus]
    gpus = [compact_spaces(gpu) for gpu in gpus if compact_spaces(gpu)]

    physical, logical = get_cpu_counts()

    cpu_display = format_cpu_display(cpu_name, logical, max_mhz)

    return {
        "provider": "Windows",
        "user": getpass.getuser(),
        "hostname": socket.gethostname(),
        "os": os_caption or f"Windows {platform.release()}",
        "host": host_model,
        "kernel": kernel,
        "build": build or None,
        "uptime": format_uptime(time.time() - get_boot_time()),
        "packages": get_windows_packages(),
        "shell": get_shell(),
        "resolution": get_resolution(),
        "de": "Windows Shell",
        "wm": "Desktop Window Manager",
        "wm_theme": None,
        "theme": get_windows_theme(),
        "icons": None,
        "terminal": get_terminal(),
        "terminal_font": None,
        "cpu": cpu_display,
        "cpu_name": cpu_name,
        "physical_cores": physical,
        "logical_cores": logical,
        "cpu_max_mhz": max_mhz,
        "gpus": gpus or ["Unknown"],
        "memory_used_mib": mib(memory["used"]),
        "memory_total_mib": mib(memory["total"]),
        "memory_percent": memory["percent"],
        "disk": disk,
        "architecture": platform.machine() or None,
    }


def collect_linux_snapshot():
    os_release = get_linux_os_release()
    memory = get_memory_snapshot()
    disk = get_primary_disk()

    pretty = os_release.get("PRETTY_NAME") or os_release.get("NAME") or "Linux"
    cpu_name = get_linux_cpu_name() or "Unknown"
    physical, logical = get_cpu_counts()

    try:
        max_mhz = get_linux_cpu_max_mhz()
    except Exception:
        max_mhz = None

    cpu_display = format_cpu_display(cpu_name, logical, max_mhz)

    return {
        "provider": "Linux",
        "user": getpass.getuser(),
        "hostname": socket.gethostname(),
        "os": pretty,
        "host": get_linux_machine_model(),
        "kernel": platform.release(),
        "build": None,
        "uptime": format_uptime(time.time() - get_boot_time()),
        "packages": None,
        "shell": get_shell(),
        "resolution": get_resolution(),
        "de": os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION"),
        "wm": os.environ.get("XDG_SESSION_DESKTOP"),
        "wm_theme": None,
        "theme": None,
        "icons": None,
        "terminal": get_terminal(),
        "terminal_font": None,
        "cpu": cpu_display,
        "cpu_name": cpu_name,
        "physical_cores": physical,
        "logical_cores": logical,
        "cpu_max_mhz": max_mhz,
        "gpus": get_linux_gpus() or ["Unknown"],
        "memory_used_mib": mib(memory["used"]),
        "memory_total_mib": mib(memory["total"]),
        "memory_percent": memory["percent"],
        "disk": disk,
        "architecture": platform.machine() or None,
        "distro_id": os_release.get("ID"),
        "distro_like": os_release.get("ID_LIKE"),
    }


def collect_macos_snapshot():
    details = get_macos_snapshot()
    memory = get_memory_snapshot()
    disk = get_primary_disk()

    mac_version = platform.mac_ver()[0]
    cpu_name = details["cpu"] or "Unknown"
    physical, logical = get_cpu_counts()

    cpu_display = format_cpu_display(cpu_name, logical, None)

    return {
        "provider": "macOS",
        "user": getpass.getuser(),
        "hostname": socket.gethostname(),
        "os": f"macOS {mac_version}".strip(),
        "host": details["model"],
        "kernel": platform.release(),
        "build": None,
        "uptime": format_uptime(time.time() - get_boot_time()),
        "packages": None,
        "shell": get_shell(),
        "resolution": get_resolution(),
        "de": "Aqua",
        "wm": "Quartz Compositor",
        "wm_theme": None,
        "theme": None,
        "icons": None,
        "terminal": get_terminal(),
        "terminal_font": None,
        "cpu": cpu_display,
        "cpu_name": cpu_name,
        "physical_cores": physical,
        "logical_cores": logical,
        "cpu_max_mhz": None,
        "gpus": details["gpus"] or ["Unknown"],
        "memory_used_mib": mib(memory["used"]),
        "memory_total_mib": mib(memory["total"]),
        "memory_percent": memory["percent"],
        "disk": disk,
        "architecture": platform.machine() or None,
    }


def collect_system_snapshot():
    system = platform.system()

    if system == "Windows":
        return collect_windows_snapshot()
    if system == "Linux":
        return collect_linux_snapshot()
    if system == "Darwin":
        return collect_macos_snapshot()

    raise RuntimeError(f"Unsupported operating system: {system}")



ART_DATABASE_PATTERN = re.compile(
    r"^PythoFetchArt_(\d+(?:\.\d+)*)\.db$",
    re.IGNORECASE,
)

_ART_DATABASE = None


def runtime_directories():
    directories = []

    if getattr(sys, "frozen", False):
        bundle_dir = getattr(
            sys,
            "_MEIPASS",
            None,
        )

        if bundle_dir:
            directories.append(
                Path(bundle_dir).resolve()
            )
        else:
            directories.append(
                Path(
                    sys.executable
                ).resolve().parent
            )

    else:
        source_dir = (
            Path(__file__).resolve().parent
        )

        directories.append(
            source_dir
        )

        development_db = (
            source_dir
            / "PythoFetchArtAssets"
            / "ArtAssetsDB"
        )

        if development_db.is_dir():
            directories.append(
                development_db
            )

    unique = []
    seen = set()

    for directory in directories:
        key = os.path.normcase(
            str(directory)
        )

        if key not in seen:
            seen.add(key)
            unique.append(directory)

    return unique


def database_version_key(path):
    match = ART_DATABASE_PATTERN.match(
        Path(path).name
    )

    if not match:
        return ()

    return version_key(
        match.group(1)
    )


def read_database_metadata(
    connection,
):
    rows = connection.execute(
        """
        SELECT key, value
        FROM metadata
        """
    ).fetchall()

    return {
        str(key): str(value)
        for key, value in rows
    }


def validate_art_database(
    path,
    expected_version=None,
):
    path = Path(path)

    if not path.is_file():
        raise RuntimeError(
            "Art database file is missing."
        )

    connection = sqlite3.connect(
        str(path)
    )

    try:
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if (
            not integrity
            or integrity[0] != "ok"
        ):
            raise RuntimeError(
                "Art database integrity "
                "check failed."
            )

        metadata = read_database_metadata(
            connection
        )

        if (
            metadata.get(
                "database_name"
            )
            != "PythoFetchArt"
        ):
            raise RuntimeError(
                "Art database identity "
                "is invalid."
            )

        try:
            schema_version = int(
                metadata.get(
                    "schema_version",
                    "",
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "Art database schema "
                "metadata is invalid."
            ) from exc

        if (
            schema_version
            != ART_DATABASE_SCHEMA_VERSION
        ):
            raise RuntimeError(
                "Art database schema is "
                "not compatible with this "
                "PythoFetch version."
            )

        database_version = metadata.get(
            "database_version"
        )

        if (
            expected_version is not None
            and database_version
            != expected_version
        ):
            raise RuntimeError(
                "Art database version "
                "metadata does not match "
                "the manifest."
            )

        artwork_count = connection.execute(
            "SELECT COUNT(*) FROM artwork"
        ).fetchone()[0]

        if artwork_count <= 0:
            raise RuntimeError(
                "Art database contains no "
                "artwork."
            )

        return metadata

    except sqlite3.Error as exc:
        raise RuntimeError(
            "Art database could not be "
            "validated."
        ) from exc

    finally:
        connection.close()


def latest_compatible_database_entry(
    manifest,
):
    versions = manifest.get(
        "versions"
    )

    if not isinstance(versions, dict):
        raise RuntimeError(
            "Art database manifest has an "
            "invalid versions object."
        )

    compatible = []

    for version, entry in versions.items():
        if not isinstance(entry, dict):
            continue

        try:
            schema_version = int(
                entry.get(
                    "schema_version"
                )
            )
        except Exception:
            continue

        if (
            schema_version
            != ART_DATABASE_SCHEMA_VERSION
        ):
            continue

        try:
            key = version_key(version)
        except Exception:
            continue

        compatible.append(
            (
                key,
                str(version),
                entry,
            )
        )

    if not compatible:
        raise RuntimeError(
            "Art database manifest contains "
            "no compatible database version."
        )

    compatible.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return (
        compatible[0][1],
        compatible[0][2],
    )


def development_database_directory():
    source_dir = (
        Path(__file__).resolve().parent
    )

    development_db = (
        source_dir
        / "PythoFetchArtAssets"
        / "ArtAssetsDB"
    )

    if development_db.is_dir():
        return development_db

    return source_dir


def download_latest_art_database():
    manifest = fetch_json(
        ART_DATABASE_MANIFEST_URL
    )

    version, entry = (
        latest_compatible_database_entry(
            manifest
        )
    )

    filename = str(
        entry.get("file") or ""
    ).strip()

    download_url = str(
        entry.get(
            "download_url"
        )
        or ""
    ).strip()

    if (
        not filename
        or not ART_DATABASE_PATTERN.match(
            filename
        )
    ):
        raise RuntimeError(
            "Art database manifest contains "
            "an invalid database filename."
        )

    if not download_url:
        raise RuntimeError(
            "Art database manifest does not "
            "provide a download URL."
        )

    destination = (
        development_database_directory()
        / filename
    )

    download_verified_file(
        download_url,
        destination,
        entry.get("sha256"),
        entry.get("size_bytes"),
    )

    try:
        validate_art_database(
            destination,
            expected_version=version,
        )
    except Exception:
        if destination.exists():
            destination.unlink()
        raise

    return destination


def find_art_database():
    global _ART_DATABASE

    if _ART_DATABASE is not None:
        return _ART_DATABASE

    candidates = []

    for directory in runtime_directories():
        try:
            for path in directory.iterdir():
                if (
                    path.is_file()
                    and ART_DATABASE_PATTERN.match(
                        path.name
                    )
                ):
                    candidates.append(
                        path
                    )
        except Exception:
            pass

    candidates.sort(
        key=database_version_key,
        reverse=True,
    )

    for candidate in candidates:
        try:
            validate_art_database(
                candidate
            )
        except Exception:
            continue

        _ART_DATABASE = candidate
        return _ART_DATABASE

    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "The bundled PythoFetch art "
            "database is missing or invalid. "
            "Reinstall PythoFetch."
        )

    try:
        _ART_DATABASE = (
            download_latest_art_database()
        )
    except Exception as exc:
        raise RuntimeError(
            "No compatible PythoFetch art "
            "database was found and automatic "
            "database recovery failed."
        ) from exc

    return _ART_DATABASE


ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"

ANSI_FG = {
    0: "\033[30m",
    1: "\033[31m",
    2: "\033[32m",
    3: "\033[33m",
    4: "\033[34m",
    5: "\033[35m",
    6: "\033[36m",
    7: "\033[37m",
}

ANSI_BG = {
    0: "\033[40m",
    1: "\033[41m",
    2: "\033[42m",
    3: "\033[43m",
    4: "\033[44m",
    5: "\033[45m",
    6: "\033[46m",
    7: "\033[47m",
}

ANSI_BG_BRIGHT = {
    0: "\033[100m",
    1: "\033[101m",
    2: "\033[102m",
    3: "\033[103m",
    4: "\033[104m",
    5: "\033[105m",
    6: "\033[106m",
    7: "\033[107m",
}

ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
COLOR_TOKEN_PATTERN = re.compile(r"\$\{c([1-8])\}")


def enable_ansi():
    if platform.system() != "Windows":
        return

    try:
        kernel32 = ctypes.windll.kernel32
        stdout_handle = kernel32.GetStdHandle(-11)

        mode = ctypes.c_uint32()

        if kernel32.GetConsoleMode(
            stdout_handle,
            ctypes.byref(mode),
        ):
            kernel32.SetConsoleMode(
                stdout_handle,
                mode.value | 0x0004,
            )
    except Exception:
        pass


def ansi_color(number):
    if str(number).lower() == "fg":
        return ANSI_RESET

    try:
        value = int(number)
    except Exception:
        return ""

    if value in ANSI_FG:
        return ANSI_FG[value]

    if value == 8:
        return ANSI_RESET

    if 0 <= value <= 255:
        return f"\033[38;5;{value}m"

    return ""


def ansi_bold_color(number):
    if str(number).lower() == "fg":
        return ANSI_BOLD

    try:
        value = int(number)
    except Exception:
        return ANSI_BOLD

    if 0 <= value <= 7:
        return f"\033[1;3{value}m"

    if 0 <= value <= 255:
        return f"\033[1;38;5;{value}m"

    return ANSI_BOLD


def info_label_number(palette):
    primary = palette[0] if palette else 7
    secondary = palette[1] if len(palette) > 1 else 7

    if secondary == 7:
        return primary

    return secondary


def visible_text(value):
    value = COLOR_TOKEN_PATTERN.sub("", value)
    value = ANSI_PATTERN.sub("", value)
    return value


def visible_width(value):
    return len(visible_text(value))


def pad_visible(value, width):
    missing = max(0, width - visible_width(value))
    return value + (" " * missing)


def normalize_alias_candidates(snapshot):
    candidates = []
    seen = set()

    def add(value):
        if value is None:
            return

        value = compact_spaces(str(value))

        if not value:
            return

        key = value.lower()

        if key in seen:
            return

        seen.add(key)
        candidates.append(value)

    provider = snapshot.get("provider")
    os_name = snapshot.get("os")
    distro_id = snapshot.get("distro_id")

    if provider == "Windows":
        add(os_name)

        if os_name:
            if os_name.startswith("Windows 11"):
                add("Windows 11")
                add("Windows_11")

            if os_name.startswith("Windows 10"):
                add("Windows 10")
                add("Windows_10")

        add("Windows")

    elif provider == "Linux":
        add(os_name)
        add(distro_id)

        if os_name:
            add(re.sub(r"\s+\d[\w.\- ]*$", "", os_name).strip())
            add(os_name.split()[0])

    elif provider == "macOS":
        add("macOS")
        add("Darwin")
        add(os_name)

    return candidates


def database_lookup_by_alias(
    connection,
    alias,
    prefer_small=False,
):
    preferred = (
        "small"
        if prefer_small
        else "default"
    )

    secondary = (
        "default"
        if prefer_small
        else "small"
    )

    return connection.execute(
        """
        SELECT
            artwork.id,
            artwork.name,
            artwork.family,
            artwork.variant,
            artwork.colors_json,
            artwork.art
        FROM aliases
        JOIN artwork
            ON aliases.artwork_id = artwork.id
        WHERE aliases.alias = ?
          AND lower(artwork.variant) != 'old'
        ORDER BY
            CASE
                WHEN lower(artwork.variant) = ? THEN 0
                WHEN lower(artwork.variant) = ? THEN 1
                ELSE 2
            END,
            artwork.id
        LIMIT 1
        """,
        (
            alias,
            preferred,
            secondary,
        ),
    ).fetchone()


def database_lookup_default(
    connection,
    family,
    prefer_small=False,
):
    if prefer_small:
        preferred_ids = {
            "Windows": [
                "Windows_11_Small",
                "Windows_10_Small",
                "Windows_Small",
                "Windows_11",
                "Windows_10",
                "Windows",
            ],
            "Linux": [],
            "macOS": [
                "macOS_Small",
                "Darwin_Small",
                "macOS",
                "Darwin",
            ],
        }
    else:
        preferred_ids = {
            "Windows": [
                "Windows_11",
                "Windows_10",
                "Windows",
            ],
            "Linux": [],
            "macOS": [
                "macOS",
                "Darwin",
            ],
        }

    for preferred_id in (
        preferred_ids.get(
            family,
            [],
        )
    ):
        row = connection.execute(
            """
            SELECT
                id,
                name,
                family,
                variant,
                colors_json,
                art
            FROM artwork
            WHERE id = ?
              AND lower(variant) != 'old'
            LIMIT 1
            """,
            (preferred_id,),
        ).fetchone()

        if row:
            return row

    preferred = (
        "small"
        if prefer_small
        else "default"
    )

    secondary = (
        "default"
        if prefer_small
        else "small"
    )

    return connection.execute(
        """
        SELECT
            id,
            name,
            family,
            variant,
            colors_json,
            art
        FROM artwork
        WHERE family = ?
          AND lower(variant) != 'old'
        ORDER BY
            CASE
                WHEN lower(variant) = ? THEN 0
                WHEN lower(variant) = ? THEN 1
                ELSE 2
            END,
            id
        LIMIT 1
        """,
        (
            family,
            preferred,
            secondary,
        ),
    ).fetchone()


def resolve_artwork_record(
    snapshot,
    prefer_small=False,
):
    family = (
        snapshot.get("provider")
        or "Unknown"
    )

    database = find_art_database()
    connection = sqlite3.connect(
        database
    )

    try:
        for alias in (
            normalize_alias_candidates(
                snapshot
            )
        ):
            row = database_lookup_by_alias(
                connection,
                alias,
                prefer_small=prefer_small,
            )

            if row:
                return row

        row = database_lookup_default(
            connection,
            family,
            prefer_small=prefer_small,
        )

        if row:
            return row

        raise RuntimeError(
            "No artwork could be resolved "
            "from the PythoFetch art database "
            f"for provider: {family}"
        )

    finally:
        connection.close()


def get_art_payload(
    snapshot,
    prefer_small=False,
):
    record = resolve_artwork_record(
        snapshot,
        prefer_small=prefer_small,
    )

    (
        artwork_id,
        artwork_name,
        family,
        variant,
        colors_json,
        art,
    ) = record

    try:
        raw_palette = (
            json.loads(colors_json)
            if colors_json
            else []
        )
    except Exception:
        raw_palette = []

    palette = []

    for value in raw_palette:
        try:
            palette.append(
                int(value)
            )
        except Exception:
            palette.append(
                value
            )

    return {
        "id": artwork_id,
        "name": artwork_name,
        "family": family,
        "variant": variant,
        "palette": palette,
        "art": art,
    }


def load_logo_lines(snapshot):
    terminal_width = (
        shutil.get_terminal_size(
            (120, 30)
        ).columns
    )

    payload = get_art_payload(
        snapshot,
        prefer_small=(
            terminal_width
            < NARROW_ART_WIDTH
        ),
    )
    palette = payload.get("palette") or [6, 7]
    color_map = {}

    for index in range(1, 9):
        if index <= len(palette):
            color_map[index] = (
                ANSI_BOLD
                + ansi_color(
                    palette[index - 1]
                )
            )
        else:
            color_map[index] = ""

    rendered = []
    active_color = ""

    for raw_line in payload["art"].splitlines():
        output = active_color
        position = 0

        for match in COLOR_TOKEN_PATTERN.finditer(
            raw_line
        ):
            output += raw_line[
                position:match.start()
            ]

            index = int(
                match.group(1)
            )

            active_color = color_map.get(
                index,
                "",
            )

            output += active_color
            position = match.end()

        output += raw_line[position:]

        rendered.append(
            output + ANSI_RESET
        )

    return rendered, palette, payload


def color_blocks():
    normal = "".join(
        ANSI_BG[index] + "   "
        for index in range(8)
    ) + ANSI_RESET

    bright = "".join(
        ANSI_BG_BRIGHT[index] + "   "
        for index in range(8)
    ) + ANSI_RESET

    return normal, bright


def styled_label(label, value, label_number):
    return (
        f"{ansi_bold_color(label_number)}"
        f"{label}:{ANSI_RESET} {value}"
    )


def build_styled_info_lines(snapshot, palette):
    primary_number = palette[0] if palette else 7
    label_number = info_label_number(palette)
    title_color = ansi_color(primary_number)

    user = snapshot.get("user") or "Unknown"
    hostname = snapshot.get("hostname") or "Unknown"

    title_plain = f"{user}@{hostname}"

    lines = [
        (
            f"{ansi_bold_color(label_number)}{user}"
            f"{ANSI_RESET}@"
            f"{ansi_bold_color(label_number)}{hostname}"
            f"{ANSI_RESET}"
        ),
        "-" * len(title_plain),
    ]

    ordered_fields = [
        ("OS", snapshot.get("os")),
        ("Host", snapshot.get("host")),
        ("Kernel", snapshot.get("kernel")),
        ("Uptime", snapshot.get("uptime")),
        ("Packages", snapshot.get("packages")),
        ("Shell", snapshot.get("shell")),
        ("Resolution", snapshot.get("resolution")),
        ("DE", snapshot.get("de")),
        ("WM", snapshot.get("wm")),
        ("WM Theme", snapshot.get("wm_theme")),
        ("Theme", snapshot.get("theme")),
        ("Icons", snapshot.get("icons")),
        ("Terminal", snapshot.get("terminal")),
        ("Terminal Font", snapshot.get("terminal_font")),
        ("CPU", snapshot.get("cpu")),
    ]

    for label, value in ordered_fields:
        if value not in (None, "", [], ()):
            lines.append(
                styled_label(
                    label,
                    value,
                    label_number,
                )
            )

    for gpu in snapshot.get("gpus") or []:
        if gpu:
            lines.append(
                styled_label(
                    "GPU",
                    gpu,
                    label_number,
                )
            )

    used = snapshot.get("memory_used_mib")
    total = snapshot.get("memory_total_mib")

    if used is not None and total is not None:
        lines.append(
            styled_label(
                "Memory",
                f"{used}MiB / {total}MiB",
                label_number,
            )
        )

    normal, bright = color_blocks()

    lines.extend(
        [
            "",
            normal,
            bright,
        ]
    )

    return lines


def render_neofetch_layout(snapshot):
    enable_ansi()

    logo_lines, palette, payload = load_logo_lines(snapshot)
    info_lines = build_styled_info_lines(
        snapshot,
        palette,
    )

    raw_logo_lines = [
        visible_text(line)
        for line in logo_lines
    ]

    logo_width = max(
        (
            len(line)
            for line in raw_logo_lines
        ),
        default=0,
    )

    gap = 3
    total_rows = max(
        len(logo_lines),
        len(info_lines),
    )

    print()

    for row in range(total_rows):
        left = (
            logo_lines[row]
            if row < len(logo_lines)
            else ""
        )

        right = (
            info_lines[row]
            if row < len(info_lines)
            else ""
        )

        if row < len(logo_lines):
            left = pad_visible(
                left,
                logo_width,
            )
        else:
            left = " " * logo_width

        print(
            f"{left}"
            f"{' ' * gap}"
            f"{right}"
            f"{ANSI_RESET}"
        )

    print()


def plain_info_items(snapshot):
    items = [
        ("OS", snapshot.get("os")),
        ("Host", snapshot.get("host")),
        ("Kernel", snapshot.get("kernel")),
        ("Uptime", snapshot.get("uptime")),
        ("Packages", snapshot.get("packages")),
        ("Shell", snapshot.get("shell")),
        ("Resolution", snapshot.get("resolution")),
        ("DE", snapshot.get("de")),
        ("WM", snapshot.get("wm")),
        ("WM Theme", snapshot.get("wm_theme")),
        ("Theme", snapshot.get("theme")),
        ("Icons", snapshot.get("icons")),
        ("Terminal", snapshot.get("terminal")),
        ("Terminal Font", snapshot.get("terminal_font")),
        ("CPU", snapshot.get("cpu")),
    ]

    for gpu in snapshot.get("gpus") or []:
        if gpu:
            items.append(("GPU", gpu))

    used = snapshot.get("memory_used_mib")
    total = snapshot.get("memory_total_mib")

    if used is not None and total is not None:
        items.append(
            (
                "Memory",
                f"{used}MiB / {total}MiB",
            )
        )

    return [
        (label, value)
        for label, value in items
        if value not in (None, "", [], ())
    ]


def clear_terminal():
    enable_ansi()
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def center_visible(value, width):
    size = visible_width(value)

    if size >= width:
        return value

    left = (width - size) // 2
    right = width - size - left

    return (
        (" " * left)
        + value
        + (" " * right)
    )


def fit_visible(value, width):
    if visible_width(value) <= width:
        return value

    plain = visible_text(value)

    if width <= 1:
        return plain[:width]

    return plain[: width - 1] + "…"


def panel_cell(value, width, left_padding=2):
    usable = max(0, width - left_padding - 1)
    value = fit_visible(value, usable)

    return (
        (" " * left_padding)
        + pad_visible(value, usable)
        + " "
    )


def tui_info_lines(snapshot, palette):
    label_number = info_label_number(palette)
    label_color = ansi_bold_color(label_number)
    user = snapshot.get("user") or "Unknown"
    hostname = snapshot.get("hostname") or "Unknown"

    title = (
        f"{label_color}{user}"
        f"{ANSI_RESET}@"
        f"{label_color}{hostname}"
        f"{ANSI_RESET}"
    )

    items = plain_info_items(snapshot)

    lines = [
        title,
        "-" * len(f"{user}@{hostname}"),
        "",
    ]

    for label, value in items:
        lines.append(
            f"{label_color}{label}:"
            f"{ANSI_RESET} {value}"
        )

    normal, bright = color_blocks()

    lines.extend(
        [
            "",
            normal,
            bright,
        ]
    )

    return lines


def border_piece(value, color):
    return color + value + ANSI_RESET


def tui_full_row(value, width, border_color):
    return (
        border_piece("║", border_color)
        + center_visible(value, width)
        + border_piece("║", border_color)
    )


def tui_side_by_side_layout(logo_lines, info_lines):
    logo_width = max(
        (visible_width(line) for line in logo_lines),
        default=0,
    )

    info_width = max(
        (visible_width(line) for line in info_lines),
        default=0,
    )

    left_width = max(
        logo_width + 3,
        30,
    )

    right_width = max(
        info_width + 3,
        44,
    )

    gap = 2
    terminal_width = (
        left_width
        + gap
        + right_width
        + 2
    )

    return (
        left_width,
        right_width,
        gap,
        terminal_width,
    )


def render_tui_side_by_side(snapshot, logo_lines, palette, payload):
    info_lines = tui_info_lines(snapshot, palette)

    (
        left_width,
        right_width,
        gap,
        _,
    ) = tui_side_by_side_layout(
        logo_lines,
        info_lines,
    )

    full_width = left_width + gap + right_width
    label_number = info_label_number(palette)
    border_color = ansi_bold_color(label_number)
    heading_color = ANSI_BOLD

    print(
        border_piece(
            "╔" + ("═" * full_width) + "╗",
            border_color,
        )
    )

    for value in (
        "PROJECT HOMELAB",
        "PRESENTS",
        "PYTHOFETCH",
    ):
        print(
            tui_full_row(
                heading_color
                + value
                + ANSI_RESET,
                full_width,
                border_color,
            )
        )

    print(
        border_piece(
            "╠"
            + ("═" * full_width)
            + "╣",
            border_color,
        )
    )

    content_height = max(
        len(logo_lines),
        len(info_lines),
    )

    logo_offset = max(
        0,
        (content_height - len(logo_lines)) // 2,
    )

    for row in range(content_height):
        logo_index = row - logo_offset

        left = (
            logo_lines[logo_index]
            if 0 <= logo_index < len(logo_lines)
            else ""
        )

        right = (
            info_lines[row]
            if row < len(info_lines)
            else ""
        )

        left_cell = panel_cell(
            left,
            left_width,
        )

        right_cell = panel_cell(
            right,
            right_width,
        )

        print(
            border_piece(
                "║",
                border_color,
            )
            + left_cell
            + (" " * gap)
            + right_cell
            + border_piece(
                "║",
                border_color,
            )
        )

    print(
        border_piece(
            "╠"
            + ("═" * full_width)
            + "╣",
            border_color,
        )
    )

    footer = (
        f"PythoFetch {PYTHOFETCH_VERSION}"
        f"   {snapshot.get('provider')}"
        f" / {payload.get('id')}"
        "   Enter: Exit"
    )

    print(
        tui_full_row(
            footer,
            full_width,
            border_color,
        )
    )

    print(
        border_piece(
            "╚" + ("═" * full_width) + "╝",
            border_color,
        )
    )


def render_tui_stacked(snapshot, logo_lines, palette, payload):
    info_lines = tui_info_lines(snapshot, palette)

    content_width = max(
        62,
        max(
            [visible_width(line) for line in logo_lines]
            + [visible_width(line) for line in info_lines]
            + [0]
        )
        + 4,
    )

    terminal_width = shutil.get_terminal_size(
        (100, 30)
    ).columns

    content_width = min(
        content_width,
        max(
            40,
            terminal_width - 2,
        ),
    )

    label_number = info_label_number(palette)
    border_color = ansi_bold_color(label_number)
    heading_color = ANSI_BOLD

    print(
        border_piece(
            "╔" + ("═" * content_width) + "╗",
            border_color,
        )
    )

    for value in (
        "PROJECT HOMELAB",
        "PRESENTS",
        "PYTHOFETCH",
    ):
        print(
            tui_full_row(
                heading_color
                + value
                + ANSI_RESET,
                content_width,
                border_color,
            )
        )

    print(
        border_piece(
            "╠"
            + ("═" * content_width)
            + "╣",
            border_color,
        )
    )

    for line in logo_lines:
        print(
            border_piece(
                "║",
                border_color,
            )
            + panel_cell(
                line,
                content_width,
            )
            + border_piece(
                "║",
                border_color,
            )
        )

    print(
        border_piece(
            "║",
            border_color,
        )
        + panel_cell(
            "",
            content_width,
        )
        + border_piece(
            "║",
            border_color,
        )
    )

    for line in info_lines:
        print(
            border_piece(
                "║",
                border_color,
            )
            + panel_cell(
                line,
                content_width,
            )
            + border_piece(
                "║",
                border_color,
            )
        )

    print(
        border_piece(
            "╠"
            + ("═" * content_width)
            + "╣",
            border_color,
        )
    )

    footer = (
        f"PythoFetch {PYTHOFETCH_VERSION}"
        f"   {snapshot.get('provider')}"
        f" / {payload.get('id')}"
        "   Enter: Exit"
    )

    print(
        tui_full_row(
            footer,
            content_width,
            border_color,
        )
    )

    print(
        border_piece(
            "╚" + ("═" * content_width) + "╝",
            border_color,
        )
    )


def render_tui(snapshot):
    enable_ansi()

    logo_lines, palette, payload = load_logo_lines(
        snapshot
    )

    info_lines = tui_info_lines(
        snapshot,
        palette,
    )

    (
        _,
        _,
        _,
        required_width,
    ) = tui_side_by_side_layout(
        logo_lines,
        info_lines,
    )

    terminal_width = shutil.get_terminal_size(
        (120, 30)
    ).columns

    clear_terminal()

    if terminal_width >= required_width:
        render_tui_side_by_side(
            snapshot,
            logo_lines,
            palette,
            payload,
        )
    else:
        render_tui_stacked(
            snapshot,
            logo_lines,
            palette,
            payload,
        )


def emit_json(value):
    sys.stdout.write(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )

    sys.stdout.flush()


def emit_info_text(snapshot):
    for label, value in plain_info_items(snapshot):
        sys.stdout.write(
            f"{label}: {value}\n"
        )


def emit_art_text(payload):
    art = payload.get("art", "")
    sys.stdout.write(art)

    if not art.endswith("\n"):
        sys.stdout.write("\n")


def run_headless(args):
    snapshot = collect_system_snapshot()

    mode = "all"

    if args.info:
        mode = "info"
    elif args.art:
        mode = "art"
    elif args.all:
        mode = "all"

    if mode == "info":
        payload = snapshot
    elif mode == "art":
        payload = get_art_payload(
            snapshot
        )
    else:
        payload = {
            "info": snapshot,
            "art": get_art_payload(
                snapshot
            ),
        }

    if args.format == "json":
        emit_json(payload)
        return 0

    if mode == "info":
        emit_info_text(snapshot)
        return 0

    if mode == "art":
        emit_art_text(payload)
        return 0

    emit_info_text(snapshot)
    sys.stdout.write("\n")
    emit_art_text(payload["art"])
    return 0


def run_classic():
    snapshot = collect_system_snapshot()
    render_neofetch_layout(snapshot)
    return 0


def run_tui():
    snapshot = collect_system_snapshot()
    render_tui(snapshot)

    try:
        input()
    except EOFError:
        pass

    return 0


def normalized_platform_name():
    system = platform.system()

    if system == "Windows":
        return "Windows"

    if system == "Linux":
        return "Linux"

    if system == "Darwin":
        return "macOS"

    raise RuntimeError(
        "Unsupported update platform: "
        f"{system}"
    )


def normalized_architecture():
    machine = str(
        platform.machine() or ""
    ).strip().lower()

    if machine in (
        "x86_64",
        "amd64",
        "x64",
    ):
        return "x86_64"

    if machine in (
        "arm64",
        "aarch64",
    ):
        return "arm64"

    if machine in (
        "universal",
        "universal2",
    ):
        return "Universal"

    return machine or "Unknown"


def release_asset_candidates():
    system = normalized_platform_name()
    architecture = normalized_architecture()

    candidates = []

    if architecture != "Unknown":
        candidates.append(
            f"{system}_{architecture}"
        )

    candidates.append(
        f"{system}_Universal"
    )

    candidates.append(
        "Universal"
    )

    return candidates


def select_release_asset(release):
    assets = (
        release.get("assets")
        or release.get("platforms")
    )

    if not isinstance(assets, dict):
        raise RuntimeError(
            "Release manifest entry does "
            "not contain an assets object."
        )

    lookup = {
        str(key).casefold(): (
            str(key),
            value,
        )
        for key, value in assets.items()
    }

    for candidate in (
        release_asset_candidates()
    ):
        selected = lookup.get(
            candidate.casefold()
        )

        if selected:
            key, asset = selected

            if not isinstance(
                asset,
                dict,
            ):
                raise RuntimeError(
                    "Selected release asset "
                    "is malformed."
                )

            return key, asset

    raise RuntimeError(
        "No release asset is available "
        "for this system. Tried: "
        + ", ".join(
            release_asset_candidates()
        )
    )


def powershell_literal(value):
    return (
        "'"
        + str(value).replace(
            "'",
            "''",
        )
        + "'"
    )


def runtime_application_path():
    system = platform.system()

    if system == "Linux":
        appimage_value = str(
            os.environ.get("APPIMAGE")
            or ""
        ).strip()

        if appimage_value:
            appimage_path = Path(
                appimage_value
            ).expanduser().resolve()

            if appimage_path.is_file():
                return appimage_path

    executable = Path(
        sys.executable
    ).resolve()

    if system == "Darwin":
        candidates = (
            executable,
            *executable.parents,
        )

        for candidate in candidates:
            if (
                candidate.name.lower().endswith(
                    ".app"
                )
                and candidate.is_dir()
            ):
                return candidate

    return executable


def runtime_application_kind(
    target=None,
):
    target = Path(
        target
        or runtime_application_path()
    )

    if (
        platform.system() == "Linux"
        and target.is_file()
        and target.name.lower().endswith(
            ".appimage"
        )
    ):
        return "appimage"

    if (
        platform.system() == "Darwin"
        and target.is_dir()
        and target.name.lower().endswith(
            ".app"
        )
    ):
        return "app_bundle"

    return "executable"


def release_executable_name(
    latest,
    asset,
    target=None,
):
    configured = str(
        asset.get("executable")
        or ""
    ).strip()

    if configured:
        normalized = configured.replace(
            "\\",
            "/",
        )

        if "/" in normalized:
            raise RuntimeError(
                "Release manifest executable "
                "must be a filename, not a path."
            )

        return normalized

    kind = runtime_application_kind(
        target
    )

    if platform.system() == "Windows":
        return (
            f"PythoFetch_{latest}.exe"
        )

    if kind == "appimage":
        return (
            f"PythoFetch_{latest}_Linux_"
            f"{normalized_architecture()}.AppImage"
        )

    if kind == "app_bundle":
        return f"PythoFetch_{latest}.app"

    return f"PythoFetch_{latest}"


def remove_update_path(path):
    path = Path(path)

    if path.is_symlink() or path.is_file():
        path.unlink()
        return

    if path.is_dir():
        shutil.rmtree(path)


def normalized_zip_member_name(value):
    normalized = str(value).replace(
        "\\",
        "/",
    )

    while normalized.startswith("./"):
        normalized = normalized[2:]

    if (
        not normalized
        or normalized.startswith("/")
        or "\x00" in normalized
    ):
        raise RuntimeError(
            "Release archive contains an "
            "invalid member path."
        )

    parts = [
        part
        for part in normalized.split("/")
        if part not in ("", ".")
    ]

    if (
        not parts
        or any(
            part == ".."
            for part in parts
        )
        or (
            len(parts[0]) >= 2
            and parts[0][1] == ":"
        )
    ):
        raise RuntimeError(
            "Release archive contains an "
            "unsafe member path."
        )

    return "/".join(parts)


def verify_update_payload(
    path,
    expected_sha256=None,
    expected_size=None,
):
    path = Path(path)

    if (
        not path.is_file()
        or path.stat().st_size == 0
    ):
        raise RuntimeError(
            "Extracted update application "
            "is missing or empty."
        )

    if expected_size is not None:
        try:
            required_size = int(
                expected_size
            )
        except Exception as exc:
            raise RuntimeError(
                "Manifest contains an invalid "
                "update application size."
            ) from exc

        if (
            path.stat().st_size
            != required_size
        ):
            raise RuntimeError(
                "Extracted update application "
                "size does not match the "
                "manifest."
            )

    expected_hash = str(
        expected_sha256 or ""
    ).strip().lower()

    if expected_hash:
        actual_hash = sha256_file(
            path
        ).lower()

        if actual_hash != expected_hash:
            raise RuntimeError(
                "Extracted update application "
                "failed SHA-256 verification."
            )

    return path


def extract_zip_update(
    archive_path,
    executable_name,
    destination,
    asset,
):
    archive_path = Path(
        archive_path
    )
    destination = Path(
        destination
    )

    remove_update_path(
        destination
    )

    try:
        with zipfile.ZipFile(
            archive_path,
            "r",
        ) as archive:
            candidates = []

            for info in archive.infolist():
                member_path = (
                    normalized_zip_member_name(
                        info.filename
                    )
                )

                if info.is_dir():
                    continue

                member_name = (
                    member_path.rsplit(
                        "/",
                        1,
                    )[-1]
                )

                if (
                    member_name.casefold()
                    == executable_name.casefold()
                ):
                    candidates.append(
                        info
                    )

            if len(candidates) != 1:
                raise RuntimeError(
                    "Release archive must contain "
                    "exactly one expected PythoFetch "
                    "application file."
                )

            selected = candidates[0]

            with archive.open(
                selected,
                "r",
            ) as source:
                with destination.open(
                    "wb"
                ) as target_handle:
                    shutil.copyfileobj(
                        source,
                        target_handle,
                    )

        verify_update_payload(
            destination,
            asset.get(
                "executable_sha256"
            ),
            asset.get(
                "executable_size_bytes"
            ),
        )

        return destination

    except Exception:
        remove_update_path(
            destination
        )
        raise

    finally:
        remove_update_path(
            archive_path
        )


def validate_macos_bundle(path):
    path = Path(path)

    if (
        not path.is_dir()
        or not path.name.lower().endswith(
            ".app"
        )
    ):
        raise RuntimeError(
            "Extracted macOS application "
            "bundle is missing."
        )

    contents = path / "Contents"
    info_plist = contents / "Info.plist"
    macos_dir = contents / "MacOS"

    if (
        not info_plist.is_file()
        or not macos_dir.is_dir()
    ):
        raise RuntimeError(
            "Extracted macOS application "
            "bundle is malformed."
        )

    launchers = [
        child
        for child in macos_dir.iterdir()
        if (
            child.is_file()
            and os.access(
                child,
                os.X_OK,
            )
        )
    ]

    if not launchers:
        raise RuntimeError(
            "Extracted macOS application "
            "bundle has no executable launcher."
        )

    return path


def extract_macos_bundle_update(
    archive_path,
    application_name,
    destination,
):
    archive_path = Path(
        archive_path
    )
    destination = Path(
        destination
    )
    staging = destination.with_name(
        destination.name + ".extract"
    )

    remove_update_path(
        destination
    )
    remove_update_path(
        staging
    )

    try:
        with zipfile.ZipFile(
            archive_path,
            "r",
        ) as archive:
            expected = (
                application_name.casefold()
            )
            found_expected = False
            application_roots = set()

            for info in archive.infolist():
                member_path = (
                    normalized_zip_member_name(
                        info.filename
                    )
                )
                root = member_path.split(
                    "/",
                    1,
                )[0]
                root_folded = root.casefold()

                if root_folded == "__macosx":
                    continue

                if root_folded.endswith(
                    ".app"
                ):
                    application_roots.add(
                        root_folded
                    )

                if root_folded == expected:
                    found_expected = True

            if (
                not found_expected
                or application_roots
                != {expected}
            ):
                raise RuntimeError(
                    "Release archive must contain "
                    "exactly one expected PythoFetch "
                    "macOS application bundle."
                )

        staging.mkdir(
            parents=True,
            exist_ok=False,
        )

        result = subprocess.run(
            [
                "ditto",
                "-x",
                "-k",
                str(archive_path),
                str(staging),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            raise RuntimeError(
                "macOS could not extract the "
                "application update."
            )

        extracted = staging / application_name

        validate_macos_bundle(
            extracted
        )

        shutil.move(
            str(extracted),
            str(destination),
        )

        validate_macos_bundle(
            destination
        )

        return destination

    except Exception:
        remove_update_path(
            destination
        )
        raise

    finally:
        remove_update_path(
            staging
        )
        remove_update_path(
            archive_path
        )


def prepare_update_payload(
    downloaded,
    filename,
    latest,
    asset,
    target,
):
    filename = str(
        filename
    ).strip()

    executable_name = (
        release_executable_name(
            latest,
            asset,
            target,
        )
    )

    lower_name = filename.lower()

    if lower_name.endswith(".zip"):
        is_macos_bundle = (
            platform.system() == "Darwin"
            and executable_name.lower().endswith(
                ".app"
            )
        )

        if is_macos_bundle:
            destination = target.with_name(
                ".update-"
                + executable_name
            )
            payload = (
                extract_macos_bundle_update(
                    downloaded,
                    executable_name,
                    destination,
                )
            )
        else:
            destination = (
                target.with_name(
                    "."
                    + executable_name
                    + ".update"
                )
            )
            payload = extract_zip_update(
                downloaded,
                executable_name,
                destination,
                asset,
            )

        return (
            payload,
            executable_name,
        )

    if lower_name.endswith(
        (
            ".tar",
            ".tar.gz",
            ".tgz",
        )
    ):
        remove_update_path(
            downloaded
        )

        raise RuntimeError(
            "This PythoFetch version supports "
            "ZIP release archives or direct "
            "application files, not TAR archives."
        )

    if executable_name.lower().endswith(
        ".app"
    ):
        remove_update_path(
            downloaded
        )

        raise RuntimeError(
            "macOS application bundles must be "
            "distributed inside a ZIP archive."
        )

    verify_update_payload(
        downloaded
    )

    return (
        Path(downloaded),
        executable_name,
    )


def schedule_windows_update(
    downloaded,
    target,
    destination,
):
    script_path = target.with_name(
        "." + target.name + ".update.ps1"
    )

    target_literal = powershell_literal(
        target
    )

    destination_literal = (
        powershell_literal(
            destination
        )
    )

    script_lines = [
        (
            "$targetPid = "
            f"{os.getpid()}"
        ),
        (
            "while (Get-Process -Id "
            "$targetPid -ErrorAction "
            "SilentlyContinue) {"
        ),
        (
            "    Start-Sleep "
            "-Milliseconds 250"
        ),
        "}",
        (
            "Move-Item -LiteralPath "
            f"{powershell_literal(downloaded)} "
            "-Destination "
            f"{destination_literal} "
            "-Force"
        ),
    ]

    if (
        os.path.normcase(
            str(target)
        )
        != os.path.normcase(
            str(destination)
        )
    ):
        script_lines.append(
            (
                "Remove-Item -LiteralPath "
                f"{target_literal} "
                "-Force -ErrorAction "
                "SilentlyContinue"
            )
        )

    script_lines.extend(
        [
            (
                "Start-Process -FilePath "
                f"{destination_literal}"
            ),
            (
                "Remove-Item -LiteralPath "
                "$MyInvocation.MyCommand.Path "
                "-Force"
            ),
        ]
    )

    script = "\n".join(
        script_lines
    )

    script_path.write_text(
        script + "\n",
        encoding="utf-8",
    )

    creation_flags = (
        getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0,
        )
        | getattr(
            subprocess,
            "DETACHED_PROCESS",
            0,
        )
        | getattr(
            subprocess,
            "CREATE_NO_WINDOW",
            0,
        )
    )

    subprocess.Popen(
        [
            "powershell",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )


def schedule_unix_update(
    downloaded,
    target,
    destination,
):
    script_path = target.with_name(
        "." + target.name + ".update.sh"
    )

    downloaded_q = shlex.quote(
        str(downloaded)
    )

    target_q = shlex.quote(
        str(target)
    )

    destination_q = shlex.quote(
        str(destination)
    )

    script_q = shlex.quote(
        str(script_path)
    )

    script_lines = [
        f"pid={os.getpid()}",
        (
            'while kill -0 "$pid" '
            "2>/dev/null; do"
        ),
        "    sleep 0.25",
        "done",
        (
            f"mv -f {downloaded_q} "
            f"{destination_q}"
        ),
        f"chmod +x {destination_q}",
    ]

    if (
        os.path.normcase(
            str(target)
        )
        != os.path.normcase(
            str(destination)
        )
    ):
        script_lines.append(
            f"rm -f -- {target_q}"
        )

    script_lines.extend(
        [
            (
                f"{destination_q} "
                ">/dev/null 2>&1 &"
            ),
            (
                f"rm -f -- {script_q}"
            ),
        ]
    )

    script = "\n".join(
        script_lines
    )

    script_path.write_text(
        script + "\n",
        encoding="utf-8",
    )

    subprocess.Popen(
        [
            "/bin/sh",
            str(script_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def schedule_macos_update(
    downloaded,
    target,
    destination,
):
    script_path = target.with_name(
        "." + target.name + ".update.sh"
    )

    downloaded_q = shlex.quote(
        str(downloaded)
    )

    target_q = shlex.quote(
        str(target)
    )

    destination_q = shlex.quote(
        str(destination)
    )

    script_q = shlex.quote(
        str(script_path)
    )

    script_lines = [
        f"pid={os.getpid()}",
        (
            'while kill -0 "$pid" '
            "2>/dev/null; do"
        ),
        "    sleep 0.25",
        "done",
        (
            f"rm -rf -- {destination_q}"
        ),
        (
            f"mv -f {downloaded_q} "
            f"{destination_q}"
        ),
    ]

    if (
        os.path.normcase(
            str(target)
        )
        != os.path.normcase(
            str(destination)
        )
    ):
        script_lines.append(
            f"rm -rf -- {target_q}"
        )

    script_lines.extend(
        [
            (
                f"open {destination_q} "
                ">/dev/null 2>&1"
            ),
            (
                f"rm -f -- {script_q}"
            ),
        ]
    )

    script = "\n".join(
        script_lines
    )

    script_path.write_text(
        script + "\n",
        encoding="utf-8",
    )

    subprocess.Popen(
        [
            "/bin/sh",
            str(script_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def schedule_self_update(
    downloaded,
    executable_name,
):
    target = runtime_application_path()

    destination = target.with_name(
        executable_name
    )

    kind = runtime_application_kind(
        target
    )

    if platform.system() == "Windows":
        schedule_windows_update(
            downloaded,
            target,
            destination,
        )
    elif kind == "app_bundle":
        schedule_macos_update(
            downloaded,
            target,
            destination,
        )
    else:
        schedule_unix_update(
            downloaded,
            target,
            destination,
        )


def run_update():
    print(
        "Checking for PythoFetch updates..."
    )

    manifest = fetch_json(
        RELEASE_MANIFEST_URL
    )

    latest = manifest.get(
        "latest_version"
    )

    if not latest:
        print(
            "No published PythoFetch "
            "release is available yet."
        )
        return 0

    latest = str(latest).strip()

    releases = manifest.get(
        "releases"
    )

    if not isinstance(releases, dict):
        raise RuntimeError(
            "Release manifest contains an "
            "invalid releases object."
        )

    current_key = version_key(
        PYTHOFETCH_VERSION
    )

    latest_key = version_key(
        latest
    )

    if latest_key == current_key:
        print(
            f"PythoFetch {PYTHOFETCH_VERSION} "
            "is already the latest release."
        )
        return 0

    if latest_key < current_key:
        print(
            f"PythoFetch {PYTHOFETCH_VERSION} "
            "is newer than the published "
            f"release {latest}."
        )
        return 0

    release = releases.get(
        latest
    )

    if not isinstance(release, dict):
        raise RuntimeError(
            "Latest release is not present "
            "in the release manifest."
        )

    print(
        f"PythoFetch {latest} is available."
    )

    if not getattr(
        sys,
        "frozen",
        False,
    ):
        print(
            "Source checkout detected. "
            "Automatic binary replacement "
            "is only used by packaged "
            "PythoFetch releases."
        )
        return 0

    asset_key, asset = (
        select_release_asset(
            release
        )
    )

    download_url = str(
        asset.get(
            "download_url"
        )
        or ""
    ).strip()

    if not download_url:
        raise RuntimeError(
            "Selected release asset does "
            "not provide a download URL."
        )

    filename = str(
        asset.get("file")
        or Path(
            download_url.split(
                "?",
                1,
            )[0]
        ).name
        or "PythoFetch.update"
    )

    release_filename = (
        filename.replace(
            "\\",
            "/",
        ).rsplit(
            "/",
            1,
        )[-1]
    )

    if not release_filename:
        raise RuntimeError(
            "Selected release asset does "
            "not provide a valid filename."
        )

    target = runtime_application_path()

    downloaded = target.with_name(
        "."
        + release_filename
        + ".update"
    )

    if downloaded.exists():
        downloaded.unlink()

    print(
        f"Downloading {asset_key}..."
    )

    download_verified_file(
        download_url,
        downloaded,
        asset.get("sha256"),
        asset.get("size_bytes"),
    )

    (
        payload,
        executable_name,
    ) = prepare_update_payload(
        downloaded,
        release_filename,
        latest,
        asset,
        target,
    )

    schedule_self_update(
        payload,
        executable_name,
    )

    print(
        "Update downloaded and verified."
    )
    print(
        "PythoFetch will restart with "
        f"version {latest}."
    )

    return 0


def build_argument_parser():
    parser = argparse.ArgumentParser(
        prog="PythoFetch",
        add_help=True,
    )

    parser.add_argument(
        "--classic",
        action="store_true",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
    )

    parser.add_argument(
        "--update",
        action="store_true",
    )

    selector = (
        parser.add_mutually_exclusive_group()
    )

    selector.add_argument(
        "--info",
        action="store_true",
    )

    selector.add_argument(
        "--art",
        action="store_true",
    )

    selector.add_argument(
        "--all",
        action="store_true",
    )

    parser.add_argument(
        "--format",
        choices=(
            "json",
            "text",
        ),
        default="json",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=(
            f"PythoFetch "
            f"{PYTHOFETCH_VERSION}"
        ),
    )

    return parser


def validate_arguments(
    parser,
    args,
):
    if args.classic and args.headless:
        parser.error(
            "--classic and --headless "
            "cannot be used together."
        )

    if (
        args.update
        and (
            args.classic
            or args.headless
            or args.info
            or args.art
            or args.all
        )
    ):
        parser.error(
            "--update cannot be combined "
            "with display or headless modes."
        )

    if (
        (
            args.info
            or args.art
            or args.all
        )
        and not args.headless
    ):
        parser.error(
            "--info, --art and --all "
            "require --headless."
        )

    if (
        args.format != "json"
        and not args.headless
    ):
        parser.error(
            "--format is only used with "
            "--headless."
        )


def emit_runtime_error(
    args,
    exc,
):
    message = (
        f"PythoFetch error: {exc}"
    )

    if args.headless:
        sys.stderr.write(
            message + "\n"
        )
        sys.stderr.flush()
        return

    print()
    print(message)

    if (
        not args.classic
        and not args.update
        and sys.stdin.isatty()
    ):
        try:
            input(
                "Press Enter to exit..."
            )
        except EOFError:
            pass


def main():
    parser = build_argument_parser()
    args = parser.parse_args()
    validate_arguments(
        parser,
        args,
    )

    try:
        if args.update:
            return run_update()

        if args.headless:
            return run_headless(args)

        if args.classic:
            return run_classic()

        return run_tui()

    except KeyboardInterrupt:
        if args.headless:
            sys.stderr.write(
                "PythoFetch cancelled.\n"
            )
            sys.stderr.flush()
        else:
            print()
            print(
                "PythoFetch cancelled."
            )

        return 130

    except Exception as exc:
        emit_runtime_error(
            args,
            exc,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
