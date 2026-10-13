# Snake — Bot Focused — Version 1.20 (unificada) — FIX corner-food stall
# Reqs: pip install pygame
# Opcional TikTok: corre tu tiktok_listener.py (UDP -> 127.0.0.1:8765)

from __future__ import annotations

import sys
import json
import socket
import random
from dataclasses import dataclass
from enum import Enum
from collections import deque
from typing import Deque, Dict, List, Optional, Protocol, Set, Tuple, Any

try:
    import pygame  # type: ignore
except Exception as e:
    print("ERROR: No se pudo importar pygame.")
    print("Instala con: python -m pip install pygame")
    print("Detalle:", repr(e))
    sys.exit(1)

# ============================================================
# CONFIG (SOLO estas variables son editables por ti)
# ============================================================

INITIAL_SNAKE_LENGTH = 5

INITIAL_FOODS = 1               # “originales” (respawnean). Recomendado dejar en 1
BOMB_DURATION_MS = 5000
BOMB_SPAWN_COUNT = 1

GRID_SIZE = 16                  # 16 => 16x16
WALL_COLLISION_DEFAULT = True   # el toggle W cambia esto en runtime

INITIAL_FPS = 12                # velocidad base (J/L la modifican)

# BOT TUNING (SOLO estas dos variables)
PATTERN_VS_FOOD = 7       # 1..10 (1=mantener patrón, 10=ir por comida lo más rápido posible, SIEMPRE con retorno seguro)
PATTERN_VS_DYNAMISM = 6   # 1..10 (1=muy patrón, 10=sin patrón)

# UDP (Tk.py)
UDP_HOST = "127.0.0.1"
UDP_PORT = 8765

# MODES
EXTASIS_DURATION_MS = 10_000
GOLDEN_DURATION_MS = 7_000

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


def dir_from_to(a: Point, b: Point) -> Direction:
    dx = b.x - a.x
    dy = b.y - a.y
    if dx == 1 and dy == 0:
        return Direction.RIGHT
    if dx == -1 and dy == 0:
        return Direction.LEFT
    if dx == 0 and dy == 1:
        return Direction.DOWN
    return Direction.UP


# ============================================================
# Estado del juego
# ============================================================

class SnakeMode(Enum):
    NORMAL = "NORMAL"
    EXTASIS = "EXTASIS"
    GOLDEN = "GOLDEN"


@dataclass(slots=True)
class GameConfig:
    n: int
    wall_collision: bool
    fps_base: int  # velocidad base; el modo aplica multiplicador


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

    # growth
    grow_pending: int

    # runtime toggles / modes
    paused: bool
    mode: SnakeMode
    mode_until_ms: int
    last_donor: str

    # pattern stage
    pattern_stage: int            # 0 early, 1 mid, 2 late


# ============================================================
# EventBus + Actions (teclado + UDP + TikTok)
# ============================================================

@dataclass(frozen=True, slots=True)
class GameEvent:
    type: str
    payload: Dict[str, Any] | None = None


class EventBus:
    def __init__(self):
        self._q: Deque[GameEvent] = deque()

    def emit(self, ev: GameEvent) -> None:
        self._q.append(ev)

    def drain(self) -> List[GameEvent]:
        out: List[GameEvent] = []
        while self._q:
            out.append(self._q.popleft())
        return out


class IGameAction(Protocol):
    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        ...


def random_free_cell(state: GameState, cfg: GameConfig, rng: random.Random) -> Optional[Point]:
    occupied = set(state.snake) | set(state.bombs.keys()) | {f.pos for f in state.foods}
    free = [Point(x, y) for y in range(cfg.n) for x in range(cfg.n) if Point(x, y) not in occupied]
    return rng.choice(free) if free else None


class SpawnBombAction:
    def __init__(self, count: int, ttl_ms: int):
        self.count = max(1, int(count))
        self.ttl_ms = max(200, int(ttl_ms))

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        for _ in range(self.count):
            p = random_free_cell(state, cfg, rng)
            if p is None:
                break
            state.bombs[p] = now_ms + self.ttl_ms


class SpawnExtraFoodAction:
    def __init__(self, count: int):
        self.count = max(1, int(count))

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        for _ in range(self.count):
            p = random_free_cell(state, cfg, rng)
            if p is None:
                return
            state.foods.append(Food(pos=p, respawn=False))


class SpeedUpAction:
    def __init__(self, delta: int):
        self.delta = int(delta)

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        cfg.fps_base = min(60, cfg.fps_base + self.delta)


class SlowDownAction:
    def __init__(self, delta: int):
        self.delta = int(delta)

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        cfg.fps_base = max(1, cfg.fps_base - self.delta)


class ChangeSnakeColorAction:
    def __init__(self, times: int = 1):
        self.times = max(1, int(times))

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        for _ in range(self.times):
            state.snake_color_index = (state.snake_color_index + 1) % 8


class ResetGameAction:
    def __init__(self, app: "App", times: int = 1):
        self.app = app
        self.times = max(1, int(times))

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        self.app._pending_reset = True


class ToggleWallModeAction:
    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        cfg.wall_collision = not cfg.wall_collision


class PauseToggleAction:
    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        state.paused = not state.paused


class ActivateExtasisAction:
    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        if state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms:
            return
        state.mode = SnakeMode.EXTASIS
        state.mode_until_ms = now_ms + EXTASIS_DURATION_MS


class ActivateGoldenAction:
    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        state.mode = SnakeMode.GOLDEN
        state.mode_until_ms = now_ms + GOLDEN_DURATION_MS


class UpdateDonorAction:
    def __init__(self, donor: str):
        self.donor = (donor or "").strip()

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        if self.donor:
            state.last_donor = self.donor


class ActionSystem:
    def __init__(self, app: "App"):
        self.app = app

    def dispatch(self, events: List[GameEvent], state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        for ev in events:
            t = ev.type
            payload = ev.payload or {}

            donor = payload.get("donor") or payload.get("sender") or payload.get("user")
            if donor:
                UpdateDonorAction(str(donor)).apply(state, cfg, rng, now_ms)

            if t == "SPAWN_BOMB":
                SpawnBombAction(
                    count=int(payload.get("count", BOMB_SPAWN_COUNT)),
                    ttl_ms=int(payload.get("ttl_ms", BOMB_DURATION_MS)),
                ).apply(state, cfg, rng, now_ms)
            elif t == "SPAWN_EXTRA_FOOD":
                SpawnExtraFoodAction(count=int(payload.get("count", 1))).apply(state, cfg, rng, now_ms)
            elif t in ("SPEED_UP",):
                SpeedUpAction(delta=int(payload.get("delta", 1))).apply(state, cfg, rng, now_ms)
            elif t in ("SLOW_DOWN",):
                SlowDownAction(delta=int(payload.get("delta", 1))).apply(state, cfg, rng, now_ms)
            elif t in ("CHANGE_SNAKE_COLOR", "SNAKE_COLOR_CYCLE"):
                ChangeSnakeColorAction(times=int(payload.get("times", 1))).apply(state, cfg, rng, now_ms)
            elif t in ("RESET_GAME",):
                ResetGameAction(self.app, times=int(payload.get("times", 1))).apply(state, cfg, rng, now_ms)
            elif t in ("TOGGLE_WALL_MODE", "WRAP_TOGGLE"):
                ToggleWallModeAction().apply(state, cfg, rng, now_ms)
            elif t in ("PAUSE_TOGGLE",):
                PauseToggleAction().apply(state, cfg, rng, now_ms)
            elif t in ("EXTASIS", "ACTIVATE_EXTASIS"):
                ActivateExtasisAction().apply(state, cfg, rng, now_ms)
            elif t in ("GOLDEN_MODE", "ACTIVATE_GOLDEN"):
                ActivateGoldenAction().apply(state, cfg, rng, now_ms)
            elif t in ("UPDATE_DONOR",):
                UpdateDonorAction(str(payload.get("donor", ""))).apply(state, cfg, rng, now_ms)


# ============================================================
# Movimiento (wall / wrap)
# ============================================================

def head_step(head: Point, d: Direction, cfg: GameConfig) -> Optional[Point]:
    nxt = Point(head.x + d.dx, head.y + d.dy)
    if cfg.wall_collision:
        return nxt if in_bounds(nxt, cfg.n) else None
    return wrap(nxt, cfg.n)


# ============================================================
# Patrones (branding)
# ============================================================

class Pattern(Protocol):
    name: str
    display: str
    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        ...


class SpiralPattern:
    name = "spiral"
    display = "Espiral infinita"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        n = cfg.n
        cur_layer = layer_index(head, n)

        best = state.direction
        best_score = -1e9
        for d in DIRS:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue
            lyr = layer_index(nxt, n)
            score = 0.0
            score += (cur_layer - lyr) * 3.0
            score += (1.0 if d == state.direction else 0.0) * 0.7
            score += rng.uniform(-0.05, 0.05)
            if score > best_score:
                best_score = score
                best = d
        return best


class PerimeterPattern:
    name = "perimeter"
    display = "Loop perfecto"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        n = cfg.n
        best = state.direction
        best_score = -1e9
        for d in DIRS:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue
            lyr = layer_index(nxt, n)
            score = 0.0
            score += -(lyr) * 2.2
            score += (1.0 if d == state.direction else 0.0) * 0.6
            score += rng.uniform(-0.05, 0.05)
            if score > best_score:
                best_score = score
                best = d
        return best


class ZigZagPattern:
    name = "zigzag"
    display = "Onda sinusoidal"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        prefer_horizontal = (state.tick // 22) % 2 == 0
        if prefer_horizontal:
            return Direction.RIGHT if head.x < cfg.n - 1 else Direction.LEFT
        return Direction.DOWN if head.y < cfg.n - 1 else Direction.UP


class DiagonalPattern:
    name = "diagonal"
    display = "Doble hélice"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        t = state.tick // 26
        if t % 2 == 0:
            return Direction.RIGHT if head.x < cfg.n - 1 else Direction.DOWN
        return Direction.LEFT if head.x > 0 else Direction.DOWN


class SmoothRandomPattern:
    name = "smooth_random"
    display = "Flujo suave"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        if rng.random() < 0.88:
            return state.direction
        turns = {
            Direction.UP: [Direction.LEFT, Direction.RIGHT],
            Direction.DOWN: [Direction.LEFT, Direction.RIGHT],
            Direction.LEFT: [Direction.UP, Direction.DOWN],
            Direction.RIGHT: [Direction.UP, Direction.DOWN],
        }
        cur = state.direction
        return rng.choice(turns[cur])


class HamiltonPattern:
    name = "hamilton"
    display = "Orbital"

    def __init__(self, cycle: List[Point]):
        self.nxt = {cycle[i]: cycle[(i + 1) % len(cycle)] for i in range(len(cycle))}

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        nxt = self.nxt.get(head)
        if nxt is None:
            return state.direction
        return dir_from_to(head, nxt)


def build_hamilton_cycle(n: int) -> List[Point]:
    if n % 2 == 1:
        cycle: List[Point] = []
        for y in range(n):
            xs = range(n) if y % 2 == 0 else range(n - 1, -1, -1)
            for x in xs:
                cycle.append(Point(x, y))
        return cycle

    cycle: List[Point] = []
    for y in range(n):
        cycle.append(Point(0, y))
    for x in range(1, n):
        if x % 2 == 1:
            for y in range(n - 1, 0, -1):
                cycle.append(Point(x, y))
        else:
            for y in range(1, n):
                cycle.append(Point(x, y))
    cycle.append(Point(n - 1, 0))
    for x in range(n - 2, 0, -1):
        cycle.append(Point(x, 0))
    return cycle


# ============================================================
# Reglas del juego
# ============================================================

class SnakeRules:
    def __init__(self, rng: random.Random):
        self.rng = rng

    def step(self, state: GameState, cfg: GameConfig, now_ms: int) -> None:
        if not state.alive or state.paused:
            return

        if state.mode != SnakeMode.NORMAL and now_ms >= state.mode_until_ms:
            state.mode = SnakeMode.NORMAL
            state.mode_until_ms = 0

        if state.bombs:
            expired = [p for p, t in state.bombs.items() if t <= now_ms]
            for p in expired:
                state.bombs.pop(p, None)

        head = state.snake[0]
        nxt = head_step(head, state.direction, cfg)
        if nxt is None:
            state.alive = False
            return

        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)

        if nxt in state.bombs:
            if golden_active:
                state.bombs.pop(nxt, None)
                state.score += 1
                state.grow_pending += 1
                self._move_snake(state, nxt)
                self._post_tick(state)
                return
            else:
                state.alive = False
                return

        eaten_index = -1
        for i, f in enumerate(state.foods):
            if f.pos == nxt:
                eaten_index = i
                break

        eats = (eaten_index != -1)

        body_set = set(state.snake)
        tail = state.snake[-1]
        if nxt in body_set:
            if not eats and nxt == tail:
                pass
            else:
                state.alive = False
                return

        if eats:
            eaten_food = state.foods.pop(eaten_index)
            if golden_active:
                state.score += 2
                state.grow_pending += 2
            else:
                state.score += 1
                state.grow_pending += 1

            if eaten_food.respawn:
                self._spawn_original_food(state, cfg)

            self._move_snake(state, nxt)
        else:
            self._move_snake(state, nxt)

        self._post_tick(state)

    def _move_snake(self, state: GameState, nxt: Point) -> None:
        state.snake.appendleft(nxt)
        if state.grow_pending > 0:
            state.grow_pending -= 1
        else:
            state.snake.pop()

    def _post_tick(self, state: GameState) -> None:
        state.tick += 1
        state.head_history.append(state.snake[0])
        while len(state.head_history) > 180:
            state.head_history.popleft()

        L = len(state.snake)
        if L >= 24:
            state.pattern_stage = 2
        elif L >= 12:
            state.pattern_stage = 1
        else:
            state.pattern_stage = 0

    def _spawn_original_food(self, state: GameState, cfg: GameConfig) -> None:
        originals = [f for f in state.foods if f.respawn]
        if len(originals) >= INITIAL_FOODS:
            return
        p = random_free_cell(state, cfg, self.rng)
        if p is None:
            return
        state.foods.append(Food(pos=p, respawn=True))


# ============================================================
# BOT (FIX incluido)
# ============================================================

class BotController:
    def __init__(self, rng: random.Random, patterns: List[Pattern]):
        self.rng = rng
        self.patterns = patterns

        self.current_idx = 0
        self.last_switch_tick = 0

        self.pattern_vs_food = max(1, min(10, int(PATTERN_VS_FOOD)))
        self.pattern_vs_dyn = max(1, min(10, int(PATTERN_VS_DYNAMISM)))

    def choose_direction(self, state: GameState, cfg: GameConfig, now_ms: int) -> Direction:
        if state.paused or not state.alive:
            return state.direction

        if state.mode != SnakeMode.NORMAL and now_ms >= state.mode_until_ms:
            state.mode = SnakeMode.NORMAL
            state.mode_until_ms = 0

        safe_moves = self._safe_moves(state, cfg, now_ms)
        if not safe_moves:
            return self._best_delay_death_move(state, cfg)

        loop_detected = self._detect_loop(state)
        if loop_detected and state.tick >= state.cycle_penalty_until:
            state.cycle_penalty_until = state.tick + 45
            if state.pattern_stage >= 1:
                self._switch_pattern_deterministic(state)

        if state.pattern_stage == 0:
            return self._hunt_mode_direction(state, cfg, safe_moves, now_ms)

        self._maybe_switch_pattern_by_time(state)

        pat = self.patterns[self.current_idx]
        pat_dir = pat.preferred_direction(state, cfg, self.rng)

        targets: List[Point] = [f.pos for f in state.foods]
        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)
        if golden_active and state.bombs:
            targets += list(state.bombs.keys())

        head = state.snake[0]
        tail = state.snake[-1]
        food_target = min(targets, key=lambda p: manhattan(head, p)) if targets else head

        if state.pattern_stage == 1:
            pattern_weight = 0.75
            food_weight = 0.95
            smooth_bonus_scale = 0.35
        else:
            pattern_weight = 1.05
            food_weight = 0.75
            smooth_bonus_scale = 0.55

        bombs_pressure = min(1.0, len(state.bombs) / 8.0)
        if not golden_active:
            food_weight *= (1.0 - 0.35 * bombs_pressure)
            pattern_weight *= (1.0 + 0.15 * bombs_pressure)

        best_d = safe_moves[0]
        best_score = -1e18

        for d in safe_moves:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue

            dist_food = manhattan(nxt, food_target)
            pat_bonus = 1.0 if d == pat_dir else 0.0

            straight_bonus = (0.45 * smooth_bonus_scale) if d == state.direction else 0.0
            turn_pen = (-0.25 * smooth_bonus_scale) if d != state.direction else 0.0

            head_tail_dist = manhattan(nxt, tail)
            tail_avoid = 0.0
            if head_tail_dist <= 2:
                tail_avoid = -1.2 * (3 - head_tail_dist)

            loop_pen = 0.0
            if state.tick < state.cycle_penalty_until:
                occ = sum(1 for p in list(state.head_history)[-80:] if p == nxt)
                loop_pen = -0.9 * min(4, occ)

            dyn = self.pattern_vs_dyn / 10.0
            jitter = dyn * 0.08
            rand_j = self.rng.uniform(-jitter, jitter)

            score = 0.0
            score += (-dist_food) * (2.1 * food_weight)
            score += pat_bonus * (2.2 * pattern_weight)
            score += straight_bonus + turn_pen
            score += tail_avoid
            score += loop_pen
            score += rand_j

            if any(nxt == f.pos for f in state.foods):
                score += 6.0
            if golden_active and (nxt in state.bombs):
                score += 6.0

            # FIX: no permitir que la penalización de huecos bloquee comida cerca de esquinas
            score += self._small_empty_components_penalty(state, cfg, proposed_dir=d, now_ms=now_ms)

            if score > best_score:
                best_score = score
                best_d = d

        return best_d

    def _maybe_switch_pattern_by_time(self, state: GameState) -> None:
        if state.pattern_stage == 1:
            interval = 260
        else:
            interval = 420
        if state.tick - self.last_switch_tick >= interval:
            self._switch_pattern_deterministic(state)

    def _switch_pattern_deterministic(self, state: GameState) -> None:
        self.current_idx = (self.current_idx + 1) % len(self.patterns)
        self.last_switch_tick = state.tick

    def _hunt_mode_direction(self, state: GameState, cfg: GameConfig, safe_moves: List[Direction], now_ms: int) -> Direction:
        head = state.snake[0]
        targets: List[Point] = [f.pos for f in state.foods]
        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)
        if golden_active and state.bombs:
            targets += list(state.bombs.keys())
        if not targets:
            return safe_moves[0]
        target = min(targets, key=lambda p: manhattan(head, p))

        best_d = safe_moves[0]
        best_score = -1e18
        for d in safe_moves:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue
            dist = manhattan(nxt, target)
            score = 0.0
            score += -dist * 3.2
            if d == state.direction:
                score += 0.35
            if state.tick < state.cycle_penalty_until:
                occ = sum(1 for p in list(state.head_history)[-70:] if p == nxt)
                score -= 0.9 * min(4, occ)

            if any(nxt == f.pos for f in state.foods):
                score += 8.0
            if golden_active and (nxt in state.bombs):
                score += 8.0

            score += self._small_empty_components_penalty(state, cfg, proposed_dir=d, now_ms=now_ms)

            if score > best_score:
                best_score = score
                best_d = d
        return best_d

    def _safe_moves(self, state: GameState, cfg: GameConfig, now_ms: int) -> List[Direction]:
        head = state.snake[0]
        tail = state.snake[-1]
        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)

        bombs = set(state.bombs.keys())
        snake_list = list(state.snake)
        snake_set = set(snake_list)

        safe: List[Direction] = []
        for d in DIRS:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue

            if (nxt in bombs) and (not golden_active):
                continue

            eats_food = any(nxt == f.pos for f in state.foods)
            eats_bomb = golden_active and (nxt in bombs)
            eats = eats_food or eats_bomb

            if nxt in snake_set:
                if not eats and nxt == tail:
                    pass
                else:
                    continue

            projected_snake = deque(snake_list)
            projected_snake.appendleft(nxt)

            if eats:
                pass
            else:
                if state.grow_pending > 0:
                    pass
                else:
                    projected_snake.pop()

            bombs_block = set(bombs)
            if golden_active and (nxt in bombs_block):
                bombs_block.remove(nxt)

            if not self._has_escape(projected_snake, bombs_block, cfg):
                continue

            safe.append(d)

        return safe

    def _has_escape(self, projected_snake: Deque[Point], bombs: Set[Point], cfg: GameConfig) -> bool:
        head = projected_snake[0]
        tail = projected_snake[-1]

        blocked = set(projected_snake)
        blocked.remove(tail)
        blocked |= bombs

        q = deque([head])
        seen = {head}
        while q:
            p = q.popleft()
            if p == tail:
                return True
            for d in DIRS:
                nxt = head_step(p, d, cfg)
                if nxt is None:
                    continue
                if nxt in seen:
                    continue
                if nxt in blocked:
                    continue
                seen.add(nxt)
                q.append(nxt)
        return False

    def _best_delay_death_move(self, state: GameState, cfg: GameConfig) -> Direction:
        head = state.snake[0]
        bombs = set(state.bombs.keys())
        snake_set = set(state.snake)

        best = state.direction
        best_free = -1
        for d in DIRS:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue
            if nxt in bombs:
                continue

            free = 0
            for dd in DIRS:
                nn = head_step(nxt, dd, cfg)
                if nn is None:
                    continue
                if nn in bombs or nn in snake_set:
                    continue
                free += 1

            if free > best_free:
                best_free = free
                best = d

        return best

    def _detect_loop(self, state: GameState) -> bool:
        hist = list(state.head_history)
        if len(hist) < 90:
            return False
        for L in range(4, 23):
            a = hist[-L:]
            b = hist[-2 * L:-L]
            c = hist[-3 * L:-2 * L]
            if a == b == c:
                return True
        return False

    def _small_empty_components_penalty(self, state: GameState, cfg: GameConfig, proposed_dir: Direction, now_ms: int) -> float:
        """
        Penaliza dejar componentes vacíos de tamaño 1 o 2.
        FIX: si el movimiento PROPUESTO come comida/bomba (en golden), NO penalizamos,
        para evitar el caso patológico de manzana junto a esquina que queda "prohibida".
        """
        head = state.snake[0]
        nxt = head_step(head, proposed_dir, cfg)
        if nxt is None:
            return 0.0

        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)

        eats_food = any(nxt == f.pos for f in state.foods)
        eats_bomb = golden_active and (nxt in state.bombs)
        eats = eats_food or eats_bomb

        # ---- FIX CRÍTICO ----
        if eats:
            return 0.0

        projected = deque(state.snake)
        projected.appendleft(nxt)

        if state.grow_pending > 0:
            pass
        else:
            projected.pop()

        occupied = set(projected) | ({f.pos for f in state.foods}) | (set(state.bombs.keys()) if not golden_active else set())
        n = cfg.n

        visited: Set[Point] = set()
        small_1 = 0
        small_2 = 0

        def neighbors(p: Point) -> List[Point]:
            out: List[Point] = []
            for d in DIRS:
                q = head_step(p, d, cfg)
                if q is None:
                    continue
                out.append(q)
            return out

        for y in range(n):
            for x in range(n):
                p = Point(x, y)
                if p in occupied or p in visited:
                    continue

                q = deque([p])
                visited.add(p)
                size = 0
                while q:
                    u = q.popleft()
                    size += 1
                    for v in neighbors(u):
                        if v in visited:
                            continue
                        if v in occupied:
                            continue
                        visited.add(v)
                        q.append(v)

                if size == 1:
                    small_1 += 1
                elif size == 2:
                    small_2 += 1

        return -(small_1 * 10.0 + small_2 * 6.0)


# ============================================================
# Renderer (mismo estilo 1.17; no cambia diseño)
# ============================================================

class Renderer:
    def __init__(self, cell_px: int = 32, margin_px: int = 16, hud_h: int = 52):
        self.cell_px = cell_px
        self.margin_px = margin_px
        self.hud_h = hud_h
        self.font: Optional["pygame.font.Font"] = None

        self.snake_palettes = [
            ((95, 235, 140), (65, 175, 105)),
            ((120, 190, 255), (60, 130, 210)),
            ((255, 175, 90), (205, 120, 55)),
            ((255, 120, 170), (200, 75, 125)),
            ((220, 220, 220), (140, 140, 140)),
            ((210, 140, 255), (145, 85, 200)),
            ((255, 235, 110), (205, 175, 60)),
            ((120, 255, 220), (70, 200, 170)),
        ]

    def window_size(self, n: int) -> Tuple[int, int]:
        w = n * self.cell_px + 2 * self.margin_px
        h = n * self.cell_px + 2 * self.margin_px + self.hud_h
        return w, h

    def render(self, surface: "pygame.Surface", state: GameState, cfg: GameConfig, now_ms: int, current_pattern_display: str, effective_fps: int) -> None:
        if self.font is None:
            self.font = pygame.font.SysFont("consolas", 18)

        surface.fill((12, 12, 14))
        self._draw_background(surface, cfg)

        pygame.draw.rect(surface, (18, 18, 22), pygame.Rect(0, 0, surface.get_width(), self.margin_px + self.hud_h))
        self._text(surface, f"Vel: {effective_fps} | Score: {state.score} | Pattern: {current_pattern_display}",
                   (self.margin_px, 10), (235, 235, 235))

        mode_line = self._mode_line(state, now_ms)
        self._text(surface, mode_line, (self.margin_px, 30), (170, 170, 170))

        donor = state.last_donor if state.last_donor else "-"
        self._text(surface, f"Last donor: {donor}", (self.margin_px, 48), (150, 150, 150))

        for p, exp in state.bombs.items():
            self._draw_bomb(surface, p, exp, now_ms, cfg, state)

        for f in state.foods:
            self._draw_food(surface, f, cfg, state)

        self._draw_snake(surface, list(state.snake), state.direction, state.snake_color_index, cfg, state, now_ms)

        if state.paused and state.alive:
            self._text(surface, "PAUSED", (self.margin_px, 70), (255, 220, 120))

        if not state.alive:
            self._text(surface, "GAME OVER — R reinicia | ESC menú", (self.margin_px, 70), (255, 200, 120))

    def _mode_line(self, state: GameState, now_ms: int) -> str:
        if state.mode == SnakeMode.NORMAL or state.mode_until_ms <= now_ms:
            return "State: NORMAL"
        left = max(0, state.mode_until_ms - now_ms) / 1000.0
        return f"State: {state.mode.value} ({left:0.1f}s)"

    def _origin(self) -> Tuple[int, int]:
        return self.margin_px, self.margin_px + self.hud_h

    def _cell_center(self, p: Point, cfg: GameConfig) -> Tuple[int, int]:
        ox, oy = self._origin()
        return (ox + p.x * self.cell_px + self.cell_px // 2,
                oy + p.y * self.cell_px + self.cell_px // 2)

    def _draw_background(self, surface: "pygame.Surface", cfg: GameConfig) -> None:
        ox, oy = self._origin()
        n = cfg.n
        board_w = n * self.cell_px
        board_h = n * self.cell_px
        board_rect = pygame.Rect(ox - 6, oy - 6, board_w + 12, board_h + 12)
        pygame.draw.rect(surface, (20, 20, 24), board_rect, border_radius=14)

        for y in range(n):
            for x in range(n):
                col = (34, 34, 40) if (x + y) % 2 == 0 else (26, 26, 32)
                pygame.draw.rect(surface, col, pygame.Rect(ox + x * self.cell_px, oy + y * self.cell_px, self.cell_px, self.cell_px))

        grid_color = (38, 38, 44)
        for x in range(n + 1):
            px = ox + x * self.cell_px
            pygame.draw.line(surface, grid_color, (px, oy), (px, oy + board_h), 1)
        for y in range(n + 1):
            py = oy + y * self.cell_px
            pygame.draw.line(surface, grid_color, (ox, py), (ox + board_w, py), 1)

    def _draw_snake(self, surface: "pygame.Surface", pts: List[Point], direction: Direction, color_idx: int, cfg: GameConfig, state: GameState, now_ms: int) -> None:
        if not pts:
            return

        shadow = (14, 14, 16)

        r_body = max(6, self.cell_px // 2 - 7)
        r_head = r_body + 2
        r_tail = max(5, r_body - 2)

        centers = [self._cell_center(p, cfg) for p in pts]

        def is_wrap_jump(a: Point, b: Point) -> bool:
            dx = abs(a.x - b.x)
            dy = abs(a.y - b.y)
            return dx > 1 or dy > 1

        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)
        extasis_active = (state.mode == SnakeMode.EXTASIS and state.mode_until_ms > now_ms)

        if golden_active:
            head_col = (235, 195, 90)
            body_col = (205, 160, 60)
            for i in range(len(centers) - 1):
                if (not cfg.wall_collision) and is_wrap_jump(pts[i], pts[i + 1]):
                    continue
                pygame.draw.line(surface, shadow, centers[i], centers[i + 1], r_body * 2 + 6)
            for i in range(len(centers) - 1):
                if (not cfg.wall_collision) and is_wrap_jump(pts[i], pts[i + 1]):
                    continue
                pygame.draw.line(surface, body_col, centers[i], centers[i + 1], r_body * 2)
            for i in range(1, len(centers) - 1):
                pygame.draw.circle(surface, body_col, centers[i], r_body)
            pygame.draw.circle(surface, body_col, centers[-1], r_tail)
            pygame.draw.circle(surface, head_col, centers[0], r_head)
            self._draw_head_eyes(surface, centers[0], direction, r_head)
            return

        if extasis_active:
            phase = (state.tick * 0.22) % 1.0

            def rainbow_color(i: int) -> Tuple[int, int, int]:
                h = (phase + i * 0.07) % 1.0
                x = int(h * 6.0)
                f = (h * 6.0) - x
                x = x % 6
                v = 1.0
                s = 1.0
                p = v * (1.0 - s)
                q = v * (1.0 - f * s)
                t = v * (1.0 - (1.0 - f) * s)
                if x == 0: r, g, b = v, t, p
                elif x == 1: r, g, b = q, v, p
                elif x == 2: r, g, b = p, v, t
                elif x == 3: r, g, b = p, q, v
                elif x == 4: r, g, b = t, p, v
                else: r, g, b = v, p, q
                return (int(r * 255), int(g * 255), int(b * 255))

            for i in range(len(centers) - 1):
                if (not cfg.wall_collision) and is_wrap_jump(pts[i], pts[i + 1]):
                    continue
                pygame.draw.line(surface, shadow, centers[i], centers[i + 1], r_body * 2 + 6)

            for i in range(len(centers) - 1):
                if (not cfg.wall_collision) and is_wrap_jump(pts[i], pts[i + 1]):
                    continue
                col = rainbow_color(i)
                pygame.draw.line(surface, col, centers[i], centers[i + 1], r_body * 2)

            for i in range(1, len(centers) - 1):
                pygame.draw.circle(surface, rainbow_color(i), centers[i], r_body)
            pygame.draw.circle(surface, rainbow_color(len(centers) - 1), centers[-1], r_tail)
            pygame.draw.circle(surface, rainbow_color(0), centers[0], r_head)
            self._draw_head_eyes(surface, centers[0], direction, r_head)
            return

        head_col, body_col = self.snake_palettes[color_idx % len(self.snake_palettes)]
        for i in range(len(centers) - 1):
            if (not cfg.wall_collision) and is_wrap_jump(pts[i], pts[i + 1]):
                continue
            pygame.draw.line(surface, shadow, centers[i], centers[i + 1], r_body * 2 + 6)
        for i in range(len(centers) - 1):
            if (not cfg.wall_collision) and is_wrap_jump(pts[i], pts[i + 1]):
                continue
            pygame.draw.line(surface, body_col, centers[i], centers[i + 1], r_body * 2)
        for i in range(1, len(centers) - 1):
            pygame.draw.circle(surface, body_col, centers[i], r_body)
        pygame.draw.circle(surface, body_col, centers[-1], r_tail)
        pygame.draw.circle(surface, head_col, centers[0], r_head)
        self._draw_head_eyes(surface, centers[0], direction, r_head)

    def _draw_head_eyes(self, surface: "pygame.Surface", c: Tuple[int, int], d: Direction, r: int) -> None:
        cx, cy = c
        if d == Direction.UP:
            o1 = (cx - r // 3, cy - r // 3)
            o2 = (cx + r // 3, cy - r // 3)
        elif d == Direction.DOWN:
            o1 = (cx - r // 3, cy + r // 3)
            o2 = (cx + r // 3, cy + r // 3)
        elif d == Direction.LEFT:
            o1 = (cx - r // 3, cy - r // 3)
            o2 = (cx - r // 3, cy + r // 3)
        else:
            o1 = (cx + r // 3, cy - r // 3)
            o2 = (cx + r // 3, cy + r // 3)

        pygame.draw.circle(surface, (12, 12, 12), o1, max(2, r // 6))
        pygame.draw.circle(surface, (12, 12, 12), o2, max(2, r // 6))

    def _draw_food(self, surface: "pygame.Surface", f: Food, cfg: GameConfig, state: GameState) -> None:
        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > pygame.time.get_ticks())
        if golden_active:
            self._draw_gold_food(surface, f.pos, cfg)
            return
        if f.respawn:
            self._draw_apple(surface, f.pos, cfg)
        else:
            self._draw_berry(surface, f.pos, cfg)

    def _draw_apple(self, surface: "pygame.Surface", p: Point, cfg: GameConfig) -> None:
        cx, cy = self._cell_center(p, cfg)
        r = max(6, self.cell_px // 2 - 8)
        pygame.draw.circle(surface, (220, 70, 70), (cx, cy), r)
        pygame.draw.circle(surface, (245, 120, 120), (cx - r // 3, cy - r // 3), max(2, r // 3))
        pygame.draw.rect(surface, (110, 75, 45), pygame.Rect(cx - 2, cy - r - 4, 4, 10), border_radius=2)
        leaf = [(cx + 2, cy - r - 2), (cx + r // 2 + 6, cy - r - 8), (cx + r // 2, cy - r + 6)]
        pygame.draw.polygon(surface, (70, 190, 90), leaf)

    def _draw_berry(self, surface: "pygame.Surface", p: Point, cfg: GameConfig) -> None:
        cx, cy = self._cell_center(p, cfg)
        r = max(6, self.cell_px // 2 - 9)
        pygame.draw.circle(surface, (190, 120, 255), (cx, cy), r)
        pygame.draw.circle(surface, (230, 190, 255), (cx - r // 4, cy - r // 4), max(2, r // 3))

    def _draw_gold_food(self, surface: "pygame.Surface", p: Point, cfg: GameConfig) -> None:
        cx, cy = self._cell_center(p, cfg)
        r = max(6, self.cell_px // 2 - 8)
        pygame.draw.circle(surface, (230, 190, 90), (cx, cy), r)
        pygame.draw.circle(surface, (255, 230, 140), (cx - r // 3, cy - r // 3), max(2, r // 3))

    def _draw_bomb(self, surface: "pygame.Surface", p: Point, exp_ms: int, now_ms: int, cfg: GameConfig, state: GameState) -> None:
        cx, cy = self._cell_center(p, cfg)
        r = max(6, self.cell_px // 2 - 9)

        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)
        if golden_active:
            pygame.draw.circle(surface, (210, 170, 70), (cx, cy), r)
            pygame.draw.circle(surface, (255, 230, 140), (cx - r // 4, cy - r // 4), max(2, r // 3))
            return

        pygame.draw.circle(surface, (60, 60, 70), (cx, cy), r)
        pygame.draw.circle(surface, (90, 90, 105), (cx - r // 4, cy - r // 4), max(2, r // 3))

        tleft = max(0, exp_ms - now_ms)
        blink = (tleft // 200) % 2 == 0
        spark_color = (255, 200, 80) if blink else (255, 140, 60)

        pygame.draw.line(surface, (160, 130, 90), (cx + r // 2, cy - r // 2), (cx + r + 6, cy - r - 6), 3)
        pygame.draw.circle(surface, spark_color, (cx + r + 6, cy - r - 6), 4)

    def _text(self, surface: "pygame.Surface", s: str, pos: Tuple[int, int], col: Tuple[int, int, int]) -> None:
        assert self.font is not None
        img = self.font.render(s, True, col)
        surface.blit(img, pos)


# ============================================================
# Input (teclado -> GameEvents)
# ============================================================

class ExternalInputController:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    def handle_keydown(self, key: int) -> None:
        if key == pygame.K_j:
            self.event_bus.emit(GameEvent("SLOW_DOWN", {"delta": 1}))
        elif key == pygame.K_l:
            self.event_bus.emit(GameEvent("SPEED_UP", {"delta": 1}))
        elif key == pygame.K_k:
            self.event_bus.emit(GameEvent("PAUSE_TOGGLE", {}))
        elif key == pygame.K_x:
            self.event_bus.emit(GameEvent("SPAWN_BOMB", {"count": BOMB_SPAWN_COUNT, "ttl_ms": BOMB_DURATION_MS}))
        elif key == pygame.K_z:
            self.event_bus.emit(GameEvent("SPAWN_EXTRA_FOOD", {"count": 1}))
        elif key == pygame.K_c:
            self.event_bus.emit(GameEvent("SNAKE_COLOR_CYCLE", {"times": 1}))
        elif key == pygame.K_w:
            self.event_bus.emit(GameEvent("WRAP_TOGGLE", {}))
        elif key == pygame.K_e:
            self.event_bus.emit(GameEvent("EXTASIS", {}))
        elif key == pygame.K_g:
            self.event_bus.emit(GameEvent("GOLDEN_MODE", {}))


# ============================================================
# UDP Receiver
# ============================================================

class UDPReceiver:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.host, self.port))
        self.sock.setblocking(False)

    def poll(self, bus: EventBus) -> None:
        while True:
            try:
                data, _addr = self.sock.recvfrom(65535)
            except BlockingIOError:
                break
            except Exception:
                break

            try:
                msg = json.loads(data.decode("utf-8"))
                if not isinstance(msg, dict):
                    continue
                ev_type = str(msg.get("type", "")).strip()
                payload = msg.get("payload", {})
                if payload is None:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                if ev_type:
                    bus.emit(GameEvent(ev_type, payload))
            except Exception:
                continue


# ============================================================
# Scenes
# ============================================================

class Scene(Protocol):
    def handle(self, events: List["pygame.event.Event"]) -> Optional["Scene"]:
        ...
    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        ...


class MenuScene:
    def __init__(self, app: "App"):
        self.app = app
        self.idx = 0
        self.items = [
            ("Play (Keyboard)", "kbd"),
            ("Watch Bot", "bot"),
            ("Quit", "quit"),
        ]
        self.font_t: Optional["pygame.font.Font"] = None
        self.font_i: Optional["pygame.font.Font"] = None
        self.font_s: Optional["pygame.font.Font"] = None

    def handle(self, events: List["pygame.event.Event"]) -> Optional["Scene"]:
        for e in events:
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return None
                if e.key in (pygame.K_UP, pygame.K_w):
                    self.idx = (self.idx - 1) % len(self.items)
                if e.key in (pygame.K_DOWN, pygame.K_s):
                    self.idx = (self.idx + 1) % len(self.items)
                if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    tag = self.items[self.idx][1]
                    if tag == "quit":
                        return None
                    if tag == "kbd":
                        return PlayScene(self.app, bot_mode=False)
                    return PlayScene(self.app, bot_mode=True)
        return self

    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        if self.font_t is None:
            self.font_t = pygame.font.SysFont("consolas", 30)
        if self.font_i is None:
            self.font_i = pygame.font.SysFont("consolas", 22)
        if self.font_s is None:
            self.font_s = pygame.font.SysFont("consolas", 16)

        surface.fill((12, 12, 14))
        surface.blit(self.font_t.render("SNAKE — BOT FOCUSED", True, (235, 235, 235)), (16, 16))

        y = 90
        for i, (label, _) in enumerate(self.items):
            sel = (i == self.idx)
            col = (255, 220, 120) if sel else (200, 200, 200)
            pref = "> " if sel else "  "
            surface.blit(self.font_i.render(pref + label, True, col), (16, y))
            y += 36

        surface.blit(self.font_s.render("UP/DOWN + ENTER | ESC quit", True, (150, 150, 150)),
                     (16, surface.get_height() - 30))


class PlayScene:
    def __init__(self, app: "App", bot_mode: bool):
        self.app = app
        self.bot_mode = bot_mode
        self.state = self.app.new_game_state()
        self.kbd_dir = self.state.direction  # flechas solo

    def handle(self, events: List["pygame.event.Event"]) -> Optional["Scene"]:
        for e in events:
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return MenuScene(self.app)
                if e.key == pygame.K_r:
                    self.state = self.app.new_game_state()

                self.app.input_controller.handle_keydown(e.key)

                if not self.bot_mode:
                    self._handle_dir_key(e.key)
        return self

    def _handle_dir_key(self, key: int) -> None:
        mapping = {
            pygame.K_UP: Direction.UP,
            pygame.K_DOWN: Direction.DOWN,
            pygame.K_LEFT: Direction.LEFT,
            pygame.K_RIGHT: Direction.RIGHT,
        }
        if key not in mapping:
            return
        cand = mapping[key]
        if (cand.dx + self.kbd_dir.dx == 0) and (cand.dy + self.kbd_dir.dy == 0):
            return
        self.kbd_dir = cand

    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        pat_display = self.app.current_pattern_display(self.state)
        eff_fps = self.app.effective_fps(self.state, now_ms)
        self.app.renderer.render(surface, self.state, self.app.cfg, now_ms, pat_display, eff_fps)


# ============================================================
# App
# ============================================================

class App:
    def __init__(self):
        self.rng = random.Random()

        self.cfg = GameConfig(
            n=int(GRID_SIZE),
            wall_collision=bool(WALL_COLLISION_DEFAULT),
            fps_base=int(INITIAL_FPS),
        )

        self.renderer = Renderer(cell_px=32, margin_px=16, hud_h=52)

        self.event_bus = EventBus()
        self.input_controller = ExternalInputController(self.event_bus)
        self.udp = UDPReceiver(UDP_HOST, UDP_PORT)

        self.rules = SnakeRules(self.rng)

        cycle = build_hamilton_cycle(self.cfg.n)
        self.patterns: List[Pattern] = [
            SpiralPattern(),
            PerimeterPattern(),
            ZigZagPattern(),
            DiagonalPattern(),
            SmoothRandomPattern(),
            HamiltonPattern(cycle),
        ]
        self.bot = BotController(self.rng, self.patterns)

        self.actions = ActionSystem(self)
        self._pending_reset = False

    def current_pattern_display(self, state: GameState) -> str:
        if state.pattern_stage == 0:
            return "Caza"
        return self.patterns[self.bot.current_idx].display

    def effective_fps(self, state: GameState, now_ms: int) -> int:
        if state.mode != SnakeMode.NORMAL and now_ms >= state.mode_until_ms:
            state.mode = SnakeMode.NORMAL
            state.mode_until_ms = 0

        mult = 1.0
        if state.mode == SnakeMode.EXTASIS and state.mode_until_ms > now_ms:
            mult = 2.0
        elif state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms:
            mult = 3.0

        eff = int(self.cfg.fps_base * mult)
        return max(1, min(60, eff))

    def new_game_state(self) -> GameState:
        n = self.cfg.n
        cx, cy = n // 2, n // 2
        snake = deque([Point(cx - i, cy) for i in range(INITIAL_SNAKE_LENGTH)])

        state = GameState(
            snake=snake,
            direction=Direction.RIGHT,
            foods=[],
            bombs={},
            alive=True,
            score=0,
            snake_color_index=self.rng.randrange(0, 8),
            tick=0,
            head_history=deque(maxlen=180),
            cycle_penalty_until=0,
            grow_pending=0,
            paused=False,
            mode=SnakeMode.NORMAL,
            mode_until_ms=0,
            last_donor="-",
            pattern_stage=0,
        )

        for _ in range(max(1, int(INITIAL_FOODS))):
            p = random_free_cell(state, self.cfg, self.rng)
            if p is None:
                break
            state.foods.append(Food(pos=p, respawn=True))

        state.head_history.append(state.snake[0])
        return state

    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption("Snake — Bot Focused (v1.20)")
        surface = pygame.display.set_mode(self.renderer.window_size(self.cfg.n))
        clock = pygame.time.Clock()

        scene: Optional[Scene] = MenuScene(self)

        while scene is not None:
            now_ms = pygame.time.get_ticks()
            events = pygame.event.get()

            scene = scene.handle(events)
            if scene is None:
                break

            self.udp.poll(self.event_bus)

            if isinstance(scene, PlayScene):
                drained = self.event_bus.drain()
                if drained:
                    self.actions.dispatch(drained, scene.state, self.cfg, self.rng, now_ms)

                if self._pending_reset:
                    scene.state = self.new_game_state()
                    self._pending_reset = False

                if scene.state.alive:
                    if scene.bot_mode and (not scene.state.paused):
                        scene.state.direction = self.bot.choose_direction(scene.state, self.cfg, now_ms)
                    elif not scene.bot_mode:
                        scene.state.direction = scene.kbd_dir

                    self.rules.step(scene.state, self.cfg, now_ms)

            scene.render(surface, now_ms)
            pygame.display.flip()

            if isinstance(scene, PlayScene):
                clock.tick(self.effective_fps(scene.state, now_ms))
            else:
                clock.tick(max(1, min(60, self.cfg.fps_base)))

        pygame.quit()


def main() -> None:
    if not (1 <= PATTERN_VS_FOOD <= 10 and 1 <= PATTERN_VS_DYNAMISM <= 10):
        print("ERROR: PATTERN_VS_FOOD y PATTERN_VS_DYNAMISM deben estar en 1..10")
        sys.exit(1)

    print("===================================")
    print(" Snake Bot Focused v1.20 (FIX corner-food stall)")
    print(" UDP listening:", UDP_HOST, UDP_PORT)
    print("===================================")

    App().run()

if __name__ == "__main__":
    main()
