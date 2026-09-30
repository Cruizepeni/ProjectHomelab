from __future__ import annotations

import subprocess
from typing import Any

from TerminalSSUI import TerminalSSUI


class TerminalSSPythoFetchProtocol:
    PROTOCOL_ID = "PythoFetch"
    KEY = "6"
    EXTERNAL_STATIC = True
    ALLOW_MISSING_ASSETS = True
    DEFAULT_SETTINGS = {
        "DisplayMode": "Classic",
    }
    SETTING_SCHEMA = {
        "DisplayMode": {
            "Label": "Display Mode",
            "Type": "choice",
            "Choices": ["Classic", "Headless Text"],
        },
    }

    @classmethod
    def settings_contract(cls) -> dict[str, Any]:
        return {"Defaults": cls.DEFAULT_SETTINGS, "Schema": cls.SETTING_SCHEMA}

    @classmethod
    def ensure_assets(cls, asset_manager):
        return asset_manager.ensure_pythofetch()

    @classmethod
    def repair_assets(cls, asset_manager):
        return asset_manager.ensure_pythofetch(force=True)

    @classmethod
    def rebuild_assets(cls, asset_manager):
        return asset_manager.ensure_pythofetch(force=True)

    def __init__(self, asset_manager, ui: TerminalSSUI):
        self.asset_manager = asset_manager
        self.ui = ui

    def reset(self, settings: dict, width: int, height: int, now: float) -> None:
        return None

    def activate_external(self, settings: dict) -> int:
        print("Collecting system information...", flush=True)
        command = self.asset_manager.pythofetch_command()
        if str(settings.get("DisplayMode", "Classic")).casefold() == "headless text":
            command.extend(["--headless", "--all", "--format", "text"])
        else:
            command.append("--classic")
        result = subprocess.run(
            command,
            cwd=str(self.asset_manager.pythofetch_path()),
            check=False,
        )
        return int(result.returncode)

    def render(self, width: int, height: int, settings: dict, now: float):
        canvas = self.ui.canvas(width, height)
        canvas.overlay_center_box(
            "PYTHOFETCH",
            [
                "PythoFetch output is displayed directly in this protocol.",
                "Press 6 to refresh the system snapshot.",
                "Press another protocol key to return to TerminalSS rendering.",
            ],
        )
        return canvas

    def handle_runtime_key(self, key, settings: dict) -> None:
        return None

    def reverse_direction(self, settings: dict) -> None:
        return None

    def primary_speed_label(self, settings: dict) -> str:
        return "PythoFetch"


PROTOCOL_CLASS = TerminalSSPythoFetchProtocol
