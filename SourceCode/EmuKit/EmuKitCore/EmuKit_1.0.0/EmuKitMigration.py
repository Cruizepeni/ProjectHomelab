from __future__ import annotations

import copy
from typing import Any, Callable


class EmuKitMigrationManager:

    def __init__(self, settings) -> None:
        self.settings = settings
        self._steps: list[tuple[str, str, Callable[[], dict[str, Any] | None]]] = []

    def register(
        self,
        from_version: str,
        to_version: str,
        callback: Callable[[], dict[str, Any] | None],
    ) -> None:
        self._steps.append((from_version, to_version, callback))

    @staticmethod
    def _version_key(value: str) -> tuple:
        parts: list[tuple[int, Any]] = []
        import re
        for part in re.split(r"([0-9]+)", str(value).casefold()):
            if not part:
                continue
            if part.isdigit():
                parts.append((1, int(part)))
            else:
                parts.append((0, part))
        return tuple(parts)

    def migrate(self, from_version: str, to_version: str) -> dict[str, Any]:
        before = self.settings.snapshot()
        normalized = self.settings.reload()
        applied: list[dict[str, Any]] = []

        current = from_version
        target_key = self._version_key(to_version)
        for step_from, step_to, callback in sorted(
            self._steps,
            key=lambda item: self._version_key(item[0]),
        ):
            if current != step_from:
                continue
            if self._version_key(step_to) > target_key:
                continue
            details = callback() or {}
            applied.append({
                "from": step_from,
                "to": step_to,
                "details": copy.deepcopy(details),
            })
            current = step_to

        return {
            "success": True,
            "operation": "migration",
            "state": "complete",
            "message": "EmuKit persistent data migration completed.",
            "details": {
                "from_version": from_version,
                "to_version": to_version,
                "steps": applied,
                "settings_normalized": before != normalized,
            },
        }
