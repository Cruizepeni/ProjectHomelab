from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path


def apply_window_icon(window):
    source = Path(__file__).resolve().parent
    candidates = [Path(getattr(sys, '_MEIPASS', source)), source]
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).resolve().parent)
    for parent in source.parents:
        candidates.append(parent / 'Resources' / 'Icons' / 'Features' / 'YouSnipe')
    seen = set()
    for folder in candidates:
        if str(folder) in seen:
            continue
        seen.add(str(folder))
        ico = folder / 'Icon_YouSnipe.ico'
        if os.name == 'nt' and ico.is_file():
            try:
                window.iconbitmap(default=str(ico))
                return True
            except (tk.TclError, OSError):
                pass
        png = folder / 'Icon_YouSnipe.png'
        if png.is_file():
            try:
                window._yousnipe_icon = tk.PhotoImage(file=str(png), master=window)
                window.iconphoto(True, window._yousnipe_icon)
                return True
            except (tk.TclError, OSError):
                pass
    return False
