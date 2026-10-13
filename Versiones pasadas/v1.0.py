from __future__ import annotations

import sys
import math
import random
from dataclasses import dataclass
from enum import Enum
from collections import deque, Counter
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

INITIAL_FOODS = 1  # “originales” (respawnean). Recomendado dejar en 1
MAX_EXTRA_FOODS_SIMULTANEOUS = 1  # tecla Z añade extras hasta este máximo; extras NO respawnean

BOMB_DURATION_MS = 5000
BOMB_SPAWN_COUNT = 1  # tecla X spawnea esta cantidad simultánea

GRID_SIZE = 16  # 16 => 16x16
WALL_COLLISION = True

INITIAL_FPS = 12

# BOT TUNING (SOLO estas dos variables)
PATTERN_VS_FOOD = 7       # 1..10 (1=mantener patrón, 10=ir por comida lo más rápido posible, SIEMPRE con retorno seguro)
PATTERN_VS_DYNAMISM = 6   # 1..10 (1=muy patrón, 10=sin patrón)


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


def add_dir(p: Point, d: Direction) -> Point:
    return Point(p.x + d.dx, p.y + d.dy)


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
    background_id: int

    # bot instrumentation (para anti-ciclos)
    tick: int
    head_history: Deque[Point]    # tamaño fijo
    cycle_penalty_until: int      # ticks hasta los que castigamos bucles


# ============================================================
# EventBus + Actions (listo para Listener externo)
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
    def __init__(self, max_extra: int):
        self.max_extra = max(0, int(max_extra))

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        extras = [f for f in state.foods if not f.respawn]
        if len(extras) >= self.max_extra:
            return
        p = random_free_cell(state, cfg, rng)
        if p is None:
            return
        state.foods.append(Food(pos=p, respawn=False))


class SpeedUpAction:
    def __init__(self, delta: int):
        self.delta = int(delta)

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        cfg.fps = min(60, cfg.fps + self.delta)


class SlowDownAction:
    def __init__(self, delta: int):
        self.delta = int(delta)

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        cfg.fps = max(1, cfg.fps - self.delta)


class ChangeSnakeColorAction:
    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        state.snake_color_index = (state.snake_color_index + 1) % 8


class ActionSystem:
    def __init__(self):
        self.registry: Dict[str, Any] = {
            "SPAWN_BOMB": lambda ev: SpawnBombAction(
                count=int((ev.payload or {}).get("count", BOMB_SPAWN_COUNT)),
                ttl_ms=int((ev.payload or {}).get("ttl_ms", BOMB_DURATION_MS)),
            ),
            "SPAWN_EXTRA_FOOD": lambda ev: SpawnExtraFoodAction(
                max_extra=int((ev.payload or {}).get("max_extra", MAX_EXTRA_FOODS_SIMULTANEOUS))
            ),
            "SPEED_UP": lambda ev: SpeedUpAction(delta=int((ev.payload or {}).get("delta", 1))),
            "SLOW_DOWN": lambda ev: SlowDownAction(delta=int((ev.payload or {}).get("delta", 1))),
            "CHANGE_SNAKE_COLOR": lambda ev: ChangeSnakeColorAction(),
        }

    def dispatch(self, events: List[GameEvent], state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        for ev in events:
            factory = self.registry.get(ev.type)
            if factory is None:
                continue
            action: IGameAction = factory(ev)
            action.apply(state, cfg, rng, now_ms)


# ============================================================
# Patrones (múltiples, rotación)
# ============================================================

class Pattern(Protocol):
    name: str
    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        ...


class SpiralPattern:
    name = "spiral"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        # Sesgo a capas: intenta bajar layer gradualmente => da sensación de espiral
        head = state.snake[0]
        n = cfg.n
        cur_layer = layer_index(head, n)

        # preferir movimientos que mantengan o reduzcan layer, y que sean suaves
        best = state.direction
        best_score = -1e9
        for d in DIRS:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue
            lyr = layer_index(nxt, n)
            score = 0.0
            score += (cur_layer - lyr) * 3.0         # bajar layer = más score
            score += (1.0 if d == state.direction else 0.0) * 0.7
            score += rng.uniform(-0.05, 0.05)
            if score > best_score:
                best_score = score
                best = d
        return best


class PerimeterPattern:
    name = "perimeter"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        # Recorre bordes/capas externas: “cuadrado”
        head = state.snake[0]
        n = cfg.n
        # objetivo: quedarse en layer 0 o 1 si se puede
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

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        # Zigzag “visual”: alterna prioridad horizontal/vertical según tick
        head = state.snake[0]
        prefer_horizontal = (state.tick // 20) % 2 == 0
        if prefer_horizontal:
            return Direction.RIGHT if head.x < cfg.n - 1 else Direction.LEFT
        return Direction.DOWN if head.y < cfg.n - 1 else Direction.UP


class DiagonalPattern:
    name = "diagonal"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        # Diagonal suave en “S”
        head = state.snake[0]
        t = state.tick // 25
        if t % 2 == 0:
            return Direction.RIGHT if head.x < cfg.n - 1 else Direction.DOWN
        return Direction.LEFT if head.x > 0 else Direction.DOWN


class SmoothRandomPattern:
    name = "smooth_random"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        # Random pero con inercia (no se ve nervioso)
        if rng.random() < 0.75:
            return state.direction
        # escoger entre giros (izq/der) preferidos
        cur = state.direction
        turns = {
            Direction.UP: [Direction.LEFT, Direction.RIGHT],
            Direction.DOWN: [Direction.LEFT, Direction.RIGHT],
            Direction.LEFT: [Direction.UP, Direction.DOWN],
            Direction.RIGHT: [Direction.UP, Direction.DOWN],
        }
        return rng.choice(turns[cur])


# Hamilton como “patrón” posible, pero NO dominante: solo se usa si cae elegido
class HamiltonPattern:
    name = "hamilton"

    def __init__(self, cycle: List[Point]):
        self.idx = {p: i for i, p in enumerate(cycle)}
        self.nxt = {cycle[i]: cycle[(i + 1) % len(cycle)] for i in range(len(cycle))}

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        if head not in self.nxt:
            return state.direction
        nxt = self.nxt[head]
        return dir_from_to(head, nxt)


def build_hamilton_cycle(n: int) -> List[Point]:
    # construcción simple para n par (GRID_SIZE por defecto 16)
    if n % 2 == 1:
        # en grids impares, no garantizamos ciclo; igual devolvemos recorrido serpiente parcial
        cycle: List[Point] = []
        for y in range(n):
            rng = range(n) if y % 2 == 0 else range(n - 1, -1, -1)
            for x in rng:
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
# “Paso de cabeza” con wall / wrap
# ============================================================

def head_step(head: Point, d: Direction, cfg: GameConfig) -> Optional[Point]:
    nxt = Point(head.x + d.dx, head.y + d.dy)
    if cfg.wall_collision:
        return nxt if in_bounds(nxt, cfg.n) else None
    return wrap(nxt, cfg.n)


# ============================================================
# Reglas del juego (comidas + bombas TTL)
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

        # bot instrumentation
        state.tick += 1
        state.head_history.append(state.snake[0])
        while len(state.head_history) > 180:
            state.head_history.popleft()

    def _spawn_original_food(self, state: GameState, cfg: GameConfig) -> None:
        # mantener cantidad de originales = INITIAL_FOODS (normalmente 1)
        # si ya hay suficientes originales, no spawnear extra
        originals = [f for f in state.foods if f.respawn]
        if len(originals) >= INITIAL_FOODS:
            return
        p = random_free_cell(state, cfg, self.rng)
        if p is None:
            return
        state.foods.append(Food(pos=p, respawn=True))


# ============================================================
# BOT (supervivencia primero, múltiples patrones, anti-ciclos)
# ============================================================

class BotController:
    def __init__(self, rng: random.Random, patterns: List[Pattern]):
        self.rng = rng
        self.patterns = patterns
        self.current_idx = 0
        self.next_switch_tick = 0

        # normaliza sliders 1..10
        self.pattern_vs_food = max(1, min(10, int(PATTERN_VS_FOOD)))
        self.pattern_vs_dyn = max(1, min(10, int(PATTERN_VS_DYNAMISM)))

    def choose_direction(self, state: GameState, cfg: GameConfig) -> Direction:
        # 1) rotación de patrones (más dinamismo => cambia más seguido)
        self._maybe_switch_pattern(state)

        # 2) calcular movimientos seguros (supervivencia)
        safe_moves = self._safe_moves(state, cfg)
        if not safe_moves:
            # si no hay, ya está muerto en el próximo tick: escoger el que “más demore” la muerte (heurística)
            return self._best_delay_death_move(state, cfg)

        # 3) anti-ciclos: detectar loops >2 vueltas
        loop_detected = self._detect_loop(state)
        if loop_detected and state.tick >= state.cycle_penalty_until:
            # activar “penalización de loop” por un rato
            state.cycle_penalty_until = state.tick + 40

        # 4) scoring: patrón vs comida vs dinamismo + evitación cabeza/cola
        pat = self.patterns[self.current_idx]
        pat_dir = pat.preferred_direction(state, cfg, self.rng)

        # comida objetivo = más cercana (entre todas)
        food_targets = [f.pos for f in state.foods]
        food_target = min(food_targets, key=lambda p: manhattan(state.snake[0], p)) if food_targets else state.snake[0]

        # pesos (solo dependen de sliders)
        # - pattern_weight cae cuando PATTERN_VS_DYNAMISM sube
        # - food_weight sube cuando PATTERN_VS_FOOD sube
        pattern_weight = (11 - self.pattern_vs_dyn) / 10.0  # 1..0.1
        food_weight = self.pattern_vs_food / 10.0           # 0.1..1
        # balance: queremos que patrón siempre exista, pero no sea obligatorio
        # el motor lo hace con "prefer_dir bonus" y "layer style", no con hard locks.

        # presión por bombas existentes (si hay muchas, prioriza comida menos agresivo)
        bombs_pressure = min(1.0, len(state.bombs) / 8.0)
        food_weight *= (1.0 - 0.35 * bombs_pressure)

        head = state.snake[0]
        tail = state.snake[-1]

        best_d = safe_moves[0]
        best_score = -1e18

        for d in safe_moves:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue

            # distancia a comida (más pequeño mejor)
            dist_food = manhattan(nxt, food_target)

            # patrón: bonus por seguir el patrón actual
            pat_bonus = 1.0 if d == pat_dir else 0.0

            # dinamismo: a mayor dinamismo, más probabilidad de NO seguir el patrón
            # implementado como jitter y menor bonus de patrón
            jitter = (self.pattern_vs_dyn / 10.0) * 0.35
            rand_j = self.rng.uniform(-jitter, jitter)

            # suavidad visual (menos cambios bruscos)
            straight_bonus = 0.25 if d == state.direction else 0.0

            # NO querer cabeza pegada a cola constantemente
            head_tail_dist = manhattan(nxt, tail)
            tail_avoid = 0.0
            # penaliza estar demasiado cerca, a menos que sea necesario por seguridad
            if head_tail_dist <= 2:
                tail_avoid = -1.2 * (3 - head_tail_dist)  # -2.4 si dist 1, -1.2 si dist 2

            # anti-loop: si loop activo, penalizar repetir patrón de camino (forzar desviación)
            loop_pen = 0.0
            if state.tick < state.cycle_penalty_until:
                # penaliza volver hacia el mismo "trazo" (simple: si nxt aparece demasiado en historia reciente)
                occ = sum(1 for p in list(state.head_history)[-80:] if p == nxt)
                loop_pen = -0.8 * min(4, occ)

            # score total
            # supervivencia ya garantizada por safe_moves.
            score = 0.0
            score += (-dist_food) * (2.3 * food_weight)
            score += pat_bonus * (2.0 * pattern_weight)
            score += straight_bonus
            score += tail_avoid
            score += loop_pen
            score += rand_j

            # prioridad extra: si nxt es comida ahora, sumar grande
            if any(nxt == f.pos for f in state.foods):
                score += 6.0

            if score > best_score:
                best_score = score
                best_d = d

        return best_d

    # --------------------------------------------------------

    def _maybe_switch_pattern(self, state: GameState) -> None:
        # intervalo base y probabilidad de cambio
        # más dinamismo => cambia más rápido y más aleatorio
        dyn = self.pattern_vs_dyn / 10.0  # 0.1..1
        base = 55  # ticks
        interval = int(base * (1.10 - 0.70 * dyn))  # 55..~22
        interval = max(18, interval)

        if state.tick >= self.next_switch_tick:
            # cambia patrón con prob según dinamismo
            # dyn alto => casi siempre cambia
            p = 0.25 + 0.60 * dyn
            if self.rng.random() < p:
                self.current_idx = self.rng.randrange(0, len(self.patterns))
            self.next_switch_tick = state.tick + interval

    def _safe_moves(self, state: GameState, cfg: GameConfig) -> List[Direction]:
        """
        Supervivencia primero:
        Un movimiento es “seguro” si:
        - no choca con muro (o wrap)
        - no choca con bomba
        - no choca con cuerpo (considerando que la cola se moverá si NO come)
        - y además existe ruta desde la nueva cabeza hacia la cola (escape) en el grid libre
          usando flood-fill con el cuerpo proyectado.
        """
        head = state.snake[0]
        tail = state.snake[-1]
        bombs = set(state.bombs.keys())
        snake_list = list(state.snake)
        snake_set = set(snake_list)

        safe: List[Direction] = []

        for d in DIRS:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue
            if nxt in bombs:
                continue

            # ¿come?
            eats = any(nxt == f.pos for f in state.foods)

            # cuerpo proyectado
            if nxt in snake_set:
                if not eats and nxt == tail:
                    # cola se mueve, OK
                    pass
                else:
                    continue

            projected_snake = deque(snake_list)
            projected_snake.appendleft(nxt)
            if not eats:
                projected_snake.pop()

            if not self._has_escape(projected_snake, bombs, cfg):
                continue

            safe.append(d)

        return safe

    def _has_escape(self, projected_snake: Deque[Point], bombs: Set[Point], cfg: GameConfig) -> bool:
        """
        Escape = hay camino de head a tail en el “espacio libre” (no-bombas, no-cuerpo salvo tail).
        Esto evita meterse en cavidades sin salida.
        """
        head = projected_snake[0]
        tail = projected_snake[-1]
        blocked = set(projected_snake)
        # permitir llegar al tail
        blocked.remove(tail)
        blocked |= bombs

        # BFS
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
        # Cuando no hay safe_moves, elegir el movimiento que menos “obstrucción” tenga (heurístico)
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

            # contar libres alrededor de nxt
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
        """
        “Prohibidos ciclos infinitos”:
        Si detectamos que la cabeza repite un mismo ciclo corto (4..22) más de 2 veces,
        activamos penalización para forzar desviación.
        """
        hist = list(state.head_history)
        if len(hist) < 90:
            return False

        # probar longitudes de ciclo cortas
        for L in range(4, 23):
            a = hist[-L:]
            b = hist[-2*L:-L]
            c = hist[-3*L:-2*L]
            if a == b == c:
                return True
        return False


# ============================================================
# Renderer (fondos + serpiente + comida + bombas + HUD)
# ============================================================

class Renderer:
    def __init__(self, cell_px: int = 32, margin_px: int = 16, hud_h: int = 44):
        self.cell_px = cell_px
        self.margin_px = margin_px
        self.hud_h = hud_h
        self.font: Optional["pygame.font.Font"] = None

        # 8 paletas “bonitas”
        self.snake_palettes = [
            ((95, 235, 140), (65, 175, 105)),   # green
            ((120, 190, 255), (60, 130, 210)),  # blue
            ((255, 175, 90), (205, 120, 55)),   # orange
            ((255, 120, 170), (200, 75, 125)),  # pink
            ((220, 220, 220), (140, 140, 140)), # gray
            ((210, 140, 255), (145, 85, 200)),  # purple
            ((255, 235, 110), (205, 175, 60)),  # yellow
            ((120, 255, 220), (70, 200, 170)),  # mint
        ]

    def window_size(self, n: int) -> Tuple[int, int]:
        w = n * self.cell_px + 2 * self.margin_px
        h = n * self.cell_px + 2 * self.margin_px + self.hud_h
        return w, h

    def render(self, surface: "pygame.Surface", state: GameState, cfg: GameConfig, now_ms: int, current_pattern_name: str) -> None:
        if self.font is None:
            self.font = pygame.font.SysFont("consolas", 18)

        # fondo + “card” del tablero
        surface.fill((12, 12, 14))
        self._draw_background(surface, state, cfg)

        # HUD
        pygame.draw.rect(surface, (18, 18, 22), pygame.Rect(0, 0, surface.get_width(), self.margin_px + self.hud_h))
        self._text(surface, f"Score: {state.score}   FPS: {cfg.fps}   Pattern: {current_pattern_name}", (self.margin_px, 10), (235, 235, 235))
        self._text(surface, "J/L speed | X bombs | Z extra food | C color | R restart | ESC menu",
                   (self.margin_px, 28), (160, 160, 160))

        # bombs
        for p, exp in state.bombs.items():
            self._draw_bomb(surface, p, exp, now_ms, cfg)

        # foods
        for f in state.foods:
            if f.respawn:
                self._draw_apple(surface, f.pos, cfg)
            else:
                self._draw_berry(surface, f.pos, cfg)

        # snake
        self._draw_snake(surface, list(state.snake), state.direction, state.snake_color_index, cfg)

        if not state.alive:
            self._text(surface, "GAME OVER — R reinicia | ESC menú", (self.margin_px, 50), (255, 200, 120))

    # --------------------------------------------------------

    def _origin(self) -> Tuple[int, int]:
        return self.margin_px, self.margin_px + self.hud_h

    def _cell_center(self, p: Point, cfg: GameConfig) -> Tuple[int, int]:
        ox, oy = self._origin()
        return (ox + p.x * self.cell_px + self.cell_px // 2,
                oy + p.y * self.cell_px + self.cell_px // 2)

    def _draw_background(self, surface: "pygame.Surface", state: GameState, cfg: GameConfig) -> None:
        ox, oy = self._origin()
        n = cfg.n
        board_w = n * self.cell_px
        board_h = n * self.cell_px
        board_rect = pygame.Rect(ox - 6, oy - 6, board_w + 12, board_h + 12)
        pygame.draw.rect(surface, (20, 20, 24), board_rect, border_radius=14)

        # mapas: 0=grass, 1=chess, 2=sky
        if state.background_id % 3 == 0:
            self._bg_grass(surface, cfg)
        elif state.background_id % 3 == 1:
            self._bg_chess(surface, cfg)
        else:
            self._bg_sky(surface, cfg)

        # grid sutil encima
        grid_color = (38, 38, 44)
        for x in range(n + 1):
            px = ox + x * self.cell_px
            pygame.draw.line(surface, grid_color, (px, oy), (px, oy + board_h), 1)
        for y in range(n + 1):
            py = oy + y * self.cell_px
            pygame.draw.line(surface, grid_color, (ox, py), (ox + board_w, py), 1)

    def _bg_grass(self, surface: "pygame.Surface", cfg: GameConfig) -> None:
        ox, oy = self._origin()
        n = cfg.n
        for y in range(n):
            for x in range(n):
                base = 45 + ((x * 7 + y * 11) % 15)
                col = (20, base + 60, 25)
                pygame.draw.rect(surface, col, pygame.Rect(ox + x * self.cell_px, oy + y * self.cell_px, self.cell_px, self.cell_px))

    def _bg_chess(self, surface: "pygame.Surface", cfg: GameConfig) -> None:
        ox, oy = self._origin()
        n = cfg.n
        for y in range(n):
            for x in range(n):
                if (x + y) % 2 == 0:
                    col = (34, 34, 40)
                else:
                    col = (26, 26, 32)
                pygame.draw.rect(surface, col, pygame.Rect(ox + x * self.cell_px, oy + y * self.cell_px, self.cell_px, self.cell_px))

    def _bg_sky(self, surface: "pygame.Surface", cfg: GameConfig) -> None:
        ox, oy = self._origin()
        n = cfg.n
        for y in range(n):
            for x in range(n):
                t = y / max(1, n - 1)
                col = (int(30 + 20 * t), int(60 + 60 * t), int(90 + 90 * t))
                pygame.draw.rect(surface, col, pygame.Rect(ox + x * self.cell_px, oy + y * self.cell_px, self.cell_px, self.cell_px))
        # nubes pixeladas simples
        for k in range(6):
            cx = (k * 3 + 2) % n
            cy = (k * 2 + 1) % n
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    x = cx + dx
                    y = cy + dy
                    if 0 <= x < n and 0 <= y < n and (abs(dx) + abs(dy) <= 2):
                        pygame.draw.rect(surface, (200, 210, 220),
                                         pygame.Rect(ox + x * self.cell_px + 6, oy + y * self.cell_px + 6, self.cell_px - 12, self.cell_px - 12),
                                         border_radius=6)

    def _draw_snake(self, surface: "pygame.Surface", pts: List[Point], direction: Direction, color_idx: int, cfg: GameConfig) -> None:
        if not pts:
            return
        head_col, body_col = self.snake_palettes[color_idx % len(self.snake_palettes)]
        shadow = (14, 14, 16)

        r_body = max(6, self.cell_px // 2 - 7)
        r_head = r_body + 2
        r_tail = max(5, r_body - 2)

        centers = [self._cell_center(p, cfg) for p in pts]

        # “tubo”
        for i in range(len(centers) - 1):
            pygame.draw.line(surface, shadow, centers[i], centers[i + 1], r_body * 2 + 6)
        for i in range(len(centers) - 1):
            pygame.draw.line(surface, body_col, centers[i], centers[i + 1], r_body * 2)

        # body nodes
        for i in range(1, len(centers) - 1):
            pygame.draw.circle(surface, body_col, centers[i], r_body)

        # tail
        pygame.draw.circle(surface, body_col, centers[-1], r_tail)

        # head
        pygame.draw.circle(surface, head_col, centers[0], r_head)
        self._draw_head_eyes(surface, centers[0], direction, r_head)

    def _draw_head_eyes(self, surface: "pygame.Surface", c: Tuple[int, int], d: Direction, r: int) -> None:
        cx, cy = c
        if d == Direction.UP:
            o1 = (cx - r // 3, cy - r // 3); o2 = (cx + r // 3, cy - r // 3)
        elif d == Direction.DOWN:
            o1 = (cx - r // 3, cy + r // 3); o2 = (cx + r // 3, cy + r // 3)
        elif d == Direction.LEFT:
            o1 = (cx - r // 3, cy - r // 3); o2 = (cx - r // 3, cy + r // 3)
        else:
            o1 = (cx + r // 3, cy - r // 3); o2 = (cx + r // 3, cy + r // 3)

        pygame.draw.circle(surface, (12, 12, 12), o1, max(2, r // 6))
        pygame.draw.circle(surface, (12, 12, 12), o2, max(2, r // 6))

    def _draw_apple(self, surface: "pygame.Surface", p: Point, cfg: GameConfig) -> None:
        cx, cy = self._cell_center(p, cfg)
        r = max(6, self.cell_px // 2 - 8)
        pygame.draw.circle(surface, (220, 70, 70), (cx, cy), r)
        pygame.draw.circle(surface, (245, 120, 120), (cx - r // 3, cy - r // 3), max(2, r // 3))
        pygame.draw.rect(surface, (110, 75, 45), pygame.Rect(cx - 2, cy - r - 4, 4, 10), border_radius=2)
        leaf = [(cx + 2, cy - r - 2), (cx + r // 2 + 6, cy - r - 8), (cx + r // 2, cy - r + 6)]
        pygame.draw.polygon(surface, (70, 190, 90), leaf)

    def _draw_berry(self, surface: "pygame.Surface", p: Point, cfg: GameConfig) -> None:
        # comida extra distinta visualmente (morado)
        cx, cy = self._cell_center(p, cfg)
        r = max(6, self.cell_px // 2 - 9)
        pygame.draw.circle(surface, (190, 120, 255), (cx, cy), r)
        pygame.draw.circle(surface, (230, 190, 255), (cx - r // 4, cy - r // 4), max(2, r // 3))

    def _draw_bomb(self, surface: "pygame.Surface", p: Point, exp_ms: int, now_ms: int, cfg: GameConfig) -> None:
        cx, cy = self._cell_center(p, cfg)
        r = max(6, self.cell_px // 2 - 9)

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
# Scenes (menu + play)
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
        self.kbd_dir = self.state.direction

    def handle(self, events: List["pygame.event.Event"]) -> Optional["Scene"]:
        for e in events:
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return MenuScene(self.app)
                if e.key == pygame.K_r:
                    self.state = self.app.new_game_state()

                # controles manuales (simulan TikTok / testing)
                if e.key == pygame.K_j:
                    self.app.event_bus.emit(GameEvent("SPEED_UP", {"delta": 1}))
                if e.key == pygame.K_l:
                    self.app.event_bus.emit(GameEvent("SLOW_DOWN", {"delta": 1}))
                if e.key == pygame.K_x:
                    self.app.event_bus.emit(GameEvent("SPAWN_BOMB", {"count": BOMB_SPAWN_COUNT, "ttl_ms": BOMB_DURATION_MS}))
                if e.key == pygame.K_z:
                    self.app.event_bus.emit(GameEvent("SPAWN_EXTRA_FOOD", {"max_extra": MAX_EXTRA_FOODS_SIMULTANEOUS}))
                if e.key == pygame.K_c:
                    self.app.event_bus.emit(GameEvent("CHANGE_SNAKE_COLOR"))

                # teclado
                if not self.bot_mode:
                    self._handle_dir_key(e.key)

        return self

    def _handle_dir_key(self, key: int) -> None:
        mapping = {
            pygame.K_UP: Direction.UP, pygame.K_w: Direction.UP,
            pygame.K_DOWN: Direction.DOWN, pygame.K_s: Direction.DOWN,
            pygame.K_LEFT: Direction.LEFT, pygame.K_a: Direction.LEFT,
            pygame.K_RIGHT: Direction.RIGHT, pygame.K_d: Direction.RIGHT,
        }
        if key not in mapping:
            return
        cand = mapping[key]
        if (cand.dx + self.kbd_dir.dx == 0) and (cand.dy + self.kbd_dir.dy == 0):
            return
        self.kbd_dir = cand

    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        # pattern name para HUD
        pat_name = self.app.current_pattern_name()
        self.app.renderer.render(surface, self.state, self.app.cfg, now_ms, pat_name)


# ============================================================
# App (engine)
# ============================================================

class App:
    def __init__(self):
        self.rng = random.Random()

        self.cfg = GameConfig(
            n=int(GRID_SIZE),
            wall_collision=bool(WALL_COLLISION),
            fps=int(INITIAL_FPS),
        )

        self.renderer = Renderer(cell_px=32, margin_px=16, hud_h=44)

        self.event_bus = EventBus()
        self.actions = ActionSystem()
        self.rules = SnakeRules(self.rng)

        # patrones disponibles (rotación). Incluye Hamilton, pero no domina.
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

        # se usa para HUD (patrón actual del bot)
        self._last_pattern_idx = 0

    def current_pattern_name(self) -> str:
        return self.patterns[self.bot.current_idx].name

    def new_game_state(self) -> GameState:
        n = self.cfg.n
        # start snake (horizontal)
        cx, cy = n // 2, n // 2
        snake = deque([Point(cx - i, cy) for i in range(INITIAL_SNAKE_LENGTH)])

        foods: List[Food] = []
        bombs: Dict[Point, int] = {}

        state = GameState(
            snake=snake,
            direction=Direction.RIGHT,
            foods=foods,
            bombs=bombs,
            alive=True,
            score=0,
            snake_color_index=self.rng.randrange(0, 8),
            background_id=self.rng.randrange(0, 100000),
            tick=0,
            head_history=deque(maxlen=180),
            cycle_penalty_until=0,
        )

        # spawn originales (respawn=True)
        for _ in range(max(1, int(INITIAL_FOODS))):
            p = random_free_cell(state, self.cfg, self.rng)
            if p is None:
                break
            state.foods.append(Food(pos=p, respawn=True))

        state.head_history.append(state.snake[0])
        return state

    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption("Snake — Bot Focused")
        surface = pygame.display.set_mode(self.renderer.window_size(self.cfg.n))
        clock = pygame.time.Clock()

        scene: Optional[Scene] = MenuScene(self)

        while scene is not None:
            now_ms = pygame.time.get_ticks()
            events = pygame.event.get()

            # escena maneja input
            scene = scene.handle(events)
            if scene is None:
                break

            # aplicar acciones externas/manuales
            if isinstance(scene, PlayScene):
                drained = self.event_bus.drain()
                if drained:
                    self.actions.dispatch(drained, scene.state, self.cfg, self.rng, now_ms)

                # tick game
                if scene.state.alive:
                    if scene.bot_mode:
                        # bot decide
                        d = self.bot.choose_direction(scene.state, self.cfg)
                        scene.state.direction = d
                    else:
                        scene.state.direction = scene.kbd_dir

                    # avanzar reglas
                    self.rules.step(scene.state, self.cfg, now_ms)

            # render
            scene.render(surface, now_ms)
            pygame.display.flip()
            clock.tick(self.cfg.fps)

        pygame.quit()


def main() -> None:
    # sanity: sliders 1..10
    if not (1 <= PATTERN_VS_FOOD <= 10 and 1 <= PATTERN_VS_DYNAMISM <= 10):
        print("ERROR: PATTERN_VS_FOOD y PATTERN_VS_DYNAMISM deben estar en 1..10")
        sys.exit(1)

    app = App()
    app.run()


if __name__ == "__main__":
    main()
