from __future__ import annotations

import random
import time
from typing import Any

from TerminalSSGameAI import PongAI
from TerminalSSUI import TerminalCanvas, TerminalSSUI


class TerminalSSPongProtocol:
    PROTOCOL_ID = "Pong"
    KEY = "8"
    ALLOW_MISSING_ASSETS = True
    DEFAULT_SETTINGS = {
        "GameSpeed": 50,
        "DemoReturnTime": 20.0,
        "PlayerMode": "1 Player",
        "WinningScore": "7",
        "PaddleSize": "Classic",
        "AISkill": 72,
        "Color": "White",
        "RGB": False,
        "RGBSpeed": 50,
        "CustomColorShift": False,
        "CustomColorShiftSpeed": 50,
        "CustomColorShiftColors": ["White", "Silver", "Cyan"],
    }
    SETTING_SCHEMA = {
        "GameSpeed": {"Label": "Game Speed", "Type": "percent"},
        "DemoReturnTime": {"Label": "Return To Demo After", "Type": "seconds", "Min": 5, "Max": 300},
        "PlayerMode": {"Label": "Player Mode", "Type": "choice", "Choices": ["1 Player", "2 Players"]},
        "WinningScore": {"Label": "Winning Score", "Type": "choice", "Choices": ["5", "7", "11"]},
        "PaddleSize": {"Label": "Paddle Size", "Type": "choice", "Choices": ["Small", "Classic", "Large"]},
        "AISkill": {"Label": "AI Skill", "Type": "percent"},
        "Color": {"Label": "Color", "Type": "color"},
        "RGB": {"Label": "RGB", "Type": "boolean"},
        "RGBSpeed": {"Label": "RGB Speed", "Type": "percent"},
        "CustomColorShift": {"Label": "Custom Color Shift", "Type": "boolean"},
        "CustomColorShiftSpeed": {"Label": "Custom Color Shift Speed", "Type": "percent"},
        "CustomColorShiftColors": {"Label": "Custom Color Shift Colors", "Type": "color_list"},
    }
    DIGITS = {
        "0": ("███", "█ █", "█ █", "█ █", "███"),
        "1": (" ██", "  █", "  █", "  █", "███"),
        "2": ("███", "  █", "███", "█  ", "███"),
        "3": ("███", "  █", "███", "  █", "███"),
        "4": ("█ █", "█ █", "███", "  █", "  █"),
        "5": ("███", "█  ", "███", "  █", "███"),
        "6": ("███", "█  ", "███", "█ █", "███"),
        "7": ("███", "  █", "  █", "  █", "  █"),
        "8": ("███", "█ █", "███", "█ █", "███"),
        "9": ("███", "█ █", "███", "  █", "███"),
    }

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
        self.field_width = 0
        self.field_height = 0
        self.left_y = 0.0
        self.right_y = 0.0
        self.left_move = 0
        self.right_move = 0
        self.left_move_until = 0.0
        self.right_move_until = 0.0
        self.ball_x = 0.0
        self.ball_y = 0.0
        self.ball_dx = 1.0
        self.ball_dy = 0.3
        self.left_score = 0
        self.right_score = 0
        self.demo_mode = True
        self.last_input = 0.0
        self.last_update = 0.0
        self.serve_until = 0.0
        self.match_until = 0.0
        self.winner = ""
        self.ai_left_move = 0
        self.ai_right_move = 0
        self.next_ai_update = 0.0

    def help_lines(self) -> list[str]:
        return [
            "PONG CONTROLS",
            "1 PLAYER       W/S or UP/DOWN",
            "2 PLAYERS      W/S left • UP/DOWN right",
            "R              Restart match",
            "Input takes control; inactivity returns to AI vs AI",
        ]

    def _layout(self, width: int, height: int) -> tuple[int, int, int, int]:
        field_width = max(24, min(78, width - 6))
        field_height = max(12, min(28, height - 5))
        x = max(1, (width - field_width - 2) // 2)
        y = max(1, (height - field_height - 2) // 2)
        return x, y, field_width, field_height

    @staticmethod
    def _paddle_height(settings: dict, field_height: int) -> int:
        name = str(settings.get("PaddleSize", "Classic")).casefold()
        fraction = 0.15 if name == "small" else 0.26 if name == "large" else 0.20
        return max(3, min(9, int(round(field_height * fraction))))

    @staticmethod
    def _ball_speed(settings: dict) -> float:
        speed = max(0, min(100, int(settings.get("GameSpeed", 50))))
        return 18.0 + speed * 0.17

    @staticmethod
    def _paddle_speed(settings: dict) -> float:
        speed = max(0, min(100, int(settings.get("GameSpeed", 50))))
        return 15.0 + speed * 0.10

    def _reset_positions(self, settings: dict, now: float, serve_direction: int | None = None) -> None:
        paddle_height = self._paddle_height(settings, self.field_height)
        center = (self.field_height - paddle_height) / 2.0
        self.left_y = center
        self.right_y = center
        self.left_move = 0
        self.right_move = 0
        self.left_move_until = 0.0
        self.right_move_until = 0.0
        self.ball_x = self.field_width / 2.0
        self.ball_y = self.field_height / 2.0
        direction = serve_direction if serve_direction in {-1, 1} else random.choice((-1, 1))
        angle = random.uniform(-0.55, 0.55)
        self.ball_dx = float(direction)
        self.ball_dy = angle
        magnitude = max(1.0, (self.ball_dx * self.ball_dx + self.ball_dy * self.ball_dy) ** 0.5)
        self.ball_dx /= magnitude
        self.ball_dy /= magnitude
        self.serve_until = now + 0.85

    def _reset_match(self, settings: dict, now: float, keep_mode: bool = True) -> None:
        self.left_score = 0
        self.right_score = 0
        self.winner = ""
        self.match_until = 0.0
        if not keep_mode:
            self.demo_mode = True
        self._reset_positions(settings, now)

    def reset(self, settings: dict, width: int, height: int, now: float | None = None) -> None:
        base = time.monotonic() if now is None else now
        _, _, self.field_width, self.field_height = self._layout(width, height)
        self.demo_mode = True
        self.last_input = base
        self.last_update = base
        self.next_ai_update = base
        self._reset_match(settings, base, True)

    def _set_player_mode(self) -> None:
        self.demo_mode = False
        self.last_input = time.monotonic()

    def handle_runtime_key(self, key: str, settings: dict) -> bool:
        normalized = str(key or "")
        letter = normalized.casefold()
        two_player = str(settings.get("PlayerMode", "1 Player")).casefold() == "2 players"
        if letter == "r":
            self._set_player_mode()
            self._reset_match(settings, time.monotonic(), True)
            return True
        if letter == "w":
            self._set_player_mode()
            self.left_move = -1
            self.left_move_until = time.monotonic() + 0.16
            return True
        if letter == "s":
            self._set_player_mode()
            self.left_move = 1
            self.left_move_until = time.monotonic() + 0.16
            return True
        if normalized == "UP":
            self._set_player_mode()
            if two_player:
                self.right_move = -1
                self.right_move_until = time.monotonic() + 0.16
            else:
                self.left_move = -1
                self.left_move_until = time.monotonic() + 0.16
            return True
        if normalized == "DOWN":
            self._set_player_mode()
            if two_player:
                self.right_move = 1
                self.right_move_until = time.monotonic() + 0.16
            else:
                self.left_move = 1
                self.left_move_until = time.monotonic() + 0.16
            return True
        return False

    def _release_moves(self) -> None:
        self.left_move = 0
        self.right_move = 0
        self.left_move_until = 0.0
        self.right_move_until = 0.0

    def _ai_moves(self, settings: dict, now: float) -> tuple[int, int]:
        if now < self.next_ai_update:
            return self.ai_left_move, self.ai_right_move
        skill = max(0, min(100, int(settings.get("AISkill", 72))))
        reaction = 0.15 - skill * 0.00105
        reaction = max(0.035, reaction)
        self.next_ai_update = now + reaction
        paddle_height = self._paddle_height(settings, self.field_height)
        error_span = max(0.0, (100 - skill) / 100.0 * paddle_height * 1.3)
        left_bias = random.uniform(-error_span, error_span)
        right_bias = random.uniform(-error_span, error_span)
        self.ai_left_move = PongAI.choose_move(self.left_y + paddle_height / 2.0, self.ball_y, self.ball_dy, 0.65, left_bias)
        self.ai_right_move = PongAI.choose_move(self.right_y + paddle_height / 2.0, self.ball_y, self.ball_dy, 0.65, right_bias)
        return self.ai_left_move, self.ai_right_move

    def _score_point(self, settings: dict, now: float, left_scored: bool) -> None:
        if left_scored:
            self.left_score += 1
            serve_direction = 1
        else:
            self.right_score += 1
            serve_direction = -1
        try:
            winning = int(str(settings.get("WinningScore", "7")))
        except Exception:
            winning = 7
        if self.left_score >= winning or self.right_score >= winning:
            self.winner = "LEFT PLAYER" if self.left_score > self.right_score else "RIGHT PLAYER"
            self.match_until = now + (1.0 if self.demo_mode else 2.0)
            self.serve_until = self.match_until
            return
        self._reset_positions(settings, now, serve_direction)

    def _update_ball(self, settings: dict, now: float, dt: float) -> None:
        if now < self.serve_until or self.match_until:
            return
        speed = self._ball_speed(settings)
        self.ball_x += self.ball_dx * speed * dt
        self.ball_y += self.ball_dy * speed * dt
        if self.ball_y <= 0:
            self.ball_y = 0
            self.ball_dy = abs(self.ball_dy)
        elif self.ball_y >= self.field_height - 1:
            self.ball_y = self.field_height - 1
            self.ball_dy = -abs(self.ball_dy)
        paddle_height = self._paddle_height(settings, self.field_height)
        left_x = 2.0
        right_x = float(self.field_width - 3)
        if self.ball_dx < 0 and self.ball_x <= left_x + 0.6:
            if self.left_y - 0.4 <= self.ball_y <= self.left_y + paddle_height - 0.6:
                self.ball_x = left_x + 0.65
                offset = (self.ball_y - (self.left_y + paddle_height / 2.0)) / max(1.0, paddle_height / 2.0)
                self.ball_dx = abs(self.ball_dx) * 1.03
                self.ball_dy += offset * 0.52
        if self.ball_dx > 0 and self.ball_x >= right_x - 0.6:
            if self.right_y - 0.4 <= self.ball_y <= self.right_y + paddle_height - 0.6:
                self.ball_x = right_x - 0.65
                offset = (self.ball_y - (self.right_y + paddle_height / 2.0)) / max(1.0, paddle_height / 2.0)
                self.ball_dx = -abs(self.ball_dx) * 1.03
                self.ball_dy += offset * 0.52
        magnitude = max(0.001, (self.ball_dx * self.ball_dx + self.ball_dy * self.ball_dy) ** 0.5)
        self.ball_dx /= magnitude
        self.ball_dy /= magnitude
        if self.ball_x < -1:
            self._score_point(settings, now, False)
        elif self.ball_x > self.field_width:
            self._score_point(settings, now, True)

    def _update(self, settings: dict, now: float) -> None:
        timeout = max(5.0, float(settings.get("DemoReturnTime", 20.0)))
        if not self.demo_mode and now - self.last_input >= timeout:
            self.demo_mode = True
            self._release_moves()
        if self.match_until and now >= self.match_until:
            self._reset_match(settings, now, True)
        dt = max(0.0, min(0.08, now - self.last_update))
        self.last_update = now
        paddle_height = self._paddle_height(settings, self.field_height)
        left_move = self.left_move if now <= self.left_move_until else 0
        right_move = self.right_move if now <= self.right_move_until else 0
        if self.demo_mode:
            left_move, right_move = self._ai_moves(settings, now)
        elif str(settings.get("PlayerMode", "1 Player")).casefold() != "2 players":
            _, right_move = self._ai_moves(settings, now)
        paddle_speed = self._paddle_speed(settings)
        self.left_y += left_move * paddle_speed * dt
        self.right_y += right_move * paddle_speed * dt
        maximum = max(0.0, self.field_height - paddle_height)
        self.left_y = max(0.0, min(maximum, self.left_y))
        self.right_y = max(0.0, min(maximum, self.right_y))
        self._update_ball(settings, now, dt)
        if not self.demo_mode:
            if now > self.left_move_until:
                self.left_move = 0
            if now > self.right_move_until:
                self.right_move = 0

    def _score_lines(self, value: int) -> list[str]:
        text = str(max(0, int(value)))
        rows = ["" for _ in range(5)]
        for index, digit in enumerate(text):
            pattern = self.DIGITS[digit]
            for row in range(5):
                if index:
                    rows[row] += " "
                rows[row] += pattern[row]
        return rows

    def _draw_score_number(self, canvas: TerminalCanvas, anchor_x: int, y: int, value: int, align: str, style: int = 3) -> None:
        lines = self._score_lines(value)
        width = max((len(line) for line in lines), default=0)
        x = anchor_x - width if align == "right" else anchor_x
        for row, line in enumerate(lines):
            canvas.text(x, y + row, line, style)

    def _draw_field(self, canvas: TerminalCanvas, x: int, y: int, settings: dict) -> None:
        title = "PONG // DEMO" if self.demo_mode else "PONG // PLAYER"
        canvas.panel(x, y, self.field_width + 2, self.field_height + 2, title, 2)
        inner_x = x + 1
        inner_y = y + 1
        center_x = inner_x + self.field_width // 2
        for row in range(1, self.field_height, 2):
            canvas.put(center_x, inner_y + row, "│", 1)
        score_y = inner_y + 1
        self._draw_score_number(canvas, center_x - 4, score_y, self.left_score, "right", 3)
        self._draw_score_number(canvas, center_x + 5, score_y, self.right_score, "left", 3)
        paddle_height = self._paddle_height(settings, self.field_height)
        for offset in range(paddle_height):
            canvas.put(inner_x + 2, inner_y + int(round(self.left_y)) + offset, "█", 4)
            canvas.put(inner_x + self.field_width - 3, inner_y + int(round(self.right_y)) + offset, "█", 4)
        canvas.put(inner_x + int(round(self.ball_x)), inner_y + int(round(self.ball_y)), "●", 4)

    def render(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        x, y, field_width, field_height = self._layout(width, height)
        if field_width != self.field_width or field_height != self.field_height:
            self.field_width = field_width
            self.field_height = field_height
            self._reset_positions(settings, now)
        self._update(settings, now)
        canvas = self.ui.canvas(width, height)
        self._draw_field(canvas, x, y, settings)
        hint_y = min(height - 1, y + self.field_height + 2)
        if hint_y < height:
            if self.demo_mode:
                hint = "AI VS AI • PRESS W/S OR UP/DOWN TO PLAY"
            elif str(settings.get("PlayerMode", "1 Player")).casefold() == "2 players":
                hint = "P1 W/S • P2 UP/DOWN • R RESTART"
            else:
                hint = "PLAYER W/S OR UP/DOWN • AI OPPONENT • R RESTART"
            canvas.centered_text(hint_y, hint, 1)
        if self.match_until:
            canvas.overlay_center_box("MATCH", [f"{self.winner} WINS", f"{self.left_score}  -  {self.right_score}"])
        elif now < self.serve_until:
            canvas.centered_text(y + self.field_height // 2, "READY", 3)
        return canvas

    def reverse_direction(self, settings: dict) -> None:
        return None

    def primary_speed_label(self, settings: dict) -> str:
        mode = "AI vs AI" if self.demo_mode else str(settings.get("PlayerMode", "1 Player"))
        return f"Pong {mode} • Speed {int(settings.get('GameSpeed', 50))}%"


PROTOCOL_CLASS = TerminalSSPongProtocol
