# game.py
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from collections import deque
from typing import Deque, Dict, List, Optional, Set, Tuple


# ============================================================
# CONFIG (SOLO estas variables son editables por ti)
# ============================================================

INITIAL_SNAKE_LENGTH = 5

INITIAL_FOODS = 1  # “originales” (respawnean). Recomendado dejar en 1
MAX_EXTRA_FOODS_SIMULTANEOUS = 1  # tecla Z añade extras hasta este máximo; extras NO respawnean

BOMB_DURATION_MS = 5000
BOMB_SPAWN_COUNT = 1  # tecla X spawnea esta cantidad simultánea

GRID_SIZE = 16  # 16 => 16x16
WALL_COLLISION = True

INITIAL_FPS = 12


# ============================================================
# Dominio
# ============================================================

@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int


class Direction(Enum):
    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)

    @property
    def dx(self) -> int:
        return self.value[0]

    @property
    def dy(self) -> int:
        return self.value[1]


DIRS: Tuple[Direction, ...] = (Direction.UP, Direction.DOWN, Direction.LEFT, Direction.RIGHT)


def in_bounds(p: Point, n: int) -> bool:
    return 0 <= p.x < n and 0 <= p.y < n


def wrap(p: Point, n: int) -> Point:
    return Point(p.x % n, p.y % n)


def manhattan(a: Point, b: Point) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def layer_index(p: Point, n: int) -> int:
    return min(p.x, p.y, n - 1 - p.x, n - 1 - p.y)


# ============================================================
# Estado del juego
# ============================================================

@dataclass(slots=True)
class GameConfig:
    n: int
    wall_collision: bool
    fps: int


@dataclass(slots=True)
class Food:
    pos: Point
    respawn: bool  # True = “original”; False = “extra”


@dataclass(slots=True)
class GameState:
    snake: Deque[Point]           # head = snake[0]
    direction: Direction
    foods: List[Food]
    bombs: Dict[Point, int]       # Point -> expire_ms
    alive: bool
    score: int

    # visual
    snake_color_index: int

    # bot instrumentation
    tick: int
    head_history: Deque[Point]    # tamaño fijo
    cycle_penalty_until: int      # ticks hasta los que castigamos bucles


# ============================================================
# Helpers de spawn / movimiento
# ============================================================

def head_step(head: Point, d: Direction, cfg: GameConfig) -> Optional[Point]:
    nxt = Point(head.x + d.dx, head.y + d.dy)
    if cfg.wall_collision:
        return nxt if in_bounds(nxt, cfg.n) else None
    return wrap(nxt, cfg.n)


def random_free_cell(state: GameState, cfg: GameConfig, rng: random.Random) -> Optional[Point]:
    occupied = set(state.snake) | set(state.bombs.keys()) | {f.pos for f in state.foods}
    free = [Point(x, y) for y in range(cfg.n) for x in range(cfg.n) if Point(x, y) not in occupied]
    return rng.choice(free) if free else None


def make_default_config() -> GameConfig:
    return GameConfig(
        n=int(GRID_SIZE),
        wall_collision=bool(WALL_COLLISION),
        fps=int(INITIAL_FPS),
    )


def make_new_game_state(cfg: GameConfig, rng: random.Random) -> GameState:
    n = cfg.n
    cx, cy = n // 2, n // 2
    snake = deque([Point(cx - i, cy) for i in range(INITIAL_SNAKE_LENGTH)])

    state = GameState(
        snake=snake,
        direction=Direction.RIGHT,
        foods=[],
        bombs={},
        alive=True,
        score=0,
        snake_color_index=rng.randrange(0, 8),
        tick=0,
        head_history=deque(maxlen=180),
        cycle_penalty_until=0,
    )

    # spawn originales (respawn=True)
    for _ in range(max(1, int(INITIAL_FOODS))):
        p = random_free_cell(state, cfg, rng)
        if p is None:
            break
        state.foods.append(Food(pos=p, respawn=True))

    state.head_history.append(state.snake[0])
    return state


# ============================================================
# Reglas del juego (comidas + bombas TTL) — igual
# ============================================================

class SnakeRules:
    def __init__(self, rng: random.Random):
        self.rng = rng

    def step(self, state: GameState, cfg: GameConfig, now_ms: int) -> None:
        if not state.alive:
            return

        # limpiar bombas expiradas
        if state.bombs:
            expired = [p for p, t in state.bombs.items() if t <= now_ms]
            for p in expired:
                state.bombs.pop(p, None)

        head = state.snake[0]
        nxt = head_step(head, state.direction, cfg)
        if nxt is None:
            state.alive = False
            return

        if nxt in state.bombs:
            state.alive = False
            return

        # detectar si come
        eaten_index = -1
        for i, f in enumerate(state.foods):
            if f.pos == nxt:
                eaten_index = i
                break
        eats = (eaten_index != -1)

        # auto-colisión (si no come, cola se mueve)
        body_set = set(state.snake)
        tail = state.snake[-1]
        if nxt in body_set:
            if not eats and nxt == tail:
                # permitido: la cola sale
                pass
            else:
                state.alive = False
                return

        # mover
        state.snake.appendleft(nxt)
        if eats:
            state.score += 1
            eaten_food = state.foods.pop(eaten_index)

            # respawn SOLO si era “original”
            if eaten_food.respawn:
                self._spawn_original_food(state, cfg)
        else:
            state.snake.pop()

        # instrumentation
        state.tick += 1
        state.head_history.append(state.snake[0])
        while len(state.head_history) > 180:
            state.head_history.popleft()

    def _spawn_original_food(self, state: GameState, cfg: GameConfig) -> None:
        originals = [f for f in state.foods if f.respawn]
        if len(originals) >= INITIAL_FOODS:
            return
        p = random_free_cell(state, cfg, self.rng)
        if p is None:
            return
        state.foods.append(Food(pos=p, respawn=True))


# ============================================================
# Utilidades que usan acciones externas (ex.py) de forma segura
# (No dependen de pygame, solo del estado)
# ============================================================

def spawn_bombs(state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int,
                count: int = BOMB_SPAWN_COUNT, ttl_ms: int = BOMB_DURATION_MS) -> None:
    count = max(1, int(count))
    ttl_ms = max(200, int(ttl_ms))
    for _ in range(count):
        p = random_free_cell(state, cfg, rng)
        if p is None:
            break
        state.bombs[p] = now_ms + ttl_ms


def spawn_extra_food(state: GameState, cfg: GameConfig, rng: random.Random,
                     max_extra: int = MAX_EXTRA_FOODS_SIMULTANEOUS) -> None:
    max_extra = max(0, int(max_extra))
    extras = [f for f in state.foods if not f.respawn]
    if len(extras) >= max_extra:
        return
    p = random_free_cell(state, cfg, rng)
    if p is None:
        return
    state.foods.append(Food(pos=p, respawn=False))


def speed_up(cfg: GameConfig, delta: int = 1) -> None:
    cfg.fps = min(60, cfg.fps + int(delta))


def slow_down(cfg: GameConfig, delta: int = 1) -> None:
    cfg.fps = max(1, cfg.fps - int(delta))


def change_snake_color(state: GameState) -> None:
    state.snake_color_index = (state.snake_color_index + 1) % 8


def blocked_cells(state: GameState) -> Set[Point]:
    # útil para debug/bot si lo necesitas
    return set(state.snake) | set(state.bombs.keys()) | {f.pos for f in state.foods}
