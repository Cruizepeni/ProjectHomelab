from __future__ import annotations

import os
import shutil
import sys
from typing import Any, Iterable


class EmuKitTerminalUI:

    MIN_WIDTH = 64
    MAX_WIDTH = 96

    def __init__(self) -> None:
        self._colour = self._supports_colour()
        self._enable_windows_vt()

    @staticmethod
    def _enable_windows_vt() -> None:
        if os.name != "nt":
            return
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass

    @staticmethod
    def _supports_colour() -> bool:
        if os.environ.get("NO_COLOR") is not None:
            return False
        if not getattr(sys.stdout, "isatty", lambda: False)():
            return False
        if os.name == "nt":
            return True
        return os.environ.get("TERM", "") != "dumb"

    @property
    def width(self) -> int:
        terminal = shutil.get_terminal_size(fallback=(80, 24)).columns
        return max(self.MIN_WIDTH, min(self.MAX_WIDTH, terminal - 2))

    def _style(self, text: str, code: str) -> str:
        if not self._colour:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text: str) -> str:
        return self._style(text, "1")

    def dim(self, text: str) -> str:
        return self._style(text, "2")

    def green(self, text: str) -> str:
        return self._style(text, "32")

    def yellow(self, text: str) -> str:
        return self._style(text, "33")

    def red(self, text: str) -> str:
        return self._style(text, "31")

    def cyan(self, text: str) -> str:
        return self._style(text, "36")

    @staticmethod
    def set_title(title: str) -> None:
        if os.name == "nt":
            try:
                import ctypes

                ctypes.windll.kernel32.SetConsoleTitleW(title)
                return
            except Exception:
                pass
        if getattr(sys.stdout, "isatty", lambda: False)():
            print(f"\033]0;{title}\007", end="", flush=True)

    @staticmethod
    def _plain_len(value: str) -> int:
        import re

        return len(re.sub(r"\x1b\[[0-9;]*m", "", value))

    def _fit(self, value: Any, width: int) -> str:
        text = str(value if value is not None else "").replace("\t", "    ")
        if width <= 0:
            return ""
        if len(text) <= width:
            return text
        if width <= 3:
            return text[:width]
        return text[: width - 3] + "..."

    def _center(self, text: str, inner_width: int) -> str:
        length = self._plain_len(text)
        left = max(0, (inner_width - length) // 2)
        right = max(0, inner_width - length - left)
        return " " * left + text + " " * right

    def banner(self, product: str = "EMUKIT") -> None:
        width = self.width
        inner = width - 2
        lines = [
            "",
            self.bold("PROJECT HOMELAB"),
            "PRESENTS",
            self.bold(product.upper()),
            "",
        ]
        print("╔" + "═" * inner + "╗")
        for line in lines:
            print("║" + self._center(line, inner) + "║")
        print("╚" + "═" * inner + "╝")

    def runtime_panel(self, rows: Iterable[tuple[str, Any]]) -> None:
        width = self.width
        inner = width - 2
        rows = list(rows)
        label_width = max([len(str(label)) for label, _ in rows] + [6])
        print("╔" + "═" * inner + "╗")
        for label, value in rows:
            prefix = f" {str(label):<{label_width}}  "
            value_width = max(1, inner - len(prefix) - 1)
            text = prefix + self._fit(value, value_width)
            print("║" + text.ljust(inner) + "║")
        print("╚" + "═" * inner + "╝")

    def panel(self, title: str, lines: Iterable[Any] = (), *, border: str = "single") -> None:
        width = self.width
        inner = width - 2
        top_l, top_r, bottom_l, bottom_r, h, v = (
            ("╭", "╮", "╰", "╯", "─", "│") if border == "single" else
            ("╔", "╗", "╚", "╝", "═", "║")
        )
        title_text = f" {title} " if title else ""
        title_plain = self._plain_len(title_text)
        if title_text and title_plain < inner:
            top = top_l + title_text + h * (inner - title_plain) + top_r
        else:
            top = top_l + h * inner + top_r
        print(top)
        emitted = False
        for value in lines:
            emitted = True
            text = str(value)
            if not text:
                print(v + " " * inner + v)
                continue
            for logical in text.splitlines() or [""]:
                print(v + " " + self._fit(logical, inner - 2).ljust(inner - 2) + " " + v)
        if not emitted:
            print(v + " " * inner + v)
        print(bottom_l + h * inner + bottom_r)

    def key_value_panel(self, title: str, rows: Iterable[tuple[str, Any]]) -> None:
        rows = list(rows)
        label_width = max([len(str(label)) for label, _ in rows] + [1])
        lines = [f"{label:<{label_width}}  {value}" for label, value in rows]
        self.panel(title, lines)

    def table(
        self,
        title: str,
        headers: list[str],
        rows: Iterable[Iterable[Any]],
        *,
        summary: str | None = None,
    ) -> None:
        rows = [[str(cell if cell is not None else "") for cell in row] for row in rows]
        width = self.width
        inner = width - 2
        available = inner - (3 * (len(headers) - 1)) - 2
        natural = []
        minimums = []
        for index, header in enumerate(headers):
            content_width = max([len(header)] + [len(row[index]) if index < len(row) else 0 for row in rows])
            natural.append(content_width)
            minimums.append(max(7, len(header)))
        widths = [max(minimums[i], natural[i]) for i in range(len(headers))]
        while sum(widths) > available:
            candidates = [i for i in range(len(widths)) if widths[i] > minimums[i]]
            if not candidates:
                break
            idx = max(candidates, key=lambda i: widths[i] - minimums[i])
            widths[idx] -= 1
        while sum(widths) < available:
            idx = max(range(len(widths)), key=lambda i: natural[i] - widths[i])
            widths[idx] += 1

        title_text = f" {title} "
        print("╭" + title_text + "─" * max(0, inner - len(title_text)) + "╮")
        header_line = " │ ".join(self._fit(h, widths[i]).ljust(widths[i]) for i, h in enumerate(headers))
        header_padding = max(0, inner - 2 - len(header_line))
        print("│ " + self.bold(header_line) + " " * header_padding + " │")
        print("├" + "─" * inner + "┤")
        if not rows:
            print("│ " + "None".ljust(inner - 2) + " │")
        else:
            for row in rows:
                line = " │ ".join(
                    self._fit(row[i] if i < len(row) else "", widths[i]).ljust(widths[i])
                    for i in range(len(headers))
                )
                print("│ " + line.ljust(inner - 2) + " │")
        print("╰" + "─" * inner + "╯")
        if summary:
            print(self.dim(summary))

    def success(self, message: str) -> None:
        print(f"{self.green('[✓]')} {message}")

    def info(self, message: str) -> None:
        print(f"{self.cyan('[•]')} {message}")

    def warning(self, message: str) -> None:
        print(f"{self.yellow('[!]')} {message}")

    def error(self, message: str) -> None:
        print(f"{self.red('[✗]')} {message}")

    def usage(self, message: str) -> None:
        print(f"{self.yellow('Usage:')} {message}")

    def prompt(self) -> str:
        return f"{self.cyan('EmuKit')} {self.bold('>')} "

    def yes_no_prompt(self, message: str, *, default_yes: bool = True) -> str:
        suffix = "[Y/n]" if default_yes else "[y/N]"
        return f"{message} {self.dim(suffix)} {self.bold('>')} "

    def progress_line(
        self,
        module: str,
        stage: str,
        percent: int | None,
        message: str = "",
    ) -> str:
        width = self.width
        if isinstance(percent, int):
            percent = max(0, min(100, percent))
            percent_text = f"{percent:3d}%"
            fixed = len(module) + len(stage) + len(percent_text) + 11
            bar_width = max(10, min(30, width - fixed))
            filled = round(bar_width * percent / 100)
            bar = "█" * filled + "░" * (bar_width - filled)
            base = f"{module:<18} {bar} {percent_text}  {stage}"
        else:
            base = f"{module:<18} {stage}"
        if message and percent != 100:
            remaining = width - len(base) - 3
            if remaining > 8:
                base += "  " + self._fit(message, remaining)
        return self._fit(base, width - 1).ljust(width - 1)
