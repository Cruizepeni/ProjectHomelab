from __future__ import annotations

import math
import random
import time
from typing import Any

from TerminalSSUI import TerminalCanvas, TerminalSSUI


class TerminalSSCockpitProtocol:
    PROTOCOL_ID = "Cockpit"
    KEY = "0"
    ALLOW_MISSING_ASSETS = True
    DEFAULT_SETTINGS = {
        "StarDensity": 65,
        "CruiseThrottle": 42,
        "DemoReturnTime": 20.0,
        "AutoEvents": True,
        "Color": "Cyan",
        "RGB": False,
        "RGBSpeed": 50,
        "CustomColorShift": False,
        "CustomColorShiftSpeed": 50,
        "CustomColorShiftColors": ["Cyan", "Electric Blue", "Mint"],
    }
    SETTING_SCHEMA = {
        "StarDensity": {"Label": "Star Density", "Type": "percent"},
        "CruiseThrottle": {"Label": "Autopilot Cruise Throttle", "Type": "percent"},
        "DemoReturnTime": {"Label": "Return To Autopilot After", "Type": "seconds", "Min": 5, "Max": 300},
        "AutoEvents": {"Label": "Automatic Flight Events", "Type": "boolean"},
        "Color": {"Label": "Color", "Type": "color"},
        "RGB": {"Label": "RGB", "Type": "boolean"},
        "RGBSpeed": {"Label": "RGB Speed", "Type": "percent"},
        "CustomColorShift": {"Label": "Custom Color Shift", "Type": "boolean"},
        "CustomColorShiftSpeed": {"Label": "Custom Color Shift Speed", "Type": "percent"},
        "CustomColorShiftColors": {"Label": "Custom Color Shift Colors", "Type": "color_list"},
    }
    EVENT_MESSAGES = (
        "NAVIGATION BEACON ACQUIRED",
        "LONG-RANGE SCAN COMPLETE",
        "COURSE CORRECTION CALCULATED",
        "DEEP SPACE TELEMETRY NOMINAL",
        "UNIDENTIFIED CONTACT AT EXTREME RANGE",
        "GRAVITATIONAL SHEAR WITHIN TOLERANCE",
        "STARBOARD SENSOR ARRAY CALIBRATED",
        "PASSIVE COMMS SWEEP COMPLETE",
        "ENGINE CORE TEMPERATURE NOMINAL",
        "AUTOPILOT ROUTE OPTIMISED",
        "MICROMETEORITE FIELD DETECTED",
        "DISTANT PULSAR LOCKED FOR NAVIGATION",
    )
    RADAR_RANGES = (5, 25, 100, 500)

    @classmethod
    def settings_contract(cls) -> dict[str, Any]:
        return {"Defaults": cls.DEFAULT_SETTINGS, "Schema": cls.SETTING_SCHEMA}

    @classmethod
    def ensure_assets(cls, asset_manager):
        return None

    @classmethod
    def repair_assets(cls, asset_manager):
        return "built-in"

    @classmethod
    def rebuild_assets(cls, asset_manager):
        return "built-in"

    def __init__(self, asset_manager, ui: TerminalSSUI):
        self.asset_manager = asset_manager
        self.ui = ui
        self.stars: list[dict[str, float]] = []
        self.throttle = 0.0
        self.heading = 0.0
        self.heading_velocity = 0.0
        self.autopilot = True
        self.last_input = 0.0
        self.last_update = 0.0
        self.shields = True
        self.lights = True
        self.radar_index = 1
        self.radar_contacts: list[tuple[float, float]] = []
        self.next_radar_refresh = 0.0
        self.status_message = "FLIGHT SYSTEMS ONLINE"
        self.next_event = 0.0
        self.ftl_state = "idle"
        self.ftl_started = 0.0
        self.ftl_until = 0.0
        self.pre_jump_throttle = 0.0
        self.distance = 0.0
        self.engine_heat = 18.0

    def help_lines(self) -> list[str]:
        return [
            "COCKPIT CONTROLS",
            "UP / DOWN      Throttle",
            "LEFT / RIGHT   Heading",
            "A              Toggle autopilot",
            "J              Engage FTL jump",
            "R              Radar range",
            "S              Shields",
            "L              Cockpit lights",
        ]

    def _star_count(self, settings: dict, width: int, height: int) -> int:
        density = max(0, min(100, int(settings.get("StarDensity", 65))))
        area = max(1, width * height)
        return max(12, min(220, int(area / 55 * (0.3 + density / 100.0))))

    @staticmethod
    def _new_star() -> dict[str, float]:
        angle = random.random() * math.tau
        radius = math.sqrt(random.random()) * 1.25
        return {
            "x": math.cos(angle) * radius,
            "y": math.sin(angle) * radius * 0.72,
            "z": random.uniform(0.10, 1.0),
            "twinkle": random.random() * math.tau,
        }

    def _ensure_stars(self, settings: dict, width: int, height: int) -> None:
        target = self._star_count(settings, width, height)
        while len(self.stars) < target:
            self.stars.append(self._new_star())
        if len(self.stars) > target:
            self.stars = self.stars[:target]

    def _refresh_radar(self, now: float) -> None:
        self.radar_contacts = []
        count = random.randint(1, 5)
        for _ in range(count):
            angle = random.random() * math.tau
            radius = math.sqrt(random.random()) * 0.95
            self.radar_contacts.append((math.cos(angle) * radius, math.sin(angle) * radius))
        self.next_radar_refresh = now + random.uniform(3.0, 6.0)

    def reset(self, settings: dict, width: int, height: int, now: float | None = None) -> None:
        base = time.monotonic() if now is None else now
        self.stars = []
        self.throttle = float(max(0, min(100, int(settings.get("CruiseThrottle", 42)))))
        self.heading = random.uniform(0.0, 360.0)
        self.heading_velocity = 0.0
        self.autopilot = True
        self.last_input = base
        self.last_update = base
        self.shields = True
        self.lights = True
        self.radar_index = 1
        self.status_message = "FLIGHT SYSTEMS ONLINE"
        self.next_event = base + 3.0
        self.ftl_state = "idle"
        self.ftl_started = 0.0
        self.ftl_until = 0.0
        self.pre_jump_throttle = self.throttle
        self.distance = 0.0
        self.engine_heat = 18.0
        self._ensure_stars(settings, width, height)
        self._refresh_radar(base)

    def _manual_input(self) -> None:
        self.autopilot = False
        self.last_input = time.monotonic()

    def _start_jump(self, now: float) -> None:
        if self.ftl_state != "idle":
            return
        self._manual_input()
        self.pre_jump_throttle = self.throttle
        self.ftl_state = "charging"
        self.ftl_started = now
        self.ftl_until = now + 2.5
        self.status_message = "FTL DRIVE CHARGING"

    def handle_runtime_key(self, key: str, settings: dict) -> bool:
        normalized = str(key or "")
        letter = normalized.casefold()
        now = time.monotonic()
        if normalized == "UP":
            self._manual_input()
            self.throttle = min(100.0, self.throttle + 5.0)
            return True
        if normalized == "DOWN":
            self._manual_input()
            self.throttle = max(0.0, self.throttle - 5.0)
            return True
        if normalized == "LEFT":
            self._manual_input()
            self.heading_velocity = max(-22.0, self.heading_velocity - 5.0)
            return True
        if normalized == "RIGHT":
            self._manual_input()
            self.heading_velocity = min(22.0, self.heading_velocity + 5.0)
            return True
        if letter == "a":
            self.last_input = now
            self.autopilot = not self.autopilot
            self.status_message = "AUTOPILOT ENGAGED" if self.autopilot else "MANUAL FLIGHT CONTROL"
            return True
        if letter == "j":
            self._start_jump(now)
            return True
        if letter == "r":
            self._manual_input()
            self.radar_index = (self.radar_index + 1) % len(self.RADAR_RANGES)
            self._refresh_radar(now)
            self.status_message = f"RADAR RANGE {self.RADAR_RANGES[self.radar_index]} AU"
            return True
        if letter == "s":
            self._manual_input()
            self.shields = not self.shields
            self.status_message = "SHIELDS ONLINE" if self.shields else "SHIELDS STANDBY"
            return True
        if letter == "l":
            self._manual_input()
            self.lights = not self.lights
            self.status_message = "COCKPIT LIGHTS ON" if self.lights else "COCKPIT LIGHTS DIMMED"
            return True
        return False

    def _autopilot_update(self, settings: dict, dt: float, now: float) -> None:
        target = float(max(0, min(100, int(settings.get("CruiseThrottle", 42)))))
        delta = target - self.throttle
        self.throttle += max(-10.0 * dt, min(10.0 * dt, delta))
        self.heading_velocity += math.sin(now * 0.17) * 0.35 * dt
        self.heading_velocity = max(-3.0, min(3.0, self.heading_velocity))

    def _update_ftl(self, now: float) -> None:
        if self.ftl_state == "charging" and now >= self.ftl_until:
            self.ftl_state = "jump"
            self.ftl_started = now
            self.ftl_until = now + 2.2
            self.status_message = "FTL DRIVE ENGAGED"
        elif self.ftl_state == "jump" and now >= self.ftl_until:
            self.ftl_state = "idle"
            self.ftl_started = now
            self.ftl_until = 0.0
            self.throttle = max(self.pre_jump_throttle, 25.0)
            self.status_message = "FTL EXIT • NAVIGATION LOCK RESTORED"
            for star in self.stars:
                star["z"] = random.uniform(0.12, 1.0)

    def _update_stars(self, dt: float) -> None:
        if self.ftl_state == "jump":
            speed = 2.7
        else:
            speed = 0.035 + (self.throttle / 100.0) ** 1.35 * 0.75
        drift = self.heading_velocity / 180.0
        for star in self.stars:
            star["z"] -= speed * dt
            star["x"] -= drift * dt * max(0.25, 1.2 - star["z"])
            if star["z"] <= 0.035 or abs(star["x"]) > 1.7 or abs(star["y"]) > 1.25:
                replacement = self._new_star()
                replacement["z"] = 1.0
                star.update(replacement)

    def _update(self, settings: dict, now: float, width: int, height: int) -> None:
        self._ensure_stars(settings, width, height)
        timeout = max(5.0, float(settings.get("DemoReturnTime", 20.0)))
        if not self.autopilot and now - self.last_input >= timeout:
            self.autopilot = True
            self.status_message = "AUTOPILOT RESUMED"
        dt = max(0.0, min(0.10, now - self.last_update))
        self.last_update = now
        self._update_ftl(now)
        if self.autopilot and self.ftl_state == "idle":
            self._autopilot_update(settings, dt, now)
        self.heading += self.heading_velocity * dt
        self.heading %= 360.0
        self.heading_velocity *= max(0.0, 1.0 - dt * 1.8)
        self._update_stars(dt)
        velocity = self._velocity()
        self.distance += velocity * dt / 3600.0
        target_heat = 18.0 + self.throttle * 0.62 + (25.0 if self.ftl_state == "jump" else 0.0)
        self.engine_heat += (target_heat - self.engine_heat) * min(1.0, dt * 0.8)
        if now >= self.next_radar_refresh:
            self._refresh_radar(now)
        if bool(settings.get("AutoEvents", True)) and now >= self.next_event and self.ftl_state == "idle":
            self.status_message = random.choice(self.EVENT_MESSAGES)
            self.next_event = now + random.uniform(5.0, 10.0)

    def _velocity(self) -> float:
        if self.ftl_state == "jump":
            return 299792.0 * 18.0
        return (self.throttle / 100.0) ** 1.55 * 38000.0

    def _rpm(self) -> int:
        if self.ftl_state == "jump":
            return 9999
        return int(850 + self.throttle * 76.0)

    def _project_star(self, star: dict[str, float], width: int, height: int) -> tuple[int, int] | None:
        z = max(0.03, star["z"])
        scale_x = width * 0.42
        scale_y = height * 0.42
        x = int(round(width / 2 + star["x"] / z * scale_x))
        y = int(round(height / 2 + star["y"] / z * scale_y))
        if 0 <= x < width and 0 <= y < height:
            return x, y
        return None

    def _draw_starfield(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, now: float) -> None:
        center_x = x + width // 2
        center_y = y + height // 2
        for star in self.stars:
            point = self._project_star(star, width, height)
            if point is None:
                continue
            sx = x + point[0]
            sy = y + point[1]
            z = star["z"]
            char = "." if z > 0.72 else "·" if z > 0.48 else "*" if z > 0.24 else "+"
            style = 1 if z > 0.70 else 2 if z > 0.42 else 3
            canvas.put(sx, sy, char, style)
            streak = 0
            if self.ftl_state == "jump":
                streak = 8
            elif self.throttle >= 82:
                streak = 3
            elif self.throttle >= 62 and z < 0.35:
                streak = 1
            if streak:
                dx = sx - center_x
                dy = sy - center_y
                magnitude = max(1.0, math.hypot(dx, dy))
                ux = dx / magnitude
                uy = dy / magnitude
                for step in range(1, streak + 1):
                    tx = int(round(sx - ux * step))
                    ty = int(round(sy - uy * step * 0.55))
                    canvas.put(tx, ty, "─" if abs(dx) >= abs(dy) else "│", max(1, style - 1), False)

    def _draw_bracing(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int) -> None:
        depth = min(6, max(2, width // 18))
        for step in range(depth):
            if y + step < y + height:
                canvas.put(x + step, y + step, "\\", 2)
                canvas.put(x + width - 1 - step, y + step, "/", 2)
            bottom = y + height - 1 - step
            if bottom >= y:
                canvas.put(x + step, bottom, "/", 2)
                canvas.put(x + width - 1 - step, bottom, "\\", 2)
        canvas.text(x + 2, y + 1, f"HDG {self.heading:06.1f}°", 3)
        mode = "AUTO" if self.autopilot else "MANUAL"
        canvas.text(max(x + 2, x + width - 16), y + 1, mode, 3)

    def _draw_radar(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int) -> None:
        canvas.panel(x, y, width, height, f"RADAR {self.RADAR_RANGES[self.radar_index]} AU", 1)
        if width < 8 or height < 5:
            return
        cx = x + width // 2
        cy = y + height // 2
        radius_x = max(2, width // 2 - 3)
        radius_y = max(1, height // 2 - 2)
        canvas.put(cx, cy, "+", 4)
        for rx, ry in self.radar_contacts:
            px = cx + int(round(rx * radius_x))
            py = cy + int(round(ry * radius_y))
            canvas.put(px, py, "•", 3)

    def _draw_instruments(self, canvas: TerminalCanvas, y: int, height: int, width: int) -> None:
        if height < 5:
            return
        gap = 1
        left_width = max(20, width // 3)
        center_width = max(24, width // 3)
        right_x = left_width + center_width + gap * 2
        right_width = max(1, width - right_x)
        center_x = left_width + gap
        self._draw_radar(canvas, 0, y, left_width, height)
        canvas.panel(center_x, y, center_width, height, "PROPULSION", 1)
        row = y + 2
        if row < y + height - 1:
            canvas.text(center_x + 2, row, "THROTTLE", 2)
            bar_x = center_x + 12
            bar_width = max(5, center_width - 23)
            canvas.progress_bar(bar_x, row, bar_width, self.throttle, 3)
            canvas.text(bar_x + bar_width + 1, row, f"{self.throttle:3.0f}%", 3)
            row += 1
        if row < y + height - 1:
            rpm_percent = min(100.0, self._rpm() / 100.0)
            canvas.text(center_x + 2, row, "ENGINE RPM", 2)
            bar_x = center_x + 12
            bar_width = max(5, center_width - 23)
            canvas.progress_bar(bar_x, row, bar_width, rpm_percent, 3)
            canvas.text(bar_x + bar_width + 1, row, f"{self._rpm():4d}", 3)
            row += 1
        if row < y + height - 1:
            canvas.text(center_x + 2, row, f"VEL {self._velocity():,.0f} KM/S", 2, max_width=center_width - 4)
        if right_width >= 8:
            canvas.panel(right_x, y, right_width, height, "SYSTEMS", 1)
            system_rows = [
                ("SHIELDS", "ONLINE" if self.shields else "STANDBY"),
                ("LIGHTS", "ON" if self.lights else "DIM"),
                ("CORE", f"{self.engine_heat:3.0f} C"),
            ]
            for index, (label, value) in enumerate(system_rows):
                row_y = y + 2 + index
                if row_y < y + height - 1:
                    canvas.text(right_x + 2, row_y, f"{label:<8} {value}", 3 if value not in {"STANDBY", "DIM"} else 1, max_width=right_width - 4)

    def _draw_ftl(self, canvas: TerminalCanvas, now: float) -> None:
        if self.ftl_state == "idle":
            return
        duration = max(0.001, self.ftl_until - self.ftl_started)
        progress = max(0.0, min(1.0, (now - self.ftl_started) / duration))
        if self.ftl_state == "charging":
            lines = ["FTL DRIVE CHARGING", f"{progress * 100:3.0f}%"]
            canvas.overlay_center_box("JUMP DRIVE", lines, 38)
        else:
            canvas.overlay_center_box("FTL ENGAGED", ["SPACETIME VECTOR LOCKED", f"JUMP {progress * 100:3.0f}%"], 42)

    def render(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        self._update(settings, now, width, height)
        canvas = self.ui.canvas(width, height)
        instrument_height = max(7, min(10, height // 4))
        viewport_height = max(6, height - instrument_height - 1)
        canvas.panel(0, 0, width, viewport_height, "COCKPIT // " + ("AUTOPILOT" if self.autopilot else "MANUAL"), 2)
        if viewport_height > 2:
            self._draw_starfield(canvas, 1, 1, max(1, width - 2), max(1, viewport_height - 2), now)
            self._draw_bracing(canvas, 1, 1, max(1, width - 2), max(1, viewport_height - 2))
        instrument_y = viewport_height
        self._draw_instruments(canvas, instrument_y, max(1, height - instrument_y), width)
        status_y = max(1, viewport_height - 2)
        canvas.centered_text(status_y, self.status_message, 4 if self.ftl_state != "idle" else 2, 2, max(3, width - 2))
        if viewport_height >= 7:
            canvas.centered_text(viewport_height - 3, "↑↓ THROTTLE   ←→ HEADING   A AUTO   J FTL   R RADAR   S SHIELDS   L LIGHTS", 1, 2, max(3, width - 2))
        self._draw_ftl(canvas, now)
        return canvas

    def reverse_direction(self, settings: dict) -> None:
        self.heading_velocity *= -1

    def primary_speed_label(self, settings: dict) -> str:
        mode = "Autopilot" if self.autopilot else "Manual"
        return f"Cockpit {mode} • Throttle {self.throttle:.0f}% • Heading {self.heading:.0f}°"


PROTOCOL_CLASS = TerminalSSCockpitProtocol
