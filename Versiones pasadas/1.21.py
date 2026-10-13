# Snake — Bot Focused — Version 1.21 (Organic Snake, Visual Leap & Cinematic Nuclear)
# Requisitos: pip install pygame
# Integración TikTok: corre tk.py (UDP -> 127.0.0.1:8765)

from __future__ import annotations

import sys
import json
import math
import socket
import random
from dataclasses import dataclass, field
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
# CONFIG (Variables principales de juego y bot)
# ============================================================

INITIAL_SNAKE_LENGTH = 6
INITIAL_FOODS = 1               # Comidas originales (respawneables)
BOMB_DURATION_MS = 5000         # Duración de bombas estándar
BOMB_SPAWN_COUNT = 1            # Cantidad por donación / tecla X

GRID_SIZE = 16                  # Tablero 16x16
WALL_COLLISION_DEFAULT = True   # True = colisión letal | False = Wrap morado

INITIAL_FPS = 12                # Velocidad base

# Afinación del Bot
PATTERN_VS_FOOD = 7             # 1..10 (1=patrón dominante, 10=ir a comida veloz con escape)
PATTERN_VS_DYNAMISM = 6         # 1..10 (1=rígido, 10=fluido y cambiante)

# UDP (tk.py)
UDP_HOST = "127.0.0.1"
UDP_PORT = 8765

# Modos Especiales
EXTASIS_DURATION_MS = 10_000
GOLDEN_DURATION_MS = 7_000

# ============================================================
# Dominio Espacial y Matemáticas Toroidales
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

def manhattan_plane(a: Point, b: Point) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)

def manhattan_toroidal(a: Point, b: Point, n: int) -> int:
    dx = abs(a.x - b.x)
    dy = abs(a.y - b.y)
    return min(dx, n - dx) + min(dy, n - dy)

def dist_for_config(a: Point, b: Point, cfg: "GameConfig") -> int:
    if cfg.wall_collision:
        return manhattan_plane(a, b)
    return manhattan_toroidal(a, b, cfg.n)

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
# Sistema de Partículas y Cinemática Nuclear
# ============================================================

@dataclass
class VisualParticle:
    x: float
    y: float
    vx: float
    vy: float
    color: Tuple[int, int, int]
    radius: float
    life_ms: int
    max_life_ms: int

@dataclass
class NuclearStrike:
    center: Point
    state: str                 # "FALLING", "ARMED", "EXPLODING", "FINISHED"
    start_ms: int
    fall_y: float = -100.0     # Coordenada en píxeles para animación de caída
    rings_expanded: int = 0
    max_rings: int = 12
    ring_next_ms: int = 0
    affected_cells: Dict[Point, Tuple[str, int]] = field(default_factory=dict) # Point -> (fase: "HOT"|"ASH"|"CHAR", exp_ms)

# ============================================================
# Estado del Juego y Modos
# ============================================================

class SnakeMode(Enum):
    NORMAL = "NORMAL"
    EXTASIS = "EXTASIS"
    GOLDEN = "GOLDEN"

@dataclass(slots=True)
class GameConfig:
    n: int
    wall_collision: bool
    fps_base: int

@dataclass(slots=True)
class Food:
    pos: Point
    respawn: bool  # True = original, False = extra

@dataclass
class GameState:
    snake: Deque[Point]
    direction: Direction
    foods: List[Food]
    bombs: Dict[Point, int]       # Point -> expire_ms
    alive: bool
    score: int
    snake_color_index: int
    tick: int
    head_history: Deque[Point]
    cycle_penalty_until: int
    grow_pending: int
    paused: bool
    mode: SnakeMode
    mode_until_ms: int
    last_donor: str
    pattern_stage: int
    
    # Nuevas variables visuales orgánicas
    blink_timer: int = 0
    tongue_timer: int = 0
    particles: List[VisualParticle] = field(default_factory=list)
    nuclear: Optional[NuclearStrike] = None
    last_udp_packet_ms: int = 0

# ============================================================
# EventBus y Acciones Desacopladas
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

def random_free_cell(state: GameState, cfg: GameConfig, rng: random.Random) -> Optional[Point]:
    occupied = set(state.snake) | set(state.bombs.keys()) | {f.pos for f in state.foods}
    if state.nuclear and state.nuclear.affected_cells:
        occupied |= set(state.nuclear.affected_cells.keys())
    free = [Point(x, y) for y in range(cfg.n) for x in range(cfg.n) if Point(x, y) not in occupied]
    return rng.choice(free) if free else None

class ActionSystem:
    def __init__(self, app: "App"):
        self.app = app

    def dispatch(self, events: List[GameEvent], state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        for ev in events:
            t = ev.type
            payload = ev.payload or {}

            donor = payload.get("donor") or payload.get("sender") or payload.get("user")
            if donor:
                state.last_donor = str(donor).strip()

            state.last_udp_packet_ms = now_ms

            if t == "PING":
                pass
            elif t == "SPAWN_BOMB":
                count = max(1, int(payload.get("count", BOMB_SPAWN_COUNT)))
                ttl = max(1000, int(payload.get("ttl_ms", BOMB_DURATION_MS)))
                for _ in range(count):
                    p = random_free_cell(state, cfg, rng)
                    if p: state.bombs[p] = now_ms + ttl
            elif t == "SPAWN_EXTRA_FOOD":
                count = max(1, int(payload.get("count", 1)))
                for _ in range(count):
                    p = random_free_cell(state, cfg, rng)
                    if p: state.foods.append(Food(pos=p, respawn=False))
            elif t == "SPEED_UP":
                cfg.fps_base = min(60, cfg.fps_base + int(payload.get("delta", 1)))
            elif t == "SLOW_DOWN":
                cfg.fps_base = max(1, cfg.fps_base - int(payload.get("delta", 1)))
            elif t in ("CHANGE_SNAKE_COLOR", "SNAKE_COLOR_CYCLE"):
                times = max(1, int(payload.get("times", 1)))
                state.snake_color_index = (state.snake_color_index + times) % 8
            elif t in ("RESET_GAME", "RESTART"):
                self.app._pending_reset = True
            elif t in ("TOGGLE_WALL_MODE", "WRAP_TOGGLE"):
                cfg.wall_collision = not cfg.wall_collision
            elif t == "PAUSE_TOGGLE":
                state.paused = not state.paused
            elif t in ("EXTASIS", "ACTIVATE_EXTASIS"):
                if state.mode != SnakeMode.GOLDEN:
                    state.mode = SnakeMode.EXTASIS
                    state.mode_until_ms = now_ms + EXTASIS_DURATION_MS
            elif t in ("GOLDEN_MODE", "ACTIVATE_GOLDEN"):
                state.mode = SnakeMode.GOLDEN
                state.mode_until_ms = now_ms + GOLDEN_DURATION_MS
            elif t == "SPAWN_NUCLEAR_BOMB":
                if state.nuclear is None or state.nuclear.state == "FINISHED":
                    center = Point(cfg.n // 2, cfg.n // 2)
                    state.nuclear = NuclearStrike(
                        center=center,
                        state="FALLING",
                        start_ms=now_ms,
                        fall_y=-80.0
                    )

# ============================================================
# Movimiento (Muro / Wrap Toroidal)
# ============================================================

def head_step(head: Point, d: Direction, cfg: GameConfig) -> Optional[Point]:
    nxt = Point(head.x + d.dx, head.y + d.dy)
    if cfg.wall_collision:
        return nxt if in_bounds(nxt, cfg.n) else None
    return wrap(nxt, cfg.n)

# ============================================================
# Patrones Geométricos
# ============================================================

class Pattern(Protocol):
    name: str
    display: str
    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        ...

class SpiralPattern:
    name = "spiral"
    display = "Espiral Infinita"
    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        cur_layer = layer_index(head, cfg.n)
        best = state.direction
        best_score = -1e9
        for d in DIRS:
            nxt = head_step(head, d, cfg)
            if nxt is None: continue
            lyr = layer_index(nxt, cfg.n)
            score = (cur_layer - lyr) * 3.0 + (1.0 if d == state.direction else 0.0) * 0.7 + rng.uniform(-0.05, 0.05)
            if score > best_score:
                best_score = score
                best = d
        return best

class PerimeterPattern:
    name = "perimeter"
    display = "Loop Perimetral"
    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        best = state.direction
        best_score = -1e9
        for d in DIRS:
            nxt = head_step(head, d, cfg)
            if nxt is None: continue
            lyr = layer_index(nxt, cfg.n)
            score = -(lyr * 2.2) + (1.0 if d == state.direction else 0.0) * 0.6 + rng.uniform(-0.05, 0.05)
            if score > best_score:
                best_score = score
                best = d
        return best

class ZigZagPattern:
    name = "zigzag"
    display = "Onda Sinusoidal"
    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        if (state.tick // 22) % 2 == 0:
            return Direction.RIGHT if head.x < cfg.n - 1 else Direction.LEFT
        return Direction.DOWN if head.y < cfg.n - 1 else Direction.UP

class DiagonalPattern:
    name = "diagonal"
    display = "Doble Hélice"
    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        if (state.tick // 26) % 2 == 0:
            return Direction.RIGHT if head.x < cfg.n - 1 else Direction.DOWN
        return Direction.LEFT if head.x > 0 else Direction.DOWN

class SmoothRandomPattern:
    name = "smooth_random"
    display = "Flujo Suave"
    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        if rng.random() < 0.88: return state.direction
        turns = {
            Direction.UP: [Direction.LEFT, Direction.RIGHT],
            Direction.DOWN: [Direction.LEFT, Direction.RIGHT],
            Direction.LEFT: [Direction.UP, Direction.DOWN],
            Direction.RIGHT: [Direction.UP, Direction.DOWN],
        }
        return rng.choice(turns[state.direction])

class HamiltonPattern:
    name = "hamilton"
    display = "Orbital Hamiltoniano"
    def __init__(self, cycle: List[Point]):
        self.nxt = {cycle[i]: cycle[(i + 1) % len(cycle)] for i in range(len(cycle))}

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        nxt = self.nxt.get(head)
        return dir_from_to(head, nxt) if nxt else state.direction

def build_hamilton_cycle(n: int) -> List[Point]:
    cycle: List[Point] = []
    for y in range(n): cycle.append(Point(0, y))
    for x in range(1, n):
        if x % 2 == 1:
            for y in range(n - 1, 0, -1): cycle.append(Point(x, y))
        else:
            for y in range(1, n): cycle.append(Point(x, y))
    cycle.append(Point(n - 1, 0))
    for x in range(n - 2, 0, -1): cycle.append(Point(x, 0))
    return cycle

# ============================================================
# Reglas y Dinámicas del Motor de Juego
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

        # Expiración y partículas de bombas estándar
        if state.bombs:
            expired = [p for p, t in state.bombs.items() if t <= now_ms]
            for p in expired:
                state.bombs.pop(p, None)
                self._spawn_explosion_particles(state, p, cfg, count=16)

        # Actualización de cinemática nuclear
        self._update_nuclear(state, cfg, now_ms)

        head = state.snake[0]
        nxt = head_step(head, state.direction, cfg)
        if nxt is None:
            state.alive = False
            return

        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)

        # Colisión con celdas incendiadas por bomba nuclear
        if state.nuclear and nxt in state.nuclear.affected_cells:
            phase, _ = state.nuclear.affected_cells[nxt]
            if phase in ("HOT", "ASH"):
                if not golden_active:
                    state.alive = False
                    return

        # Colisión con bomba estándar
        if nxt in state.bombs:
            if golden_active:
                state.bombs.pop(nxt, None)
                state.score += 2
                state.grow_pending += 1
                self._spawn_gold_sparks(state, nxt, cfg)
                self._move_snake(state, nxt)
                self._post_tick(state)
                return
            else:
                state.alive = False
                self._spawn_explosion_particles(state, nxt, cfg, count=24)
                return

        # Comida
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
                self._spawn_gold_sparks(state, nxt, cfg)
            else:
                state.score += 1
                state.grow_pending += 1
                self._spawn_food_bite_particles(state, nxt, cfg)

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

        # Actualizar animaciones orgánicas
        if state.blink_timer > 0:
            state.blink_timer -= 1
        elif self.rng.random() < 0.015:
            state.blink_timer = 3  # Parpadeo de 3 ticks

        if state.tongue_timer > 0:
            state.tongue_timer -= 1
        elif self.rng.random() < 0.04:
            state.tongue_timer = 4  # Lengua asomada 4 ticks

    def _spawn_original_food(self, state: GameState, cfg: GameConfig) -> None:
        originals = [f for f in state.foods if f.respawn]
        if len(originals) >= INITIAL_FOODS:
            return
        p = random_free_cell(state, cfg, self.rng)
        if p: state.foods.append(Food(pos=p, respawn=True))

    def _spawn_explosion_particles(self, state: GameState, p: Point, cfg: GameConfig, count: int = 20) -> None:
        cell_px = 32
        ox = 16 + p.x * cell_px + cell_px // 2
        oy = 68 + p.y * cell_px + cell_px // 2
        for _ in range(count):
            angle = self.rng.uniform(0, 2 * math.pi)
            spd = self.rng.uniform(2.0, 7.0)
            col = self.rng.choice([(255, 120, 30), (255, 200, 50), (220, 50, 40), (80, 80, 85)])
            state.particles.append(VisualParticle(
                x=ox, y=oy,
                vx=math.cos(angle) * spd,
                vy=math.sin(angle) * spd,
                color=col,
                radius=self.rng.uniform(3.0, 7.0),
                life_ms=self.rng.randint(300, 600),
                max_life_ms=600
            ))

    def _spawn_gold_sparks(self, state: GameState, p: Point, cfg: GameConfig) -> None:
        cell_px = 32
        ox = 16 + p.x * cell_px + cell_px // 2
        oy = 68 + p.y * cell_px + cell_px // 2
        for _ in range(14):
            ang = self.rng.uniform(0, 2 * math.pi)
            spd = self.rng.uniform(1.5, 5.0)
            state.particles.append(VisualParticle(
                x=ox, y=oy,
                vx=math.cos(ang) * spd,
                vy=math.sin(ang) * spd,
                color=(255, 235, 110),
                radius=self.rng.uniform(2.5, 5.0),
                life_ms=400,
                max_life_ms=400
            ))

    def _spawn_food_bite_particles(self, state: GameState, p: Point, cfg: GameConfig) -> None:
        cell_px = 32
        ox = 16 + p.x * cell_px + cell_px // 2
        oy = 68 + p.y * cell_px + cell_px // 2
        for _ in range(8):
            ang = self.rng.uniform(0, 2 * math.pi)
            spd = self.rng.uniform(1.0, 3.5)
            state.particles.append(VisualParticle(
                x=ox, y=oy,
                vx=math.cos(ang) * spd,
                vy=math.sin(ang) * spd,
                color=(240, 70, 70),
                radius=self.rng.uniform(2.0, 4.0),
                life_ms=300,
                max_life_ms=300
            ))

    def _update_nuclear(self, state: GameState, cfg: GameConfig, now_ms: int) -> None:
        nuke = state.nuclear
        if not nuke or nuke.state == "FINISHED":
            return

        cell_px = 32
        target_y = 68 + nuke.center.y * cell_px + cell_px // 2

        if nuke.state == "FALLING":
            nuke.fall_y += 18.0
            if nuke.fall_y >= target_y:
                nuke.fall_y = target_y
                nuke.state = "ARMED"
                nuke.start_ms = now_ms + 1200  # 1.2s armado
                self._spawn_explosion_particles(state, nuke.center, cfg, count=15)
        elif nuke.state == "ARMED":
            if now_ms >= nuke.start_ms:
                nuke.state = "EXPLODING"
                nuke.rings_expanded = 0
                nuke.ring_next_ms = now_ms
        elif nuke.state == "EXPLODING":
            # Expirar fases de celdas
            to_remove = []
            for p, (fase, exp) in nuke.affected_cells.items():
                if now_ms >= exp:
                    if fase == "HOT":
                        nuke.affected_cells[p] = ("ASH", now_ms + 900)
                    elif fase == "ASH":
                        nuke.affected_cells[p] = ("CHAR", now_ms + 1200)
                    elif fase == "CHAR":
                        to_remove.append(p)
            for p in to_remove:
                nuke.affected_cells.pop(p, None)

            # Expandir nuevo anillo
            if now_ms >= nuke.ring_next_ms and nuke.rings_expanded < nuke.max_rings:
                r = nuke.rings_expanded
                nuke.rings_expanded += 1
                nuke.ring_next_ms = now_ms + 160  # Paso entre anillos
                for y in range(cfg.n):
                    for x in range(cfg.n):
                        pt = Point(x, y)
                        if manhattan_plane(pt, nuke.center) == r:
                            nuke.affected_cells[pt] = ("HOT", now_ms + 600)
                            if pt in state.bombs:
                                state.bombs.pop(pt, None)
                                self._spawn_explosion_particles(state, pt, cfg, count=8)
            elif nuke.rings_expanded >= nuke.max_rings and not nuke.affected_cells:
                nuke.state = "FINISHED"

# ============================================================
# Bot Controller (IA Híbrida Toroidal con Fix de Esquinas)
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
        food_target = min(targets, key=lambda p: dist_for_config(head, p, cfg)) if targets else head

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
            if nxt is None: continue

            dist_food = dist_for_config(nxt, food_target, cfg)
            pat_bonus = 1.0 if d == pat_dir else 0.0

            straight_bonus = (0.45 * smooth_bonus_scale) if d == state.direction else 0.0
            turn_pen = (-0.25 * smooth_bonus_scale) if d != state.direction else 0.0

            head_tail_dist = dist_for_config(nxt, tail, cfg)
            tail_avoid = -1.2 * (3 - head_tail_dist) if head_tail_dist <= 2 else 0.0

            loop_pen = 0.0
            if state.tick < state.cycle_penalty_until:
                occ = sum(1 for p in list(state.head_history)[-80:] if p == nxt)
                loop_pen = -0.9 * min(4, occ)

            dyn = self.pattern_vs_dyn / 10.0
            rand_j = self.rng.uniform(-dyn * 0.08, dyn * 0.08)

            score = 0.0
            score += (-dist_food) * (2.1 * food_weight)
            score += pat_bonus * (2.2 * pattern_weight)
            score += straight_bonus + turn_pen + tail_avoid + loop_pen + rand_j

            if any(nxt == f.pos for f in state.foods):
                score += 6.0
            if golden_active and (nxt in state.bombs):
                score += 6.0

            # FIX CRÍTICO de esquinas incluido
            score += self._small_empty_components_penalty(state, cfg, proposed_dir=d, now_ms=now_ms)

            if score > best_score:
                best_score = score
                best_d = d

        return best_d

    def _maybe_switch_pattern_by_time(self, state: GameState) -> None:
        interval = 260 if state.pattern_stage == 1 else 420
        if state.tick - self.last_switch_tick >= interval:
            self._switch_pattern_deterministic(state)

    def _switch_pattern_deterministic(self, state: GameState) -> None:
        self.current_idx = (self.current_idx + 1) % len(self.patterns)
        self.last_switch_tick = state.tick

    def _hunt_mode_direction(self, state: GameState, cfg: GameConfig, safe_moves: List[Direction], now_ms: int) -> Direction:
        head = state.snake[0]
        targets = [f.pos for f in state.foods]
        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)
        if golden_active and state.bombs:
            targets += list(state.bombs.keys())
        if not targets:
            return safe_moves[0]
        target = min(targets, key=lambda p: dist_for_config(head, p, cfg))

        best_d = safe_moves[0]
        best_score = -1e18
        for d in safe_moves:
            nxt = head_step(head, d, cfg)
            if nxt is None: continue
            dist = dist_for_config(nxt, target, cfg)
            score = -dist * 3.2 + (0.35 if d == state.direction else 0.0)
            if state.tick < state.cycle_penalty_until:
                occ = sum(1 for p in list(state.head_history)[-70:] if p == nxt)
                score -= 0.9 * min(4, occ)
            if any(nxt == f.pos for f in state.foods): score += 8.0
            if golden_active and (nxt in state.bombs): score += 8.0
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
        if state.nuclear and state.nuclear.affected_cells and not golden_active:
            hot_cells = {p for p, (f, _) in state.nuclear.affected_cells.items() if f in ("HOT", "ASH")}
            bombs |= hot_cells

        snake_list = list(state.snake)
        snake_set = set(snake_list)
        safe: List[Direction] = []

        for d in DIRS:
            nxt = head_step(head, d, cfg)
            if nxt is None: continue
            if (nxt in bombs) and (not golden_active): continue

            eats_food = any(nxt == f.pos for f in state.foods)
            eats_bomb = golden_active and (nxt in bombs)
            eats = eats_food or eats_bomb

            if nxt in snake_set:
                if not eats and nxt == tail: pass
                else: continue

            projected = deque(snake_list)
            projected.appendleft(nxt)
            if not eats and state.grow_pending == 0:
                projected.pop()

            bombs_block = set(bombs)
            if golden_active and (nxt in bombs_block):
                bombs_block.remove(nxt)

            if not self._has_escape(projected, bombs_block, cfg):
                continue
            safe.append(d)
        return safe

    def _has_escape(self, projected_snake: Deque[Point], bombs: Set[Point], cfg: GameConfig) -> bool:
        head = projected_snake[0]
        tail = projected_snake[-1]
        blocked = set(projected_snake)
        if tail in blocked: blocked.remove(tail)
        blocked |= bombs

        q = deque([head])
        seen = {head}
        while q:
            p = q.popleft()
            if p == tail: return True
            for d in DIRS:
                nxt = head_step(p, d, cfg)
                if nxt is None or nxt in seen or nxt in blocked: continue
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
            if nxt is None or nxt in bombs: continue
            free = 0
            for dd in DIRS:
                nn = head_step(nxt, dd, cfg)
                if nn and nn not in bombs and nn not in snake_set: free += 1
            if free > best_free:
                best_free = free
                best = d
        return best

    def _detect_loop(self, state: GameState) -> bool:
        hist = list(state.head_history)
        if len(hist) < 90: return False
        for L in range(4, 23):
            a, b, c = hist[-L:], hist[-2*L:-L], hist[-3*L:-2*L]
            if a == b == c: return True
        return False

    def _small_empty_components_penalty(self, state: GameState, cfg: GameConfig, proposed_dir: Direction, now_ms: int) -> float:
        head = state.snake[0]
        nxt = head_step(head, proposed_dir, cfg)
        if nxt is None: return 0.0

        golden_active = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)
        eats_food = any(nxt == f.pos for f in state.foods)
        eats_bomb = golden_active and (nxt in state.bombs)
        if eats_food or eats_bomb:
            return 0.0  # FIX CRÍTICO: No penalizar comida en esquinas

        projected = deque(state.snake)
        projected.appendleft(nxt)
        if state.grow_pending == 0: projected.pop()

        occupied = set(projected) | {f.pos for f in state.foods} | (set(state.bombs.keys()) if not golden_active else set())
        n = cfg.n
        visited: Set[Point] = set()
        small_1 = 0
        small_2 = 0

        for y in range(n):
            for x in range(n):
                p = Point(x, y)
                if p in occupied or p in visited: continue
                q = deque([p])
                visited.add(p)
                size = 0
                while q:
                    u = q.popleft()
                    size += 1
                    for d in DIRS:
                        v = head_step(u, d, cfg)
                        if v and v not in visited and v not in occupied:
                            visited.add(v)
                            q.append(v)
                if size == 1: small_1 += 1
                elif size == 2: small_2 += 1
        return -(small_1 * 10.0 + small_2 * 6.0)

# ============================================================
# Renderer Orgánico y Cinemáticas Gráficas
# ============================================================

class Renderer:
    def __init__(self, cell_px: int = 32, margin_px: int = 16, hud_h: int = 56):
        self.cell_px = cell_px
        self.margin_px = margin_px
        self.hud_h = hud_h
        self.font_main: Optional[pygame.font.Font] = None
        self.font_sub: Optional[pygame.font.Font] = None

        self.snake_palettes = [
            ((95, 235, 140), (65, 175, 105)),   # Verde bosque
            ((120, 190, 255), (60, 130, 210)),  # Zafiro
            ((255, 175, 90), (205, 120, 55)),   # Fénix naranja
            ((255, 120, 170), (200, 75, 125)),  # Rubí rosa
            ((220, 220, 220), (140, 140, 140)), # Titanio
            ((210, 140, 255), (145, 85, 200)),  # Amatista
            ((255, 235, 110), (205, 175, 60)),  # Oro solar
            ((120, 255, 220), (70, 200, 170)),  # Turquesa
        ]

    def window_size(self, n: int) -> Tuple[int, int]:
        w = n * self.cell_px + 2 * self.margin_px
        h = n * self.cell_px + 2 * self.margin_px + self.hud_h
        return w, h

    def render(self, surface: pygame.Surface, state: GameState, cfg: GameConfig, now_ms: int, pat_display: str, eff_fps: int) -> None:
        if self.font_main is None:
            self.font_main = pygame.font.SysFont("consolas", 17, bold=True)
            self.font_sub = pygame.font.SysFont("consolas", 14)

        surface.fill((12, 12, 15))
        self._draw_board(surface, cfg, state)
        self._draw_hud(surface, state, cfg, now_ms, pat_display, eff_fps)

        # Cinemática nuclear de fondo (anillos de calor)
        if state.nuclear:
            self._draw_nuclear(surface, state.nuclear, cfg, now_ms)

        # Bombas y comida
        for p, exp in state.bombs.items():
            self._draw_bomb(surface, p, exp, now_ms, cfg, state)

        for f in state.foods:
            self._draw_food(surface, f, cfg, state, now_ms)

        # Serpiente Orgánica con Rostro Vivo y Cola Cónica
        self._draw_organic_snake(surface, state, cfg, now_ms)

        # Renderizar partículas
        self._update_and_draw_particles(surface, state)

        # Alerta de estado pausado / Game Over
        if state.paused and state.alive:
            self._draw_center_badge(surface, "SIMULACIÓN PAUSADA", (255, 215, 80))
        elif not state.alive:
            self._draw_center_badge(surface, "GAME OVER — 'R' REINICIA", (255, 100, 100))

    def _origin(self) -> Tuple[int, int]:
        return self.margin_px, self.margin_px + self.hud_h

    def _cell_center(self, p: Point) -> Tuple[int, int]:
        ox, oy = self._origin()
        return (ox + p.x * self.cell_px + self.cell_px // 2,
                oy + p.y * self.cell_px + self.cell_px // 2)

    def _draw_board(self, surface: pygame.Surface, cfg: GameConfig, state: GameState) -> None:
        ox, oy = self._origin()
        bw = cfg.n * self.cell_px
        bh = cfg.n * self.cell_px

        # Borde exterior con brillo morado en modo wrap
        border_col = (140, 70, 220) if not cfg.wall_collision else (26, 26, 32)
        pygame.draw.rect(surface, (18, 18, 22), pygame.Rect(ox - 6, oy - 6, bw + 12, bh + 12), border_radius=14)
        if not cfg.wall_collision:
            pygame.draw.rect(surface, border_col, pygame.Rect(ox - 6, oy - 6, bw + 12, bh + 12), width=2, border_radius=14)

        # Tablero estilo ajedrez sutil
        for y in range(cfg.n):
            for x in range(cfg.n):
                col = (32, 33, 38) if (x + y) % 2 == 0 else (24, 25, 29)
                pygame.draw.rect(surface, col, pygame.Rect(ox + x * self.cell_px, oy + y * self.cell_px, self.cell_px, self.cell_px))

    def _draw_hud(self, surface: pygame.Surface, state: GameState, cfg: GameConfig, now_ms: int, pat_display: str, eff_fps: int) -> None:
        ox, oy = 16, 8
        pygame.draw.rect(surface, (18, 18, 24), pygame.Rect(0, 0, surface.get_width(), self.hud_h + 10))

        # Indicador de conexión TikTok (punto verde / amarillo)
        is_live = (now_ms - state.last_udp_packet_ms < 4000) and (state.last_udp_packet_ms > 0)
        live_col = (60, 235, 120) if is_live else (200, 160, 50)
        live_txt = "TIKTOK: LIVE" if is_live else "TIKTOK: ESPERA"
        pygame.draw.circle(surface, live_col, (ox + 6, oy + 10), 5)
        surface.blit(self.font_sub.render(live_txt, True, live_col), (ox + 16, oy + 2))

        # Métricas principales
        mode_str = f" | Modo: {state.mode.value}" if state.mode != SnakeMode.NORMAL else ""
        if not cfg.wall_collision: mode_str += " [WRAP]"
        line1 = f"Vel: {eff_fps} FPS | Score: {state.score}{mode_str}"
        surface.blit(self.font_main.render(line1, True, (240, 240, 240)), (ox + 160, oy + 1))

        # Sub-información (Patrón y donante)
        donor = state.last_donor if state.last_donor else "Comunidad"
        line2 = f"Patrón: {pat_display} | Último Donante: {donor}"
        surface.blit(self.font_sub.render(line2, True, (165, 170, 185)), (ox, oy + 28))

    def _draw_organic_snake(self, surface: pygame.Surface, state: GameState, cfg: GameConfig, now_ms: int) -> None:
        pts = list(state.snake)
        if not pts: return

        L = len(pts)
        centers = [self._cell_center(p) for p in pts]
        base_r = max(6, self.cell_px // 2 - 5)

        # Paleta de color según modo
        golden = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)
        extasis = (state.mode == SnakeMode.EXTASIS and state.mode_until_ms > now_ms)
        wrap_mode = not cfg.wall_collision

        # 1) Calcular radios con adelgazamiento cónico del último 15% (cola)
        taper_len = max(3, int(L * 0.15))
        radii: List[float] = []
        for i in range(L):
            if i == 0:
                radii.append(base_r + 3.0)  # Cabeza más ancha
            elif i >= L - taper_len:
                idx_tail = L - 1 - i  # 0 en la punta de la cola
                factor = 0.35 + 0.65 * (idx_tail / taper_len)
                radii.append(max(3.0, base_r * factor))
            else:
                radii.append(base_r)

        # 2) Sombra proyectada del cuerpo
        for i in range(L - 1):
            if wrap_mode and (abs(pts[i].x - pts[i+1].x) > 1 or abs(pts[i].y - pts[i+1].y) > 1):
                continue
            c1 = (centers[i][0] + 2, centers[i][1] + 3)
            c2 = (centers[i+1][0] + 2, centers[i+1][1] + 3)
            pygame.draw.line(surface, (10, 10, 13), c1, c2, int(radii[i] * 2 + 4))

        # 3) Dibujar segmentos tubulares conectados
        for i in range(L - 1, -1, -1):
            c = centers[i]
            r = radii[i]

            # Color del segmento
            if golden:
                col = (255, 215, 75) if i == 0 else (220, 175, 45)
            elif extasis:
                phase = ((state.tick * 0.18) + i * 0.08) % 1.0
                col = self._hsv_to_rgb(phase, 0.95, 1.0)
            elif wrap_mode:
                col = (210, 130, 255) if i == 0 else (160, 65, 230)
            else:
                h_col, b_col = self.snake_palettes[state.snake_color_index % len(self.snake_palettes)]
                col = h_col if i == 0 else b_col

            # Conector entre nodos
            if i < L - 1:
                nxt_c = centers[i + 1]
                if not (wrap_mode and (abs(pts[i].x - pts[i+1].x) > 1 or abs(pts[i].y - pts[i+1].y) > 1)):
                    pygame.draw.line(surface, col, c, nxt_c, int(r * 2))

            pygame.draw.circle(surface, col, c, int(r))

        # 4) Rostro vivo en la cabeza
        self._draw_live_head(surface, state, centers[0], radii[0], cfg)

    def _draw_live_head(self, surface: pygame.Surface, state: GameState, c: Tuple[int, int], r: float, cfg: GameConfig) -> None:
        cx, cy = c
        d = state.direction
        head_p = state.snake[0]

        # Posiciones de las cuencas oculares
        if d == Direction.UP:
            eye1 = (cx - r * 0.45, cy - r * 0.3)
            eye2 = (cx + r * 0.45, cy - r * 0.3)
            snout = (cx, cy - r * 0.9)
            tongue_end = (cx, cy - r * 1.7)
        elif d == Direction.DOWN:
            eye1 = (cx - r * 0.45, cy + r * 0.3)
            eye2 = (cx + r * 0.45, cy + r * 0.3)
            snout = (cx, cy + r * 0.9)
            tongue_end = (cx, cy + r * 1.7)
        elif d == Direction.LEFT:
            eye1 = (cx - r * 0.3, cy - r * 0.45)
            eye2 = (cx - r * 0.3, cy + r * 0.45)
            snout = (cx - r * 0.9, cy)
            tongue_end = (cx - r * 1.7, cy)
        else: # RIGHT
            eye1 = (cx + r * 0.3, cy - r * 0.45)
            eye2 = (cx + r * 0.3, cy + r * 0.45)
            snout = (cx + r * 0.9, cy)
            tongue_end = (cx + r * 1.7, cy)

        # Lengua bífida animada
        if state.tongue_timer > 0:
            pygame.draw.line(surface, (230, 40, 50), snout, tongue_end, 2)
            # Bifurcación en la punta
            tx, ty = tongue_end
            if d in (Direction.UP, Direction.DOWN):
                pygame.draw.line(surface, (230, 40, 50), (tx, ty), (tx - 3, ty + (-3 if d == Direction.UP else 3)), 2)
                pygame.draw.line(surface, (230, 40, 50), (tx, ty), (tx + 3, ty + (-3 if d == Direction.UP else 3)), 2)
            else:
                pygame.draw.line(surface, (230, 40, 50), (tx, ty), (tx + (-3 if d == Direction.LEFT else 3), ty - 3), 2)
                pygame.draw.line(surface, (230, 40, 50), (tx, ty), (tx + (-3 if d == Direction.LEFT else 3), ty + 3), 2)

        # Ojos (Esclerótica blanca + Pupilas dinámicas)
        is_blinking = (state.blink_timer > 0)
        eye_r = max(2.5, r * 0.32)

        # Calcular vector hacia la comida más cercana para orientar pupilas
        target_food = min(state.foods, key=lambda f: dist_for_config(head_p, f.pos, cfg)).pos if state.foods else None
        p_dx, p_dy = 0.0, 0.0
        if target_food:
            vx = target_food.x - head_p.x
            vy = target_food.y - head_p.y
            dist_v = math.hypot(vx, vy)
            if dist_v > 0.01:
                p_dx = (vx / dist_v) * (eye_r * 0.4)
                p_dy = (vy / dist_v) * (eye_r * 0.4)

        for e in (eye1, eye2):
            ex, ey = int(e[0]), int(e[1])
            if is_blinking:
                # Ojo cerrado (hendidura)
                pygame.draw.line(surface, (25, 25, 30), (ex - eye_r, ey), (ex + eye_r, ey), 2)
            else:
                pygame.draw.circle(surface, (250, 250, 250), (ex, ey), int(eye_r))
                # Pupila negra mirando a la manzana
                pupil_x = int(ex + p_dx)
                pupil_y = int(ey + p_dy)
                pygame.draw.circle(surface, (18, 18, 22), (pupil_x, pupil_y), max(2, int(eye_r * 0.55)))
                # Brillo blanco especular en la pupila
                pygame.draw.circle(surface, (255, 255, 255), (pupil_x - 1, pupil_y - 1), 1)

    def _draw_food(self, surface: pygame.Surface, f: Food, cfg: GameConfig, state: GameState, now_ms: int) -> None:
        cx, cy = self._cell_center(f.pos)
        golden = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)

        if golden or not f.respawn:
            # Manzana Dorada o Baya Especial con Aura Pulsante
            pulse = math.sin(state.tick * 0.16) * 3.0
            r_glow = max(8, self.cell_px // 2 - 4 + pulse)
            glow_col = (255, 220, 90) if golden else (220, 140, 255)
            pygame.draw.circle(surface, glow_col, (cx, cy), int(r_glow), width=2)
            pygame.draw.circle(surface, (255, 235, 120) if golden else (200, 110, 245), (cx, cy), max(5, self.cell_px // 2 - 6))
            pygame.draw.circle(surface, (255, 255, 200), (cx - 2, cy - 2), 2)
        else:
            # Manzana Clásica con Volumen y Brillo Especular
            r = max(6, self.cell_px // 2 - 6)
            # Sombra base
            pygame.draw.circle(surface, (15, 15, 18), (cx + 1, cy + 2), r)
            # Cuerpo esférico con degradado simulado
            pygame.draw.circle(surface, (195, 35, 40), (cx, cy), r)
            pygame.draw.circle(surface, (235, 65, 70), (cx - 1, cy - 1), max(3, r - 3))
            # Brillo superior blanco
            pygame.draw.circle(surface, (255, 190, 195), (cx - r // 2, cy - r // 2), max(2, r // 4))
            # Tallo café y hoja verde con relieve
            pygame.draw.rect(surface, (110, 70, 40), pygame.Rect(cx - 1, cy - r - 4, 3, 6), border_radius=1)
            leaf = [(cx + 1, cy - r - 2), (cx + r // 2 + 5, cy - r - 6), (cx + r // 2, cy - r + 3)]
            pygame.draw.polygon(surface, (60, 190, 80), leaf)

    def _draw_bomb(self, surface: pygame.Surface, p: Point, exp_ms: int, now_ms: int, cfg: GameConfig, state: GameState) -> None:
        cx, cy = self._cell_center(p)
        golden = (state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms)
        r = max(6, self.cell_px // 2 - 7)

        if golden:
            # En modo golden son esferas doradas devorables
            pygame.draw.circle(surface, (255, 210, 80), (cx, cy), r)
            pygame.draw.circle(surface, (255, 245, 160), (cx - 2, cy - 2), max(2, r // 3))
            return

        # Sombra
        pygame.draw.circle(surface, (12, 12, 15), (cx + 2, cy + 3), r)
        # Cuerpo negro grafito
        pygame.draw.circle(surface, (45, 45, 55), (cx, cy), r)
        pygame.draw.circle(surface, (75, 75, 90), (cx - 2, cy - 2), max(2, r // 3))

        # Mecha chisporroteante
        tleft = max(0, exp_ms - now_ms)
        blink = (tleft // 150) % 2 == 0
        spark_col = (255, 220, 60) if blink else (255, 100, 30)

        pygame.draw.line(surface, (150, 120, 80), (cx + r * 0.4, cy - r * 0.4), (cx + r + 5, cy - r - 5), 2)
        pygame.draw.circle(surface, spark_col, (int(cx + r + 5), int(cy - r - 5)), 4)
        pygame.draw.circle(surface, (255, 255, 255), (int(cx + r + 5), int(cy - r - 5)), 1)

    def _draw_nuclear(self, surface: pygame.Surface, nuke: NuclearStrike, cfg: GameConfig, now_ms: int) -> None:
        # 1) Celdas con anillos de fuego / ceniza / carbón
        for pt, (fase, _) in nuke.affected_cells.items():
            cx, cy = self._cell_center(pt)
            rect = pygame.Rect(cx - self.cell_px // 2, cy - self.cell_px // 2, self.cell_px, self.cell_px)
            if fase == "HOT":
                col = (255, 160, 30, 180)
                pygame.draw.rect(surface, (240, 140, 20), rect)
            elif fase == "ASH":
                pygame.draw.rect(surface, (110, 105, 115), rect)
            else: # CHAR
                pygame.draw.rect(surface, (35, 35, 40), rect)

        # 2) Ojiva cayendo verticalmente
        if nuke.state == "FALLING":
            cx, _ = self._cell_center(nuke.center)
            cy = int(nuke.fall_y)
            # Misil / Ojiva
            pygame.draw.rect(surface, (210, 40, 40), pygame.Rect(cx - 5, cy - 14, 10, 20), border_radius=4)
            # Estela de fuego
            pygame.draw.line(surface, (255, 200, 50), (cx, cy - 14), (cx, cy - 35), 4)
        elif nuke.state == "ARMED":
            # Parpadeo de bomba nuclear armada en el centro
            cx, cy = self._cell_center(nuke.center)
            blink = (now_ms // 120) % 2 == 0
            col = (255, 30, 30) if blink else (80, 20, 20)
            pygame.draw.circle(surface, col, (cx, cy), self.cell_px // 2, width=3)
            pygame.draw.circle(surface, (255, 220, 50), (cx, cy), 6)

    def _update_and_draw_particles(self, surface: pygame.Surface, state: GameState) -> None:
        alive_p: List[VisualParticle] = []
        for p in state.particles:
            p.x += p.vx
            p.y += p.vy
            p.life_ms -= 16
            if p.life_ms > 0:
                alpha_factor = p.life_ms / p.max_life_ms
                r = max(1.0, p.radius * alpha_factor)
                pygame.draw.circle(surface, p.color, (int(p.x), int(p.y)), int(r))
                alive_p.append(p)
        state.particles = alive_p

    def _draw_center_badge(self, surface: pygame.Surface, txt: str, col: Tuple[int, int, int]) -> None:
        assert self.font_main is not None
        img = self.font_main.render(txt, True, col)
        rect = img.get_rect(center=(surface.get_width() // 2, surface.get_height() // 2))
        bg = rect.inflate(24, 14)
        pygame.draw.rect(surface, (18, 18, 24), bg, border_radius=8)
        pygame.draw.rect(surface, col, bg, width=2, border_radius=8)
        surface.blit(img, rect)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> Tuple[int, int, int]:
        i = int(h * 6.0)
        f = (h * 6.0) - i
        p = v * (1.0 - s)
        q = v * (1.0 - f * s)
        t = v * (1.0 - (1.0 - f) * s)
        i = i % 6
        if i == 0: r, g, b = v, t, p
        elif i == 1: r, g, b = q, v, p
        elif i == 2: r, g, b = p, v, t
        elif i == 3: r, g, b = p, q, v
        elif i == 4: r, g, b = t, p, v
        else: r, g, b = v, p, q
        return int(r * 255), int(g * 255), int(b * 255)

# ============================================================
# Receptor UDP y Controladores de Entrada
# ============================================================

class UDPReceiver:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.is_bound = False
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.host, self.port))
            self.sock.setblocking(False)
            self.is_bound = True
        except OSError:
            self.is_bound = False

    def poll(self, bus: EventBus) -> None:
        if not self.is_bound: return
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
                msg = json.loads(data.decode("utf-8"))
                if isinstance(msg, dict):
                    t = str(msg.get("type", "")).strip()
                    payload = msg.get("payload", {})
                    if t: bus.emit(GameEvent(t, payload if isinstance(payload, dict) else {}))
            except (BlockingIOError, Exception):
                break

class ExternalInputController:
    def __init__(self, bus: EventBus):
        self.bus = bus

    def handle_keydown(self, key: int) -> None:
        if key == pygame.K_j: self.bus.emit(GameEvent("SLOW_DOWN", {"delta": 1}))
        elif key == pygame.K_l: self.bus.emit(GameEvent("SPEED_UP", {"delta": 1}))
        elif key == pygame.K_k: self.bus.emit(GameEvent("PAUSE_TOGGLE"))
        elif key == pygame.K_x: self.bus.emit(GameEvent("SPAWN_BOMB"))
        elif key == pygame.K_z: self.bus.emit(GameEvent("SPAWN_EXTRA_FOOD"))
        elif key == pygame.K_c: self.bus.emit(GameEvent("SNAKE_COLOR_CYCLE"))
        elif key == pygame.K_w: self.bus.emit(GameEvent("WRAP_TOGGLE"))
        elif key == pygame.K_e: self.bus.emit(GameEvent("EXTASIS"))
        elif key == pygame.K_g: self.bus.emit(GameEvent("GOLDEN_MODE"))
        elif key == pygame.K_b: self.bus.emit(GameEvent("SPAWN_NUCLEAR_BOMB"))

# ============================================================
# Escenas y Aplicación Principal
# ============================================================

class Scene(Protocol):
    def handle(self, events: List[pygame.event.Event]) -> Optional["Scene"]: ...
    def render(self, surface: pygame.Surface, now_ms: int) -> None: ...

class MenuScene:
    def __init__(self, app: "App"):
        self.app = app
        self.idx = 0
        self.items = [("Play Manual (Keyboard)", "kbd"), ("Watch Autonomous Bot", "bot"), ("Quit", "quit")]
        self.font: Optional[pygame.font.Font] = None

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                return None
            if e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_UP, pygame.K_w): self.idx = (self.idx - 1) % len(self.items)
                elif e.key in (pygame.K_DOWN, pygame.K_s): self.idx = (self.idx + 1) % len(self.items)
                elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    tag = self.items[self.idx][1]
                    if tag == "quit": return None
                    return PlayScene(self.app, bot_mode=(tag == "bot"))
        return self

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if self.font is None: self.font = pygame.font.SysFont("consolas", 22)
        surface.fill((12, 12, 15))
        title = pygame.font.SysFont("consolas", 28, bold=True).render("SNAKE BOT & COLOSSEUM v1.21", True, (240, 240, 240))
        surface.blit(title, (24, 24))
        y = 110
        for i, (label, _) in enumerate(self.items):
            sel = (i == self.idx)
            col = (255, 215, 80) if sel else (180, 180, 190)
            surface.blit(self.font.render(("> " if sel else "  ") + label, True, col), (24, y))
            y += 40

class PlayScene:
    def __init__(self, app: "App", bot_mode: bool):
        self.app = app
        self.bot_mode = bot_mode
        self.state = self.app.new_game_state()
        self.kbd_dir = self.state.direction

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE: return MenuScene(self.app)
                if e.key == pygame.K_r: self.state = self.app.new_game_state()
                self.app.input.handle_keydown(e.key)
                if not self.bot_mode:
                    mapping = {pygame.K_UP: Direction.UP, pygame.K_DOWN: Direction.DOWN,
                               pygame.K_LEFT: Direction.LEFT, pygame.K_RIGHT: Direction.RIGHT}
                    if e.key in mapping:
                        cand = mapping[e.key]
                        if cand.dx + self.kbd_dir.dx != 0 or cand.dy + self.kbd_dir.dy != 0:
                            self.kbd_dir = cand
        return self

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        pat_display = self.app.current_pattern_display(self.state)
        eff_fps = self.app.effective_fps(self.state, now_ms)
        self.app.renderer.render(surface, self.state, self.app.cfg, now_ms, pat_display, eff_fps)

class App:
    def __init__(self):
        self.rng = random.Random()
        self.cfg = GameConfig(n=GRID_SIZE, wall_collision=WALL_COLLISION_DEFAULT, fps_base=INITIAL_FPS)
        self.renderer = Renderer(cell_px=32, margin_px=16, hud_h=56)
        self.event_bus = EventBus()
        self.input = ExternalInputController(self.event_bus)
        self.udp = UDPReceiver(UDP_HOST, UDP_PORT)
        self.rules = SnakeRules(self.rng)
        self.actions = ActionSystem(self)
        self._pending_reset = False

        cycle = build_hamilton_cycle(self.cfg.n)
        self.patterns: List[Pattern] = [
            SpiralPattern(), PerimeterPattern(), ZigZagPattern(),
            DiagonalPattern(), SmoothRandomPattern(), HamiltonPattern(cycle)
        ]
        self.bot = BotController(self.rng, self.patterns)

    def current_pattern_display(self, state: GameState) -> str:
        return "Caza Directa" if state.pattern_stage == 0 else self.patterns[self.bot.current_idx].display

    def effective_fps(self, state: GameState, now_ms: int) -> int:
        mult = 1.0
        if state.mode == SnakeMode.EXTASIS and state.mode_until_ms > now_ms: mult = 2.0
        elif state.mode == SnakeMode.GOLDEN and state.mode_until_ms > now_ms: mult = 3.0
        return max(1, min(60, int(self.cfg.fps_base * mult)))

    def new_game_state(self) -> GameState:
        cx, cy = self.cfg.n // 2, self.cfg.n // 2
        snake = deque([Point(cx - i, cy) for i in range(INITIAL_SNAKE_LENGTH)])
        state = GameState(
            snake=snake, direction=Direction.RIGHT, foods=[], bombs={}, alive=True, score=0,
            snake_color_index=self.rng.randrange(0, 8), tick=0, head_history=deque(maxlen=180),
            cycle_penalty_until=0, grow_pending=0, paused=False, mode=SnakeMode.NORMAL,
            mode_until_ms=0, last_donor="Esperando Donación", pattern_stage=0
        )
        for _ in range(INITIAL_FOODS):
            p = random_free_cell(state, self.cfg, self.rng)
            if p: state.foods.append(Food(pos=p, respawn=True))
        state.head_history.append(state.snake[0])
        return state

    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption("Snake — Bot Focused (v1.21)")
        surface = pygame.display.set_mode(self.renderer.window_size(self.cfg.n))
        clock = pygame.time.Clock()
        scene: Optional[Scene] = MenuScene(self)

        while scene is not None:
            now_ms = pygame.time.get_ticks()
            events = pygame.event.get()
            scene = scene.handle(events)
            if scene is None: break

            self.udp.poll(self.event_bus)

            if isinstance(scene, PlayScene):
                drained = self.event_bus.drain()
                if drained:
                    self.actions.dispatch(drained, scene.state, self.cfg, self.rng, now_ms)
                if self._pending_reset:
                    scene.state = self.new_game_state()
                    self._pending_reset = False

                if scene.state.alive and not scene.state.paused:
                    if scene.bot_mode:
                        scene.state.direction = self.bot.choose_direction(scene.state, self.cfg, now_ms)
                    else:
                        scene.state.direction = scene.kbd_dir
                    self.rules.step(scene.state, self.cfg, now_ms)

            scene.render(surface, now_ms)
            pygame.display.flip()

            fps = self.effective_fps(scene.state, now_ms) if isinstance(scene, PlayScene) else self.cfg.fps_base
            clock.tick(fps)

        pygame.quit()

def main():
    print("==================================================")
    print(" Snake Bot Focused v1.21 — Organic & Cinematic Leap")
    print(f" UDP Listening: {UDP_HOST}:{UDP_PORT}")
    print("==================================================")
    App().run()

if __name__ == "__main__":
    main()
