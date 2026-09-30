from __future__ import annotations

import colorsys
import math
import random
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable


RESET = "\033[0m"
BOLD = "\033[1m"
CURSOR_HOME = "\033[H"
SYNC_START = "\033[?2026h"
SYNC_END = "\033[?2026l"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

PALETTE = {
    "Matrix Green": (0, 255, 70),
    "Lime": (150, 255, 40),
    "Yellow": (255, 230, 40),
    "Orange": (255, 145, 20),
    "Red": (255, 55, 55),
    "Crimson": (220, 20, 60),
    "Pink": (255, 105, 180),
    "Magenta": (255, 50, 220),
    "Purple": (180, 70, 255),
    "Violet": (125, 70, 255),
    "Blue": (45, 125, 255),
    "Azure": (0, 155, 255),
    "Cyan": (0, 255, 255),
    "Teal": (0, 205, 170),
    "Mint": (80, 255, 185),
    "White": (245, 245, 245),
    "Silver": (200, 210, 220),
    "Gray": (145, 145, 145),
    "Amber": (255, 190, 20),
    "Electric Blue": (0, 110, 255),
    "Indigo": (75, 0, 200),
    "Lavender": (200, 155, 255),
    "Coral": (255, 110, 90),
    "Gold": (255, 205, 40),
    "Aqua": (40, 255, 220),
    "Neon Green": (70, 255, 40),
}

COLOUR_KEYS = {
    "q": "Matrix Green",
    "w": "Lime",
    "e": "Yellow",
    "r": "Orange",
    "t": "Red",
    "y": "Crimson",
    "u": "Pink",
    "i": "Magenta",
    "o": "Purple",
    "p": "Violet",
    "a": "Blue",
    "s": "Azure",
    "d": "Cyan",
    "f": "Teal",
    "g": "Mint",
    "h": "White",
    "j": "Silver",
    "k": "Gray",
    "l": "Amber",
    "z": "Electric Blue",
    "x": "Indigo",
    "c": "Lavender",
    "v": "Coral",
    "b": "Gold",
    "n": "Aqua",
    "m": "Neon Green",
}

COLOUR_ORDER = tuple(PALETTE)


def is_emoji_codepoint(codepoint: int) -> bool:
    return (
        0x1F1E6 <= codepoint <= 0x1F1FF
        or 0x1F300 <= codepoint <= 0x1F6FF
        or 0x1F900 <= codepoint <= 0x1FAFF
    )


def display_width(token: str) -> int:
    if not token or token == " ":
        return 1
    width = 0
    emoji = False
    for char in token:
        codepoint = ord(char)
        if char == "\u200d" or 0xFE00 <= codepoint <= 0xFE0F:
            continue
        if unicodedata.combining(char):
            continue
        if is_emoji_codepoint(codepoint):
            emoji = True
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    if emoji:
        return 2
    return max(1, width)


def rgb_escape(rgb: tuple[int, int, int], factor: float = 1.0) -> str:
    red, green, blue = rgb
    red = max(0, min(255, int(red * factor)))
    green = max(0, min(255, int(green * factor)))
    blue = max(0, min(255, int(blue * factor)))
    return f"\033[38;2;{red};{green};{blue}m"


def clamp_percent(value) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, number))


def interpolate_rgb(first: tuple[int, int, int], second: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(int(round(a + (b - a) * amount)) for a, b in zip(first, second))


def colour_for_settings(settings: dict, now: float) -> tuple[int, int, int]:
    if settings.get("RGB", False):
        speed = clamp_percent(settings.get("RGBSpeed", 50))
        period = 20.0 * (0.1 ** (speed / 100.0))
        hue = (now / max(0.25, period)) % 1.0
        red, green, blue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        return int(red * 255), int(green * 255), int(blue * 255)
    if settings.get("CustomColorShift", False):
        names = [name for name in settings.get("CustomColorShiftColors", []) if name in PALETTE]
        if len(names) >= 2:
            speed = clamp_percent(settings.get("CustomColorShiftSpeed", 50))
            segment = 10.0 * (0.1 ** (speed / 100.0))
            position = now / max(0.25, segment)
            index = int(math.floor(position)) % len(names)
            amount = position - math.floor(position)
            return interpolate_rgb(PALETTE[names[index]], PALETTE[names[(index + 1) % len(names)]], amount)
    return PALETTE.get(settings.get("Color", "Matrix Green"), PALETTE["Matrix Green"])


def cycle_colour(name: str, step: int) -> str:
    try:
        index = COLOUR_ORDER.index(name)
    except ValueError:
        index = 0
    return COLOUR_ORDER[(index + step) % len(COLOUR_ORDER)]


@dataclass
class Cell:
    char: str = " "
    style: int = 0
    continuation: bool = False


class TerminalCanvas:
    def __init__(self, width: int, height: int):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.cells = [Cell() for _ in range(self.width * self.height)]

    def _index(self, x: int, y: int) -> int:
        return y * self.width + x

    def clear(self) -> None:
        self.cells = [Cell() for _ in range(self.width * self.height)]

    def put(self, x: int, y: int, char: str, style: int = 2, overwrite: bool = True) -> int:
        if not char or not 0 <= y < self.height or not 0 <= x < self.width:
            return 0
        width = display_width(char)
        if width > 2:
            width = 1
        if width == 2 and x + 1 >= self.width:
            char = " "
            width = 1
        index = self._index(x, y)
        if not overwrite and self.cells[index].style != 0:
            return width
        self.cells[index] = Cell(char, max(0, min(4, int(style))), False)
        if width == 2:
            self.cells[self._index(x + 1, y)] = Cell("", max(0, min(4, int(style))), True)
        return width

    def text(self, x: int, y: int, text: str, style: int = 2, max_width: int | None = None, overwrite: bool = True, transparent_spaces: bool = False) -> None:
        column = x
        limit = self.width if max_width is None else min(self.width, x + max(0, max_width))
        for char in str(text):
            width = display_width(char)
            if column + width > limit:
                break
            if transparent_spaces and char == " ":
                column += width
                continue
            moved = self.put(column, y, char, style, overwrite)
            column += moved if moved else width

    def centered_text(self, y: int, text: str, style: int = 2, left: int = 0, right: int | None = None, transparent_spaces: bool = False) -> None:
        right = self.width if right is None else min(self.width, right)
        available = max(0, right - left)
        visible = ANSI_RE.sub("", str(text))
        text_width = sum(display_width(char) for char in visible)
        x = left + max(0, (available - text_width) // 2)
        self.text(x, y, text, style, max_width=available, transparent_spaces=transparent_spaces)

    def line(self, x: int, y: int, length: int, char: str = "─", style: int = 1) -> None:
        for offset in range(max(0, length)):
            self.put(x + offset, y, char, style)

    def panel(self, x: int, y: int, width: int, height: int, title: str | None = None, style: int = 1) -> None:
        if width < 2 or height < 2:
            return
        right = min(self.width - 1, x + width - 1)
        bottom = min(self.height - 1, y + height - 1)
        if x < 0 or y < 0 or x >= self.width or y >= self.height or right <= x or bottom <= y:
            return
        self.put(x, y, "╭", style)
        self.put(right, y, "╮", style)
        self.put(x, bottom, "╰", style)
        self.put(right, bottom, "╯", style)
        for column in range(x + 1, right):
            self.put(column, y, "─", style)
            self.put(column, bottom, "─", style)
        for row in range(y + 1, bottom):
            self.put(x, row, "│", style)
            self.put(right, row, "│", style)
        if title:
            label = f" {title} "
            self.text(x + 2, y, label, max(style, 2), max_width=max(0, right - x - 3))

    def progress_bar(self, x: int, y: int, width: int, percent: float, style: int = 2) -> None:
        width = max(1, width)
        value = max(0.0, min(100.0, float(percent)))
        filled = int(round(width * value / 100.0))
        for offset in range(width):
            self.put(x + offset, y, "█" if offset < filled else "░", style if offset < filled else 1)

    def wrapped_text(self, x: int, y: int, width: int, lines: Iterable[str], style: int = 2, max_lines: int | None = None) -> int:
        row = y
        used = 0
        for source in lines:
            words = str(source).split(" ")
            current = ""
            chunks = []
            for word in words:
                candidate = word if not current else current + " " + word
                if len(candidate) <= width:
                    current = candidate
                else:
                    if current:
                        chunks.append(current)
                    current = word
            if current or not chunks:
                chunks.append(current)
            for chunk in chunks:
                if max_lines is not None and used >= max_lines:
                    return used
                if row >= self.height:
                    return used
                self.text(x, row, chunk, style, max_width=width)
                row += 1
                used += 1
        return used

    def art(self, x: int, y: int, width: int, height: int, lines: list[str], style: int = 1, centered: bool = True, overwrite: bool = True) -> None:
        if not lines or width <= 0 or height <= 0:
            return
        clipped = lines[:height]
        art_width = max((len(line) for line in clipped), default=0)
        start_y = y + max(0, (height - len(clipped)) // 2) if centered else y
        start_x = x + max(0, (width - art_width) // 2) if centered else x
        for row_offset, line in enumerate(clipped):
            row = start_y + row_offset
            if row >= y + height or row >= self.height:
                break
            for column_offset, char in enumerate(line[:width]):
                if char != " ":
                    self.put(start_x + column_offset, row, char, style, overwrite)

    def overlay_center_box(self, title: str, lines: list[str], width: int | None = None) -> None:
        target_width = width or min(self.width - 4, max(44, max((len(line) for line in lines), default=0) + 6))
        target_width = max(20, min(self.width - 2, target_width))
        target_height = min(self.height - 2, len(lines) + 4)
        x = max(0, (self.width - target_width) // 2)
        y = max(0, (self.height - target_height) // 2)
        for row in range(y, min(self.height, y + target_height)):
            for column in range(x, min(self.width, x + target_width)):
                self.put(column, row, " ", 0)
        self.panel(x, y, target_width, target_height, title, 3)
        for index, line in enumerate(lines[: max(0, target_height - 3)]):
            self.text(x + 2, y + 2 + index, line, 2, max_width=target_width - 4)


class TerminalSSUI:
    def __init__(self):
        self.palette = PALETTE
        self.colour_keys = COLOUR_KEYS

    def canvas(self, width: int, height: int) -> TerminalCanvas:
        return TerminalCanvas(width, height)

    def render(self, canvas: TerminalCanvas, settings: dict, now: float) -> str:
        base = colour_for_settings(settings, now)
        styles = (
            RESET,
            rgb_escape(base, 0.35),
            rgb_escape(base, 0.72),
            rgb_escape(base, 1.0),
            "\033[97m",
        )
        rows = []
        for row in range(canvas.height):
            output = []
            active = -1
            column = 0
            while column < canvas.width:
                cell = canvas.cells[row * canvas.width + column]
                if cell.continuation:
                    column += 1
                    continue
                style = cell.style
                if style != active:
                    output.append(styles[style])
                    active = style
                char = cell.char if cell.char else " "
                output.append(char)
                column += max(1, display_width(char))
            output.append(RESET)
            rows.append("".join(output))
        return SYNC_START + CURSOR_HOME + "\n".join(rows) + SYNC_END

    def analyser_trace(self, width: int, now: float, seed: int = 0, state: str = "normal", recovery: float = 1.0, speed: float = 1.0) -> str:
        width = max(0, int(width))
        if width <= 0:
            return ""
        state = str(state or "normal").casefold()
        if state == "failed":
            return "─" * width
        blocks = "▁▂▃▄▅▆▇█"
        speed = max(0.2, float(speed))
        tick = int(now * (17.0 + speed * 9.0))
        rng = random.Random(int(seed) ^ tick)
        if state == "glitch":
            trace = []
            for index in range(width):
                if rng.random() < 0.12:
                    trace.append("─")
                    continue
                value = rng.randrange(len(blocks))
                if rng.random() < 0.34:
                    value = rng.choice((0, 1, len(blocks) - 2, len(blocks) - 1))
                trace.append(blocks[value])
            return "".join(trace)
        recovery = max(0.0, min(1.0, float(recovery)))
        if state == "recovery" and recovery <= 0.03:
            return "─" * width
        amplitude = recovery if state == "recovery" else 1.0
        trace = []
        phase = (int(seed) % 97) * 0.071
        for index in range(width):
            carrier = math.sin(index * 0.57 + now * 3.4 * speed + phase) * 0.82
            harmonic = math.sin(index * 0.21 - now * 2.1 * speed + phase * 0.5) * 0.48
            noise = (rng.random() - 0.5) * 0.58
            value = (carrier + harmonic + noise + 1.95) / 3.9
            if state == "recovery":
                value = 0.04 + value * amplitude * 0.96
            block_index = int(round(value * (len(blocks) - 1)))
            trace.append(blocks[max(0, min(len(blocks) - 1, block_index))])
        return "".join(trace)

    def apply_glitch(self, canvas: TerminalCanvas, pool: tuple[str, ...], strength: float = 0.18, seed: int | None = None) -> None:
        rng = random.Random(seed)
        usable = tuple(token for token in pool if display_width(token) == 1) or tuple("01#@$%&*+-=<>?/\\|[]{}")
        strength = max(0.02, min(0.5, float(strength)))
        count = max(1, int(canvas.width * canvas.height * strength * 0.08))
        for _ in range(count):
            x = rng.randrange(canvas.width)
            y = rng.randrange(canvas.height)
            canvas.put(x, y, rng.choice(usable), rng.choice((1, 2, 3, 4)))
        bands = max(1, int(1 + strength * 8))
        for _ in range(bands):
            y = rng.randrange(canvas.height)
            start = rng.randrange(canvas.width)
            length = rng.randint(3, max(3, min(canvas.width - start, int(canvas.width * (0.15 + strength))))) if start < canvas.width - 2 else 1
            for x in range(start, min(canvas.width, start + length)):
                canvas.put(x, y, rng.choice(usable), rng.choice((1, 2, 3)))

    def help_canvas(self, width: int, height: int, protocol_name: str, protocol_keys: dict[str, str] | None = None) -> TerminalCanvas:
        canvas = self.canvas(width, height)
        lines = [
            f"CURRENT PROTOCOL: {protocol_name}",
            "",
            "ESC / CTRL+C  Exit",
            "SPACE         Pause / Resume",
            "0             Current Protocol Settings",
        ]
        if protocol_keys:
            for key, name in sorted(protocol_keys.items(), key=lambda item: item[0]):
                lines.append(f"{key:<13} {name} Protocol")
        lines.extend([
            "?             Help / Return",
            "LEFT / RIGHT  Previous / Next fixed colour",
            "A-Z           Direct fixed colour selection",
            "[             Toggle RGB",
            "]             Toggle Custom Color Shift",
        ])
        if protocol_name == "Matrix":
            lines.extend([
                "",
                "MATRIX CONTROLS",
                "+ / -         More / Less rain",
                "UP / DOWN     Faster / Slower rain",
                "BACKSPACE     Reverse rain direction",
            ])
        canvas.overlay_center_box("TERMINALSS", lines, min(76, width - 2))
        return canvas
