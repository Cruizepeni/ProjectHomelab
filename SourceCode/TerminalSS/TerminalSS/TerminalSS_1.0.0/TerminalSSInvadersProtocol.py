from __future__ import annotations

import random
import time
from typing import Any

from TerminalSSGameAI import InvadersAI
from TerminalSSUI import TerminalCanvas, TerminalSSUI


class TerminalSSInvadersProtocol:
    PROTOCOL_ID = "Invaders"
    KEY = "9"
    ALLOW_MISSING_ASSETS = True
    DEFAULT_SETTINGS = {
        "GameSpeed": 50,
        "DemoReturnTime": 20.0,
        "EnemyFireRate": 45,
        "AISkill": 76,
        "Color": "Mint",
        "RGB": False,
        "RGBSpeed": 50,
        "CustomColorShift": False,
        "CustomColorShiftSpeed": 50,
        "CustomColorShiftColors": ["Mint", "Lime", "Cyan"],
    }
    SETTING_SCHEMA = {
        "GameSpeed": {"Label": "Game Speed", "Type": "percent"},
        "DemoReturnTime": {"Label": "Return To Demo After", "Type": "seconds", "Min": 5, "Max": 300},
        "EnemyFireRate": {"Label": "Enemy Fire Rate", "Type": "percent"},
        "AISkill": {"Label": "Demo AI Skill", "Type": "percent"},
        "Color": {"Label": "Color", "Type": "color"},
        "RGB": {"Label": "RGB", "Type": "boolean"},
        "RGBSpeed": {"Label": "RGB Speed", "Type": "percent"},
        "CustomColorShift": {"Label": "Custom Color Shift", "Type": "boolean"},
        "CustomColorShiftSpeed": {"Label": "Custom Color Shift Speed", "Type": "percent"},
        "CustomColorShiftColors": {"Label": "Custom Color Shift Colors", "Type": "color_list"},
    }
    ENEMY_SPRITES = ("<o>", "{M}", "/W\\")

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
        self.player_x = 0.0
        self.player_move = 0
        self.player_move_until = 0.0
        self.player_bullets: list[dict[str, float]] = []
        self.enemy_bullets: list[dict[str, float]] = []
        self.enemies: list[dict[str, Any]] = []
        self.barriers: set[tuple[int, int]] = set()
        self.formation_x = 0
        self.formation_y = 3
        self.formation_direction = 1
        self.last_formation_step = 0.0
        self.last_update = 0.0
        self.last_enemy_fire = 0.0
        self.next_player_fire = 0.0
        self.score = 0
        self.high_score = 0
        self.lives = 3
        self.wave = 1
        self.demo_mode = True
        self.last_input = 0.0
        self.state_until = 0.0
        self.state = "playing"
        self.explosions: list[dict[str, float]] = []
        self.next_ai_update = 0.0
        self.ai_move = 0
        self.ai_shoot = False

    def help_lines(self) -> list[str]:
        return [
            "INVADERS CONTROLS",
            "LEFT / RIGHT   Move cannon",
            "A / D          Move cannon",
            "SPACE          Fire",
            "R              Restart game",
            "Input takes control; inactivity returns to defense AI",
        ]

    def _layout(self, width: int, height: int) -> tuple[int, int, int, int]:
        field_width = max(30, min(82, width - 6))
        field_height = max(16, min(30, height - 5))
        x = max(1, (width - field_width - 2) // 2)
        y = max(1, (height - field_height - 2) // 2)
        return x, y, field_width, field_height

    def _enemy_columns(self) -> int:
        return max(5, min(10, (self.field_width - 12) // 6))

    def _enemy_rows(self) -> int:
        return 4 if self.field_height >= 22 else 3

    def _formation_width(self) -> int:
        columns = self._enemy_columns()
        return max(3, (columns - 1) * 5 + 3)

    def _make_enemies(self) -> list[dict[str, Any]]:
        result = []
        columns = self._enemy_columns()
        rows = self._enemy_rows()
        for row in range(rows):
            for column in range(columns):
                result.append({
                    "col": column,
                    "row": row,
                    "alive": True,
                    "kind": min(2, row),
                    "screen_x": 0,
                    "screen_y": 0,
                })
        return result

    def _make_barriers(self) -> set[tuple[int, int]]:
        cells: set[tuple[int, int]] = set()
        count = 4 if self.field_width >= 52 else 3
        barrier_y = self.field_height - 6
        centers = [int(round((index + 1) * self.field_width / (count + 1))) for index in range(count)]
        shape = (
            " █████ ",
            "███████",
            "██   ██",
        )
        for center in centers:
            left = center - len(shape[0]) // 2
            for sy, line in enumerate(shape):
                for sx, char in enumerate(line):
                    if char != " ":
                        x = left + sx
                        y = barrier_y + sy
                        if 0 <= x < self.field_width and 0 <= y < self.field_height:
                            cells.add((x, y))
        return cells

    def _screen_enemy_positions(self) -> None:
        for enemy in self.enemies:
            enemy["screen_x"] = self.formation_x + int(enemy["col"]) * 5 + 2
            enemy["screen_y"] = self.formation_y + int(enemy["row"]) * 2

    def _reset_wave(self, now: float) -> None:
        self.enemies = self._make_enemies()
        formation_width = self._formation_width()
        self.formation_x = max(1, (self.field_width - formation_width) // 2)
        self.formation_y = 3
        self.formation_direction = random.choice((-1, 1))
        self.last_formation_step = now
        self.player_bullets = []
        self.enemy_bullets = []
        self.barriers = self._make_barriers()
        self.player_x = self.field_width / 2.0
        self.player_move = 0
        self.player_move_until = 0.0
        self.next_player_fire = now
        self.last_enemy_fire = now
        self._screen_enemy_positions()

    def _reset_game(self, now: float, keep_mode: bool = True) -> None:
        self.score = 0
        self.lives = 3
        self.wave = 1
        self.state = "playing"
        self.state_until = 0.0
        self.explosions = []
        if not keep_mode:
            self.demo_mode = True
        self._reset_wave(now)

    def reset(self, settings: dict, width: int, height: int, now: float | None = None) -> None:
        base = time.monotonic() if now is None else now
        _, _, self.field_width, self.field_height = self._layout(width, height)
        self.demo_mode = True
        self.last_input = base
        self.last_update = base
        self.next_ai_update = base
        self._reset_game(base, True)

    def _set_player_mode(self) -> None:
        self.demo_mode = False
        self.last_input = time.monotonic()

    def _fire_player(self, now: float) -> bool:
        if self.state != "playing" or now < self.next_player_fire:
            return False
        if len(self.player_bullets) >= 3:
            return False
        self.player_bullets.append({"x": float(round(self.player_x)), "y": float(self.field_height - 3)})
        self.next_player_fire = now + 0.22
        return True

    def handle_runtime_key(self, key: str, settings: dict) -> bool:
        normalized = str(key or "")
        letter = normalized.casefold()
        if normalized == "LEFT" or letter == "a":
            self._set_player_mode()
            self.player_move = -1
            self.player_move_until = time.monotonic() + 0.14
            return True
        if normalized == "RIGHT" or letter == "d":
            self._set_player_mode()
            self.player_move = 1
            self.player_move_until = time.monotonic() + 0.14
            return True
        if normalized == " " or letter == "f":
            self._set_player_mode()
            self._fire_player(time.monotonic())
            return True
        if letter == "r":
            self._set_player_mode()
            self._reset_game(time.monotonic(), True)
            return True
        return False

    def _formation_interval(self, settings: dict) -> float:
        speed = max(0, min(100, int(settings.get("GameSpeed", 50))))
        base = 0.72 - speed * 0.0046
        living = sum(1 for enemy in self.enemies if enemy.get("alive"))
        total = max(1, len(self.enemies))
        factor = 0.34 + 0.66 * living / total
        return max(0.045, base * factor)

    def _step_formation(self, settings: dict, now: float) -> None:
        interval = self._formation_interval(settings)
        steps = 0
        while now - self.last_formation_step >= interval and steps < 5:
            self.last_formation_step += interval
            living = [enemy for enemy in self.enemies if enemy.get("alive")]
            if not living:
                return
            self._screen_enemy_positions()
            left = min(int(enemy["screen_x"]) - 1 for enemy in living)
            right = max(int(enemy["screen_x"]) + 1 for enemy in living)
            drop = (self.formation_direction < 0 and left <= 1) or (self.formation_direction > 0 and right >= self.field_width - 2)
            if drop:
                self.formation_direction *= -1
                self.formation_y += 1
            else:
                self.formation_x += self.formation_direction
            self._screen_enemy_positions()
            steps += 1
        player_line = self.field_height - 3
        if any(enemy.get("alive") and int(enemy.get("screen_y", 0)) >= player_line - 2 for enemy in self.enemies):
            self._game_over(now, "INVASION COMPLETE")

    def _enemy_fire_interval(self, settings: dict) -> float:
        rate = max(0, min(100, int(settings.get("EnemyFireRate", 45))))
        return max(0.18, 1.35 - rate * 0.010)

    def _fire_enemy(self, settings: dict, now: float) -> None:
        if now - self.last_enemy_fire < self._enemy_fire_interval(settings):
            return
        self.last_enemy_fire = now
        living = [enemy for enemy in self.enemies if enemy.get("alive")]
        if not living:
            return
        lowest: dict[int, dict[str, Any]] = {}
        for enemy in living:
            column = int(enemy["col"])
            current = lowest.get(column)
            if current is None or int(enemy["row"]) > int(current["row"]):
                lowest[column] = enemy
        candidates = list(lowest.values())
        if not candidates:
            return
        if random.random() < 0.42:
            shooter = min(candidates, key=lambda enemy: abs(int(enemy["screen_x"]) - self.player_x))
        else:
            shooter = random.choice(candidates)
        self.enemy_bullets.append({"x": float(shooter["screen_x"]), "y": float(shooter["screen_y"] + 1)})

    def _add_explosion(self, x: float, y: float, now: float, duration: float = 0.28) -> None:
        self.explosions.append({"x": x, "y": y, "until": now + duration})

    def _hit_player(self, now: float) -> None:
        if self.state != "playing":
            return
        self.lives -= 1
        self._add_explosion(self.player_x, self.field_height - 2, now, 0.65)
        self.player_bullets = []
        self.enemy_bullets = []
        if self.lives <= 0:
            self._game_over(now, "DEFENSE FAILED")
        else:
            self.state = "respawn"
            self.state_until = now + 1.0

    def _game_over(self, now: float, reason: str) -> None:
        if self.state == "gameover":
            return
        self.high_score = max(self.high_score, self.score)
        self.state = "gameover"
        self.state_until = now + (1.2 if self.demo_mode else 2.2)
        self.game_over_reason = reason

    def _bullet_hits_barrier(self, bullet: dict[str, float]) -> bool:
        point = (int(round(bullet["x"])), int(round(bullet["y"])))
        if point in self.barriers:
            self.barriers.discard(point)
            neighbors = [
                (point[0] - 1, point[1]),
                (point[0] + 1, point[1]),
                (point[0], point[1] - 1),
                (point[0], point[1] + 1),
            ]
            if random.random() < 0.35:
                existing = [candidate for candidate in neighbors if candidate in self.barriers]
                if existing:
                    self.barriers.discard(random.choice(existing))
            return True
        return False

    def _update_bullets(self, settings: dict, now: float, dt: float) -> None:
        speed_scale = 0.85 + max(0, min(100, int(settings.get("GameSpeed", 50)))) / 100.0 * 0.45
        player_speed = 24.0 * speed_scale
        enemy_speed = 12.0 * speed_scale
        for bullet in self.player_bullets:
            bullet["y"] -= player_speed * dt
        for bullet in self.enemy_bullets:
            bullet["y"] += enemy_speed * dt
        surviving_player = []
        for bullet in self.player_bullets:
            if bullet["y"] < 0:
                continue
            if self._bullet_hits_barrier(bullet):
                continue
            hit = None
            for enemy in self.enemies:
                if not enemy.get("alive"):
                    continue
                if abs(float(enemy["screen_x"]) - bullet["x"]) <= 1.35 and abs(float(enemy["screen_y"]) - bullet["y"]) <= 0.75:
                    hit = enemy
                    break
            if hit is not None:
                hit["alive"] = False
                points = (3 - min(2, int(hit["kind"]))) * 10
                self.score += points
                self.high_score = max(self.high_score, self.score)
                self._add_explosion(float(hit["screen_x"]), float(hit["screen_y"]), now)
            else:
                surviving_player.append(bullet)
        self.player_bullets = surviving_player
        surviving_enemy = []
        player_y = self.field_height - 2
        for bullet in self.enemy_bullets:
            if bullet["y"] >= self.field_height:
                continue
            if self._bullet_hits_barrier(bullet):
                continue
            if abs(bullet["x"] - self.player_x) <= 1.45 and abs(bullet["y"] - player_y) <= 0.8:
                self._hit_player(now)
                continue
            surviving_enemy.append(bullet)
        self.enemy_bullets = surviving_enemy

    def _demo_control(self, settings: dict, now: float) -> tuple[int, bool]:
        if now < self.next_ai_update:
            return self.ai_move, self.ai_shoot
        skill = max(0, min(100, int(settings.get("AISkill", 76))))
        self.next_ai_update = now + max(0.035, 0.15 - skill * 0.00105)
        can_shoot = now >= self.next_player_fire and len(self.player_bullets) < 3
        move, shoot = InvadersAI.choose_action(
            int(round(self.player_x)),
            self.field_height - 2,
            self.enemies,
            self.enemy_bullets,
            self.field_width,
            can_shoot,
        )
        if skill < 100 and random.random() < (100 - skill) / 360.0:
            move *= -1
        if shoot and random.random() > 0.55 + skill / 300.0:
            shoot = False
        self.ai_move = move
        self.ai_shoot = shoot
        return move, shoot

    def _update(self, settings: dict, now: float) -> None:
        timeout = max(5.0, float(settings.get("DemoReturnTime", 20.0)))
        if not self.demo_mode and now - self.last_input >= timeout:
            self.demo_mode = True
        if self.state == "gameover":
            if now >= self.state_until:
                self._reset_game(now, True)
            self.last_update = now
            return
        if self.state == "waveclear":
            if now >= self.state_until:
                self.wave += 1
                self.state = "playing"
                self._reset_wave(now)
            self.last_update = now
            return
        if self.state == "respawn":
            if now >= self.state_until:
                self.state = "playing"
                self.player_x = self.field_width / 2.0
            self.last_update = now
            return
        dt = max(0.0, min(0.08, now - self.last_update))
        self.last_update = now
        move = self.player_move if now <= self.player_move_until else 0
        shoot = False
        if self.demo_mode:
            move, shoot = self._demo_control(settings, now)
        speed = 22.0
        self.player_x += move * speed * dt
        self.player_x = max(2.0, min(self.field_width - 3.0, self.player_x))
        if now > self.player_move_until:
            self.player_move = 0
        if shoot:
            self._fire_player(now)
        self._step_formation(settings, now)
        if self.state != "playing":
            return
        self._fire_enemy(settings, now)
        self._update_bullets(settings, now, dt)
        self.explosions = [explosion for explosion in self.explosions if now < explosion["until"]]
        if self.state == "playing" and not any(enemy.get("alive") for enemy in self.enemies):
            self.state = "waveclear"
            self.state_until = now + (0.7 if self.demo_mode else 1.5)
            self.player_bullets = []
            self.enemy_bullets = []

    def _draw_field(self, canvas: TerminalCanvas, x: int, y: int) -> None:
        title = "SPACE INVADERS // DEMO" if self.demo_mode else "SPACE INVADERS // PLAYER"
        canvas.panel(x, y, self.field_width + 2, self.field_height + 2, title, 2)
        inner_x = x + 1
        inner_y = y + 1
        status = f"SCORE {self.score:05d}   HIGH {self.high_score:05d}   WAVE {self.wave:02d}   LIVES {'▲' * max(0, self.lives)}"
        canvas.centered_text(inner_y, status, 3, inner_x, inner_x + self.field_width)
        for enemy in self.enemies:
            if not enemy.get("alive"):
                continue
            ex = inner_x + int(enemy["screen_x"]) - 1
            ey = inner_y + int(enemy["screen_y"])
            sprite = self.ENEMY_SPRITES[min(2, int(enemy["kind"]))]
            canvas.text(ex, ey, sprite, 3)
        for bx, by in self.barriers:
            canvas.put(inner_x + bx, inner_y + by, "█", 2)
        for bullet in self.player_bullets:
            canvas.put(inner_x + int(round(bullet["x"])), inner_y + int(round(bullet["y"])), "│", 4)
        for bullet in self.enemy_bullets:
            canvas.put(inner_x + int(round(bullet["x"])), inner_y + int(round(bullet["y"])), "!", 3)
        if self.state != "respawn":
            canvas.text(inner_x + int(round(self.player_x)) - 1, inner_y + self.field_height - 2, "/A\\", 4)
        for explosion in self.explosions:
            canvas.text(inner_x + int(round(explosion["x"])) - 1, inner_y + int(round(explosion["y"])), "***", 4)

    def render(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        x, y, field_width, field_height = self._layout(width, height)
        if field_width != self.field_width or field_height != self.field_height:
            self.field_width = field_width
            self.field_height = field_height
            self._reset_wave(now)
        self._update(settings, now)
        canvas = self.ui.canvas(width, height)
        self._draw_field(canvas, x, y)
        hint_y = min(height - 1, y + self.field_height + 2)
        if hint_y < height:
            hint = "AUTOMATED DEFENSE • PRESS LEFT/RIGHT OR A/D TO TAKE CONTROL" if self.demo_mode else "LEFT/RIGHT OR A/D MOVE • SPACE FIRE • R RESTART"
            canvas.centered_text(hint_y, hint, 1)
        if self.state == "gameover":
            canvas.overlay_center_box("GAME OVER", [getattr(self, "game_over_reason", "DEFENSE FAILED"), f"SCORE {self.score}"])
        elif self.state == "waveclear":
            canvas.overlay_center_box("WAVE CLEAR", [f"SECTOR {self.wave:02d} SECURED", "PREPARING NEXT FORMATION"])
        elif self.state == "respawn":
            canvas.overlay_center_box("SHIP DESTROYED", [f"LIVES REMAINING {self.lives}"])
        return canvas

    def reverse_direction(self, settings: dict) -> None:
        self.formation_direction *= -1

    def primary_speed_label(self, settings: dict) -> str:
        mode = "Defense AI" if self.demo_mode else "Player"
        return f"Invaders {mode} • Wave {self.wave} • Score {self.score}"


PROTOCOL_CLASS = TerminalSSInvadersProtocol
