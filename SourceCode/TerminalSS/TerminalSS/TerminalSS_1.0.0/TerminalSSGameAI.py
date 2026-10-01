from __future__ import annotations

from collections import deque
from typing import Any


DIRECTIONS = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}


class SnakeAI:
    @staticmethod
    def _neighbors(point: tuple[int, int], width: int, height: int, wrap: bool) -> list[tuple[str, tuple[int, int]]]:
        result = []
        x, y = point
        for name, (dx, dy) in DIRECTIONS.items():
            nx = x + dx
            ny = y + dy
            if wrap:
                nx %= width
                ny %= height
            if 0 <= nx < width and 0 <= ny < height:
                result.append((name, (nx, ny)))
        return result

    @classmethod
    def _path_to_food(
        cls,
        head: tuple[int, int],
        food: tuple[int, int],
        blocked: set[tuple[int, int]],
        width: int,
        height: int,
        wrap: bool,
    ) -> list[str]:
        queue = deque([(head, [])])
        seen = {head}
        while queue:
            point, path = queue.popleft()
            if point == food:
                return path
            for direction, neighbor in cls._neighbors(point, width, height, wrap):
                if neighbor in seen or neighbor in blocked:
                    continue
                seen.add(neighbor)
                queue.append((neighbor, path + [direction]))
        return []

    @classmethod
    def _reachable_space(
        cls,
        start: tuple[int, int],
        blocked: set[tuple[int, int]],
        width: int,
        height: int,
        wrap: bool,
    ) -> int:
        queue = deque([start])
        seen = {start}
        while queue:
            point = queue.popleft()
            for _, neighbor in cls._neighbors(point, width, height, wrap):
                if neighbor in seen or neighbor in blocked:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        return len(seen)

    @classmethod
    def choose_direction(
        cls,
        snake: list[tuple[int, int]],
        food: tuple[int, int],
        width: int,
        height: int,
        current: str,
        wrap: bool = False,
    ) -> str:
        if not snake:
            return current
        head = snake[0]
        tail = snake[-1]
        blocked = set(snake[:-1])
        opposite = {
            "UP": "DOWN",
            "DOWN": "UP",
            "LEFT": "RIGHT",
            "RIGHT": "LEFT",
        }
        path = cls._path_to_food(head, food, blocked, width, height, wrap)
        if path and path[0] != opposite.get(current):
            return path[0]
        candidates = []
        for direction, neighbor in cls._neighbors(head, width, height, wrap):
            if direction == opposite.get(current) or neighbor in blocked:
                continue
            future_blocked = set(snake[:-1])
            future_blocked.discard(tail)
            score = cls._reachable_space(neighbor, future_blocked, width, height, wrap)
            distance = abs(neighbor[0] - food[0]) + abs(neighbor[1] - food[1])
            candidates.append((score, -distance, direction))
        if not candidates:
            return current
        candidates.sort(reverse=True)
        return candidates[0][2]


class PongAI:
    @staticmethod
    def choose_move(
        paddle_center: float,
        ball_y: float,
        ball_dy: float,
        dead_zone: float = 0.75,
        bias: float = 0.0,
    ) -> int:
        target = ball_y + bias
        delta = target - paddle_center
        if abs(delta) <= dead_zone:
            return 0
        if ball_dy == 0 and abs(delta) < dead_zone * 2:
            return 0
        return 1 if delta > 0 else -1


class InvadersAI:
    @staticmethod
    def choose_action(
        player_x: int,
        player_y: int,
        enemies: list[dict[str, Any]],
        enemy_bullets: list[dict[str, float]],
        field_width: int,
        can_shoot: bool,
    ) -> tuple[int, bool]:
        danger_left = 0.0
        danger_right = 0.0
        immediate = False
        for bullet in enemy_bullets:
            bx = float(bullet.get("x", 0.0))
            by = float(bullet.get("y", 0.0))
            vertical = player_y - by
            if vertical < 0 or vertical > 7:
                continue
            horizontal = bx - player_x
            weight = max(0.0, 8.0 - vertical) / max(1.0, abs(horizontal) + 1.0)
            if horizontal <= 0:
                danger_left += weight
            if horizontal >= 0:
                danger_right += weight
            if abs(horizontal) <= 2 and vertical <= 4:
                immediate = True
        living = [enemy for enemy in enemies if enemy.get("alive", True)]
        if not living:
            return 0, False
        lowest_by_column: dict[int, dict[str, Any]] = {}
        for enemy in living:
            x = int(enemy.get("screen_x", enemy.get("x", 0)))
            y = int(enemy.get("screen_y", enemy.get("y", 0)))
            current = lowest_by_column.get(x)
            if current is None or y > int(current.get("screen_y", current.get("y", 0))):
                lowest_by_column[x] = enemy
        targets = list(lowest_by_column.values()) or living
        target = min(
            targets,
            key=lambda enemy: (
                abs(int(enemy.get("screen_x", enemy.get("x", 0))) - player_x),
                -int(enemy.get("screen_y", enemy.get("y", 0))),
            ),
        )
        target_x = int(target.get("screen_x", target.get("x", 0)))
        move = 0
        if immediate:
            if danger_left > danger_right and player_x < field_width - 3:
                move = 1
            elif danger_right > danger_left and player_x > 2:
                move = -1
            elif player_x < field_width // 2:
                move = 1
            else:
                move = -1
        elif abs(target_x - player_x) > 1:
            move = 1 if target_x > player_x else -1
        aligned = abs(target_x - player_x) <= 1
        shoot = bool(can_shoot and aligned and not immediate)
        return move, shoot
