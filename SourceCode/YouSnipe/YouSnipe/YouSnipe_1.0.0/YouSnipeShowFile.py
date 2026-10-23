from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def reveal_file_in_folder(file_path: str) -> dict:
    target = Path(str(file_path or '').strip())
    if not str(target):
        return {"ok": False, "error": "empty_path"}

    if os.name == 'nt':
        if target.exists() and target.is_file():
            subprocess.Popen(["explorer.exe", "/select,", str(target)])
            return {"ok": True, "path": str(target), "method": "explorer_select"}

        parent = target if target.is_dir() else target.parent
        if parent and parent.exists():
            os.startfile(str(parent))
            return {"ok": True, "path": str(parent), "method": "startfile_dir"}

        return {"ok": False, "error": "path_not_found", "path": str(target)}

    if sys.platform == 'darwin':
        if target.exists():
            subprocess.Popen(["open", "-R", str(target)])
            return {"ok": True, "path": str(target), "method": "open_reveal"}
        parent = target.parent
        if parent.exists():
            subprocess.Popen(["open", str(parent)])
            return {"ok": True, "path": str(parent), "method": "open_dir"}
        return {"ok": False, "error": "path_not_found", "path": str(target)}

    parent = target if target.is_dir() else target.parent
    if parent and parent.exists():
        subprocess.Popen(["xdg-open", str(parent)])
        return {"ok": True, "path": str(parent), "method": "xdg_open_dir"}

    return {"ok": False, "error": "path_not_found", "path": str(target)}