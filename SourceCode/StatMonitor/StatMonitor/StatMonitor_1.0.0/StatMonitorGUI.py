from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from StatMonitorLogger import LOG_MODULE_NAMES


_BG = "#0d1117"
_PANEL = "#151b23"
_PANEL_2 = "#10161d"
_TEXT = "#e6edf3"
_MUTED = "#8b949e"
_ACCENT = "#32d7ff"
_GOOD = "#3fb950"
_WARN = "#d29922"
_BAD = "#f85149"
_BORDER = "#30363d"
_ANSI = re.compile(r"\x1b\[([0-9;]*)m")


class StatMonitorGUI:
	def __init__(self, stat_monitor: Any, request_stop: Callable[[], None]):
		self.stat_monitor = stat_monitor
		self.manager = stat_monitor.manager
		self.fan_service = stat_monitor.fan_controller
		self.logger = stat_monitor.logger
		self.request_stop = request_stop
		self.root: tk.Tk | None = None
		self._closing = False
		self._fan_rows: dict[str, dict[str, Any]] = {}
		self._fan_profiles: list[str] = []
		self._fan_maps: list[str] = []
		self._fan_sensor_label_to_id: dict[str, str] = {}
		self._fan_sensor_id_to_label: dict[str, str] = {}
		self._fan_temperature_sensors: list[dict[str, Any]] = []
		self._fan_form_identifier: str | None = None
		self._module_vars: dict[str, tk.BooleanVar] = {}
		self._setting_vars: dict[tuple[str, str], tk.BooleanVar] = {}
		self._log_module_vars: dict[str, tk.BooleanVar] = {}
		self._art_loaded = False
		self._art_tags: dict[str, str] = {}
		self._last_snapshot: dict[str, Any] = {}
		self._status_var: tk.StringVar | None = None
		self._fan_enabled_var: tk.BooleanVar | None = None
		self._fan_name_var: tk.StringVar | None = None
		self._fan_profile_var: tk.StringVar | None = None
		self._fan_map_var: tk.StringVar | None = None
		self._fan_sensor_var: tk.StringVar | None = None
		self._fan_test_var: tk.DoubleVar | None = None
		self._fan_test_label_var: tk.StringVar | None = None
		self._fan_test_confirmed = False
		self._log_duration_var: tk.StringVar | None = None
		self._log_interval_var: tk.StringVar | None = None
		self._log_path_var: tk.StringVar | None = None
		self._log_status_var: tk.StringVar | None = None
		self._overview_vars: dict[str, tk.StringVar] = {}
		self._overview_bars: dict[str, tk.DoubleVar] = {}
		self._overview_bar_labels: dict[str, tk.StringVar] = {}
		self._vendor_rows: dict[str, dict[str, Any]] = {}
		self._storage_rows: dict[str, dict[str, Any]] = {}
		self._network_rows: dict[str, dict[str, Any]] = {}
		self._wifi_rows: dict[str, dict[str, Any]] = {}
		self._bluetooth_rows: dict[str, dict[str, Any]] = {}
		self._storage_tool_rows: dict[str, dict[str, Any]] = {}
		self._storage_partition_rows: dict[str, dict[str, Any]] = {}
		self._storage_tool_capabilities: dict[str, Any] = {}
		self._storage_tools_refreshing = False
		self._privacy_vars: dict[str, tk.StringVar] = {}
		self._privacy_refreshing = False
		self._window_icon_image: tk.PhotoImage | None = None

	def run(self) -> None:
		self.root = tk.Tk()
		self.root.withdraw()
		self.root.title("StatMonitor 1.0.0")
		self.root.geometry("1180x760")
		self.root.minsize(900, 620)
		self.root.configure(bg=_BG)
		self.root.protocol("WM_DELETE_WINDOW", self._close)
		self._apply_window_icon()
		self._apply_style()
		self._build()
		self._load_pythofetch_art()
		self._refresh()
		self.root.update_idletasks()
		self.root.deiconify()
		self.root.mainloop()

	def stop(self) -> None:
		if self.root is None:
			return
		try:
			self.root.after(0, self._destroy)
		except Exception:
			pass

	def _destroy(self) -> None:
		if self.root is None:
			return
		try:
			self.root.destroy()
		except Exception:
			pass
		self.root = None

	def _close(self) -> None:
		if self._closing:
			return
		self._closing = True
		self.request_stop()
		self._destroy()

	def _apply_window_icon(self) -> None:
		if self.root is None:
			return
		try:
			if os.name == "nt":
				import ctypes
				ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ProjectHomelab.StatMonitor")
		except Exception:
			pass
		png_candidates = [
			Path(__file__).resolve().with_name("StatMonitor.png"),
			Path(getattr(self.stat_monitor, "project_root", Path.cwd())) / "StatMonitor.png",
			Path.cwd() / "StatMonitor.png",
		]
		for icon in png_candidates:
			if not icon.is_file():
				continue
			try:
				self._window_icon_image = tk.PhotoImage(file=str(icon))
				self.root.iconphoto(True, self._window_icon_image)
				break
			except Exception:
				continue
		ico_candidates = [
			Path(__file__).resolve().with_name("StatMonitor.ico"),
			Path(getattr(self.stat_monitor, "project_root", Path.cwd())) / "StatMonitor.ico",
			Path.cwd() / "StatMonitor.ico",
		]
		for icon in ico_candidates:
			if not icon.is_file():
				continue
			try:
				self.root.iconbitmap(default=str(icon))
				break
			except Exception:
				continue

	def _apply_style(self) -> None:
		style = ttk.Style(self.root)
		try:
			style.theme_use("clam")
		except Exception:
			pass
		style.configure(".", background=_BG, foreground=_TEXT, fieldbackground=_PANEL, bordercolor=_BORDER, lightcolor=_BORDER, darkcolor=_BORDER)
		style.configure("TFrame", background=_BG)
		style.configure("Panel.TFrame", background=_PANEL)
		style.configure("TLabel", background=_BG, foreground=_TEXT)
		style.configure("Panel.TLabel", background=_PANEL, foreground=_TEXT)
		style.configure("Muted.TLabel", background=_BG, foreground=_MUTED)
		style.configure("Title.TLabel", background=_BG, foreground=_TEXT, font=("Segoe UI", 18, "bold"))
		style.configure("Heading.TLabel", background=_PANEL, foreground=_TEXT, font=("Segoe UI", 11, "bold"))
		style.configure("Value.TLabel", background=_PANEL, foreground=_TEXT, font=("Segoe UI", 10))
		style.configure("Accent.TLabel", background=_BG, foreground=_ACCENT)
		style.configure("TButton", background=_PANEL, foreground=_TEXT, padding=(9, 6))
		style.map("TButton", background=[("active", "#212936")])
		style.configure("TCheckbutton", background=_BG, foreground=_TEXT)
		style.map("TCheckbutton", background=[("active", _BG)])
		style.configure("Panel.TCheckbutton", background=_PANEL, foreground=_TEXT)
		style.map("Panel.TCheckbutton", background=[("active", _PANEL)])
		style.configure("TNotebook", background=_BG, borderwidth=0)
		style.configure("TNotebook.Tab", background=_PANEL, foreground=_MUTED, padding=(14, 8))
		style.map("TNotebook.Tab", background=[("selected", "#1f2630")], foreground=[("selected", _TEXT)])
		style.configure("Treeview", background=_PANEL_2, fieldbackground=_PANEL_2, foreground=_TEXT, rowheight=27, bordercolor=_BORDER)
		style.configure("Treeview.Heading", background=_PANEL, foreground=_TEXT, relief="flat")
		style.map("Treeview", background=[("selected", "#21405a")])
		style.configure("TEntry", fieldbackground=_PANEL_2, foreground=_TEXT, insertcolor=_TEXT)
		style.configure("TCombobox", fieldbackground=_PANEL_2, foreground=_TEXT)
		style.map("TCombobox", fieldbackground=[("readonly", _PANEL_2)], foreground=[("readonly", _TEXT)])
		style.configure("TLabelframe", background=_BG, foreground=_TEXT, bordercolor=_BORDER)
		style.configure("TLabelframe.Label", background=_BG, foreground=_TEXT)
		style.configure("Usage.Horizontal.TProgressbar", troughcolor=_PANEL_2, background=_ACCENT, bordercolor=_BORDER, lightcolor=_ACCENT, darkcolor=_ACCENT, thickness=12)

	def _build(self) -> None:
		root = self.root
		if root is None:
			return
		header = ttk.Frame(root)
		header.pack(fill="x", padx=16, pady=(14, 8))
		ttk.Label(header, text="StatMonitor", style="Title.TLabel").pack(side="left")
		ttk.Label(header, text="1.0.0", style="Muted.TLabel").pack(side="left", padx=(8, 0), pady=(7, 0))
		self._status_var = tk.StringVar(value="Starting hardware providers...")
		ttk.Label(header, textvariable=self._status_var, style="Accent.TLabel").pack(side="right", pady=(7, 0))
		self.notebook = ttk.Notebook(root)
		self.notebook.pack(fill="both", expand=True, padx=16, pady=(0, 10))
		self.overview_tab = ttk.Frame(self.notebook)
		self.fans_tab = ttk.Frame(self.notebook)
		self.storage_tab = ttk.Frame(self.notebook)
		self.network_tab = ttk.Frame(self.notebook)
		self.wifi_tab = ttk.Frame(self.notebook)
		self.bluetooth_tab = ttk.Frame(self.notebook)
		self.privacy_tab = ttk.Frame(self.notebook)
		self.vendor_tools_tab = ttk.Frame(self.notebook)
		self.logs_tab = ttk.Frame(self.notebook)
		self.settings_tab = ttk.Frame(self.notebook)
		for frame, label in ((self.overview_tab, "Overview"), (self.fans_tab, "Fans"), (self.storage_tab, "Storage"), (self.network_tab, "Network"), (self.wifi_tab, "Wi-Fi"), (self.bluetooth_tab, "Bluetooth"), (self.privacy_tab, "Privacy"), (self.vendor_tools_tab, "Vendor Tools"), (self.logs_tab, "Logs"), (self.settings_tab, "Settings")):
			self.notebook.add(frame, text=label)
		self._build_overview()
		self._build_fans()
		self._build_storage()
		self._build_network()
		self._build_wifi()
		self._build_bluetooth()
		self._build_privacy()
		self._build_vendor_tools()
		self._build_logs()
		self._build_settings()
		self.notebook.bind("<<NotebookTabChanged>>", self._main_notebook_changed)
		footer = ttk.Frame(root)
		footer.pack(fill="x", padx=16, pady=(0, 10))
		self.alert_var = tk.StringVar(value="No active warnings.")
		ttk.Label(footer, textvariable=self.alert_var, style="Muted.TLabel").pack(side="left")
		ttk.Label(footer, text="Native GUI · WebSocket server off", style="Muted.TLabel").pack(side="right")
	def _main_tab_selected(self, tab: Any) -> bool:
		if not hasattr(self, "notebook"):
			return False
		try:
			return self.notebook.select() == str(tab)
		except Exception:
			return False

	def _storage_tools_selected(self) -> bool:
		if not hasattr(self, "storage_notebook") or not hasattr(self, "storage_tools_tab"):
			return False
		try:
			return self.storage_notebook.select() == str(self.storage_tools_tab)
		except Exception:
			return False

	def _main_notebook_changed(self, _event=None) -> None:
		if self._main_tab_selected(self.privacy_tab):
			self._request_privacy_refresh()
		elif self._main_tab_selected(self.storage_tab) and self._storage_tools_selected():
			self._request_storage_tools_refresh()

	def _storage_notebook_changed(self, _event=None) -> None:
		if self._main_tab_selected(self.storage_tab) and self._storage_tools_selected():
			self._request_storage_tools_refresh()

	def _build_overview(self) -> None:
		outer = ttk.Frame(self.overview_tab)
		outer.pack(fill="both", expand=True, padx=4, pady=8)
		outer.columnconfigure(0, weight=0, minsize=205)
		outer.columnconfigure(1, weight=1)
		outer.rowconfigure(0, weight=0)
		outer.rowconfigure(1, weight=1)

		art_frame = ttk.Frame(outer, style="Panel.TFrame")
		art_frame.grid(row=0, column=0, sticky="new", padx=(0, 8))
		art_frame.columnconfigure(0, weight=1)
		self.art_text = tk.Text(art_frame, bg=_PANEL, fg=_TEXT, insertbackground=_TEXT, relief="flat", borderwidth=0, highlightthickness=0, wrap="none", font=("Consolas", 8), padx=6, pady=7, width=24, height=24)
		self.art_text.grid(row=0, column=0, sticky="new")
		self.art_text.configure(state="disabled")

		self._overview_vars["System"] = tk.StringVar(value="Loading...")
		system_frame = ttk.Frame(outer, style="Panel.TFrame")
		system_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(8, 0))
		ttk.Label(system_frame, text="System", style="Heading.TLabel").pack(anchor="w", padx=12, pady=(9, 3))
		ttk.Label(system_frame, textvariable=self._overview_vars["System"], style="Value.TLabel", justify="left", wraplength=180).pack(anchor="nw", padx=12, pady=(4, 8))

		cards = ttk.Frame(outer)
		cards.grid(row=0, column=1, rowspan=2, sticky="nsew")
		for row in range(3):
			cards.rowconfigure(row, weight=1)
		for col in range(2):
			cards.columnconfigure(col, weight=1)
		items = (("CPU", 0, 0), ("GPU", 0, 1), ("RAM", 1, 0), ("Motherboard", 1, 1), ("Network", 2, 0), ("Storage", 2, 1))
		for key, row, col in items:
			self._overview_vars[key] = tk.StringVar(value="Loading...")
			frame = ttk.Frame(cards, style="Panel.TFrame")
			frame.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0), pady=(0 if row == 0 else 6, 0))
			ttk.Label(frame, text=key, style="Heading.TLabel").pack(anchor="w", padx=12, pady=(9, 3))
			if key in {"CPU", "GPU", "RAM"}:
				self._build_usage_bar(frame, key, "Utilisation")
			if key == "GPU":
				self._build_usage_bar(frame, "VRAM", "VRAM")
			ttk.Label(frame, textvariable=self._overview_vars[key], style="Value.TLabel", justify="left").pack(anchor="nw", padx=12, pady=(4, 8))

	def _build_usage_bar(self, parent: ttk.Frame, key: str, label: str) -> None:
		row = ttk.Frame(parent, style="Panel.TFrame")
		row.pack(fill="x", padx=12, pady=(2, 2))
		row.columnconfigure(1, weight=1)
		value = tk.DoubleVar(value=0.0)
		text = tk.StringVar(value="0%")
		self._overview_bars[key] = value
		self._overview_bar_labels[key] = text
		ttk.Label(row, text=label, style="Panel.TLabel", width=10).grid(row=0, column=0, sticky="w")
		ttk.Progressbar(row, variable=value, maximum=100.0, style="Usage.Horizontal.TProgressbar").grid(row=0, column=1, sticky="ew", padx=(7, 7))
		ttk.Label(row, textvariable=text, style="Panel.TLabel", width=6, anchor="e").grid(row=0, column=2, sticky="e")

	def _set_overview_bar(self, key: str, value: Any) -> None:
		try:
			percent = float(value)
		except (TypeError, ValueError):
			percent = 0.0
		percent = max(0.0, min(100.0, percent))
		bar = self._overview_bars.get(key)
		label = self._overview_bar_labels.get(key)
		if bar is not None:
			bar.set(percent)
		if label is not None:
			label.set(f"{percent:.0f}%")

	def _build_fans(self) -> None:
		outer = ttk.Frame(self.fans_tab)
		outer.pack(fill="both", expand=True, padx=4, pady=8)
		top = ttk.Frame(outer)
		top.pack(fill="x", pady=(0, 8))
		self._fan_enabled_var = tk.BooleanVar(value=False)
		ttk.Checkbutton(top, text="Enable StatMonitor fan control", variable=self._fan_enabled_var, command=self._toggle_fan_control).pack(side="left")
		ttk.Label(top, text="Once StatMonitor takes fan ownership, restart is required to return firmware control.", style="Muted.TLabel").pack(side="left", padx=14)
		ttk.Button(top, text="Refresh", command=self._refresh_fans).pack(side="right")
		columns = ("number", "name", "reported", "profile", "map", "rpm", "target", "output", "temp", "source", "state")
		self.fan_tree = ttk.Treeview(outer, columns=columns, show="headings", height=10)
		headings = {"number":"#", "name":"Friendly Name", "reported":"Reported", "profile":"Profile", "map":"Map", "rpm":"RPM", "target":"Target", "output":"Output", "temp":"Temp", "source":"Active Sensor", "state":"State"}
		widths = {"number":40, "name":145, "reported":120, "profile":85, "map":95, "rpm":65, "target":65, "output":65, "temp":65, "source":180, "state":90}
		for column in columns:
			self.fan_tree.heading(column, text=headings[column])
			self.fan_tree.column(column, width=widths[column], anchor="w")
		self.fan_tree.pack(fill="both", expand=True)
		self.fan_tree.bind("<<TreeviewSelect>>", self._fan_selected)
		edit = ttk.LabelFrame(outer, text="Selected fan")
		edit.pack(fill="x", pady=(8, 0))
		for col in range(8):
			edit.columnconfigure(col, weight=1 if col in (1,3,5,7) else 0)
		self._fan_name_var = tk.StringVar()
		self._fan_profile_var = tk.StringVar()
		self._fan_map_var = tk.StringVar(value="Profile Default")
		self._fan_sensor_var = tk.StringVar(value="Profile Default")
		ttk.Label(edit, text="Friendly name").grid(row=0, column=0, sticky="w", padx=(10, 4), pady=9)
		self.fan_name_entry = ttk.Entry(edit, textvariable=self._fan_name_var)
		self.fan_name_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=9)
		ttk.Label(edit, text="Profile").grid(row=0, column=2, sticky="w", padx=(0, 4), pady=9)
		self.fan_profile_combo = ttk.Combobox(edit, textvariable=self._fan_profile_var, state="readonly")
		self.fan_profile_combo.grid(row=0, column=3, sticky="ew", padx=(0, 10), pady=9)
		ttk.Label(edit, text="Map").grid(row=0, column=4, sticky="w", padx=(0, 4), pady=9)
		self.fan_map_combo = ttk.Combobox(edit, textvariable=self._fan_map_var, state="readonly")
		self.fan_map_combo.grid(row=0, column=5, sticky="ew", padx=(0, 10), pady=9)
		ttk.Label(edit, text="Sensor").grid(row=0, column=6, sticky="w", padx=(0, 4), pady=9)
		self.fan_sensor_combo = ttk.Combobox(edit, textvariable=self._fan_sensor_var, state="readonly", values=("Profile Default",))
		self.fan_sensor_combo.grid(row=0, column=7, sticky="ew", padx=(0, 10), pady=9)
		buttons = ttk.Frame(edit)
		buttons.grid(row=1, column=0, columnspan=8, sticky="ew", padx=10, pady=(0, 10))
		ttk.Button(buttons, text="Apply / Register", command=self._apply_selected_fan).pack(side="left")
		ttk.Button(buttons, text="Unregister", command=self._unregister_selected_fan).pack(side="left", padx=(6, 0))
		ttk.Button(buttons, text="Create Profile", command=self._create_profile_dialog).pack(side="left", padx=(18, 0))
		ttk.Button(buttons, text="Create Fan Map", command=self._create_map_dialog).pack(side="left", padx=(6, 0))
		ttk.Button(buttons, text="Edit Profile Map", command=self._edit_profile_map_dialog).pack(side="left", padx=(6, 0))
		self.fan_message_var = tk.StringVar(value="Select a discovered fan to configure it.")
		ttk.Label(buttons, textvariable=self.fan_message_var, style="Muted.TLabel").pack(side="right")
		test = ttk.LabelFrame(outer, text="Fan identification test")
		test.pack(fill="x", pady=(8, 0))
		test.columnconfigure(1, weight=1)
		self._fan_test_var = tk.DoubleVar(value=50.0)
		self._fan_test_label_var = tk.StringVar(value="50%")
		ttk.Label(test, text="Test speed").grid(row=0, column=0, sticky="w", padx=(10, 8), pady=9)
		ttk.Scale(test, from_=30.0, to=100.0, variable=self._fan_test_var, orient="horizontal", command=self._fan_test_slider_changed).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=9)
		ttk.Label(test, textvariable=self._fan_test_label_var, width=6).grid(row=0, column=2, sticky="w", padx=(0, 8), pady=9)
		ttk.Button(test, text="Apply Test Speed", command=self._apply_fan_test).grid(row=0, column=3, padx=(0, 6), pady=7)
		ttk.Button(test, text="Stop Test / Resume Map", command=self._stop_fan_test).grid(row=0, column=4, padx=(0, 10), pady=7)
		ttk.Label(test, text="Temporary 15-second override for identifying the physical fan. Safety override still wins; taking ownership may require a restart to return firmware control.", style="Muted.TLabel").grid(row=1, column=0, columnspan=5, sticky="w", padx=10, pady=(0, 8))

	def _build_storage(self) -> None:
		outer = ttk.Frame(self.storage_tab)
		outer.pack(fill="both", expand=True, padx=4, pady=8)
		self.storage_notebook = ttk.Notebook(outer)
		self.storage_notebook.pack(fill="both", expand=True)
		volumes_tab = ttk.Frame(self.storage_notebook)
		self.storage_tools_tab = ttk.Frame(self.storage_notebook)
		self.storage_notebook.add(volumes_tab, text="Volumes & Health")
		self.storage_notebook.add(self.storage_tools_tab, text="Drive Tools")
		tools_tab = self.storage_tools_tab

		self.storage_summary_var = tk.StringVar(value="Loading storage information...")
		ttk.Label(volumes_tab, textvariable=self.storage_summary_var, style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
		columns = ("drive", "model", "type", "size", "free", "activity", "temp", "health", "wear", "read", "write")
		self.storage_tree = ttk.Treeview(volumes_tab, columns=columns, show="headings", height=15)
		headings = {"drive":"Drive", "model":"Model", "type":"Type", "size":"Size", "free":"Free", "activity":"Activity", "temp":"Temp", "health":"Health", "wear":"Wear", "read":"Read", "write":"Write"}
		widths = {"drive":95, "model":220, "type":100, "size":90, "free":90, "activity":75, "temp":70, "health":95, "wear":70, "read":95, "write":95}
		for column in columns:
			self.storage_tree.heading(column, text=headings[column])
			self.storage_tree.column(column, width=widths[column], anchor="w")
		self.storage_tree.pack(fill="both", expand=True)
		actions = ttk.Frame(volumes_tab)
		actions.pack(fill="x", pady=(8, 0))
		ttk.Button(actions, text="Open Selected Drive", command=self._open_selected_drive).pack(side="left")
		ttk.Button(actions, text="Refresh", command=lambda: self._refresh_storage(self._last_snapshot)).pack(side="left", padx=(6, 0))
		self.storage_detail_var = tk.StringVar(value="Select a drive for its mount path and live details.")
		ttk.Label(actions, textvariable=self.storage_detail_var, style="Muted.TLabel").pack(side="right")
		self.storage_tree.bind("<<TreeviewSelect>>", self._storage_selected)

		self.storage_tools_status_var = tk.StringVar(value="Physical disk discovery includes disks without Windows/Linux volumes.")
		ttk.Label(tools_tab, textvariable=self.storage_tools_status_var, style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
		disk_columns = ("disk", "model", "bus", "size", "style", "status", "parts", "protection")
		self.storage_disk_tree = ttk.Treeview(tools_tab, columns=disk_columns, show="headings", height=8)
		disk_headings = {"disk":"Physical Disk", "model":"Model", "bus":"Bus", "size":"Size", "style":"Partition Style", "status":"Status", "parts":"Partitions", "protection":"Protection"}
		disk_widths = {"disk":105, "model":245, "bus":80, "size":95, "style":110, "status":130, "parts":75, "protection":260}
		for column in disk_columns:
			self.storage_disk_tree.heading(column, text=disk_headings[column])
			self.storage_disk_tree.column(column, width=disk_widths[column], anchor="w")
		self.storage_disk_tree.pack(fill="x")
		self.storage_disk_tree.bind("<<TreeviewSelect>>", self._storage_tool_disk_selected)

		partition_frame = ttk.LabelFrame(tools_tab, text="Partitions on selected physical disk")
		partition_frame.pack(fill="both", expand=True, pady=(8, 0))
		part_columns = ("number", "path", "size", "filesystem", "label", "mount", "flags")
		self.storage_partition_tree = ttk.Treeview(partition_frame, columns=part_columns, show="headings", height=6)
		part_headings = {"number":"#", "path":"Drive / Device", "size":"Size", "filesystem":"Filesystem", "label":"Label", "mount":"Mount", "flags":"Flags"}
		part_widths = {"number":45, "path":130, "size":90, "filesystem":95, "label":145, "mount":220, "flags":180}
		for column in part_columns:
			self.storage_partition_tree.heading(column, text=part_headings[column])
			self.storage_partition_tree.column(column, width=part_widths[column], anchor="w")
		self.storage_partition_tree.pack(fill="both", expand=True)

		options = ttk.LabelFrame(tools_tab, text="Drive preparation")
		options.pack(fill="x", pady=(8, 0))
		for col in (1, 3, 5, 7):
			options.columnconfigure(col, weight=1)
		self.storage_preset_var = tk.StringVar(value="Portable Storage")
		self.storage_style_var = tk.StringVar(value="GPT")
		self.storage_filesystem_var = tk.StringVar(value="exFAT")
		self.storage_label_var = tk.StringVar(value="StatMonitor Drive")
		ttk.Label(options, text="Preset").grid(row=0, column=0, sticky="w", padx=(10, 4), pady=8)
		self.storage_preset_combo = ttk.Combobox(options, textvariable=self.storage_preset_var, state="readonly", values=("Portable Storage",))
		self.storage_preset_combo.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=8)
		self.storage_preset_combo.bind("<<ComboboxSelected>>", self._storage_preset_selected)
		ttk.Label(options, text="Partition style").grid(row=0, column=2, sticky="w", padx=(0, 4), pady=8)
		self.storage_style_combo = ttk.Combobox(options, textvariable=self.storage_style_var, state="readonly", values=("GPT", "MBR"))
		self.storage_style_combo.grid(row=0, column=3, sticky="ew", padx=(0, 10), pady=8)
		ttk.Label(options, text="Filesystem").grid(row=0, column=4, sticky="w", padx=(0, 4), pady=8)
		self.storage_filesystem_combo = ttk.Combobox(options, textvariable=self.storage_filesystem_var, state="readonly", values=("NTFS", "exFAT", "FAT32", "None"))
		self.storage_filesystem_combo.grid(row=0, column=5, sticky="ew", padx=(0, 10), pady=8)
		ttk.Label(options, text="Label").grid(row=0, column=6, sticky="w", padx=(0, 4), pady=8)
		ttk.Entry(options, textvariable=self.storage_label_var).grid(row=0, column=7, sticky="ew", padx=(0, 10), pady=8)
		buttons = ttk.Frame(options)
		buttons.grid(row=1, column=0, columnspan=8, sticky="ew", padx=10, pady=(0, 10))
		ttk.Button(buttons, text="Refresh Physical Disks", command=self._request_storage_tools_refresh).pack(side="left")
		ttk.Button(buttons, text="Clean Selected Disk", command=self._storage_clean_selected).pack(side="left", padx=(6, 0))
		ttk.Button(buttons, text="Rebuild Selected Disk", command=self._storage_prepare_selected).pack(side="left", padx=(6, 0))
		ttk.Button(buttons, text="Quick Format Selected Partition", command=self._storage_format_selected_partition).pack(side="left", padx=(6, 0))
		ttk.Label(buttons, text="Destructive actions are blocked for the OS disk and the disk running StatMonitor. Typed confirmation is required.", style="Muted.TLabel").pack(side="right")
		self.storage_notebook.bind("<<NotebookTabChanged>>", self._storage_notebook_changed)

	def _build_network(self) -> None:
		outer = ttk.Frame(self.network_tab)
		outer.pack(fill="both", expand=True, padx=4, pady=8)
		self.network_summary_var = tk.StringVar(value="Loading network information...")
		ttk.Label(outer, textvariable=self.network_summary_var, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
		columns = ("name", "type", "state", "network", "ip", "rxlink", "txlink", "down", "up", "signal")
		self.network_tree = ttk.Treeview(outer, columns=columns, show="headings", height=16)
		headings = {"name":"Adapter", "type":"Type", "state":"State", "network":"Network", "ip":"IP Address", "rxlink":"Rx Link", "txlink":"Tx Link", "down":"Download", "up":"Upload", "signal":"Signal"}
		widths = {"name":220, "type":95, "state":85, "network":140, "ip":170, "rxlink":90, "txlink":90, "down":95, "up":95, "signal":65}
		for column in columns:
			self.network_tree.heading(column, text=headings[column])
			self.network_tree.column(column, width=widths[column], anchor="w")
		self.network_tree.pack(fill="both", expand=True)
		actions = ttk.Frame(outer)
		actions.pack(fill="x", pady=(8, 0))
		ttk.Button(actions, text="Refresh", command=lambda: self._refresh_network(self._last_snapshot)).pack(side="left")
		self.network_detail_var = tk.StringVar(value="Physical, virtual and disconnected adapters are shown when enabled in Settings.")
		ttk.Label(actions, textvariable=self.network_detail_var, style="Muted.TLabel").pack(side="right")

	def _build_wifi(self) -> None:
		outer = ttk.Frame(self.wifi_tab)
		outer.pack(fill="both", expand=True, padx=4, pady=8)
		self.wifi_status_var = tk.StringVar(value="Loading Wi-Fi...")
		self.wifi_action_var = tk.StringVar(value="")
		status = ttk.Frame(outer)
		status.pack(fill="x", pady=(0, 8))
		ttk.Label(status, textvariable=self.wifi_status_var).pack(side="left")
		ttk.Label(status, textvariable=self.wifi_action_var, style="Muted.TLabel").pack(side="right")
		buttons = ttk.Frame(outer)
		buttons.pack(fill="x", pady=(0, 8))
		for label, command in (("On", lambda: self._device_action("WiFiOn")), ("Off", lambda: self._device_action("WiFiOff")), ("Scan", lambda: self._device_action("ScanWiFi")), ("Connect", self._wifi_connect), ("Disconnect", lambda: self._device_action("DisconnectWiFi")), ("Forget", self._wifi_forget)):
			ttk.Button(buttons, text=label, command=command).pack(side="left", padx=(0, 6))
		columns = ("ssid", "signal", "security", "cipher", "saved", "connected", "interface")
		self.wifi_tree = ttk.Treeview(outer, columns=columns, show="headings", height=17)
		headings = {"ssid":"SSID", "signal":"Signal", "security":"Security", "cipher":"Cipher", "saved":"Saved", "connected":"Status", "interface":"Adapter"}
		widths = {"ssid":260, "signal":80, "security":150, "cipher":90, "saved":70, "connected":100, "interface":240}
		for column in columns:
			self.wifi_tree.heading(column, text=headings[column])
			self.wifi_tree.column(column, width=widths[column], anchor="w")
		self.wifi_tree.pack(fill="both", expand=True)
		ttk.Label(outer, text="Select a network then Connect or Forget. Connect asks for a password only when needed for a new profile.", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

	def _build_bluetooth(self) -> None:
		outer = ttk.Frame(self.bluetooth_tab)
		outer.pack(fill="both", expand=True, padx=4, pady=8)
		self.bt_status_var = tk.StringVar(value="Loading Bluetooth...")
		self.bt_action_var = tk.StringVar(value="")
		status = ttk.Frame(outer)
		status.pack(fill="x", pady=(0, 8))
		ttk.Label(status, textvariable=self.bt_status_var).pack(side="left")
		ttk.Label(status, textvariable=self.bt_action_var, style="Muted.TLabel").pack(side="right")
		buttons = ttk.Frame(outer)
		buttons.pack(fill="x", pady=(0, 8))
		for label, command in (("On", lambda: self._device_action("BluetoothOn")), ("Off", lambda: self._device_action("BluetoothOff")), ("Scan", lambda: self._device_action("ScanBluetooth")), ("Pair", lambda: self._bluetooth_device_action("PairBluetoothDevice")), ("Unpair", lambda: self._bluetooth_device_action("UnpairBluetoothDevice")), ("Connect", lambda: self._bluetooth_device_action("ConnectBluetoothDevice")), ("Disconnect", lambda: self._bluetooth_device_action("DisconnectBluetoothDevice"))):
			ttk.Button(buttons, text=label, command=command).pack(side="left", padx=(0, 6))
		columns = ("name", "type", "transport", "paired", "connected", "battery", "signal", "address")
		self.bt_tree = ttk.Treeview(outer, columns=columns, show="headings", height=17)
		headings = {"name":"Device", "type":"Type", "transport":"Transport", "paired":"Paired", "connected":"Connected", "battery":"Battery", "signal":"Signal", "address":"Address / ID"}
		widths = {"name":230, "type":125, "transport":130, "paired":70, "connected":85, "battery":75, "signal":75, "address":270}
		for column in columns:
			self.bt_tree.heading(column, text=headings[column])
			self.bt_tree.column(column, width=widths[column], anchor="w")
		self.bt_tree.pack(fill="both", expand=True)
		ttk.Label(outer, text="Select a device then Pair, Unpair, Connect or Disconnect. Scan refreshes discovery.", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
	def _build_privacy(self) -> None:
		outer = ttk.Frame(self.privacy_tab)
		outer.pack(fill="both", expand=True, padx=4, pady=8)
		ttk.Label(outer, text="Webcam, microphone and location privacy controls. Windows policy may override per-user settings.", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
		grid = ttk.Frame(outer)
		grid.pack(fill="x")
		for column in range(3):
			grid.columnconfigure(column, weight=1)
		for column, (key, title, on_command, off_command) in enumerate((("camera", "Webcam", "CameraOn", "CameraOff"), ("microphone", "Microphone", "MicrophoneOn", "MicrophoneOff"), ("location", "Location", "LocationOn", "LocationOff"))):
			panel = ttk.LabelFrame(grid, text=title)
			panel.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
			status_var = tk.StringVar(value="Loading...")
			detail_var = tk.StringVar(value="")
			self._privacy_vars[f"{key}:status"] = status_var
			self._privacy_vars[f"{key}:detail"] = detail_var
			ttk.Label(panel, textvariable=status_var, style="Heading.TLabel").pack(anchor="w", padx=12, pady=(10, 4))
			ttk.Label(panel, textvariable=detail_var, style="Muted.TLabel", justify="left", wraplength=300).pack(anchor="w", padx=12, pady=(0, 10))
			buttons = ttk.Frame(panel, style="Panel.TFrame")
			buttons.pack(fill="x", padx=10, pady=(0, 10))
			ttk.Button(buttons, text="Enable", command=lambda c=on_command: self._privacy_action(c)).pack(side="left")
			ttk.Button(buttons, text="Disable", command=lambda c=off_command: self._privacy_action(c)).pack(side="left", padx=(6, 0))
		self.privacy_action_var = tk.StringVar(value="")
		actions = ttk.Frame(outer)
		actions.pack(fill="x", pady=(10, 0))
		ttk.Button(actions, text="Refresh Status", command=self._request_privacy_refresh).pack(side="left")
		ttk.Label(actions, textvariable=self.privacy_action_var, style="Muted.TLabel").pack(side="left", padx=(10, 0))

	def _build_vendor_tools(self) -> None:
		outer = ttk.Frame(self.vendor_tools_tab)
		outer.pack(fill="both", expand=True, padx=4, pady=8)
		columns = ("vendor", "name", "status", "restore")
		self.vendor_tree = ttk.Treeview(outer, columns=columns, show="headings", height=10)
		self.vendor_tree.heading("vendor", text="Vendor")
		self.vendor_tree.heading("name", text="Tool")
		self.vendor_tree.heading("status", text="Status")
		self.vendor_tree.heading("restore", text="Restore")
		self.vendor_tree.column("vendor", width=120, anchor="w")
		self.vendor_tree.column("name", width=260, anchor="w")
		self.vendor_tree.column("status", width=140, anchor="w")
		self.vendor_tree.column("restore", width=260, anchor="w")
		self.vendor_tree.pack(fill="both", expand=True)
		self.vendor_tree.bind("<<TreeviewSelect>>", self._vendor_selected)
		detail = ttk.LabelFrame(outer, text="Selected vendor tool")
		detail.pack(fill="x", pady=(10, 0))
		self.vendor_var = tk.StringVar(value="No vendor tools detected.")
		ttk.Label(detail, textvariable=self.vendor_var, justify="left", wraplength=880).pack(side="left", fill="x", expand=True, padx=10, pady=10)
		actions = ttk.Frame(detail)
		actions.pack(side="right", padx=10, pady=8)
		ttk.Button(actions, text="Apply Selected Tool", command=self._apply_vendor_tool).pack(side="left")
		ttk.Button(actions, text="Refresh", command=self._refresh_vendor).pack(side="left", padx=(6, 0))

	def _build_logs(self) -> None:
		outer = ttk.Frame(self.logs_tab)
		outer.pack(fill="both", expand=True, padx=4, pady=8)
		selection = ttk.LabelFrame(outer, text="Telemetry")
		selection.pack(fill="x")
		for index, name in enumerate(LOG_MODULE_NAMES):
			var = tk.BooleanVar(value=name in ("CPU", "GPU", "RAM"))
			self._log_module_vars[name] = var
			ttk.Checkbutton(selection, text=name, variable=var).grid(row=index // 6, column=index % 6, sticky="w", padx=10, pady=7)
		controls = ttk.LabelFrame(outer, text="Log options")
		controls.pack(fill="x", pady=(10, 0))
		for col in (1,3,5):
			controls.columnconfigure(col, weight=1)
		self._log_duration_var = tk.StringVar(value="")
		self._log_interval_var = tk.StringVar(value="1s")
		self._log_path_var = tk.StringVar(value=str(self.logger.default_directory))
		ttk.Label(controls, text="Duration").grid(row=0, column=0, sticky="w", padx=(10, 4), pady=10)
		ttk.Entry(controls, textvariable=self._log_duration_var).grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=10)
		ttk.Label(controls, text="blank = until stopped", style="Muted.TLabel").grid(row=1, column=1, sticky="w", padx=(0, 10), pady=(0, 8))
		ttk.Label(controls, text="Interval").grid(row=0, column=2, sticky="w", padx=(0, 4), pady=10)
		ttk.Entry(controls, textvariable=self._log_interval_var).grid(row=0, column=3, sticky="ew", padx=(0, 10), pady=10)
		ttk.Label(controls, text="Save path").grid(row=0, column=4, sticky="w", padx=(0, 4), pady=10)
		path_row = ttk.Frame(controls)
		path_row.grid(row=0, column=5, sticky="ew", padx=(0, 10), pady=10)
		path_row.columnconfigure(0, weight=1)
		ttk.Entry(path_row, textvariable=self._log_path_var).grid(row=0, column=0, sticky="ew")
		ttk.Button(path_row, text="Browse", command=self._browse_log_path).grid(row=0, column=1, padx=(5, 0))
		actions = ttk.Frame(outer)
		actions.pack(fill="x", pady=10)
		ttk.Button(actions, text="Start Logging", command=self._start_log).pack(side="left")
		ttk.Button(actions, text="Stop Logging", command=self._stop_log).pack(side="left", padx=(6, 0))
		ttk.Button(actions, text="Open Log Folder", command=self._open_log_folder).pack(side="left", padx=(18, 0))
		self._log_status_var = tk.StringVar(value="Logging is stopped.")
		ttk.Label(actions, textvariable=self._log_status_var, style="Muted.TLabel").pack(side="right")
		info = ttk.LabelFrame(outer, text="Format")
		info.pack(fill="x")
		ttk.Label(info, text="Logs are graph-friendly JSONL time series with timestamp, elapsed time, selected module data and flattened numeric series.", style="Muted.TLabel").pack(anchor="w", padx=10, pady=10)

	def _build_settings(self) -> None:
		outer = ttk.Frame(self.settings_tab)
		outer.pack(fill="both", expand=True, padx=4, pady=8)
		settings_notebook = ttk.Notebook(outer)
		settings_notebook.pack(fill="both", expand=True)

		general_tab = ttk.Frame(settings_notebook)
		settings_notebook.add(general_tab, text="General")
		modules = ttk.LabelFrame(general_tab, text="Modules")
		modules.pack(fill="x", padx=4, pady=(4, 0))
		for index, name in enumerate(("CPU", "GPU", "RAM", "Drives", "Network", "WiFi", "Bluetooth", "Power", "Motherboard", "System")):
			var = tk.BooleanVar(value=self.stat_monitor.settings.is_module_enabled(name))
			self._module_vars[name] = var
			ttk.Checkbutton(modules, text=name, variable=var, command=self._save_module_settings).grid(row=index // 5, column=index % 5, sticky="w", padx=12, pady=8)

		application = ttk.LabelFrame(general_tab, text="Application")
		application.pack(fill="x", padx=4, pady=(10, 0))
		self.ai_var = tk.BooleanVar(value=self.stat_monitor.settings.is_ai_enabled())
		ttk.Checkbutton(application, text="Enable AI tool interface", variable=self.ai_var, command=self._toggle_ai).pack(anchor="w", padx=10, pady=9)
		path = getattr(self.stat_monitor.settings, "path", None)
		self.settings_path_var = tk.StringVar(value=f"Settings: {path}" if path else "Settings path unavailable")
		ttk.Label(application, textvariable=self.settings_path_var, style="Muted.TLabel").pack(anchor="w", padx=10, pady=(0, 9))

		actions = ttk.Frame(general_tab)
		actions.pack(fill="x", padx=4, pady=10)
		ttk.Button(actions, text="Open Settings Folder", command=self._open_settings_folder).pack(side="left")
		ttk.Button(actions, text="Reload Settings", command=self._reload_settings_from_disk).pack(side="left", padx=(6, 0))
		ttk.Button(actions, text="Reset All Defaults", command=self._reset_settings_defaults).pack(side="left", padx=(18, 0))

		sections = (("CPU", "CPU"), ("GPU", "GPU"), ("RAM", "RAM"), ("Drives", "Storage"), ("Network", "Network"), ("WiFi", "Wi-Fi"), ("Bluetooth", "Bluetooth"), ("Power", "Power"), ("Motherboard", "Motherboard"), ("System", "System"))
		for section, title in sections:
			tab = ttk.Frame(settings_notebook)
			settings_notebook.add(tab, text=title)
			panel = ttk.LabelFrame(tab, text=f"{title} display and monitoring")
			panel.pack(fill="both", expand=True, padx=4, pady=4)
			values = self.stat_monitor.settings.get_module_settings(section, resolved=True)
			for index, (key, enabled) in enumerate(values.items()):
				var = tk.BooleanVar(value=bool(enabled))
				self._setting_vars[(section, key)] = var
				label = key[5:] if key.startswith("Show ") else key
				check = ttk.Checkbutton(panel, text=label, variable=var, command=lambda s=section, k=key: self._save_setting(s, k))
				check.grid(row=index // 2, column=index % 2, sticky="w", padx=14, pady=8)
			panel.columnconfigure(0, weight=1)
			panel.columnconfigure(1, weight=1)

	def _refresh(self) -> None:
		if self.root is None or self._closing:
			return
		try:
			snapshot = self.manager.get_latest_snapshot()
			self._last_snapshot = snapshot
			self._refresh_overview(snapshot)
			self._refresh_fans()
			self._refresh_storage(snapshot)
			self._refresh_network(snapshot)
			self._refresh_wifi(snapshot)
			self._refresh_bluetooth(snapshot)
			self._refresh_log_status()
			self._refresh_vendor()
			warnings = snapshot.get("warnings", []) or []
			if warnings:
				message = warnings[-1].get("message") if isinstance(warnings[-1], dict) else str(warnings[-1])
				self.alert_var.set(str(message or "Warning detected"))
			else:
				self.alert_var.set("No active warnings.")
			states = self.manager.get_module_states()
			running = sum(1 for state in states.values() if state == "running")
			if self._status_var is not None:
				self._status_var.set(f"{self.stat_monitor.platform_name} · {running}/{len(states)} modules running")
		except Exception as error:
			if self._status_var is not None:
				self._status_var.set(f"GUI refresh error: {error}")
		if self.root is not None:
			self.root.after(1000, self._refresh)
	def _refresh_overview(self, snapshot: dict[str, Any]) -> None:
		modules = snapshot.get("modules", {}) or {}
		cpu = modules.get("CPU", {}) or {}
		cpu_h = cpu.get("hardware", {}) or {}
		cpu_l = cpu.get("live", {}) or {}
		clock = cpu_l.get("clock", {}) if isinstance(cpu_l.get("clock"), dict) else {}
		self._set_overview_bar("CPU", cpu_l.get("usage_percent"))
		self._overview_vars["CPU"].set("\n".join((str(cpu_h.get("name") or cpu_h.get("brand") or "CPU"), f"Temp: {_fmt(cpu_l.get('temperature_c'), '°C')}    Power: {_fmt(cpu_l.get('power_w'), ' W')}", f"Clock: {_fmt(clock.get('average_mhz'), ' MHz')}")))
		gpu = modules.get("GPU", {}) or {}
		gpu_h = gpu.get("hardware", {}) or {}
		gpu_l = gpu.get("live", {}) or {}
		gpus = gpu_h.get("gpus", []) or []
		live_gpus = gpu_l.get("gpus", []) or []
		gh = gpus[0] if gpus else {}
		gl = live_gpus[0] if live_gpus else {}
		self._set_overview_bar("GPU", gl.get("usage_percent"))
		vram_used = gl.get("vram_used_bytes")
		vram_total = gh.get("vram_total_bytes") or gl.get("vram_total_bytes")
		try:
			vram_percent = float(vram_used) / float(vram_total) * 100.0 if float(vram_total) > 0 else 0.0
		except (TypeError, ValueError, ZeroDivisionError):
			vram_percent = 0.0
		self._set_overview_bar("VRAM", vram_percent)
		self._overview_vars["GPU"].set("\n".join((str(gh.get("name") or "GPU"), f"Temp: {_fmt(gl.get('temperature_c'), '°C')}    Power: {_fmt(gl.get('power_w'), ' W')}", f"VRAM: {_bytes(vram_used)} / {_bytes(vram_total)}")))
		ram = modules.get("RAM", {}) or {}
		ram_h = ram.get("hardware", {}) or {}
		ram_l = ram.get("live", {}) or {}
		self._set_overview_bar("RAM", ram_l.get("usage_percent"))
		self._overview_vars["RAM"].set("\n".join((f"Used: {_bytes(ram_l.get('used_bytes'))}", f"Available: {_bytes(ram_l.get('available_bytes'))}", f"Installed: {_bytes(ram_h.get('total_installed_bytes'))}")))
		system = modules.get("System", {}) or {}
		sys_h = system.get("hardware", {}) or {}
		sys_l = system.get("live", {}) or {}
		version = sys_h.get("os_version", {}) if isinstance(sys_h.get("os_version"), dict) else {}
		self._overview_vars["System"].set("\n".join((str(sys_h.get("device_name") or "System"), f"{sys_h.get('operating_system') or '-'} {version.get('version') or ''}".strip(), f"Build: {version.get('build') or '-'}    Uptime: {_duration(sys_l.get('uptime_seconds'))}")))
		board = modules.get("Motherboard", {}) or {}
		board_h = board.get("hardware", {}) or {}
		board_l = board.get("live", {}) or {}
		provider = board.get("provider", {}) if isinstance(board.get("provider"), dict) else {}
		temperatures = [item for item in (board_l.get("temperatures", []) or []) if isinstance(item, dict)]
		temp_text = ", ".join(f"{item.get('name') or 'Sensor'} {_fmt(item.get('temperature_c'), '°C')}" for item in temperatures[:2]) or "No live board temperatures"
		self._overview_vars["Motherboard"].set("\n".join((f"{board_h.get('manufacturer') or ''} {board_h.get('motherboard_name') or 'Motherboard'}".strip(), f"Chipset: {board_h.get('chipset') or '-'}    BIOS: {board_h.get('bios_version') or '-'}", f"{temp_text} · {str(provider.get('status') or '-').replace('_', ' ').title()}")))
		network = modules.get("Network", {}) or {}
		wifi = modules.get("WiFi", {}) or {}
		nl = network.get("live", {}) or {}
		wl = wifi.get("live", {}) or {}
		connections = wl.get("connections", []) or []
		connection = connections[0] if connections else {}
		self._overview_vars["Network"].set("\n".join((f"SSID: {connection.get('ssid') or connection.get('profile_name') or 'Disconnected'}", f"Signal: {_fmt(connection.get('signal_quality_percent'), '%')}", f"Down: {_rate(nl.get('download_bytes_per_sec'))}    Up: {_rate(nl.get('upload_bytes_per_sec'))}")))
		drives = modules.get("Drives", {}) or {}
		dh = drives.get("hardware", {}) or {}
		dl = drives.get("live", {}) or {}
		drive_list = dh.get("drives", []) or []
		live_by_id = {item.get("drive_id"): item for item in (dl.get("drives", []) or []) if isinstance(item, dict)}
		lines = [f"Detected drives: {len(drive_list)}"]
		for drive in drive_list[:4]:
			live = live_by_id.get(drive.get("drive_id"), {})
			name = drive.get("drive_letter") or drive.get("name") or drive.get("model") or "Drive"
			lines.append(f"{name}: {_fmt(live.get('temperature_c'), '°C')}  {str(live.get('health') or '').replace('_', ' ').title()}")
		self._overview_vars["Storage"].set("    ".join(lines))
	def _refresh_fans(self) -> None:
		if not hasattr(self, "fan_tree"):
			return
		result = self.fan_service.handle_command("GetFanMapStatus", {})
		if not result.get("success"):
			return
		if self._fan_enabled_var is not None and self.root is not None:
			self._fan_enabled_var.set(bool(result.get("enabled")))
		profiles_result = self.fan_service.handle_command("GetFanProfiles", {})
		maps_result = self.fan_service.handle_command("GetFanMaps", {})
		sensors_result = self.fan_service.handle_command("GetFanTemperatureSensors", {})
		self._fan_temperature_sensors = [item for item in sensors_result.get("sensors", []) if isinstance(item, dict) and item.get("id") and item.get("label")] if sensors_result.get("success") else []
		current_sensor_text = self._fan_sensor_var.get() if self._fan_sensor_var is not None else "Profile Default"
		current_sensor_id = self._fan_sensor_label_to_id.get(current_sensor_text)
		self._fan_sensor_label_to_id = {}
		self._fan_sensor_id_to_label = {}
		for sensor in self._fan_temperature_sensors:
			label = str(sensor.get("label"))
			temperature = sensor.get("temperature_c")
			if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
				label = f"{label} — {float(temperature):.1f}°C"
			active = str(sensor.get("active_source_label") or "").strip()
			if active and str(sensor.get("category") or "") == "Automatic":
				label = f"{label} ({active})"
			if sensor.get("trusted") is False:
				label = f"{label} (manual)"
			sensor_id = str(sensor.get("id"))
			if label in self._fan_sensor_label_to_id:
				label = f"{label} [{sensor_id}]"
			self._fan_sensor_label_to_id[label] = sensor_id
			self._fan_sensor_id_to_label[sensor_id] = label
		self.fan_sensor_combo.configure(values=["Profile Default"] + list(self._fan_sensor_label_to_id))
		if self._fan_sensor_var is not None and current_sensor_id:
			self._fan_sensor_var.set(self._fan_sensor_id_to_label.get(current_sensor_id, current_sensor_text))
		profiles = [item.get("name") for item in profiles_result.get("profiles", []) if item.get("name")]
		maps = [item.get("name") for item in maps_result.get("maps", []) if item.get("name")]
		self._fan_profiles = profiles
		self._fan_maps = maps
		self.fan_profile_combo.configure(values=profiles)
		self.fan_map_combo.configure(values=["Profile Default"] + maps)
		selected = self.fan_tree.selection()
		selected_id = selected[0] if selected else None
		current = {item: self.fan_tree.item(item, "values") for item in self.fan_tree.get_children()}
		fans = result.get("fans", []) or []
		self._fan_rows = {}
		seen = set()
		for fan in fans:
			identifier = str(fan.get("identifier") or fan.get("fan_number") or "")
			if not identifier:
				continue
			seen.add(identifier)
			self._fan_rows[identifier] = fan
			state = "Registered" if fan.get("registered") else "Discovered"
			if fan.get("test_active"):
				state = "Testing"
			elif fan.get("last_error"):
				state = "Failsafe"
			elif fan.get("registered") and not result.get("enabled"):
				state = "Control Off"
			values = (
				fan.get("fan_number") or "-",
				fan.get("friendly_name") or "-",
				fan.get("reported_name") or "-",
				fan.get("profile") or fan.get("best_guess_profile") or "-",
				fan.get("map") or ("Provider" if fan.get("provider_controlled") else "-"),
				_fmt(fan.get("rpm"), ""),
				_fmt(fan.get("target_percent"), "%"),
				_fmt(fan.get("output_percent"), "%"),
				_fmt(fan.get("temperature_c"), "°C"),
				str(fan.get("active_temperature_source_label") or "-"),
				state,
			)
			if identifier in current:
				self.fan_tree.item(identifier, values=values)
			else:
				self.fan_tree.insert("", "end", iid=identifier, values=values)
		for item in self.fan_tree.get_children():
			if item not in seen:
				self.fan_tree.delete(item)
		if selected_id in seen:
			self.fan_tree.selection_set(selected_id)
			fan = self._fan_rows.get(selected_id) or {}
			if fan.get("last_error"):
				self.fan_message_var.set(str(fan.get("last_error")))
			elif fan.get("test_active"):
				self.fan_message_var.set(f"Testing at {_fmt(fan.get('test_percent'), '%')} · {_fmt(fan.get('test_remaining_seconds'), 's')} remaining · RPM {_fmt(fan.get('rpm'), '')}")
			elif fan.get("registered") and not result.get("enabled"):
				self.fan_message_var.set("Configuration saved, but StatMonitor fan control is disabled so the selected map is not currently being applied.")
			else:
				self.fan_message_var.set(f"Target {_fmt(fan.get('target_percent'), '%')} · Output {_fmt(fan.get('output_percent'), '%')} · Temp {_fmt(fan.get('temperature_c'), '°C')} · Source {fan.get('active_temperature_source_label') or 'Waiting...'}")
		elif selected_id is not None:
			self._fan_form_identifier = None

	def _fan_selected(self, _event=None) -> None:
		selection = self.fan_tree.selection()
		if not selection:
			self._fan_form_identifier = None
			return
		identifier = selection[0]
		if identifier == self._fan_form_identifier:
			return
		self._fan_form_identifier = identifier
		fan = self._fan_rows.get(identifier) or {}
		if self._fan_name_var is not None:
			self._fan_name_var.set(str(fan.get("friendly_name") or fan.get("reported_name") or ""))
		profile = fan.get("profile") or fan.get("best_guess_profile") or (self._fan_profiles[0] if self._fan_profiles else "")
		if self._fan_profile_var is not None:
			self._fan_profile_var.set(str(profile))
		if self._fan_map_var is not None:
			self._fan_map_var.set(str(fan.get("map_override") or "Profile Default"))
		source_override = fan.get("temperature_source_override")
		if self._fan_sensor_var is not None:
			if source_override:
				source_id = str(source_override)
				self._fan_sensor_var.set(self._fan_sensor_id_to_label.get(source_id, source_id))
			else:
				self._fan_sensor_var.set("Profile Default")
		if self._fan_test_var is not None:
			current = fan.get("test_percent") if fan.get("test_active") else fan.get("target_percent")
			if not isinstance(current, (int, float)) or isinstance(current, bool):
				current = fan.get("output_percent")
			if not isinstance(current, (int, float)) or isinstance(current, bool):
				current = 50.0
			self._fan_test_var.set(max(30.0, min(100.0, float(current))))
			self._fan_test_slider_changed(self._fan_test_var.get())
		if fan.get("last_error"):
			self.fan_message_var.set(str(fan.get("last_error")))
		else:
			self.fan_message_var.set(f"Hardware: {fan.get('reported_name') or '-'} · Best guess: {fan.get('best_guess_profile') or fan.get('profile') or '-'}")

	def _selected_fan(self) -> dict[str, Any] | None:
		selection = self.fan_tree.selection()
		return self._fan_rows.get(selection[0]) if selection else None

	def _apply_selected_fan(self) -> None:
		fan = self._selected_fan()
		if not fan or not fan.get("fan_number"):
			messagebox.showinfo("StatMonitor", "Select a currently discovered fan first.", parent=self.root)
			return
		number = int(fan["fan_number"])
		name = self._fan_name_var.get().strip() if self._fan_name_var is not None else ""
		profile = self._fan_profile_var.get().strip() if self._fan_profile_var is not None else ""
		fan_map = self._fan_map_var.get().strip() if self._fan_map_var is not None else "Profile Default"
		sensor_label = self._fan_sensor_var.get().strip() if self._fan_sensor_var is not None else "Profile Default"
		sensor = None if sensor_label == "Profile Default" else self._fan_sensor_label_to_id.get(sensor_label, sensor_label)
		if not profile:
			messagebox.showerror("StatMonitor", "Choose a fan profile.", parent=self.root)
			return
		if not fan.get("registered"):
			result = self.fan_service.handle_command("RegisterFan", {"fan_number": number, "profile": profile, "friendly_name": name or None})
			if not result.get("success"):
				self._show_result_error(result)
				return
		else:
			if name:
				result = self.fan_service.handle_command("SetFanFriendlyName", {"fan_number": number, "name": name})
				if not result.get("success"):
					self._show_result_error(result)
					return
			result = self.fan_service.handle_command("SetFanProfile", {"fan_number": number, "profile": profile})
			if not result.get("success"):
				self._show_result_error(result)
				return
		if fan_map == "Profile Default":
			result = self.fan_service.handle_command("RemoveFanMapAssignment", {"fan_number": number})
		else:
			result = self.fan_service.handle_command("AssignFanMap", {"fan_number": number, "map": fan_map})
		if not result.get("success"):
			self._show_result_error(result)
			return
		result = self.fan_service.handle_command("SetFanTemperatureSource", {"fan_number": number, "source": sensor})
		if not result.get("success"):
			self._show_result_error(result)
			return
		control_enabled = bool(self._fan_enabled_var.get()) if self._fan_enabled_var is not None else False
		if not control_enabled:
			enable_now = messagebox.askyesno("Fan configuration saved", "The fan configuration was saved, but StatMonitor fan control is currently disabled. Enable it now so the selected fan map is actually applied?\n\nOnce StatMonitor takes ownership, a restart may be required to return firmware control.", parent=self.root)
			if enable_now:
				result = self.fan_service.handle_command("SetFanMapsEnabled", {"enabled": True})
				if not result.get("success"):
					self._show_result_error(result)
				else:
					self._fan_enabled_var.set(True)
		self.fan_message_var.set("Fan configuration saved. Waiting for the controller to apply the selected map.")
		self._refresh_fans()

	def _fan_test_slider_changed(self, value: Any = None) -> None:
		if self._fan_test_label_var is None:
			return
		try:
			percent = float(self._fan_test_var.get() if self._fan_test_var is not None else value)
		except Exception:
			percent = 50.0
		self._fan_test_label_var.set(f"{percent:.0f}%")

	def _apply_fan_test(self) -> None:
		fan = self._selected_fan()
		if not fan or not fan.get("fan_number"):
			messagebox.showinfo("Fan test", "Select a currently discovered fan first.", parent=self.root)
			return
		if not self._fan_test_confirmed:
			confirmed = messagebox.askyesno("Fan identification test", "This will temporarily take software control of the selected fan for 15 seconds. On affected hardware, firmware control cannot be restored until the machine restarts.\n\nContinue?", parent=self.root)
			if not confirmed:
				return
			self._fan_test_confirmed = True
		percent = float(self._fan_test_var.get()) if self._fan_test_var is not None else 50.0
		result = self.fan_service.handle_command("TestFanSpeed", {"fan_number": int(fan["fan_number"]), "percent": percent})
		if not result.get("success"):
			self._show_result_error(result)
			return
		self.fan_message_var.set(f"Fan test applied at {percent:.0f}% for 15 seconds.")
		self._refresh_fans()

	def _stop_fan_test(self) -> None:
		fan = self._selected_fan()
		if not fan or not fan.get("fan_number"):
			return
		result = self.fan_service.handle_command("StopFanTest", {"fan_number": int(fan["fan_number"])})
		if not result.get("success"):
			self._show_result_error(result)
			return
		self.fan_message_var.set("Fan test stopped. The configured map will resume if fan control is enabled; otherwise the owned channel is held at 100% failsafe.")
		self._refresh_fans()

	def _unregister_selected_fan(self) -> None:
		fan = self._selected_fan()
		if not fan or not fan.get("fan_number"):
			return
		if not messagebox.askyesno("Unregister fan", "Remove this fan registration? If StatMonitor already owns the channel it will move it to 100% failsafe until reboot.", parent=self.root):
			return
		result = self.fan_service.handle_command("UnregisterFan", {"fan_number": int(fan["fan_number"])})
		if result.get("success"):
			self.fan_message_var.set("Fan unregistered.")
			self._fan_form_identifier = None
			self._refresh_fans()
		else:
			self._show_result_error(result)

	def _toggle_fan_control(self) -> None:
		enabled = bool(self._fan_enabled_var.get()) if self._fan_enabled_var is not None else False
		if enabled:
			confirmed = messagebox.askyesno("Enable fan control", "StatMonitor will take software ownership of registered fan channels as maps are applied. On affected hardware, firmware control cannot be restored until the machine restarts. Continue?", parent=self.root)
			if not confirmed:
				if self._fan_enabled_var is not None:
					self._fan_enabled_var.set(False)
				return
		result = self.fan_service.handle_command("SetFanMapsEnabled", {"enabled": enabled})
		if not result.get("success"):
			self._show_result_error(result)
		self._refresh_fans()

	def _create_profile_dialog(self) -> None:
		name = simpledialog.askstring("Create fan profile", "Profile name:", parent=self.root)
		if not name:
			return
		fan_map = self._choice_dialog("Create fan profile", "Default map:", ["Provider"] + self._fan_maps, "Balanced")
		if not fan_map:
			return
		source_values = list(self._fan_sensor_label_to_id) or ["Automatic — Hottest CPU/GPU"]
		source_label = self._choice_dialog("Create fan profile", "Temperature source:", source_values, "Automatic — Hottest CPU/GPU")
		if not source_label:
			return
		source = self._fan_sensor_label_to_id.get(source_label, "CaseHottest" if source_label == "Automatic — Hottest CPU/GPU" else source_label)
		result = self.fan_service.handle_command("CreateFanProfile", {"name": name, "map": fan_map, "temperature_source": source})
		if result.get("success"):
			self.fan_message_var.set(f"Created profile {name}.")
			self._refresh_fans()
		else:
			self._show_result_error(result)

	def _create_map_dialog(self) -> None:
		window = tk.Toplevel(self.root)
		window.title("Create Fan Map")
		window.configure(bg=_BG)
		window.transient(self.root)
		window.grab_set()
		window.geometry("430x420")
		frame = ttk.Frame(window)
		frame.pack(fill="both", expand=True, padx=14, pady=14)
		name_var = tk.StringVar()
		hysteresis_var = tk.StringVar(value="3")
		ttk.Label(frame, text="Map name").pack(anchor="w")
		ttk.Entry(frame, textvariable=name_var).pack(fill="x", pady=(3, 10))
		ttk.Label(frame, text="Hysteresis °C").pack(anchor="w")
		ttk.Entry(frame, textvariable=hysteresis_var).pack(fill="x", pady=(3, 10))
		ttk.Label(frame, text="Temperature / speed points").pack(anchor="w")
		ttk.Label(frame, text="One per line, for example: 30=40   50=55   70=80   88=100", style="Muted.TLabel").pack(anchor="w", pady=(0, 5))
		points_text = tk.Text(frame, bg=_PANEL_2, fg=_TEXT, insertbackground=_TEXT, relief="flat", height=11, font=("Consolas", 10))
		points_text.pack(fill="both", expand=True)
		points_text.insert("1.0", "30=40\n50=40\n60=50\n70=65\n80=85\n88=100")
		buttons = ttk.Frame(frame)
		buttons.pack(fill="x", pady=(10, 0))
		def save():
			try:
				points = []
				for raw in points_text.get("1.0", "end").splitlines():
					line = raw.strip()
					if not line:
						continue
					parts = re.split(r"\s*(?:=|,|:)\s*", line, maxsplit=1)
					if len(parts) != 2:
						raise ValueError(f"Invalid point: {line}")
					points.append({"temperature_c": float(parts[0]), "speed_percent": float(parts[1])})
				result = self.fan_service.handle_command("CreateFanMap", {"name": name_var.get().strip(), "points": points, "hysteresis_c": float(hysteresis_var.get())})
				if not result.get("success"):
					raise ValueError(result.get("message") or result.get("error") or "Unable to create fan map")
				window.destroy()
				self.fan_message_var.set(f"Created fan map {name_var.get().strip()}.")
				self._refresh_fans()
			except Exception as error:
				messagebox.showerror("Fan map", str(error), parent=window)
		ttk.Button(buttons, text="Create", command=save).pack(side="left")
		ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="right")

	def _edit_profile_map_dialog(self) -> None:
		profile = self._choice_dialog("Profile map", "Profile:", self._fan_profiles, self._fan_profiles[0] if self._fan_profiles else "")
		if not profile:
			return
		fan_map = self._choice_dialog("Profile map", "Default fan map:", ["Provider"] + self._fan_maps, "Balanced")
		if not fan_map:
			return
		source_values = list(self._fan_sensor_label_to_id) or ["Automatic — Hottest CPU/GPU"]
		source_label = self._choice_dialog("Profile map", "Temperature source:", source_values, "Automatic — Hottest CPU/GPU")
		if not source_label:
			return
		source = self._fan_sensor_label_to_id.get(source_label, "CaseHottest" if source_label == "Automatic — Hottest CPU/GPU" else source_label)
		result = self.fan_service.handle_command("SetFanProfileMap", {"profile": profile, "map": fan_map, "temperature_source": source})
		if result.get("success"):
			self.fan_message_var.set(f"Updated {profile} profile defaults.")
			self._refresh_fans()
		else:
			self._show_result_error(result)

	def _choice_dialog(self, title: str, label: str, values: list[str], default: str = "") -> str | None:
		if not values:
			return None
		window = tk.Toplevel(self.root)
		window.title(title)
		window.configure(bg=_BG)
		window.transient(self.root)
		window.grab_set()
		var = tk.StringVar(value=default if default in values else values[0])
		frame = ttk.Frame(window)
		frame.pack(fill="both", expand=True, padx=14, pady=14)
		ttk.Label(frame, text=label).pack(anchor="w")
		combo = ttk.Combobox(frame, textvariable=var, values=values, state="readonly", width=34)
		combo.pack(fill="x", pady=(4, 12))
		result = {"value": None}
		def accept():
			result["value"] = var.get()
			window.destroy()
		buttons = ttk.Frame(frame)
		buttons.pack(fill="x")
		ttk.Button(buttons, text="OK", command=accept).pack(side="left")
		ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="right")
		window.wait_window()
		return result["value"]

	def _refresh_storage(self, snapshot: dict[str, Any]) -> None:
		if not hasattr(self, "storage_tree"):
			return
		modules = snapshot.get("modules", {}) or {}
		drives = modules.get("Drives", {}) or {}
		hardware = drives.get("hardware", {}) or {}
		live = drives.get("live", {}) or {}
		hardware_rows = [item for item in (hardware.get("drives", []) or []) if isinstance(item, dict)]
		live_by_id = {str(item.get("drive_id")): item for item in (live.get("drives", []) or []) if isinstance(item, dict) and item.get("drive_id") is not None}
		selected = self.storage_tree.selection()
		selected_id = selected[0] if selected else None
		existing = set(self.storage_tree.get_children())
		self._storage_rows = {}
		for index, drive in enumerate(hardware_rows):
			drive_id = str(drive.get("drive_id") or f"drive-{index}")
			live_drive = live_by_id.get(drive_id, {})
			row_id = f"storage:{index}"
			drive_type = drive.get("drive_type") if isinstance(drive.get("drive_type"), dict) else {}
			name = drive.get("drive_letter") or drive.get("name") or drive.get("mount_path") or drive_id
			type_text = " / ".join(str(drive_type.get(key)) for key in ("class", "bus", "media") if drive_type.get(key)) or "-"
			health = str(live_drive.get("health") or "-").replace("_", " ").title()
			values = (name, drive.get("model") or "-", type_text, _bytes(drive.get("size_bytes")), _bytes(live_drive.get("free_bytes")), _fmt(live_drive.get("activity_percent"), "%"), _fmt(live_drive.get("temperature_c"), "°C"), health, _fmt(live_drive.get("wear_used_percent"), "%"), _rate(live_drive.get("read_bytes_per_sec")), _rate(live_drive.get("write_bytes_per_sec")))
			self._storage_rows[row_id] = {"hardware": drive, "live": live_drive}
			if row_id in existing:
				self.storage_tree.item(row_id, values=values)
				existing.remove(row_id)
			else:
				self.storage_tree.insert("", "end", iid=row_id, values=values)
		for row_id in existing:
			self.storage_tree.delete(row_id)
		if selected_id in self._storage_rows:
			self.storage_tree.selection_set(selected_id)
		self.storage_summary_var.set(f"{len(hardware_rows)} drive(s) detected · SMART/temperature values are shown when the provider exposes them.")
		self._storage_selected()

	def _storage_selected(self, _event=None) -> None:
		selection = self.storage_tree.selection() if hasattr(self, "storage_tree") else ()
		if not selection:
			return
		row = self._storage_rows.get(selection[0]) or {}
		hardware = row.get("hardware", {}) or {}
		live = row.get("live", {}) or {}
		path = hardware.get("mount_path") or hardware.get("open_path") or "-"
		self.storage_detail_var.set(f"{path} · Free {_bytes(live.get('free_bytes'))} · Temp {_fmt(live.get('temperature_c'), '°C')} · Activity {_fmt(live.get('activity_percent'), '%')}")

	def _open_selected_drive(self) -> None:
		selection = self.storage_tree.selection() if hasattr(self, "storage_tree") else ()
		if not selection:
			messagebox.showinfo("StatMonitor", "Select a drive first.", parent=self.root)
			return
		row = self._storage_rows.get(selection[0]) or {}
		hardware = row.get("hardware", {}) or {}
		value = hardware.get("open_path") or hardware.get("mount_path")
		if not value:
			messagebox.showinfo("StatMonitor", "This drive does not expose an open path.", parent=self.root)
			return
		self._open_path(Path(str(value)))

	def _request_storage_tools_refresh(self) -> None:
		if not hasattr(self, "storage_disk_tree") or self._storage_tools_refreshing:
			return
		self._storage_tools_refreshing = True
		self._run_async(lambda: self.stat_monitor.handle_device_command("GetStorageToolDisks", {}), self._storage_tools_refreshed)

	def _storage_tools_refreshed(self, result: Any) -> None:
		self._storage_tools_refreshing = False
		if not isinstance(result, dict) or not result.get("success"):
			if hasattr(self, "storage_tools_status_var"):
				self.storage_tools_status_var.set(str(result.get("message") or result.get("error") or "Drive Tools unavailable") if isinstance(result, dict) else "Drive Tools unavailable")
			return
		capabilities = result.get("capabilities") if isinstance(result.get("capabilities"), dict) else {}
		self._storage_tool_capabilities = capabilities
		presets = [item for item in (capabilities.get("presets", []) or []) if isinstance(item, dict) and item.get("name")]
		if hasattr(self, "storage_preset_combo"):
			self.storage_preset_combo.configure(values=[str(item["name"]) for item in presets])
		if hasattr(self, "storage_style_combo"):
			self.storage_style_combo.configure(values=capabilities.get("partition_styles", []) or ("GPT", "MBR"))
		if hasattr(self, "storage_filesystem_combo"):
			self.storage_filesystem_combo.configure(values=capabilities.get("filesystems", []) or ("NTFS", "exFAT", "FAT32", "None"))
		disks = [item for item in (result.get("disks", []) or []) if isinstance(item, dict)]
		selected = self.storage_disk_tree.selection() if hasattr(self, "storage_disk_tree") else ()
		selected_key = selected[0] if selected else None
		existing = set(self.storage_disk_tree.get_children())
		self._storage_tool_rows = {}
		for index, disk in enumerate(disks):
			row_id = f"physical:{index}"
			disk_id = disk.get("disk_number")
			disk_label = f"Disk {disk_id}" if isinstance(disk_id, int) else str(disk.get("device") or disk_id or index)
			status = ", ".join(str(item) for item in (disk.get("operational_status", []) or [])) or ("Offline" if disk.get("is_offline") else "Online")
			protection = "; ".join(str(item) for item in (disk.get("protected_reasons", []) or [])) or "None"
			values = (disk_label, disk.get("friendly_name") or "-", disk.get("bus_type") or "-", _bytes(disk.get("size")), disk.get("partition_style") or "RAW", status, len(disk.get("partitions", []) or []), protection)
			self._storage_tool_rows[row_id] = disk
			if row_id in existing:
				self.storage_disk_tree.item(row_id, values=values)
				existing.remove(row_id)
			else:
				self.storage_disk_tree.insert("", "end", iid=row_id, values=values)
		for row_id in existing:
			self.storage_disk_tree.delete(row_id)
		if selected_key in self._storage_tool_rows:
			self.storage_disk_tree.selection_set(selected_key)
		elif self.storage_disk_tree.get_children():
			self.storage_disk_tree.selection_set(self.storage_disk_tree.get_children()[0])
		self.storage_tools_status_var.set(f"{len(disks)} physical disk(s) detected · {capabilities.get('platform') or self.stat_monitor.platform_name} Drive Tools")
		self._storage_tool_disk_selected()

	def _storage_tool_disk_selected(self, _event=None) -> None:
		if not hasattr(self, "storage_partition_tree"):
			return
		selection = self.storage_disk_tree.selection() if hasattr(self, "storage_disk_tree") else ()
		disk = self._storage_tool_rows.get(selection[0]) if selection else None
		for row in self.storage_partition_tree.get_children():
			self.storage_partition_tree.delete(row)
		self._storage_partition_rows = {}
		if not disk:
			return
		for index, part in enumerate(disk.get("partitions", []) or []):
			if not isinstance(part, dict):
				continue
			row_id = f"partition:{index}"
			number = part.get("partition_number") or index + 1
			path = part.get("drive_letter") or part.get("path") or "-"
			if part.get("drive_letter"):
				path = f"{part.get('drive_letter')}:"
			mounts = part.get("mountpoints") or part.get("access_paths") or []
			if isinstance(mounts, str):
				mounts = [mounts]
			flags = []
			for key, label in (("is_boot", "Boot"), ("is_system", "System"), ("is_active", "Active")):
				if part.get(key):
					flags.append(label)
			values = (number, path, _bytes(part.get("size") or part.get("volume_size")), part.get("filesystem") or "-", part.get("label") or "-", ", ".join(str(item) for item in mounts if item) or "-", ", ".join(flags) or "-")
			self._storage_partition_rows[row_id] = part
			self.storage_partition_tree.insert("", "end", iid=row_id, values=values)

	def _storage_preset_selected(self, _event=None) -> None:
		name = self.storage_preset_var.get() if hasattr(self, "storage_preset_var") else ""
		for preset in self._storage_tool_capabilities.get("presets", []) or []:
			if isinstance(preset, dict) and str(preset.get("name")) == name:
				self.storage_style_var.set(str(preset.get("partition_style") or "GPT"))
				self.storage_filesystem_var.set(str(preset.get("filesystem") or "None"))
				break

	def _selected_storage_tool_disk(self) -> dict[str, Any] | None:
		selection = self.storage_disk_tree.selection() if hasattr(self, "storage_disk_tree") else ()
		return self._storage_tool_rows.get(selection[0]) if selection else None

	def _storage_disk_identifier(self, disk: dict[str, Any]) -> Any:
		return disk.get("disk_number") if disk.get("disk_number") is not None else disk.get("device")

	def _confirm_disk_action(self, disk: dict[str, Any], title: str, description: str, phrase: str) -> bool:
		if disk.get("protected"):
			messagebox.showerror(title, "StatMonitor has blocked this disk from destructive operations:\n\n" + "\n".join(str(item) for item in disk.get("protected_reasons", []) or []), parent=self.root)
			return False
		model = disk.get("friendly_name") or "Physical Disk"
		size = _bytes(disk.get("size"))
		message = f"{description}\n\n{model}\n{size}\n\nALL DATA AFFECTED BY THIS OPERATION WILL BE LOST.\n\nContinue to typed confirmation?"
		if not messagebox.askyesno(title, message, parent=self.root):
			return False
		value = simpledialog.askstring(title, f"Type exactly:\n{phrase}", parent=self.root)
		return str(value or "").strip() == phrase

	def _storage_clean_selected(self) -> None:
		disk = self._selected_storage_tool_disk()
		if not disk:
			messagebox.showinfo("Drive Tools", "Select a physical disk first.", parent=self.root)
			return
		identifier = self._storage_disk_identifier(disk)
		phrase = f"ERASE DISK {identifier}"
		if not self._confirm_disk_action(disk, "Clean physical disk", "Remove every partition and partition-table entry from this physical disk, leaving it blank/RAW.", phrase):
			return
		self._run_async(lambda: self.stat_monitor.handle_device_command("CleanStorageDisk", {"disk_number": identifier, "confirmation": phrase}), self._storage_tool_action_result)

	def _storage_prepare_selected(self) -> None:
		disk = self._selected_storage_tool_disk()
		if not disk:
			messagebox.showinfo("Drive Tools", "Select a physical disk first.", parent=self.root)
			return
		identifier = self._storage_disk_identifier(disk)
		style = self.storage_style_var.get().strip()
		filesystem = self.storage_filesystem_var.get().strip()
		label = self.storage_label_var.get().strip()
		phrase = f"ERASE DISK {identifier}"
		description = f"Erase the entire disk, initialize it as {style}, create one full-size partition, and format it as {filesystem}."
		if not self._confirm_disk_action(disk, "Rebuild physical disk", description, phrase):
			return
		payload = {"disk_number": identifier, "partition_style": style, "filesystem": filesystem, "label": label, "confirmation": phrase}
		self._run_async(lambda: self.stat_monitor.handle_device_command("PrepareStorageDisk", payload), self._storage_tool_action_result)

	def _storage_format_selected_partition(self) -> None:
		disk = self._selected_storage_tool_disk()
		selection = self.storage_partition_tree.selection() if hasattr(self, "storage_partition_tree") else ()
		part = self._storage_partition_rows.get(selection[0]) if selection else None
		if not disk or not part:
			messagebox.showinfo("Drive Tools", "Select a physical disk and partition first.", parent=self.root)
			return
		identifier = self._storage_disk_identifier(disk)
		part_id = part.get("partition_number") or part.get("path")
		phrase = f"FORMAT DISK {identifier} PARTITION {part_id}"
		filesystem = self.storage_filesystem_var.get().strip()
		if filesystem.casefold() == "none":
			messagebox.showerror("Drive Tools", "Choose a filesystem before quick formatting a partition.", parent=self.root)
			return
		if not self._confirm_disk_action(disk, "Format partition", f"Format only partition {part_id} as {filesystem}. Other partitions remain untouched.", phrase):
			return
		payload = {"disk_number": identifier, "partition_number": part_id, "filesystem": filesystem, "label": self.storage_label_var.get().strip(), "confirmation": phrase}
		self._run_async(lambda: self.stat_monitor.handle_device_command("FormatStoragePartition", payload), self._storage_tool_action_result)

	def _storage_tool_action_result(self, result: Any) -> None:
		if isinstance(result, dict) and result.get("success"):
			messagebox.showinfo("Drive Tools", "Storage operation completed successfully.", parent=self.root)
			self._request_storage_tools_refresh()
			self._refresh_storage(self.manager.get_latest_snapshot())
		else:
			self._show_result_error(result)


	def _refresh_network(self, snapshot: dict[str, Any]) -> None:
		if not hasattr(self, "network_tree"):
			return
		modules = snapshot.get("modules", {}) or {}
		network = modules.get("Network", {}) or {}
		hardware = network.get("hardware", {}) or {}
		live = network.get("live", {}) or {}
		hardware_rows = [item for item in (hardware.get("adapters", []) or []) if isinstance(item, dict)]
		live_by_id = {str(item.get("adapter_id")): item for item in (live.get("adapters", []) or []) if isinstance(item, dict) and item.get("adapter_id") is not None}
		existing = set(self.network_tree.get_children())
		self._network_rows = {}
		for index, adapter in enumerate(hardware_rows):
			adapter_id = str(adapter.get("adapter_id") or f"adapter-{index}")
			live_adapter = live_by_id.get(adapter_id, {})
			row_id = f"network:{index}"
			addresses = adapter.get("ip_addresses", []) or []
			ip_text = ", ".join(str(item.get("address")) for item in addresses if isinstance(item, dict) and item.get("address")) or "-"
			link = adapter.get("link_speed") if isinstance(adapter.get("link_speed"), dict) else {}
			values = (adapter.get("name") or adapter_id, adapter.get("connection_type") or "-", "Connected" if adapter.get("connected") else "Disconnected", adapter.get("network_name") or "-", ip_text, _bit_rate(link.get("receive_bps")), _bit_rate(link.get("transmit_bps")), _rate(live_adapter.get("download_bytes_per_sec")), _rate(live_adapter.get("upload_bytes_per_sec")), _fmt(live_adapter.get("signal_quality_percent"), "%"))
			self._network_rows[row_id] = {"hardware": adapter, "live": live_adapter}
			if row_id in existing:
				self.network_tree.item(row_id, values=values)
				existing.remove(row_id)
			else:
				self.network_tree.insert("", "end", iid=row_id, values=values)
		for row_id in existing:
			self.network_tree.delete(row_id)
		self.network_summary_var.set(f"Download {_rate(live.get('download_bytes_per_sec'))} · Upload {_rate(live.get('upload_bytes_per_sec'))} · Received {_bytes(live.get('total_received_bytes'))} · Sent {_bytes(live.get('total_sent_bytes'))} · {len(hardware_rows)} adapter(s)")

	def _refresh_wifi(self, snapshot: dict[str, Any]) -> None:
		if not hasattr(self, "wifi_tree"):
			return
		modules = snapshot.get("modules", {}) or {}
		wifi = modules.get("WiFi", {}) or {}
		hardware = wifi.get("hardware", {}) or {}
		live = wifi.get("live", {}) or {}
		connections = [item for item in (live.get("connections", []) or []) if isinstance(item, dict)]
		connection = connections[0] if connections else {}
		adapters = [item for item in (hardware.get("adapters", []) or []) if isinstance(item, dict)]
		adapter_name = connection.get("interface_name") or (adapters[0].get("name") if adapters else "-")
		self.wifi_status_var.set(f"Adapter: {adapter_name} · Network: {connection.get('ssid') or connection.get('profile_name') or 'Disconnected'} · Signal: {_fmt(connection.get('signal_quality_percent'), '%')} · Rx {_bit_rate(connection.get('receive_rate_bps'))} · Tx {_bit_rate(connection.get('transmit_rate_bps'))}")
		saved_profiles = [item for item in (hardware.get("saved_networks", []) or []) if isinstance(item, dict)]
		saved_names = {str(item.get("profile_name") or "").casefold() for item in saved_profiles if item.get("profile_name")}
		networks = [dict(item) for item in (hardware.get("available_networks", []) or []) if isinstance(item, dict)]
		visible_names = {str(item.get("ssid") or "").casefold() for item in networks if item.get("ssid")}
		for profile in saved_profiles:
			profile_name = str(profile.get("profile_name") or "").strip()
			if not profile_name or profile_name.casefold() in visible_names:
				continue
			networks.append({"ssid": profile_name, "profile_name": profile_name, "interface_id": profile.get("interface_id"), "interface_name": profile.get("interface_name"), "saved_only": True})
		existing = set(self.wifi_tree.get_children())
		self._wifi_rows = {}
		for index, item in enumerate(networks):
			row_id = f"wifi:{index}"
			ssid = str(item.get("ssid") or "")
			saved = bool(item.get("saved_only")) or bool(item.get("has_profile")) or ssid.casefold() in saved_names
			connected = bool(item.get("connected")) or any(str(c.get("ssid") or "").casefold() == ssid.casefold() for c in connections)
			security = item.get("authentication") or ("Secured" if item.get("security_enabled") else "-")
			status = "Connected" if connected else "Saved" if item.get("saved_only") else "Available"
			values = (ssid or "<Hidden>", _fmt(item.get("signal_quality_percent"), "%"), security or "-", item.get("cipher") or "-", "Yes" if saved else "No", status, item.get("interface_name") or "-")
			self._wifi_rows[row_id] = {**item, "saved": saved}
			if row_id in existing:
				self.wifi_tree.item(row_id, values=values)
				existing.remove(row_id)
			else:
				self.wifi_tree.insert("", "end", iid=row_id, values=values)
		for row_id in existing:
			self.wifi_tree.delete(row_id)
	def _refresh_bluetooth(self, snapshot: dict[str, Any]) -> None:
		if not hasattr(self, "bt_tree"):
			return
		modules = snapshot.get("modules", {}) or {}
		bluetooth = modules.get("Bluetooth", {}) or {}
		hardware = bluetooth.get("hardware", {}) or {}
		live = bluetooth.get("live", {}) or {}
		adapter_h = hardware.get("adapter", {}) if isinstance(hardware.get("adapter"), dict) else {}
		adapter_l = live.get("adapter", {}) if isinstance(live.get("adapter"), dict) else {}
		self.bt_status_var.set(f"Adapter: {adapter_h.get('name') or '-'} · Radio: {str(adapter_l.get('state') or '-').replace('_', ' ').title()} · Classic: {_yesno(adapter_h.get('classic_supported'))} · Low Energy: {_yesno(adapter_h.get('low_energy_supported'))}")
		live_by_id = {str(item.get("device_id")): item for item in (live.get("devices", []) or []) if isinstance(item, dict) and item.get("device_id") is not None}
		try:
			control_result = self.stat_monitor.handle_device_command("GetBluetoothDevices", {})
		except Exception:
			control_result = {}
		control_devices = [item for item in (control_result.get("devices", []) or []) if isinstance(item, dict)] if isinstance(control_result, dict) and control_result.get("success") else []
		if control_devices:
			devices = control_devices
		else:
			devices = [dict(item) for item in (hardware.get("devices", []) or []) if isinstance(item, dict)]
		existing = set(self.bt_tree.get_children())
		self._bluetooth_rows = {}
		for index, item in enumerate(devices):
			device_id = str(item.get("device_id") or f"bt-{index}")
			live_device = live_by_id.get(device_id, {})
			row_id = f"bluetooth:{index}"
			transports = item.get("transports", []) or []
			type_value = item.get("device_type")
			if isinstance(type_value, dict):
				type_value = type_value.get("name") or type_value.get("category") or json.dumps(type_value, default=str)
			paired = item.get("paired") if item.get("paired") is not None else live_device.get("paired")
			connected = item.get("connected") if item.get("connected") is not None else live_device.get("connected")
			battery = item.get("battery_percent") if item.get("battery_percent") is not None else live_device.get("battery_percent")
			signal = live_device.get("signal_strength_dbm")
			address = item.get("address") or device_id
			values = (item.get("name") or "Bluetooth Device", type_value or "-", ", ".join(str(value).replace("_", " ").title() for value in transports) or "-", _yesno(paired), _yesno(connected), _fmt(battery, "%"), _fmt(signal, " dBm"), address)
			self._bluetooth_rows[row_id] = {"device_id": device_id, "name": item.get("name"), "address": item.get("address"), "paired": paired, "connected": connected}
			if row_id in existing:
				self.bt_tree.item(row_id, values=values)
				existing.remove(row_id)
			else:
				self.bt_tree.insert("", "end", iid=row_id, values=values)
		for row_id in existing:
			self.bt_tree.delete(row_id)
	def _selected_wifi(self) -> dict[str, Any] | None:
		selection = self.wifi_tree.selection() if hasattr(self, "wifi_tree") else ()
		return self._wifi_rows.get(selection[0]) if selection else None

	def _wifi_forget(self) -> None:
		selected = self._selected_wifi()
		if not selected:
			messagebox.showinfo("StatMonitor", "Select a Wi-Fi network first.", parent=self.root)
			return
		ssid = str(selected.get("ssid") or "").strip()
		if not ssid:
			return
		payload: dict[str, Any] = {"profile": ssid}
		if selected.get("interface_id"):
			payload["interface_id"] = selected.get("interface_id")
		if messagebox.askyesno("Forget Wi-Fi network", f"Forget the saved Wi-Fi profile for {ssid}?", parent=self.root):
			self._device_action("ForgetWiFiNetwork", payload)

	def _device_action(self, command: str, arguments: dict[str, Any] | None = None) -> None:
		self._run_async(lambda: self.stat_monitor.handle_device_command(command, arguments or {}), lambda result: self._device_result(command, result))
	def _device_result(self, command: str, result: Any) -> None:
		success = not isinstance(result, dict) or bool(result.get("success", True))
		message = "Completed" if success else str(result.get("message") or result.get("error") or "Failed") if isinstance(result, dict) else "Failed"
		if "Bluetooth" in command:
			if hasattr(self, "bt_action_var"):
				self.bt_action_var.set(f"{command}: {message}")
		else:
			if hasattr(self, "wifi_action_var"):
				self.wifi_action_var.set(f"{command}: {message}")
		if not success:
			self._show_result_error(result)
	def _wifi_connect(self) -> None:
		selected = self._selected_wifi()
		ssid = str(selected.get("ssid") or "").strip() if selected else ""
		if not ssid:
			ssid = simpledialog.askstring("Wi-Fi", "SSID or saved profile:", parent=self.root) or ""
		if not ssid:
			return
		payload: dict[str, Any] = {"ssid": ssid}
		if selected and selected.get("interface_id"):
			payload["interface_id"] = selected.get("interface_id")
		if selected and selected.get("saved"):
			payload["profile"] = ssid
		else:
			security = str(selected.get("authentication") or "").lower() if selected else ""
			if selected is None or (security and security != "open") or bool(selected.get("security_enabled") if selected else False):
				password = simpledialog.askstring("Wi-Fi", f"Password for {ssid} (leave blank if Windows already has a profile):", parent=self.root, show="*")
				if password:
					payload["password"] = password
		self._device_action("ConnectWiFi", payload)
	def _bluetooth_device_action(self, command: str) -> None:
		selection = self.bt_tree.selection() if hasattr(self, "bt_tree") else ()
		device = None
		if selection:
			row = self._bluetooth_rows.get(selection[0]) or {}
			device = row.get("device_id") or row.get("name")
		if not device:
			device = simpledialog.askstring("Bluetooth", "Device name, address, or ID:", parent=self.root)
		if device:
			self._device_action(command, {"device": device})
	def _request_privacy_refresh(self) -> None:
		if not hasattr(self, "privacy_action_var") or self._privacy_refreshing:
			return
		self._privacy_refreshing = True
		self._run_async(lambda: self.stat_monitor.handle_device_command("GetPrivacyStatus", {}), self._privacy_refreshed)

	def _privacy_refreshed(self, result: Any) -> None:
		self._privacy_refreshing = False
		if not isinstance(result, dict) or not result.get("success"):
			self.privacy_action_var.set(str(result.get("message") or result.get("error") or "Privacy controls unavailable") if isinstance(result, dict) else "Privacy controls unavailable")
			return
		privacy = result.get("privacy") if isinstance(result.get("privacy"), dict) else {}
		for key in ("camera", "microphone", "location"):
			state = privacy.get(key) if isinstance(privacy.get(key), dict) else {}
			status_var = self._privacy_vars.get(f"{key}:status")
			detail_var = self._privacy_vars.get(f"{key}:detail")
			if status_var is None or detail_var is None:
				continue
			if state.get("available") is False:
				status_var.set("Unavailable")
			else:
				status_var.set("Enabled" if state.get("enabled") else "Disabled")
			mode = str(state.get("policy_mode") or "user_control").replace("_", " ").title()
			devices = [item for item in (state.get("devices", []) or []) if isinstance(item, dict)]
			device_text = ", ".join(str(item.get("name")) for item in devices if item.get("name")) or ("No device list required" if key == "location" else "No matching device detected")
			detail_var.set(f"Mode: {mode}\n{device_text}")

	def _privacy_action(self, command: str) -> None:
		self.privacy_action_var.set(f"Applying {command}...")
		self._run_async(lambda: self.stat_monitor.handle_device_command(command, {}), lambda result: self._privacy_action_result(command, result))

	def _privacy_action_result(self, command: str, result: Any) -> None:
		if isinstance(result, dict) and result.get("success"):
			self.privacy_action_var.set(f"{command}: completed")
		else:
			self.privacy_action_var.set(f"{command}: failed")
			self._show_result_error(result)
		self._request_privacy_refresh()


	def _refresh_vendor(self) -> None:
		if not hasattr(self, "vendor_tree"):
			return
		selected = self.vendor_tree.selection()
		selected_id = selected[0] if selected else None
		try:
			tools = self.stat_monitor.vendor_tools.get_status()
		except Exception:
			tools = []
		self._vendor_rows = {str(tool.get("id")): tool for tool in tools if tool.get("id")}
		existing = set(self.vendor_tree.get_children())
		for identifier, tool in self._vendor_rows.items():
			status = "Action Required" if tool.get("available") and tool.get("active") else "Ready" if tool.get("available") else "Unavailable"
			restore = str(tool.get("restore") or ("Restart required" if tool.get("restart_required_to_restore") else "-"))
			values = (tool.get("vendor") or "-", tool.get("name") or identifier, status, restore)
			if identifier in existing:
				self.vendor_tree.item(identifier, values=values)
				existing.remove(identifier)
			else:
				self.vendor_tree.insert("", "end", iid=identifier, values=values)
		for identifier in existing:
			self.vendor_tree.delete(identifier)
		if selected_id in self._vendor_rows:
			self.vendor_tree.selection_set(selected_id)
		elif self._vendor_rows and not self.vendor_tree.selection():
			first = next(iter(self._vendor_rows))
			self.vendor_tree.selection_set(first)
		self._vendor_selected()

	def _vendor_selected(self, _event=None) -> None:
		if not hasattr(self, "vendor_tree") or not hasattr(self, "vendor_var"):
			return
		selection = self.vendor_tree.selection()
		if not selection:
			self.vendor_var.set("No vendor tools detected.")
			return
		tool = self._vendor_rows.get(selection[0])
		if not tool:
			return
		status = "Action required" if tool.get("available") and tool.get("active") else "Ready" if tool.get("available") else "Unavailable"
		parts = [
			str(tool.get("description") or tool.get("name") or tool.get("id")),
			f"Status: {status}",
		]
		if tool.get("action"):
			parts.append(str(tool.get("action")))
		if tool.get("restore"):
			parts.append(str(tool.get("restore")))
		self.vendor_var.set("\n".join(parts))

	def _apply_vendor_tool(self) -> None:
		selection = self.vendor_tree.selection() if hasattr(self, "vendor_tree") else ()
		tool = self._vendor_rows.get(selection[0]) if selection else None
		if tool is None:
			pending = self.stat_monitor.vendor_tools.get_pending()
			tool = pending[0] if pending else None
		if not tool:
			messagebox.showinfo("Vendor Tools", "No vendor workaround currently requires action.", parent=self.root)
			return
		if not tool.get("available", True):
			messagebox.showinfo("Vendor Tools", "The selected vendor tool is unavailable on this system.", parent=self.root)
			return
		if not tool.get("active", False):
			messagebox.showinfo("Vendor Tools", "The selected vendor tool does not currently require action.", parent=self.root)
			return
		if tool.get("confirmation_required", True) and not messagebox.askyesno("Vendor Tool", f"{tool.get('description') or tool.get('name')}\n\nApply this workaround?", parent=self.root):
			return
		self._run_async(lambda: self.stat_monitor.vendor_tools.apply(tool.get("id")), self._vendor_result)

	def _vendor_result(self, result: dict[str, Any]) -> None:
		if result.get("success"):
			messagebox.showinfo("Vendor Tool", "Vendor workaround applied.", parent=self.root)
		else:
			self._show_result_error(result)
		self._refresh_vendor()

	def _browse_log_path(self) -> None:
		path = filedialog.askdirectory(parent=self.root, title="Choose StatMonitor log folder")
		if path and self._log_path_var is not None:
			self._log_path_var.set(path)

	def _start_log(self) -> None:
		modules = [name for name, var in self._log_module_vars.items() if var.get()]
		if not modules:
			messagebox.showerror("Logging", "Select at least one telemetry module.", parent=self.root)
			return
		try:
			duration = None
			text = self._log_duration_var.get().strip() if self._log_duration_var is not None else ""
			if text:
				duration = self.logger.parse_duration(text)
			interval = self.logger.parse_duration(self._log_interval_var.get().strip() if self._log_interval_var is not None else "1s")
			path = self._log_path_var.get().strip() if self._log_path_var is not None else ""
			result = self.logger.start(modules, duration, path or None, interval)
			if not result.get("success"):
				self._show_result_error(result)
			self._refresh_log_status()
		except Exception as error:
			messagebox.showerror("Logging", str(error), parent=self.root)

	def _stop_log(self) -> None:
		self.logger.stop()
		self._refresh_log_status()

	def _refresh_log_status(self) -> None:
		if self._log_status_var is None:
			return
		status = self.logger.get_status()
		if status.get("active"):
			modules = ", ".join(status.get("modules", []))
			self._log_status_var.set(f"Recording {modules} · {_duration(status.get('elapsed_seconds'))} · {status.get('samples', 0)} samples")
		else:
			path = status.get("path")
			self._log_status_var.set(f"Stopped · last file: {path}" if path else "Logging is stopped.")

	def _open_log_folder(self) -> None:
		self._open_path(self.logger.default_directory)

	def _save_module_settings(self) -> None:
		updates = {"Modules": {name: bool(var.get()) for name, var in self._module_vars.items()}}
		try:
			self.stat_monitor.settings.update_settings(updates)
		except Exception as error:
			messagebox.showerror("Settings", str(error), parent=self.root)

	def _save_setting(self, section: str, key: str) -> None:
		var = self._setting_vars.get((section, key))
		if var is None:
			return
		try:
			self.stat_monitor.settings.update(section, key, bool(var.get()))
		except Exception as error:
			messagebox.showerror("Settings", str(error), parent=self.root)

	def _toggle_ai(self) -> None:
		try:
			self.stat_monitor.settings.set_ai_enabled(bool(self.ai_var.get()))
		except Exception as error:
			messagebox.showerror("Settings", str(error), parent=self.root)

	def _open_settings_folder(self) -> None:
		path = getattr(self.stat_monitor.settings, "path", None)
		if path:
			self._open_path(Path(path).parent)

	def _sync_settings_controls(self) -> None:
		for name, var in self._module_vars.items():
			var.set(self.stat_monitor.settings.is_module_enabled(name))
		if hasattr(self, "ai_var"):
			self.ai_var.set(self.stat_monitor.settings.is_ai_enabled())
		for (section, key), var in self._setting_vars.items():
			values = self.stat_monitor.settings.get_module_settings(section, resolved=True)
			if key in values:
				var.set(bool(values[key]))

	def _reset_settings_defaults(self) -> None:
		if not messagebox.askyesno("Reset settings", "Reset StatMonitor settings, fan profiles, custom fan maps, friendly fan names, and assignments to their built-in defaults?", parent=self.root):
			return
		try:
			self.stat_monitor.settings.reset_defaults()
			self._sync_settings_controls()
			self._fan_form_identifier = None
			self._refresh_fans()
		except Exception as error:
			messagebox.showerror("Settings", str(error), parent=self.root)

	def _reload_settings_from_disk(self) -> None:
		path = getattr(self.stat_monitor.settings, "path", None)
		try:
			self.stat_monitor.settings.load()
			self._sync_settings_controls()
			self._fan_form_identifier = None
			self._refresh_fans()
		except Exception as error:
			messagebox.showerror("Settings", str(error), parent=self.root)

	def _load_pythofetch_art(self) -> None:
		if self._art_loaded:
			return
		self._art_loaded = True
		dependencies = getattr(self.stat_monitor, "dependencies", None)
		getter = getattr(dependencies, "get_pythofetch_art", None)
		if not callable(getter):
			self._set_art_plain("Art Unavailable")
			return
		self._run_async(getter, self._render_art)

	def _set_art_plain(self, text: str) -> None:
		self.art_text.configure(state="normal")
		self.art_text.delete("1.0", "end")
		self.art_text.insert("1.0", text)
		self.art_text.configure(state="disabled")

	def _render_art(self, text: str) -> None:
		if not text:
			self._set_art_plain("Art Unavailable")
			return
		self.art_text.configure(state="normal")
		self.art_text.delete("1.0", "end")
		current = _TEXT
		position = 0
		for match in _ANSI.finditer(text):
			segment = text[position:match.start()]
			if segment:
				self.art_text.insert("end", segment, self._art_tag(current))
			current = self._ansi_colour(match.group(1), current)
			position = match.end()
		remaining = text[position:]
		if remaining:
			self.art_text.insert("end", remaining, self._art_tag(current))
		self.art_text.configure(state="disabled")

	def _art_tag(self, colour: str) -> str:
		if colour not in self._art_tags:
			name = f"art_{len(self._art_tags)}"
			self._art_tags[colour] = name
			self.art_text.tag_configure(name, foreground=colour)
		return self._art_tags[colour]

	def _ansi_colour(self, codes: str, current: str) -> str:
		parts = [int(part) for part in codes.split(";") if part.isdigit()]
		if not parts or 0 in parts:
			current = _TEXT
		base = {30:"#000000",31:"#ff5555",32:"#50fa7b",33:"#f1fa8c",34:"#6272a4",35:"#ff79c6",36:"#8be9fd",37:"#f8f8f2"}
		for code in parts:
			if code in base:
				current = base[code]
		for index, code in enumerate(parts):
			if code == 38 and index + 2 < len(parts) and parts[index + 1] == 5:
				current = _xterm_colour(parts[index + 2])
		return current

	def _run_async(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
		def runner():
			try:
				result = work()
			except Exception as error:
				result = {"success": False, "error": type(error).__name__, "message": str(error)}
			root = self.root
			if root is not None and not self._closing:
				try:
					root.after(0, lambda: done(result))
				except Exception:
					pass
		threading.Thread(target=runner, daemon=True).start()

	def _show_result_error(self, result: Any) -> None:
		if isinstance(result, dict):
			message = result.get("message") or result.get("error") or json.dumps(result, default=str)
		else:
			message = str(result)
		messagebox.showerror("StatMonitor", str(message), parent=self.root)

	def _open_path(self, path: Path) -> None:
		path = Path(path)
		path.mkdir(parents=True, exist_ok=True)
		try:
			if os.name == "nt":
				os.startfile(str(path))
			elif sys_platform() == "darwin":
				subprocess.Popen(["open", str(path)])
			else:
				subprocess.Popen(["xdg-open", str(path)])
		except Exception as error:
			messagebox.showerror("StatMonitor", str(error), parent=self.root)


def _fmt(value: Any, suffix: str = "") -> str:
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		return "-"
	return f"{float(value):.1f}{suffix}"


def _bytes(value: Any) -> str:
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		return "-"
	number = float(value)
	for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
		if abs(number) < 1024.0 or unit == "TiB":
			return f"{number:.1f} {unit}"
		number /= 1024.0
	return "-"


def _rate(value: Any) -> str:
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		return "-"
	number = float(value)
	for unit in ("B/s", "KiB/s", "MiB/s", "GiB/s"):
		if abs(number) < 1024.0 or unit == "GiB/s":
			return f"{number:.1f} {unit}"
		number /= 1024.0
	return "-"


def _bit_rate(value: Any) -> str:
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		return "-"
	number = float(value)
	for unit in ("bps", "Kbps", "Mbps", "Gbps", "Tbps"):
		if abs(number) < 1000.0 or unit == "Tbps":
			return f"{number:.1f} {unit}"
		number /= 1000.0
	return "-"


def _yesno(value: Any) -> str:
	if value is None:
		return "-"
	return "Yes" if bool(value) else "No"


def _duration(value: Any) -> str:
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		return "-"
	seconds = max(0, int(float(value)))
	days, seconds = divmod(seconds, 86400)
	hours, seconds = divmod(seconds, 3600)
	minutes, seconds = divmod(seconds, 60)
	parts = []
	if days:
		parts.append(f"{days}d")
	if hours or days:
		parts.append(f"{hours}h")
	if minutes or hours or days:
		parts.append(f"{minutes}m")
	parts.append(f"{seconds}s")
	return " ".join(parts)


def _xterm_colour(value: int) -> str:
	value = max(0, min(255, int(value)))
	base = (
		"#000000", "#800000", "#008000", "#808000", "#000080", "#800080", "#008080", "#c0c0c0",
		"#808080", "#ff0000", "#00ff00", "#ffff00", "#0000ff", "#ff00ff", "#00ffff", "#ffffff",
	)
	if value < 16:
		return base[value]
	if value < 232:
		value -= 16
		red = value // 36
		green = (value % 36) // 6
		blue = value % 6
		steps = (0, 95, 135, 175, 215, 255)
		return f"#{steps[red]:02x}{steps[green]:02x}{steps[blue]:02x}"
	gray = 8 + (value - 232) * 10
	return f"#{gray:02x}{gray:02x}{gray:02x}"


def sys_platform() -> str:
	import sys
	return sys.platform
