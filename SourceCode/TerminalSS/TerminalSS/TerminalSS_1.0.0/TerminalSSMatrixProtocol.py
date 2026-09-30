from __future__ import annotations

import math
import random
import textwrap
import time
from pathlib import Path
from typing import Any

from TerminalSSUI import TerminalSSUI, TerminalCanvas, display_width


SPEED_LEVELS = {
    -10: 0.20,
    -9: 0.28,
    -8: 0.36,
    -7: 0.44,
    -6: 0.52,
    -5: 0.60,
    -4: 0.68,
    -3: 0.76,
    -2: 0.84,
    -1: 0.92,
    0: 1.00,
    1: 1.15,
    2: 1.35,
    3: 1.60,
    4: 1.90,
    5: 2.25,
    6: 2.65,
    7: 3.10,
    8: 3.60,
    9: 4.20,
    10: 5.00,
}

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----",
    "2": "..---", "3": "...--", "4": "....-", "5": ".....", "6": "-....", "7": "--...", "8": "---..",
    "9": "----.",
}


class MatrixStream:
    def __init__(self, height: int, direction: int, first_run: bool = True):
        self.characters: list[str] = []
        self.head = 0.0
        self.length = 0
        self.speed = 1.0
        self.reset(height, direction, first_run)

    def reset(self, height: int, direction: int, first_run: bool = False) -> None:
        if first_run:
            self.head = random.uniform(-height, height * 2)
        elif direction > 0:
            self.head = random.uniform(-height * 1.4, -1)
        else:
            self.head = random.uniform(height + 1, height * 2.4)
        minimum = max(7, height // 5)
        maximum = max(minimum + 1, int(height * 0.85))
        self.length = random.randint(minimum, maximum)
        self.speed = random.uniform(0.35, 1.35)
        self.characters = []

    def ensure_characters(self, pool: tuple[str, ...]) -> list[str]:
        if len(self.characters) != self.length + 1:
            self.characters = [random.choice(pool) for _ in range(self.length + 1)]
        return self.characters

    def advance(self, height: int, speed_multiplier: float, direction: int) -> None:
        self.head += self.speed * speed_multiplier * direction
        if direction > 0 and self.head - self.length > height:
            self.reset(height, direction)
        elif direction < 0 and self.head + self.length < 0:
            self.reset(height, direction)

    def randomize_character(self, pool: tuple[str, ...]) -> None:
        if not self.characters or not pool:
            return
        index = random.randrange(len(self.characters))
        current = self.characters[index]
        replacement = random.choice(pool)
        if len(pool) > 1 and replacement == current:
            replacement = random.choice(pool)
        self.characters[index] = replacement


class TerminalSSMatrixProtocol:
    PROTOCOL_ID = "Matrix"
    KEY = "1"
    DEFAULT_SETTINGS = {
        "RainSpeed": 50,
        "RainDensity": 80,
        "RainDirection": "Down",
        "RainCharacterRandomizationSpeed": 50,
        "MessageDisplayTime": 10.0,
        "TimeBetweenMessages": 4.0,
        "EncryptedMessageDecodeSpeed": 70,
        "DisplayMessages": True,
        "DisplayArt": True,
        "BinaryStyle": False,
        "Color": "Matrix Green",
        "RGB": False,
        "RGBSpeed": 50,
        "CustomColorShift": False,
        "CustomColorShiftSpeed": 50,
        "CustomColorShiftColors": ["Matrix Green", "Cyan", "Electric Blue"],
        "GlitchChance": 5,
    }
    SETTING_SCHEMA = {
        "RainSpeed": {"Label": "Rain Speed", "Type": "percent"},
        "RainDensity": {"Label": "Rain Density", "Type": "percent"},
        "RainDirection": {"Label": "Rain Direction", "Type": "choice", "Choices": ["Down", "Up"]},
        "RainCharacterRandomizationSpeed": {"Label": "Rain Character Randomization Speed", "Type": "percent"},
        "MessageDisplayTime": {"Label": "Message Display Time", "Type": "seconds", "Min": 1, "Max": 300},
        "TimeBetweenMessages": {"Label": "Time Between Messages", "Type": "seconds", "Min": 0, "Max": 300},
        "EncryptedMessageDecodeSpeed": {"Label": "Encrypted Message Decode Speed", "Type": "percent"},
        "DisplayMessages": {"Label": "Display Messages", "Type": "boolean"},
        "DisplayArt": {"Label": "Display Art", "Type": "boolean"},
        "BinaryStyle": {"Label": "Binary Style", "Type": "boolean"},
        "Color": {"Label": "Color", "Type": "color"},
        "RGB": {"Label": "RGB", "Type": "boolean"},
        "RGBSpeed": {"Label": "RGB Speed", "Type": "percent"},
        "CustomColorShift": {"Label": "Custom Color Shift", "Type": "boolean"},
        "CustomColorShiftSpeed": {"Label": "Custom Color Shift Speed", "Type": "percent"},
        "CustomColorShiftColors": {"Label": "Custom Color Shift Colors", "Type": "color_list"},
        "GlitchChance": {"Label": "Glitch Chance", "Type": "percent"},
    }

    @classmethod
    def settings_contract(cls) -> dict[str, Any]:
        return {"Defaults": cls.DEFAULT_SETTINGS, "Schema": cls.SETTING_SCHEMA}

    def __init__(self, asset_manager, ui: TerminalSSUI):
        self.asset_manager = asset_manager
        self.ui = ui
        self.asset_path = self.asset_manager.protocol_path(self.PROTOCOL_ID)
        self.characters: tuple[str, ...] = tuple("01")
        self.messages: list[Any] = []
        self.art_paths: list[Path] = []
        self.streams: list[list[MatrixStream]] = []
        self.width = 0
        self.height = 0
        self.density = -1
        self.layers = 2
        self.last_randomize = 0.0
        self.next_event_at = 0.0
        self.event: dict[str, Any] | None = None
        self.glitch_at: float | None = None
        self.glitch_until = 0.0
        self.load_assets()

    def load_assets(self) -> None:
        roots = self.asset_manager.protocol_asset_roots(self.PROTOCOL_ID)
        pool = self.asset_manager.character_set("Curated Matrix", "01")
        unique = []
        seen = set()
        for token in pool:
            if token and token not in seen and display_width(token) == 1:
                seen.add(token)
                unique.append(token)
        self.characters = tuple(unique) or tuple("01")
        self.messages = []
        self.art_paths = []
        for root in roots:
            custom_root = root.name.casefold() == "custom"
            for path in sorted(root.rglob("*.txt")):
                relative_parts = [part.casefold() for part in path.relative_to(root).parts[:-1]]
                is_custom_art = custom_root and "custom_art" in relative_parts
                is_art = path.name.casefold().startswith("art_") or is_custom_art
                if is_art:
                    self.art_paths.append(path)
                    continue
                if not custom_root and "message" not in path.name.casefold():
                    continue
                try:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                for raw in lines:
                    value = raw.strip()
                    if not value:
                        continue
                    if value.casefold().startswith("morse:"):
                        message = value.split(":", 1)[1].strip()
                        if message:
                            self.messages.append({"Message": message, "Encoding": "Morse"})
                    else:
                        self.messages.append(value)

    def reset(self, settings: dict, width: int, height: int, now: float | None = None) -> None:
        self.width = 0
        self.height = 0
        self.density = -1
        self.streams = []
        self.event = None
        self.glitch_at = None
        self.glitch_until = 0.0
        self.last_randomize = now if now is not None else time.monotonic()
        base = now if now is not None else time.monotonic()
        self.next_event_at = base + max(0.0, float(settings.get("TimeBetweenMessages", 4.0)))
        self._ensure_streams(settings, width, height)

    @staticmethod
    def _direction(settings: dict) -> int:
        return -1 if str(settings.get("RainDirection", "Down")).casefold() == "up" else 1

    @staticmethod
    def _speed_multiplier(percent: int) -> float:
        value = max(0, min(100, int(percent)))
        level = max(-10, min(10, int(round((value - 50) / 5.0))))
        return SPEED_LEVELS[level]

    def _pool(self, settings: dict) -> tuple[str, ...]:
        return tuple("01") if settings.get("BinaryStyle", False) else self.characters

    def _ensure_streams(self, settings: dict, width: int, height: int) -> None:
        width = max(1, width)
        height = max(1, height)
        density = max(0, min(100, int(settings.get("RainDensity", 80))))
        if self.width == width and self.height == height and self.density == density and self.streams:
            return
        self.width = width
        self.height = height
        self.density = density
        probability = density / 100.0
        if self.layers > 1 and probability < 1.0:
            layer_density = 1.0 - (1.0 - probability) ** (1.0 / self.layers)
        else:
            layer_density = probability
        direction = self._direction(settings)
        matrix = []
        for _ in range(width):
            column = []
            for layer in range(self.layers):
                if random.random() <= layer_density:
                    stream = MatrixStream(height, direction, True)
                    if direction > 0:
                        stream.head -= layer * random.uniform(height * 0.25, height * 0.80)
                    else:
                        stream.head += layer * random.uniform(height * 0.25, height * 0.80)
                    column.append(stream)
            matrix.append(column)
        self.streams = matrix

    @staticmethod
    def _morse(text: str) -> str:
        words = []
        for word in text.upper().split():
            letters = [MORSE.get(char, char) for char in word]
            words.append(" ".join(letters))
        return " / ".join(words)

    @staticmethod
    def _message_payload(entry: Any) -> tuple[str, str | None]:
        if isinstance(entry, str):
            return entry, None
        if not isinstance(entry, dict):
            return "", None
        message = entry.get("Message")
        if not isinstance(message, str):
            return "", None
        encoded = entry.get("Encoded")
        if not isinstance(encoded, str):
            encoded = None
        if encoded is None and str(entry.get("Encoding", "")).casefold() == "morse":
            encoded = TerminalSSMatrixProtocol._morse(message)
        return message, encoded

    def _start_event(self, settings: dict, now: float) -> None:
        candidates = []
        if settings.get("DisplayMessages", True):
            candidates.extend(("message", item) for item in self.messages)
        if settings.get("DisplayArt", True):
            candidates.extend(("art", item) for item in self.art_paths)
        if not candidates:
            self.next_event_at = now + max(0.2, float(settings.get("TimeBetweenMessages", 4.0)))
            return
        kind, payload = random.choice(candidates)
        duration = max(1.0, float(settings.get("MessageDisplayTime", 10.0)))
        decode_percent = max(0, min(100, int(settings.get("EncryptedMessageDecodeSpeed", 70))))
        decode_time = duration * decode_percent / 100.0
        seed = random.randrange(1, 2**31)
        event = {"Kind": kind, "Start": now, "End": now + duration, "DecodeTime": decode_time, "Seed": seed}
        if kind == "message":
            message, encoded = self._message_payload(payload)
            event["Message"] = message
            event["Encoded"] = encoded
            positions = [index for index, char in enumerate(message) if not char.isspace()]
            rng = random.Random(seed)
            rng.shuffle(positions)
            event["RevealOrder"] = positions
        else:
            path = Path(payload)
            event["Art"] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        self.event = event
        self.glitch_at = None
        chance = max(0, min(100, int(settings.get("GlitchChance", 5))))
        if random.random() * 100 < chance:
            self.glitch_at = now + random.uniform(duration * 0.12, max(duration * 0.13, duration * 0.82))
        self.next_event_at = now + duration + max(0.0, float(settings.get("TimeBetweenMessages", 4.0)))

    def _event_progress(self, now: float) -> float:
        if not self.event:
            return 0.0
        decode_time = float(self.event.get("DecodeTime", 0.0))
        if decode_time <= 0:
            return 1.0
        return max(0.0, min(1.0, (now - float(self.event["Start"])) / decode_time))

    def _decoded_message(self, event: dict[str, Any], progress: float, pool: tuple[str, ...], now: float) -> str:
        target = str(event.get("Message", ""))
        encoded = event.get("Encoded")
        if encoded and progress < 0.18:
            return str(encoded)
        adjusted = 1.0 if progress >= 1.0 else max(0.0, (progress - 0.18) / 0.82) if encoded else progress
        reveal_order = event.get("RevealOrder", [])
        reveal_count = int(math.floor(len(reveal_order) * adjusted))
        revealed = set(reveal_order[:reveal_count])
        rng = random.Random(int(event.get("Seed", 0)) ^ int(now * 12))
        output = []
        for index, char in enumerate(target):
            if char.isspace() or index in revealed:
                output.append(char)
            elif char.isprintable():
                output.append(rng.choice(pool))
            else:
                output.append(char)
        return "".join(output)

    def _draw_event(self, canvas: TerminalCanvas, settings: dict, now: float, pool: tuple[str, ...]) -> None:
        if not self.event:
            return
        progress = self._event_progress(now)
        if self.event["Kind"] == "message":
            message = self._decoded_message(self.event, progress, pool, now)
            max_width = max(16, min(canvas.width - 8, 72))
            lines = textwrap.wrap(message, width=max_width, replace_whitespace=False, drop_whitespace=False) or [message]
            start_y = max(1, (canvas.height - len(lines)) // 2)
            for index, line in enumerate(lines):
                canvas.centered_text(start_y + index, line, 3)
        else:
            lines = self.event.get("Art", [])
            if not isinstance(lines, list):
                return
            visible = len(lines) if progress >= 1.0 else max(1, int(math.ceil(len(lines) * progress)))
            partial = lines[:visible]
            art_width = min(canvas.width - 4, max((len(line) for line in partial), default=0))
            art_height = min(canvas.height - 4, len(partial))
            canvas.art(2, 2, max(1, canvas.width - 4), max(1, canvas.height - 4), partial, 3, True, True)

    def _draw_rain(self, canvas: TerminalCanvas, settings: dict, pool: tuple[str, ...]) -> None:
        direction = self._direction(settings)
        multiplier = self._speed_multiplier(int(settings.get("RainSpeed", 50)))
        for column, streams in enumerate(self.streams):
            for stream in streams:
                stream.advance(canvas.height, multiplier, direction)
                head = int(stream.head)
                buffer = stream.ensure_characters(pool)
                if direction > 0:
                    first = max(0, head - (canvas.height - 1))
                    last = min(stream.length - 1, head)
                else:
                    first = max(0, -head)
                    last = min(stream.length - 1, canvas.height - 1 - head)
                if last < first:
                    continue
                for distance in range(first, last + 1):
                    row = head - distance if direction > 0 else head + distance
                    if not 0 <= row < canvas.height:
                        continue
                    style = 4 if distance == 0 else 3 if distance <= 2 else 2 if distance <= 5 else 1
                    index = row * canvas.width + column
                    existing = canvas.cells[index]
                    if existing.style <= style:
                        canvas.put(column, row, buffer[distance], style, True)

    def _randomize(self, settings: dict, pool: tuple[str, ...], now: float) -> None:
        speed = max(0, min(100, int(settings.get("RainCharacterRandomizationSpeed", 50))))
        if speed <= 0:
            return
        interval = 1.5 * (0.025 ** (speed / 100.0))
        if now - self.last_randomize < interval:
            return
        self.last_randomize = now
        for streams in self.streams:
            for stream in streams:
                if random.random() < 0.45:
                    stream.randomize_character(pool)

    def render(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        self._ensure_streams(settings, width, height)
        if self.event and now >= float(self.event["End"]):
            self.event = None
            self.glitch_at = None
        if self.event is None and now >= self.next_event_at:
            self._start_event(settings, now)
        pool = self._pool(settings)
        self._randomize(settings, pool, now)
        canvas = self.ui.canvas(width, height)
        self._draw_event(canvas, settings, now, pool)
        self._draw_rain(canvas, settings, pool)
        if self.glitch_at is not None and now >= self.glitch_at and self.glitch_until <= now:
            self.glitch_until = now + random.uniform(0.22, 0.65)
            self.glitch_at = None
        if now < self.glitch_until:
            self.ui.apply_glitch(canvas, pool, 0.18, int(now * 20))
        return canvas

    def handle_runtime_key(self, key: str, settings: dict) -> bool:
        changed = False
        if key in {"+", "="}:
            settings["RainDensity"] = min(100, int(settings.get("RainDensity", 80)) + 10)
            changed = True
        elif key in {"-", "_"}:
            settings["RainDensity"] = max(0, int(settings.get("RainDensity", 80)) - 10)
            changed = True
        elif key == "UP":
            settings["RainSpeed"] = min(100, int(settings.get("RainSpeed", 50)) + 5)
            changed = True
        elif key == "DOWN":
            settings["RainSpeed"] = max(0, int(settings.get("RainSpeed", 50)) - 5)
            changed = True
        elif key == "BACKSPACE":
            self.reverse_direction(settings)
            changed = True
        return changed

    def reverse_direction(self, settings: dict) -> None:
        settings["RainDirection"] = "Up" if str(settings.get("RainDirection", "Down")).casefold() == "down" else "Down"

    def primary_speed_label(self, settings: dict) -> str:
        return f"Rain Speed {int(settings.get('RainSpeed', 50))}%"

PROTOCOL_CLASS = TerminalSSMatrixProtocol
