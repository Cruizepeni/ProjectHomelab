
from __future__ import annotations

import asyncio
import importlib.util
import shutil
import csv
import json
import os
import sys
import threading
import traceback
from datetime import datetime
from urllib.parse import urlsplit, parse_qs
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from YouSnipeDownloadEngine import fetch_metadata, build_metadata_response
from YouSnipeJobManager import YouSnipeJobManager
from YouSnipeSettings import get_effective_settings, get_save_path, update_settings, DEFAULT_ACCENT, normalize_accent
from YouSnipeUpdater import CURRENT_VERSION, check_update, start_external_update
from YouSnipeThumbnails import ThumbnailLoader



UI_BG = "#0d1117"
UI_PANEL = "#151b23"
UI_INPUT = "#10161d"
UI_TEXT = "#e6edf3"
UI_MUTED = "#8b949e"
UI_ACCENT = DEFAULT_ACCENT
UI_GOOD = "#3fb950"
UI_BAD = "#f85149"
UI_BORDER = "#30363d"
UI_HOVER = "#212936"
UI_SELECTED = "#1f2630"


def _display_stage(value):
    return re.sub(r'\s+', ' ', str(value or '').replace('_', ' ')).strip().title()


class Backend:
    

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.manager = None
        self.failure = None
        self.thread = threading.Thread(target=self._run, name="YouSnipe-Backend", daemon=True)
        self.thread.start()
        if not self.ready.wait(timeout=12):
            raise RuntimeError("Timed out starting YouSnipe backend")
        if self.failure:
            raise RuntimeError(f"Unable to start backend: {self.failure}")

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.manager = YouSnipeJobManager()
            self.loop.run_until_complete(self.manager.start())
        except Exception as exc:
            self.failure = exc
            self.ready.set()
            return
        self.ready.set()
        self.loop.run_forever()
        self.loop.close()

    def call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def shutdown(self):
        tasks = list(self.manager._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        await asyncio.sleep(0.1)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


class YouSnipeGUI(tk.Tk):
    def __init__(self):
        if sys.platform.startswith('linux'):
            super().__init__(className='YouSnipe')
        else:
            super().__init__()
        self.title(f"YouSnipe {CURRENT_VERSION}")
        self._configure_window_icon()
        self.geometry("1120x850")
        self.minsize(860, 690)
        self.settings = get_effective_settings()
        self.accent = normalize_accent(self.settings["application"].get("accentColor"))
        self.backend = Backend()
        self.metadata = None
        self.item_rows = {}
        self.notified_access_restrictions = set()
        self.selected_rows = {'queue': set(), 'history': set(), 'playlist': set()}
        self.thumbnail_loader = ThumbnailLoader()
        self.thumbnail_images = {}  
        self.requested_row_thumbnails = set()
        self._original_title = ""
        self._analysis_request_token = 0
        self._analysis_in_progress = False
        self.pending = []
        self.shutting_down = False
        self.media_mode = tk.StringVar(value=self.settings["downloadDefaults"].get("defaultMediaMode", "video"))
        self.format_value = tk.StringVar(value=self.settings["downloadDefaults"].get(
            "defaultAudioFormat" if self.media_mode.get() == "audio" else "defaultVideoFormat", "MP4"))
        self.quality_value = tk.StringVar(value="Highest")
        self.folder_value = tk.StringVar(value=get_save_path(self.media_mode.get(), self.settings))
        self._last_auto_folder = self.folder_value.get()
        self.name_value = tk.StringVar(value="")
        self.playlist_value = tk.BooleanVar(value=False)
        self.url_value = tk.StringVar(value="")
        self._analysed_url = ""
        self.playlist_dialog = None
        self.playlist_list = None  
        self.playlist_selection_text = tk.StringVar(value="Select Playlist Items")
        self.preview_title_value = tk.StringVar(value="")
        self.preview_stage_value = tk.StringVar(value="")
        self.preview_counts_value = tk.StringVar(value="")
        self.preview_visible = False
        self._preview_download_item_ids = ()
        self._single_displayed_item_id = None
        self._single_thumbnail_source = None
        self.preview_progress_value = tk.DoubleVar(value=0.0)
        self.preview_progress_text = tk.StringVar(value='')
        self.single_title_value = tk.StringVar(value='')
        self.single_stage_value = tk.StringVar(value='')
        self.single_details_value = tk.StringVar(value='')
        self.single_progress_value = tk.DoubleVar(value=0.0)
        self.single_progress_text = tk.StringVar(value='')
        self._reported_failure_ids = set()
        self.status_value = tk.StringVar(value="Ready — enter a URL and Analyse.")
        self.summary_value = tk.StringVar(value="Queue: 0 active | History: 0 completed")
        self.history_search = tk.StringVar(value="")
        self.history_filter = tk.StringVar(value="All")
        self.history_search.trace_add("write", lambda *_: self._refresh_queue())
        self.history_filter.trace_add("write", lambda *_: self._refresh_queue())
        self.current_tree = 'queue'
        self.history_sort_column = 'date'
        self.history_sort_descending = True
        self._verified_update = None
        self._draw()
        
        
        self.url_value.trace_add("write", lambda *_: self._url_changed())
        self._update_formats()
        self.quality_value.trace_add('write', lambda *_: self._sync_analysed_output())
        self.after(500, self._poll_queue)
        self.after(120, self._poll_futures)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_window_icon(self):
        from YouSnipeWindowIcon import apply_window_icon
        apply_window_icon(self)

    def _draw(self):
        style = ttk.Style(self)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        self.configure(background=UI_BG)
        
        style.configure('.', font=('Segoe UI', 10), background=UI_BG,
                        foreground=UI_TEXT, fieldbackground=UI_PANEL,
                        bordercolor=UI_BORDER, lightcolor=UI_BORDER, darkcolor=UI_BORDER)
        style.configure('TFrame', background=UI_BG)
        style.configure('Panel.TFrame', background=UI_PANEL)
        style.configure('TLabel', background=UI_BG, foreground=UI_TEXT)
        style.configure('Muted.TLabel', background=UI_BG, foreground=UI_MUTED)
        style.configure('CompactTitle.TLabel', background=UI_BG, foreground=UI_TEXT,
                        font=('Segoe UI', 12, 'bold'))
        style.configure('CompactVersion.TLabel', background=UI_BG, foreground=UI_MUTED,
                        font=('Segoe UI', 8))
        style.configure('CompactStatus.TLabel', background=UI_BG, foreground=self.accent,
                        font=('Segoe UI', 9))
        style.configure('Footer.TLabel', background=UI_PANEL, foreground=UI_TEXT,
                        padding=(9, 7))
        style.configure('TLabelframe', background=UI_BG, foreground=UI_TEXT,
                        bordercolor=UI_BORDER)
        style.configure('TLabelframe.Label', background=UI_BG, foreground=UI_TEXT,
                        font=('Segoe UI', 10, 'bold'))
        style.configure('TButton', background=UI_PANEL, foreground=UI_TEXT,
                        padding=(9, 6), bordercolor=UI_BORDER)
        style.map('TButton', background=[('active', UI_HOVER)])
        style.configure('Accent.TButton', background=UI_PANEL, foreground=self.accent,
                        bordercolor=self.accent, padding=(9, 6))
        style.map('Accent.TButton', background=[('active', UI_HOVER)],
                  foreground=[('active', self.accent)])
        
        style.configure('MainNav.TButton', background=UI_PANEL, foreground=UI_MUTED,
                        padding=(6, 7), bordercolor=UI_BORDER, borderwidth=1,
                        relief='flat', font=('Segoe UI', 9))
        style.map('MainNav.TButton',
                  background=[('selected', UI_SELECTED), ('active', UI_HOVER)],
                  foreground=[('selected', UI_TEXT), ('active', UI_TEXT)],
                  bordercolor=[('selected', '#8995a2'), ('active', UI_BORDER)])
        style.configure('MainTabless.TNotebook', background=UI_BG,
                        borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.layout('MainTabless.TNotebook.Tab', [])
        style.configure('TNotebook', background=UI_BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=UI_PANEL, foreground=UI_MUTED, padding=(14, 8))
        style.map('TNotebook.Tab', background=[('selected', UI_SELECTED)],
                  foreground=[('selected', UI_TEXT)])
        style.configure('TEntry', fieldbackground=UI_INPUT, foreground=UI_TEXT,
                        insertcolor=UI_TEXT, bordercolor=UI_BORDER)
        style.configure('TCombobox', fieldbackground=UI_INPUT, foreground=UI_TEXT,
                        bordercolor=UI_BORDER, arrowcolor=UI_MUTED)
        style.map('TCombobox', fieldbackground=[('readonly', UI_INPUT)],
                  foreground=[('readonly', UI_TEXT)], arrowcolor=[('active', UI_TEXT)])
        style.configure('TCheckbutton', background=UI_BG, foreground=UI_TEXT)
        style.map('TCheckbutton', background=[('active', UI_BG)])
        style.configure('TRadiobutton', background=UI_BG, foreground=UI_TEXT)
        style.map('TRadiobutton', background=[('active', UI_BG)])
        style.configure('Treeview', background=UI_INPUT, fieldbackground=UI_INPUT,
                        foreground=UI_TEXT, rowheight=50, bordercolor=UI_BORDER)
        style.map('Treeview', background=[('selected', '#21405a')],
                  foreground=[('selected', UI_TEXT)])
        style.configure('Treeview.Heading', background=UI_PANEL, foreground=UI_TEXT,
                        relief='flat', font=('Segoe UI', 10, 'bold'))
        style.configure('Download.Horizontal.TProgressbar', background=self.accent,
                        troughcolor=UI_PANEL, bordercolor=UI_BORDER)
        
        self.option_add('*TCombobox*Listbox.background', UI_INPUT)
        self.option_add('*TCombobox*Listbox.foreground', UI_TEXT)
        self.option_add('*TCombobox*Listbox.selectBackground', '#21405a')
        self.option_add('*TCombobox*Listbox.selectForeground', UI_TEXT)

        self.outer = ttk.Frame(self, padding=(12, 6, 12, 10))
        self.outer.pack(fill='both', expand=True)
        outer = self.outer
        
        
        header = ttk.Frame(outer)
        header.pack(fill='x', pady=(0, 6))
        branding = ttk.Frame(header)
        branding.pack(side='left', padx=(0, 9))
        ttk.Label(branding, text='YouSnipe', style='CompactTitle.TLabel').pack(side='left')
        ttk.Label(branding, text=CURRENT_VERSION, style='CompactVersion.TLabel').pack(
            side='left', padx=(5, 0), pady=(3, 0))
        navigation = ttk.Frame(header)
        navigation.pack(side='left', fill='x', expand=True)
        self._nav_buttons = {}

        self.tabs = ttk.Notebook(outer, style='MainTabless.TNotebook')
        self.tabs.pack(fill='both', expand=True)
        self.download_tab = ttk.Frame(self.tabs, padding=12)
        self.history_tab = ttk.Frame(self.tabs, padding=12)
        self.settings_tab = ttk.Frame(self.tabs, padding=12)
        for name, pane in [('Download', self.download_tab),
                           ('History', self.history_tab), ('Settings', self.settings_tab)]:
            self.tabs.add(pane, text=name)
            button = ttk.Button(navigation, text=name, width=0,
                                style='MainNav.TButton',
                                command=lambda target=pane: self.tabs.select(target))
            button.pack(side='left')
            self._nav_buttons[str(pane)] = button
        self.tabs.bind('<<NotebookTabChanged>>', self._sync_main_navigation)
        self._sync_main_navigation()

        source = ttk.LabelFrame(self.download_tab, text='Source', padding=12)
        source.pack(fill='x')
        
        
        source.columnconfigure(1, weight=1)
        ttk.Label(source, text='URL Input:', width=10).grid(row=0, column=0, sticky='w', padx=(0, 6))
        self.url_entry = ttk.Entry(source, textvariable=self.url_value)
        self.url_entry.grid(row=0, column=1, sticky='ew', padx=(0, 9))
        self._context_menu(self.url_entry)
        ttk.Button(source, text='Analyse URL', command=self._analyse).grid(row=0, column=2, sticky='ew')
        ttk.Checkbutton(source, text='Force Playlist Extraction', variable=self.playlist_value).grid(
            row=1, column=1, sticky='w', pady=(8, 0))
        ttk.Button(source, text='Reset URL', command=self._reset_url).grid(
            row=1, column=2, sticky='ew', pady=(8, 0))

        options = ttk.LabelFrame(self.download_tab, text='Output', padding=12)
        options.pack(fill='x', pady=(10, 0))
        row = ttk.Frame(options)
        row.pack(fill='x')
        ttk.Label(row, text='Name:', width=10).pack(side='left')
        self.name_entry = ttk.Entry(row, textvariable=self.name_value)
        self.name_entry.pack(side='left', fill='x', expand=True, padx=(0, 9))
        self._context_menu(self.name_entry)
        ttk.Button(row, text='Reset', command=self._reset_name).pack(side='left')
        row2 = ttk.Frame(options)
        row2.pack(fill='x', pady=(9, 0))
        ttk.Label(row2, text='Save to:', width=10).pack(side='left')
        save_entry = ttk.Entry(row2, textvariable=self.folder_value)
        save_entry.pack(side='left', fill='x', expand=True, padx=(0, 9))
        self._context_menu(save_entry)
        ttk.Button(row2, text='Browse…', command=self._browse).pack(side='left')
        row3 = ttk.Frame(options)
        row3.pack(fill='x', pady=(9, 0))
        ttk.Label(row3, text='Mode:', width=10).pack(side='left')
        ttk.Radiobutton(row3, text='Video', variable=self.media_mode, value='video', command=self._mode_changed).pack(side='left', padx=(0, 5))
        ttk.Radiobutton(row3, text='Audio', variable=self.media_mode, value='audio', command=self._mode_changed).pack(side='left', padx=(0, 12))
        self.format_box = ttk.Combobox(row3, state='readonly', textvariable=self.format_value, width=10)
        self.format_box.pack(side='left', padx=(0, 8))
        self.format_box.bind('<<ComboboxSelected>>', lambda _: (self._refresh_qualities(), self._sync_analysed_output()))
        self.quality_box = ttk.Combobox(row3, state='readonly', textvariable=self.quality_value, width=19)
        self.quality_box.pack(side='left', padx=(0, 8))
        self.download_button = ttk.Button(row3, text='Download', command=self._queue)
        self.download_button.pack(side='right')
        self.playlist_edit_button = ttk.Button(row3, textvariable=self.playlist_selection_text,
                                               command=self._open_playlist_selector)
        

        
        
        self.download_progress_panel = ttk.LabelFrame(self.download_tab, text='Analysed URL', padding=12)
        self.preview_thumbnail = ttk.Label(self.download_progress_panel, text='No Thumbnail', width=23, anchor='center')
        self.preview_thumbnail.pack(side='left', padx=(0, 16), anchor='nw')
        preview_details = ttk.Frame(self.download_progress_panel)
        preview_details.pack(side='left', fill='both', expand=True)
        ttk.Label(preview_details, textvariable=self.preview_title_value,
                  font=('Segoe UI', 11, 'bold'), wraplength=700).pack(anchor='w', fill='x')
        ttk.Label(preview_details, textvariable=self.preview_stage_value).pack(anchor='w', pady=(9, 0))
        ttk.Label(preview_details, textvariable=self.preview_counts_value,
                  foreground=UI_MUTED).pack(anchor='w', pady=(5, 0))
        self.preview_progress_row = ttk.Frame(preview_details)
        ttk.Progressbar(self.preview_progress_row, orient='horizontal', maximum=100,
                        variable=self.preview_progress_value,
                        style='Download.Horizontal.TProgressbar').pack(fill='x', pady=(9, 3))
        ttk.Label(self.preview_progress_row, textvariable=self.preview_progress_text,
                  foreground=UI_MUTED).pack(anchor='w')

        self.single_progress_panel = ttk.LabelFrame(self.download_tab, text='Download Progress', padding=12)
        self.single_thumbnail = ttk.Label(self.single_progress_panel, text='No Thumbnail',
                                          width=23, anchor='center')
        self.single_thumbnail.pack(side='left', padx=(0, 16), anchor='nw')
        single_details = ttk.Frame(self.single_progress_panel)
        single_details.pack(side='left', fill='both', expand=True)
        ttk.Label(single_details, textvariable=self.single_title_value,
                  font=('Segoe UI', 11, 'bold'), wraplength=700).pack(anchor='w', fill='x')
        ttk.Label(single_details, textvariable=self.single_stage_value).pack(anchor='w', pady=(9, 0))
        ttk.Label(single_details, textvariable=self.single_details_value,
                  foreground=UI_MUTED).pack(anchor='w', pady=(5, 0))
        ttk.Progressbar(single_details, orient='horizontal', maximum=100,
                        variable=self.single_progress_value,
                        style='Download.Horizontal.TProgressbar').pack(fill='x', pady=(9, 3))
        ttk.Label(single_details, textvariable=self.single_progress_text,
                  foreground=UI_MUTED).pack(anchor='w')

        self.queue_section = ttk.LabelFrame(self.download_tab, text='Active Queue', padding=10)
        self._build_table(self.queue_section, 'queue')
        self._build_table(self.history_tab, 'history')
        self._build_settings()
        ttk.Label(outer, textvariable=self.summary_value, foreground=UI_MUTED).pack(anchor='w', pady=(8, 2))
        ttk.Label(outer, textvariable=self.status_value, style='Footer.TLabel').pack(fill='x')

    def _sync_main_navigation(self, _event=None):
        
        try:
            selected = self.tabs.select()
        except tk.TclError:
            return
        for tab_id, button in self._nav_buttons.items():
            button.state(['selected'] if tab_id == selected else ['!selected'])

    def _build_table(self, parent, kind):
        controls = ttk.Frame(parent)
        controls.pack(fill='x', pady=(0, 9))
        if kind == 'queue':
            ttk.Button(controls, text='Cancel selected', command=self._cancel).pack(side='left', padx=(0, 6))
            ttk.Button(controls, text='Open folder', command=self._open_folder).pack(side='left')
        else:
            ttk.Label(controls, text='Search:').pack(side='left')
            ttk.Entry(controls, textvariable=self.history_search, width=25).pack(side='left', padx=6)
            ttk.Combobox(controls, textvariable=self.history_filter, width=12, state='readonly',
                         values=['All', 'Completed', 'Failed', 'Cancelled']).pack(side='left', padx=5)
            ttk.Button(controls, text='Retry selected', command=self._retry).pack(side='left', padx=5)
            ttk.Button(controls, text='Remove selected', command=self._remove_history_item).pack(side='left', padx=5)
            ttk.Button(controls, text='Clear history', command=self._clear_history).pack(side='left', padx=5)
            ttk.Button(controls, text='Export CSV', command=self._export_history).pack(side='left', padx=5)
        ttk.Button(controls, text='Refresh', command=self._refresh_queue).pack(side='right')
        ttk.Button(controls, text='Deselect all', command=lambda k=kind: self._tree_bulk(k, False)).pack(side='right', padx=4)
        ttk.Button(controls, text='Select all', command=lambda k=kind: self._tree_bulk(k, True)).pack(side='right', padx=4)
        table_frame = ttk.Frame(parent)
        table_frame.pack(fill='both', expand=True)
        cols = ('pick', 'title', 'date', 'status', 'stage', 'progress', 'format', 'folder') if kind == 'history' else ('pick', 'title', 'status', 'stage', 'progress', 'format', 'folder')
        tree = ttk.Treeview(table_frame, columns=cols, show='tree headings', height=16, selectmode='extended')
        tree.heading('#0', text='Art')
        tree.column('#0', width=110, minwidth=105, stretch=False)
        column_widths = [('pick', 64), ('title', 255)]
        if kind == 'history':
            column_widths.append(('date', 155))
        column_widths += [('status', 96), ('stage', 103), ('progress', 77), ('format', 72), ('folder', 280)]
        for name, width in column_widths:
            if kind == 'history':
                label = 'Select' if name == 'pick' else name.title()
                tree.heading(name, text=label, command=lambda c=name: self._sort_history(c))
            else:
                tree.heading(name, text='Select' if name == 'pick' else name.title())
            tree.column(name, width=width, minwidth=65, stretch=name in ('title', 'folder'))
        horizontal = ttk.Scrollbar(table_frame, orient='horizontal', command=tree.xview)
        horizontal.pack(side='bottom', fill='x')
        tree.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        scrollbar.pack(side='right', fill='y')
        tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        tree.tag_configure('failed', foreground=UI_BAD)
        tree.tag_configure('completed', foreground=UI_GOOD)
        tree.bind('<<TreeviewSelect>>', lambda event, which=kind: self._select_item(event, which))
        tree.bind('<Button-1>', lambda event, which=kind: self._tree_click(event, which))
        if kind == 'queue':
            self.tree = tree
        else:
            self.history_tree = tree

    HISTORY_SORT_COLUMNS = ('pick', 'title', 'date', 'status', 'stage', 'progress', 'format', 'folder')

    def _sort_history(self, column):
        if column not in self.HISTORY_SORT_COLUMNS:
            return
        if self.history_sort_column == column:
            self.history_sort_descending = not self.history_sort_descending
        else:
            self.history_sort_column = column
            self.history_sort_descending = column == 'date'
        self._refresh_queue()

    @staticmethod
    def _history_timestamp(record):
        raw = str(record.get('completed_at') or record.get('failed_at') or
                  record.get('cancelled_at') or record.get('created_at') or '')
        try:
            return datetime.fromisoformat(raw.replace('Z', '+00:00')).timestamp()
        except (ValueError, TypeError, OverflowError):
            return 0.0

    @staticmethod
    def _history_folder(record, job):
        file_path = str(record.get('file_path') or '').strip()
        if file_path:
            return str(Path(file_path).parent)
        return str(job.get('save_path') or '')

    def _history_sort_key(self, item, jobs_by_item):
        ident, record = item
        column = self.history_sort_column
        if column == 'date':
            return (self._history_timestamp(record), str(ident))
        if column == 'pick':
            return (ident in self.selected_rows['history'], str(ident))
        if column == 'progress':
            value = record.get('progress_percent')
            try:
                return (float(value) if value is not None else -1.0, str(ident))
            except (ValueError, TypeError):
                return (-1.0, str(ident))
        job = jobs_by_item.get(ident) or {}
        if column == 'title':
            value = record.get('title') or 'Download'
        elif column == 'status':
            value = record.get('status') or ''
        elif column == 'stage':
            value = record.get('stage') or ''
        elif column == 'folder':
            value = self._history_folder(record, job)
        else:
            value = job.get('target_format') or ''
        return (str(value).casefold(), str(ident))

    def _update_history_heading(self):
        for column in self.HISTORY_SORT_COLUMNS:
            label = 'Select' if column == 'pick' else column.title()
            if column == self.history_sort_column:
                label += ' ▼' if self.history_sort_descending else ' ▲'
            self.history_tree.heading(column, text=label)

    @staticmethod
    def _installed_binary_location(value):

        command = str(value or '').strip()
        if not command or command.lower() == 'default':
            return 'Not detected'
        path = Path(command).expanduser()
        if path.is_file():
            return str(path.resolve())
        found = shutil.which(command)
        if found:
            return str(Path(found).resolve())
        return 'Not detected (configured path: ' + command + ')'

    @staticmethod
    def _installed_python_location(module):

        try:
            spec = importlib.util.find_spec(module)
            if spec is None:
                return 'Not installed for this Python interpreter'
            if spec.submodule_search_locations:
                return str(Path(next(iter(spec.submodule_search_locations))).resolve())
            if spec.origin and spec.origin not in ('built-in', 'frozen'):
                return str(Path(spec.origin).resolve().parent)
            return 'Bundled in this Python interpreter'
        except (ImportError, AttributeError, OSError, ValueError):
            return 'Not installed for this Python interpreter'

    def _refresh_dependency_locations(self):


        from YouSnipeSettings import get_effective_settings
        runtime = get_effective_settings().get('runtime', {})
        raw_js = str(runtime.get('ytdlpJsRuntime') or '').strip()
        js_engine, separator, js_command = raw_js.partition(':')
        if not separator or js_engine.casefold() not in ('deno', 'node', 'bun', 'quickjs'):
            js_command = raw_js
        display = {
            'Yt-dlp': self._installed_binary_location(runtime.get('ytdlpBin')),
            'Ffmpeg': self._installed_binary_location(runtime.get('ffmpegPath')),
            'Ffprobe': self._installed_binary_location(runtime.get('ffprobePath')),
            'JavaScript Runtime': self._installed_binary_location(js_command),
        }
        if not getattr(sys, 'frozen', False):
            display.update({
                'Pillow': self._installed_python_location('PIL'),
                'Websockets': self._installed_python_location('websockets'),
            })
        for name, location in display.items():
            self.installed_dependency_vars[name].set(location)


        engine = js_engine.casefold()
        if engine not in ('deno', 'node', 'bun', 'quickjs'):
            engine = 'deno'
        engine_label = 'QuickJS' if engine == 'quickjs' else engine.capitalize()
        self.dependency_js_label.set(f'{engine_label} (JavaScript Runtime):')

    def _build_settings(self):
        canvas = tk.Canvas(self.settings_tab, bg=UI_BG, highlightthickness=0)
        scroll = ttk.Scrollbar(self.settings_tab, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(canvas, padding=(0, 0, 12, 0))
        window = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))

        def scroll_wheel(event):
            canvas.yview_scroll(-int(event.delta / 120) if event.delta else 0, 'units')

        canvas.bind('<Enter>', lambda _: canvas.bind_all('<MouseWheel>', scroll_wheel))
        canvas.bind('<Leave>', lambda _: canvas.unbind_all('<MouseWheel>'))
        self.setting_vars = {}
        cfg = self.settings

        storage = ttk.LabelFrame(content, text='Save Locations', padding=10)
        storage.pack(fill='x', pady=(0, 9))
        for label, key in [
            ('Main Download Folder:', 'defaultSavePath'),
            ('Video Folder:', 'videoSavePath'),
            ('Audio Folder:', 'audioSavePath'),
        ]:
            row = ttk.Frame(storage)
            row.pack(fill='x', pady=3)
            ttk.Label(row, text=label, width=37).pack(side='left')
            var = tk.StringVar(value=str(cfg['storage'].get(key, '') or ''))
            self.setting_vars[('storage', key)] = var
            ttk.Entry(row, textvariable=var).pack(side='left', fill='x', expand=True)
        ttk.Label(storage,
                  text='Leave Video Folder and Audio Folder blank to use Main Download Folder.',
                  foreground=UI_MUTED).pack(anchor='w', pady=(6, 0))

        
        dl = ttk.LabelFrame(content, text='Download Defaults', padding=10)
        dl.pack(fill='x', pady=(0, 9))
        
        
        self.default_mode_var = tk.StringVar(value=cfg['downloadDefaults']['defaultMediaMode'].capitalize())
        self.default_video_var = tk.StringVar(value=cfg['downloadDefaults']['defaultVideoFormat'])
        self.default_audio_var = tk.StringVar(value=cfg['downloadDefaults']['defaultAudioFormat'])
        for label, variable, values in [
            ('Default Mode:', self.default_mode_var, ['Video', 'Audio']),
            ('Default Video Format:', self.default_video_var, ['MP4', 'MKV', 'WEBM', 'MOV', 'AVI', 'WMV', 'FLV']),
            ('Default Audio Format:', self.default_audio_var, ['MP3', 'M4A', 'MP4', 'MPA', 'WAV', 'AAC', 'FLAC', 'OGG', 'ALAC', 'WMA']),
        ]:
            row = ttk.Frame(dl)
            row.pack(fill='x', pady=3)
            ttk.Label(row, text=label, width=37).pack(side='left')
            ttk.Combobox(row, textvariable=variable, values=values, state='readonly', width=17).pack(side='left')

        self.overwrite_existing = tk.BooleanVar(value=cfg['downloadDefaults']['overwriteExisting'])
        ttk.Checkbutton(dl, text='Overwrite Existing Downloads',
                        variable=self.overwrite_existing).pack(anchor='w', pady=(7, 2))
        ttk.Label(dl, text='When disabled, a numbered filename is used instead of replacing a file.',
                  foreground=UI_MUTED).pack(anchor='w', pady=(0, 4))

        self.video_suffix = tk.BooleanVar(value=cfg['downloadDefaults']['includeVideoQualityInFileName'])
        self.audio_suffix = tk.BooleanVar(value=cfg['downloadDefaults']['includeAudioQualityInFileName'])
        ttk.Checkbutton(dl, text='Suffix Video Quality (e.g. [2160p])',
                        variable=self.video_suffix).pack(anchor='w', pady=(7, 2))
        ttk.Checkbutton(dl, text='Suffix Audio Quality (e.g. [256kbps])',
                        variable=self.audio_suffix).pack(anchor='w', pady=(0, 7))

        row = ttk.Frame(dl)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text='Simultaneous Downloads:', width=37).pack(side='left')
        self.concurrency = tk.StringVar(value=str(cfg['queue']['maxConcurrentDownloads']))
        ttk.Combobox(row, textvariable=self.concurrency, state='readonly', width=8,
                     values=['1', '2', '3', '4', '5', '6', '8']).pack(side='left')
        self.keep_failed = tk.BooleanVar(value=cfg['history']['keepFailedDownloadsInHistory'])
        ttk.Checkbutton(dl, text='Include Failed Downloads In History',
                        variable=self.keep_failed).pack(anchor='w', pady=(7, 6))

        retention = cfg['history']['historyRetention']
        value_to_label = {
            ('day', 30): '30 Days', ('day', 90): '90 Days',
            ('year', 1): '1 Year', ('year', 2): '2 Years',
        }
        if retention == 'never':
            retention_label = 'Keep Forever'
        elif isinstance(retention, dict):
            retention_label = value_to_label.get(
                (retention.get('unit'), retention.get('value')), 'Custom (Unchanged)')
        else:
            retention_label = 'Custom (Unchanged)'
        self.retention = tk.StringVar(value=retention_label)
        row = ttk.Frame(dl)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text='History Retention:', width=37).pack(side='left')
        ttk.Combobox(row, textvariable=self.retention, state='readonly', width=23,
                     values=['Keep Forever', '30 Days', '90 Days', '1 Year', '2 Years',
                             'Custom (Unchanged)']).pack(side='left')

        
        playlist_options = ttk.LabelFrame(content, text='Playlist Options', padding=10)
        playlist_options.pack(fill='x', pady=(0, 9))
        self.playlist_vars = {}
        for label, key in [
            ('Create Folder For Each Playlist', 'createPlaylistFolder'),
            ('Include Playlist Index In Metadata', 'addPlaylistIndexToMetadata'),
            ('Prefix Download Filenames With Playlist Index', 'addPlaylistIndexToFileName'),
        ]:
            flag = tk.BooleanVar(value=cfg['playlist'][key])
            self.playlist_vars[key] = flag
            ttk.Checkbutton(playlist_options, text=label, variable=flag).pack(anchor='w', pady=3)

        limits = ttk.LabelFrame(content, text='Download Limits', padding=10)
        limits.pack(fill='x', pady=(0, 9))
        limit_cfg = cfg['limits']
        current_speed = limit_cfg.get('maxDownloadSpeedMBPerSecond', 'unlimited')
        self.speed_limit_var = tk.StringVar(value='Unlimited' if current_speed == 'unlimited' else str(current_speed))
        row = ttk.Frame(limits)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text='Speed Limit (MB/s per download):', width=37).pack(side='left')
        ttk.Entry(row, textvariable=self.speed_limit_var, width=14).pack(side='left')
        ttk.Label(row, text='Unlimited or a number greater than zero', foreground=UI_MUTED).pack(side='left', padx=8)
        cap = limit_cfg.get('dataUsageCap', {})
        self.cap_enabled = tk.BooleanVar(value=bool(cap.get('enabled')))
        ttk.Checkbutton(limits, text='Enable Data Usage Cap', variable=self.cap_enabled).pack(anchor='w', pady=(8, 5))
        row = ttk.Frame(limits)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text='Cap Amount:', width=37).pack(side='left')
        self.cap_amount = tk.StringVar(value=str(cap.get('amount', 20)))
        ttk.Entry(row, textvariable=self.cap_amount, width=12).pack(side='left')
        self.cap_unit = tk.StringVar(value=str(cap.get('unit', 'GB')))
        ttk.Combobox(row, textvariable=self.cap_unit, state='readonly', width=6,
                     values=['MB', 'GB']).pack(side='left', padx=8)
        row = ttk.Frame(limits)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text='Reset Interval:', width=37).pack(side='left')
        period = cap.get('period') or {}
        self.cap_period_value = tk.StringVar(value=str(period.get('value', 1)))
        ttk.Entry(row, textvariable=self.cap_period_value, width=12).pack(side='left')
        self.cap_period_unit = tk.StringVar(value=str(period.get('unit', 'month')))
        ttk.Combobox(row, textvariable=self.cap_period_unit, state='readonly', width=12,
                     values=['hour', 'day', 'week', 'month', 'year']).pack(side='left', padx=8)
        ttk.Label(limits, text='Software data cap is approximate - speed limit applies per download.',
                  foreground=UI_MUTED).pack(anchor='w', pady=(6, 0))

        server = ttk.LabelFrame(content, text='Server', padding=10)
        server.pack(fill='x', pady=(0, 9))
        row = ttk.Frame(server)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text='Local WebSocket Server Port:', width=37).pack(side='left')
        self.server_port = tk.StringVar(value=str(cfg['server']['port']))
        ttk.Entry(row, textvariable=self.server_port, width=12).pack(side='left')
        ttk.Label(server, text='Configure custom WebSocket server port',
                  foreground=UI_MUTED).pack(anchor='w', pady=(5, 0))

        
        ai = ttk.LabelFrame(content, text='Ai Tool', padding=10)
        ai.pack(fill='x', pady=(0, 9))
        self.ai_vars = {}
        for label, key in [
            ('Enable AITool', 'enabled'),
            ('Enable Downloads', 'enableDownloads'),
            ('Enable History Removal', 'enableHistoryRemoval'),
            ('Enable Settings Updates', 'enableSettingsUpdates'),
        ]:
            flag = tk.BooleanVar(value=cfg['aiTool'][key])
            self.ai_vars[key] = flag
            ttk.Checkbutton(ai, text=label, variable=flag).pack(anchor='w', pady=2)
        ttk.Label(ai, text="AI Tool is a development feature — please see YouSnipe's documentation for more information.",
                  foreground=UI_MUTED).pack(anchor='w', pady=(5, 0))

        updates = ttk.LabelFrame(content, text='Updates', padding=10)
        updates.pack(fill='x', pady=(0, 9))
        row = ttk.Frame(updates)
        row.pack(fill='x')
        self._update_check_button = ttk.Button(row, text='Check Updates', command=self._check_updates)
        self._update_check_button.pack(side='left', padx=(0, 8))
        self._update_button = ttk.Button(row, text='Update', command=self._start_update)


        deps = ttk.LabelFrame(content, text='Installed Dependencies', padding=10)
        deps.pack(fill='x', pady=(0, 9))
        self.installed_dependency_vars = {}
        self.dependency_js_label = tk.StringVar(value='Deno (JavaScript Runtime):')
        names = ['Yt-dlp', 'Ffmpeg', 'Ffprobe', 'JavaScript Runtime']
        if not getattr(sys, 'frozen', False):
            names.extend(('Pillow', 'Websockets'))
        for name in names:
            row = ttk.Frame(deps)
            row.pack(fill='x', pady=3)
            if name == 'JavaScript Runtime':
                ttk.Label(row, textvariable=self.dependency_js_label, width=28).pack(side='left')
            else:
                ttk.Label(row, text=name + ':', width=28).pack(side='left')
            location = tk.StringVar(value='Checking...')
            self.installed_dependency_vars[name] = location
            ttk.Entry(row, textvariable=location, state='readonly').pack(
                side='left', fill='x', expand=True)
        self._refresh_dependency_locations()

        appearance = ttk.LabelFrame(content, text='Appearance', padding=10)
        appearance.pack(fill='x', pady=(0, 9))
        row = ttk.Frame(appearance)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text='Progress Bar Color:', width=37).pack(side='left')
        self.accent_preset = tk.StringVar(value='Default' if self.accent == DEFAULT_ACCENT else 'Custom')
        self.accent_hex = tk.StringVar(value=self.accent)
        self._last_custom_accent = self.accent if self.accent != DEFAULT_ACCENT else DEFAULT_ACCENT
        picker = ttk.Combobox(row, textvariable=self.accent_preset, state='readonly', width=20,
                              values=['Default', 'Custom'])
        picker.pack(side='left')
        ttk.Label(row, text='HEX:').pack(side='left', padx=(12, 5))
        ttk.Entry(row, textvariable=self.accent_hex, width=11).pack(side='left')
        self._changing_accent_controls = False
        def choose_accent(*_):
            if self._changing_accent_controls:
                return
            self._changing_accent_controls = True
            try:
                if self.accent_preset.get() == 'Default':
                    current = self.accent_hex.get().strip()
                    if current != DEFAULT_ACCENT:
                        self._last_custom_accent = current
                    self.accent_hex.set(DEFAULT_ACCENT)
                else:
                    self.accent_hex.set(self._last_custom_accent)
            finally:
                self._changing_accent_controls = False
        self.accent_preset.trace_add('write', choose_accent)
        def custom_accent(*_):
            if self._changing_accent_controls:
                return
            self._changing_accent_controls = True
            try:
                self.accent_preset.set('Custom')
                self._last_custom_accent = self.accent_hex.get().strip()
            finally:
                self._changing_accent_controls = False
        self.accent_hex.trace_add('write', custom_accent)

        ttk.Button(content, text='Save Settings',
                   command=self._save_settings).pack(anchor='e', pady=10)

    def _apply_accent(self):
        style = ttk.Style(self)
        style.configure('CompactStatus.TLabel', foreground=self.accent)
        style.configure('Accent.TButton', foreground=self.accent, bordercolor=self.accent)
        style.map('Accent.TButton', foreground=[('active', self.accent)])
        style.configure('Download.Horizontal.TProgressbar', background=self.accent,
                        lightcolor=self.accent, darkcolor=self.accent)

    def _save_settings(self):
        try:
            changes = {'application': {'accentColor': DEFAULT_ACCENT if self.accent_preset.get() == 'Default' else self.accent_hex.get().strip()},
                       'storage': {key: self.setting_vars['storage', key].get().strip()
                                   for key in ('defaultSavePath', 'videoSavePath', 'audioSavePath')},
                       'queue': {'maxConcurrentDownloads': int(self.concurrency.get())},
                       'server': {'port': int(self.server_port.get()), 'host': '127.0.0.1'},
                       'aiTool': {key: flag.get() for key, flag in self.ai_vars.items()},
                       'downloadDefaults': {'defaultMediaMode': self.default_mode_var.get().strip().lower(),
                                            'defaultVideoFormat': self.default_video_var.get(),
                                            'defaultAudioFormat': self.default_audio_var.get(),
                                            'overwriteExisting': self.overwrite_existing.get(),
                                            'includeVideoQualityInFileName': self.video_suffix.get(),
                                            'includeAudioQualityInFileName': self.audio_suffix.get()},
                       'history': {'keepFailedDownloadsInHistory': self.keep_failed.get()},
                       'playlist': {key: flag.get() for key, flag in self.playlist_vars.items()},
                       'limits': {'maxDownloadSpeedMBPerSecond': self.speed_limit_var.get().strip(),
                                  'dataUsageCap': {'enabled': self.cap_enabled.get(),
                                                   'amount': float(self.cap_amount.get()),
                                                   'unit': self.cap_unit.get(),
                                                   'period': {'value': int(self.cap_period_value.get()),
                                                              'unit': self.cap_period_unit.get()}}}}
            rule = self.retention.get()
            retention_rules = {'Keep Forever': 'never',
                               '30 Days': {'mode':'interval', 'value':30, 'unit':'day'},
                               '90 Days': {'mode':'interval', 'value':90, 'unit':'day'},
                               '1 Year': {'mode':'interval', 'value':1, 'unit':'year'},
                               '2 Years': {'mode':'interval', 'value':2, 'unit':'year'}}
            if rule in retention_rules:
                changes['history']['historyRetention'] = retention_rules[rule]
            if not changes['storage']['defaultSavePath']:
                messagebox.showwarning('Invalid path', 'Main download folder cannot be blank.')
                return
            speed = changes['limits']['maxDownloadSpeedMBPerSecond']
            if speed.casefold() != 'unlimited' and float(speed) <= 0:
                raise ValueError('Speed limit must be Unlimited or a number greater than zero')
            if changes['limits']['dataUsageCap']['amount'] <= 0 or changes['limits']['dataUsageCap']['period']['value'] <= 0:
                raise ValueError('Data cap amount and reset interval must be greater than zero')
            if not 1 <= int(self.server_port.get()) <= 65535:
                raise ValueError('Server port must be between 1 and 65535')
            self.settings = update_settings(changes)
            self.accent = self.settings['application']['accentColor']
            self._apply_accent()
            self._last_auto_folder = get_save_path(self.media_mode.get(), self.settings)
            self.folder_value.set(self._last_auto_folder)
            self.status_value.set('Settings saved. Changes apply to newly queued downloads.')
        except Exception as exc:
            messagebox.showerror('Settings', str(exc))

    def _check_updates(self):
        self._verified_update = None
        self._update_button.pack_forget()
        self._update_check_button.configure(state='disabled')
        self.status_value.set('Checking ProjectHomelab release manifest...')
        async def execute():
            return await asyncio.to_thread(check_update)
        self._enqueue_future(execute(), self._show_update_check)

    def _show_update_check(self, result, error):
        self._update_check_button.configure(state='normal')
        self._verified_update = None
        self._update_button.pack_forget()
        if error:
            self.status_value.set(f'Update check failed: {error}')
            return
        if result['updateAvailable']:
            if getattr(sys, 'frozen', False):
                self._verified_update = result
                self._update_button.pack(side='left')
            self.status_value.set('Newer release available')
        else:
            self.status_value.set('No newer release found')
        heading = 'Update Available' if result['updateAvailable'] else 'YouSnipe Is Up to Date'
        messagebox.showinfo('YouSnipe Update',
            f'{heading}\n'
            f'Installed: {result["currentVersion"]}\n'
            f'Latest: {result["releaseVersion"]}')

    def _start_update(self):
        if not self._verified_update or not self._verified_update.get('updateAvailable'):
            messagebox.showinfo('YouSnipe update', 'Check for an available update first.')
            return
        if not getattr(sys, 'frozen', False):
            messagebox.showinfo('YouSnipe update', 'Automatic updates require a packaged YouSnipe build. Source builds can check for updates.')
            return
        active = [record for record in self.item_rows.values() if record.get('status') in ('queued', 'running')]
        if active:
            messagebox.showwarning('YouSnipe update', 'Please finish or cancel active downloads before updating.')
            return
        if not messagebox.askyesno('Update YouSnipe', f'Install Latest Version {self._verified_update["releaseVersion"]}?'):
            return
        self.status_value.set('Checking update and preparing verified updater...')
        async def execute():
            return await asyncio.to_thread(start_external_update, 'gui')
        self._enqueue_future(execute(), self._on_update_started)

    def _on_update_started(self, result, error):
        if error:
            self.status_value.set(f'Update failed: {error}')
            messagebox.showerror('YouSnipe update', str(error))
            return
        self.status_value.set('External updater started. Closing YouSnipe...')
        self._close()

    def _mode_changed(self):
        if self.folder_value.get() == self._last_auto_folder:
            self._last_auto_folder = get_save_path(self.media_mode.get(), self.settings)
            self.folder_value.set(self._last_auto_folder)
        self.format_value.set(self.settings['downloadDefaults'][
            'defaultAudioFormat' if self.media_mode.get() == 'audio' else 'defaultVideoFormat'])
        self._update_formats()

    def _urls(self):
        
        url = self.url_value.get().strip()
        return [url] if url else []

    def _url_changed(self):
        self.quality_value.set('Highest')
        self._clear_analysis_state()

    def _clear_analysis_state(self):
        
        self._analysis_request_token += 1
        self._analysis_in_progress = False
        self.download_button.state(['!disabled'])
        self._close_playlist_dialog()
        self.metadata = None
        self._analysed_url = ""
        self._original_title = ""
        self.name_value.set("")
        self.selected_rows['playlist'].clear()
        self.playlist_edit_button.pack_forget()
        self.playlist_selection_text.set('Select Playlist Items')
        self._preview_download_item_ids = ()
        self._hide_download_preview()
        self._refresh_qualities()

    def _hide_download_preview(self):
        self.preview_visible = False
        self.preview_title_value.set('')
        self.preview_stage_value.set('')
        self.preview_counts_value.set('')
        self.preview_progress_value.set(0)
        self.preview_progress_text.set('')
        self.preview_progress_row.pack_forget()
        self.preview_thumbnail.configure(image='', text='No Thumbnail')
        self.thumbnail_images.pop('download-preview', None)
        self.download_progress_panel.pack_forget()

    def _selected_output_description(self):
        mode = self.media_mode.get().lower()
        selected_format = self.format_value.get().upper()
        quality = self._quality_raw()
        data = (self.metadata or {}).get(mode) or {}
        if str(quality).casefold() == 'highest':
            native = str(data.get('nativeQuality') or '').strip()
            if native and native.casefold() != 'highest':
                unit = 'p' if mode == 'video' else ' kbps'
                quality = f'{native}{unit}'
            else:
                quality = 'Highest (source quality unknown)'
        elif str(quality).upper() == 'LOSSLESS':
            quality = 'Lossless output'
        else:
            quality = f'{quality}{"p" if mode == "video" else " kbps"}'
        return f'Output: {mode.title()} · {selected_format} · {quality}'

    def _sync_analysed_output(self):
        if not self.preview_visible or not self.metadata or self._preview_download_item_ids:
            return
        if (self.metadata or {}).get('playlist'):
            return
        self.preview_counts_value.set(self._selected_output_description())

    def _show_download_preview(self, url, title, thumbnail):
        self.preview_visible = True
        self.preview_title_value.set(title or url)
        self.preview_stage_value.set('Ready to download')
        self.preview_progress_value.set(0)
        self.preview_progress_text.set('')
        self.preview_progress_row.pack_forget()
        info = self.metadata or {}
        if info.get('playlist'):
            entries = info['playlist'].get('items') or []
            self.preview_counts_value.set(f'{len(entries)} playlist items · Select items before downloading')
        else:
            self.preview_counts_value.set(self._selected_output_description())
        token = self._analysis_request_token
        self.preview_thumbnail.configure(image='', text='No Thumbnail')
        self.thumbnail_images.pop('download-preview', None)
        self._request_thumbnail(thumbnail, lambda photo, generation=token:
            self._show_thumbnail(self.preview_thumbnail, photo, 'download-preview')
            if self.preview_visible and generation == self._analysis_request_token else None,
            size=(160, 90))
        self._update_download_preview(self.item_rows)

    def _single_download_thumbnail(self, record):
        try:
            stored = json.loads(record.get('raw_metadata_json') or '{}')
        except (TypeError, ValueError):
            stored = {}
        request = stored.get('request') if isinstance(stored, dict) else {}
        request = request if isinstance(request, dict) else {}
        thumbnail = str(request.get('thumbnail') or stored.get('thumbnail') or '')
        if not thumbnail and str(record.get('item_uuid') or '') in self._preview_download_item_ids:
            thumbnail = str((self.metadata or {}).get('thumbnail') or '')
        return thumbnail

    def _show_single_download(self, record):
        identifier = str(record.get('item_uuid') or '')
        thumbnail = self._single_download_thumbnail(record)
        if (identifier, thumbnail) != self._single_thumbnail_source:
            self._single_thumbnail_source = (identifier, thumbnail)
            self.single_thumbnail.configure(image='', text='No Thumbnail')
            self.thumbnail_images.pop('download-single', None)
            self._request_thumbnail(thumbnail, lambda photo, key=(identifier, thumbnail):
                self._show_thumbnail(self.single_thumbnail, photo, 'download-single')
                if self._single_thumbnail_source == key else None, size=(160, 90))
        self._single_displayed_item_id = identifier
        self.single_title_value.set(record.get('title') or self.preview_title_value.get() or 'Download')
        status = str(record.get('status') or 'queued').lower()
        stage = _display_stage(record.get('stage'))
        self.single_stage_value.set(stage if status == 'running' and stage.casefold() not in ('running', 'queued') else ('Downloading' if status == 'running' else 'Queued'))
        try:
            percent = max(0.0, min(100.0, float(record.get('progress_percent') or 0)))
        except (TypeError, ValueError):
            percent = 0.0
        self.single_progress_value.set(percent)
        suffix = f' · {stage}' if stage and stage.casefold() not in ('running', 'queued') else ''
        self.single_progress_text.set(f'{percent:.0f}%{suffix}' if status == 'running' else 'Waiting to start')
        details = []
        try:
            stored = json.loads(record.get('raw_metadata_json') or '{}')
            request = stored.get('request') if isinstance(stored, dict) else {}
            request = request if isinstance(request, dict) else {}
        except (TypeError, ValueError):
            request = {}
        if request.get('format'):
            details.append(str(request['format']).upper())
        if request.get('quality'):
            details.append(str(request['quality']))
        speed = record.get('speed_bytes_per_second')
        if status == 'running' and speed:
            try:
                details.append(f'{float(speed) / 1048576:.1f} MB/s')
            except (TypeError, ValueError):
                pass
        self.single_details_value.set(' · '.join(details))
        if not self.single_progress_panel.winfo_manager():
            self.single_progress_panel.pack(fill='x', pady=(10, 0))

    def _requested_output_description(self, record):
        try:
            stored = json.loads(record.get('raw_metadata_json') or '{}')
        except (TypeError, ValueError):
            stored = {}
        request = stored.get('request') if isinstance(stored, dict) else {}
        request = request if isinstance(request, dict) else {}
        mode = str(request.get('mediaMode') or record.get('target_media_mode') or '').strip().lower()
        selected_format = str(request.get('format') or record.get('target_format') or '').strip().upper()
        selected_quality = str(request.get('quality') or record.get('target_quality') or '').strip()
        if mode not in ('audio', 'video'):
            mode = 'audio' if selected_format in ('MP3', 'M4A', 'MPA', 'WAV', 'AAC', 'FLAC', 'OGG', 'ALAC', 'WMA') else 'video'
        parts = [mode.title()]
        if selected_format:
            parts.append(selected_format)
        if selected_quality:
            if selected_quality.casefold() == 'highest':
                data = (self.metadata or {}).get(mode) or {}
                native = str(data.get('nativeQuality') or '').strip()
                if native and native.casefold() != 'highest':
                    selected_quality = f'{native}{"p" if mode == "video" else " kbps"}'
                else:
                    selected_quality = 'Highest'
            elif selected_quality.upper() == 'LOSSLESS':
                selected_quality = 'Lossless output'
            elif selected_quality.isdigit():
                selected_quality = f'{selected_quality}{"p" if mode == "video" else " kbps"}'
            parts.append(selected_quality)
        return 'Output: ' + ' · '.join(parts)

    def _update_preview_result(self, records):
        ids = self._preview_download_item_ids
        if not ids or not self.preview_visible:
            return
        selected = [records[identifier] for identifier in ids if identifier in records]
        if len(selected) != len(ids):
            return
        statuses = [str(row.get('status') or '').lower() for row in selected]
        terminal = {'completed', 'failed', 'cancelled'}
        if not all(status in terminal for status in statuses):
            return
        output_description = self._requested_output_description(selected[0])
        if len(selected) > 1:
            output_description += f' · {len(selected)} items'
        self.preview_counts_value.set(output_description)
        completed = statuses.count('completed')
        if completed == len(selected):
            self.preview_stage_value.set('Completed' if len(selected) == 1 else f'Completed · {completed} items')
            self.preview_progress_value.set(100)
            self.preview_progress_text.set('100% · Download complete' if len(selected) == 1
                                           else f'{completed} of {len(selected)} downloads complete')
        elif completed:
            self.preview_stage_value.set('Partially completed')
            self.preview_progress_value.set(100 * completed / len(selected))
            self.preview_progress_text.set(f'{completed} of {len(selected)} downloads completed')
        elif all(status == 'cancelled' for status in statuses):
            self.preview_stage_value.set('Cancelled')
            self.preview_progress_value.set(0)
            self.preview_progress_text.set('Download cancelled')
        else:
            self.preview_stage_value.set('Failed')
            self.preview_progress_value.set(0)
            self.preview_progress_text.set(str(next((row.get('error_message') for row in selected
                                                     if row.get('error_message')), 'Download failed'))[:160])
        if not self.preview_progress_row.winfo_manager():
            self.preview_progress_row.pack(fill='x')

    def _update_download_preview(self, records):
        active = [row for row in records.values()
                  if str(row.get('status') or '').lower() in ('queued', 'running')]
        if len(active) == 1:
            self.queue_section.pack_forget()
            self.download_progress_panel.pack_forget()
            self._show_single_download(active[0])
        elif len(active) > 1:
            self.single_progress_panel.pack_forget()
            self.download_progress_panel.pack_forget()
            if not self.queue_section.winfo_manager():
                self.queue_section.pack(fill='both', expand=True, pady=(10, 0))
        else:
            self.queue_section.pack_forget()
            self.single_progress_panel.pack_forget()
            self._single_displayed_item_id = None
            self._single_thumbnail_source = None
            self._update_preview_result(records)
            if self.preview_visible and self.metadata and self._analysed_url:
                if not self.download_progress_panel.winfo_manager():
                    self.download_progress_panel.pack(fill='x', pady=(10, 0))
            else:
                self.download_progress_panel.pack_forget()
        for row in records.values():
            if (str(row.get('error_code') or '') == 'YOUTUBE_ACCESS_RESTRICTED'
                and str(row.get('status') or '').lower() == 'failed'):
                item_key = str(row.get('item_uuid') or '')
                if item_key and item_key not in self._reported_failure_ids:
                    self._reported_failure_ids.add(item_key)
                    messagebox.showwarning('YouSnipe - YouTube Access Restricted',
                        str(row.get('error_message') or 'YouTube may temporarily restrict this network.'))

    def _update_formats(self):
        if self.media_mode.get() == "audio":
            formats = ["MP3", "M4A", "MP4", "MPA", "WAV", "AAC", "FLAC", "OGG", "ALAC", "WMA"]
            choices = ["Highest", "320", "256", "192", "160", "128", "96", "64", "LOSSLESS"]
            default = self.settings['downloadDefaults']['defaultAudioFormat']
        else:
            formats = ["MP4", "MKV", "WEBM", "MOV", "AVI", "WMV", "FLV"]
            choices = ["Highest", "4320", "2160", "1440", "1080", "720", "480", "360", "240", "144"]
            default = self.settings['downloadDefaults']['defaultVideoFormat']
        self.format_box["values"] = formats
        self.quality_box["values"] = choices
        if self.format_value.get() not in formats:
            self.format_value.set(default)
        self._refresh_qualities()

    def _browse(self):
        directory = filedialog.askdirectory(initialdir=self.folder_value.get() if Path(self.folder_value.get()).exists() else str(Path.home()))
        if directory:
            self.folder_value.set(directory)

    def _enqueue_future(self, coro, callback):
        self.pending.append((self.backend.call(coro), callback))

    @staticmethod
    def _record_gui_error(message, exc):
        
        from YouSnipePaths import appdata_subdirectory
        try:
            logs = appdata_subdirectory('Logs')
            logs.mkdir(parents=True, exist_ok=True)
            with (logs / 'YouSnipeGUI.log').open('a', encoding='utf-8') as stream:
                stream.write(f'\n{message}\n')
                stream.write(''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        except OSError:
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)

    def _poll_futures(self):
        if self.shutting_down:
            return
        waiting = []
        for future, callback in self.pending:
            if future.done():
                try:
                    result = future.result()
                except Exception as exc:
                    self._record_gui_error('Backend task failed', exc)
                    try:
                        callback(None, exc)
                    except Exception as callback_error:
                        self._record_gui_error('Error displaying a backend failure', callback_error)
                        messagebox.showerror('GUI Error', f'Could not display the failure: {callback_error}')
                else:
                    try:
                        callback(result, None)
                    except Exception as exc:
                        
                        
                        self._record_gui_error('Error displaying backend result', exc)
                        messagebox.showerror('GUI Error', f'Error displaying results: {exc}')
            else:
                waiting.append((future, callback))
        self.pending = waiting
        self.after(120, self._poll_futures)

    def _analyse(self, queue_after=False):
        urls = self._urls()
        if not urls:
            messagebox.showwarning('Missing URL', 'Paste one URL first.')
            return
        url = urls[0]
        if any(ch.isspace() for ch in url):
            messagebox.showwarning('Invalid URL', 'Enter one URL only (not multiple URLs).')
            return
        if self._analysis_in_progress:
            return
        requested_name = self.name_value.get().strip() if queue_after else ''
        self._clear_analysis_state()
        self._analysis_in_progress = True
        self.download_button.state(['disabled'])
        self.status_value.set('Fetching video information before download…' if queue_after
                              else 'Analysing URL metadata (yt-dlp)…')
        token = self._analysis_request_token
        force_playlist = self.playlist_value.get()

        async def fetch():
            return build_metadata_response(await fetch_metadata(url, force_playlist=force_playlist))['data']
        self._enqueue_future(fetch(), lambda info, err:
            self._metadata_ready(info, err, queue_after=queue_after, requested_name=requested_name)
            if token == self._analysis_request_token else None)

    def _metadata_ready(self, info, error, queue_after=False, requested_name=''):
        self._analysis_in_progress = False
        self.download_button.state(['!disabled'])
        if error:
            self.status_value.set(f'Metadata failed: {error}')
            messagebox.showerror('Metadata Failed', str(error))
            return
        self.metadata = info
        self._analysed_url = self.url_value.get().strip()
        self._original_title = info.get('originalFileName') or ''
        self.name_value.set(self._original_title)
        self._refresh_qualities()
        playlist = info.get('playlist') or {}
        entries = playlist.get('items') or []
        if entries:
            self.playlist_value.set(True)
            self.selected_rows['playlist'] = {str(i) for i, item in enumerate(entries)
                                              if item.get('available', True)}
            self._update_playlist_selection_label()
            self.playlist_edit_button.pack(side='right', padx=(0, 8))
            playable = len(self.selected_rows['playlist'])
            self.status_value.set(f'Playlist: {playable} playable / {len(entries)} entries. Choose your items in the popup.')
            self._open_playlist_selector()
        else:
            self.status_value.set(f'Single item: {self._original_title or "Unknown"}')
        self._show_download_preview(self._analysed_url, self._original_title, info.get('thumbnail') or '')
        if queue_after and not entries:
            if requested_name:
                self.name_value.set(requested_name)
            self._queue()
        elif queue_after and entries:
            self.status_value.set('Playlist found. Select the items to download, then press Download.')

    def _update_playlist_selection_label(self):
        entries = ((self.metadata or {}).get('playlist') or {}).get('items') or []
        selected = len(self.selected_rows['playlist'])
        self.playlist_selection_text.set(f'Playlist: {selected}/{len(entries)} Selected' if entries
                                         else 'Select Playlist Items')
        if self.playlist_dialog is not None and self.playlist_dialog.winfo_exists():
            self.playlist_selection_summary.set(f'{selected} of {len(entries)} Entries Selected')

    def _open_playlist_selector(self):
        
        playlist = (self.metadata or {}).get('playlist') or {}
        entries = playlist.get('items') or []
        if not entries:
            return
        if self.playlist_dialog is not None and self.playlist_dialog.winfo_exists():
            self.playlist_dialog.lift()
            self.playlist_dialog.focus_force()
            return
        previous = set(self.selected_rows['playlist'])
        dialog = tk.Toplevel(self)
        self.playlist_dialog = dialog
        dialog.title(f'YouSnipe — Playlist Selection: {playlist.get("name") or "Playlist"}')
        dialog.configure(background=UI_BG)
        self.update_idletasks()
        x = max(0, self.winfo_rootx() + (self.winfo_width() - 840) // 2)
        y = max(0, self.winfo_rooty() + (self.winfo_height() - 485) // 2)
        dialog.geometry(f'840x485+{x}+{y}')
        dialog.minsize(620, 350)
        dialog.transient(self)
        body = ttk.Frame(dialog, padding=13)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=playlist.get('name') or 'Playlist', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        self.playlist_selection_summary = tk.StringVar()
        ttk.Label(body, textvariable=self.playlist_selection_summary).pack(anchor='w', pady=(3, 10))
        list_frame = ttk.Frame(body)
        list_frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(list_frame, columns=('checked', 'title'), show='tree headings', selectmode='extended', height=6)
        self.playlist_list = tree
        tree.heading('#0', text='Preview')
        tree.column('#0', width=85, stretch=False)
        tree.heading('checked', text='Use')
        tree.column('checked', width=50, stretch=False, anchor='center')
        tree.heading('title', text='Title')
        tree.column('title', width=620, stretch=True)
        tree.pack(side='left', fill='both', expand=True)
        tree.bind('<Button-1>', self._playlist_click)
        tree.bind('<space>', lambda _: self._playlist_keyboard())
        scroll = ttk.Scrollbar(list_frame, orient='vertical', command=tree.yview)
        scroll.pack(side='right', fill='y')
        tree.configure(yscrollcommand=scroll.set)
        for i, item in enumerate(entries):
            ident = str(i)
            available = item.get('available', True)
            tree.insert('', 'end', iid=ident, values=(
                '—' if not available else '☑' if ident in self.selected_rows['playlist'] else '☐',
                f'{i+1:03d}  {item.get("title", "Unknown")}' + (' [UNAVAILABLE]' if not available else '')))
            self._request_thumbnail(item.get('thumbnail') or '',
                lambda photo, identifier=ident, generation=self._analysis_request_token, target=tree:
                    self._show_playlist_thumbnail(target, identifier, photo)
                    if generation == self._analysis_request_token else None, size=(70, 39))
        actions = ttk.Frame(body)
        actions.pack(fill='x', pady=(11, 0))
        ttk.Button(actions, text='Select All', command=lambda: self._playlist_bulk(True)).pack(side='left', padx=(0, 6))
        ttk.Button(actions, text='Deselect All', command=lambda: self._playlist_bulk(False)).pack(side='left')
        ttk.Button(actions, text='Use Selected Items', style='Accent.TButton',
                   command=self._close_playlist_dialog).pack(side='right')
        ttk.Button(actions, text='Cancel', command=lambda: cancel()).pack(side='right', padx=(0, 8))
        def cancel():
            self.selected_rows['playlist'] = previous
            self._close_playlist_dialog()
        dialog.protocol('WM_DELETE_WINDOW', cancel)
        self._update_playlist_selection_label()
        dialog.grab_set()
        tree.focus_set()

    def _close_playlist_dialog(self):
        dialog = self.playlist_dialog
        self.playlist_dialog = None
        self.playlist_list = None
        if dialog is not None:
            try:
                dialog.grab_release()
                dialog.destroy()
            except tk.TclError:
                pass
        self._update_playlist_selection_label()

    def _queue(self):
        urls = self._urls()
        if not urls:
            messagebox.showwarning('Missing URL', 'Paste one URL first.')
            return
        url = urls[0]
        if any(ch.isspace() for ch in url):
            messagebox.showwarning('Invalid URL', 'Enter one URL only (not multiple URLs).')
            return
        folder = self.folder_value.get().strip()
        if not folder:
            messagebox.showwarning('Missing Folder', 'Select an output folder.')
            return
        if not self.metadata or self._analysed_url != url:
            self._analyse(queue_after=True)
            return
        common = {'format': self.format_value.get(), 'quality': self._quality_raw(),
                  'mediaMode': self.media_mode.get(), 'savePath': folder}
        playlist = (self.metadata or {}).get('playlist') or {}
        if playlist:
            indices = sorted(int(i) for i in self.selected_rows['playlist'])
            if not indices:
                messagebox.showwarning('No Items', 'Select at least one playable playlist entry.')
                self._open_playlist_selector()
                return
            excluded = [item['index'] for index, item in enumerate(playlist['items']) if index not in indices]
            async def submit():
                from YouSnipeCommands import CommandDispatcher
                dispatcher = CommandDispatcher(self.backend.manager)
                prepared = dispatcher.prepare_playlist({**common, 'url': url, 'playlistName': self.name_value.get().strip() or playlist.get('name') or 'Playlist'}, playlist)
                return await dispatcher.execute('confirm playlist download',
                                                {'selectionId': prepared['selectionId'], 'excludeItems': excluded}, origin='gui')
        else:
            title = self.name_value.get().strip()
            original = self._original_title
            thumb = (self.metadata or {}).get('thumbnail') or ''
            async def submit():
                from YouSnipeCommands import CommandDispatcher
                return await CommandDispatcher(self.backend.manager).execute('download', {
                    **common, 'url': url, 'originalFileName': original,
                    'customFileName': title if title != original else '', 'thumbnail': thumb}, origin='gui')
        token = self._analysis_request_token
        self.status_value.set('Submitting to the real YouSnipe queue…')
        self._enqueue_future(submit(), lambda result, error:
                             self._queued(result, error, token))

    def _queued(self, result, error, token):
        if error:
            self.status_value.set(f'Queue error: {error}')
            messagebox.showerror('Queue Failed', str(error))
            return
        skipped = result.get('skippedEntries') if isinstance(result, dict) else []
        count = result.get('selectedCount', 1)
        if token == self._analysis_request_token and isinstance(result, dict):
            submitted = result.get('itemIds') or ([result['itemId']] if result.get('itemId') else [])
            self._preview_download_item_ids = tuple(str(ident) for ident in submitted)
            self.preview_stage_value.set('Queued for download')
            self.preview_progress_value.set(0)
            self.preview_progress_text.set('')
            self.preview_progress_row.pack_forget()
        self.status_value.set(f'Queued {count} item(s)' +
                              (f'; skipped {len(skipped)} unresolved playlist entries' if skipped else '') +
                              ' — progress is shown below Output.')
        self._refresh_queue()

    def _poll_queue(self):
        if not self.shutting_down:
            self._refresh_queue()
            self.after(900, self._poll_queue)

    def _refresh_queue(self):
        if self.shutting_down:
            return
        try:
            jobs = self.backend.manager.db.list_jobs(limit=500)
            new_rows = {}
            details = {}
            for job in jobs:
                for record in self.backend.manager.db.list_download_items_for_job(int(job['id'])):
                    ident = record['item_uuid']
                    new_rows[ident] = record
                    details[ident] = job
            self.item_rows = new_rows
            active = 0
            historical = 0
            term = self.history_search.get().casefold()
            status_filter = self.history_filter.get().lower()
            for tree, kind in [(self.tree, 'queue'), (self.history_tree, 'history')]:
                wanted = set()
                if kind == 'history':
                    ordered = sorted(new_rows.items(),
                        key=lambda item: self._history_sort_key(item, details),
                        reverse=self.history_sort_descending)
                    self._update_history_heading()
                else:
                    ordered = sorted(new_rows.items(), key=lambda pair: (
                        str(pair[1].get('created_at') or ''), str(pair[0])))
                for ident, record in ordered:
                    status = str(record.get('status') or '').lower()
                    is_active = status in ('queued', 'running')
                    if (kind == 'queue') != is_active:
                        continue
                    if kind == 'history':
                        if status == 'failed' and not self.keep_failed.get():
                            continue
                        if status_filter != 'all' and status != status_filter:
                            continue
                        if term and term not in (str(record.get('title') or '') + ' ' +
                                                str(record.get('webpage_url') or '') + ' ' +
                                                str(record.get('file_path') or '')).casefold():
                            continue
                    job = details[ident]
                    pct = record.get('progress_percent')
                    values = ['☑' if ident in self.selected_rows[kind] else '☐', record.get('title') or 'Download']
                    if kind == 'history':
                        timestamp = str(record.get('completed_at') or record.get('failed_at') or
                                        record.get('cancelled_at') or record.get('created_at') or '')
                        try:
                            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M:%S')
                        except (ValueError, TypeError, OverflowError):
                            timestamp = timestamp[:19].replace('T', ' ')
                        values.append(timestamp)
                    values.extend([_display_stage(status), _display_stage(record.get('stage')),
                                  f'{pct:.0f}%' if pct is not None else '—',
                                  job.get('target_format') or '', (self._history_folder(record, job) if kind == 'history' else (record.get('file_path') or job.get('save_path') or ''))])
                    wanted.add(ident)
                    if tree.exists(ident):
                        tree.item(ident, values=values, tags=(status,))
                    else:
                        tree.insert('', 'end', iid=ident, values=values, tags=(status,))
                    thumb_key = (kind, ident)
                    if thumb_key not in self.requested_row_thumbnails:

                        try:
                            stored = json.loads(record.get('raw_metadata_json') or '{}')
                            url_thumb = stored.get('thumbnail') or (stored.get('request') or {}).get('thumbnail')
                            if not url_thumb:
                                page_url = str(record.get('webpage_url') or '')
                                parsed = urlsplit(page_url)
                                hostname = (parsed.hostname or '').lower()
                                video_id = (parse_qs(parsed.query).get('v') or [''])[0]
                                if hostname in {'youtu.be', 'www.youtu.be'}:
                                    video_id = parsed.path.strip('/').split('/')[0]
                                if hostname in {'youtube.com', 'www.youtube.com', 'm.youtube.com'} and parsed.path.startswith('/shorts/'):
                                    video_id = parsed.path.split('/')[2]
                                if (hostname in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'www.youtu.be'}
                                    and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id)):
                                    url_thumb = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'
                        except (ValueError, TypeError, AttributeError):
                            url_thumb = ''
                        if url_thumb:
                            self.requested_row_thumbnails.add(thumb_key)
                            self._request_thumbnail(url_thumb, lambda photo, key=ident, t=tree, k=kind:
                                self._table_thumbnail_ready(t, key, photo, k), size=(78, 44))
                    if kind == 'queue':
                        active += 1
                    else:
                        historical += 1
                if kind == 'history':
                    for index, (ident, _) in enumerate((pair for pair in ordered if pair[0] in wanted)):
                        if tree.exists(ident):
                            tree.move(ident, '', index)
                self.selected_rows[kind].intersection_update(wanted)
                for ident in tree.get_children(''):
                    if ident not in wanted:
                        tree.delete(ident)
                        self.requested_row_thumbnails.discard((kind, ident))
                        self.thumbnail_images.pop(kind + '-' + ident, None)
            self.summary_value.set(f'Queue: {active} active   |   History: {historical} shown   |   {len(jobs)} recent jobs')
            self._update_download_preview(new_rows)
        except Exception as exc:
            self.status_value.set(f'Queue refresh error: {exc}')

    def _selected(self):
        kind = self.current_tree
        picked = self.selected_rows[kind]
        if picked:
            return next(iter(picked))
        tree = self.history_tree if kind == 'history' else self.tree
        chosen = tree.selection()
        return chosen[0] if chosen else None

    def _select_item(self, _event=None, which='queue'):
        self.current_tree = which
        ident = self._selected()
        if ident and ident in self.item_rows:
            record = self.item_rows[ident]
            err = record.get('error_message')
            self.status_value.set(f'{record.get("title")}: {_display_stage(record.get("status"))}' + (f' — {err}' if err else ''))

    def _remove_history_item(self):
        self.current_tree = 'history'
        selected = list(self.selected_rows['history'] or self.history_tree.selection())
        if not selected:
            return
        if not messagebox.askyesno('Remove from history', f'Remove {len(selected)} selected entries? Downloaded files will NOT be deleted.'):
            return
        try:
            from YouSnipeCommands import CommandDispatcher
            dispatcher = CommandDispatcher(self.backend.manager)
            result = self.backend.call(dispatcher.execute('remove download history item', {'ids': selected}, origin='gui', approved=True)).result(timeout=30)
            self.selected_rows['history'].difference_update(selected)
            self.status_value.set(f'{len(selected)} history entries removed. Downloaded files untouched.')
            self._refresh_queue()
        except Exception as exc:
            messagebox.showerror('History', str(exc))

    def _clear_history(self):
        if not messagebox.askyesno('Clear completed history',
                                   'Remove all completed, failed and cancelled jobs from history? Files on disk will NOT be deleted.'):
            return
        try:
            from YouSnipeCommands import CommandDispatcher
            dispatcher = CommandDispatcher(self.backend.manager)
            result = self.backend.call(dispatcher.execute('remove all download history', {}, origin='gui', approved=True)).result(timeout=30)
            self.status_value.set(f'Cleared {result["deletedJobs"]} jobs. Files are untouched.')
            self._refresh_queue()
        except Exception as exc:
            messagebox.showerror('History', str(exc))

    def _export_history(self):
        path = filedialog.asksaveasfilename(title='Export download history', defaultextension='.csv',
                                            filetypes=[('CSV files', '*.csv')])
        if not path:
            return
        try:
            jobs = self.backend.manager.db.list_terminal_jobs(limit=1000, include_failed=True)
            with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
                writer = csv.writer(fh)
                writer.writerow(['Date', 'Title', 'Status', 'URL', 'Format', 'File', 'Error'])
                for job in jobs:
                    for record in self.backend.manager.db.list_download_items_for_job(int(job['id'])):
                        writer.writerow([record.get('completed_at') or record.get('created_at') or '',
                                         record.get('title') or '', record.get('status') or '',
                                         record.get('webpage_url') or '', job.get('target_format') or '',
                                         record.get('file_path') or '', record.get('error_message') or ''])
            self.status_value.set(f'History exported to {path}')
        except Exception as exc:
            messagebox.showerror('Export failed', str(exc))

    def _cancel(self):
        self.current_tree = 'queue'
        ids = list(self.selected_rows['queue'] or self.tree.selection())
        if ids:
            async def cancel_all():
                return await asyncio.gather(*(self.backend.manager.cancel_item(i) for i in ids), return_exceptions=True)
            self._enqueue_future(cancel_all(), lambda r,e: self.status_value.set(
                f'Cancellation requested for {len(ids)} item(s)' if not e else f'Cancel error: {e}'))

    def _retry(self):
        self.current_tree = 'history'
        ids = list(self.selected_rows['history'] or self.history_tree.selection())
        if ids:
            async def retry_all():
                return await asyncio.gather(*(self.backend.manager.retry_item(i) for i in ids), return_exceptions=True)
            self._enqueue_future(retry_all(), lambda r,e: self.status_value.set(
                f'Retry requested for {len(ids)} item(s)' if not e else f'Retry error: {e}'))

    def _open_folder(self):
        self.current_tree = 'queue'
        ident = self._selected()
        path = (self.item_rows.get(ident) or {}).get("file_path") if ident else None
        folder = Path(path).parent if path else Path(self.folder_value.get())
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(folder)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showerror("Folder", str(exc))

    def _context_menu(self, widget):
        menu = tk.Menu(widget, tearoff=0)
        for label, sequence in [('Cut', '<<Cut>>'), ('Copy', '<<Copy>>'), ('Paste', '<<Paste>>'),
                                ('Select all', '<<SelectAll>>')]:
            menu.add_command(label=label, command=lambda seq=sequence: widget.event_generate(seq))
        def show(event):
            widget.focus_set()
            menu.tk_popup(event.x_root, event.y_root)
        widget.bind('<Button-3>', show)
        widget.bind('<Control-Button-1>', show) 

    def _reset_name(self):
        self.name_value.set(self._original_title)

    def _reset_url(self):
        self.url_value.set('')  
        self._clear_analysis_state()  
        self.playlist_value.set(False)
        self.media_mode.set(self.settings['downloadDefaults']['defaultMediaMode'])
        self.format_value.set(self.settings['downloadDefaults'][
            'defaultAudioFormat' if self.media_mode.get() == 'audio' else 'defaultVideoFormat'])
        self._update_formats()
        self.status_value.set('URL, analysis and download preview cleared')
        self.url_entry.focus_set()

    def _quality_raw(self):
        displayed = self.quality_value.get().strip()
        return 'Highest' if displayed.startswith('Highest (') else (displayed or 'Highest')

    def _refresh_qualities(self):
        data = (self.metadata or {}).get(self.media_mode.get()) or {}
        native = data.get('nativeQuality') or ''
        label = f'Highest ({native}{"p" if self.media_mode.get() == "video" else " kbps"})' if native else 'Highest'
        formats = data.get('qualitiesByFormat') or {}
        native_options = formats.get(self.format_value.get()) or []
        fixed = ([f'{q}' for q in native_options if q != 'Highest']
                 if native_options else (['4320','2160','1440','1080','720','480','360','240','144']
                     if self.media_mode.get() == 'video' else ['320','256','192','160','128','96','64','LOSSLESS']))
        self.quality_box['values'] = [label] + fixed
        old = self._quality_raw()
        self.quality_value.set(old if old != 'Highest' and old in fixed else label)
        self._sync_analysed_output()

    def _playlist_click(self, event):
        tree = self.playlist_list
        if tree is None or tree.identify_region(event.x, event.y) != 'cell':
            return
        ident = tree.identify_row(event.y)
        if ident and tree.identify_column(event.x) == '#1':
            entries = ((self.metadata or {}).get('playlist') or {}).get('items') or []
            if int(ident) < len(entries) and entries[int(ident)].get('available', True):
                self._toggle_playlist(ident)
            return 'break'

    def _playlist_keyboard(self):
        if self.playlist_list is not None:
            entries = ((self.metadata or {}).get('playlist') or {}).get('items') or []
            for ident in self.playlist_list.selection():
                if int(ident) < len(entries) and entries[int(ident)].get('available', True):
                    self._toggle_playlist(ident)
        return 'break'

    def _toggle_playlist(self, ident):
        selected = self.selected_rows['playlist']
        if ident in selected:
            selected.remove(ident)
        else:
            selected.add(ident)
        if self.playlist_list is not None and self.playlist_list.exists(ident):
            self.playlist_list.set(ident, 'checked', '☑' if ident in selected else '☐')
        self._update_playlist_selection_label()

    def _playlist_bulk(self, checked):
        entries = ((self.metadata or {}).get('playlist') or {}).get('items') or []
        selected = self.selected_rows['playlist']
        selected.clear()
        for i, item in enumerate(entries):
            ident = str(i)
            available = item.get('available', True)
            if checked and available:
                selected.add(ident)
            if self.playlist_list is not None and self.playlist_list.exists(ident):
                self.playlist_list.set(ident, 'checked',
                                       '—' if not available else '☑' if checked else '☐')
        self._update_playlist_selection_label()

    def _tree_click(self, event, kind):
        tree = self.tree if kind == 'queue' else self.history_tree
        ident = tree.identify_row(event.y)
        if ident and tree.identify_region(event.x, event.y) == 'cell' and tree.identify_column(event.x) == '#1':
            selected = self.selected_rows[kind]
            if ident in selected:
                selected.remove(ident)
            else:
                selected.add(ident)
            tree.set(ident, 'pick', '☑' if ident in selected else '☐')
            if kind == 'history' and self.history_sort_column == 'pick':
                self.after_idle(self._refresh_queue)
            return 'break'

    def _tree_bulk(self, kind, checked):
        tree = self.tree if kind == 'queue' else self.history_tree
        selected = self.selected_rows[kind]
        selected.clear()
        for ident in tree.get_children():
            if checked:
                selected.add(ident)
            tree.set(ident, 'pick', '☑' if checked else '☐')
        if kind == 'history' and self.history_sort_column == 'pick':
            self.after_idle(self._refresh_queue)

    def _show_thumbnail(self, widget, photo, key):
        if not photo or not widget.winfo_exists():
            return
        self.thumbnail_images[key] = photo
        widget.configure(image=photo, text='')

    def _table_thumbnail_ready(self, tree, ident, photo, kind):
        if photo is None:
            self.requested_row_thumbnails.discard((kind, ident))
            return
        self._show_table_thumbnail(tree, ident, photo, kind)

    def _show_table_thumbnail(self, tree, ident, photo, kind):
        if photo and tree.exists(ident):
            self.thumbnail_images[kind+'-'+ident] = photo
            tree.item(ident, image=photo)

    def _show_playlist_thumbnail(self, tree, ident, photo):
        if photo and tree.winfo_exists() and tree.exists(ident):
            self.thumbnail_images['playlist-'+str(tree)+'-'+ident] = photo
            tree.item(ident, image=photo)

    def _request_thumbnail(self, url, callback, size=(120, 68)):
        if not url:
            return
        
        future = self.thumbnail_loader.submit(url, size)
        if future is None:
            return
        def poll():
            if self.shutting_down:
                return
            if not future.done():
                self.after(130, poll)
                return
            try:
                from PIL import ImageTk
                image = future.result()
                callback(ImageTk.PhotoImage(image, master=self) if image is not None else None)
            except Exception:
                callback(None)
        self.after(120, poll)

    def _close(self):
        self._close_playlist_dialog()
        active = [r for r in self.item_rows.values() if r.get("status") in ("queued", "running")]
        if active and not messagebox.askyesno("Exit YouSnipe", f"Cancel {len(active)} queued/running item(s) and exit?"):
            return
        self.shutting_down = True
        self.status_value.set("Shutting down download processes safely…")
        future = self.backend.call(self.backend.shutdown())
        def finish():
            if future.done():
                self.backend.stop()
                self.destroy()
            else:
                self.after(100, finish)
        self.after(100, finish)


def main(on_ready=None):
    try:
        app = YouSnipeGUI()
        if on_ready:
            on_ready()
        app.mainloop()
    except tk.TclError as exc:
        print(f"Unable to create the GUI: {exc}", file=sys.stderr)
        print("Tkinter requires a desktop session. Run YouSnipe.py for the WebSocket backend.", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    
    from YouSnipe import prepare_windows_gui
    prepare_windows_gui()
    main()
