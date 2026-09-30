from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Any

from TerminalSSUI import TerminalSSUI, TerminalCanvas, display_width
from TerminalSSHackerSimulator import HackerScenario, HackerSimulator, parse_scenario_text


class TerminalSSHackerProtocol:
    PROTOCOL_ID = "Hacker"
    KEY = "5"
    ALLOW_MISSING_ASSETS = True
    DEFAULT_SETTINGS = {
        "Pace": 100,
        "ResultDisplayTime": 6.0,
        "Color": "Electric Blue",
        "RGB": False,
        "RGBSpeed": 50,
        "CustomColorShift": False,
        "CustomColorShiftSpeed": 50,
        "CustomColorShiftColors": ["Electric Blue", "Cyan", "Matrix Green"],
    }
    SETTING_SCHEMA = {
        "Pace": {"Label": "Simulation Pace", "Type": "integer", "Min": 40, "Max": 220},
        "ResultDisplayTime": {"Label": "Result Display Time", "Type": "seconds", "Min": 1, "Max": 120},
        "Color": {"Label": "Color", "Type": "color"},
        "RGB": {"Label": "RGB", "Type": "boolean"},
        "RGBSpeed": {"Label": "RGB Speed", "Type": "percent"},
        "CustomColorShift": {"Label": "Custom Color Shift", "Type": "boolean"},
        "CustomColorShiftSpeed": {"Label": "Custom Color Shift Speed", "Type": "percent"},
        "CustomColorShiftColors": {"Label": "Custom Color Shift Colors", "Type": "color_list"},
    }
    TARGET_FIELDS = (
        ("TARGET", "Target"),
        ("ADDRESS", "TargetAddress"),
        ("LOCATION", "Location"),
        ("OBJECTIVE", "Objective"),
        ("SECURITY", "Security"),
        ("RATES", "Rates"),
    )

    @classmethod
    def settings_contract(cls) -> dict[str, Any]:
        return {"Defaults": cls.DEFAULT_SETTINGS, "Schema": cls.SETTING_SCHEMA}

    def __init__(self, asset_manager, ui: TerminalSSUI):
        self.asset_manager = asset_manager
        self.ui = ui
        self.asset_path = self.asset_manager.protocol_path(self.PROTOCOL_ID)
        self.characters: tuple[str, ...] = tuple("01#@$%&*+-=<>?/\\|[]{}")
        self.operations: list[dict[str, Any]] = []
        self.simulator = HackerSimulator()
        self.plan = None
        self.current: dict[str, Any] | None = None
        self.last_operation_path: Path | None = None
        self.phase = "operation"
        self.phase_started = 0.0
        self.operation_ends = 0.0
        self.result_ends = 0.0
        self.operation_duration = 24.0
        self.result_duration = 6.0
        self.outcome = "SUCCESS"
        self.operation_seed = 0
        self.packet_direction = 1
        self.last_stage_index = -1
        self.log_entries: list[str] = []
        self.next_log_time = 0.0
        self.counter_event_at: float | None = None
        self.counter_active_until = 0.0
        self.counter_started = False
        self.counter_resolved = False
        self.glitch_at: float | None = None
        self.glitch_until = 0.0
        self.route_variant = 0
        self.topology_variant = 0
        self.traffic_rate = 0
        self.load_assets()

    def load_assets(self) -> None:
        pool = self.asset_manager.character_set("Curated CyberPunk", "01#@$%&*+-=<>?/\\|[]{}")
        unique = []
        seen = set()
        for token in pool:
            if token and token not in seen and display_width(token) == 1:
                seen.add(token)
                unique.append(token)
        if unique:
            self.characters = tuple(unique)
        self.operations = []
        seen_files = set()
        for root in self.asset_manager.protocol_asset_roots(self.PROTOCOL_ID):
            for path in sorted(root.rglob("*.txt")):
                resolved = path.resolve()
                if resolved in seen_files:
                    continue
                seen_files.add(resolved)
                try:
                    scenario = parse_scenario_text(path.read_text(encoding="utf-8"), path)
                except OSError:
                    continue
                operation = scenario.as_mapping()
                if str(operation.get("Operation", "Unknown")).strip().casefold() == "unknown":
                    continue
                operation["_Warnings"] = tuple(scenario.warnings)
                self.operations.append(operation)

        if not self.operations:
            defaults = (
                {
                    "Operation": "Project Archive Extraction",
                    "Target": "Research Workstation",
                    "TargetAddress": "https://archive.example",
                    "Location": "Remote",
                    "Objective": "Download Files",
                    "Security": 72,
                    "SuccessRate": 82,
                    "GlitchRate": 8,
                    "FreezeRate": 4,
                    "HackBackChance": 6,
                    "BlockAttempts": 5,
                },
                {
                    "Operation": "Internal Audit Simulation",
                    "Target": "Finance Workstation",
                    "TargetAddress": "FIN-WS-07",
                    "Location": "Internal Network",
                    "Objective": "Penetration Test",
                    "Security": 84,
                    "SuccessRate": 90,
                    "GlitchRate": 5,
                    "FreezeRate": 2,
                    "HackBackChance": 12,
                    "BlockAttempts": 3,
                },
                {
                    "Operation": "Local Persistence Test",
                    "Target": "Engineering Terminal",
                    "TargetAddress": "LOCALHOST",
                    "Location": "Local",
                    "Objective": "Create Back Door",
                    "Security": 48,
                    "SuccessRate": 88,
                    "GlitchRate": 3,
                    "FreezeRate": 2,
                    "HackBackChance": 0,
                    "BlockAttempts": 1,
                },
            )
            self.operations = [HackerScenario.from_mapping(item).as_mapping() for item in defaults]

    @staticmethod
    def _value(operation: dict[str, Any] | None, key: str, default: str = "Unknown") -> str:
        if not isinstance(operation, dict):
            return default
        value = operation.get(key, default)
        if value is None or str(value).strip() == "":
            return default
        return str(value)

    def _choose_operation(self) -> dict[str, Any] | None:
        if not self.operations:
            return None
        choices = self.operations
        if self.last_operation_path is not None and len(choices) > 1:
            filtered = [operation for operation in choices if operation.get("_Path") != self.last_operation_path]
            if filtered:
                choices = filtered
        return random.choice(choices)

    def _stages(self) -> tuple[str, ...]:
        if self.plan is None:
            return ("ANALYSING",)
        return tuple(event.label for event in self.plan.events) or ("ANALYSING",)

    def _append_log(self, text: str) -> None:
        line = str(text).strip().upper()
        if not line:
            return
        if self.log_entries and self.log_entries[-1] == line:
            return
        self.log_entries.append(line)
        if len(self.log_entries) > 80:
            self.log_entries = self.log_entries[-80:]

    def _background_logs(self) -> tuple[str, ...]:
        location = self._value(self.current, "Location", "Remote")
        if location == "Local":
            return (
                "LOCAL PROCESS MAP REFRESHED",
                "ACTIVE USER CONTEXT VERIFIED",
                "SERVICE INVENTORY UPDATED",
                "LOCAL POLICY STATE REFRESHED",
                "STORAGE INDEX SYNCHRONISED",
                "SESSION CONTEXT STABLE",
                "RESOURCE ACCESS MAP UPDATED",
            )
        if location == "Internal Network":
            return (
                "INTERNAL NODE HEARTBEAT DETECTED",
                "DIRECTORY RELATIONSHIP GRAPH REFRESHED",
                "SEGMENT ROUTE VERIFIED",
                "REMOTE SERVICE MAP UPDATED",
                "INTERNAL SESSION CONTEXT STABLE",
                "TARGET PATH REVALIDATED",
                "IDENTITY RELATIONSHIP CACHE UPDATED",
            )
        return (
            "REMOTE RESPONSE RECEIVED",
            "ROUTE LATENCY RECALCULATED",
            "PACKET ROUTE VERIFIED",
            "SESSION CONTEXT REFRESHED",
            "SERVICE SURFACE UPDATED",
            "REMOTE NODE HEARTBEAT DETECTED",
            "TRANSPORT SESSION STABLE",
        )

    def _start_operation(self, settings: dict, now: float, operation: dict[str, Any] | None = None) -> None:
        selected = operation or self._choose_operation() or {}
        scenario = HackerScenario.from_mapping(selected, selected.get("_Path") if isinstance(selected, dict) else None)
        self.plan = self.simulator.build_plan(scenario, settings)
        self.current = scenario.as_mapping()
        self.current["_Warnings"] = tuple(scenario.warnings)
        self.phase = "operation"
        self.phase_started = now
        self.operation_duration = self.plan.duration
        self.result_duration = max(1.0, float(settings.get("ResultDisplayTime", 6.0)))
        self.operation_ends = now + self.operation_duration
        self.result_ends = self.operation_ends + self.result_duration
        self.outcome = self.plan.outcome
        self.operation_seed = self.plan.seed
        self.topology_variant = random.Random(self.operation_seed ^ 0x91A3).randrange(5)
        self.route_variant = random.Random(self.operation_seed ^ 0x3F77).randrange(4)
        self.traffic_rate = random.Random(self.operation_seed ^ 0x6C21).randint(80, 480)
        self.last_stage_index = -1
        self.log_entries = []
        self.next_log_time = now + random.uniform(0.55, 1.25)
        self.counter_event_at = None
        self.counter_active_until = 0.0
        self.counter_started = False
        self.counter_resolved = False
        self.glitch_at = None
        self.glitch_until = 0.0
        for effect in self.plan.effects:
            if effect.kind == "hackback":
                self.counter_event_at = now + effect.at
                self.counter_active_until = self.counter_event_at + effect.duration
            elif effect.kind == "glitch":
                self.glitch_at = now + effect.at
        self._append_log("OPERATION INITIALISED")
        self._append_log(f"TARGET ACQUIRED: {scenario.target}")
        self._append_log(f"LOCATION PROFILE: {scenario.location}")
        self._append_log(f"OBJECTIVE LOADED: {scenario.objective}")
        for warning in scenario.warnings:
            self._append_log(f"CONFIG WARNING: {warning}")
        self.last_operation_path = scenario.source_path

    def reset(self, settings: dict, width: int, height: int, now: float | None = None) -> None:
        base = now if now is not None else time.monotonic()
        self.current = None
        self.plan = None
        self.packet_direction = 1
        self._start_operation(settings, base)

    def _progress(self, now: float) -> float:
        if self.phase == "result":
            return 1.0
        duration = max(0.001, self.operation_duration)
        return max(0.0, min(1.0, (now - self.phase_started) / duration))

    def _stage_index(self, progress: float) -> int:
        if self.plan is None or not self.plan.events:
            return 0
        index, _, _ = self.plan.event_at(progress * self.plan.duration)
        return index

    def _current_plan_event(self, progress: float):
        if self.plan is None or not self.plan.events:
            return None, 0.0
        _, event, local = self.plan.event_at(progress * self.plan.duration)
        return event, local

    def _stage_name(self, progress: float) -> str:
        if self.phase == "result":
            if self.outcome == "SUCCESS":
                return "OPERATION COMPLETE"
            if self.outcome == "FREEZE":
                return "PROCESS FROZEN"
            return "OPERATION FAILED"
        event, _ = self._current_plan_event(progress)
        return event.label if event is not None else "ANALYSING"

    def _target_scan(self, progress: float) -> float:
        if self.plan is None:
            return max(0.0, min(100.0, progress * 175.0))
        access_fraction = max(0.08, min(0.92, self.plan.access_at / max(0.001, self.plan.duration)))
        if progress >= access_fraction:
            return 100.0
        return max(0.0, min(100.0, progress / access_fraction * 100.0))

    def _breach_progress(self, progress: float) -> float:
        if self.plan is None:
            return progress * 100.0
        has_access = any(event.kind == "access" for event in self.plan.events)
        if not has_access and self.outcome in {"FAILURE", "FREEZE"}:
            return max(0.0, min(82.0, progress * 82.0))
        access_fraction = max(0.08, min(0.92, self.plan.access_at / max(0.001, self.plan.duration)))
        if progress < access_fraction:
            return max(0.0, min(90.0, progress / access_fraction * 90.0))
        remaining = max(0.001, 1.0 - access_fraction)
        return max(90.0, min(100.0, 90.0 + (progress - access_fraction) / remaining * 10.0))

    def _trace_risk(self, progress: float, now: float) -> float:
        base = 6.0 + math.sin(now * 1.7 + self.operation_seed % 13) * 2.5
        security = 50.0
        if self.current is not None:
            try:
                security = float(self.current.get("Security", 50))
            except (TypeError, ValueError):
                security = 50.0
        base += progress * (8.0 + security * 0.14)
        if self.counter_started and now < self.counter_active_until:
            total = max(0.1, self.counter_active_until - (self.counter_event_at or now))
            event_progress = 1.0 - max(0.0, self.counter_active_until - now) / total
            base = max(base, 40.0 + event_progress * 48.0 + math.sin(now * 9.0) * 5.0)
        if self.counter_resolved and self.outcome == "SUCCESS":
            base *= max(0.30, 1.0 - progress * 0.48)
        if self.phase == "result" and self.outcome == "SUCCESS":
            base = max(2.0, base * 0.20)
        return max(0.0, min(100.0, base))

    def _access_level(self, progress: float) -> str:
        if self.plan is None:
            return "NONE"
        has_access = any(event.kind == "access" for event in self.plan.events)
        access_fraction = max(0.05, min(0.95, self.plan.access_at / max(0.001, self.plan.duration)))
        if progress < access_fraction * 0.35:
            return "NONE"
        if progress < access_fraction * 0.70:
            return "RESTRICTED"
        if not has_access:
            if self.outcome == "FREEZE" and progress >= 0.90:
                return "UNRESPONSIVE"
            if self.outcome == "FAILURE" and progress >= 0.90:
                return "DENIED"
            return "NEGOTIATING"
        if progress < access_fraction:
            return "NEGOTIATING"
        if self.outcome == "FAILURE" and progress >= 0.95:
            return "LOST"
        if self.outcome == "FREEZE" and progress >= 0.95:
            return "UNRESPONSIVE"
        return "ESTABLISHED"

    def _update_logs(self, now: float, progress: float) -> None:
        index = self._stage_index(progress)
        if index != self.last_stage_index and self.plan is not None and 0 <= index < len(self.plan.events):
            event = self.plan.events[index]
            self._append_log(event.log)
            self.last_stage_index = index
        if now >= self.next_log_time and self.phase == "operation":
            rng = random.Random(self.operation_seed ^ int(now * 4.0))
            self._append_log(rng.choice(self._background_logs()))
            self.next_log_time = now + random.uniform(0.85, 1.9)
        if self.counter_event_at is not None and not self.counter_started and now >= self.counter_event_at:
            self.counter_started = True
            self.glitch_until = max(self.glitch_until, now + 0.45)
            self._append_log("DEFENDER ACTIVITY DETECTED")
            self._append_log("COUNTER-INTRUSION ACTIVE")
        if self.counter_started and not self.counter_resolved and now >= self.counter_active_until:
            self.counter_resolved = True
            self._append_log("COUNTER-INTRUSION CONTAINED")
            self._append_log("SESSION ROUTE STABILISED")
            self._append_log("OPERATION RESUMED")

    @staticmethod
    def _draw_progress_row(canvas: TerminalCanvas, x: int, y: int, width: int, label: str, value: float, style: int = 3) -> None:
        label_text = f"{label.upper()}:"
        percent = f"{max(0.0, min(100.0, value)):3.0f}%"
        label_w = min(max(12, len(label_text) + 1), max(12, width // 3))
        label_x = x + 2
        percent_x = x + width - len(percent) - 2
        bar_x = label_x + label_w
        bar_width = max(3, percent_x - bar_x - 1)
        canvas.text(label_x, y, label_text, 1, max_width=max(1, label_w - 1))
        canvas.progress_bar(bar_x, y, bar_width, value, style)
        canvas.text(percent_x, y, percent, style, max_width=max(1, x + width - percent_x - 1))

    def _topology_spec(self) -> tuple[str, dict[str, tuple[float, float]], list[tuple[str, str]], tuple[list[str], ...]]:
        variants = (
            (
                "LAYERED MESH",
                {
                    "ENTRY": (0.05, 0.50), "P1": (0.24, 0.22), "P2": (0.24, 0.76),
                    "N1": (0.46, 0.12), "N2": (0.46, 0.50), "N3": (0.46, 0.88),
                    "GATE": (0.66, 0.50), "FW": (0.82, 0.50), "TARGET": (0.96, 0.50),
                },
                [("ENTRY", "P1"), ("ENTRY", "P2"), ("P1", "N1"), ("P1", "N2"), ("P2", "N2"), ("P2", "N3"), ("N1", "GATE"), ("N2", "GATE"), ("N3", "GATE"), ("GATE", "FW"), ("FW", "TARGET")],
                (["ENTRY", "P1", "N1", "GATE", "FW", "TARGET"], ["ENTRY", "P1", "N2", "GATE", "FW", "TARGET"], ["ENTRY", "P2", "N3", "GATE", "FW", "TARGET"]),
            ),
            (
                "RING RELAY",
                {
                    "ENTRY": (0.06, 0.50), "P1": (0.22, 0.16), "P2": (0.22, 0.84),
                    "N1": (0.44, 0.08), "N2": (0.44, 0.92), "N3": (0.57, 0.50),
                    "GATE": (0.70, 0.16), "FW": (0.70, 0.84), "TARGET": (0.95, 0.50),
                },
                [("ENTRY", "P1"), ("ENTRY", "P2"), ("P1", "N1"), ("P2", "N2"), ("N1", "GATE"), ("N2", "FW"), ("GATE", "N3"), ("FW", "N3"), ("GATE", "FW"), ("N3", "TARGET")],
                (["ENTRY", "P1", "N1", "GATE", "N3", "TARGET"], ["ENTRY", "P2", "N2", "FW", "N3", "TARGET"]),
            ),
            (
                "BRIDGED CLUSTER",
                {
                    "ENTRY": (0.05, 0.50), "P1": (0.22, 0.34), "P2": (0.22, 0.66),
                    "N1": (0.43, 0.18), "N2": (0.43, 0.50), "N3": (0.43, 0.82),
                    "GATE": (0.64, 0.50), "FW": (0.80, 0.30), "TARGET": (0.95, 0.50),
                },
                [("ENTRY", "P1"), ("ENTRY", "P2"), ("P1", "N1"), ("P1", "N2"), ("P2", "N2"), ("P2", "N3"), ("N1", "N2"), ("N2", "N3"), ("N1", "GATE"), ("N2", "GATE"), ("N3", "GATE"), ("GATE", "FW"), ("FW", "TARGET")],
                (["ENTRY", "P1", "N1", "GATE", "FW", "TARGET"], ["ENTRY", "P1", "N2", "GATE", "FW", "TARGET"], ["ENTRY", "P2", "N3", "GATE", "FW", "TARGET"]),
            ),
            (
                "ZIGZAG BACKBONE",
                {
                    "ENTRY": (0.05, 0.74), "P1": (0.20, 0.26), "P2": (0.30, 0.74),
                    "N1": (0.40, 0.18), "N2": (0.50, 0.68), "N3": (0.62, 0.30),
                    "GATE": (0.72, 0.72), "FW": (0.82, 0.26), "TARGET": (0.95, 0.50),
                },
                [("ENTRY", "P1"), ("ENTRY", "P2"), ("P1", "N1"), ("P1", "N2"), ("P2", "N2"), ("N1", "N3"), ("N2", "N3"), ("N2", "GATE"), ("N3", "FW"), ("GATE", "FW"), ("FW", "TARGET")],
                (["ENTRY", "P1", "N1", "N3", "FW", "TARGET"], ["ENTRY", "P2", "N2", "GATE", "FW", "TARGET"], ["ENTRY", "P1", "N2", "GATE", "FW", "TARGET"]),
            ),
            (
                "SPLIT GATEWAY",
                {
                    "ENTRY": (0.05, 0.50), "P1": (0.20, 0.18), "P2": (0.20, 0.82),
                    "N1": (0.42, 0.28), "N2": (0.42, 0.72), "N3": (0.58, 0.50),
                    "GATE": (0.70, 0.20), "FW": (0.78, 0.76), "TARGET": (0.95, 0.50),
                },
                [("ENTRY", "P1"), ("ENTRY", "P2"), ("P1", "N1"), ("P2", "N2"), ("N1", "N3"), ("N2", "N3"), ("N1", "GATE"), ("N2", "FW"), ("N3", "GATE"), ("N3", "FW"), ("GATE", "TARGET"), ("FW", "TARGET")],
                (["ENTRY", "P1", "N1", "GATE", "TARGET"], ["ENTRY", "P2", "N2", "FW", "TARGET"], ["ENTRY", "P1", "N1", "N3", "FW", "TARGET"], ["ENTRY", "P2", "N2", "N3", "GATE", "TARGET"]),
            ),
        )
        return variants[self.topology_variant % len(variants)]

    def _topology_nodes(self, x: int, y: int, width: int, height: int) -> dict[str, tuple[int, int]]:
        _, layout, _, _ = self._topology_spec()
        left = x + 4
        right = x + width - 5
        top = y + 4
        bottom = y + height - 3
        span_x = max(12, right - left)
        span_y = max(6, bottom - top)
        return {name: (left + int(span_x * px), top + int(span_y * py)) for name, (px, py) in layout.items()}

    def _topology_edges(self) -> list[tuple[str, str]]:
        return self._topology_spec()[2]

    def _active_route(self) -> list[str]:
        routes = self._topology_spec()[3]
        return routes[self.route_variant % len(routes)]


    def _breach_state(self, route: list[str], progress: float) -> tuple[str, str, float]:
        if len(route) < 2:
            node = route[0] if route else "UNKNOWN"
            return node, node, 1.0
        if self.phase == "result" or progress >= 1.0:
            return route[-2], route[-1], 1.0
        scaled = max(0.0, min(0.999999, progress)) * (len(route) - 1)
        index = min(len(route) - 2, int(scaled))
        return route[index], route[index + 1], scaled - index

    def _breach_vector(self, target: str) -> str:
        if target.startswith("P"):
            return "PROXY HANDSHAKE"
        if target.startswith("N"):
            return "NODE AUTH TOKEN"
        if target == "GATE":
            return "GATEWAY SESSION KEY"
        if target == "FW":
            return "FIREWALL RULESET"
        if target == "TARGET":
            return "MASTER ACCESS TOKEN"
        return "REMOTE ACCESS VECTOR"

    def _breach_token(self, target: str) -> str:
        seed = self.operation_seed ^ sum((index + 1) * ord(char) for index, char in enumerate(target))
        rng = random.Random(seed)
        groups = []
        for _ in range(4):
            groups.append("".join(rng.choice("0123456789ABCDEF") for _ in range(4)))
        return "-".join(groups)

    def _decrypt_token(self, target: str, progress: float, now: float) -> str:
        final = self._breach_token(target)
        character_total = sum(1 for char in final if char != "-")
        resolved = int(max(0.0, min(1.0, progress)) * character_total)
        seed = self.operation_seed ^ sum((index + 7) * ord(char) for index, char in enumerate(target)) ^ int(now * 14.0)
        rng = random.Random(seed)
        output = []
        seen = 0
        for char in final:
            if char == "-":
                output.append(char)
                continue
            if seen < resolved:
                output.append(char)
            else:
                output.append("?" if rng.random() < 0.72 else rng.choice("0123456789ABCDEF"))
            seen += 1
        return "".join(output)

    def _breach_command(self, source: str, target: str, progress: float) -> str:
        vector = self._breach_vector(target)
        if progress < 0.18:
            return f"> PROBING {target} :: {vector}"
        if progress < 0.42:
            return f"> NEGOTIATING {source} -> {target}"
        if progress < 0.70:
            return f"> DECRYPTING {vector}"
        if progress < 0.92:
            return f"> VERIFYING REMOTE CREDENTIAL :: {target}"
        return f"> ACCESS VECTOR ACCEPTED :: {target}"

    def _draw_breach_console(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, route: list[str], progress: float, now: float) -> None:
        canvas.panel(x, y, width, height, "ACTIVE PROCESS", 2)
        if width < 24 or height < 6:
            return
        event, local = self._current_plan_event(progress)
        if event is None:
            return
        style = 4 if self.counter_started and now < self.counter_active_until else 3
        row = y + 1
        canvas.text(x + 2, row, f"STAGE: {event.label}", style, max_width=max(1, width - 4))
        row += 1
        if row < y + height - 1:
            tool = event.tool or "SIMULATION ENGINE"
            canvas.text(x + 2, row, f"TOOL: {tool}", 2, max_width=max(1, width - 4))
            row += 1
        if row < y + height - 1:
            self._draw_progress_row(canvas, x, row, width, event.meter or "PROCESS", local * 100.0, style)
            row += 1
        if row < y + height - 1:
            status = event.log
            canvas.text(x + 2, row, f"STATUS: {status}", style if local >= 0.80 else 1, max_width=max(1, width - 4))

    @staticmethod
    def _wipe_rect(canvas: TerminalCanvas, x: int, y: int, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        for row in range(max(0, y), min(canvas.height, y + height)):
            for column in range(max(0, x), min(canvas.width, x + width)):
                canvas.put(column, row, " ", 0)

    def _tool_profile(self, target: str) -> tuple[str, str, tuple[str, ...]]:
        if target.startswith("P"):
            return (
                "PROXY SESSION NEGOTIATOR",
                "SESSION",
                (
                    "[route] locating viable relay endpoint",
                    "[transport] negotiating remote handshake",
                    "[session] validating relay identity",
                    "[tunnel] synchronising forwarding channel",
                    "[proxy] route persistence check active",
                    "[latency] timing variance within tolerance",
                    "[session] relay context accepted",
                ),
            )
        if target.startswith("N"):
            return (
                "REMOTE SERVICE PROBE",
                "SERVICE MAP",
                (
                    "[host] remote service fingerprint acquired",
                    "[service] authentication boundary detected",
                    "[session] challenge response captured",
                    "[token] validating session material",
                    "[process] remote context map refreshed",
                    "[access] privilege boundary identified",
                    "[service] candidate session path accepted",
                ),
            )
        if target == "GATE":
            return (
                "SESSION KEY ANALYSIS",
                "CORRELATION",
                (
                    "[gateway] route table snapshot received",
                    "[crypto] protected session metadata observed",
                    "[session] key exchange pattern analysed",
                    "[auth] response correlation increasing",
                    "[timing] handshake cadence stabilised",
                    "[route] gateway pivot condition verified",
                    "[session] candidate key material accepted",
                ),
            )
        if target == "FW":
            return (
                "FIREWALL RULE ANALYSIS",
                "POLICY MAP",
                (
                    "[filter] ruleset snapshot acquired",
                    "[policy] ingress chain enumerated",
                    "[state] connection state model reconstructed",
                    "[route] permitted traversal path identified",
                    "[filter] candidate path validation running",
                    "[policy] conflicting rule branch isolated",
                    "[filter] traversal vector accepted",
                ),
            )
        if target == "TARGET":
            return (
                "ACCESS TOKEN RECOVERY",
                "TOKEN MATCH",
                (
                    "[target] service surface mapped",
                    "[auth] privileged token challenge captured",
                    "[session] access context reconstruction active",
                    "[token] candidate response correlation rising",
                    "[payload] execution channel negotiated",
                    "[target] final session validation running",
                    "[auth] privileged access context accepted",
                ),
            )
        return (
            "REMOTE ACCESS ANALYSER",
            "ACCESS",
            (
                "[remote] endpoint response received",
                "[session] access context under analysis",
                "[route] transport path verified",
                "[auth] remote response correlated",
                "[session] candidate context accepted",
            ),
        )

    def _tool_lines(self, target: str, local: float, now: float) -> tuple[str, str, list[str]]:
        title, meter, bank = self._tool_profile(target)
        seed = self.operation_seed ^ sum((index + 13) * ord(char) for index, char in enumerate(target))
        tick = int(now * 8.0)
        rng = random.Random(seed ^ tick)
        reveal = max(2, min(len(bank), 2 + int(local * (len(bank) - 1))))
        pool = list(bank[:reveal])
        rng.shuffle(pool)
        visible = pool[: min(5, len(pool))]
        phase_hex = random.Random(seed ^ int(local * 1000) ^ tick)
        code = "0x" + "".join(phase_hex.choice("0123456789ABCDEF") for _ in range(8))
        if local < 0.24:
            visible.append(f"[probe] candidate {code} queued")
        elif local < 0.58:
            visible.append(f"[analysis] candidate {code} correlated")
        elif local < 0.90:
            visible.append(f"[validate] response {code} accepted")
        else:
            visible.append(f"[complete] {self._breach_vector(target).lower()} verified")
        return title, meter, visible[-5:]

    def _draw_tool_window(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, title: str, meter: str, lines: list[str], percent: float, style: int) -> None:
        self._wipe_rect(canvas, x, y, width, height)
        canvas.panel(x, y, width, height, title, style)
        row = y + 2
        bottom = y + height - 2
        for line in lines:
            if row >= bottom:
                break
            canvas.text(x + 2, row, line, 2 if row < bottom - 1 else style, max_width=max(1, width - 4))
            row += 1
        if bottom > y + 1:
            self._draw_progress_row(canvas, x, bottom, width, meter, percent, style)

    def _draw_packet_monitor(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, source: str, target: str, local: float, now: float) -> None:
        active_counter = self.counter_started and now < self.counter_active_until
        location = self._value(self.current, "Location", "Remote")
        if active_counter:
            title = "COUNTER-INTRUSION MONITOR"
        elif location == "Local":
            title = "PROCESS MONITOR"
        elif location == "Internal Network":
            title = "INTERNAL ACTIVITY"
        else:
            title = "PACKET MONITOR"
        style = 4 if active_counter else 2
        self._wipe_rect(canvas, x, y, width, height)
        canvas.panel(x, y, width, height, title, style)
        if height < 4:
            return
        seed = self.operation_seed ^ int(now * 12.0) ^ sum(ord(char) for char in source + target)
        rng = random.Random(seed)
        row = y + 2
        bottom = y + height - 1
        if active_counter:
            entries = (
                f"DETECTION RISK  {self._trace_risk(self._progress(now), now):02.0f}%",
                "DEFENDER RESPONSE CHANNEL ACTIVE",
                "SESSION ROUTE REBALANCING",
                "COUNTER-ACTIVITY CONTAINMENT ACTIVE",
            )
        elif location == "Local":
            entries = tuple(
                f"PID {rng.randint(120, 9999):04d}  {rng.choice(('PROC','SVC','ACL','IO')):4s}  LOAD {rng.randint(1, 38):02d}%"
                for _ in range(5)
            )
        elif location == "Internal Network":
            entries = tuple(
                f"NODE-{rng.randint(1, 24):02d}  {rng.choice(('SMB','RDP','WINRM','SSH','AUTH')):5s}  {rng.randint(4, 42):02d}ms"
                for _ in range(5)
            )
        else:
            kinds = ("TLS", "AUTH", "ACK", "DATA", "SYNC")
            entries = tuple(
                f"{source}>{target}  {rng.choice(kinds):4s}  {rng.randint(64, 2048):04d}B  {rng.randint(8, 49):02d}ms"
                for _ in range(5)
            )
        for entry in entries:
            if row >= bottom:
                break
            canvas.text(x + 2, row, entry, style if active_counter else 2, max_width=max(1, width - 4))
            row += 1

    def _draw_hacking_popups(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, route: list[str], progress: float, now: float) -> None:
        if self.phase != "operation" or width < 38 or height < 15:
            return
        event, local = self._current_plan_event(progress)
        if event is None or local < 0.05:
            return
        main_w = min(width - 6, max(32, int(width * 0.68)))
        main_h = 9 if height >= 20 else 8
        event_index = self._stage_index(progress)
        main_x = x + 3 if event_index % 2 == 0 else x + width - main_w - 3
        main_y = y + 4
        style = 4 if self.counter_started and now < self.counter_active_until else 3
        lines = list(event.details)
        if not lines:
            lines = [f"[{event.kind}] {event.log.lower()}"]
        if local < 0.35:
            lines.append("[process] initial analysis active")
        elif local < 0.75:
            lines.append("[process] operation state advancing")
        else:
            lines.append("[process] stage validation nearing completion")
        self._draw_tool_window(
            canvas,
            main_x,
            main_y,
            main_w,
            main_h,
            event.tool or "SIMULATION ENGINE",
            event.meter or "PROCESS",
            lines[-5:],
            local * 100.0,
            style,
        )
        if height < 19 or local < 0.18 or local > 0.94:
            return
        monitor_w = min(width - 8, max(24, int(width * 0.48)))
        monitor_h = 6
        monitor_x = x + width - monitor_w - 3 if main_x == x + 3 else x + 3
        monitor_y = min(y + height - monitor_h - 2, main_y + main_h + 1)
        if monitor_y <= main_y + main_h - 1:
            monitor_y = y + height - monitor_h - 2
        source, target, _ = self._breach_state(route, self._breach_progress(progress) / 100.0)
        self._draw_packet_monitor(canvas, monitor_x, monitor_y, monitor_w, monitor_h, source, target, local, now)

    @staticmethod
    def _edge_points(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
        x1, y1 = start
        x2, y2 = end
        dx = x2 - x1
        dy = y2 - y1
        steps = max(abs(dx), abs(dy), 1)
        result = []
        seen = set()
        for index in range(steps + 1):
            amount = index / steps
            point = (int(round(x1 + dx * amount)), int(round(y1 + dy * amount)))
            if point not in seen:
                seen.add(point)
                result.append(point)
        return result

    def _topology_context(self) -> tuple[str, dict[str, str], str]:
        location = self._value(self.current, "Location", "Remote")
        if location == "Local":
            return (
                "SYSTEM ACCESS MAP",
                {"ENTRY": "EXEC", "P1": "USER", "P2": "PROC", "N1": "SVC1", "N2": "SVC2", "N3": "ACL", "GATE": "POLICY", "FW": "EDR", "TARGET": "TARGET"},
                "OPS/S",
            )
        if location == "Internal Network":
            return (
                "INTERNAL NETWORK MAP",
                {"ENTRY": "FOOT", "P1": "WS01", "P2": "WS02", "N1": "NODE1", "N2": "NODE2", "N3": "AUTH", "GATE": "SEG", "FW": "HOST", "TARGET": "TARGET"},
                "PKT/S",
            )
        return (
            "REMOTE ROUTE MAP",
            {"ENTRY": "ENTRY", "P1": "P-01", "P2": "P-02", "N1": "N-01", "N2": "N-02", "N3": "N-03", "GATE": "GATE", "FW": "FW", "TARGET": "TARGET"},
            "PKT/S",
        )

    def _draw_network_topology(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, progress: float, now: float) -> None:
        panel_title, labels, rate_unit = self._topology_context()
        canvas.panel(x, y, width, height, panel_title, 2)
        if width < 34 or height < 13:
            canvas.centered_text(y + height // 2, "TOPOLOGY VIEW REQUIRES MORE SPACE", 2, x + 2, x + width - 2)
            return
        trace = self._trace_risk(progress, now)
        topology_name = self._topology_spec()[0]
        route = self._active_route()
        status = f"{topology_name}   {self.traffic_rate + int(math.sin(now * 2.4) * 25):03d} {rate_unit}   DETECT {trace:02.0f}%"
        canvas.centered_text(y + 2, status, 1, x + 2, x + width - 2)
        nodes = self._topology_nodes(x, y, width, height)
        map_progress = min(1.0, progress * 1.9)
        edges = self._topology_edges()
        active_edges = set(zip(route, route[1:])) | set((b, a) for a, b in zip(route, route[1:]))
        for edge_index, (first, second) in enumerate(edges):
            reveal = (edge_index + 1) / max(1, len(edges))
            if map_progress + 0.08 < reveal:
                continue
            points = self._edge_points(nodes[first], nodes[second])
            active = (first, second) in active_edges
            for px, py in points[1:-1]:
                if x + 1 < px < x + width - 1 and y + 3 < py < y + height - 2:
                    canvas.put(px, py, "·", 2 if active else 1)
            if active and progress > 0.14 and len(points) > 2:
                speed = 6.0 + progress * 7.0
                phase = (now * speed + edge_index * 3.7) % max(1, len(points) - 2)
                if self.packet_direction < 0:
                    phase = (len(points) - 3) - phase
                packet_index = 1 + int(max(0, min(len(points) - 3, phase)))
                px, py = points[packet_index]
                canvas.put(px, py, "•", 4 if self.counter_started and now < self.counter_active_until else 3)
        node_order = ["ENTRY", "P1", "P2", "N1", "N2", "N3", "GATE", "FW", "TARGET"]
        route_index = {name: index for index, name in enumerate(route)}
        access_progress = self._breach_progress(progress) / 100.0
        route_progress = access_progress * max(1, len(route) - 1)
        for index, name in enumerate(node_order):
            reveal = index / max(1, len(node_order) - 1)
            if map_progress + 0.14 < reveal:
                continue
            px, py = nodes[name]
            label = labels[name]
            compromised = name in route_index and route_progress >= route_index[name]
            active = name in route_index and abs(route_progress - route_index[name]) < 0.75
            if name == "TARGET":
                has_access = self.plan is not None and any(event.kind == "access" for event in self.plan.events)
                if not has_access or access_progress < 0.95:
                    compromised = False
            if compromised:
                node_text = f"<{label}>"
                style = 4 if active else 3
            else:
                node_text = f"[{label}]"
                style = 2 if name in route_index else 1
            canvas.text(px - len(node_text) // 2, py, node_text, style, max_width=len(node_text))
        self._draw_hacking_popups(canvas, x, y, width, height, route, progress, now)
        if self.counter_started and now < self.counter_active_until:
            canvas.centered_text(y + height - 2, "COUNTER-INTRUSION ACTIVE", 4, x + 2, x + width - 2)

    def _draw_inline_analyser(self, canvas: TerminalCanvas, x: int, y: int, width: int, label: str, confidence: float, now: float, seed: int, style: int = 2) -> None:
        label_text = f"{label.upper()}: "
        canvas.text(x, y, label_text, 1, max_width=max(1, width))
        spectrum_x = x + len(label_text)
        spectrum_w = max(1, width - len(label_text))
        blocks = "▁▂▃▄▅▆▇█"
        confidence = max(0.0, min(1.0, confidence))
        rng = random.Random(seed ^ int(now * 11.0))
        output = []
        for index in range(spectrum_w):
            carrier = math.sin(index * 0.61 + now * 3.4 + seed % 7) * (0.45 + confidence * 0.45)
            harmonic = math.sin(index * 0.19 - now * 1.8) * 0.48
            noise = (rng.random() - 0.5) * (1.25 - confidence * 0.55)
            value = int(round((carrier + harmonic + noise + 1.8) / 3.6 * (len(blocks) - 1)))
            output.append(blocks[max(0, min(len(blocks) - 1, value))])
        canvas.text(spectrum_x, y, "".join(output), style, max_width=spectrum_w)

    def _session_activity(self, progress: float, now: float, width: int) -> str:
        seed = self.operation_seed ^ int(now * 9.0) ^ int(progress * 1000.0)
        rng = random.Random(seed)
        chunks = []
        for _ in range(max(1, width // 5 + 1)):
            chunks.append("".join(rng.choice("0123456789ABCDEF") for _ in range(4)))
        return " ".join(chunks)[:max(1, width)]

    def _draw_target_analysis(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, progress: float, now: float) -> None:
        canvas.panel(x, y, width, height, "TARGET ANALYSIS", 2)
        if self.current is None:
            canvas.centered_text(y + height // 2, "NO OPERATION DATA", 2, x + 2, x + width - 2)
            return
        label_x = x + 2
        value_x = x + min(20, max(14, width // 3))
        value_width = max(1, x + width - 2 - value_x)
        row = y + 2
        bottom = y + height - 2
        for label, key in self.TARGET_FIELDS:
            if row >= bottom - 2:
                break
            if key == "Rates":
                success = self._value(self.current, "SuccessRate", "0")
                glitch = self._value(self.current, "GlitchRate", "0")
                freeze = self._value(self.current, "FreezeRate", "0")
                hackback = self._value(self.current, "HackBackChance", "0")
                blocks = self._value(self.current, "BlockAttempts", "0")
                value = f"S{success}% G{glitch}% F{freeze}% H{hackback}% B{blocks}".upper()
            else:
                value = self._value(self.current, key).upper()
                if key == "Security":
                    value = f"{value}/100"
            visible = progress >= (row - (y + 1)) * 0.045
            display = value if visible else "ANALYSING..."
            canvas.text(label_x, row, f"{label}:", 1, max_width=max(1, value_x - label_x - 1))
            canvas.text(value_x, row, display, 3 if visible else 2, max_width=value_width)
            row += 1
        if row < bottom - 1:
            row += 1
        if row < bottom:
            self._draw_inline_analyser(canvas, x + 2, row, max(1, width - 4), "SECURITY ANALYSER", min(1.0, progress * 1.35), now, self.operation_seed ^ 0x51A7, 2)
            row += 1
        if row < bottom:
            self._draw_progress_row(canvas, x, row, width, "TARGET SCAN", self._target_scan(progress), 3)

    def _draw_intrusion_control(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, progress: float, now: float) -> None:
        canvas.panel(x, y, width, height, "INTRUSION CONTROL", 2)
        row = y + 2
        bottom = y + height - 2
        label_x = x + 2
        value_x = x + min(21, max(15, width // 3))
        canvas.text(label_x, row, "STAGE:", 1, max_width=max(1, value_x - label_x - 1))
        canvas.text(value_x, row, self._stage_name(progress), 4 if self.counter_started and now < self.counter_active_until else 3, max_width=max(1, x + width - value_x - 2))
        row += 2
        if row < bottom:
            self._draw_progress_row(canvas, x, row, width, "ACCESS PROGRESS", self._breach_progress(progress), 3)
            row += 2
        if row < bottom:
            trace = self._trace_risk(progress, now)
            self._draw_progress_row(canvas, x, row, width, "DETECTION RISK", trace, 4 if trace >= 70 else 3)
            row += 2
        if row < bottom:
            canvas.text(label_x, row, "ACCESS LEVEL:", 1, max_width=max(1, value_x - label_x - 1))
            canvas.text(value_x, row, self._access_level(progress), 3, max_width=max(1, x + width - value_x - 2))
            row += 1
        if row < bottom:
            objective = self._value(self.current, "Objective", "Unknown").upper()
            canvas.text(label_x, row, "OBJECTIVE:", 1, max_width=max(1, value_x - label_x - 1))
            canvas.text(value_x, row, objective, 2, max_width=max(1, x + width - value_x - 2))
            row += 1
        if row < bottom:
            row += 1
        if row < bottom:
            label = "SESSION ACTIVITY: "
            canvas.text(label_x, row, label, 1, max_width=max(1, width - 4))
            activity_x = label_x + len(label)
            activity_width = max(1, x + width - 2 - activity_x)
            canvas.text(activity_x, row, self._session_activity(progress, now, activity_width), 4 if self.counter_started and now < self.counter_active_until else 2, max_width=activity_width)

    def _draw_operation_log(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int) -> None:
        canvas.panel(x, y, width, height, "OPERATION LOG", 2)
        max_rows = max(1, height - 3)
        visible = self.log_entries[-max_rows:]
        start_y = y + 2
        for index, entry in enumerate(visible):
            style = 4 if any(token in entry for token in ("COUNTER", "TRACE LOCK", "TERMINATED", "FAILED", "ABORT")) else 3 if any(token in entry for token in ("ACQUIRED", "ESTABLISHED", "COMPLETE", "CONTAINED", "TARGET")) else 2
            canvas.text(x + 2, start_y + index, "> " + entry, style, max_width=max(1, width - 4))

    def _result_content(self) -> tuple[str, list[str]]:
        objective = self._value(self.current, "Objective", "Objective")
        if self.outcome == "FREEZE":
            return "PROCESS FROZEN", ["PROCESS UNRESPONSIVE", "RECOVERY FAILED", "OPERATION TERMINATED"]
        if self.outcome != "SUCCESS":
            return "OPERATION FAILED", ["AVAILABLE METHODS EXHAUSTED", "OBJECTIVE NOT COMPLETED", "SESSION CLOSED"]
        success_map = {
            "Download Files": ("FILES ACQUIRED", ["TRANSFER COMPLETE", "FILE SET VERIFIED", "OBJECTIVE COMPLETE"]),
            "Extract Database": ("DATABASE EXTRACTED", ["EXPORT COMPLETE", "RECORD SET VERIFIED", "OBJECTIVE COMPLETE"]),
            "Steal Personal Information": ("PERSONAL DATA ACQUIRED", ["PROFILE SET COLLECTED", "TRANSFER VERIFIED", "OBJECTIVE COMPLETE"]),
            "Steal Financial Information": ("FINANCIAL DATA ACQUIRED", ["FINANCIAL RECORDS COLLECTED", "EXPORT VERIFIED", "OBJECTIVE COMPLETE"]),
            "Steal Intellectual Property": ("INTELLECTUAL PROPERTY ACQUIRED", ["PROJECT MATERIAL COLLECTED", "TRANSFER VERIFIED", "OBJECTIVE COMPLETE"]),
            "Steal Emails / Messages": ("COMMUNICATIONS ACQUIRED", ["MESSAGE EXPORT COMPLETE", "ATTACHMENTS VERIFIED", "OBJECTIVE COMPLETE"]),
            "Capture Login Information": ("LOGIN INFORMATION CAPTURED", ["AUTH MATERIAL DETECTED", "VALIDATION COMPLETE", "OBJECTIVE COMPLETE"]),
            "Hijack Account": ("ACCOUNT CONTROLLED", ["TARGET SESSION ACTIVE", "RESOURCE ACCESS VERIFIED", "OBJECTIVE COMPLETE"]),
            "Profile Target": ("PROFILE COMPLETE", ["TARGET DOSSIER GENERATED", "RELATIONSHIPS CORRELATED", "OBJECTIVE COMPLETE"]),
            "Plant Bug": ("SURVEILLANCE ACTIVE", ["CAPTURE CHANNELS VERIFIED", "RECURRING MONITOR ACTIVE", "OBJECTIVE COMPLETE"]),
            "Create Back Door": ("BACK DOOR VERIFIED", ["PERSISTENT ACCESS ACTIVE", "RECONNECT TEST PASSED", "OBJECTIVE COMPLETE"]),
            "Disable Security": ("SECURITY DEGRADED", ["DEFENSIVE CONTROLS SUPPRESSED", "MONITORING REDUCED", "OBJECTIVE COMPLETE"]),
            "Disrupt System": ("SYSTEM DISRUPTED", ["TARGET AVAILABILITY FAILED", "CRITICAL SERVICES OFFLINE", "OBJECTIVE COMPLETE"]),
            "Destroy Data": ("DATA DESTROYED", ["TARGET DATA UNAVAILABLE", "DESTRUCTION VERIFIED", "OBJECTIVE COMPLETE"]),
            "Encrypt Files": ("FILES LOCKED", ["TARGET DATA ENCRYPTED", "NORMAL ACCESS DENIED", "OBJECTIVE COMPLETE"]),
            "Deface System / Website": ("DEFACEMENT LIVE", ["VISIBLE CONTENT MODIFIED", "PUBLISH STATE VERIFIED", "OBJECTIVE COMPLETE"]),
            "Manipulate Data": ("DATA ALTERED", ["TARGET RECORDS MODIFIED", "CHANGES VERIFIED", "OBJECTIVE COMPLETE"]),
            "Financial Theft": ("FUNDS TRANSFERRED", ["SIMULATED TRANSACTION CONFIRMED", "LEDGER STATE UPDATED", "OBJECTIVE COMPLETE"]),
            "Penetration Test": ("PENETRATION TEST COMPLETE", ["FINDINGS VALIDATED", "TEST STATE CLEANED", "REPORT GENERATED"]),
        }
        return success_map.get(objective, ("OPERATION COMPLETE", ["TARGET ACCESS CONFIRMED", "OBJECTIVE COMPLETE", "SESSION CLOSED"]))

    def _draw_result_overlay(self, canvas: TerminalCanvas) -> None:
        if self.phase != "result":
            return
        title, lines = self._result_content()
        canvas.overlay_center_box(title, lines, width=min(58, max(38, canvas.width // 2)))

    def _draw_layout(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        canvas = self.ui.canvas(width, height)
        if width < 82 or height < 28:
            canvas.overlay_center_box("HACKER PROTOCOL", ["TERMINAL TOO SMALL", "Resize to at least 82 x 28", "Network topology requires working space"])
            return canvas
        progress = self._progress(now)
        left_width = max(36, width // 2)
        left_width = min(width - 36, left_width)
        right_width = width - left_width
        breach_height = 8 if height >= 32 else 7
        topology_height = max(13, height - breach_height)
        breach_height = height - topology_height
        target_height = 12
        intrusion_height = 13
        if target_height + intrusion_height > height - 6:
            overflow = target_height + intrusion_height - (height - 6)
            reduce_intrusion = min(overflow, max(0, intrusion_height - 9))
            intrusion_height -= reduce_intrusion
            overflow -= reduce_intrusion
            target_height = max(9, target_height - overflow)
        log_height = max(5, height - target_height - intrusion_height)
        route = self._active_route()
        self._draw_network_topology(canvas, 0, 0, left_width, topology_height, progress, now)
        self._draw_breach_console(canvas, 0, topology_height, left_width, breach_height, route, progress, now)
        self._draw_target_analysis(canvas, left_width, 0, right_width, target_height, progress, now)
        self._draw_intrusion_control(canvas, left_width, target_height, right_width, intrusion_height, progress, now)
        self._draw_operation_log(canvas, left_width, target_height + intrusion_height, right_width, log_height)
        self._draw_result_overlay(canvas)
        return canvas

    def _advance_state(self, settings: dict, now: float) -> None:
        if self.current is None or self.plan is None:
            self._start_operation(settings, now)
            return
        progress = self._progress(now)
        self._update_logs(now, progress)
        if self.glitch_at is not None and now >= self.glitch_at:
            self.glitch_until = max(self.glitch_until, now + random.uniform(0.22, 0.55))
            self.glitch_at = None
            self._append_log("VISUAL SIGNAL GLITCH DETECTED")
        if self.phase == "operation" and now >= self.operation_ends:
            self.phase = "result"
            self.phase_started = now
            self.result_ends = now + self.result_duration
            if self.outcome == "SUCCESS":
                self._append_log("OBJECTIVE COMPLETE")
                self._append_log("OPERATION CLOSED")
            elif self.outcome == "FREEZE":
                self._append_log("PROCESS UNRESPONSIVE")
                self._append_log("RECOVERY FAILED")
                self.glitch_until = max(self.glitch_until, now + 0.70)
            else:
                self._append_log("OPERATION FAILED")
                self._append_log("OBJECTIVE NOT COMPLETED")
                self.glitch_until = max(self.glitch_until, now + 0.45)
            return
        if self.phase == "result" and now >= self.result_ends:
            self._start_operation(settings, now)

    def render(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        self._advance_state(settings, now)
        canvas = self._draw_layout(width, height, settings, now)
        if now < self.glitch_until:
            self.ui.apply_glitch(canvas, self.characters, 0.20 if self.counter_started else 0.15, int(now * 24))
        return canvas

    def handle_runtime_key(self, key: str, settings: dict) -> bool:
        if key in {"+", "="}:
            old = max(40.0, min(220.0, float(settings.get("Pace", 100.0))))
            new = min(220.0, old + 10.0)
            settings["Pace"] = new
            if self.phase == "operation":
                factor = old / new
                elapsed = max(0.0, time.monotonic() - self.phase_started)
                remaining = max(0.5, self.operation_duration - elapsed) * factor
                self.operation_duration = elapsed + remaining
                self.operation_ends = self.phase_started + self.operation_duration
            return True
        if key in {"-", "_"}:
            old = max(40.0, min(220.0, float(settings.get("Pace", 100.0))))
            new = max(40.0, old - 10.0)
            settings["Pace"] = new
            if self.phase == "operation":
                factor = old / new
                elapsed = max(0.0, time.monotonic() - self.phase_started)
                remaining = max(0.5, self.operation_duration - elapsed) * factor
                self.operation_duration = elapsed + remaining
                self.operation_ends = self.phase_started + self.operation_duration
            return True
        if key == "BACKSPACE":
            self.reverse_direction(settings)
            return True
        return False

    def reverse_direction(self, settings: dict) -> None:
        self.packet_direction *= -1

    def primary_speed_label(self, settings: dict) -> str:
        return f"Simulation Pace {float(settings.get('Pace', 100.0)):g}%"


PROTOCOL_CLASS = TerminalSSHackerProtocol
