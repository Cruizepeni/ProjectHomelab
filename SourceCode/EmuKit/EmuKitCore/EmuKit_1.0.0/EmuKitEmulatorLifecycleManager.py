from __future__ import annotations

import csv
import io
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class EmuKitEmulatorLifecycleManager:

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self._known_pids: dict[str, set[int]] = {}

    def remember_launch(self, module_id: str, pid: int | None) -> None:
        if isinstance(pid, int) and pid > 0:
            self._known_pids.setdefault(module_id, set()).add(pid)

    def forget_module(self, module_id: str) -> None:
        self._known_pids.pop(module_id, None)

    def _resolve_project_path(self, configured_path: str) -> Path:
        path = Path(configured_path)
        if path.is_absolute():
            return path.resolve()
        return (self.project_root / path).resolve()

    def _process_name(self, module_info: dict[str, Any]) -> str:
        lifecycle = module_info.get("Lifecycle")
        if isinstance(lifecycle, dict):
            value = lifecycle.get("ProcessName")
            if isinstance(value, str) and value.strip():
                return Path(value.strip()).name
        launch_path = module_info.get("LaunchPath")
        if isinstance(launch_path, str) and launch_path.strip():
            return Path(launch_path).name
        return ""

    def _expected_executable(self, module_info: dict[str, Any]) -> Path | None:
        launch_path = module_info.get("LaunchPath")
        if not isinstance(launch_path, str) or not launch_path.strip():
            return None
        return self._resolve_project_path(launch_path)

    @staticmethod
    def _same_path(left: str | Path | None, right: str | Path | None) -> bool:
        if left is None or right is None:
            return False
        try:
            a = os.path.normcase(os.path.abspath(str(left)))
            b = os.path.normcase(os.path.abspath(str(right)))
            return a == b
        except Exception:
            return False

    def _windows_processes(self) -> list[dict[str, Any]]:
        powershell = shutil_which("powershell.exe") or shutil_which("powershell")
        if powershell:
            script = (
                "Get-CimInstance Win32_Process | "
                "Select-Object ProcessId,Name,ExecutablePath | ConvertTo-Csv -NoTypeInformation"
            )
            try:
                completed = subprocess.run(
                    [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                    capture_output=True,
                    text=True,
                    timeout=12,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if completed.returncode == 0:
                    rows = csv.DictReader(io.StringIO(completed.stdout))
                    result = []
                    for row in rows:
                        try:
                            pid = int(row.get("ProcessId") or 0)
                        except ValueError:
                            continue
                        result.append({
                            "pid": pid,
                            "name": row.get("Name") or "",
                            "path": row.get("ExecutablePath") or None,
                        })
                    return result
            except Exception:
                pass

        try:
            completed = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            result = []
            for row in csv.reader(io.StringIO(completed.stdout)):
                if len(row) < 2:
                    continue
                try:
                    pid = int(row[1])
                except ValueError:
                    continue
                result.append({"pid": pid, "name": row[0], "path": None})
            return result
        except Exception:
            return []

    @staticmethod
    def _linux_processes() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        proc = Path("/proc")
        if not proc.is_dir():
            return result
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                pid = int(entry.name)
                exe = (entry / "exe").resolve()
                name = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip()
                result.append({"pid": pid, "name": name or exe.name, "path": str(exe)})
            except (OSError, ValueError):
                continue
        return result

    @staticmethod
    def _posix_ps_processes() -> list[dict[str, Any]]:
        try:
            completed = subprocess.run(
                ["ps", "-axo", "pid=,comm="],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return []
        result = []
        for line in completed.stdout.splitlines():
            value = line.strip()
            if not value:
                continue
            parts = value.split(None, 1)
            if len(parts) != 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            path = parts[1]
            result.append({"pid": pid, "name": Path(path).name, "path": path})
        return result

    def _processes(self) -> list[dict[str, Any]]:
        if os.name == "nt":
            return self._windows_processes()
        if sys.platform.startswith("linux"):
            return self._linux_processes()
        return self._posix_ps_processes()

    def matching_processes(self, module_id: str, module_info: dict[str, Any]) -> list[dict[str, Any]]:
        expected = self._expected_executable(module_info)
        process_name = self._process_name(module_info).casefold()
        processes = self._processes()

        exact = [
            item for item in processes
            if expected is not None and self._same_path(item.get("path"), expected)
        ]
        if exact:
            matches = exact
        else:
            matches = [
                item for item in processes
                if process_name and str(item.get("name") or "").casefold() == process_name
            ]

        known = self._known_pids.get(module_id, set())
        return sorted(matches, key=lambda item: (item.get("pid") not in known, item.get("pid", 0)))

    def is_running(self, module_id: str, module_info: dict[str, Any]) -> dict[str, Any]:
        matches = self.matching_processes(module_id, module_info)
        return {
            "success": True,
            "module": module_id,
            "operation": "is_running",
            "state": "running" if matches else "not_running",
            "message": (
                f'Emulator "{module_info.get("Name", module_id)}" is running.'
                if matches else
                f'Emulator "{module_info.get("Name", module_id)}" is not running.'
            ),
            "details": {"running": bool(matches), "processes": matches},
        }

    def close(self, module_id: str, module_info: dict[str, Any], *, timeout: float = 5.0) -> dict[str, Any]:
        matches = self.matching_processes(module_id, module_info)
        if not matches:
            return {
                "success": True,
                "module": module_id,
                "operation": "close_emulator",
                "state": "not_running",
                "message": f'Emulator "{module_info.get("Name", module_id)}" is not currently running.',
                "details": {"closed": []},
            }

        pids = sorted({int(item["pid"]) for item in matches if int(item.get("pid", 0)) > 0})
        closed: list[int] = []
        errors: list[dict[str, Any]] = []

        if os.name == "nt":
            for pid in pids:
                try:
                    completed = subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T"],
                        capture_output=True,
                        text=True,
                        timeout=max(2.0, timeout),
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if completed.returncode == 0:
                        closed.append(pid)
                    else:
                        forced = subprocess.run(
                            ["taskkill", "/PID", str(pid), "/T", "/F"],
                            capture_output=True,
                            text=True,
                            timeout=max(2.0, timeout),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        if forced.returncode == 0:
                            closed.append(pid)
                        else:
                            errors.append({"pid": pid, "error": forced.stderr.strip() or forced.stdout.strip()})
                except Exception as exc:
                    errors.append({"pid": pid, "error": str(exc)})
        else:
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                    closed.append(pid)
                except ProcessLookupError:
                    closed.append(pid)
                except Exception as exc:
                    errors.append({"pid": pid, "error": str(exc)})
            if closed:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    remaining = {item["pid"] for item in self.matching_processes(module_id, module_info)}
                    if not remaining.intersection(closed):
                        break
                    time.sleep(0.1)
                for pid in list(closed):
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        continue
                    except Exception:
                        continue
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except Exception:
                        pass

        self._known_pids.pop(module_id, None)
        success = not errors
        return {
            "success": success,
            "module": module_id,
            "operation": "close_emulator",
            "state": "closed" if success else "closed_with_errors",
            "message": (
                f'Closed emulator "{module_info.get("Name", module_id)}".'
                if success else
                f'Emulator "{module_info.get("Name", module_id)}" was closed with one or more errors.'
            ),
            "details": {"closed": closed, "errors": errors},
        }


def shutil_which(command: str) -> str | None:
    path = os.environ.get("PATH", "")
    pathext = os.environ.get("PATHEXT", ".EXE;.BAT;.CMD;.COM").split(os.pathsep)
    candidates = [command]
    if os.name == "nt" and not Path(command).suffix:
        candidates.extend(command + ext for ext in pathext if ext)
    for directory in path.split(os.pathsep):
        directory = directory.strip('"')
        if not directory:
            continue
        for candidate in candidates:
            value = Path(directory) / candidate
            if value.is_file():
                return str(value)
    return None
