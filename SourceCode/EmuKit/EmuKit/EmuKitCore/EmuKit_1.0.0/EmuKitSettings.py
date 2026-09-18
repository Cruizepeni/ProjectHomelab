from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class EmuKitSettings:
    SETTINGS_VERSION = 2

    def __init__(self, project_root: str | Path) -> None:
        self._lock = threading.RLock()
        self.project_root = Path(project_root).resolve()
        self.settings_path = self.project_root / "appdata" / "settings" / "EmuKitSettings.json"
        self._data: dict[str, Any] = {}
        self.load()

    def _default_document(self) -> dict[str, Any]:
        return {
            "Version": self.SETTINGS_VERSION,
            "Fullscreen": True,
            "Modules": {},
            "SystemAssignments": {},
        }

    def _normalize(self, data: Any) -> dict[str, Any]:
        source = data if isinstance(data, dict) else {}

        fullscreen = source.get("Fullscreen", True)
        if not isinstance(fullscreen, bool):
            fullscreen = True

        modules = source.get("Modules", {})
        if not isinstance(modules, dict):
            modules = {}

        normalized_modules: dict[str, dict[str, Any]] = {}
        for module_id, entry in modules.items():
            if not isinstance(module_id, str) or not module_id.strip():
                continue
            enabled = False
            if isinstance(entry, dict):
                if isinstance(entry.get("Enabled"), bool):
                    enabled = entry["Enabled"]
                elif isinstance(entry.get("Installed"), bool):
                    enabled = entry["Installed"]
            normalized_modules[module_id] = {"Enabled": enabled}

        assignments = source.get("SystemAssignments", {})
        if not isinstance(assignments, dict):
            assignments = {}

        normalized_assignments: dict[str, str | None] = {}
        for system_id, module_id in assignments.items():
            if not isinstance(system_id, str) or not system_id.strip():
                continue
            normalized_assignments[system_id] = module_id if isinstance(module_id, str) else None

        return {
            "Version": self.SETTINGS_VERSION,
            "Fullscreen": fullscreen,
            "Modules": normalized_modules,
            "SystemAssignments": normalized_assignments,
        }

    def _backup_corrupt_file(self) -> None:
        if not self.settings_path.exists():
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.settings_path.with_name(
            f"{self.settings_path.stem}.corrupt-{stamp}{self.settings_path.suffix}"
        )
        index = 1
        while target.exists():
            target = self.settings_path.with_name(
                f"{self.settings_path.stem}.corrupt-{stamp}-{index}{self.settings_path.suffix}"
            )
            index += 1
        self.settings_path.replace(target)

    def _atomic_write(self, data: dict[str, Any]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.settings_path.with_suffix(self.settings_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(self.settings_path)

    def load(self) -> dict[str, Any]:
        with self._lock:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.settings_path.exists():
                self._data = self._default_document()
                self._atomic_write(self._data)
                return copy.deepcopy(self._data)

            try:
                with self.settings_path.open("r", encoding="utf-8") as handle:
                    raw = json.load(handle)
            except (json.JSONDecodeError, OSError):
                self._backup_corrupt_file()
                raw = {}

            normalized = self._normalize(raw)
            self._data = normalized
            if normalized != raw:
                self._atomic_write(normalized)
            return copy.deepcopy(self._data)

    def reload(self) -> dict[str, Any]:
        return self.load()

    def save(self) -> None:
        with self._lock:
            self._data = self._normalize(self._data)
            self._atomic_write(self._data)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def get_fullscreen(self) -> bool:
        with self._lock:
            return bool(self._data.get("Fullscreen", True))

    def set_fullscreen(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("Fullscreen must be a boolean.")
        with self._lock:
            self._data["Fullscreen"] = enabled
            self.save()

    def get_global_setting(self, setting_name: str) -> Any:
        key = setting_name.strip().casefold()
        with self._lock:
            if key == "fullscreen":
                return self._data["Fullscreen"]
        raise KeyError(setting_name)

    def update_global_setting(self, setting_name: str, value: Any) -> Any:
        key = setting_name.strip().casefold()
        if key != "fullscreen":
            raise KeyError(setting_name)
        if not isinstance(value, bool):
            raise TypeError("Fullscreen must be a boolean.")
        self.set_fullscreen(value)
        return value

    def has_module(self, module_id: str) -> bool:
        with self._lock:
            return module_id in self._data["Modules"]

    def get_module_settings(self, module_id: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._data["Modules"].get(module_id)
            return copy.deepcopy(entry) if isinstance(entry, dict) else None

    def ensure_module(self, module_id: str, *, enabled: bool = False) -> bool:
        with self._lock:
            if module_id in self._data["Modules"]:
                return False
            self._data["Modules"][module_id] = {"Enabled": bool(enabled)}
            self.save()
            return True

    def remove_module(self, module_id: str) -> bool:
        with self._lock:
            if module_id not in self._data["Modules"]:
                return False
            del self._data["Modules"][module_id]
            for system_id, assigned_module in list(self._data["SystemAssignments"].items()):
                if assigned_module == module_id:
                    self._data["SystemAssignments"][system_id] = None
            self.save()
            return True

    def is_module_enabled(self, module_id: str) -> bool:
        with self._lock:
            entry = self._data["Modules"].get(module_id, {})
            return bool(entry.get("Enabled", False))

    def set_module_enabled(self, module_id: str, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("Enabled must be a boolean.")
        with self._lock:
            if module_id not in self._data["Modules"]:
                self._data["Modules"][module_id] = {"Enabled": enabled}
            else:
                self._data["Modules"][module_id]["Enabled"] = enabled
            self.save()

    def set_module_installed(self, module_id: str, installed: bool) -> None:
        self.set_module_enabled(module_id, installed)

    def get_system_assignment(self, system_id: str) -> str | None:
        with self._lock:
            value = self._data["SystemAssignments"].get(system_id)
            return value if isinstance(value, str) else None

    def has_system_assignment(self, system_id: str) -> bool:
        with self._lock:
            return system_id in self._data["SystemAssignments"]

    def ensure_system_assignment(self, system_id: str, module_id: str | None) -> bool:
        if module_id is not None and not isinstance(module_id, str):
            raise TypeError("module_id must be a string or None.")
        with self._lock:
            if system_id in self._data["SystemAssignments"]:
                return False
            self._data["SystemAssignments"][system_id] = module_id
            self.save()
            return True

    def set_system_assignment(self, system_id: str, module_id: str | None) -> None:
        if module_id is not None and not isinstance(module_id, str):
            raise TypeError("module_id must be a string or None.")
        with self._lock:
            self._data["SystemAssignments"][system_id] = module_id
            self.save()

    def remove_system_assignment(self, system_id: str) -> bool:
        with self._lock:
            if system_id not in self._data["SystemAssignments"]:
                return False
            del self._data["SystemAssignments"][system_id]
            self.save()
            return True
