from __future__ import annotations

import os
import subprocess
import time

try:
	import psutil
except ImportError:
	psutil = None


SERVICES = (
	"ArmouryCrateService",
	"ROG Live Service",
)

_ARMOURY_PROCESS_FAMILIES = (
	"armourycrate",
	"armourysocketserver",
	"armouryswagent",
	"rogliveservice",
)

STOP_TIMEOUT_SECONDS = 5.0


def _run_quiet(command: list[str]) -> int:
	try:
		completed = subprocess.run(
			command,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
			check=False,
			creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
		)
		return int(completed.returncode)
	except Exception:
		return -1


def _matching_processes():
	if psutil is None:
		return []
	matches = []
	try:
		for process in psutil.process_iter(["pid", "name"]):
			name = str(process.info.get("name") or "").strip()
			lower = name.lower()
			if lower and any(family in lower for family in _ARMOURY_PROCESS_FAMILIES):
				matches.append(process)
	except Exception:
		pass
	return matches


def detect_armoury_crate() -> dict:
	if os.name != "nt":
		return {"active": False, "available": False, "reason": "unsupported_platform", "processes": []}
	if psutil is None:
		return {"active": False, "available": False, "reason": "psutil_unavailable", "processes": []}
	processes = []
	for process in _matching_processes():
		try:
			processes.append(str(process.info.get("name") or process.pid))
		except Exception:
			pass
	return {"active": bool(processes), "available": True, "processes": sorted(set(processes))}


def turn_off_armoury_crate() -> bool:
	if os.name != "nt":
		print("Turn Off Armoury Crate is only supported on Windows.")
		return False
	if psutil is None:
		print("Unable to turn off Armoury Crate: psutil is unavailable.")
		return False
	print("Turning off Armoury Crate...")
	for service_name in SERVICES:
		_run_quiet(["sc.exe", "stop", service_name])
	processes = _matching_processes()
	for process in processes:
		try:
			process.terminate()
		except (psutil.NoSuchProcess, psutil.AccessDenied):
			pass
	_, alive = psutil.wait_procs(processes, timeout=2.0)
	for process in alive:
		try:
			process.kill()
		except (psutil.NoSuchProcess, psutil.AccessDenied):
			pass
	deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
	while time.monotonic() < deadline:
		remaining = _matching_processes()
		if not remaining:
			print("Armoury Crate is off.")
			return True
		for process in remaining:
			try:
				process.kill()
			except (psutil.NoSuchProcess, psutil.AccessDenied):
				pass
		time.sleep(0.25)
	remaining_names = sorted({
		str(process.info.get("name") or process.pid)
		for process in _matching_processes()
	})
	print("Armoury Crate could not be fully stopped.")
	if remaining_names:
		print("Still running: " + ", ".join(remaining_names))
	print("Try running PowerShell as Administrator.")
	return False


def main() -> int:
	return 0 if turn_off_armoury_crate() else 1


TOOL = {
	"id": "ASUS.ArmouryCrateOff",
	"vendor": "ASUS",
	"name": "Turn Off Armoury Crate",
	"description": "Armoury Crate is blocking motherboard sensor access.",
	"action": "StatMonitor can temporarily stop Armoury Crate and related services to restore motherboard sensor access.",
	"restore": "Armoury Crate will return after Windows restarts.",
	"confirmation_required": True,
	"restart_required_to_restore": True,
	"detect": detect_armoury_crate,
	"apply": turn_off_armoury_crate,
}


if __name__ == "__main__":
	raise SystemExit(main())
