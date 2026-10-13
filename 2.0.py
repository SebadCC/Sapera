# Snake — The Colosseum & SaperaAI — Version 2.0 (Ultimate Edition — Safe Logic & Clean UI)
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
# CONFIGURACIÓN GENERAL Y DIMENSIONES
# ============================================================

GRID_SIZE = 22                  # 22x22 casillas
CELL_PX = 28                    # 22 * 28 = 616 px de tablero
MARGIN_PX = 16                  # 16 px a cada lado -> Ancho total = 616 + 32 = 648 px
HUD_HEIGHT = 56                 # HUD limpio, proporcional y compacto

INITIAL_SNAKE_LENGTH = 5
BOMB_DURATION_MS = 5000
INITIAL_FPS = 12

UDP_HOST = "127.0.0.1"
UDP_PORT = 8765

EXTASIS_DURATION_MS = 8_000
GOLDEN_DURATION_MS = 6_000
WRAP_EVENT_DURATION_MS = 7_000

# ============================================================
# Modos de Juego
# ============================================================

class GameMode(Enum):
    BATTLE_ROYALE = "BATTLE_ROYALE" # 4 Serpientes
    DUEL_1V1 = "DUEL_1V1"           # 2 Serpientes
    HYPNOTIC = "HYPNOTIC"           # 1 Serpiente Espectáculo
    SPEEDRUN = "SPEEDRUN"           # 1 Serpiente Caza Rápida

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
    def dx(self) -> int: return self.value[0]
    @property
    def dy(self) -> int: return self.value[1]

DIRS: Tuple[Direction, ...] = (Direction.UP, Direction.DOWN, Direction.LEFT, Direction.RIGHT)

def in_bounds(p: Point, n: int) -> bool: return 0 <= p.x < n and 0 <= p.y < n
def wrap(p: Point, n: int) -> Point: return Point(p.x % n, p.y % n)

def manhattan_plane(a: Point, b: Point) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)

def manhattan_toroidal(a: Point, b: Point, n: int) -> int:
    dx = abs(a.x - b.x)
    dy = abs(a.y - b.y)
    return min(dx, n - dx) + min(dy, n - dy)

def dist_for_config(a: Point, b: Point, wall_col: bool, n: int) -> int:
    return manhattan_plane(a, b) if wall_col else manhattan_toroidal(a, b, n)

def layer_index(p: Point, n: int) -> int:
    return min(p.x, p.y, n - 1 - p.x, n - 1 - p.y)

def dir_from_to(a: Point, b: Point) -> Direction:
    dx, dy = b.x - a.x, b.y - a.y
    if dx == 1 and dy == 0: return Direction.RIGHT
    if dx == -1 and dy == 0: return Direction.LEFT
    if dx == 0 and dy == 1: return Direction.DOWN
    return Direction.UP

# ============================================================
# Partículas y Bomba Nuclear 3D
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
    state: str                 # "FALLING", "IMPACT_FLASH", "EXPLODING", "FINISHED"
    start_ms: int
    fall_y: float = -140.0
    impact_flash_ms: int = 0
    rings_expanded: int = 0
    max_rings: int = 15
    ring_next_ms: int = 0
    affected_cells: Dict[Point, Tuple[str, int]] = field(default_factory=dict)

# ============================================================
# Facciones del Coliseo
# ============================================================

class FactionId(Enum):
    RED = "RED"       # Fénix Carmesí
    GREEN = "GREEN"   # Cobra Esmeralda
    BLUE = "BLUE"     # Dragón Zafiro
    PURPLE = "PURPLE" # Víbora Amatista
    GOLD = "GOLD"     # Basilisco Ámbar / Titán Dorado

@dataclass(slots=True)
class FactionConfig:
    faction_id: FactionId
    name: str
    tag: str
    head_color: Tuple[int, int, int]
    body_color: Tuple[int, int, int]
    personality_title: str
    pattern_weight: float
    food_weight: float
    risk_tolerance: float
    tail_avoid_factor: float
    preferred_center_layer: bool = False

FACTION_CONFIGS: Dict[FactionId, FactionConfig] = {
    FactionId.RED: FactionConfig(
        faction_id=FactionId.RED,
        name="Fénix Carmesí",
        tag="#Rojo",
        head_color=(255, 80, 80),
        body_color=(215, 40, 45),
        personality_title="Voraz",
        pattern_weight=0.17,
        food_weight=2.71,
        risk_tolerance=0.85,
        tail_avoid_factor=1.46
    ),
    FactionId.GREEN: FactionConfig(
        faction_id=FactionId.GREEN,
        name="Cobra Esmeralda",
        tag="#Verde",
        head_color=(90, 240, 130),
        body_color=(45, 180, 90),
        personality_title="Zen",
        pattern_weight=1.40,
        food_weight=1.20,
        risk_tolerance=0.05,
        tail_avoid_factor=2.45
    ),
    FactionId.BLUE: FactionConfig(
        faction_id=FactionId.BLUE,
        name="Dragón Zafiro",
        tag="#Azul",
        head_color=(95, 195, 255),
        body_color=(45, 130, 230),
        personality_title="Territorial",
        pattern_weight=0.80,
        food_weight=0.60,
        risk_tolerance=0.30,
        tail_avoid_factor=1.56,
        preferred_center_layer=True
    ),
    FactionId.PURPLE: FactionConfig(
        faction_id=FactionId.PURPLE,
        name="Víbora Amatista",
        tag="#Morado",
        head_color=(220, 135, 255),
        body_color=(165, 70, 225),
        personality_title="Mística",
        pattern_weight=1.25,
        food_weight=1.02,
        risk_tolerance=0.60,
        tail_avoid_factor=0.55
    ),
    FactionId.GOLD: FactionConfig(
        faction_id=FactionId.GOLD,
        name="Basilisco Ámbar",
        tag="#Dorado",
        head_color=(255, 215, 60),
        body_color=(218, 165, 32),
        personality_title="Táctico",
        pattern_weight=1.10,
        food_weight=1.20,
        risk_tolerance=0.40,
        tail_avoid_factor=1.80,
        preferred_center_layer=True
    )
}

FACTION_TACTICAL_DESCS: Dict[FactionId, str] = {
    FactionId.RED: "Caza voraz de comida a máxima velocidad y presión frontal.",
    FactionId.GREEN: "Supervivencia zen: evasión geométrica perimetral y cero riesgo.",
    FactionId.BLUE: "Control territorial en espirales concéntricas y asfixia interna.",
    FactionId.PURPLE: "Víbora mística: patrones impredecibles, zigzag y riesgo audaz.",
    FactionId.GOLD: "Depredador táctico: emboscadas, centro y trampas de doble olla."
}


# ============================================================
# Agente Serpiente
# ============================================================

class SnakeMode(Enum):
    NORMAL = "NORMAL"
    EXTASIS = "EXTASIS"
    GOLDEN = "GOLDEN"

@dataclass
class ColosseumSnake:
    snake_id: int
    faction: FactionConfig
    body: Deque[Point]
    direction: Direction
    alive: bool = True
    score: int = 0
    wins: int = 0
    grow_pending: int = 0
    mode: SnakeMode = SnakeMode.NORMAL
    mode_until_ms: int = 0
    
    # Expresiones visuales
    blink_timer: int = 0
    tongue_timer: int = 0
    head_history: Deque[Point] = field(default_factory=lambda: deque(maxlen=160))
    cycle_penalty_until: int = 0
    pattern_idx: int = 0
    last_switch_tick: int = 0

@dataclass(slots=True)
class Food:
    pos: Point
    value: int = 1

# ============================================================
# Patrones Geométricos
# ============================================================

class Pattern(Protocol):
    name: str
    display: str
    def preferred_direction(self, head: Point, cur_dir: Direction, n: int, wall_col: bool, tick: int, rng: random.Random) -> Direction: ...

class SpiralPattern:
    name = "spiral"
    display = "Espiral"
    def preferred_direction(self, head: Point, cur_dir: Direction, n: int, wall_col: bool, tick: int, rng: random.Random) -> Direction:
        cur_lyr = layer_index(head, n)
        best, best_score = cur_dir, -1e9
        for d in DIRS:
            nxt = Point(head.x + d.dx, head.y + d.dy)
            if wall_col and not in_bounds(nxt, n): continue
            nxt = wrap(nxt, n)
            score = (cur_lyr - layer_index(nxt, n)) * 3.0 + (1.0 if d == cur_dir else 0.0) * 0.7 + rng.uniform(-0.05, 0.05)
            if score > best_score: best_score, best = score, d
        return best

class PerimeterPattern:
    name = "perimeter"
    display = "Perímetro"
    def preferred_direction(self, head: Point, cur_dir: Direction, n: int, wall_col: bool, tick: int, rng: random.Random) -> Direction:
        best, best_score = cur_dir, -1e9
        for d in DIRS:
            nxt = Point(head.x + d.dx, head.y + d.dy)
            if wall_col and not in_bounds(nxt, n): continue
            nxt = wrap(nxt, n)
            score = -(layer_index(nxt, n) * 2.2) + (1.0 if d == cur_dir else 0.0) * 0.6 + rng.uniform(-0.05, 0.05)
            if score > best_score: best_score, best = score, d
        return best

class ZigZagPattern:
    name = "zigzag"
    display = "ZigZag"
    def preferred_direction(self, head: Point, cur_dir: Direction, n: int, wall_col: bool, tick: int, rng: random.Random) -> Direction:
        if (tick // 22) % 2 == 0:
            return Direction.RIGHT if head.x < n - 1 else Direction.LEFT
        return Direction.DOWN if head.y < n - 1 else Direction.UP

class SmoothFlowPattern:
    name = "smooth"
    display = "Flujo Suave"
    def preferred_direction(self, head: Point, cur_dir: Direction, n: int, wall_col: bool, tick: int, rng: random.Random) -> Direction:
        if rng.random() < 0.88: return cur_dir
        turns = {Direction.UP: [Direction.LEFT, Direction.RIGHT], Direction.DOWN: [Direction.LEFT, Direction.RIGHT],
                 Direction.LEFT: [Direction.UP, Direction.DOWN], Direction.RIGHT: [Direction.UP, Direction.DOWN]}
        return rng.choice(turns[cur_dir])

# ============================================================
# Configuración Personalizada de Partida y Estado Global
# ============================================================

@dataclass
class ColosseumMatchSetup:
    grid_size: int = 22
    factions: List[FactionId] = field(default_factory=lambda: [FactionId.RED, FactionId.GREEN, FactionId.BLUE, FactionId.PURPLE])

@dataclass
class ColosseumState:
    game_mode: GameMode
    snakes: List[ColosseumSnake]
    foods: List[Food]
    bombs: Dict[Point, int]
    grid_size: int = GRID_SIZE
    cell_px: int = CELL_PX
    tick: int = 0
    round_number: int = 1
    round_winner: Optional[str] = None
    round_reset_ms: int = 0
    paused: bool = False
    
    wall_collision: bool = True
    wrap_mode_until_ms: int = 0
    
    fps_base: int = INITIAL_FPS
    last_donor: str = "Esperando Donación"
    last_udp_ms: int = 0
    particles: List[VisualParticle] = field(default_factory=list)
    nuclear: Optional[NuclearStrike] = None
    
    countdown_active: bool = True
    countdown_start_ms: int = 0


# ============================================================
# EventBus y Acciones
# ============================================================

@dataclass(frozen=True, slots=True)
class GameEvent:
    type: str
    payload: Dict[str, Any] | None = None

class EventBus:
    def __init__(self): self._q: Deque[GameEvent] = deque()
    def emit(self, ev: GameEvent) -> None: self._q.append(ev)
    def drain(self) -> List[GameEvent]:
        out = []
        while self._q: out.append(self._q.popleft())
        return out

class ActionSystem:
    def __init__(self, app: "ColosseumApp"):
        self.app = app

    def dispatch(self, events: List[GameEvent], state: ColosseumState, now_ms: int) -> None:
        for ev in events:
            t = ev.type
            payload = ev.payload or {}
            donor = payload.get("donor") or payload.get("sender") or payload.get("user")
            if donor: state.last_donor = str(donor).strip()
            state.last_udp_ms = now_ms

            if t == "PING": pass
            elif t == "SPAWN_BOMB":
                count = max(1, int(payload.get("count", 1)))
                ttl = max(1000, int(payload.get("ttl_ms", BOMB_DURATION_MS)))
                for _ in range(count):
                    p = self.app.random_free_cell(state)
                    if p: state.bombs[p] = now_ms + ttl
            elif t == "SPAWN_EXTRA_FOOD":
                count = max(1, int(payload.get("count", 2)))
                for _ in range(count):
                    p = self.app.random_free_cell(state)
                    if p: state.foods.append(Food(pos=p, value=1))
            elif t == "SPEED_UP":
                state.fps_base = min(60, state.fps_base + int(payload.get("delta", 2)))
            elif t == "SLOW_DOWN":
                state.fps_base = max(4, state.fps_base - int(payload.get("delta", 2)))
            elif t in ("RESET_GAME", "RESTART"):
                self.app.reset_round(state, hard=True, now_ms=now_ms)
            elif t in ("TOGGLE_WALL_MODE", "WRAP_TOGGLE", "ACTIVATE_WRAP"):
                state.wall_collision = False
                state.wrap_mode_until_ms = now_ms + WRAP_EVENT_DURATION_MS
            elif t == "PAUSE_TOGGLE":
                state.paused = not state.paused
            elif t in ("EXTASIS", "ACTIVATE_EXTASIS"):
                target_f = str(payload.get("faction", "")).upper()
                for s in state.snakes:
                    if not target_f or s.faction.faction_id.value == target_f:
                        s.mode = SnakeMode.EXTASIS
                        s.mode_until_ms = now_ms + EXTASIS_DURATION_MS
            elif t in ("GOLDEN_MODE", "ACTIVATE_GOLDEN"):
                target_f = str(payload.get("faction", "")).upper()
                for s in state.snakes:
                    if not target_f or s.faction.faction_id.value == target_f:
                        s.mode = SnakeMode.GOLDEN
                        s.mode_until_ms = now_ms + GOLDEN_DURATION_MS
            elif t == "SPAWN_NUCLEAR_BOMB":
                if state.nuclear is None or state.nuclear.state == "FINISHED":
                    center = Point(state.grid_size // 2, state.grid_size // 2)
                    state.nuclear = NuclearStrike(center=center, state="FALLING", start_ms=now_ms, fall_y=-140.0)

# ============================================================
# Reglas Físicas y Mecánicas
# ============================================================

class ColosseumRules:
    def __init__(self, rng: random.Random):
        self.rng = rng

    def step(self, state: ColosseumState, now_ms: int) -> None:
        if state.paused or state.countdown_active: return

        # Expiración del modo Trascendente (Wrap)
        if not state.wall_collision and state.wrap_mode_until_ms > 0:
            if now_ms >= state.wrap_mode_until_ms:
                state.wall_collision = True
                state.wrap_mode_until_ms = 0

        # Verificación de fin de ronda
        alive_snakes = [s for s in state.snakes if s.alive]
        total_snakes = len(state.snakes)

        if total_snakes > 1 and len(alive_snakes) <= 1 and state.round_winner is None:
            if len(alive_snakes) == 1:
                winner = alive_snakes[0]
                winner.wins += 1
                state.round_winner = f"¡{winner.faction.name.upper()} GANA!"
            else:
                state.round_winner = "¡EMPATE TOTAL!"
            state.round_reset_ms = now_ms + 3500

        if total_snakes == 1 and not alive_snakes and state.round_winner is None:
            state.round_winner = "FIN DE PARTIDA"
            state.round_reset_ms = now_ms + 3000

        if state.round_winner and now_ms >= state.round_reset_ms:
            self.reset_round(state, now_ms)
            return

        # Expiración de bombas
        if state.bombs:
            expired = [p for p, exp in state.bombs.items() if exp <= now_ms]
            for p in expired:
                state.bombs.pop(p, None)
                self._spawn_explosion(state, p, count=16)

        self._update_nuclear(state, now_ms)

        # 1. Proyectar pasos
        projections: Dict[int, Optional[Point]] = {}
        for s in state.snakes:
            if not s.alive: continue
            if s.mode != SnakeMode.NORMAL and now_ms >= s.mode_until_ms:
                s.mode = SnakeMode.NORMAL
                s.mode_until_ms = 0

            cand = Point(s.body[0].x + s.direction.dx, s.body[0].y + s.direction.dy)
            if state.wall_collision:
                projections[s.snake_id] = cand if in_bounds(cand, state.grid_size) else None
            else:
                projections[s.snake_id] = wrap(cand, state.grid_size)


        # 2. Impacto con paredes
        for s in state.snakes:
            if not s.alive: continue
            if projections[s.snake_id] is None:
                s.alive = False
                self._spawn_death_debris(state, s)

        # 3. Bombas y explosiones
        for s in state.snakes:
            if not s.alive: continue
            nxt = projections[s.snake_id]
            if not nxt: continue
            golden = (s.mode == SnakeMode.GOLDEN and s.mode_until_ms > now_ms)

            if state.nuclear and nxt in state.nuclear.affected_cells:
                fase, _ = state.nuclear.affected_cells[nxt]
                if fase in ("HOT", "ASH") and not golden:
                    s.alive = False
                    self._spawn_death_debris(state, s)
                    continue

            if nxt in state.bombs:
                if golden:
                    state.bombs.pop(nxt, None)
                    s.score += 2
                    s.grow_pending += 1
                else:
                    s.alive = False
                    self._spawn_death_debris(state, s)
                    self._spawn_explosion(state, nxt, count=22)
                    continue

        # 4. Choque frontal cabeza con cabeza
        heads_target: Dict[Point, List[ColosseumSnake]] = {}
        for s in state.snakes:
            if s.alive and projections[s.snake_id]:
                heads_target.setdefault(projections[s.snake_id], []).append(s)

        for pt, snk_list in heads_target.items():
            if len(snk_list) > 1:
                for s in snk_list:
                    if s.mode != SnakeMode.GOLDEN:
                        s.alive = False
                        self._spawn_death_debris(state, s)

        # 5. Choque con cuerpos
        for s in state.snakes:
            if not s.alive: continue
            nxt = projections[s.snake_id]
            if not nxt: continue
            golden = (s.mode == SnakeMode.GOLDEN and s.mode_until_ms > now_ms)
            if golden: continue

            for other in state.snakes:
                body_list = list(other.body)
                if other.snake_id == s.snake_id and s.grow_pending == 0:
                    body_set = set(body_list[:-1])
                else:
                    body_set = set(body_list)

                if nxt in body_set:
                    s.alive = False
                    self._spawn_death_debris(state, s)
                    break

        # 6. Mover serpientes supervivientes
        for s in state.snakes:
            if not s.alive: continue
            nxt = projections[s.snake_id]
            if not nxt: continue

            eaten_idx = next((i for i, f in enumerate(state.foods) if f.pos == nxt), -1)
            if eaten_idx != -1:
                food = state.foods.pop(eaten_idx)
                mult = 2 if s.mode == SnakeMode.GOLDEN else 1
                s.score += food.value * mult
                s.grow_pending += food.value * mult
                self._spawn_bite_sparks(state, nxt, s.faction.head_color)
                new_p = self.random_free_cell(state)
                if new_p: state.foods.append(Food(pos=new_p, value=1))

            s.body.appendleft(nxt)
            if s.grow_pending > 0:
                s.grow_pending -= 1
            else:
                s.body.pop()

            s.head_history.append(nxt)
            if s.blink_timer > 0: s.blink_timer -= 1
            elif self.rng.random() < 0.015: s.blink_timer = 3

            if s.tongue_timer > 0: s.tongue_timer -= 1
            elif self.rng.random() < 0.04: s.tongue_timer = 4

        state.tick += 1

    def reset_round(self, state: ColosseumState, now_ms: int) -> None:
        state.round_number += 1
        state.round_winner = None
        state.round_reset_ms = 0
        state.foods = []
        state.bombs = {}
        state.nuclear = None
        state.countdown_active = True
        state.countdown_start_ms = now_ms

        starts_all = [
            (Point(4, 4), Direction.RIGHT),
            (Point(state.grid_size - 5, 4), Direction.DOWN),
            (Point(state.grid_size - 5, state.grid_size - 5), Direction.LEFT),
            (Point(4, state.grid_size - 5), Direction.UP),
            (Point(state.grid_size // 2, state.grid_size // 2), Direction.RIGHT),
        ]
        starts_2p = [
            (Point(4, state.grid_size // 2), Direction.RIGHT),
            (Point(state.grid_size - 5, state.grid_size // 2), Direction.LEFT),
        ]
        starts_1p = [
            (Point(state.grid_size // 2, state.grid_size // 2), Direction.RIGHT)
        ]

        if state.game_mode == GameMode.BATTLE_ROYALE: starts = starts_all
        elif state.game_mode == GameMode.DUEL_1V1: starts = starts_2p
        else: starts = starts_1p

        for i, s in enumerate(state.snakes):
            start_p, start_d = starts[i % len(starts)]
            s.body = deque([Point(start_p.x - start_d.dx * j, start_p.y - start_d.dy * j) for j in range(INITIAL_SNAKE_LENGTH)])
            s.direction = start_d
            s.alive = True
            s.grow_pending = 0
            s.mode = SnakeMode.NORMAL
            s.mode_until_ms = 0
            s.head_history.clear()

        target_food_count = max(4, (state.grid_size * state.grid_size) // 100) if state.game_mode == GameMode.BATTLE_ROYALE else (2 if state.game_mode == GameMode.DUEL_1V1 else 1)
        for _ in range(target_food_count):
            p = self.random_free_cell(state)
            if p: state.foods.append(Food(pos=p, value=1))

    def random_free_cell(self, state: ColosseumState) -> Optional[Point]:
        occupied = set(state.bombs.keys()) | {f.pos for f in state.foods}
        for s in state.snakes: occupied |= set(s.body)
        free = [Point(x, y) for y in range(state.grid_size) for x in range(state.grid_size) if Point(x, y) not in occupied]
        return self.rng.choice(free) if free else None

    def _spawn_death_debris(self, state: ColosseumState, s: ColosseumSnake) -> None:
        for i, p in enumerate(s.body):
            if i % 3 == 0: state.foods.append(Food(pos=p, value=1))
            self._spawn_explosion(state, p, count=6, col=s.faction.body_color)

    def _spawn_explosion(self, state: ColosseumState, p: Point, count: int = 14, col: Optional[Tuple[int, int, int]] = None) -> None:
        bw = state.grid_size * state.cell_px
        ox = max(MARGIN_PX, (648 - bw) // 2) + p.x * state.cell_px + state.cell_px // 2
        oy = HUD_HEIGHT + MARGIN_PX + p.y * state.cell_px + state.cell_px // 2
        for _ in range(count):
            ang = self.rng.uniform(0, 2 * math.pi)
            spd = self.rng.uniform(2.0, 6.0)
            c = col if col else self.rng.choice([(255, 120, 30), (255, 200, 50), (220, 50, 40)])
            state.particles.append(VisualParticle(
                x=ox, y=oy, vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                color=c, radius=self.rng.uniform(2.5, 5.5), life_ms=400, max_life_ms=400
            ))

    def _spawn_bite_sparks(self, state: ColosseumState, p: Point, col: Tuple[int, int, int]) -> None:
        bw = state.grid_size * state.cell_px
        ox = max(MARGIN_PX, (648 - bw) // 2) + p.x * state.cell_px + state.cell_px // 2
        oy = HUD_HEIGHT + MARGIN_PX + p.y * state.cell_px + state.cell_px // 2
        for _ in range(8):
            ang = self.rng.uniform(0, 2 * math.pi)
            spd = self.rng.uniform(1.2, 3.5)
            state.particles.append(VisualParticle(
                x=ox, y=oy, vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                color=col, radius=self.rng.uniform(2.0, 4.0), life_ms=250, max_life_ms=250
            ))

    def _update_nuclear(self, state: ColosseumState, now_ms: int) -> None:
        nuke = state.nuclear
        if not nuke or nuke.state == "FINISHED": return
        target_y = HUD_HEIGHT + MARGIN_PX + nuke.center.y * state.cell_px + state.cell_px // 2

        if nuke.state == "FALLING":
            nuke.fall_y += 16.0
            if nuke.fall_y >= target_y:
                nuke.fall_y = target_y
                nuke.state = "IMPACT_FLASH"
                nuke.impact_flash_ms = now_ms + 180
                self._spawn_explosion(state, nuke.center, count=25)
        elif nuke.state == "IMPACT_FLASH":
            if now_ms >= nuke.impact_flash_ms:
                nuke.state = "EXPLODING"
                nuke.rings_expanded = 0
                nuke.ring_next_ms = now_ms
        elif nuke.state == "EXPLODING":
            to_remove = []
            for p, (fase, exp) in nuke.affected_cells.items():
                if now_ms >= exp:
                    if fase == "HOT": nuke.affected_cells[p] = ("ASH", now_ms + 800)
                    elif fase == "ASH": nuke.affected_cells[p] = ("CHAR", now_ms + 1100)
                    else: to_remove.append(p)
            for p in to_remove: nuke.affected_cells.pop(p, None)

            if now_ms >= nuke.ring_next_ms and nuke.rings_expanded < nuke.max_rings:
                r = nuke.rings_expanded
                nuke.rings_expanded += 1
                nuke.ring_next_ms = now_ms + 150
                for y in range(state.grid_size):
                    for x in range(state.grid_size):
                        pt = Point(x, y)
                        if manhattan_plane(pt, nuke.center) == r:
                            nuke.affected_cells[pt] = ("HOT", now_ms + 550)
                            if pt in state.bombs:
                                state.bombs.pop(pt, None)
                                self._spawn_explosion(state, pt, count=6)

            elif nuke.rings_expanded >= nuke.max_rings and not nuke.affected_cells:
                nuke.state = "FINISHED"

# ============================================================
# Inteligencia Artificial Infalible (BFS Escape & Safe Moves)
# ============================================================

class MultiAgentBotController:
    def __init__(self, rng: random.Random, patterns: List[Pattern]):
        self.rng = rng
        self.patterns = patterns

    def decide_all(self, state: ColosseumState, now_ms: int) -> None:
        if state.countdown_active: return
        for s in state.snakes:
            if not s.alive: continue
            s.direction = self._choose_direction_for_snake(s, state, now_ms)

    def _choose_direction_for_snake(self, snake: ColosseumSnake, state: ColosseumState, now_ms: int) -> Direction:
        profile = snake.faction
        
        # Consciencia temporal de paredes
        effective_wall_col = state.wall_collision
        if not state.wall_collision and state.wrap_mode_until_ms > 0:
            if state.wrap_mode_until_ms - now_ms < 1500:
                effective_wall_col = True

        n = state.grid_size
        safe_moves = self._safe_moves(snake, state, now_ms, effective_wall_col, n)
        if not safe_moves:
            return self._best_delay_death(snake, state, effective_wall_col, n)

        targets = [f.pos for f in state.foods]
        golden = (snake.mode == SnakeMode.GOLDEN and snake.mode_until_ms > now_ms)
        if golden and state.bombs: targets += list(state.bombs.keys())

        head = snake.body[0]
        tail = snake.body[-1]
        food_target = min(targets, key=lambda p: dist_for_config(head, p, effective_wall_col, n)) if targets else head

        # Ponderación según modo
        if state.game_mode == GameMode.SPEEDRUN:
            pat_dir = snake.direction
            pat_weight = 0.05
            food_weight = 2.80
        elif state.game_mode == GameMode.HYPNOTIC:
            L = len(snake.body)
            pat_weight = 0.4 if L < 10 else 1.7
            food_weight = 1.6 if L < 10 else 0.6
            pat = self.patterns[snake.pattern_idx % len(self.patterns)]
            pat_dir = pat.preferred_direction(head, snake.direction, n, effective_wall_col, state.tick, self.rng)
        else:
            L = len(snake.body)
            pers_scale = min(1.0, L / 16.0)
            pat_weight = 0.8 + (profile.pattern_weight - 0.8) * pers_scale
            food_weight = 1.0 + (profile.food_weight - 1.0) * pers_scale
            pat = self.patterns[snake.pattern_idx % len(self.patterns)]
            pat_dir = pat.preferred_direction(head, snake.direction, n, effective_wall_col, state.tick, self.rng)

        best_d = safe_moves[0]
        best_score = -1e18

        for d in safe_moves:
            cand = Point(head.x + d.dx, head.y + d.dy)
            nxt = cand if effective_wall_col else wrap(cand, n)

            dist_food = dist_for_config(nxt, food_target, effective_wall_col, n)
            pat_bonus = 1.0 if d == pat_dir else 0.0
            straight_bonus = 0.4 if d == snake.direction else -0.25

            tail_dist = dist_for_config(nxt, tail, effective_wall_col, n)
            tail_avoid = -profile.tail_avoid_factor * (3 - tail_dist) if tail_dist <= 2 else 0.0

            # Anti-choque frontal con rivales
            rival_danger_pen = 0.0
            for other in state.snakes:
                if other.snake_id != snake.snake_id and other.alive:
                    d_rival_head = dist_for_config(nxt, other.body[0], effective_wall_col, n)
                    if d_rival_head <= 1 and other.mode != SnakeMode.GOLDEN:
                        rival_danger_pen -= 9.0
                    elif d_rival_head == 2:
                        rival_danger_pen -= 2.5

            center_bonus = 0.0
            if profile.preferred_center_layer:
                lyr = layer_index(nxt, n)
                if 2 <= lyr <= n // 3: center_bonus = 1.5

            jitter = self.rng.uniform(-0.04, 0.04)

            score = 0.0
            score += (-dist_food) * (2.2 * food_weight)
            score += pat_bonus * (2.0 * pat_weight)
            score += straight_bonus + tail_avoid + rival_danger_pen + center_bonus + jitter

            if any(nxt == f.pos for f in state.foods): score += 7.0
            if golden and (nxt in state.bombs): score += 7.0

            # Penalización de bolsas vacías
            score += self._small_empty_components_penalty(nxt, snake, state, effective_wall_col, now_ms, n)

            if score > best_score:
                best_score = score
                best_d = d

        return best_d

    def _safe_moves(self, snake: ColosseumSnake, state: ColosseumState, now_ms: int, wall_col: bool, n: int) -> List[Direction]:
        head = snake.body[0]
        tail = snake.body[-1]
        golden = (snake.mode == SnakeMode.GOLDEN and snake.mode_until_ms > now_ms)

        # Obstáculos mortales
        blocked: Set[Point] = set()
        if not golden:
            blocked |= set(state.bombs.keys())
            if state.nuclear and state.nuclear.affected_cells:
                blocked |= {p for p, (f, _) in state.nuclear.affected_cells.items() if f in ("HOT", "ASH")}

        # Cuerpos ajenos
        for s in state.snakes:
            if not s.alive: continue
            if s.snake_id != snake.snake_id:
                blocked |= set(s.body)

        own_body = list(snake.body)
        own_set = set(own_body)

        safe = []
        for d in DIRS:
            cand = Point(head.x + d.dx, head.y + d.dy)
            if wall_col and not in_bounds(cand, n): continue
            nxt = cand if wall_col else wrap(cand, n)

            if nxt in blocked: continue

            eats = any(nxt == f.pos for f in state.foods) or (golden and nxt in state.bombs)
            if nxt in own_set:
                # Solo puede avanzar a la cola si no come y no hay comida pendiente
                if not eats and snake.grow_pending == 0 and nxt == tail:
                    pass
                else:
                    continue

            # Simular serpiente proyectada
            proj = deque(own_body)
            proj.appendleft(nxt)
            if not eats and snake.grow_pending == 0:
                proj.pop()

            # MANDATO SAGRADO: VERIFICACIÓN BFS DE ESCAPE A LA COLA
            if not self._has_escape(proj, blocked, wall_col, n):
                continue

            safe.append(d)
        return safe

    def _has_escape(self, proj_snake: Deque[Point], blocked_env: Set[Point], wall_col: bool, n: int) -> bool:
        head = proj_snake[0]
        tail = proj_snake[-1]
        
        # Bloquear todo el cuerpo excepto la cola liberada
        snake_block = set(proj_snake)
        if tail in snake_block:
            snake_block.remove(tail)
        
        total_block = snake_block | blocked_env
        if tail in total_block:
            total_block.remove(tail)

        q = deque([head])
        seen = {head}
        while q:
            cur = q.popleft()
            if cur == tail:
                return True
            for d in DIRS:
                cand = Point(cur.x + d.dx, cur.y + d.dy)
                if wall_col and not in_bounds(cand, n): continue
                nxt = cand if wall_col else wrap(cand, n)

                if nxt in seen or nxt in total_block: continue
                seen.add(nxt)
                q.append(nxt)
        return False

    def _small_empty_components_penalty(self, nxt: Point, snake: ColosseumSnake, state: ColosseumState, wall_col: bool, now_ms: int, n: int) -> float:
        golden = (snake.mode == SnakeMode.GOLDEN and snake.mode_until_ms > now_ms)
        eats = any(nxt == f.pos for f in state.foods) or (golden and nxt in state.bombs)
        if eats:
            return 0.0  # Regla sagrada: comida en esquinas no se penaliza

        # Proyectar
        proj = deque(snake.body)
        proj.appendleft(nxt)
        if snake.grow_pending == 0: proj.pop()

        occupied = set(proj) | {f.pos for f in state.foods}
        if not golden: occupied |= set(state.bombs.keys())
        for s in state.snakes:
            if s.alive and s.snake_id != snake.snake_id:
                occupied |= set(s.body)

        # Evaluar vecinos inmediatos de la celda proyectada
        penalty = 0.0
        for d in DIRS:
            cand = Point(nxt.x + d.dx, nxt.y + d.dy)
            if wall_col and not in_bounds(cand, n): continue
            neighbor = cand if wall_col else wrap(cand, n)

            if neighbor in occupied: continue

            # Medir tamaño del espacio libre desde este vecino
            q = deque([neighbor])
            seen = {neighbor}
            while q and len(seen) < 4:
                u = q.popleft()
                for dd in DIRS:
                    c2 = Point(u.x + dd.dx, u.y + dd.dy)
                    if wall_col and not in_bounds(c2, n): continue
                    v = c2 if wall_col else wrap(c2, n)
                    if v not in occupied and v not in seen:
                        seen.add(v)
                        q.append(v)
            if len(seen) == 1: penalty -= 8.0
            elif len(seen) == 2: penalty -= 4.0

        return penalty

    def _best_delay_death(self, snake: ColosseumSnake, state: ColosseumState, wall_col: bool, n: int) -> Direction:
        head = snake.body[0]
        blocked = set(state.bombs.keys())
        for s in state.snakes:
            if s.alive: blocked |= set(s.body)

        best, best_free = snake.direction, -1
        for d in DIRS:
            cand = Point(head.x + d.dx, head.y + d.dy)
            if wall_col and not in_bounds(cand, n): continue
            nxt = cand if wall_col else wrap(cand, n)
            if nxt in blocked: continue
            free = sum(1 for dd in DIRS if wrap(Point(nxt.x + dd.dx, nxt.y + dd.dy), n) not in blocked)
            if free > best_free: best_free, best = free, d
        return best


# ============================================================
# Renderer Proporcional (Texto Adaptado y HUD Estricto)
# ============================================================

class ColosseumRenderer:
    def __init__(self):
        self.font_title: Optional[pygame.font.Font] = None
        self.font_hud: Optional[pygame.font.Font] = None
        self.font_sub: Optional[pygame.font.Font] = None

    def window_size(self) -> Tuple[int, int]:
        # 22 * 28 + 32 = 648 de ancho, 616 + 32 + 56 = 704 de alto
        return GRID_SIZE * CELL_PX + 2 * MARGIN_PX, GRID_SIZE * CELL_PX + 2 * MARGIN_PX + HUD_HEIGHT

    def render(self, surface: pygame.Surface, state: ColosseumState, now_ms: int) -> None:
        if not self.font_hud:
            self.font_title = pygame.font.SysFont("consolas", 20, bold=True)
            self.font_hud = pygame.font.SysFont("consolas", 13, bold=True)
            self.font_sub = pygame.font.SysFont("consolas", 12)

        surface.fill((12, 12, 15))
        self._draw_board(surface, state)
        self._draw_hud_strict(surface, state, now_ms)

        if state.nuclear: self._draw_nuclear_3d(surface, state.nuclear, state, now_ms)
        for p, exp in state.bombs.items(): self._draw_bomb(surface, p, exp, state, now_ms)
        for f in state.foods: self._draw_food(surface, f, state)

        for s in state.snakes:
            if s.alive: self._draw_organic_snake(surface, s, state, now_ms)

        self._update_and_draw_particles(surface, state)

        if state.countdown_active:
            self._draw_countdown(surface, state, now_ms)

        if state.round_winner and not state.countdown_active:
            self._draw_winner_banner(surface, state.round_winner)

    def _origin(self, state: Optional[ColosseumState] = None) -> Tuple[int, int]:
        if state:
            bw = state.grid_size * state.cell_px
            ox = max(MARGIN_PX, (648 - bw) // 2)
            return ox, MARGIN_PX + HUD_HEIGHT
        return MARGIN_PX, MARGIN_PX + HUD_HEIGHT

    def _cell_center(self, p: Point, state: Optional[ColosseumState] = None) -> Tuple[int, int]:
        cpx = state.cell_px if state else CELL_PX
        ox, oy = self._origin(state)
        return ox + p.x * cpx + cpx // 2, oy + p.y * cpx + cpx // 2

    def _draw_board(self, surface: pygame.Surface, state: ColosseumState) -> None:
        ox, oy = self._origin(state)
        bw, bh = state.grid_size * state.cell_px, state.grid_size * state.cell_px
        border_col = (150, 75, 235) if not state.wall_collision else (32, 33, 40)
        pygame.draw.rect(surface, (18, 18, 22), pygame.Rect(ox - 6, oy - 6, bw + 12, bh + 12), border_radius=14)
        if not state.wall_collision:
            pygame.draw.rect(surface, border_col, pygame.Rect(ox - 6, oy - 6, bw + 12, bh + 12), width=2, border_radius=14)

        for y in range(state.grid_size):
            for x in range(state.grid_size):
                col = (28, 29, 34) if (x + y) % 2 == 0 else (22, 23, 27)
                pygame.draw.rect(surface, col, pygame.Rect(ox + x * state.cell_px, oy + y * state.cell_px, state.cell_px, state.cell_px))

    def _draw_hud_strict(self, surface: pygame.Surface, state: ColosseumState, now_ms: int) -> None:
        """
        HUD ESTRICTO:
        Contiene ÚNICA Y EXCLUSIVAMENTE los 5 elementos exigidos:
        1. Estado de TikTok
        2. Modo de juego
        3. FPS
        4. Nombre de patrón
        5. Evento activo
        """
        w = surface.get_width()
        pygame.draw.rect(surface, (18, 18, 24), pygame.Rect(0, 0, w, HUD_HEIGHT))
        pygame.draw.line(surface, (35, 36, 45), (0, HUD_HEIGHT - 1), (w, HUD_HEIGHT - 1), 1)

        # 1. Estado de TikTok (LED + Texto)
        is_live = (now_ms - state.last_udp_ms < 4000) and (state.last_udp_ms > 0)
        led_col = (60, 235, 120) if is_live else (200, 160, 50)
        pygame.draw.circle(surface, led_col, (24, 18), 5)
        live_txt = "TIKTOK: LIVE" if is_live else "TIKTOK: ESPERA"
        surface.blit(self.font_hud.render(live_txt, True, led_col), (34, 10))

        # 2. Modo de Juego
        mode_names = {
            GameMode.BATTLE_ROYALE: f"BATTLE ROYALE ({len(state.snakes)}P)",
            GameMode.DUEL_1V1: "DUELO 1V1 (2P)",
            GameMode.HYPNOTIC: "HIPNÓTICO (1P)",
            GameMode.SPEEDRUN: "SPEEDRUN (1P)"
        }
        mode_txt = f"MODO: {mode_names[state.game_mode]}"
        surface.blit(self.font_hud.render(mode_txt, True, (240, 240, 245)), (185, 10))

        # 3. FPS
        fps_txt = f"FPS: {state.fps_base}"
        surface.blit(self.font_hud.render(fps_txt, True, (255, 215, 80)), (w - 90, 10))

        # FILA INFERIOR DEL HUD:
        # 4. Nombre de Patrón
        active_snake = next((s for s in state.snakes if s.alive), state.snakes[0])
        if state.game_mode == GameMode.SPEEDRUN: pat_name = "Caza Voraz"
        elif state.game_mode == GameMode.HYPNOTIC:
            pat_name = "Caza Temprana" if len(active_snake.body) < 10 else "Espiral / Geometría"
        else:
            pat_name = active_snake.faction.personality_title

        pat_txt = f"PATRÓN: {pat_name}"
        surface.blit(self.font_sub.render(pat_txt, True, (170, 175, 195)), (24, 32))

        # 5. Evento Activo (con cuenta regresiva en segundos)
        event_str = "EVENTO: NINGUNO"
        event_col = (130, 135, 150)

        # Chequear modos de serpiente o evento global
        if not state.wall_collision and state.wrap_mode_until_ms > now_ms:
            t_rem = (state.wrap_mode_until_ms - now_ms) / 1000.0
            event_str = f"EVENTO: TRASCENDENTE ({t_rem:.1f}s)"
            event_col = (210, 130, 255)
        else:
            for s in state.snakes:
                if s.alive and s.mode != SnakeMode.NORMAL and s.mode_until_ms > now_ms:
                    t_rem = (s.mode_until_ms - now_ms) / 1000.0
                    event_str = f"EVENTO: {s.mode.value} ({t_rem:.1f}s)"
                    event_col = (255, 220, 80) if s.mode == SnakeMode.GOLDEN else (255, 120, 200)
                    break

        surface.blit(self.font_sub.render(event_str, True, event_col), (260, 32))

    def _draw_organic_snake(self, surface: pygame.Surface, s: ColosseumSnake, state: ColosseumState, now_ms: int) -> None:
        pts = list(s.body)
        if not pts: return
        L = len(pts)
        centers = [self._cell_center(p, state) for p in pts]
        base_r = max(2.5, state.cell_px // 2 - 3)

        golden = (s.mode == SnakeMode.GOLDEN and s.mode_until_ms > now_ms)
        extasis = (s.mode == SnakeMode.EXTASIS and s.mode_until_ms > now_ms)

        taper_len = max(2, int(L * 0.15))
        radii = []
        for i in range(L):
            if i == 0: radii.append(base_r + 2.5)
            elif i >= L - taper_len:
                factor = 0.35 + 0.65 * ((L - 1 - i) / taper_len)
                radii.append(max(2.0, base_r * factor))
            else: radii.append(base_r)

        for i in range(L - 1):
            if abs(pts[i].x - pts[i+1].x) > 1 or abs(pts[i].y - pts[i+1].y) > 1: continue
            pygame.draw.line(surface, (10, 10, 13), (centers[i][0] + 2, centers[i][1] + 2),
                             (centers[i+1][0] + 2, centers[i+1][1] + 2), int(radii[i] * 2 + 3))

        for i in range(L - 1, -1, -1):
            c, r = centers[i], radii[i]
            if golden: col = (255, 220, 80) if i == 0 else (220, 180, 50)
            elif extasis:
                phase = ((state.tick * 0.2) + i * 0.1) % 1.0
                col = self._hsv_to_rgb(phase, 0.95, 1.0)
            else:
                col = s.faction.head_color if i == 0 else s.faction.body_color

            if i < L - 1 and not (abs(pts[i].x - pts[i+1].x) > 1 or abs(pts[i].y - pts[i+1].y) > 1):
                pygame.draw.line(surface, col, c, centers[i + 1], int(r * 2))
            pygame.draw.circle(surface, col, c, int(r))

        self._draw_snake_face(surface, s, centers[0], radii[0])

    def _draw_snake_face(self, surface: pygame.Surface, s: ColosseumSnake, c: Tuple[int, int], r: float) -> None:
        cx, cy = c
        d = s.direction
        if d == Direction.UP: eye1, eye2 = (cx - r * 0.45, cy - r * 0.3), (cx + r * 0.45, cy - r * 0.3)
        elif d == Direction.DOWN: eye1, eye2 = (cx - r * 0.45, cy + r * 0.3), (cx + r * 0.45, cy + r * 0.3)
        elif d == Direction.LEFT: eye1, eye2 = (cx - r * 0.3, cy - r * 0.45), (cx - r * 0.3, cy + r * 0.45)
        else: eye1, eye2 = (cx + r * 0.3, cy - r * 0.45), (cx + r * 0.3, cy + r * 0.45)

        eye_r = max(1.8, r * 0.32)
        for e in (eye1, eye2):
            ex, ey = int(e[0]), int(e[1])
            if s.blink_timer > 0:
                pygame.draw.line(surface, (20, 20, 25), (ex - eye_r, ey), (ex + eye_r, ey), 2)
            else:
                pygame.draw.circle(surface, (250, 250, 250), (ex, ey), int(eye_r))
                pygame.draw.circle(surface, (15, 15, 20), (ex, ey), max(1, int(eye_r * 0.55)))

    def _draw_food(self, surface: pygame.Surface, f: Food, state: Optional[ColosseumState] = None) -> None:
        cpx = state.cell_px if state else CELL_PX
        cx, cy = self._cell_center(f.pos, state)
        r = max(2.5, cpx // 2 - 4)
        pygame.draw.circle(surface, (220, 40, 45), (cx, cy), int(r))
        pygame.draw.circle(surface, (255, 90, 95), (cx - 1, cy - 1), max(2, int(r - 2)))
        pygame.draw.circle(surface, (255, 200, 205), (int(cx - r // 2), int(cy - r // 2)), 1)

    def _draw_bomb(self, surface: pygame.Surface, p: Point, exp_ms: int, state: Optional[ColosseumState] = None, now_ms: int = 0) -> None:
        cpx = state.cell_px if state else CELL_PX
        cx, cy = self._cell_center(p, state)
        r = max(2.5, cpx // 2 - 5)
        pygame.draw.circle(surface, (45, 45, 55), (cx, cy), int(r))
        spark = (255, 220, 50) if ((exp_ms - now_ms) // 150) % 2 == 0 else (255, 90, 30)
        pygame.draw.circle(surface, spark, (int(cx + r + 3), int(cy - r - 3)), 3)

    def _draw_nuclear_3d(self, surface: pygame.Surface, nuke: NuclearStrike, state: Optional[ColosseumState] = None, now_ms: int = 0) -> None:
        cpx = state.cell_px if state else CELL_PX
        for pt, (fase, _) in nuke.affected_cells.items():
            cx, cy = self._cell_center(pt, state)
            rect = pygame.Rect(cx - cpx // 2, cy - cpx // 2, cpx, cpx)
            if fase == "HOT": pygame.draw.rect(surface, (240, 140, 20), rect)
            elif fase == "ASH": pygame.draw.rect(surface, (110, 105, 115), rect)
            else: pygame.draw.rect(surface, (35, 35, 40), rect)

        if nuke.state == "FALLING":
            cx, target_y = self._cell_center(nuke.center, state)
            cur_y = int(nuke.fall_y)

            dist_to_ground = max(1.0, target_y - cur_y)
            shadow_w = max(4, int(24 * (1.0 - dist_to_ground / 300.0)))
            pygame.draw.ellipse(surface, (10, 10, 14), pygame.Rect(cx - shadow_w // 2, target_y - 4, shadow_w, 8))

            pygame.draw.line(surface, (255, 190, 40), (cx, cur_y - 12), (cx, cur_y - 40), 5)
            pygame.draw.line(surface, (255, 100, 30), (cx, cur_y - 20), (cx, cur_y - 55), 3)

            body_rect = pygame.Rect(cx - 6, cur_y - 16, 12, 24)
            pygame.draw.rect(surface, (215, 40, 40), body_rect, border_radius=5)
            pygame.draw.polygon(surface, (245, 60, 60), [(cx - 6, cur_y - 16), (cx + 6, cur_y - 16), (cx, cur_y - 26)])
            pygame.draw.rect(surface, (255, 215, 60), pygame.Rect(cx - 2, cur_y - 8, 4, 12))

        elif nuke.state == "IMPACT_FLASH":
            flash_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            flash_surf.fill((255, 255, 255, 140))
            surface.blit(flash_surf, (0, 0))


    def _draw_countdown(self, surface: pygame.Surface, state: ColosseumState, now_ms: int) -> None:
        elapsed = now_ms - state.countdown_start_ms
        if elapsed >= 3500:
            state.countdown_active = False
            return

        if elapsed < 1000: txt = "3"; prog = (elapsed % 1000) / 1000.0
        elif elapsed < 2000: txt = "2"; prog = (elapsed % 1000) / 1000.0
        elif elapsed < 3000: txt = "1"; prog = (elapsed % 1000) / 1000.0
        else: txt = "¡START!"; prog = 0.5

        scale_factor = max(0.5, 1.4 - prog * 0.7)
        font_size = int(60 * scale_factor)
        anim_font = pygame.font.SysFont("consolas", font_size, bold=True)
        img = anim_font.render(txt, True, (255, 220, 80))
        rect = img.get_rect(center=(surface.get_width() // 2, surface.get_height() // 2))
        surface.blit(img, rect)

    def _update_and_draw_particles(self, surface: pygame.Surface, state: ColosseumState) -> None:
        alive_p = []
        for p in state.particles:
            p.x += p.vx
            p.y += p.vy
            p.life_ms -= 16
            if p.life_ms > 0:
                r = max(1.0, p.radius * (p.life_ms / p.max_life_ms))
                pygame.draw.circle(surface, p.color, (int(p.x), int(p.y)), int(r))
                alive_p.append(p)
        state.particles = alive_p

    def _draw_winner_banner(self, surface: pygame.Surface, txt: str) -> None:
        assert self.font_title is not None
        img = self.font_title.render(txt, True, (255, 220, 80))
        rect = img.get_rect(center=(surface.get_width() // 2, surface.get_height() // 2))
        bg = rect.inflate(36, 20)
        pygame.draw.rect(surface, (18, 18, 26), bg, border_radius=10)
        pygame.draw.rect(surface, (255, 215, 80), bg, width=3, border_radius=10)
        surface.blit(img, rect)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> Tuple[int, int, int]:
        i = int(h * 6.0); f = (h * 6.0) - i
        p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
        i = i % 6
        if i == 0: r, g, b = v, t, p
        elif i == 1: r, g, b = q, v, p
        elif i == 2: r, g, b = p, v, t
        elif i == 3: r, g, b = p, q, v
        elif i == 4: r, g, b = t, p, v
        else: r, g, b = v, p, q
        return int(r * 255), int(g * 255), int(b * 255)

# ============================================================
# Receptor UDP y Controles
# ============================================================

class UDPReceiver:
    def __init__(self, host: str, port: int):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.is_bound = False
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((host, port))
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
            except (BlockingIOError, Exception): break

class ExternalInputController:
    def __init__(self, bus: EventBus): self.bus = bus

    def handle_keydown(self, key: int) -> None:
        if key == pygame.K_j: self.bus.emit(GameEvent("SLOW_DOWN", {"delta": 2}))
        elif key == pygame.K_l: self.bus.emit(GameEvent("SPEED_UP", {"delta": 2}))
        elif key == pygame.K_k: self.bus.emit(GameEvent("PAUSE_TOGGLE"))
        elif key == pygame.K_x: self.bus.emit(GameEvent("SPAWN_BOMB"))
        elif key == pygame.K_z: self.bus.emit(GameEvent("SPAWN_EXTRA_FOOD"))
        elif key == pygame.K_w: self.bus.emit(GameEvent("WRAP_TOGGLE"))
        elif key == pygame.K_e: self.bus.emit(GameEvent("EXTASIS"))
        elif key == pygame.K_g: self.bus.emit(GameEvent("GOLDEN_MODE"))
        elif key == pygame.K_b: self.bus.emit(GameEvent("SPAWN_NUCLEAR_BOMB"))

# ============================================================
# Escenas UI con Ajuste Perfecto al Ancho
# ============================================================

class Scene(Protocol):
    def handle(self, events: List[pygame.event.Event]) -> Optional["Scene"]: ...
    def render(self, surface: pygame.Surface, now_ms: int) -> None: ...

class MainMenuScene:
    def __init__(self, app: "ColosseumApp"):
        self.app = app
        self.font_title: Optional[pygame.font.Font] = None
        self.font_btn: Optional[pygame.font.Font] = None
        self.font_sub: Optional[pygame.font.Font] = None
        self.buttons = [
            ("⚔️ JUGAR / MODOS", "modes"),
            ("⌨️ CONTROLES", "controls"),
            ("📱 GUÍA TIKTOK LIVE", "tiktok"),
            ("🚪 SALIR", "quit")
        ]
        self.hover_idx = -1

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE: return None
            if e.type == pygame.MOUSEMOTION:
                self.hover_idx = self._get_button_at(e.pos)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                idx = self._get_button_at(e.pos)
                if idx != -1:
                    action = self.buttons[idx][1]
                    if action == "quit": return None
                    elif action == "modes": return ModeSelectScene(self.app)
                    elif action == "controls": return ControlsScene(self.app)
                    elif action == "tiktok": return TikTokGuideScene(self.app)
        return self

    def _get_button_at(self, pos: Tuple[int, int]) -> int:
        w = self.app.renderer.window_size()[0]
        bw, bh = min(380, w - 60), 48
        bx = (w - bw) // 2
        start_y = 180
        for i in range(len(self.buttons)):
            by = start_y + i * 64
            if bx <= pos[0] <= bx + bw and by <= pos[1] <= by + bh: return i
        return -1

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if not self.font_title:
            self.font_title = pygame.font.SysFont("consolas", 28, bold=True)
            self.font_btn = pygame.font.SysFont("consolas", 16, bold=True)
            self.font_sub = pygame.font.SysFont("consolas", 13)

        surface.fill((12, 12, 16))
        w, h = surface.get_width(), surface.get_height()

        title_img = self.font_title.render("SNAKE — THE COLOSSEUM", True, (245, 245, 245))
        surface.blit(title_img, title_img.get_rect(center=(w // 2, 75)))

        sub_img = self.font_sub.render("IA Autónoma & Espectáculo Interactivo", True, (160, 165, 185))
        surface.blit(sub_img, sub_img.get_rect(center=(w // 2, 110)))

        bw, bh = min(380, w - 60), 48
        bx = (w - bw) // 2
        start_y = 180
        for i, (label, _) in enumerate(self.buttons):
            by = start_y + i * 64
            is_hover = (i == self.hover_idx)
            btn_col = (40, 42, 52) if is_hover else (24, 25, 32)
            border_col = (255, 215, 80) if is_hover else (60, 65, 80)
            text_col = (255, 235, 120) if is_hover else (220, 220, 230)

            pygame.draw.rect(surface, btn_col, pygame.Rect(bx, by, bw, bh), border_radius=10)
            pygame.draw.rect(surface, border_col, pygame.Rect(bx, by, bw, bh), width=2, border_radius=10)
            txt_surf = self.font_btn.render(label, True, text_col)
            surface.blit(txt_surf, txt_surf.get_rect(center=(bx + bw // 2, by + bh // 2)))

        footer = self.font_sub.render("Creado y Desarrollado con SaperaAI", True, (130, 135, 150))
        surface.blit(footer, footer.get_rect(center=(w // 2, h - 30)))

class ModeSelectScene:
    def __init__(self, app: "ColosseumApp"):
        self.app = app
        self.font_title: Optional[pygame.font.Font] = None
        self.font_btn: Optional[pygame.font.Font] = None
        self.font_desc: Optional[pygame.font.Font] = None
        self.modes = [
            (GameMode.BATTLE_ROYALE, "⚔️ BATTLE ROYALE (COLISEO PERSONALIZADO)", "Configura tamaño de arena, gladiadores y jinetes."),
            (GameMode.DUEL_1V1, "🔥 DUELO 1V1 (2 SERPIENTES)", "Duelo directo Fénix Carmesí vs Cobra Esmeralda."),
            (GameMode.HYPNOTIC, "🌀 MODO HIPNÓTICO (1 SERPIENTE)", "Espectáculo fluido: caza rápida y patrones sagrados."),
            (GameMode.SPEEDRUN, "⚡ MODO RÁPIDO / SPEEDRUN (1P)", "IA voraz cazando comida a máxima velocidad.")
        ]
        self.hover_idx = -1

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE: return MainMenuScene(self.app)
            if e.type == pygame.MOUSEMOTION:
                self.hover_idx = self._get_mode_at(e.pos)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                idx = self._get_mode_at(e.pos)
                if idx == 99: return MainMenuScene(self.app)
                if idx == 0:
                    return ColosseumSetupScene(self.app)
                if 0 < idx < len(self.modes):
                    return PlayScene(self.app, self.modes[idx][0])
        return self

    def _get_mode_at(self, pos: Tuple[int, int]) -> int:
        w = self.app.renderer.window_size()[0]
        if 20 <= pos[0] <= 130 and 20 <= pos[1] <= 56: return 99
        bw, bh = min(560, w - 40), 70
        bx = (w - bw) // 2
        start_y = 110
        for i in range(len(self.modes)):
            by = start_y + i * 86
            if bx <= pos[0] <= bx + bw and by <= pos[1] <= by + bh: return i
        return -1

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if not self.font_title:
            self.font_title = pygame.font.SysFont("consolas", 22, bold=True)
            self.font_btn = pygame.font.SysFont("consolas", 15, bold=True)
            self.font_desc = pygame.font.SysFont("consolas", 12)

        surface.fill((12, 12, 16))
        w = surface.get_width()

        pygame.draw.rect(surface, (28, 29, 36), pygame.Rect(20, 20, 100, 34), border_radius=8)
        pygame.draw.rect(surface, (80, 85, 105), pygame.Rect(20, 20, 100, 34), width=1, border_radius=8)
        surface.blit(self.font_desc.render("⬅ VOLVER", True, (220, 220, 230)), (32, 29))

        title = self.font_title.render("ELIGE EL MODO DE JUEGO", True, (245, 245, 245))
        surface.blit(title, title.get_rect(center=(w // 2, 40)))

        bw, bh = min(560, w - 40), 70
        bx = (w - bw) // 2
        start_y = 110
        for i, (_, label, desc) in enumerate(self.modes):
            by = start_y + i * 86
            is_hover = (i == self.hover_idx)
            btn_col = (38, 40, 50) if is_hover else (22, 23, 29)
            border_col = (255, 215, 80) if is_hover else (50, 55, 70)
            text_col = (255, 235, 120) if is_hover else (230, 230, 240)

            pygame.draw.rect(surface, btn_col, pygame.Rect(bx, by, bw, bh), border_radius=10)
            pygame.draw.rect(surface, border_col, pygame.Rect(bx, by, bw, bh), width=2, border_radius=10)
            surface.blit(self.font_btn.render(label, True, text_col), (bx + 18, by + 12))
            surface.blit(self.font_desc.render(desc, True, (160, 165, 180)), (bx + 18, by + 40))

class ColosseumSetupScene:
    def __init__(self, app: "ColosseumApp"):
        self.app = app
        self.font_title: Optional[pygame.font.Font] = None
        self.font_section: Optional[pygame.font.Font] = None
        self.font_btn: Optional[pygame.font.Font] = None
        self.font_desc: Optional[pygame.font.Font] = None
        self.font_tag: Optional[pygame.font.Font] = None

        # 1. Tamaño de la Arena: (grid_size, label, sub)
        self.grid_options = [
            (16, "16x16", "Reducido"),
            (22, "22x22", "Normal"),
            (32, "32x32", "Ampliado"),
            (48, "48x48", "Mega Arena"),
        ]
        self.selected_grid_idx = 1  # 22x22 por defecto

        # 2. Cantidad de Serpientes (2 a 5)
        self.count_options = [2, 3, 4, 5]
        self.selected_count = 4     # 4 serpientes por defecto

        # 3. Facciones Disponibles (Ordenadas para rotación cíclica)
        self.available_factions: List[FactionId] = [
            FactionId.RED,
            FactionId.GREEN,
            FactionId.BLUE,
            FactionId.PURPLE,
            FactionId.GOLD
        ]

        # Facciones asignadas a cada ranura (inicialmente una de cada tipo)
        self.slot_factions: List[FactionId] = [
            FactionId.RED,
            FactionId.GREEN,
            FactionId.BLUE,
            FactionId.PURPLE,
            FactionId.GOLD
        ]

        self.hover_element: Optional[str] = None

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return ModeSelectScene(self.app)
                elif e.key in (pygame.K_RETURN, pygame.K_SPACE):
                    return self._start_game()
            if e.type == pygame.MOUSEMOTION:
                self.hover_element = self._get_element_at(e.pos)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                elem = self._get_element_at(e.pos)
                if elem == "back":
                    return ModeSelectScene(self.app)
                elif elem == "start":
                    return self._start_game()
                elif elem and elem.startswith("grid_"):
                    self.selected_grid_idx = int(elem.split("_")[1])
                elif elem and elem.startswith("count_"):
                    self.selected_count = int(elem.split("_")[1])
                elif elem and elem.startswith("slot_prev_"):
                    slot_idx = int(elem.split("_")[2])
                    cur_f = self.slot_factions[slot_idx]
                    idx = self.available_factions.index(cur_f)
                    self.slot_factions[slot_idx] = self.available_factions[(idx - 1) % len(self.available_factions)]
                elif elem and (elem.startswith("slot_next_") or elem.startswith("slot_")):
                    slot_idx = int(elem.split("_")[-1])
                    cur_f = self.slot_factions[slot_idx]
                    idx = self.available_factions.index(cur_f)
                    self.slot_factions[slot_idx] = self.available_factions[(idx + 1) % len(self.available_factions)]
        return self

    def _start_game(self) -> Scene:
        factions = [self.slot_factions[i] for i in range(self.selected_count)]
        grid_size = self.grid_options[self.selected_grid_idx][0]
        setup = ColosseumMatchSetup(grid_size=grid_size, factions=factions)
        return PlayScene(self.app, GameMode.BATTLE_ROYALE, setup=setup)

    def _get_element_at(self, pos: Tuple[int, int]) -> Optional[str]:
        # Volver
        if 20 <= pos[0] <= 115 and 16 <= pos[1] <= 48:
            return "back"

        # Grid buttons
        bw, bh, gap = 136, 36, 12
        start_x, y1 = 34, 88
        for i in range(len(self.grid_options)):
            bx = start_x + i * (bw + gap)
            if bx <= pos[0] <= bx + bw and y1 <= pos[1] <= y1 + bh:
                return f"grid_{i}"

        # Count buttons
        y2 = 152
        for i, cnt in enumerate(self.count_options):
            bx = start_x + i * (bw + gap)
            if bx <= pos[0] <= bx + bw and y2 <= pos[1] <= y2 + 32:
                return f"count_{cnt}"

        # Slot cards
        start_y = 232
        card_w, card_h, gap_card = 580, 58, 7
        for i in range(self.selected_count):
            by = start_y + i * (card_h + gap_card)
            if 34 <= pos[0] <= 34 + card_w and by <= pos[1] <= by + card_h:
                if pos[0] <= 110:
                    return f"slot_prev_{i}"
                elif pos[0] >= 34 + card_w - 40:
                    return f"slot_next_{i}"
                else:
                    return f"slot_{i}"

        # Botón Iniciar
        btn_w, btn_h = 460, 50
        btn_x = (648 - btn_w) // 2
        btn_y = 574
        if btn_x <= pos[0] <= btn_x + btn_w and btn_y <= pos[1] <= btn_y + btn_h:
            return "start"

        return None

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if not self.font_title:
            self.font_title = pygame.font.SysFont("consolas", 20, bold=True)
            self.font_section = pygame.font.SysFont("consolas", 13, bold=True)
            self.font_btn = pygame.font.SysFont("consolas", 13, bold=True)
            self.font_desc = pygame.font.SysFont("consolas", 11)
            self.font_tag = pygame.font.SysFont("consolas", 10, bold=True)

        surface.fill((12, 12, 16))
        w = surface.get_width()

        # Botón Volver
        is_back_hov = (self.hover_element == "back")
        back_col = (42, 44, 56) if is_back_hov else (28, 29, 36)
        back_border = (255, 215, 80) if is_back_hov else (60, 65, 80)
        pygame.draw.rect(surface, back_col, pygame.Rect(20, 16, 95, 32), border_radius=8)
        pygame.draw.rect(surface, back_border, pygame.Rect(20, 16, 95, 32), width=1, border_radius=8)
        surface.blit(self.font_desc.render("⬅ VOLVER", True, (220, 220, 235)), (32, 25))

        # Título y Subtítulo
        title = self.font_title.render("⚔️ CONFIGURACIÓN DEL COLISEO", True, (255, 215, 80))
        surface.blit(title, title.get_rect(center=(w // 2, 24)))
        sub = self.font_desc.render("Personaliza la arena, gladiadores y personalidades tácticas.", True, (160, 165, 180))
        surface.blit(sub, sub.get_rect(center=(w // 2, 46)))

        # 1. Tamaño de la Arena
        surface.blit(self.font_section.render("1. TAMAÑO DE LA ARENA", True, (240, 240, 245)), (34, 68))
        bw, bh, gap = 136, 36, 12
        start_x, y1 = 34, 88
        for i, (gsize, label, sub_lbl) in enumerate(self.grid_options):
            bx = start_x + i * (bw + gap)
            is_sel = (i == self.selected_grid_idx)
            is_hov = (self.hover_element == f"grid_{i}")
            if is_sel:
                bg = (48, 42, 28)
                b_border = (255, 215, 80)
                txt_c = (255, 235, 130)
            elif is_hov:
                bg = (34, 36, 46)
                b_border = (130, 135, 160)
                txt_c = (245, 245, 255)
            else:
                bg = (22, 23, 30)
                b_border = (50, 52, 65)
                txt_c = (190, 195, 210)

            pygame.draw.rect(surface, bg, pygame.Rect(bx, y1, bw, bh), border_radius=8)
            pygame.draw.rect(surface, b_border, pygame.Rect(bx, y1, bw, bh), width=2 if is_sel else 1, border_radius=8)
            l_s = self.font_btn.render(label, True, txt_c)
            surface.blit(l_s, l_s.get_rect(center=(bx + bw // 2, y1 + 12)))
            sub_s = self.font_tag.render(sub_lbl, True, (160, 165, 180) if not is_sel else (255, 220, 100))
            surface.blit(sub_s, sub_s.get_rect(center=(bx + bw // 2, y1 + 25)))

        # 2. Cantidad de Gladiadores
        surface.blit(self.font_section.render("2. CANTIDAD DE GLADIADORES", True, (240, 240, 245)), (34, 134))
        y2 = 152
        for i, cnt in enumerate(self.count_options):
            bx = start_x + i * (bw + gap)
            is_sel = (cnt == self.selected_count)
            is_hov = (self.hover_element == f"count_{cnt}")
            if is_sel:
                bg = (24, 46, 36)
                b_border = (80, 235, 150)
                txt_c = (140, 255, 190)
            elif is_hov:
                bg = (34, 36, 46)
                b_border = (130, 135, 160)
                txt_c = (245, 245, 255)
            else:
                bg = (22, 23, 30)
                b_border = (50, 52, 65)
                txt_c = (190, 195, 210)

            pygame.draw.rect(surface, bg, pygame.Rect(bx, y2, bw, 32), border_radius=8)
            pygame.draw.rect(surface, b_border, pygame.Rect(bx, y2, bw, 32), width=2 if is_sel else 1, border_radius=8)
            c_s = self.font_btn.render(f"{cnt} GLADIADORES", True, txt_c)
            surface.blit(c_s, c_s.get_rect(center=(bx + bw // 2, y2 + 16)))

        # 3. Jinetes y Personalidades
        surface.blit(self.font_section.render("3. JINETES Y PERSONALIDADES (CLIC EN RANURA PARA ROTAR)", True, (240, 240, 245)), (34, 194))
        tip_s = self.font_desc.render("Haz clic sobre cualquier ranura (o sus flechas) para cambiar su jinete táctico:", True, (150, 155, 170))
        surface.blit(tip_s, (34, 212))

        start_y = 232
        card_w = 580
        card_h = 58
        gap_card = 7
        for i in range(self.selected_count):
            by = start_y + i * (card_h + gap_card)
            fid = self.slot_factions[i]
            cfg = FACTION_CONFIGS[fid]

            is_card_hov = (self.hover_element in (f"slot_{i}", f"slot_prev_{i}", f"slot_next_{i}"))
            c_bg = (32, 34, 46) if is_card_hov else (22, 23, 31)
            c_border = cfg.head_color if is_card_hov else (55, 60, 75)

            # Tarjeta de slot
            pygame.draw.rect(surface, c_bg, pygame.Rect(34, by, card_w, card_h), border_radius=10)
            pygame.draw.rect(surface, c_border, pygame.Rect(34, by, card_w, card_h), width=2 if is_card_hov else 1, border_radius=10)

            # Badge de gladiador P1, P2...
            pygame.draw.rect(surface, (16, 17, 24), pygame.Rect(44, by + 12, 34, 34), border_radius=6)
            pygame.draw.rect(surface, cfg.head_color, pygame.Rect(44, by + 12, 34, 34), width=1, border_radius=6)
            p_s = self.font_btn.render(f"P{i+1}", True, cfg.head_color)
            surface.blit(p_s, p_s.get_rect(center=(44 + 17, by + 12 + 17)))

            # Flecha izquierda
            prev_hov = (self.hover_element == f"slot_prev_{i}")
            pygame.draw.rect(surface, (45, 48, 62) if prev_hov else (28, 30, 40), pygame.Rect(84, by + 14, 24, 30), border_radius=4)
            pygame.draw.rect(surface, (255, 215, 80) if prev_hov else (60, 65, 80), pygame.Rect(84, by + 14, 24, 30), width=1, border_radius=4)
            arr_l = self.font_btn.render("<", True, (255, 235, 120) if prev_hov else (200, 205, 220))
            surface.blit(arr_l, arr_l.get_rect(center=(84 + 12, by + 14 + 15)))

            # Círculo preview de serpiente
            cx, cy = 124, by + 29
            pygame.draw.circle(surface, cfg.head_color, (cx, cy), 10)
            pygame.draw.circle(surface, (255, 255, 255), (cx + 3, cy - 3), 3)
            pygame.draw.circle(surface, (10, 10, 15), (cx + 4, cy - 3), 1)
            pygame.draw.circle(surface, (255, 255, 255), (cx + 3, cy + 3), 3)
            pygame.draw.circle(surface, (10, 10, 15), (cx + 4, cy + 3), 1)

            # Nombre de Faccion y Tag
            name_s = self.font_btn.render(cfg.name, True, cfg.head_color)
            surface.blit(name_s, (142, by + 10))

            tag_s = self.font_tag.render(cfg.tag, True, (240, 240, 245))
            tag_rect = pygame.Rect(142 + name_s.get_width() + 8, by + 12, tag_s.get_width() + 10, 16)
            pygame.draw.rect(surface, (36, 38, 50), tag_rect, border_radius=4)
            pygame.draw.rect(surface, (70, 75, 95), tag_rect, width=1, border_radius=4)
            surface.blit(tag_s, (tag_rect.x + 5, tag_rect.y + 1))

            # Personalidad / Jinete
            pers_text = f"[{cfg.personality_title.upper()}]"
            pers_s = self.font_tag.render(pers_text, True, (255, 220, 90))
            pers_rect = pygame.Rect(tag_rect.right + 6, by + 12, pers_s.get_width() + 10, 16)
            pygame.draw.rect(surface, (44, 40, 25), pers_rect, border_radius=4)
            pygame.draw.rect(surface, (180, 145, 40), pers_rect, width=1, border_radius=4)
            surface.blit(pers_s, (pers_rect.x + 5, pers_rect.y + 1))

            # Descripción táctica
            desc_text = FACTION_TACTICAL_DESCS.get(fid, "")
            surface.blit(self.font_desc.render(desc_text, True, (165, 170, 185)), (142, by + 34))

            # Flecha derecha
            next_hov = (self.hover_element == f"slot_next_{i}")
            next_x = 34 + card_w - 36
            pygame.draw.rect(surface, (45, 48, 62) if next_hov else (28, 30, 40), pygame.Rect(next_x, by + 14, 24, 30), border_radius=4)
            pygame.draw.rect(surface, (255, 215, 80) if next_hov else (60, 65, 80), pygame.Rect(next_x, by + 14, 24, 30), width=1, border_radius=4)
            arr_r = self.font_btn.render(">", True, (255, 235, 120) if next_hov else (200, 205, 220))
            surface.blit(arr_r, arr_r.get_rect(center=(next_x + 12, by + 14 + 15)))

        # 4. Botón Iniciar Batalla
        btn_w, btn_h = 460, 50
        btn_x = (w - btn_w) // 2
        btn_y = 574
        is_start_hov = (self.hover_element == "start")
        if is_start_hov:
            s_bg = (255, 195, 45)
            s_border = (255, 235, 140)
            s_txt_col = (15, 15, 20)
        else:
            s_bg = (215, 155, 25)
            s_border = (255, 215, 80)
            s_txt_col = (12, 12, 16)

        pygame.draw.rect(surface, s_bg, pygame.Rect(btn_x, btn_y, btn_w, btn_h), border_radius=12)
        pygame.draw.rect(surface, s_border, pygame.Rect(btn_x, btn_y, btn_w, btn_h), width=2, border_radius=12)

        start_txt = pygame.font.SysFont("consolas", 16, bold=True).render("⚔️ ¡ENTRAR AL COLISEO! (INICIAR BATALLA)", True, s_txt_col)
        surface.blit(start_txt, start_txt.get_rect(center=(w // 2, btn_y + btn_h // 2)))

        info_lbl = self.font_desc.render("Presiona [ENTER] para iniciar rápido o [ESC] para volver a selección de modos", True, (130, 135, 150))
        surface.blit(info_lbl, info_lbl.get_rect(center=(w // 2, btn_y + btn_h + 16)))


class ControlsScene:
    def __init__(self, app: "ColosseumApp"):
        self.app = app
        self.font: Optional[pygame.font.Font] = None
        self.font_desc: Optional[pygame.font.Font] = None

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE: return MainMenuScene(self.app)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if 20 <= e.pos[0] <= 130 and 20 <= e.pos[1] <= 56: return MainMenuScene(self.app)
        return self

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if not self.font:
            self.font = pygame.font.SysFont("consolas", 13, bold=True)
            self.font_desc = pygame.font.SysFont("consolas", 12)

        surface.fill((12, 12, 16))
        pygame.draw.rect(surface, (28, 29, 36), pygame.Rect(20, 20, 100, 34), border_radius=8)
        surface.blit(self.font_desc.render("⬅ VOLVER", True, (220, 220, 230)), (32, 29))

        title = pygame.font.SysFont("consolas", 22, bold=True).render("CONTROLES DE TECLADO", True, (245, 245, 245))
        surface.blit(title, title.get_rect(center=(surface.get_width() // 2, 40)))

        controls = [
            ("TECLA [ K ]", "Pausar / Reanudar (Abre panel modal)"),
            ("TECLA [ J ]", "Disminuir velocidad (-2 FPS)"),
            ("TECLA [ L ]", "Aumentar velocidad (+2 FPS)"),
            ("TECLA [ W ]", "Alternar Modo Trascendente (Sin Paredes)"),
            ("TECLA [ X ]", "Spawnear Bomba con cuenta regresiva"),
            ("TECLA [ Z ]", "Spawnear Comida Extra en el tablero"),
            ("TECLA [ B ]", "Desatar Ataque de BOMBA ATÓMICA en 3D"),
            ("TECLA [ E ]", "Activar MODO ÉXTASIS (Arcoíris a 2x)"),
            ("TECLA [ G ]", "Activar MODO DORADO (Invulnerable a 3x)"),
            ("TECLA [ R ]", "Reiniciar ronda actual"),
            ("TECLA [ ESC ]", "Pausar / Volver al Menú Principal")
        ]

        start_y = 95
        for i, (kname, desc) in enumerate(controls):
            y = start_y + i * 36
            surface.blit(self.font.render(kname, True, (255, 215, 80)), (36, y))
            surface.blit(self.font_desc.render(f"➜ {desc}", True, (200, 205, 220)), (175, y))

class TikTokGuideScene:
    def __init__(self, app: "ColosseumApp"):
        self.app = app
        self.font: Optional[pygame.font.Font] = None
        self.font_desc: Optional[pygame.font.Font] = None

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE: return MainMenuScene(self.app)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if 20 <= e.pos[0] <= 130 and 20 <= e.pos[1] <= 56: return MainMenuScene(self.app)
        return self

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if not self.font:
            self.font = pygame.font.SysFont("consolas", 13, bold=True)
            self.font_desc = pygame.font.SysFont("consolas", 12)

        surface.fill((12, 12, 16))
        pygame.draw.rect(surface, (28, 29, 36), pygame.Rect(20, 20, 100, 34), border_radius=8)
        surface.blit(self.font_desc.render("⬅ VOLVER", True, (220, 220, 230)), (32, 29))

        title = pygame.font.SysFont("consolas", 22, bold=True).render("GUÍA DE TIKTOK LIVE", True, (245, 245, 245))
        surface.blit(title, title.get_rect(center=(surface.get_width() // 2, 40)))

        gifts = [
            ("🌹 ROSA", "Spawnea Bombas normales letales"),
            ("🍎 TIKTOK", "Spawnea Manzanas adicionales"),
            ("🎨 GG", "Cambia el color de la serpiente"),
            ("💖 CORAZÓN / CAP", "Activa MODO ÉXTASIS (Arcoíris a 2x)"),
            ("👑 CORONA / DRAGÓN", "Activa MODO DORADO (Invulnerable a 3x)"),
            ("☢️ LEÓN / UNIVERSO", "Ataque Cinematográfico BOMBA ATÓMICA"),
            ("🎆 FIREWORK", "Reinicia la ronda del juego"),
            ("💬 FACCIONES", "Apoya con #Rojo, #Verde, #Azul, #Morado")
        ]

        start_y = 100
        for i, (gname, desc) in enumerate(gifts):
            y = start_y + i * 42
            surface.blit(self.font.render(gname, True, (255, 120, 160)), (36, y))
            surface.blit(self.font_desc.render(f"➜ {desc}", True, (210, 215, 230)), (240, y))

class PlayScene:
    def __init__(self, app: "ColosseumApp", game_mode: GameMode, setup: Optional[ColosseumMatchSetup] = None):
        self.app = app
        self.game_mode = game_mode
        self.setup = setup
        self.state = self.app.create_initial_state(game_mode, setup=setup)
        self.pause_overlay_open = False
        self.pause_buttons = [("▶ REANUDAR", "resume"), ("🔄 REINICIAR", "restart"), ("🚪 MENÚ PRINCIPAL", "menu")]
        self.pause_hover = -1

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE or e.key == pygame.K_k:
                    self.pause_overlay_open = not self.pause_overlay_open
                    self.state.paused = self.pause_overlay_open
                elif e.key == pygame.K_r:
                    self.app.rules.reset_round(self.state, pygame.time.get_ticks())

                self.app.input.handle_keydown(e.key)

            if self.pause_overlay_open:
                if e.type == pygame.MOUSEMOTION:
                    self.pause_hover = self._get_pause_btn(e.pos)
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    idx = self._get_pause_btn(e.pos)
                    if idx == 0:
                        self.pause_overlay_open = False
                        self.state.paused = False
                    elif idx == 1:
                        self.app.rules.reset_round(self.state, pygame.time.get_ticks())
                        self.pause_overlay_open = False
                        self.state.paused = False
                    elif idx == 2:
                        return MainMenuScene(self.app)

        return self

    def _get_pause_btn(self, pos: Tuple[int, int]) -> int:
        w, h = self.app.renderer.window_size()
        bw, bh = 260, 42
        bx = (w - bw) // 2
        start_y = (h - 200) // 2 + 50
        for i in range(len(self.pause_buttons)):
            by = start_y + i * 54
            if bx <= pos[0] <= bx + bw and by <= pos[1] <= by + bh: return i
        return -1

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        self.app.renderer.render(surface, self.state, now_ms)
        if self.pause_overlay_open:
            self._render_pause_menu(surface)

    def _render_pause_menu(self, surface: pygame.Surface) -> None:
        w, h = surface.get_width(), surface.get_height()
        dark = pygame.Surface((w, h), pygame.SRCALPHA)
        dark.fill((10, 10, 14, 190))
        surface.blit(dark, (0, 0))

        pw, ph = 320, 230
        px, py = (w - pw) // 2, (h - ph) // 2
        pygame.draw.rect(surface, (20, 21, 28), pygame.Rect(px, py, pw, ph), border_radius=14)
        pygame.draw.rect(surface, (255, 215, 80), pygame.Rect(px, py, pw, ph), width=2, border_radius=14)

        title = pygame.font.SysFont("consolas", 18, bold=True).render("JUEGO EN PAUSA", True, (255, 220, 90))
        surface.blit(title, title.get_rect(center=(w // 2, py + 26)))

        bw, bh = 260, 42
        bx = (w - bw) // 2
        start_y = py + 56
        btn_font = pygame.font.SysFont("consolas", 14, bold=True)
        for i, (label, _) in enumerate(self.pause_buttons):
            by = start_y + i * 54
            is_hover = (i == self.pause_hover)
            bcol = (38, 40, 52) if is_hover else (26, 27, 34)
            b_border = (255, 215, 80) if is_hover else (60, 65, 80)
            txt_col = (255, 235, 120) if is_hover else (220, 225, 235)

            pygame.draw.rect(surface, bcol, pygame.Rect(bx, by, bw, bh), border_radius=8)
            pygame.draw.rect(surface, b_border, pygame.Rect(bx, by, bw, bh), width=2, border_radius=8)
            txt_s = btn_font.render(label, True, txt_col)
            surface.blit(txt_s, txt_s.get_rect(center=(bx + bw // 2, by + bh // 2)))

# ============================================================
# Aplicación Principal
# ============================================================

class ColosseumApp:
    def __init__(self):
        self.rng = random.Random()
        self.renderer = ColosseumRenderer()
        self.rules = ColosseumRules(self.rng)
        self.event_bus = EventBus()
        self.actions = ActionSystem(self)
        self.input = ExternalInputController(self.event_bus)
        self.udp = UDPReceiver(UDP_HOST, UDP_PORT)

        self.patterns = [SpiralPattern(), PerimeterPattern(), ZigZagPattern(), SmoothFlowPattern()]
        self.bot = MultiAgentBotController(self.rng, self.patterns)

    def create_initial_state(self, game_mode: GameMode = GameMode.BATTLE_ROYALE, setup: Optional[ColosseumMatchSetup] = None) -> ColosseumState:
        g_size = setup.grid_size if setup else GRID_SIZE
        c_px = max(10, 616 // g_size)

        starts_all = [
            (Point(4, 4), Direction.RIGHT),
            (Point(g_size - 5, 4), Direction.DOWN),
            (Point(g_size - 5, g_size - 5), Direction.LEFT),
            (Point(4, g_size - 5), Direction.UP),
            (Point(g_size // 2, g_size // 2), Direction.RIGHT),
        ]
        starts_2p = [
            (Point(4, g_size // 2), Direction.RIGHT),
            (Point(g_size - 5, g_size // 2), Direction.LEFT),
        ]
        starts_1p = [
            (Point(g_size // 2, g_size // 2), Direction.RIGHT)
        ]

        if game_mode == GameMode.BATTLE_ROYALE:
            if setup and setup.factions:
                factions = setup.factions
            else:
                factions = [FactionId.RED, FactionId.GREEN, FactionId.BLUE, FactionId.PURPLE]
            starts = starts_all
            food_cnt = max(len(factions), (g_size * g_size) // 100)
        elif game_mode == GameMode.DUEL_1V1:
            factions = [FactionId.RED, FactionId.GREEN]
            starts = starts_2p
            food_cnt = 2
        else:
            factions = [FactionId.GREEN] if game_mode == GameMode.HYPNOTIC else [FactionId.RED]
            starts = starts_1p
            food_cnt = 1

        snakes: List[ColosseumSnake] = []
        for i, fid in enumerate(factions):
            cfg = FACTION_CONFIGS[fid]
            start_p, start_d = starts[i % len(starts)]
            body = deque([Point(start_p.x - start_d.dx * j, start_p.y - start_d.dy * j) for j in range(INITIAL_SNAKE_LENGTH)])
            snakes.append(ColosseumSnake(
                snake_id=i, faction=cfg, body=body, direction=start_d, pattern_idx=i
            ))

        now_ms = pygame.time.get_ticks() if pygame.get_init() else 0
        state = ColosseumState(
            game_mode=game_mode, snakes=snakes, foods=[], bombs={}, wall_collision=True,
            grid_size=g_size, cell_px=c_px,
            fps_base=INITIAL_FPS, countdown_active=True, countdown_start_ms=now_ms
        )

        for _ in range(food_cnt):
            p = self.random_free_cell(state)
            if p: state.foods.append(Food(pos=p, value=1))
        return state

    def random_free_cell(self, state: ColosseumState) -> Optional[Point]:
        return self.rules.random_free_cell(state)

    def reset_round(self, state: ColosseumState, hard: bool = False, now_ms: int = 0) -> None:
        self.rules.reset_round(state, now_ms)
        if hard:
            for s in state.snakes: s.wins = 0; s.score = 0

    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption("Snake — The Colosseum & SaperaAI v2.0")
        surface = pygame.display.set_mode(self.renderer.window_size())
        clock = pygame.time.Clock()

        scene: Optional[Scene] = MainMenuScene(self)

        while scene is not None:
            now_ms = pygame.time.get_ticks()
            events = pygame.event.get()
            scene = scene.handle(events)
            if scene is None: break

            self.udp.poll(self.event_bus)

            if isinstance(scene, PlayScene):
                drained = self.event_bus.drain()
                if drained: self.actions.dispatch(drained, scene.state, now_ms)

                if not scene.state.paused and scene.state.round_winner is None:
                    self.bot.decide_all(scene.state, now_ms)
                    self.rules.step(scene.state, now_ms)

            scene.render(surface, now_ms)
            pygame.display.flip()

            fps = scene.state.fps_base if isinstance(scene, PlayScene) else 30
            clock.tick(fps)

        pygame.quit()

def main():
    print("==========================================================")
    print(" Snake — The Colosseum v2.0 (Ultimate Edition — SaperaAI)")
    print(f" UDP Listening: {UDP_HOST}:{UDP_PORT}")
    print("==========================================================")
    ColosseumApp().run()

if __name__ == "__main__":
    main()
