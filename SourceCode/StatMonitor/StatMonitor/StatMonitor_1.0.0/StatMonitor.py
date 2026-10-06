from __future__ import annotations

import argparse
import contextlib
import inspect
import io
import json
import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path


def _source_gui_requested(argv: list[str]) -> bool:
	if "--debug" in argv or "--help" in argv or "-h" in argv or "--version" in argv:
		return False
	non_gui = {"--terminal", "--headless", "--headless-server", "--silent-install", "--pythofetch", "--diagnostics", "--command"}
	if any(argument in non_gui for argument in argv):
		return False
	return True


def _relaunch_source_gui_without_console() -> None:
	if os.name != "nt" or getattr(sys, "frozen", False) or os.environ.get("STATMONITOR_GUI_RELAUNCHED") == "1":
		return
	if not _source_gui_requested(sys.argv[1:]):
		return
	executable = Path(sys.executable)
	pythonw = executable.with_name("pythonw.exe")
	if not pythonw.is_file() or executable.name.casefold() == "pythonw.exe":
		return
	environment = os.environ.copy()
	environment["STATMONITOR_GUI_RELAUNCHED"] = "1"
	subprocess.Popen(
		[str(pythonw), str(Path(__file__).resolve()), *sys.argv[1:]],
		cwd=os.getcwd(),
		env=environment,
		creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
	)
	raise SystemExit(0)


if __name__ == "__main__":
	_relaunch_source_gui_without_console()

from StatMonitorPythonDependencies import ensure_python_dependencies

ensure_python_dependencies(quiet=__name__ == "__main__" and _source_gui_requested(sys.argv[1:]))

from StatMonitorAITool import StatMonitorAITool
from StatMonitorDeviceControls import BLUETOOTH_COMMANDS, DEVICE_COMMANDS, PRIVACY_COMMANDS, STORAGE_TOOL_COMMANDS, WIFI_COMMANDS
from StatMonitorDiagnostics import StatMonitorDiagnostics
from StatMonitorFanService import StatMonitorFanService
from StatMonitorLogger import StatMonitorLogger
from StatMonitorManager import StatMonitorManager
from StatMonitorOutput import set_raw_output
from StatMonitorPaths import finish_packaged_containment, prepare_packaged_containment, resolve_project_root
from StatMonitorPlatform import load_platform_modules
from StatMonitorServer import DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT, StatMonitorServer
from StatMonitorSettings import StatMonitorSettings
from StatMonitorTerminal import StatMonitorTerminal
from StatMonitorVendorTools import StatMonitorVendorTools


LOGGER = logging.getLogger(__name__)
VERSION = "1.0.0"


class StatMonitor:
	def __init__(self, *, host: str = DEFAULT_SERVER_HOST, port: int = DEFAULT_SERVER_PORT, allow_remote: bool = False, allowed_origins=None, quiet_dependencies: bool = False):
		self.project_root = resolve_project_root()
		self.platform = load_platform_modules()
		self.platform_name = self.platform.name
		if self.platform.Dependencies is not None:
			try:
				self.dependencies = self.platform.Dependencies(self.project_root, interactive=False if quiet_dependencies else None, quiet=quiet_dependencies)
			except TypeError:
				try:
					self.dependencies = self.platform.Dependencies(self.project_root, interactive=False if quiet_dependencies else None)
				except TypeError:
					self.dependencies = self.platform.Dependencies(self.project_root)
		else:
			self.dependencies = None
		if self.dependencies is not None:
			if quiet_dependencies:
				with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
					self.dependencies.ensure()
			else:
				self.dependencies.ensure()
		self.settings = StatMonitorSettings(self.project_root)
		self.vendor_tools = StatMonitorVendorTools(self.platform.package)
		self.manager = StatMonitorManager(self.settings)
		self.cpu = self._construct(self.platform.CPU)
		self.gpu = self._construct(self.platform.GPU)
		self.power = self._construct(self.platform.Power, cpu_module=self.cpu, gpu_module=self.gpu)
		self.ram = self._construct(self.platform.RAM)
		self.system = self._construct(self.platform.System)
		self.network = self._construct(self.platform.Network)
		self.wifi = self._construct(self.platform.WiFi)
		self.motherboard = self._construct(self.platform.Motherboard)
		self.bluetooth = self._construct(self.platform.Bluetooth)
		self.drives = self._construct(self.platform.StorageDrives)
		self.privacy = self._construct(self.platform.Privacy) if self.platform.Privacy is not None else None
		self.storage_tools = self._construct(self.platform.StorageTools) if self.platform.StorageTools is not None else None
		for name, module in (
			("CPU", self.cpu),
			("GPU", self.gpu),
			("Power", self.power),
			("RAM", self.ram),
			("System", self.system),
			("Network", self.network),
			("WiFi", self.wifi),
			("Motherboard", self.motherboard),
			("Bluetooth", self.bluetooth),
			("Drives", self.drives),
		):
			self.manager.register_module(name, module)
		self.fan_driver = self.platform.FanController(self.motherboard)
		self.fan_controller = StatMonitorFanService(self.manager, self.fan_driver, self.settings)
		self.logger = StatMonitorLogger(self.manager, self.project_root, self.fan_controller)
		self.server = StatMonitorServer(self.manager, self.settings, host=host, port=port, fan_controller=self.fan_controller, logger=self.logger, device_controller=self, vendor_tools=self.vendor_tools, allow_remote=allow_remote, allowed_origins=allowed_origins)
		self.ai_tool = StatMonitorAITool(self.server)
		self._stop_event = threading.Event()
		self._server_started = False
		self.terminal = StatMonitorTerminal(self, request_stop=self._stop_event.set)
		self.gui = None

	def _construct(self, cls, **kwargs):
		signature = inspect.signature(cls)
		if "project_root" in signature.parameters:
			kwargs["project_root"] = self.project_root
		return cls(**kwargs)

	def handle_device_command(self, command: str, arguments: dict | None = None):
		arguments = dict(arguments or {})
		if command in WIFI_COMMANDS:
			handler = getattr(self.wifi, "handle_command", None)
		elif command in BLUETOOTH_COMMANDS:
			handler = getattr(self.bluetooth, "handle_command", None)
		elif command in PRIVACY_COMMANDS:
			handler = getattr(self.privacy, "handle_command", None) if self.privacy is not None else None
		elif command in STORAGE_TOOL_COMMANDS:
			handler = getattr(self.storage_tools, "handle_command", None) if self.storage_tools is not None else None
		else:
			return {"success": False, "error": "unknown_command", "command": command}
		if not callable(handler):
			return {"success": False, "error": "control_unavailable", "command": command}
		return handler(command, arguments)

	def get_device_commands(self):
		return dict(DEVICE_COMMANDS)

	def start(self, *, start_server: bool = False) -> None:
		self.fan_controller.start_driver()
		try:
			self.manager.start()
			self.fan_controller.start_maps()
			if start_server:
				self.server.start()
				self._server_started = True
		except Exception:
			self.fan_controller.stop_maps()
			self.fan_controller.stop_driver()
			self.manager.stop()
			raise
		LOGGER.info("StatMonitor %s started on %s%s", VERSION, self.platform_name, f" at ws://{self.server.host}:{self.server.port}" if start_server else "")

	def stop(self) -> None:
		if self.gui is not None:
			self.gui.stop()
		self.terminal.stop()
		self.ai_tool.stop()
		self.server.stop()
		self._server_started = False
		self.logger.stop()
		self.fan_controller.stop_maps()
		self.fan_controller.stop_driver()
		self.manager.stop()

	def run(self, interface: str, *, start_server: bool = False) -> None:
		self.start(start_server=start_server)
		try:
			prompt_vendor_tools = self.settings.get_module_settings("Motherboard", True).get("Show Vendor Workaround Warnings", True)
			if interface == "terminal" and prompt_vendor_tools:
				self.vendor_tools.prompt_interactive()
			if interface == "gui":
				from StatMonitorGUI import StatMonitorGUI
				self.gui = StatMonitorGUI(self, request_stop=self._stop_event.set)
				self.gui.run()
			elif interface == "terminal":
				if not self.terminal.is_available():
					raise RuntimeError("StatMonitor terminal mode requires an interactive terminal.")
				self.terminal.start()
				self._stop_event.wait()
			else:
				self._stop_event.wait()
		except KeyboardInterrupt:
			pass
		finally:
			self.stop()


def _parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(prog="StatMonitor", description="Cross-platform local hardware telemetry and control service")
	parser.add_argument("--version", action="store_true", help="Print StatMonitor version and exit")
	parser.add_argument("--host", default=DEFAULT_SERVER_HOST, help="Server bind host for --headless-server")
	parser.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT, help="Server port for --headless-server")
	parser.add_argument("--allow-remote", action="store_true", help="Allow non-loopback server binding")
	parser.add_argument("--allow-origin", action="append", default=[], help="Allow an additional browser Origin")
	parser.add_argument("--debug", action="store_true", help="Enable raw provider diagnostics and debug logging")
	mode = parser.add_mutually_exclusive_group()
	mode.add_argument("--gui", action="store_true", help="Run the standalone StatMonitor native GUI")
	mode.add_argument("--terminal", action="store_true", help="Run the legacy interactive command terminal")
	mode.add_argument("--headless", action="store_true", help="Run StatMonitor without a UI or server")
	mode.add_argument("--headless-server", action="store_true", help="Run StatMonitor without a UI and enable the WebSocket server")
	mode.add_argument("--silent-install", action="store_true", help="Prepare required dependencies and exit without starting StatMonitor")
	mode.add_argument("--pythofetch", action="store_true", help="Resolve and run PythoFetch, then exit")
	mode.add_argument("--diagnostics", action="store_true", help="Run a read-only StatMonitor platform preflight and exit")
	mode.add_argument("--command", help="Execute one StatMonitor terminal command, print JSON, and exit")
	parser.add_argument("--output", help="Write --diagnostics results to a JSON file")
	parser.add_argument("--containment-handoff", nargs=2, metavar=("PARENT_PID", "SOURCE_PATH"), help=argparse.SUPPRESS)
	return parser


def _platform_dependencies():
	project_root = resolve_project_root()
	platform = load_platform_modules()
	if platform.Dependencies is None:
		return platform, None
	return platform, platform.Dependencies(project_root)


def main() -> None:
	args = _parser().parse_args()
	gui_mode = not any((args.terminal, args.headless, args.headless_server, args.silent_install, args.pythofetch, args.diagnostics, args.command)) or args.gui
	log_level = logging.DEBUG if args.debug else logging.ERROR if gui_mode else logging.WARNING
	logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
	set_raw_output(args.debug)
	if args.containment_handoff:
		finish_packaged_containment(int(args.containment_handoff[0]), args.containment_handoff[1])
	elif not prepare_packaged_containment():
		return
	if args.version:
		print(f"StatMonitor {VERSION}")
		return
	if args.output and not args.diagnostics:
		raise SystemExit("--output is only valid with --diagnostics")
	if args.diagnostics:
		diagnostics = StatMonitorDiagnostics(resolve_project_root(), load_platform_modules(), VERSION)
		report = diagnostics.collect()
		print(diagnostics.render(report))
		if args.output:
			destination = diagnostics.write_json(report, args.output)
			print()
			print(f"Diagnostics JSON: {destination}")
		return
	if args.silent_install:
		platform, dependencies = _platform_dependencies()
		if dependencies is None:
			print(f"StatMonitor {VERSION}: no managed dependency installer is required for {platform.name}.")
			return
		try:
			dependencies.ensure(force_system_install=True)
		except TypeError:
			dependencies.ensure()
		print(f"StatMonitor {VERSION} dependency preparation complete.")
		return
	if args.pythofetch:
		platform, dependencies = _platform_dependencies()
		if dependencies is None or not hasattr(dependencies, "ensure_pythofetch"):
			raise RuntimeError(f"PythoFetch dependency integration is not available in the {platform.name} StatMonitor build")
		dependencies.ensure_pythofetch()
		raise SystemExit(dependencies.run_pythofetch())
	try:
		service = StatMonitor(host=args.host, port=args.port, allow_remote=args.allow_remote, allowed_origins=args.allow_origin, quiet_dependencies=gui_mode)
	except Exception as error:
		if gui_mode:
			try:
				import tkinter as tk
				from tkinter import messagebox
				window = tk.Tk()
				window.withdraw()
				messagebox.showerror("StatMonitor startup", str(error), parent=window)
				window.destroy()
			except Exception:
				pass
			return
		raise
	def request_stop(signum=None, frame=None):
		service._stop_event.set()
	signal.signal(signal.SIGINT, request_stop)
	if hasattr(signal, "SIGTERM"):
		signal.signal(signal.SIGTERM, request_stop)
	if args.command:
		service.start(start_server=False)
		try:
			result = service.terminal.execute_line(args.command)
			if result is not None:
				print(json.dumps(result, indent=2, default=str))
		finally:
			service.stop()
		return
	if args.terminal:
		service.run("terminal", start_server=False)
	elif args.headless:
		service.run("headless", start_server=False)
	elif args.headless_server:
		service.run("headless", start_server=True)
	else:
		service.run("gui", start_server=False)


if __name__ == "__main__":
	main()
