from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from TerminalSSUI import BOLD, PALETTE, RESET, rgb_escape


class TerminalSSSettings:
    SETTINGS_VERSION = 4

    def __init__(self, project_root: str | Path, protocol_contracts: dict[str, dict[str, Any]]):
        self.project_root = Path(project_root).resolve()
        self.settings_path = self.project_root / "Appdata" / "Settings" / "TerminalSSSettingsConfig.json"
        legacy_settings_path = self.project_root / "Appdata" / "Settings" / "EnterTheMatrixSettingsConfig.json"
        if not self.settings_path.exists() and legacy_settings_path.is_file():
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_settings_path, self.settings_path)
        self.protocol_contracts = copy.deepcopy(protocol_contracts)
        self.protocol_names = tuple(protocol_contracts)
        self._data: dict[str, Any] = {}
        self.load()

    def _default_document(self) -> dict[str, Any]:
        return {
            "Version": self.SETTINGS_VERSION,
            "General": {
                "Fullscreen": True,
            },
            "Protocols": {
                protocol: copy.deepcopy(contract.get("Defaults", {}))
                for protocol, contract in self.protocol_contracts.items()
            },
        }

    def _backup_corrupt_file(self) -> None:
        if not self.settings_path.exists():
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.settings_path.with_name(f"{self.settings_path.stem}.corrupt-{stamp}{self.settings_path.suffix}")
        index = 1
        while target.exists():
            target = self.settings_path.with_name(f"{self.settings_path.stem}.corrupt-{stamp}-{index}{self.settings_path.suffix}")
            index += 1
        self.settings_path.replace(target)

    def _atomic_write(self, data: dict[str, Any]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.settings_path.with_suffix(self.settings_path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(self.settings_path)

    @staticmethod
    def _clamp_number(value, minimum: float, maximum: float, integer: bool):
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = minimum
        number = max(minimum, min(maximum, number))
        return int(round(number)) if integer else number

    def _normalize_field(self, value: Any, spec: dict[str, Any], default: Any) -> Any:
        kind = spec.get("Type")
        if kind == "boolean":
            return value if isinstance(value, bool) else bool(default)
        if kind == "percent":
            return self._clamp_number(value, 0, 100, True)
        if kind == "seconds":
            minimum = float(spec.get("Min", 0.1))
            maximum = float(spec.get("Max", 3600.0))
            return self._clamp_number(value, minimum, maximum, False)
        if kind == "seconds_range":
            minimum = float(spec.get("Min", 0.1))
            maximum = float(spec.get("Max", 3600.0))
            source = value if isinstance(value, (list, tuple)) and len(value) >= 2 else default
            if not isinstance(source, (list, tuple)) or len(source) < 2:
                source = [minimum, maximum]
            low = self._clamp_number(source[0], minimum, maximum, False)
            high = self._clamp_number(source[1], minimum, maximum, False)
            if low > high:
                low, high = high, low
            return [low, high]
        if kind == "choice":
            choices = spec.get("Choices", [])
            if value in choices:
                return value
            if isinstance(value, str):
                for choice in choices:
                    if str(choice).casefold() == value.casefold():
                        return choice
            return default
        if kind == "color":
            if value in PALETTE:
                return value
            if isinstance(value, str):
                for colour in PALETTE:
                    if colour.casefold() == value.casefold():
                        return colour
            return default
        if kind == "color_list":
            values = value if isinstance(value, list) else default
            result = []
            for item in values if isinstance(values, list) else []:
                if item in PALETTE and item not in result:
                    result.append(item)
            if len(result) < 2:
                result = [item for item in default if item in PALETTE] if isinstance(default, list) else ["Matrix Green", "Cyan"]
            return result[:12]
        if kind == "integer":
            minimum = int(spec.get("Min", 0))
            maximum = int(spec.get("Max", 1000000))
            return self._clamp_number(value, minimum, maximum, True)
        return copy.deepcopy(value if value is not None else default)

    def _normalize_protocol(self, protocol: str, source: Any) -> dict[str, Any]:
        contract = self.protocol_contracts[protocol]
        defaults = contract.get("Defaults", {})
        schema = contract.get("Schema", {})
        raw = source if isinstance(source, dict) else {}
        result = {}
        for key, default in defaults.items():
            spec = schema.get(key, {"Type": "raw"})
            result[key] = self._normalize_field(raw.get(key, default), spec, default)
        if result.get("RGB") is True and result.get("CustomColorShift") is True:
            result["CustomColorShift"] = False
        return result

    def _normalize(self, data: Any) -> dict[str, Any]:
        source = data if isinstance(data, dict) else {}
        try:
            source_version = int(source.get("Version", 1))
        except (TypeError, ValueError):
            source_version = 1
        general_source = source.get("General") if isinstance(source.get("General"), dict) else {}
        fullscreen = general_source.get("Fullscreen", True)
        if not isinstance(fullscreen, bool):
            fullscreen = True
        protocols_source = source.get("Protocols") if isinstance(source.get("Protocols"), dict) else {}
        if not protocols_source and isinstance(source.get("Modes"), dict):
            protocols_source = source.get("Modes")
        if "Arcane" not in protocols_source and isinstance(protocols_source.get("Mystic"), dict):
            protocols_source = copy.deepcopy(protocols_source)
            protocols_source["Arcane"] = copy.deepcopy(protocols_source["Mystic"])
        if source_version < 2:
            arcane_source = protocols_source.get("Arcane") if isinstance(protocols_source.get("Arcane"), dict) else None
            if arcane_source is not None and arcane_source.get("IncompletePageGlitchChance") == 60:
                protocols_source = copy.deepcopy(protocols_source)
                protocols_source["Arcane"] = copy.deepcopy(arcane_source)
                protocols_source["Arcane"]["IncompletePageGlitchChance"] = 100
        protocols = {}
        for protocol in self.protocol_contracts:
            protocols[protocol] = self._normalize_protocol(protocol, protocols_source.get(protocol))
        for protocol, entry in protocols_source.items():
            if protocol == "Mystic" and "Arcane" in protocols:
                continue
            if protocol not in protocols and isinstance(protocol, str) and isinstance(entry, dict):
                protocols[protocol] = copy.deepcopy(entry)
        return {
            "Version": self.SETTINGS_VERSION,
            "General": {"Fullscreen": fullscreen},
            "Protocols": protocols,
        }

    def load(self) -> dict[str, Any]:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.settings_path.exists():
            self._data = self._default_document()
            self._atomic_write(self._data)
            return copy.deepcopy(self._data)
        try:
            with self.settings_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError):
            self._backup_corrupt_file()
            raw = {}
        normalized = self._normalize(raw)
        self._data = normalized
        if normalized != raw:
            self._atomic_write(normalized)
        return copy.deepcopy(self._data)

    def save(self) -> None:
        self._data = self._normalize(self._data)
        self._atomic_write(self._data)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def general(self) -> dict[str, Any]:
        return copy.deepcopy(self._data["General"])

    def protocol(self, protocol: str) -> dict[str, Any]:
        if protocol not in self.protocol_contracts:
            raise KeyError(protocol)
        return copy.deepcopy(self._data["Protocols"][protocol])

    def set_general(self, key: str, value: Any) -> Any:
        if key == "Fullscreen":
            if not isinstance(value, bool):
                raise TypeError("Fullscreen must be True or False.")
        else:
            raise KeyError(key)
        self._data["General"][key] = value
        self.save()
        return self._data["General"][key]

    def set_protocol(self, protocol: str, key: str, value: Any) -> Any:
        if protocol not in self.protocol_contracts:
            raise KeyError(protocol)
        contract = self.protocol_contracts[protocol]
        defaults = contract.get("Defaults", {})
        schema = contract.get("Schema", {})
        if key not in defaults:
            raise KeyError(key)
        normalized = self._normalize_field(value, schema.get(key, {"Type": "raw"}), defaults[key])
        self._data["Protocols"][protocol][key] = normalized
        if key == "RGB" and normalized is True and "CustomColorShift" in self._data["Protocols"][protocol]:
            self._data["Protocols"][protocol]["CustomColorShift"] = False
        if key == "CustomColorShift" and normalized is True and "RGB" in self._data["Protocols"][protocol]:
            self._data["Protocols"][protocol]["RGB"] = False
        self.save()
        return copy.deepcopy(self._data["Protocols"][protocol][key])

    def restore_protocol_defaults(self, protocol: str) -> None:
        if protocol not in self.protocol_contracts:
            raise KeyError(protocol)
        self._data["Protocols"][protocol] = copy.deepcopy(self.protocol_contracts[protocol].get("Defaults", {}))
        self.save()

    def restore_all_defaults(self) -> None:
        self._data = self._default_document()
        self.save()

    @staticmethod
    def _format_value(value: Any, spec: dict[str, Any]) -> str:
        kind = spec.get("Type")
        if kind == "percent":
            return f"{value}%"
        if kind == "seconds":
            number = float(value)
            return f"{number:g} Seconds"
        if kind == "seconds_range":
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                return f"{float(value[0]):g}-{float(value[1]):g} Seconds"
            return str(value)
        if kind == "boolean":
            return "True" if value else "False"
        if kind == "color_list":
            return ", ".join(value)
        return str(value)

    @staticmethod
    def _parse_boolean(text: str) -> bool:
        value = text.strip().casefold()
        if value in {"true", "yes", "y", "on", "1"}:
            return True
        if value in {"false", "no", "n", "off", "0"}:
            return False
        raise ValueError("Enter True or False.")

    def _parse_ui_value(self, text: str, spec: dict[str, Any]) -> Any:
        kind = spec.get("Type")
        stripped = text.strip()
        if kind == "boolean":
            return self._parse_boolean(stripped)
        if kind == "percent":
            return float(stripped.rstrip("% "))
        if kind == "seconds":
            lowered = stripped.casefold().replace("seconds", "").replace("second", "").replace("secs", "").replace("sec", "").strip()
            return float(lowered)
        if kind == "seconds_range":
            lowered = stripped.casefold().replace("seconds", "").replace("second", "").replace("secs", "").replace("sec", "").replace(" to ", "-").replace("–", "-").replace("—", "-").strip()
            if "," in lowered and "-" not in lowered:
                parts = [part.strip() for part in lowered.split(",", 1)]
            else:
                parts = [part.strip() for part in lowered.split("-", 1)]
            if len(parts) != 2 or not all(parts):
                raise ValueError("Enter a time range such as 1-3.")
            return [float(parts[0]), float(parts[1])]
        if kind == "integer":
            return int(stripped)
        if kind == "choice":
            for choice in spec.get("Choices", []):
                if str(choice).casefold() == stripped.casefold():
                    return choice
            raise ValueError("Choose one of: " + ", ".join(map(str, spec.get("Choices", []))))
        if kind == "color":
            for colour in PALETTE:
                if colour.casefold() == stripped.casefold():
                    return colour
            raise ValueError("Unknown colour.")
        if kind == "color_list":
            requested = [part.strip() for part in stripped.split(",") if part.strip()]
            resolved = []
            for item in requested:
                match = next((colour for colour in PALETTE if colour.casefold() == item.casefold()), None)
                if match is None:
                    raise ValueError(f"Unknown colour: {item}")
                if match not in resolved:
                    resolved.append(match)
            if len(resolved) < 2:
                raise ValueError("Choose at least two colours separated by commas.")
            return resolved
        return stripped

    @staticmethod
    def _enable_ansi() -> None:
        if os.name != "nt":
            return
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass

    def _clear(self) -> None:
        print("\033[2J\033[H", end="")

    @staticmethod
    def _fit(text: str, width: int) -> str:
        value = str(text)
        if len(value) <= width:
            return value
        if width <= 3:
            return value[:width]
        return value[: width - 3] + "..."

    @staticmethod
    def _center(text: str, width: int) -> str:
        value = str(text)
        if len(value) >= width:
            return value[:width]
        left = (width - len(value)) // 2
        return " " * left + value + " " * (width - len(value) - left)

    @staticmethod
    def _paint(text: str, colour: str, bold: bool = False) -> str:
        prefix = rgb_escape(PALETTE.get(colour, PALETTE["Matrix Green"]))
        if bold:
            prefix += BOLD
        return prefix + str(text) + RESET

    @staticmethod
    def _white(text: str, bold: bool = False) -> str:
        prefix = "\033[97m"
        if bold:
            prefix += BOLD
        return prefix + str(text) + RESET

    @staticmethod
    def _dim(text: str) -> str:
        return "\033[2m" + str(text) + RESET

    @staticmethod
    def _screen_width() -> int:
        columns = shutil.get_terminal_size((100, 35)).columns
        return max(64, min(96, columns - 4))

    def _frame_line(self, text: str, width: int, theme: str, emphasis: bool = False, dim: bool = False) -> str:
        inner = width - 2
        plain = self._fit(text, max(0, inner - 2))
        plain = " " + plain.ljust(max(0, inner - 2)) + " "
        if dim:
            body = self._dim(plain)
        elif emphasis:
            body = self._white(plain, True)
        else:
            body = self._white(plain)
        edge = self._paint("║", theme, True)
        return edge + body + edge

    def _header(self, section: str, theme: str) -> list[str]:
        width = self._screen_width()
        inner = width - 2
        top = self._paint("╔" + "═" * inner + "╗", theme, True)
        bottom = self._paint("╚" + "═" * inner + "╝", theme, True)
        return [
            top,
            self._frame_line(self._center("PROJECT HOMELAB", inner - 2), width, theme, True),
            self._frame_line(self._center("PRESENTS", inner - 2), width, theme, False, True),
            self._frame_line(self._center("T E R M I N A L S S", inner - 2), width, theme, True),
            self._frame_line(self._center(section, inner - 2), width, theme, True),
            bottom,
        ]

    def _panel(self, title: str, lines: list[str], theme: str) -> list[str]:
        width = self._screen_width()
        inner = width - 2
        label = f" {title} "
        remaining = max(0, inner - len(label) - 1)
        top = self._paint("╭─" + label + "─" * remaining + "╮", theme, True)
        bottom = self._paint("╰" + "─" * inner + "╯", theme, True)
        return [top, *[self._frame_line(line, width, theme) for line in lines], bottom]

    def _show(self, section: str, panels: list[tuple[str, list[str]]], theme: str, footer: str = "") -> None:
        self._clear()
        for line in self._header(section, theme):
            print(line)
        for title, lines in panels:
            print()
            for line in self._panel(title, lines, theme):
                print(line)
        if footer:
            print()
            width = self._screen_width()
            print(self._center(self._dim(footer), width))

    def _prompt(self, label: str, theme: str) -> str:
        return input(self._paint("> ", theme, True) + self._white(label)).strip()

    def _prompt_protocol_choice(self, label: str, theme: str, direct_return: bool) -> str:
        if not direct_return or not sys.stdin.isatty():
            return self._prompt(label, theme)
        prompt = self._paint("> ", theme, True) + self._white(label)
        sys.stdout.write(prompt)
        sys.stdout.flush()
        typed = ""
        if os.name == "nt":
            try:
                import msvcrt
                while True:
                    key = msvcrt.getwch()
                    if key in {"\r", "\n"}:
                        print()
                        return typed.strip()
                    if key == "0" and not typed:
                        print("0")
                        return "0"
                    if key == "\b":
                        if typed:
                            typed = typed[:-1]
                            sys.stdout.write("\b \b")
                            sys.stdout.flush()
                        continue
                    if key in {"\x00", "\xe0"}:
                        msvcrt.getwch()
                        continue
                    if key.isprintable():
                        typed += key
                        sys.stdout.write(key)
                        sys.stdout.flush()
            except Exception:
                print()
                return typed.strip()
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                while True:
                    key = sys.stdin.read(1)
                    if key in {"\r", "\n"}:
                        print()
                        return typed.strip()
                    if key == "0" and not typed:
                        print("0")
                        return "0"
                    if key in {"\x7f", "\x08"}:
                        if typed:
                            typed = typed[:-1]
                            sys.stdout.write("\b \b")
                            sys.stdout.flush()
                        continue
                    if key.isprintable():
                        typed += key
                        sys.stdout.write(key)
                        sys.stdout.flush()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            print()
            return typed.strip()

    def _protocol_theme(self, protocol: str) -> str:
        values = self._data.get("Protocols", {}).get(protocol, {})
        colour = values.get("Color", "Matrix Green") if isinstance(values, dict) else "Matrix Green"
        return colour if colour in PALETTE else "Matrix Green"

    def _protocol_menu(self, protocol: str, direct_return: bool = False) -> None:
        while True:
            self.load()
            contract = self.protocol_contracts[protocol]
            values = self._data["Protocols"][protocol]
            schema = contract.get("Schema", {})
            defaults = contract.get("Defaults", {})
            keys = list(defaults)
            theme = self._protocol_theme(protocol)
            lines = []
            for index, key in enumerate(keys, 1):
                spec = schema.get(key, {})
                label = spec.get("Label", key)
                value = self._format_value(values[key], spec)
                lines.append(f"[{index:02}] {label:<38} {value}")
            return_label = f"[0] Return to {protocol} Protocol" if direct_return else "[0] Back"
            lines.extend(["", "[R] Restore Protocol Default", return_label])
            self._show(f"{protocol.upper()} PROTOCOL SETTINGS", [("CURRENT SETTINGS", lines)], theme, "Changes save immediately  •  Enter Default to restore a single setting")
            choice = self._prompt_protocol_choice("Select setting: ", theme, direct_return)
            if choice.casefold() in {"0", "x", "back"}:
                return
            if choice.casefold() == "r":
                confirm = self._prompt(f"Restore {protocol} to defaults? (y/N): ", theme).casefold()
                if confirm == "y":
                    self.restore_protocol_defaults(protocol)
                continue
            try:
                selected = int(choice) - 1
                key = keys[selected]
            except (ValueError, IndexError):
                continue
            spec = schema.get(key, {})
            label = spec.get("Label", key)
            current = self._format_value(values[key], spec)
            if spec.get("Type") == "boolean":
                self.set_protocol(protocol, key, not bool(values[key]))
                continue
            prompt_lines = [f"Setting: {label}", f"Current: {current}"]
            if spec.get("Type") == "choice":
                prompt_lines.append("Options: " + ", ".join(map(str, spec.get("Choices", []))))
            if spec.get("Type") == "color":
                prompt_lines.append("Colours: " + ", ".join(PALETTE))
            if spec.get("Type") == "color_list":
                prompt_lines.append("Enter two or more palette colours separated by commas.")
            if spec.get("Type") == "seconds_range":
                prompt_lines.append("Enter minimum and maximum seconds as a range, for example 1-3.")
            prompt_lines.append("Enter Default to restore this setting.")
            self._show(f"{protocol.upper()} PROTOCOL SETTINGS", [("EDIT SETTING", prompt_lines)], theme)
            value_text = self._prompt("New value: ", theme)
            if value_text.casefold() == "default":
                self.set_protocol(protocol, key, copy.deepcopy(defaults[key]))
                continue
            try:
                value = self._parse_ui_value(value_text, spec)
                self.set_protocol(protocol, key, value)
            except (ValueError, TypeError) as exc:
                self._show(f"{protocol.upper()} PROTOCOL SETTINGS", [("SETTING ERROR", [str(exc), "", "Press Enter to continue..."])], theme)
                input()

    def _general_menu(self) -> None:
        theme = "Matrix Green"
        while True:
            self.load()
            general = self._data["General"]
            lines = [
                f"[1] Fullscreen                              {general['Fullscreen']}",
                "",
                "[0] Back",
            ]
            self._show("GENERAL SETTINGS", [("APPLICATION", lines)], theme, "Boolean settings toggle immediately")
            choice = self._prompt("Select setting: ", theme).casefold()
            if choice in {"0", "x", "back"}:
                return
            if choice == "1":
                self.set_general("Fullscreen", not general["Fullscreen"])

    def protocol_ui(self, protocol: str) -> None:
        self._enable_ansi()
        if protocol not in self.protocol_contracts:
            return
        self._protocol_menu(protocol, True)
        self._clear()

    def interactive_ui(self) -> None:
        self._enable_ansi()
        theme = "Matrix Green"
        while True:
            self.load()
            lines = ["[1] General Settings", "", "PROTOCOL SETTINGS"]
            for index, protocol in enumerate(self.protocol_names, 2):
                lines.append(f"[{index}] {protocol} Protocol")
            lines.extend(["", "[R] Restore All Defaults", "[0] Return to TerminalSS"])
            self._show("SETTINGS", [("CONFIGURATION", lines)], theme, "Settings are stored in Appdata/Settings/TerminalSSSettingsConfig.json")
            choice = self._prompt("Select: ", theme)
            if choice.casefold() in {"0", "x", "return"}:
                self._clear()
                return
            if choice.casefold() == "r":
                confirm = self._prompt("Restore every TerminalSS setting to default? (y/N): ", theme).casefold()
                if confirm == "y":
                    self.restore_all_defaults()
                continue
            if choice == "1":
                self._general_menu()
                continue
            try:
                protocol_index = int(choice) - 2
                protocol = self.protocol_names[protocol_index]
            except (ValueError, IndexError):
                continue
            self._protocol_menu(protocol)
