"""
SNAKE 16x16 — Enfocado en BOT estilo “patrón + eficiencia” + minas temporales (TTL)
- Arquitectura OCP: EventBus + ActionSystem + acciones extensibles (listo para Listener externo)
- Menú: teclado / bot / salir
- Teclas de test (simulan TikTok):
    J: subir velocidad
    L: bajar velocidad
    X: spawnear ráfaga de minas (count, ttl) desde config
    Z: spawnear comida extra
    R: reiniciar
    ESC: menú

Nota importante:
- Este bot NO es “perfecto” con bombas arbitrarias (ninguno lo es si te bloquean rutas),
  pero su comportamiento imita el estilo: patrón dominante + desvíos por eficiencia + regreso al patrón.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Deque, Dict, List, Optional, Protocol, Set, Tuple, Callable, Any
from collections import deque
import random
import sys

try:
    import pygame  # type: ignore
except Exception as e:
    print("ERROR: No se pudo importar 'pygame'. Instálalo con: python -m pip install pygame")
    print("Detalle:", repr(e))
    sys.exit(1)

# ============================================================
# 🔧 TUNABLES (ajusta aquí sin tocar el resto del código)
# ============================================================

@dataclass(slots=True)
class Tuning:
    # ---------- Ventana / juego ----------
    GRID_W: int = 16
    GRID_H: int = 16
    CELL_PX: int = 32
    MARGIN_PX: int = 16
    HUD_H: int = 44
    FPS_START: int = 60
    WALL_COLLISION: bool = True  # True: muere en borde | False: wrap-around

    # ---------- Comida ----------
    INITIAL_FOODS: int = 1
    FOOD_RESPAWN_ON_EAT: int = 1   # normalmente 1
    EXTRA_FOOD_KEY_Z_COUNT: int = 1

    # ---------- Minas (bombas) ----------
    BOMB_DEFAULT_TTL_MS: int = 5000
    BOMB_KEY_X_COUNT: int = 5
    BOMB_KEY_X_TTL_MS: int = 5000

    # ---------- Bot: balance patrón vs eficiencia ----------
    # w_pattern alto => más “espiral/rectángulos” (más borde/capas)
    # w_food alto => corta más para comer rápido
    BOT_W_PATTERN: float = 0.001
    BOT_W_FOOD: float = 9.50
    BOT_W_STRAIGHT: float = 9.35

    # Ruido controlado para evitar repetición idéntica
    BOT_JITTER: float = 100000.70

    # Si dura mucho sin comer, sube agresividad hacia comida
    BOT_STAGNATION_LIMIT: int = 70
    BOT_FOOD_BOOST_MULT: float = 50.0

    # Con muchas minas: reduce atajos (más seguro, más patrón)
    BOT_BOMB_EFFICIENCY_REDUCTION: float = 0.55   # 0..1 (más alto = menos agresivo con minas)
    BOT_BOMB_PATTERN_INCREASE: float = 0.70       # 0..1 (más alto = más patrón con minas)

    # Presión de minas (cuántas minas se consideran “muchas”)
    BOT_BOMB_PRESSURE_DENOM: float = 6.0  # 6 minas => presión ~1.0

    # Seguridad: si False, permite movimientos legales aunque rompan “segmento seguro”
    # (se verá más loco, pero aumenta riesgo de morir)
    BOT_STRICT_SAFE_SHORTCUTS: bool = True


T = Tuning()


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


@dataclass(slots=True)
class GameConfig:
    grid_w: int
    grid_h: int
    cell_px: int
    fps: int
    wall_collision: bool
    margin_px: int
    hud_h: int


@dataclass(slots=True)
class GameState:
    snake: Deque[Point]                  # head = snake[0]
    direction: Direction
    foods: Set[Point]
    bombs: Dict[Point, int]              # Point -> expire_time_ms
    alive: bool = True
    score: int = 0


# ============================================================
# Interfaces (OCP)
# ============================================================

class IRuleSet(Protocol):
    def step(self, state: GameState, config: GameConfig, now_ms: int) -> GameState:
        ...


class IRenderer(Protocol):
    def render(self, surface: "pygame.Surface", state: GameState, config: GameConfig, now_ms: int) -> None:
        ...


class IInputController(Protocol):
    def update_direction(self, state: GameState, config: GameConfig, now_ms: int, events: List["pygame.event.Event"]) -> Direction:
        ...


class IScene(Protocol):
    def handle_events(self, events: List["pygame.event.Event"]) -> Optional["IScene"]:
        ...
    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        ...


# ============================================================
# Helpers
# ============================================================

def add_dir(p: Point, d: Direction) -> Point:
    return Point(p.x + d.dx, p.y + d.dy)

def in_bounds(p: Point, cfg: GameConfig) -> bool:
    return 0 <= p.x < cfg.grid_w and 0 <= p.y < cfg.grid_h

def norm(p: Point, cfg: GameConfig) -> Point:
    if cfg.wall_collision:
        return p
    return Point(p.x % cfg.grid_w, p.y % cfg.grid_h)

def manhattan(a: Point, b: Point) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)

def layer_index(p: Point, cfg: GameConfig) -> int:
    # 0 = borde, 1 = 2da capa, ...
    return min(p.x, p.y, cfg.grid_w - 1 - p.x, cfg.grid_h - 1 - p.y)


# ============================================================
# EventBus + Actions (Listener externo-ready)
# ============================================================

@dataclass(frozen=True, slots=True)
class GameEvent:
    type: str
    payload: Dict[str, Any] | None = None


class EventBus:
    def __init__(self):
        self._q: Deque[GameEvent] = deque()

    def emit(self, event: GameEvent) -> None:
        self._q.append(event)

    def drain(self) -> List[GameEvent]:
        out: List[GameEvent] = []
        while self._q:
            out.append(self._q.popleft())
        return out


class IGameAction(Protocol):
    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        ...


def random_free_cell(state: GameState, cfg: GameConfig, rng: random.Random) -> Optional[Point]:
    occupied = set(state.snake) | set(state.bombs.keys()) | state.foods
    free = [Point(x, y) for y in range(cfg.grid_h) for x in range(cfg.grid_w) if Point(x, y) not in occupied]
    return rng.choice(free) if free else None


class SpawnBombAction:
    def __init__(self, count: int = 1, ttl_ms: int = 5000):
        self.count = max(1, int(count))
        self.ttl_ms = max(250, int(ttl_ms))

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        for _ in range(self.count):
            p = random_free_cell(state, cfg, rng)
            if p is None:
                break
            state.bombs[p] = now_ms + self.ttl_ms


class SpawnFoodAction:
    def __init__(self, count: int = 1):
        self.count = max(1, int(count))

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        for _ in range(self.count):
            p = random_free_cell(state, cfg, rng)
            if p is None:
                break
            state.foods.add(p)


class SpeedUpAction:
    def __init__(self, delta: int = 1):
        self.delta = int(delta)

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        cfg.fps = min(60, cfg.fps + self.delta)


class SlowDownAction:
    def __init__(self, delta: int = 1):
        self.delta = int(delta)

    def apply(self, state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        cfg.fps = max(1, cfg.fps - self.delta)


class ActionSystem:
    def __init__(self, registry: Dict[str, Callable[[GameEvent], IGameAction]]):
        self.registry = registry

    def dispatch(self, events: List[GameEvent], state: GameState, cfg: GameConfig, rng: random.Random, now_ms: int) -> None:
        for ev in events:
            factory = self.registry.get(ev.type)
            if factory is None:
                continue
            action = factory(ev)
            action.apply(state, cfg, rng, now_ms)


def default_action_registry() -> Dict[str, Callable[[GameEvent], IGameAction]]:
    return {
        "SPAWN_BOMB": lambda ev: SpawnBombAction(
            count=int((ev.payload or {}).get("count", 1)),
            ttl_ms=int((ev.payload or {}).get("ttl_ms", T.BOMB_DEFAULT_TTL_MS)),
        ),
        "SPAWN_FOOD": lambda ev: SpawnFoodAction(
            count=int((ev.payload or {}).get("count", 1)),
        ),
        "SPEED_UP": lambda ev: SpeedUpAction(delta=int((ev.payload or {}).get("delta", 1))),
        "SLOW_DOWN": lambda ev: SlowDownAction(delta=int((ev.payload or {}).get("delta", 1))),
    }


# ============================================================
# Controllers
# ============================================================

class KeyboardController(IInputController):
    _key_to_dir = {
        pygame.K_UP: Direction.UP,
        pygame.K_w: Direction.UP,
        pygame.K_DOWN: Direction.DOWN,
        pygame.K_s: Direction.DOWN,
        pygame.K_LEFT: Direction.LEFT,
        pygame.K_a: Direction.LEFT,
        pygame.K_RIGHT: Direction.RIGHT,
        pygame.K_d: Direction.RIGHT,
    }

    @staticmethod
    def _is_opposite(a: Direction, b: Direction) -> bool:
        return (a.dx + b.dx == 0) and (a.dy + b.dy == 0)

    def update_direction(self, state: GameState, config: GameConfig, now_ms: int, events: List["pygame.event.Event"]) -> Direction:
        cur = state.direction
        new_dir = cur
        for e in events:
            if e.type == pygame.KEYDOWN and e.key in self._key_to_dir:
                cand = self._key_to_dir[e.key]
                if not self._is_opposite(cur, cand):
                    new_dir = cand
        return new_dir


def build_hamiltonian_cycle(cfg: GameConfig) -> List[Point]:
    w, h = cfg.grid_w, cfg.grid_h
    if w % 2 == 1 and h % 2 == 1:
        raise ValueError("No existe ciclo Hamiltoniano si ambos lados son impares (>1).")

    if w % 2 == 0:
        cycle: List[Point] = []
        for y in range(0, h):
            cycle.append(Point(0, y))

        for x in range(1, w):
            if x % 2 == 1:
                for y in range(h - 1, 0, -1):
                    cycle.append(Point(x, y))
            else:
                for y in range(1, h):
                    cycle.append(Point(x, y))

        cycle.append(Point(w - 1, 0))
        for x in range(w - 2, 0, -1):
            cycle.append(Point(x, 0))
        return cycle

    cfg_t = GameConfig(grid_w=cfg.grid_h, grid_h=cfg.grid_w, cell_px=cfg.cell_px, fps=cfg.fps,
                       wall_collision=True, margin_px=cfg.margin_px, hud_h=cfg.hud_h)
    cycle_t = build_hamiltonian_cycle(cfg_t)
    return [Point(p.y, p.x) for p in cycle_t]


class PatternEfficiencyBot(IInputController):
    def __init__(self, cycle: List[Point], rng: random.Random):
        self.rng = rng
        self.cycle = cycle
        self.N = len(cycle)
        self.idx: Dict[Point, int] = {p: i for i, p in enumerate(cycle)}
        self.next_map: Dict[Point, Point] = {cycle[i]: cycle[(i + 1) % self.N] for i in range(self.N)}

        self._ticks_since_eat = 0
        self._last_score = 0

    def update_direction(self, state: GameState, cfg: GameConfig, now_ms: int, events: List["pygame.event.Event"]) -> Direction:
        if state.score != self._last_score:
            self._last_score = state.score
            self._ticks_since_eat = 0
        else:
            self._ticks_since_eat += 1

        head = state.snake[0]
        tail = state.snake[-1]

        if head not in self.next_map or head not in self.idx or tail not in self.idx:
            return state.direction

        snake_set = set(state.snake)
        bomb_set = set(state.bombs.keys())

        # objetivo comida: manhattan (se ve “eficiente”)
        food_target = min(state.foods, key=lambda f: manhattan(head, f))

        bombs_pressure = min(1.0, len(bomb_set) / float(T.BOT_BOMB_PRESSURE_DENOM))

        w_food = T.BOT_W_FOOD
        if self._ticks_since_eat >= T.BOT_STAGNATION_LIMIT:
            w_food *= T.BOT_FOOD_BOOST_MULT

        w_food *= (1.0 - T.BOT_BOMB_EFFICIENCY_REDUCTION * bombs_pressure)
        w_pattern = T.BOT_W_PATTERN * (1.0 + T.BOT_BOMB_PATTERN_INCREASE * bombs_pressure)
        w_straight = T.BOT_W_STRAIGHT
        jitter = T.BOT_JITTER

        cycle_next = self.next_map[head]
        fallback_dir = self._dir_from_to(head, cycle_next)

        candidates: List[Tuple[Direction, Point]] = []
        for d in DIRS:
            nxt = norm(add_dir(head, d), cfg)
            if cfg.wall_collision and not in_bounds(nxt, cfg):
                continue
            if nxt in bomb_set:
                continue

            eats = (nxt in state.foods)
            if nxt in snake_set and not (not eats and nxt == tail):
                continue

            candidates.append((d, nxt))

        if not candidates:
            return state.direction

        best_d = fallback_dir
        best_score = -1e18

        for d, nxt in candidates:
            safe = self._is_safe_shortcut(head, tail, nxt) if T.BOT_STRICT_SAFE_SHORTCUTS else True
            unsafe_pen = 0.0 if safe else 1.0

            dist_cycle = self._cycle_distance(nxt, food_target)
            lyr = layer_index(nxt, cfg)
            straight = 1.0 if d == state.direction else 0.0

            score = 0.0
            score += -w_food * dist_cycle
            score += -w_pattern * lyr
            score += w_straight * straight

            if nxt in state.foods:
                score += 50.0

            score += -9999.0 * unsafe_pen
            score += self.rng.uniform(-jitter, jitter)

            if score > best_score:
                best_score = score
                best_d = d

        if best_score < -9000:
            if cycle_next not in bomb_set and (cycle_next not in snake_set or cycle_next == tail):
                return fallback_dir
            return candidates[0][0]

        return best_d

    def _dir_from_to(self, a: Point, b: Point) -> Direction:
        dx = b.x - a.x
        dy = b.y - a.y
        if dx == 1 and dy == 0:
            return Direction.RIGHT
        if dx == -1 and dy == 0:
            return Direction.LEFT
        if dx == 0 and dy == 1:
            return Direction.DOWN
        return Direction.UP

    def _cycle_distance(self, a: Point, b: Point) -> int:
        ia = self.idx[a]
        ib = self.idx[b]
        if ib >= ia:
            return ib - ia
        return (self.N - ia) + ib

    def _is_safe_shortcut(self, head: Point, tail: Point, nxt: Point) -> bool:
        if nxt not in self.idx:
            return False
        iH = self.idx[head]
        iT = self.idx[tail]
        iN = self.idx[nxt]
        if iH < iT:
            return (iH < iN <= iT)
        else:
            return (iN > iH) or (iN <= iT)


# ============================================================
# Rules (foods + bombas TTL)
# ============================================================

class SnakeRules(IRuleSet):
    def __init__(self, rng: random.Random):
        self.rng = rng

    def step(self, state: GameState, cfg: GameConfig, now_ms: int) -> GameState:
        if not state.alive:
            return state

        # limpiar bombas expiradas
        if state.bombs:
            expired = [p for p, t in state.bombs.items() if t <= now_ms]
            for p in expired:
                state.bombs.pop(p, None)

        head = state.snake[0]
        nxt = norm(add_dir(head, state.direction), cfg)

        if cfg.wall_collision and not in_bounds(nxt, cfg):
            state.alive = False
            return state

        if nxt in state.bombs:
            state.alive = False
            return state

        eats = (nxt in state.foods)

        body = list(state.snake)
        if not eats:
            body = body[:-1]
        if nxt in body:
            state.alive = False
            return state

        state.snake.appendleft(nxt)

        if eats:
            state.score += 1
            state.foods.remove(nxt)
            for _ in range(T.FOOD_RESPAWN_ON_EAT):
                self._spawn_food(state, cfg)
        else:
            state.snake.pop()

        return state

    def _spawn_food(self, state: GameState, cfg: GameConfig) -> None:
        occupied = set(state.snake) | set(state.bombs.keys()) | state.foods
        free = [Point(x, y) for y in range(cfg.grid_h) for x in range(cfg.grid_w) if Point(x, y) not in occupied]
        if free:
            state.foods.add(self.rng.choice(free))


# ============================================================
# Renderer
# ============================================================

class FancyRenderer(IRenderer):
    def __init__(self):
        self._font: Optional["pygame.font.Font"] = None

    def render(self, surface: "pygame.Surface", state: GameState, cfg: GameConfig, now_ms: int) -> None:
        if self._font is None:
            self._font = pygame.font.SysFont("consolas", 18)

        surface.fill((16, 16, 18))
        origin = (cfg.margin_px, cfg.margin_px + cfg.hud_h)
        ox, oy = origin

        pygame.draw.rect(surface, (22, 22, 26), pygame.Rect(0, 0, surface.get_width(), cfg.margin_px + cfg.hud_h))
        self._draw_text(surface, f"Score: {state.score}   FPS: {cfg.fps}   Bombs: {len(state.bombs)}",
                        (cfg.margin_px, 10), (235, 235, 235))
        self._draw_text(surface, "J/L speed | X: bombs burst | Z food | R restart | ESC menu",
                        (cfg.margin_px, 28), (160, 160, 160))

        board_w = cfg.grid_w * cfg.cell_px
        board_h = cfg.grid_h * cfg.cell_px
        board_rect = pygame.Rect(ox - 6, oy - 6, board_w + 12, board_h + 12)
        pygame.draw.rect(surface, (24, 24, 28), board_rect, border_radius=14)

        self._draw_grid(surface, cfg, origin)

        for b, exp in state.bombs.items():
            self._draw_bomb(surface, b, exp, now_ms, cfg, origin)

        for f in state.foods:
            self._draw_apple(surface, f, cfg, origin)

        self._draw_snake(surface, list(state.snake), state.direction, cfg, origin)

        if not state.alive:
            self._draw_text(surface, "GAME OVER — R reinicia | ESC menú", (cfg.margin_px, 50), (255, 200, 120))

    def _draw_grid(self, surface: "pygame.Surface", cfg: GameConfig, origin: Tuple[int, int]) -> None:
        ox, oy = origin
        grid_color = (38, 38, 44)
        w_px = cfg.grid_w * cfg.cell_px
        h_px = cfg.grid_h * cfg.cell_px
        for x in range(cfg.grid_w + 1):
            px = ox + x * cfg.cell_px
            pygame.draw.line(surface, grid_color, (px, oy), (px, oy + h_px), 1)
        for y in range(cfg.grid_h + 1):
            py = oy + y * cfg.cell_px
            pygame.draw.line(surface, grid_color, (ox, py), (ox + w_px, py), 1)

    def _cell_center(self, p: Point, cfg: GameConfig, origin: Tuple[int, int]) -> Tuple[int, int]:
        ox, oy = origin
        return (ox + p.x * cfg.cell_px + cfg.cell_px // 2, oy + p.y * cfg.cell_px + cfg.cell_px // 2)

    def _draw_snake(self, surface: "pygame.Surface", pts: List[Point], direction: Direction, cfg: GameConfig, origin: Tuple[int, int]) -> None:
        if not pts:
            return

        head_color = (95, 235, 140)
        body_color = (65, 175, 105)
        shadow = (20, 20, 22)

        r_body = max(6, cfg.cell_px // 2 - 7)
        r_head = r_body + 2
        r_tail = max(5, r_body - 2)

        centers = [self._cell_center(p, cfg, origin) for p in pts]

        for i in range(len(centers) - 1):
            pygame.draw.line(surface, shadow, centers[i], centers[i + 1], r_body * 2 + 6)
        for i in range(len(centers) - 1):
            pygame.draw.line(surface, body_color, centers[i], centers[i + 1], r_body * 2)
        for i in range(1, len(centers) - 1):
            pygame.draw.circle(surface, body_color, centers[i], r_body)

        pygame.draw.circle(surface, body_color, centers[-1], r_tail)
        pygame.draw.circle(surface, head_color, centers[0], r_head)
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

        pygame.draw.circle(surface, (18, 18, 18), o1, max(2, r // 6))
        pygame.draw.circle(surface, (18, 18, 18), o2, max(2, r // 6))

    def _draw_apple(self, surface: "pygame.Surface", p: Point, cfg: GameConfig, origin: Tuple[int, int]) -> None:
        cx, cy = self._cell_center(p, cfg, origin)
        r = max(6, cfg.cell_px // 2 - 8)
        pygame.draw.circle(surface, (220, 70, 70), (cx, cy), r)
        pygame.draw.circle(surface, (245, 120, 120), (cx - r // 3, cy - r // 3), max(2, r // 3))
        pygame.draw.rect(surface, (110, 75, 45), pygame.Rect(cx - 2, cy - r - 4, 4, 10), border_radius=2)
        leaf = [(cx + 2, cy - r - 2), (cx + r // 2 + 6, cy - r - 8), (cx + r // 2, cy - r + 6)]
        pygame.draw.polygon(surface, (70, 190, 90), leaf)

    def _draw_bomb(self, surface: "pygame.Surface", p: Point, exp_ms: int, now_ms: int, cfg: GameConfig, origin: Tuple[int, int]) -> None:
        cx, cy = self._cell_center(p, cfg, origin)
        r = max(6, cfg.cell_px // 2 - 9)

        pygame.draw.circle(surface, (60, 60, 70), (cx, cy), r)
        pygame.draw.circle(surface, (90, 90, 105), (cx - r // 4, cy - r // 4), max(2, r // 3))

        tleft = max(0, exp_ms - now_ms)
        blink = (tleft // 200) % 2 == 0
        spark_color = (255, 200, 80) if blink else (255, 140, 60)

        pygame.draw.line(surface, (160, 130, 90), (cx + r // 2, cy - r // 2), (cx + r + 6, cy - r - 6), 3)
        pygame.draw.circle(surface, spark_color, (cx + r + 6, cy - r - 6), 4)

    def _draw_text(self, surface: "pygame.Surface", text: str, pos: Tuple[int, int], color: Tuple[int, int, int]) -> None:
        assert self._font is not None
        img = self._font.render(text, True, color)
        surface.blit(img, pos)


# ============================================================
# Scenes
# ============================================================

class QuitScene(IScene):
    def handle_events(self, events: List["pygame.event.Event"]) -> Optional[IScene]:
        return None
    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        pass


class MenuScene(IScene):
    def __init__(self, cfg: GameConfig, rules: IRuleSet, renderer: IRenderer, rng: random.Random, event_bus: EventBus, action_sys: ActionSystem):
        self.cfg = cfg
        self.rules = rules
        self.renderer = renderer
        self.rng = rng
        self.event_bus = event_bus
        self.action_sys = action_sys

        self.options = [
            ("Play (Keyboard)", "keyboard"),
            ("Watch Bot (Pattern + Efficiency)", "bot"),
            ("Quit", "quit"),
        ]
        self.index = 0
        self.font_title: Optional["pygame.font.Font"] = None
        self.font_item: Optional["pygame.font.Font"] = None
        self.font_hint: Optional["pygame.font.Font"] = None

    def handle_events(self, events: List["pygame.event.Event"]) -> Optional[IScene]:
        for e in events:
            if e.type == pygame.QUIT:
                return QuitScene()
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return QuitScene()
                if e.key in (pygame.K_UP, pygame.K_w):
                    self.index = (self.index - 1) % len(self.options)
                if e.key in (pygame.K_DOWN, pygame.K_s):
                    self.index = (self.index + 1) % len(self.options)
                if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    _, tag = self.options[self.index]
                    if tag == "quit":
                        return QuitScene()
                    if tag == "keyboard":
                        return PlayScene(self.cfg, self.rules, self.renderer, KeyboardController(), self.rng, self.event_bus, self.action_sys)
                    if tag == "bot":
                        cycle = build_hamiltonian_cycle(self.cfg)
                        bot = PatternEfficiencyBot(cycle, rng=self.rng)
                        return PlayScene(self.cfg, self.rules, self.renderer, bot, self.rng, self.event_bus, self.action_sys)
        return None

    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        if self.font_title is None:
            self.font_title = pygame.font.SysFont("consolas", 30)
        if self.font_item is None:
            self.font_item = pygame.font.SysFont("consolas", 22)
        if self.font_hint is None:
            self.font_hint = pygame.font.SysFont("consolas", 16)

        surface.fill((16, 16, 18))
        title = self.font_title.render("SNAKE 16x16", True, (235, 235, 235))
        surface.blit(title, (self.cfg.margin_px, self.cfg.margin_px))

        y = self.cfg.margin_px + 70
        for i, (label, _) in enumerate(self.options):
            sel = (i == self.index)
            color = (255, 220, 120) if sel else (210, 210, 210)
            prefix = "> " if sel else "  "
            item = self.font_item.render(prefix + label, True, color)
            surface.blit(item, (self.cfg.margin_px, y))
            y += 36

        hint = self.font_hint.render("UP/DOWN + ENTER | ESC to quit", True, (150, 150, 150))
        surface.blit(hint, (self.cfg.margin_px, surface.get_height() - self.cfg.margin_px - 20))


class PlayScene(IScene):
    def __init__(
        self,
        cfg: GameConfig,
        rules: IRuleSet,
        renderer: IRenderer,
        controller: IInputController,
        rng: random.Random,
        event_bus: EventBus,
        action_sys: ActionSystem,
    ):
        self.cfg = cfg
        self.rules = rules
        self.renderer = renderer
        self.controller = controller
        self.rng = rng
        self.event_bus = event_bus
        self.action_sys = action_sys
        self.state = self._new_game()

    def _new_game(self) -> GameState:
        bombs: Dict[Point, int] = {}
        foods: Set[Point] = set()

        cx, cy = self.cfg.grid_w // 2, self.cfg.grid_h // 2
        snake = deque([Point(cx, cy), Point(cx - 1, cy), Point(cx - 2, cy)])

        state = GameState(snake=snake, direction=Direction.RIGHT, foods=foods, bombs=bombs, alive=True, score=0)
        for _ in range(T.INITIAL_FOODS):
            self._spawn_food(state)
        return state

    def _spawn_food(self, state: GameState) -> None:
        occupied = set(state.snake) | set(state.bombs.keys()) | state.foods
        free = [Point(x, y) for y in range(self.cfg.grid_h) for x in range(self.cfg.grid_w) if Point(x, y) not in occupied]
        if free:
            state.foods.add(self.rng.choice(free))

    def handle_events(self, events: List["pygame.event.Event"]) -> Optional[IScene]:
        for e in events:
            if e.type == pygame.QUIT:
                return QuitScene()
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return MenuScene(self.cfg, self.rules, self.renderer, self.rng, self.event_bus, self.action_sys)
                if e.key == pygame.K_r:
                    self.state = self._new_game()

                # ===== manual test (simula TikTok) =====
                if e.key == pygame.K_j:
                    self.event_bus.emit(GameEvent(type="SPEED_UP", payload={"delta": 1}))
                if e.key == pygame.K_l:
                    self.event_bus.emit(GameEvent(type="SLOW_DOWN", payload={"delta": 1}))
                if e.key == pygame.K_x:
                    self.event_bus.emit(GameEvent(type="SPAWN_BOMB", payload={"count": T.BOMB_KEY_X_COUNT, "ttl_ms": T.BOMB_KEY_X_TTL_MS}))
                if e.key == pygame.K_z:
                    self.event_bus.emit(GameEvent(type="SPAWN_FOOD", payload={"count": T.EXTRA_FOOD_KEY_Z_COUNT}))

        return None

    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        self.renderer.render(surface, self.state, self.cfg, now_ms)


# ============================================================
# Engine
# ============================================================

class GameEngine:
    def __init__(self, cfg: GameConfig, initial_scene: IScene, event_bus: EventBus, action_sys: ActionSystem, rng: random.Random, rules: IRuleSet):
        self.cfg = cfg
        self.scene: IScene = initial_scene
        self.event_bus = event_bus
        self.action_sys = action_sys
        self.rng = rng
        self.rules = rules

    def _window_size(self) -> Tuple[int, int]:
        w = self.cfg.grid_w * self.cfg.cell_px + 2 * self.cfg.margin_px
        h = self.cfg.grid_h * self.cfg.cell_px + 2 * self.cfg.margin_px + self.cfg.hud_h
        return (w, h)

    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption("Snake 16x16")
        surface = pygame.display.set_mode(self._window_size())
        clock = pygame.time.Clock()

        while True:
            now_ms = pygame.time.get_ticks()
            events = pygame.event.get()

            nxt = self.scene.handle_events(events)
            if isinstance(nxt, QuitScene):
                break
            if nxt is not None:
                self.scene = nxt

            if isinstance(self.scene, PlayScene):
                drained = self.event_bus.drain()
                if drained:
                    self.action_sys.dispatch(drained, self.scene.state, self.cfg, self.rng, now_ms)

                if self.scene.state.alive:
                    self.scene.state.direction = self.scene.controller.update_direction(self.scene.state, self.cfg, now_ms, events)
                    self.scene.state = self.rules.step(self.scene.state, self.cfg, now_ms)

            self.scene.render(surface, now_ms)
            pygame.display.flip()
            clock.tick(self.cfg.fps)

        pygame.quit()


# ============================================================
# Main
# ============================================================

def main() -> None:
    cfg = GameConfig(
        grid_w=T.GRID_W,
        grid_h=T.GRID_H,
        cell_px=T.CELL_PX,
        fps=T.FPS_START,
        wall_collision=T.WALL_COLLISION,
        margin_px=T.MARGIN_PX,
        hud_h=T.HUD_H,
    )
    rng = random.Random()
    rules = SnakeRules(rng=rng)
    renderer = FancyRenderer()

    event_bus = EventBus()
    action_sys = ActionSystem(default_action_registry())

    engine = GameEngine(cfg, MenuScene(cfg, rules, renderer, rng, event_bus, action_sys), event_bus, action_sys, rng, rules)
    engine.run()


if __name__ == "__main__":
    main()
