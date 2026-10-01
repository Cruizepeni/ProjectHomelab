from __future__ import annotations

import random
import time
from typing import Any

from TerminalSSGameAI import SnakeAI
from TerminalSSUI import TerminalCanvas, TerminalSSUI


class TerminalSSSnakeProtocol:
    PROTOCOL_ID = "Snake"
    KEY = "7"
    ALLOW_MISSING_ASSETS = True
    DEFAULT_SETTINGS = {
        "GameSpeed": 50,
        "DemoReturnTime": 20.0,
        "WrapWalls": False,
        "Color": "Lime",
        "RGB": False,
        "RGBSpeed": 50,
        "CustomColorShift": False,
        "CustomColorShiftSpeed": 50,
        "CustomColorShiftColors": ["Lime", "Matrix Green", "Mint"],
    }
    SETTING_SCHEMA = {
        "GameSpeed": {"Label": "Game Speed", "Type": "percent"},
        "DemoReturnTime": {"Label": "Return To Demo After", "Type": "seconds", "Min": 5, "Max": 300},
        "WrapWalls": {"Label": "Wrap Through Walls", "Type": "boolean"},
        "Color": {"Label": "Color", "Type": "color"},
        "RGB": {"Label": "RGB", "Type": "boolean"},
        "RGBSpeed": {"Label": "RGB Speed", "Type": "percent"},
        "CustomColorShift": {"Label": "Custom Color Shift", "Type": "boolean"},
        "CustomColorShiftSpeed": {"Label": "Custom Color Shift Speed", "Type": "percent"},
        "CustomColorShiftColors": {"Label": "Custom Color Shift Colors", "Type": "color_list"},
    }
    DIRECTIONS = {
        "UP": (0, -1),
        "DOWN": (0, 1),
        "LEFT": (-1, 0),
        "RIGHT": (1, 0),
    }
    OPPOSITE = {
        "UP": "DOWN",
        "DOWN": "UP",
        "LEFT": "RIGHT",
        "RIGHT": "LEFT",
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
        self.board_width = 0
        self.board_height = 0
        self.snake: list[tuple[int, int]] = []
        self.direction = "RIGHT"
        self.pending_direction = "RIGHT"
        self.food = (0, 0)
        self.score = 0
        self.high_score = 0
        self.demo_mode = True
        self.last_input = 0.0
        self.last_step = 0.0
        self.dead_until = 0.0
        self.death_message = ""

    def help_lines(self) -> list[str]:
        return [
            "SNAKE CONTROLS",
            "ARROWS / WASD  Steer",
            "R              Restart",
            "SPACE          Pause / Resume",
            "Input takes control; inactivity returns to demo AI",
        ]

    def _layout(self, width: int, height: int) -> tuple[int, int, int, int]:
        board_width = max(12, min(72, width - 6))
        board_height = max(8, min(28, height - 7))
        x = max(1, (width - board_width - 2) // 2)
        y = max(1, (height - board_height - 4) // 2)
        return x, y, board_width, board_height

    def _new_food(self) -> tuple[int, int]:
        occupied = set(self.snake)
        available = [
            (x, y)
            for y in range(self.board_height)
            for x in range(self.board_width)
            if (x, y) not in occupied
        ]
        return random.choice(available) if available else (0, 0)

    def _reset_round(self, now: float, keep_mode: bool = True) -> None:
        length = max(4, min(8, self.board_width // 8))
        center_x = self.board_width // 2
        center_y = self.board_height // 2
        self.snake = [(center_x - index, center_y) for index in range(length)]
        self.direction = "RIGHT"
        self.pending_direction = "RIGHT"
        self.food = self._new_food()
        self.score = 0
        self.last_step = now
        self.dead_until = 0.0
        self.death_message = ""
        if not keep_mode:
            self.demo_mode = True

    def reset(self, settings: dict, width: int, height: int, now: float | None = None) -> None:
        base = time.monotonic() if now is None else now
        _, _, board_width, board_height = self._layout(width, height)
        self.board_width = board_width
        self.board_height = board_height
        self.demo_mode = True
        self.last_input = base
        self._reset_round(base, True)

    @staticmethod
    def _step_interval(settings: dict) -> float:
        speed = max(0, min(100, int(settings.get("GameSpeed", 50))))
        return 0.24 - speed * 0.0018

    def _set_player_mode(self) -> None:
        self.demo_mode = False
        self.last_input = time.monotonic()

    def _request_direction(self, direction: str) -> None:
        if direction not in self.DIRECTIONS:
            return
        if direction == self.OPPOSITE.get(self.direction) and len(self.snake) > 1:
            return
        self.pending_direction = direction

    def handle_runtime_key(self, key: str, settings: dict) -> bool:
        normalized = str(key or "")
        letter = normalized.casefold()
        mapping = {
            "UP": "UP",
            "DOWN": "DOWN",
            "LEFT": "LEFT",
            "RIGHT": "RIGHT",
            "w": "UP",
            "s": "DOWN",
            "a": "LEFT",
            "d": "RIGHT",
        }
        direction = mapping.get(normalized) or mapping.get(letter)
        if direction:
            self._set_player_mode()
            self._request_direction(direction)
            return True
        if letter == "r":
            self._set_player_mode()
            self._reset_round(time.monotonic(), True)
            return True
        return False

    def _die(self, now: float, message: str) -> None:
        self.high_score = max(self.high_score, self.score)
        self.death_message = message
        self.dead_until = now + (0.8 if self.demo_mode else 1.35)

    def _advance(self, settings: dict, now: float) -> None:
        if self.dead_until:
            if now >= self.dead_until:
                self._reset_round(now, True)
            return
        if self.demo_mode:
            self.pending_direction = SnakeAI.choose_direction(
                self.snake,
                self.food,
                self.board_width,
                self.board_height,
                self.direction,
                bool(settings.get("WrapWalls", False)),
            )
        self.direction = self.pending_direction
        dx, dy = self.DIRECTIONS[self.direction]
        head_x, head_y = self.snake[0]
        next_x = head_x + dx
        next_y = head_y + dy
        wrap = bool(settings.get("WrapWalls", False))
        if wrap:
            next_x %= self.board_width
            next_y %= self.board_height
        elif not (0 <= next_x < self.board_width and 0 <= next_y < self.board_height):
            self._die(now, "WALL COLLISION")
            return
        new_head = (next_x, next_y)
        growing = new_head == self.food
        body_to_check = self.snake if growing else self.snake[:-1]
        if new_head in body_to_check:
            self._die(now, "SELF COLLISION")
            return
        self.snake.insert(0, new_head)
        if growing:
            self.score += 10
            self.high_score = max(self.high_score, self.score)
            self.food = self._new_food()
            if len(self.snake) >= self.board_width * self.board_height:
                self._die(now, "GRID COMPLETE")
        else:
            self.snake.pop()

    def _update(self, settings: dict, now: float) -> None:
        timeout = max(5.0, float(settings.get("DemoReturnTime", 20.0)))
        if not self.demo_mode and now - self.last_input >= timeout:
            self.demo_mode = True
        interval = max(0.035, self._step_interval(settings))
        loops = 0
        while now - self.last_step >= interval and loops < 5:
            self.last_step += interval
            self._advance(settings, self.last_step)
            loops += 1

    def _draw_playfield(self, canvas: TerminalCanvas, x: int, y: int, board_width: int, board_height: int) -> None:
        title = "SNAKE // DEMO" if self.demo_mode else "SNAKE // PLAYER"
        canvas.panel(x, y, board_width + 2, board_height + 2, title, 2)
        for sx, sy in reversed(self.snake[1:]):
            canvas.put(x + 1 + sx, y + 1 + sy, "■", 2)
        if self.snake:
            hx, hy = self.snake[0]
            canvas.put(x + 1 + hx, y + 1 + hy, "◆", 4)
        fx, fy = self.food
        canvas.put(x + 1 + fx, y + 1 + fy, "●", 3)

    def render(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        x, y, board_width, board_height = self._layout(width, height)
        if board_width != self.board_width or board_height != self.board_height:
            self.board_width = board_width
            self.board_height = board_height
            self._reset_round(now, True)
        self._update(settings, now)
        canvas = self.ui.canvas(width, height)
        self._draw_playfield(canvas, x, y, board_width, board_height)
        status_y = min(height - 2, y + board_height + 2)
        status = f"SCORE {self.score:05d}   HIGH {self.high_score:05d}   LENGTH {len(self.snake):03d}"
        canvas.centered_text(status_y, status, 3)
        if status_y + 1 < height:
            hint = "DEMO AI • PRESS ARROWS/WASD TO PLAY" if self.demo_mode else "PLAYER CONTROL • R RESTART • IDLE RETURNS TO DEMO"
            canvas.centered_text(status_y + 1, hint, 1)
        if self.dead_until:
            canvas.overlay_center_box("GAME OVER" if self.death_message != "GRID COMPLETE" else "PERFECT", [self.death_message, f"SCORE {self.score}"])
        return canvas

    def reverse_direction(self, settings: dict) -> None:
        return None

    def primary_speed_label(self, settings: dict) -> str:
        mode = "Demo AI" if self.demo_mode else "Player"
        return f"Snake {mode} • Speed {int(settings.get('GameSpeed', 50))}%"


PROTOCOL_CLASS = TerminalSSSnakeProtocol
