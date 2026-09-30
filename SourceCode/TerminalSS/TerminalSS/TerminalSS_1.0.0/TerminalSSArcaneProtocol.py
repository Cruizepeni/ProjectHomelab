from __future__ import annotations

import hashlib
import math
import random
import time
from pathlib import Path
from typing import Any

from TerminalSSUI import TerminalSSUI, TerminalCanvas, display_width


def normalized_key(value: str) -> str:
    return "".join(char for char in str(value).casefold() if char.isalnum())


def parse_headers_and_sections(text: str, sections) -> tuple[dict[str, str], dict[str, list[list[str]]]]:
    names = {normalized_key(name): str(name) for name in sections}
    headers: dict[str, str] = {}
    result: dict[str, list[list[str]]] = {name: [] for name in names.values()}
    current_name: str | None = None
    current_lines: list[str] = []
    for raw in str(text).splitlines():
        stripped = raw.strip()
        if stripped.endswith(":"):
            section = names.get(normalized_key(stripped[:-1]))
            if section is not None:
                if current_name is not None:
                    result[current_name].append(current_lines)
                current_name = section
                current_lines = []
                continue
        if current_name is not None:
            current_lines.append(raw.rstrip())
            continue
        if ":" in raw:
            key, value = raw.split(":", 1)
            key = key.strip()
            if key:
                headers[key] = value.strip() or "Unknown"
    if current_name is not None:
        result[current_name].append(current_lines)
    for groups in result.values():
        for group in groups:
            while group and not group[0].strip():
                group.pop(0)
            while group and not group[-1].strip():
                group.pop()
    return headers, result


def header_value(headers: dict[str, str], key: str, default: str = "Unknown") -> str:
    target = normalized_key(key)
    for name, value in headers.items():
        if normalized_key(name) == target:
            text = str(value).strip()
            return text if text else default
    return default


class TerminalSSArcaneProtocol:
    PROTOCOL_ID = "Arcane"
    KEY = "2"
    TRANSITION_MESSAGES = {
        "Success": (
            "ANALYSIS COMPLETE",
            "ARCHIVING DECRYPTED TEXT...",
            "CATALOGUING ARCANE SIGNATURE...",
            "PAGE RECOVERED",
        ),
        "Failure": (
            "ERROR! PAGE UNRECOVERABLE!",
            "ARCHIVING PARTIAL DECRYPTION...",
            "CORRUPTED GLYPHS DISCARDED...",
            "RECOVERY LIMIT REACHED",
        ),
        "NextPage": (
            "TURNING PAGE...",
            "SCANNING NEXT PAGE...",
            "LOCATING NEXT LEGIBLE ENTRY...",
            "CALIBRATING GLYPH MATRIX...",
            "ARCANE SIGNATURE DETECTED...",
            "REINITIALISING DECODER...",
        ),
    }
    DEFAULT_SETTINGS = {
        "CharacterDecodingTime": [1.0, 3.0],
        "CharacterDecodingChance": 60,
        "BaseLineDisplayTime": 5.0,
        "SecondaryLineDisplayTime": 3.0,
        "TimeBetweenPages": 4.0,
        "DisplayArt": True,
        "Color": "Purple",
        "RGB": False,
        "RGBSpeed": 50,
        "CustomColorShift": False,
        "CustomColorShiftSpeed": 50,
        "CustomColorShiftColors": ["Purple", "Violet", "Magenta"],
        "GlitchChance": 2,
        "IncompletePageGlitchChance": 100,
    }
    SETTING_SCHEMA = {
        "CharacterDecodingTime": {"Label": "Character Decoding Time", "Type": "seconds_range", "Min": 0.1, "Max": 30},
        "CharacterDecodingChance": {"Label": "Character Decoding Chance", "Type": "percent"},
        "BaseLineDisplayTime": {"Label": "Base Line Display Time", "Type": "seconds", "Min": 0.5, "Max": 120},
        "SecondaryLineDisplayTime": {"Label": "Secondary Line Display Time", "Type": "seconds", "Min": 0, "Max": 120},
        "TimeBetweenPages": {"Label": "Time Between Pages", "Type": "seconds", "Min": 0, "Max": 120},
        "DisplayArt": {"Label": "Display Art", "Type": "boolean"},
        "Color": {"Label": "Color", "Type": "color"},
        "RGB": {"Label": "RGB", "Type": "boolean"},
        "RGBSpeed": {"Label": "RGB Speed", "Type": "percent"},
        "CustomColorShift": {"Label": "Custom Color Shift", "Type": "boolean"},
        "CustomColorShiftSpeed": {"Label": "Custom Color Shift Speed", "Type": "percent"},
        "CustomColorShiftColors": {"Label": "Custom Color Shift Colors", "Type": "color_list"},
        "GlitchChance": {"Label": "Glitch Chance", "Type": "percent"},
        "IncompletePageGlitchChance": {"Label": "Incomplete Page Glitch Chance", "Type": "percent"},
    }

    @classmethod
    def settings_contract(cls) -> dict[str, Any]:
        return {"Defaults": cls.DEFAULT_SETTINGS, "Schema": cls.SETTING_SCHEMA}

    def __init__(self, asset_manager, ui: TerminalSSUI):
        self.asset_manager = asset_manager
        self.ui = ui
        self.asset_path = self.asset_manager.protocol_path(self.PROTOCOL_ID)
        self.characters: tuple[str, ...] = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        self.transitions: dict[str, list[str]] = {}
        self.pages: list[dict[str, Any]] = []
        self.current_page: dict[str, Any] | None = None
        self.page_started = 0.0
        self.page_ends = 0.0
        self.transition_started = 0.0
        self.transition_ends = 0.0
        self.transition_sequence: list[str] = []
        self.in_transition = False
        self.last_page_path: Path | None = None
        self.mapping: dict[str, str] = {}
        self.reveal_order: list[str] = []
        self.decode_durations: list[float] = []
        self.decode_finished_at = 0.0
        self.result_started_at = 0.0
        self.glitch_at: float | None = None
        self.glitch_until = 0.0
        self.incomplete_glitch_pending = False
        self.incomplete_glitch_triggered = False
        self.load_assets()

    def load_assets(self) -> None:
        pool = self.asset_manager.character_set("Curated Arcane", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        unique = []
        seen = set()
        for token in pool:
            if token and token not in seen and display_width(token) == 1:
                seen.add(token)
                unique.append(token)
        self.characters = tuple(unique) or tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        self.transitions = {key: list(values) for key, values in self.TRANSITION_MESSAGES.items()}
        self.pages = []
        for root in self.asset_manager.protocol_asset_roots(self.PROTOCOL_ID):
            for path in sorted(root.rglob("*.txt")):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                headers, sections = parse_headers_and_sections(text, ("Message", "Art"))
                message_groups = sections.get("Message", [])
                message = message_groups[0] if message_groups else []
                if not any(line.strip() for line in message):
                    continue
                known_headers = {key.casefold().replace(" ", "") for key in headers}
                if "pagesource" not in known_headers and "page" not in known_headers:
                    continue
                completion_raw = header_value(headers, "AnalysisCompletion")
                try:
                    completion = int(round(float(completion_raw)))
                except (TypeError, ValueError):
                    completion = 100
                page = {
                    "PageSource": header_value(headers, "PageSource"),
                    "Page": header_value(headers, "Page"),
                    "Language": header_value(headers, "Language"),
                    "Origin": header_value(headers, "Origin"),
                    "Classification": header_value(headers, "Classification"),
                    "AnalysisCompletion": max(0, min(100, completion)),
                    "Message": [str(line) for line in message],
                    "_Folder": path,
                    "_Art": [group for group in sections.get("Art", []) if any(line.strip() for line in group)],
                }
                self.pages.append(page)

    def reset(self, settings: dict, width: int, height: int, now: float | None = None) -> None:
        base = now if now is not None else time.monotonic()
        self.current_page = None
        self.in_transition = False
        self.transition_sequence = []
        self.glitch_at = None
        self.glitch_until = 0.0
        self.incomplete_glitch_pending = False
        self.incomplete_glitch_triggered = False
        self._start_page(settings, base)

    def _choose_page(self) -> dict[str, Any] | None:
        if not self.pages:
            return None
        choices = self.pages
        if self.last_page_path is not None and len(self.pages) > 1:
            filtered = [page for page in self.pages if page.get("_Folder") != self.last_page_path]
            if filtered:
                choices = filtered
        page = random.choice(choices)
        self.last_page_path = page.get("_Folder")
        return page

    def _build_mapping(self, page: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
        message = "\n".join(page.get("Message", []))
        analysis = "\n".join(str(page.get(key, "Unknown")) for key in ("Page", "Language", "Origin", "Classification"))
        corpus = message + "\n" + analysis
        symbols = []
        seen = set()
        for char in corpus:
            key = char.upper()
            if char.isalnum() and key not in seen:
                seen.add(key)
                symbols.append(key)
        seed_text = str(page.get("_Folder", "")) + "|" + corpus
        seed = int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:8], "big")
        rng = random.Random(seed)
        glyphs = list(self.characters)
        rng.shuffle(glyphs)
        if len(glyphs) < len(symbols):
            fallback = [char for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" if char not in glyphs]
            rng.shuffle(fallback)
            glyphs.extend(fallback)
        while len(glyphs) < len(symbols):
            glyphs.append(chr(0x2500 + (len(glyphs) % 128)))
        mapping = {symbol: glyphs[index] for index, symbol in enumerate(symbols)}
        reveal = list(symbols)
        rng.shuffle(reveal)
        return mapping, reveal

    @staticmethod
    def _decoding_range(settings: dict) -> tuple[float, float]:
        value = settings.get("CharacterDecodingTime", [1.0, 3.0])
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                minimum = max(0.1, float(value[0]))
                maximum = max(0.1, float(value[1]))
            except (TypeError, ValueError):
                minimum, maximum = 1.0, 3.0
        else:
            minimum, maximum = 1.0, 3.0
        if minimum > maximum:
            minimum, maximum = maximum, minimum
        return minimum, maximum

    @staticmethod
    def _message_line_count(page: dict[str, Any] | None) -> int:
        if not page:
            return 1
        lines = [line for line in page.get("Message", []) if isinstance(line, str) and line.strip()]
        return max(1, len(lines))

    def _result_display_time(self, page: dict[str, Any] | None, settings: dict) -> float:
        base = max(0.5, float(settings.get("BaseLineDisplayTime", 5.0)))
        secondary = max(0.0, float(settings.get("SecondaryLineDisplayTime", 3.0)))
        return base + (self._message_line_count(page) - 1) * secondary

    def _build_decode_durations(self, page: dict[str, Any] | None, settings: dict) -> list[float]:
        if not page or not self.reveal_order:
            return []
        target = max(0, min(100, int(page.get("AnalysisCompletion", 100))))
        target_mappings = int(math.floor(len(self.reveal_order) * target / 100.0))
        if target >= 100:
            target_mappings = len(self.reveal_order)
        minimum, maximum = self._decoding_range(settings)
        delay_chance = max(0, min(100, int(settings.get("CharacterDecodingChance", 60))))
        delayed_minimum = minimum + (maximum - minimum) * 0.5
        durations = []
        for _ in range(target_mappings):
            if maximum > minimum and random.random() * 100 < delay_chance:
                durations.append(random.uniform(delayed_minimum, maximum))
            else:
                durations.append(minimum)
        return durations

    def _start_page(self, settings: dict, now: float) -> None:
        page = self._choose_page()
        self.current_page = page
        self.in_transition = False
        self.transition_sequence = []
        self.page_started = now
        self.mapping, self.reveal_order = self._build_mapping(page) if page else ({}, [])
        self.glitch_at = None
        self.glitch_until = 0.0
        self.incomplete_glitch_pending = False
        self.incomplete_glitch_triggered = False
        if page is not None and int(page.get("AnalysisCompletion", 100)) < 100:
            incomplete_chance = max(0, min(100, int(settings.get("IncompletePageGlitchChance", 100))))
            self.incomplete_glitch_pending = random.random() * 100 < incomplete_chance
        self.decode_durations = self._build_decode_durations(page, settings)
        decode_total = sum(self.decode_durations)
        self.decode_finished_at = now + decode_total
        self.result_started_at = self.decode_finished_at + (0.5 if self.incomplete_glitch_pending else 0.0)
        self.page_ends = self.result_started_at + self._result_display_time(page, settings)
        chance = max(0, min(100, int(settings.get("GlitchChance", 2))))
        total_duration = max(0.5, self.page_ends - now)
        if page is not None and random.random() * 100 < chance:
            earliest = now + min(1.0, total_duration * 0.15)
            latest = now + max(min(1.1, total_duration * 0.2), total_duration * 0.82)
            if latest > earliest:
                self.glitch_at = random.uniform(earliest, latest)

    def _transition_messages(self, success: bool) -> list[str]:
        result = []
        source = self.transitions.get("Success" if success else "Failure", [])
        if source:
            result.append(random.choice(source))
        next_page = self.transitions.get("NextPage", [])
        if next_page:
            count = min(2, len(next_page))
            result.extend(random.sample(next_page, count))
        if not result:
            result = ["TURNING PAGE...", "SCANNING NEXT PAGE..."]
        return result

    def _start_transition(self, settings: dict, now: float) -> None:
        completion = int(self.current_page.get("AnalysisCompletion", 100)) if self.current_page else 0
        success = completion >= 100
        self.in_transition = True
        self.transition_started = now
        duration = max(0.0, float(settings.get("TimeBetweenPages", 4.0)))
        self.transition_ends = now + duration
        self.transition_sequence = self._transition_messages(success)
        self.glitch_at = None

    def _decode_state(self, now: float) -> tuple[set[str], str | None, str | None, float, int, bool]:
        if not self.current_page:
            return set(), None, None, 0.0, 0, True
        target = max(0, min(100, int(self.current_page.get("AnalysisCompletion", 100))))
        target_count = len(self.decode_durations)
        if target_count <= 0:
            return set(), None, None, 1.0, target, True
        elapsed = max(0.0, now - self.page_started)
        resolved_count = 0
        active_progress = 0.0
        remaining = elapsed
        for duration in self.decode_durations:
            if remaining >= duration:
                resolved_count += 1
                remaining -= duration
                continue
            active_progress = max(0.0, min(1.0, remaining / max(0.001, duration)))
            break
        resolved_count = min(target_count, resolved_count)
        revealed = set(self.reveal_order[:resolved_count])
        finished = resolved_count >= target_count or now >= self.decode_finished_at
        if finished:
            return set(self.reveal_order[:target_count]), None, None, 1.0, target, True
        active = self.reveal_order[resolved_count]
        candidates = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        tick = int(now * 18.0)
        seed = tick ^ sum((index + 1) * ord(char) for index, char in enumerate(active))
        candidate = random.Random(seed).choice(candidates)
        overall = (resolved_count + active_progress) / max(1, target_count)
        completion = int(round(target * overall))
        return revealed, active, candidate, max(0.0, min(1.0, overall)), min(target, completion), False

    def _encode_line(self, line: str) -> str:
        output = []
        for char in line:
            key = char.upper()
            output.append(self.mapping.get(key, char) if char.isalnum() else char)
        return "".join(output)

    def _decrypt_line(self, line: str, revealed: set[str], active: str | None, candidate: str | None) -> str:
        output = []
        for char in line:
            key = char.upper()
            if char.isalnum() and key in revealed:
                output.append(char)
            elif char.isalnum() and active is not None and key == active and candidate is not None:
                output.append(candidate.lower() if char.islower() else candidate)
            elif char.isalnum():
                output.append(self.mapping.get(key, char))
            else:
                output.append(char)
        return "".join(output)

    def _decrypt_value(self, value: Any, revealed: set[str], active: str | None, candidate: str | None) -> str:
        text = "Unknown" if value is None or str(value).strip() == "" else str(value)
        return self._decrypt_line(text, revealed, active, candidate)

    @staticmethod
    def _fit_lines(lines: list[str], width: int, max_lines: int) -> list[str]:
        result = []
        for line in lines:
            current = str(line)
            if width <= 1:
                result.append(current[:1])
                continue
            while len(current) > width:
                result.append(current[:width])
                current = current[width:]
                if len(result) >= max_lines:
                    return result
            result.append(current)
            if len(result) >= max_lines:
                return result
        return result

    def _art_lines(self, page: dict[str, Any], progress: float) -> list[str]:
        blocks = page.get("_Art", [])
        if not isinstance(blocks, list) or not blocks:
            return []
        valid = [block for block in blocks if isinstance(block, list)]
        if not valid:
            return []
        index = min(len(valid) - 1, int(progress * len(valid))) if progress < 1.0 else len(valid) - 1
        return [str(line) for line in valid[index]]

    def _draw_source(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, page: dict[str, Any], progress: float, settings: dict) -> None:
        source = str(page.get("PageSource", "UNKNOWN")).upper()
        canvas.panel(x, y, width, height, f"PAGE SOURCE - {source}", 2)
        inner_x = x + 2
        inner_y = y + 2
        inner_width = max(1, width - 4)
        inner_height = max(1, height - 4)
        if settings.get("DisplayArt", True):
            art = self._art_lines(page, progress)
            if art:
                canvas.art(inner_x, inner_y, inner_width, inner_height, art, 1, True, True)
        encoded = [self._encode_line(line) for line in page.get("Message", [])]
        lines = self._fit_lines(encoded, inner_width, inner_height)
        start_y = inner_y + max(0, (inner_height - len(lines)) // 2)
        for index, line in enumerate(lines):
            canvas.centered_text(start_y + index, line, 3, inner_x, inner_x + inner_width, True)

    def _draw_progress_row(self, canvas: TerminalCanvas, x: int, y: int, width: int, label: str, value: float, style: int = 3) -> None:
        label_text = f"{label.upper()}:"
        percent = f"{max(0.0, min(100.0, value)):3.0f}%"
        label_x = x + 2
        content_right = x + width - 3
        percent_x = max(label_x + len(label_text) + 5, content_right - len(percent) + 1)
        bar_x = label_x + len(label_text) + 1
        bar_width = max(3, percent_x - bar_x - 1)
        canvas.text(label_x, y, label_text, 1, max_width=max(1, bar_x - label_x - 1))
        canvas.progress_bar(bar_x, y, bar_width, value, style)
        canvas.text(percent_x, y, percent, style, max_width=max(1, content_right - percent_x + 1))

    def _draw_language_analyser(self, canvas: TerminalCanvas, x: int, y: int, width: int, fraction: float, now: float, page: dict[str, Any]) -> None:
        label = "LANGUAGE ANALYSER:"
        label_x = x + 2
        content_right = x + width - 3
        analyser_x = label_x + len(label) + 1
        analyser_width = max(1, content_right - analyser_x + 1)
        canvas.text(label_x, y, label, 1, max_width=max(1, analyser_x - label_x - 1))
        seed_text = str(page.get("_Folder", "")) + "|" + str(page.get("Language", "Unknown"))
        seed = int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:4], "big")
        target = max(0, min(100, int(page.get("AnalysisCompletion", 100))))
        hard_failure = target < 100 and now >= self.decode_finished_at
        if hard_failure:
            state = "failed"
            recovery = 0.0
        elif now < self.glitch_until:
            state = "glitch"
            recovery = 1.0
        elif fraction < 0.18:
            state = "recovery"
            recovery = max(0.0, min(1.0, fraction / 0.18))
        else:
            state = "normal"
            recovery = 1.0
        analyser = self.ui.analyser_trace(analyser_width, now, seed, state, recovery, 0.9)
        canvas.text(analyser_x, y, analyser, 2, max_width=analyser_width)

    def _draw_arcane_decoder(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, page: dict[str, Any], fraction: float, completion: int, now: float) -> None:
        canvas.panel(x, y, width, height, "ARCANE DECODER", 2)
        row = y + 2
        bottom = y + height - 1
        if row < bottom:
            self._draw_language_analyser(canvas, x, row, width, fraction, now, page)
            row += 1
        if row + 1 < bottom:
            row += 1
        if row < bottom:
            style = 4 if int(page.get("AnalysisCompletion", 100)) < 100 and completion >= int(page.get("AnalysisCompletion", 100)) else 3
            self._draw_progress_row(canvas, x, row, width, "Analysis Completion", completion, style)

    def _draw_page_analysis(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, page: dict[str, Any], revealed: set[str], active: str | None, candidate: str | None) -> None:
        canvas.panel(x, y, width, height, "PAGE ANALYSIS", 2)
        label_x = x + 2
        row = y + 2
        bottom = y + height - 1
        content_right = x + width - 3
        value_x = x + min(24, max(19, width // 3 + 2))
        value_width = max(1, content_right - value_x + 1)
        fields = [
            ("PAGE", self._decrypt_value(page.get("Page", "Unknown"), revealed, active, candidate)),
            ("LANGUAGE", self._decrypt_value(page.get("Language", "Unknown"), revealed, active, candidate)),
            ("ORIGIN", self._decrypt_value(page.get("Origin", "Unknown"), revealed, active, candidate)),
            ("CLASSIFICATION", self._decrypt_value(page.get("Classification", "Unknown"), revealed, active, candidate)),
        ]
        for label, value in fields:
            if row >= bottom:
                return
            canvas.text(label_x, row, f"{label}:", 1, max_width=max(1, value_x - label_x - 1))
            canvas.text(value_x, row, str(value).upper(), 2, max_width=value_width)
            row += 1

    def _draw_page_decryption(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, page: dict[str, Any], now: float, revealed: set[str], active: str | None, candidate: str | None, finished: bool) -> None:
        canvas.panel(x, y, width, height, "PAGE DECRYPTION", 2)
        inner_x = x + 2
        inner_y = y + 2
        inner_width = max(1, width - 4)
        inner_height = max(1, height - 4)
        decrypted = [self._decrypt_line(line, revealed, active, candidate) for line in page.get("Message", [])]
        target = int(page.get("AnalysisCompletion", 100))
        show_status = finished and now >= self.result_started_at and inner_height >= 3
        message_height = max(1, inner_height - (2 if show_status else 0))
        lines = self._fit_lines(decrypted, inner_width, message_height)
        start_y = inner_y + max(0, (message_height - len(lines)) // 2)
        for index, line in enumerate(lines[:message_height]):
            canvas.centered_text(start_y + index, line, 3, inner_x, inner_x + inner_width, True)
        if show_status:
            status = "PAGE RECOVERED" if target >= 100 else "ERROR! PAGE UNRECOVERABLE!"
            canvas.centered_text(y + height - 2, status, 4, inner_x, inner_x + inner_width, True)

    @staticmethod
    def _right_panel_heights(height: int) -> tuple[int, int, int]:
        if height >= 24:
            decoder_height = 7
            analysis_height = 8
        elif height >= 18:
            decoder_height = 6
            analysis_height = 7
        elif height >= 13:
            decoder_height = 5
            analysis_height = 6
        else:
            decoder_height = max(3, height // 3)
            analysis_height = max(3, height // 3)
        if decoder_height + analysis_height > height - 3:
            overflow = decoder_height + analysis_height - (height - 3)
            reduce_analysis = min(overflow, max(0, analysis_height - 5))
            analysis_height -= reduce_analysis
            overflow -= reduce_analysis
            decoder_height = max(3, decoder_height - overflow)
        decryption_height = max(1, height - decoder_height - analysis_height)
        return decoder_height, analysis_height, decryption_height

    def _draw_page(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        canvas = self.ui.canvas(width, height)
        page = self.current_page
        if page is None:
            canvas.overlay_center_box("ARCANE PROTOCOL", ["NO PAGE ASSETS AVAILABLE", "CHECK APPDATA/ASSETS/TERMINALSS/ARCANEPROTOCOL"])
            return canvas
        revealed, active, candidate, fraction, completion, finished = self._decode_state(now)
        if width >= 88:
            gap = 1
            left_width = width // 2
            right_x = left_width + gap
            right_width = width - right_x
            decoder_height, analysis_height, decryption_height = self._right_panel_heights(height)
            analysis_y = decoder_height
            decryption_y = decoder_height + analysis_height
            self._draw_source(canvas, 0, 0, left_width, height, page, fraction, settings)
            if decoder_height >= 3:
                self._draw_arcane_decoder(canvas, right_x, 0, right_width, decoder_height, page, fraction, completion, now)
            if analysis_height >= 3:
                self._draw_page_analysis(canvas, right_x, analysis_y, right_width, analysis_height, page, revealed, active, candidate)
            if decryption_height >= 3:
                self._draw_page_decryption(canvas, right_x, decryption_y, right_width, decryption_height, page, now, revealed, active, candidate, finished)
        else:
            if height >= 28:
                source_height = max(8, int(round(height * 0.34)))
            elif height >= 20:
                source_height = max(6, int(round(height * 0.30)))
            else:
                source_height = max(4, height // 4)
            remaining = max(1, height - source_height)
            decoder_height, analysis_height, decryption_height = self._right_panel_heights(remaining)
            decoder_y = source_height
            analysis_y = decoder_y + decoder_height
            decryption_y = analysis_y + analysis_height
            self._draw_source(canvas, 0, 0, width, source_height, page, fraction, settings)
            if decoder_height >= 3:
                self._draw_arcane_decoder(canvas, 0, decoder_y, width, decoder_height, page, fraction, completion, now)
            if analysis_height >= 3:
                self._draw_page_analysis(canvas, 0, analysis_y, width, analysis_height, page, revealed, active, candidate)
            if decryption_height >= 3:
                self._draw_page_decryption(canvas, 0, decryption_y, width, decryption_height, page, now, revealed, active, candidate, finished)
        return canvas

    def _transition_text(self, now: float) -> tuple[str, float]:
        if not self.transition_sequence:
            return "SCANNING NEXT PAGE...", 1.0
        duration = max(0.001, self.transition_ends - self.transition_started)
        segment = duration / len(self.transition_sequence)
        elapsed = max(0.0, now - self.transition_started)
        index = min(len(self.transition_sequence) - 1, int(elapsed / max(0.001, segment)))
        local = (elapsed - index * segment) / max(0.001, segment)
        return self.transition_sequence[index], max(0.0, min(1.0, local))

    def _scramble_transition(self, text: str, progress: float, now: float) -> str:
        positions = [index for index, char in enumerate(text) if not char.isspace()]
        reveal = int(math.floor(len(positions) * min(1.0, progress * 1.6)))
        revealed = set(positions[:reveal])
        rng = random.Random(int(now * 14) ^ len(text))
        output = []
        for index, char in enumerate(text):
            if char.isspace() or index in revealed:
                output.append(char)
            else:
                output.append(rng.choice(self.characters))
        return "".join(output)

    def _draw_transition(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        canvas = self.ui.canvas(width, height)
        text, progress = self._transition_text(now)
        display = self._scramble_transition(text, progress, now)
        canvas.overlay_center_box("ARCANE DECODER", [display])
        return canvas

    def render(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        if self.in_transition:
            if now >= self.transition_ends:
                self._start_page(settings, now)
            else:
                canvas = self._draw_transition(width, height, settings, now)
                if now < self.glitch_until:
                    self.ui.apply_glitch(canvas, self.characters, 0.16, int(now * 20))
                return canvas
        if self.current_page is None:
            self._start_page(settings, now)
        if now >= self.page_ends:
            self._start_transition(settings, now)
            if self.transition_ends <= now:
                self._start_page(settings, now)
            else:
                return self._draw_transition(width, height, settings, now)
        _, _, _, _, _, finished = self._decode_state(now)
        if self.current_page is not None and int(self.current_page.get("AnalysisCompletion", 100)) < 100:
            if finished and self.incomplete_glitch_pending and not self.incomplete_glitch_triggered:
                self.glitch_until = max(self.glitch_until, now + 0.5)
                self.incomplete_glitch_triggered = True
        canvas = self._draw_page(width, height, settings, now)
        if self.glitch_at is not None and now >= self.glitch_at and self.glitch_until <= now:
            self.glitch_until = now + random.uniform(0.22, 0.7)
            self.glitch_at = None
        if now < self.glitch_until:
            self.ui.apply_glitch(canvas, self.characters, 0.16, int(now * 20))
        return canvas

    def handle_runtime_key(self, key: str, settings: dict) -> bool:
        minimum, maximum = self._decoding_range(settings)
        if key in {"+", "="}:
            minimum = max(0.1, minimum - 0.25)
            maximum = max(minimum, maximum - 0.25)
            settings["CharacterDecodingTime"] = [round(minimum, 2), round(maximum, 2)]
            return True
        if key in {"-", "_"}:
            minimum = min(30.0, minimum + 0.25)
            maximum = min(30.0, max(minimum, maximum + 0.25))
            settings["CharacterDecodingTime"] = [round(minimum, 2), round(maximum, 2)]
            return True
        return False

    def reverse_direction(self, settings: dict) -> None:
        return None

    def primary_speed_label(self, settings: dict) -> str:
        minimum, maximum = self._decoding_range(settings)
        return f"Character Decode Time {minimum:g}-{maximum:g}s"


PROTOCOL_CLASS = TerminalSSArcaneProtocol
