from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Any

from TerminalSSUI import TerminalSSUI, TerminalCanvas, display_width


class AlienRainStream:
    def __init__(self, height: int, direction: int):
        self.head = random.uniform(-height, height * 1.5)
        minimum = max(10, min(16, height))
        maximum = max(minimum, min(40, height + 16))
        self.length = random.randint(minimum, maximum)
        self.speed = random.uniform(0.18, 0.52)
        self.glyphs: list[str] = []
        self.direction = direction

    def reset(self, height: int, direction: int) -> None:
        self.direction = direction
        if direction > 0:
            self.head = random.uniform(-height, -1)
        else:
            self.head = random.uniform(height + 1, height * 2)
        minimum = max(10, min(16, height))
        maximum = max(minimum, min(40, height + 16))
        self.length = random.randint(minimum, maximum)
        self.speed = random.uniform(0.18, 0.52)
        self.glyphs = []

    def ensure_glyphs(self, pool: tuple[str, ...]) -> None:
        if len(self.glyphs) != self.length + 1:
            self.glyphs = [random.choice(pool) for _ in range(self.length + 1)]

    def advance(self, height: int, direction: int) -> None:
        self.direction = direction
        self.head += self.speed * direction
        if direction > 0 and self.head - self.length > height:
            self.reset(height, direction)
        elif direction < 0 and self.head + self.length < 0:
            self.reset(height, direction)

    def randomize(self, pool: tuple[str, ...]) -> None:
        if not self.glyphs:
            return
        self.glyphs[random.randrange(len(self.glyphs))] = random.choice(pool)


class TerminalSSAlienProtocol:
    PROTOCOL_ID = "Alien"
    KEY = "4"
    DEFAULT_SETTINGS = {
        "TransmissionDecodeTime": 12.0,
        "BaseMessageDisplayTime": 5.0,
        "SecondaryLineDisplayTime": 3.0,
        "GlitchChance": 10,
        "FailedDecryptionGlitchChance": 100,
        "Color": "Aqua",
        "RGB": False,
        "RGBSpeed": 50,
        "CustomColorShift": False,
        "CustomColorShiftSpeed": 50,
        "CustomColorShiftColors": ["Aqua", "Cyan", "Matrix Green"],
    }
    SETTING_SCHEMA = {
        "TransmissionDecodeTime": {"Label": "Base Transmission Decode Time", "Type": "seconds", "Min": 2, "Max": 120},
        "BaseMessageDisplayTime": {"Label": "Base Message Display Time", "Type": "seconds", "Min": 1, "Max": 120},
        "SecondaryLineDisplayTime": {"Label": "Secondary Line Display Time", "Type": "seconds", "Min": 0, "Max": 120},
        "GlitchChance": {"Label": "Glitch Rate", "Type": "percent"},
        "FailedDecryptionGlitchChance": {"Label": "Glitch Rate For Failed Decryption", "Type": "percent"},
        "Color": {"Label": "Color", "Type": "color"},
        "RGB": {"Label": "RGB", "Type": "boolean"},
        "RGBSpeed": {"Label": "RGB Speed", "Type": "percent"},
        "CustomColorShift": {"Label": "Custom Color Shift", "Type": "boolean"},
        "CustomColorShiftSpeed": {"Label": "Custom Color Shift Speed", "Type": "percent"},
        "CustomColorShiftColors": {"Label": "Custom Color Shift Colors", "Type": "color_list"},
    }
    ANALYSIS_FIELDS = (
        ("Source", "Source"),
        ("Origin", "Origin"),
        ("Distance", "Distance"),
        ("Classification", "Classification"),
        ("Transmission Type", "TransmissionType"),
        ("Language", "Language"),
    )
    MESSAGE_FILE_FIELDS = (
        ("Source", "Source"),
        ("Origin", "Origin"),
        ("Distance", "Distance"),
        ("Classification", "Classification"),
        ("Transmission Type", "TransmissionType"),
        ("Language", "Language"),
        ("Decryption Completion", "DecryptionCompletion"),
    )
    SIGNAL_INTERRUPTED_TIME = 0.5
    SIGNAL_INCOMING_TIME = 1.0
    GENERAL_GLITCH_TIME = 0.35
    FAILED_DECRYPTION_GLITCH_TIME = 0.5

    @classmethod
    def settings_contract(cls) -> dict[str, Any]:
        return {"Defaults": cls.DEFAULT_SETTINGS, "Schema": cls.SETTING_SCHEMA}

    def __init__(self, asset_manager, ui: TerminalSSUI):
        self.asset_manager = asset_manager
        self.ui = ui
        self.asset_path = self.asset_manager.protocol_path(self.PROTOCOL_ID)
        self.characters: tuple[str, ...] = tuple("<>[]{}0123456789")
        self.transmissions: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.last_folder: Path | None = None
        self.message_lines: list[str] = []
        self.mapping: dict[str, str] = {}
        self.decode_order: list[str] = []
        self.target_completion = 1.0
        self.phase = "incoming"
        self.phase_started = 0.0
        self.phase_ends = 0.0
        self.decode_started = 0.0
        self.decode_ends = 0.0
        self.capture_duration = 1.0
        self.capture_lead_in = 0.0
        self.capture_durations: list[float] = []
        self.decode_durations: list[float] = []
        self.target_decode_count = 0
        self.glitch_at: float | None = None
        self.glitch_until = 0.0
        self.rain_direction = 1
        self.rain_width = 0
        self.rain_height = 0
        self.rain_streams: list[AlienRainStream | None] = []
        self.frequency = 0.0
        self.bandwidth = 0.0
        self.strength_target = 0.0
        self.signal_seed = 0
        self.load_assets()

    def load_assets(self) -> None:
        pool = self.asset_manager.character_set("Curated Alien", "<>[]{}0123456789")
        unique = []
        seen = set()
        for token in pool:
            if token and token not in seen and display_width(token) == 1:
                seen.add(token)
                unique.append(token)
        if unique:
            self.characters = tuple(unique)
        self.transmissions = []
        known = {key.casefold(): key for _, key in self.MESSAGE_FILE_FIELDS}
        known.update({label.replace(" ", "").casefold(): key for label, key in self.MESSAGE_FILE_FIELDS})
        for root in self.asset_manager.protocol_asset_roots(self.PROTOCOL_ID):
            for path in sorted(root.rglob("*.txt")):
                try:
                    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                info = {key: "Unknown" for _, key in self.MESSAGE_FILE_FIELDS}
                message_lines = []
                in_message = False
                matched = 0
                for raw in raw_lines:
                    stripped = raw.strip()
                    if not in_message and not stripped:
                        in_message = True
                        continue
                    if not in_message and stripped.casefold() == "message:":
                        in_message = True
                        continue
                    if not in_message and ":" in raw:
                        label, value = raw.split(":", 1)
                        normalized = label.replace("_", "").replace("-", "").replace(" ", "").casefold()
                        key = known.get(normalized)
                        if key is not None:
                            matched += 1
                            value = value.strip() or "Unknown"
                            if key == "DecryptionCompletion":
                                try:
                                    info[key] = max(0, min(100, int(round(float(value)))))
                                except (TypeError, ValueError):
                                    info[key] = 100
                            else:
                                info[key] = value
                            continue
                    if in_message:
                        message_lines.append(raw.rstrip())
                while message_lines and not message_lines[0].strip():
                    message_lines.pop(0)
                while message_lines and not message_lines[-1].strip():
                    message_lines.pop()
                if matched == 0 or not any(line.strip() for line in message_lines):
                    continue
                if info.get("DecryptionCompletion") == "Unknown":
                    info["DecryptionCompletion"] = 100
                self.transmissions.append({"Info": info, "Message": message_lines, "Folder": path})

    def _choose_transmission(self) -> dict[str, Any] | None:
        if not self.transmissions:
            return None
        choices = [item for item in self.transmissions if item.get("Folder") != self.last_folder]
        if not choices:
            choices = list(self.transmissions)
        selected = random.choice(choices)
        folder = selected.get("Folder")
        self.last_folder = folder if isinstance(folder, Path) else None
        return selected

    def _build_cipher(self) -> None:
        self.mapping = {}
        symbols = []
        for line in self.message_lines:
            for char in line:
                if char.isalnum():
                    key = char.upper()
                    if key not in symbols:
                        symbols.append(key)
        glyphs = list(self.characters)
        random.shuffle(glyphs)
        if not glyphs:
            glyphs = list("<>[]{}0123456789")
        for index, symbol in enumerate(symbols):
            self.mapping[symbol] = glyphs[index % len(glyphs)]
        self.decode_order = list(symbols)
        random.shuffle(self.decode_order)

    def _configure_signal(self) -> None:
        self.frequency = random.uniform(110.0, 9800.0)
        self.bandwidth = random.uniform(3.0, 82.0)
        self.strength_target = random.uniform(64.0, 96.0)
        self.signal_seed = random.randrange(1, 2**31 - 1)

    def _read_target_completion(self) -> float:
        info = self.current.get("Info", {}) if isinstance(self.current, dict) else {}
        if not isinstance(info, dict):
            return 1.0
        try:
            value = float(info.get("DecryptionCompletion", 100))
        except (TypeError, ValueError):
            value = 100.0
        return max(0.0, min(1.0, value / 100.0))

    def _load_new_transmission(self) -> None:
        self.current = self._choose_transmission()
        if self.current is None:
            self.message_lines = []
        else:
            values = self.current.get("Message", [])
            self.message_lines = [str(line) for line in values] if isinstance(values, list) else []
        self._build_cipher()
        self.target_completion = self._read_target_completion()
        self._configure_signal()
        self.rain_width = 0
        self.rain_height = 0
        self.rain_streams = []

    def _start_incoming(self, now: float) -> None:
        self._load_new_transmission()
        self.phase = "incoming"
        self.phase_started = now
        self.phase_ends = now + self.SIGNAL_INCOMING_TIME
        self.glitch_at = None
        self.glitch_until = 0.0

    def _message_character_count(self) -> int:
        return sum(1 for line in self.message_lines for char in line if not char.isspace())

    def _message_line_count(self) -> int:
        return max(1, sum(1 for line in self.message_lines if line.strip()))

    def _build_capture_profile(self, settings: dict) -> tuple[float, list[float]]:
        base = max(2.0, float(settings.get("TransmissionDecodeTime", 12.0)))
        characters = max(1, self._message_character_count())
        lines = self._message_line_count()
        size_scale = min(2.1, 0.90 + characters / 95.0 + max(0, lines - 1) * 0.08)
        lead_in = base * random.uniform(0.42, 0.72) + max(0, lines - 1) * random.uniform(0.35, 0.85)
        fast_min = max(0.05, base / 260.0) * size_scale
        fast_max = max(fast_min + 0.05, base / 105.0) * size_scale
        slow_min = max(0.18, base / 72.0) * size_scale
        slow_max = max(slow_min + 0.20, base / 19.0) * size_scale
        slow_chance = min(46.0, 12.0 + lines * 4.0 + min(20.0, characters / 8.0))
        durations = []
        for _ in range(characters):
            if random.random() * 100.0 < slow_chance:
                durations.append(random.uniform(slow_min, slow_max))
            else:
                durations.append(random.uniform(fast_min, fast_max))
        if characters >= 20 and random.random() < 0.70:
            stall_count = min(4, max(1, characters // 32))
            for _ in range(stall_count):
                index = random.randrange(len(durations))
                durations[index] += random.uniform(0.45, 1.65) * min(1.8, size_scale)
        return max(1.0, lead_in), durations

    def _build_decode_durations(self, settings: dict) -> list[float]:
        total = len(self.decode_order)
        if total <= 0:
            self.target_decode_count = 0
            return []
        target_count = int(math.floor(total * self.target_completion))
        if self.target_completion >= 0.999:
            target_count = total
        if self.target_completion > 0.0 and target_count <= 0:
            target_count = 1
        self.target_decode_count = min(total, target_count)
        base = max(2.0, float(settings.get("TransmissionDecodeTime", 12.0)))
        lines = self._message_line_count()
        characters = self._message_character_count()
        size_scale = min(2.4, 0.78 + characters / 70.0 + max(0, lines - 1) * 0.14)
        minimum = max(0.18, base / 42.0) * size_scale
        maximum = max(minimum + 0.15, base / 9.5 * size_scale)
        delay_chance = min(90.0, 34.0 + lines * 8.0 + min(28.0, characters / 6.0))
        durations = []
        for _ in range(self.target_decode_count):
            if random.random() * 100.0 < delay_chance:
                durations.append(random.uniform(minimum * 1.55, maximum))
            else:
                durations.append(random.uniform(minimum * 0.85, minimum * 1.25))
        return durations

    def _start_decode(self, settings: dict, now: float) -> None:
        self.phase = "decode"
        self.phase_started = now
        self.capture_lead_in, self.capture_durations = self._build_capture_profile(settings)
        self.capture_duration = self.capture_lead_in + sum(self.capture_durations)
        self.decode_durations = self._build_decode_durations(settings)
        self.decode_started = now + self.capture_duration
        self.decode_ends = self.decode_started + sum(self.decode_durations)
        if self.decode_ends <= self.decode_started:
            self.decode_ends = self.decode_started + 0.01
        self.phase_ends = self.decode_ends
        chance = max(0, min(100, int(settings.get("GlitchChance", 10))))
        total_duration = max(0.5, self.phase_ends - now)
        self.glitch_at = now + random.uniform(total_duration * 0.2, total_duration * 0.85) if random.random() * 100 < chance else None
        self.glitch_until = 0.0

    def _message_hold_time(self, settings: dict) -> float:
        count = sum(1 for line in self.message_lines if line.strip())
        count = max(1, count)
        base = max(1.0, float(settings.get("BaseMessageDisplayTime", 5.0)))
        secondary = max(0.0, float(settings.get("SecondaryLineDisplayTime", 3.0)))
        return base + max(0, count - 1) * secondary

    def _start_hold(self, settings: dict, now: float, failed: bool = False) -> None:
        self.phase = "failed_hold" if failed else "hold"
        self.phase_started = now
        self.phase_ends = now + self._message_hold_time(settings)
        self.glitch_at = None
        self.glitch_until = 0.0

    def _start_failed_decryption(self, settings: dict, now: float) -> None:
        chance = max(0, min(100, int(settings.get("FailedDecryptionGlitchChance", 100))))
        if random.random() * 100 < chance:
            self.phase = "decrypt_fail_glitch"
            self.phase_started = now
            self.phase_ends = now + self.FAILED_DECRYPTION_GLITCH_TIME
            self.glitch_at = None
            self.glitch_until = self.phase_ends
        else:
            self._start_hold(settings, now, True)

    def _start_interrupted(self, now: float) -> None:
        self.phase = "interrupted"
        self.phase_started = now
        self.phase_ends = now + self.SIGNAL_INTERRUPTED_TIME
        self.glitch_at = None
        self.glitch_until = self.phase_ends

    def reset(self, settings: dict, width: int, height: int, now: float | None = None) -> None:
        base = now if now is not None else time.monotonic()
        self.last_folder = None
        self.rain_direction = 1
        self._start_incoming(base)

    def _timeline_progress(self, now: float) -> float:
        if self.phase in {"hold", "failed_hold", "decrypt_fail_glitch", "interrupted"}:
            return 1.0
        if self.phase == "incoming":
            return 0.0
        total = max(0.001, self.phase_ends - self.phase_started)
        return max(0.0, min(1.0, (now - self.phase_started) / total))

    def _decode_state(self, now: float) -> tuple[int, int | None, float, float]:
        if self.phase == "incoming" or now < self.decode_started:
            return 0, None, 0.0, 0.0
        if not self.decode_durations or self.target_decode_count <= 0:
            return 0, None, 1.0, self.target_completion
        remaining = max(0.0, now - self.decode_started)
        resolved = 0
        active_progress = 0.0
        for duration in self.decode_durations:
            if remaining >= duration:
                remaining -= duration
                resolved += 1
                continue
            active_progress = max(0.0, min(1.0, remaining / max(0.001, duration)))
            break
        resolved = min(self.target_decode_count, resolved)
        if resolved >= self.target_decode_count or now >= self.decode_ends:
            return self.target_decode_count, None, 1.0, self.target_completion
        active_index = resolved
        overall = (resolved + active_progress) / max(1, self.target_decode_count)
        return resolved, active_index, active_progress, self.target_completion * overall

    def _decryption_progress(self, now: float) -> float:
        return self._decode_state(now)[3]

    def _isolation_progress(self, now: float) -> float:
        if self.phase == "incoming":
            return 0.0
        if self.phase in {"hold", "failed_hold", "decrypt_fail_glitch", "interrupted"}:
            return 1.0
        elapsed = max(0.0, now - self.phase_started)
        if elapsed < self.capture_lead_in:
            return 0.0
        if not self.capture_durations:
            return 1.0
        remaining = elapsed - self.capture_lead_in
        resolved = 0
        active_progress = 0.0
        for duration in self.capture_durations:
            if remaining >= duration:
                remaining -= duration
                resolved += 1
                continue
            active_progress = max(0.0, min(1.0, remaining / max(0.001, duration)))
            break
        if resolved >= len(self.capture_durations):
            return 1.0
        return max(0.0, min(1.0, (resolved + active_progress) / len(self.capture_durations)))

    def _signal_lock(self, now: float) -> float:
        if self.phase == "incoming":
            progress = max(0.0, min(1.0, (now - self.phase_started) / max(0.001, self.SIGNAL_INCOMING_TIME)))
            base = 8.0 + progress * 20.0
        elif self.phase == "decode":
            base = 24.0 + self._timeline_progress(now) * 72.0
        elif self.phase in {"hold", "failed_hold", "decrypt_fail_glitch"}:
            base = 96.0 if self.target_completion >= 0.999 else 78.0
        else:
            base = max(0.0, 35.0 - (now - self.phase_started) * 80.0)
        jitter = math.sin(now * 4.7 + self.signal_seed % 11) * 2.4 + math.sin(now * 2.1) * 1.2
        return max(0.0, min(100.0, base + jitter))

    def _signal_strength(self, now: float, lock: float) -> float:
        target = self.strength_target if self.strength_target else 72.0
        jitter = math.sin(now * 3.1 + self.signal_seed % 7) * 4.0 + math.sin(now * 7.7) * 1.5
        if self.phase == "interrupted":
            return max(0.0, min(100.0, lock * 0.68 + jitter * 0.2))
        if self.phase == "incoming":
            factor = 0.08 + min(1.0, lock / 100.0) * 0.58
            return max(0.0, min(100.0, target * factor + jitter * 0.35))
        factor = 0.55 + min(1.0, lock / 100.0) * 0.45
        return max(3.0, min(100.0, target * factor + jitter))

    @staticmethod
    def _carrier(lock: float) -> str:
        if lock < 20:
            return "SEARCHING"
        if lock < 50:
            return "UNSTABLE"
        if lock < 82:
            return "PARTIAL LOCK"
        return "STABLE"

    def _analyser_state(self, now: float) -> tuple[str, float]:
        if self.phase in {"decrypt_fail_glitch", "failed_hold", "interrupted"}:
            return "failed", 0.0
        if self.phase == "incoming":
            recovery = max(0.0, min(1.0, (now - self.phase_started) / max(0.001, self.SIGNAL_INCOMING_TIME)))
            return "recovery", recovery
        if now < self.glitch_until:
            return "glitch", 0.0
        return "normal", 1.0

    def _encoded_char(self, char: str) -> str:
        if not char.isalnum():
            return char
        return self.mapping.get(char.upper(), random.choice(self.characters))

    def _encoded_lines(self) -> list[str]:
        return ["".join(self._encoded_char(char) for char in line) for line in self.message_lines]

    def _decoded_lines(self, progress: float, now: float) -> list[str]:
        total = len(self.decode_order)
        if total == 0:
            return list(self.message_lines)
        resolved, active_index, active_progress, _ = self._decode_state(now)
        locked_symbols = set(self.decode_order[:resolved])
        active = self.decode_order[active_index] if active_index is not None and active_index < total else None
        tick_speed = 8.0 + active_progress * 20.0
        rng = random.Random(self.signal_seed ^ int(now * tick_speed) ^ (active_index or 0) * 4099)
        candidates = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        output = []
        for line in self.message_lines:
            chars = []
            for char in line:
                if not char.isalnum():
                    chars.append(char)
                    continue
                key = char.upper()
                if key in locked_symbols or (self.target_completion >= 0.999 and resolved >= total):
                    chars.append(char.upper())
                elif key == active:
                    chars.append(rng.choice(candidates))
                else:
                    chars.append(self.mapping.get(key, random.choice(self.characters)))
            output.append("".join(chars))
        return output

    def _analysis_rows(self, progress: float) -> list[tuple[str, str]]:
        info = self.current.get("Info", {}) if isinstance(self.current, dict) else {}
        if not isinstance(info, dict):
            info = {}
        rows = []
        count = len(self.ANALYSIS_FIELDS)
        for index, (label, key) in enumerate(self.ANALYSIS_FIELDS):
            threshold = (index + 1) / (count + 1)
            value = info.get(key, "Unknown")
            if value in {None, ""}:
                value = "Unknown"
            rows.append((label, str(value).upper() if progress >= threshold else "ANALYSING..."))
        return rows

    def _ensure_rain(self, width: int, height: int) -> None:
        width = max(1, width)
        height = max(1, height)
        if width == self.rain_width and height == self.rain_height and self.rain_streams:
            return
        self.rain_width = width
        self.rain_height = height
        self.rain_streams = []
        for _ in range(width):
            self.rain_streams.append(AlienRainStream(height, self.rain_direction) if random.random() < 0.98 else None)

    def _advance_rain(self) -> None:
        for stream in self.rain_streams:
            if stream is None:
                continue
            stream.ensure_glyphs(self.characters)
            stream.advance(self.rain_height, self.rain_direction)
            if random.random() < 0.08:
                stream.randomize(self.characters)

    def _capture_rows(self, width: int, height: int, progress: float, now: float) -> list[tuple[int, int, str, set[int], int | None]]:
        encoded = [line for line in self._encoded_lines() if line]
        if not encoded or width < 3 or height < 1:
            return []
        line_width = max(1, width - 4)
        rows = []
        for line in encoded:
            rows.extend(self._wrap_line(line, line_width))
        if not rows:
            return []
        max_rows = max(1, min(len(rows), height))
        rows = rows[:max_rows]
        if len(rows) == 1:
            positions = [height // 2]
        else:
            span = min(height - 1, max(len(rows) - 1, (len(rows) - 1) * 2))
            top = max(0, (height - 1 - span) // 2)
            step = span / max(1, len(rows) - 1)
            positions = [min(height - 1, top + int(round(index * step))) for index in range(len(rows))]
        result = []
        count = len(rows)
        for index, line in enumerate(rows):
            local = max(0.0, min(1.0, progress * count - index))
            character_positions = [offset for offset, char in enumerate(line) if char != " "]
            rng = random.Random(self.signal_seed ^ ((index + 1) * 7919))
            order = list(character_positions)
            rng.shuffle(order)
            locked_count = min(len(order), int(math.floor(local * len(order) + 1e-9)))
            locked = set(order[:locked_count])
            frontier = order[locked_count - 1] if locked_count else None
            start_x = max(0, (width - len(line)) // 2)
            result.append((positions[index], start_x, line, locked, frontier))
        return result

    def _draw_incoming_stream(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, progress: float, now: float) -> None:
        canvas.panel(x, y, width, height, "INCOMING TRANSMISSION STREAM", 2)
        inner_x = x + 1
        inner_y = y + 1
        inner_w = max(1, width - 2)
        inner_h = max(1, height - 2)
        self._ensure_rain(inner_w, inner_h)
        self._advance_rain()
        static_rng = random.Random(self.signal_seed ^ int(now * 11))
        for row in range(inner_h):
            for column in range(inner_w):
                if static_rng.random() < 0.25:
                    canvas.put(inner_x + column, inner_y + row, static_rng.choice(self.characters), 1)
        for column, stream in enumerate(self.rain_streams):
            if stream is None:
                continue
            for index, glyph in enumerate(stream.glyphs):
                row = int(stream.head) - index * self.rain_direction
                if not 0 <= row < inner_h:
                    continue
                style = 4 if index == 0 else 3 if index <= 3 else 2 if index <= 8 else 1
                canvas.put(inner_x + column, inner_y + row, glyph, style)
        isolation = self._isolation_progress(now)
        for row, start_x, line, locked, frontier in self._capture_rows(inner_w, inner_h, isolation, now):
            flicker_rng = random.Random(self.signal_seed ^ (row * 65537) ^ int(now * 6))
            for offset, char in enumerate(line):
                target_x = inner_x + start_x + offset
                target_y = inner_y + row
                if char == " ":
                    if isolation > 0.0:
                        canvas.put(target_x, target_y, " ", 1)
                    continue
                if offset in locked:
                    canvas.put(target_x, target_y, char, 4 if offset == frontier else 3)
                elif flicker_rng.random() < 0.035 + isolation * 0.16:
                    canvas.put(target_x, target_y, char, 2)

    def _draw_progress_row(self, canvas: TerminalCanvas, x: int, y: int, width: int, label: str, value: float, style: int = 3) -> None:
        label_width = min(18, max(11, width // 3))
        percent = f"{max(0.0, min(100.0, value)):3.0f}%"
        label_x = x + 2
        percent_x = max(label_x + label_width + 4, x + width - len(percent) - 2)
        bar_x = label_x + label_width
        bar_width = max(3, percent_x - bar_x - 1)
        canvas.text(label_x, y, f"{label.upper()}:", 1, max_width=max(1, label_width - 1))
        canvas.progress_bar(bar_x, y, bar_width, value, style)
        canvas.text(percent_x, y, percent, style, max_width=max(1, x + width - percent_x - 1))

    def _draw_signal_analysis(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, now: float, spacious: bool = False) -> None:
        canvas.panel(x, y, width, height, "SIGNAL ANALYSIS", 2)
        lock = self._signal_lock(now)
        strength = self._signal_strength(now, lock)
        label_x = x + 2
        row = y + 2
        bottom = y + height - 2
        right = x + width - 2
        value_x = x + min(24, max(19, width // 3 + 2))
        value_width = max(1, right - value_x)

        if row < bottom:
            self._draw_progress_row(canvas, x, row, width, "Signal Lock", lock, 3)
            row += 1
        if row < bottom:
            if spacious and bottom - row >= 5:
                row += 1
            self._draw_progress_row(canvas, x, row, width, "Signal Strength", strength, 3)
            row += 1

        if row < bottom:
            if spacious and bottom - row >= 4:
                row += 1
            analyser_label = "SIGNAL ANALYSER: "
            spectrum_w = max(1, width - 4 - len(analyser_label))
            analyser_state, recovery = self._analyser_state(now)
            spectrum = self.ui.analyser_trace(spectrum_w, now, self.signal_seed ^ 0x51A1, analyser_state, recovery, 1.15)
            canvas.text(label_x, row, analyser_label, 2, max_width=max(1, width - 4))
            canvas.text(label_x + len(analyser_label), row, spectrum, 2, max_width=spectrum_w)
            row += 1

        filler = [
            ("Carrier", self._carrier(lock)),
            ("Frequency", f"{self.frequency:0.3f} MHz"),
            ("Bandwidth", f"{self.bandwidth:0.1f} kHz"),
        ]
        if filler and bottom - row > 0:
            if spacious and bottom - row > len(filler):
                row += 1
            for label, value in filler:
                if row >= bottom:
                    break
                canvas.text(label_x, row, f"{label.upper()}:", 1, max_width=max(1, value_x - label_x - 1))
                canvas.text(value_x, row, value, 3, max_width=value_width)
                row += 1

    def _draw_transmission_analysis(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, now: float, spacious: bool = False) -> None:
        canvas.panel(x, y, width, height, "TRANSMISSION ANALYSIS", 2)
        isolation = self._isolation_progress(now)
        decrypt = self._decryption_progress(now)
        analysis_progress = min(1.0, isolation * 0.78 + decrypt * 0.22)
        analysis_values = {label: value for label, value in self._analysis_rows(analysis_progress)}
        label_x = x + 2
        row = y + 2
        bottom = y + height - 2
        right = x + width - 2
        value_x = x + min(24, max(19, width // 3 + 2))
        value_width = max(1, right - value_x)
        usable_rows = max(0, bottom - row)

        core_items = ["Source", "Language"]
        optional_items = ["Origin", "Distance", "Classification", "Transmission Type"]
        reserved_core = 3
        metadata_capacity = max(0, usable_rows - reserved_core)
        selected_metadata = core_items[:metadata_capacity]
        remaining_metadata = max(0, metadata_capacity - len(selected_metadata))
        if remaining_metadata:
            selected_metadata.extend(optional_items[:remaining_metadata])

        for label in selected_metadata:
            if row >= bottom:
                return
            value = analysis_values.get(label, "Unknown")
            canvas.text(label_x, row, f"{label.upper()}:", 1, max_width=max(1, value_x - label_x - 1))
            style = 2 if value == "ANALYSING..." or value.casefold() == "unknown" else 3
            canvas.text(value_x, row, value, style, max_width=value_width)
            row += 1

        remaining_required = min(3, max(0, bottom - row))
        if spacious and row < bottom and bottom - row > remaining_required:
            row += 1

        if row < bottom:
            analyser_label = "LANGUAGE ANALYSER: "
            analyser_w = max(1, width - 4 - len(analyser_label))
            analyser_state, recovery = self._analyser_state(now)
            analyser = self.ui.analyser_trace(analyser_w, now, self.signal_seed ^ 0xA113, analyser_state, recovery, 0.9)
            canvas.text(label_x, row, analyser_label, 2, max_width=max(1, width - 4))
            canvas.text(label_x + len(analyser_label), row, analyser, 2, max_width=analyser_w)
            row += 1

        metrics = [("Pattern Match", isolation * 100.0), ("Decode Progress", decrypt * 100.0)]
        if spacious and bottom - row > len(metrics):
            row += 1
        for index, (label, value) in enumerate(metrics):
            if row >= bottom:
                return
            style = 4 if label == "Decode Progress" and self.target_completion < 0.999 and value >= self.target_completion * 100.0 - 0.5 else 3
            self._draw_progress_row(canvas, x, row, width, label, value, style)
            row += 1
            remaining = len(metrics) - index - 1
            if spacious and remaining and bottom - row > remaining:
                row += 1

    def _wrap_line(self, text: str, width: int) -> list[str]:
        if width <= 1:
            return [text[:1]]
        if len(text) <= width:
            return [text]
        chunks = []
        remaining = text
        while remaining:
            if len(remaining) <= width:
                chunks.append(remaining)
                break
            split = remaining.rfind(" ", 0, width + 1)
            if split <= 0:
                split = width
            chunks.append(remaining[:split].rstrip())
            remaining = remaining[split:].lstrip()
        return chunks

    def _draw_decoded_message(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, progress: float, now: float) -> None:
        canvas.panel(x, y, width, height, "DECODED MESSAGE", 2)
        if not self.message_lines:
            canvas.centered_text(y + height // 2, "NO MESSAGE DATA", 2, x + 1, x + width - 1)
            return
        if self._isolation_progress(now) < 0.999:
            canvas.centered_text(y + height // 2, "AWAITING ISOLATED TRANSMISSION...", 1, x + 2, x + width - 2)
            return
        available = max(1, width - 4)
        rendered = []
        for line in self._decoded_lines(progress, now):
            rendered.extend(self._wrap_line(line, available))
        visible_height = max(1, height - 3)
        start_y = y + 2 + max(0, (visible_height - len(rendered)) // 2)
        for index, line in enumerate(rendered[:visible_height]):
            complete = progress >= 0.999 and self.target_completion >= 0.999
            canvas.centered_text(start_y + index, line, 3 if complete else 2, x + 2, x + width - 2)
        if self.phase == "failed_hold" and height >= 5:
            canvas.centered_text(y + height - 2, "DECRYPTION FAILED", 4, x + 2, x + width - 2)

    def _desired_decoded_height(self, right_width: int) -> int:
        available = max(1, right_width - 4)
        rendered_lines = 0
        for line in self.message_lines:
            rendered_lines += len(self._wrap_line(line, available))
        visible_lines = max(1, min(10, rendered_lines))
        return visible_lines + 3

    def _draw_layout(self, width: int, height: int, now: float) -> TerminalCanvas:
        canvas = self.ui.canvas(width, height)
        split_x = max(20, min(width - 20, width // 2)) if width >= 40 else max(1, width // 2)
        left_w = split_x
        right_w = width - split_x

        if height >= 24:
            min_signal_h = 7
            min_transmission_h = 11
            useful_signal_h = 10
            useful_transmission_h = 13
        elif height >= 15:
            min_signal_h = 5
            min_transmission_h = 7
            useful_signal_h = 8
            useful_transmission_h = 9
        else:
            min_signal_h = 3
            min_transmission_h = 3
            useful_signal_h = 3
            useful_transmission_h = 3

        desired_decoded_h = self._desired_decoded_height(right_w)
        support_minimum = min_signal_h + min_transmission_h

        if height >= support_minimum + 4:
            decoded_h = min(desired_decoded_h, height - support_minimum)
        else:
            decoded_h = max(1, height - 6)

        remaining = max(0, height - decoded_h)
        if remaining >= support_minimum:
            signal_h = min_signal_h
            transmission_h = min_transmission_h
            extra = remaining - support_minimum

            while extra > 0 and (signal_h < useful_signal_h or transmission_h < useful_transmission_h):
                if signal_h < useful_signal_h and extra > 0:
                    signal_h += 1
                    extra -= 1
                if transmission_h < useful_transmission_h and extra > 0:
                    transmission_h += 1
                    extra -= 1

            if extra > 0:
                signal_extra = extra // 2
                transmission_extra = extra - signal_extra
                signal_h += signal_extra
                transmission_h += transmission_extra
        else:
            signal_h = max(3, remaining // 2)
            transmission_h = max(3, remaining - signal_h)
            if signal_h + transmission_h > remaining:
                overflow = signal_h + transmission_h - remaining
                reduce_transmission = min(overflow, max(0, transmission_h - 1))
                transmission_h -= reduce_transmission
                overflow -= reduce_transmission
                signal_h = max(1, signal_h - overflow)

        total = signal_h + transmission_h + decoded_h
        if total < height:
            transmission_h += height - total
        elif total > height:
            overflow = total - height
            reduce_transmission = min(overflow, max(0, transmission_h - 1))
            transmission_h -= reduce_transmission
            overflow -= reduce_transmission
            reduce_signal = min(overflow, max(0, signal_h - 1))
            signal_h -= reduce_signal
            overflow -= reduce_signal
            if overflow:
                decoded_h = max(1, decoded_h - overflow)

        isolation = self._isolation_progress(now)
        decrypt = self._decryption_progress(now)
        self._draw_incoming_stream(canvas, 0, 0, left_w, height, isolation, now)
        shared_spacious = signal_h >= useful_signal_h + 2 and transmission_h >= useful_transmission_h + 2
        self._draw_signal_analysis(canvas, split_x, 0, right_w, signal_h, now, shared_spacious)
        self._draw_transmission_analysis(canvas, split_x, signal_h, right_w, transmission_h, now, shared_spacious)
        self._draw_decoded_message(canvas, split_x, signal_h + transmission_h, right_w, decoded_h, decrypt, now)
        return canvas

    def _advance_state(self, settings: dict, now: float) -> None:
        if self.current is None and not self.transmissions:
            return
        if self.glitch_at is not None and now >= self.glitch_at and now >= self.glitch_until:
            self.glitch_until = now + self.GENERAL_GLITCH_TIME
            self.glitch_at = None
        if now < self.phase_ends:
            return
        if self.phase == "incoming":
            self._start_decode(settings, now)
        elif self.phase == "decode":
            if self.target_completion >= 0.999:
                self._start_hold(settings, now, False)
            else:
                self._start_failed_decryption(settings, now)
        elif self.phase == "decrypt_fail_glitch":
            self._start_hold(settings, now, True)
        elif self.phase in {"hold", "failed_hold"}:
            self._start_interrupted(now)
        elif self.phase == "interrupted":
            self._start_incoming(now)

    def render(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        self._advance_state(settings, now)
        canvas = self._draw_layout(width, height, now)
        if self.current is None:
            canvas.overlay_center_box("ALIEN PROTOCOL", ["NO TRANSMISSIONS AVAILABLE"])
            return canvas
        if self.phase == "interrupted":
            self.ui.apply_glitch(canvas, self.characters, 0.42, int(now * 30))
            canvas.overlay_center_box("SIGNAL INTERRUPTED...", ["NO CARRIER"])
        elif self.phase == "incoming":
            canvas.overlay_center_box("SIGNAL INCOMING...", ["ACQUIRING CARRIER"])
        elif self.phase == "decrypt_fail_glitch":
            self.ui.apply_glitch(canvas, self.characters, 0.46, int(now * 33))
            canvas.overlay_center_box("DECRYPTION FAILURE", [f"RECOVERY HALTED AT {self.target_completion * 100:0.0f}%", "SIGNAL DATA CORRUPTED"])
        elif now < self.glitch_until:
            self.ui.apply_glitch(canvas, self.characters, 0.20, int(now * 25))
        return canvas

    def handle_runtime_key(self, key: str, settings: dict) -> bool:
        if key in {"+", "="}:
            settings["TransmissionDecodeTime"] = max(2.0, float(settings.get("TransmissionDecodeTime", 12.0)) - 1.0)
            return True
        if key in {"-", "_"}:
            settings["TransmissionDecodeTime"] = min(120.0, float(settings.get("TransmissionDecodeTime", 12.0)) + 1.0)
            return True
        if key == "BACKSPACE":
            self.reverse_direction(settings)
            return True
        return False

    def reverse_direction(self, settings: dict) -> None:
        self.rain_direction *= -1
        for stream in self.rain_streams:
            if stream is not None:
                stream.direction = self.rain_direction

    def primary_speed_label(self, settings: dict) -> str:
        return f"Base Decode Time {float(settings.get('TransmissionDecodeTime', 12.0)):g}s"


PROTOCOL_CLASS = TerminalSSAlienProtocol
