from __future__ import annotations

import sys
import random
from dataclasses import dataclass
from enum import Enum
from collections import deque
from typing import Deque, Dict, List, Optional, Set, Tuple

try:
    import pygame  # type: ignore
except Exception as e:
    print("ERROR: No se pudo importar pygame. Instala con: python -m pip install pygame")
    print("Detalle:", repr(e))
    sys.exit(1)

# ============================================================
# CONFIG (puedes ajustar si quieres)
# ============================================================

GRID_SIZE = 16                 # NxN
WALL_COLLISION = True          # True: muere si sale, False: wrap
FPS = 12

INITIAL_SNAKE_LEN = 6
FOOD_COUNT = 1                 # 1 comida base que respawnea

CELL_PX = 32
MARGIN_PX = 16
HUD_H = 52

# Bot personalities (solo para darles estilo diferente)
# Snake A: más “territorio”
A_TERRITORY = 0.75
A_AGGRESSION = 0.35

# Snake B: más “agresión”
B_TERRITORY = 0.55
B_AGGRESSION = 0.65

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


def step_point(p: Point, d: Direction, n: int, wall: bool) -> Optional[Point]:
    nxt = add_dir(p, d)
    if wall:
        return nxt if in_bounds(nxt, n) else None
    return wrap(nxt, n)


def manhattan(a: Point, b: Point) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


# ============================================================
# Estado
# ============================================================

@dataclass(slots=True)
class Snake:
    body: Deque[Point]          # head = body[0]
    direction: Direction
    alive: bool
    score: int
    name: str


@dataclass(slots=True)
class GameState:
    snakes: List[Snake]         # 0=A, 1=B
    foods: Set[Point]
    tick: int


# ============================================================
# Spawning
# ============================================================

def all_occupied(state: GameState) -> Set[Point]:
    occ: Set[Point] = set()
    for s in state.snakes:
        occ |= set(s.body)
    return occ


def random_free_cell(state: GameState, rng: random.Random, n: int) -> Optional[Point]:
    occ = all_occupied(state) | set(state.foods)
    free = [Point(x, y) for y in range(n) for x in range(n) if Point(x, y) not in occ]
    return rng.choice(free) if free else None


def spawn_foods(state: GameState, rng: random.Random, n: int) -> None:
    while len(state.foods) < FOOD_COUNT:
        p = random_free_cell(state, rng, n)
        if p is None:
            return
        state.foods.add(p)


# ============================================================
# Bot: utilidad por movimiento + supervivencia (no head-on)
# ============================================================

def projected_snake_after_move(s: Snake, nxt_head: Point, eats: bool) -> Deque[Point]:
    proj = deque(s.body)
    proj.appendleft(nxt_head)
    if not eats:
        proj.pop()
    return proj


def legal_move_single(
    s: Snake,
    d: Direction,
    n: int,
    wall: bool,
    foods: Set[Point],
    other_body: Set[Point],
) -> Tuple[bool, Optional[Point], bool]:
    """
    Legalidad base (sin considerar head-on aún):
    - no salir (si wall)
    - no chocarse con su propio cuerpo (considerando cola si no come)
    - no chocar con cuerpo rival
    """
    head = s.body[0]
    nxt = step_point(head, d, n, wall)
    if nxt is None:
        return (False, None, False)

    if nxt in other_body:
        return (False, nxt, False)

    eats = (nxt in foods)

    own = set(s.body)
    tail = s.body[-1]

    if nxt in own:
        # permitido solo si NO come y es la cola (porque se mueve)
        if (not eats) and (nxt == tail):
            pass
        else:
            return (False, nxt, eats)

    return (True, nxt, eats)


def flood_reachable(start: Point, blocked: Set[Point], n: int, wall: bool) -> Set[Point]:
    q = deque([start])
    seen = {start}
    while q:
        p = q.popleft()
        for d in DIRS:
            nxt = step_point(p, d, n, wall)
            if nxt is None:
                continue
            if nxt in seen or nxt in blocked:
                continue
            seen.add(nxt)
            q.append(nxt)
    return seen


def has_escape_to_tail(proj: Deque[Point], other_body: Set[Point], n: int, wall: bool) -> bool:
    """
    Escape: existe ruta desde head hacia tail en el espacio libre (bloqueando cuerpo excepto tail).
    Esto impide meterse en cavidades sin salida.
    """
    head = proj[0]
    tail = proj[-1]

    blocked = set(proj)
    blocked.remove(tail)
    blocked |= other_body

    reachable = flood_reachable(head, blocked, n, wall)
    return tail in reachable


def territory_score(head_a: Point, head_b: Point, blocked: Set[Point], n: int, wall: bool) -> float:
    """
    Estima “control de spawn”: como spawn es uniforme en celdas libres,
    dominar más celdas libres “cercanas” te da ventaja.
    Aproximación Voronoi: para cada celda libre, compara distancia a ambas cabezas.
    """
    score = 0.0
    for y in range(n):
        for x in range(n):
            p = Point(x, y)
            if p in blocked:
                continue
            da = manhattan(head_a, p)
            db = manhattan(head_b, p)
            if da < db:
                score += 1.0
            elif da == db:
                score += 0.15  # empate
    return score


def mobility_score(body: Deque[Point], other_body: Set[Point], foods: Set[Point], n: int, wall: bool) -> int:
    """
    Movilidad: cuántos movimientos “base” tiene la serpiente desde su cabeza.
    """
    s = Snake(body=body, direction=Direction.UP, alive=True, score=0, name="")
    other = other_body
    count = 0
    for d in DIRS:
        ok, nxt, _ = legal_move_single(s, d, n, wall, foods, other)
        if ok and nxt is not None:
            count += 1
    return count


class DuelBot:
    def __init__(self, rng: random.Random, territory_w: float, aggression_w: float):
        self.rng = rng
        self.territory_w = territory_w
        self.aggression_w = aggression_w

    def utility_for_move(
        self,
        me: Snake,
        opp: Snake,
        my_dir: Direction,
        n: int,
        wall: bool,
        foods: Set[Point],
    ) -> Tuple[float, bool, Optional[Point], bool, Optional[Deque[Point]]]:
        """
        Retorna (utility, ok, nxt_head, eats, proj_body)
        - ok incluye supervivencia + escape (sin head-on, eso se resuelve al elegir el par)
        """
        if not me.alive:
            return (-1e18, False, None, False, None)

        other_body = set(opp.body)
        ok, nxt, eats = legal_move_single(me, my_dir, n, wall, foods, other_body)
        if not ok or nxt is None:
            return (-1e18, False, nxt, eats, None)

        proj = projected_snake_after_move(me, nxt, eats)

        # supervivencia > todo: exigir escape a la cola (considerando rival como paredes)
        if not has_escape_to_tail(proj, set(opp.body), n, wall):
            return (-1e18, False, nxt, eats, proj)

        # Utility:
        u = 0.0

        # 1) comida: acercarse y/o comer
        if foods:
            closest_food = min(foods, key=lambda f: manhattan(nxt, f))
            dist = manhattan(nxt, closest_food)
            u += -2.2 * dist
        if eats:
            u += 14.0

        # 2) territorio (dominar celdas libres)
        blocked = set(proj) | set(opp.body) | foods
        u += self.territory_w * 0.04 * territory_score(nxt, opp.body[0], blocked, n, wall)

        # 3) agresión: reducir movilidad del rival (aprox local)
        #    (si yo me acerco y ocupo rutas, su movilidad baja)
        my_blocked = set(proj)
        opp_mob = mobility_score(opp.body, my_blocked, foods, n, wall)
        u += self.aggression_w * (-3.0) * (opp_mob)  # menos movilidad rival => mayor u

        # 4) suavidad: no girar todo el tiempo
        if my_dir == me.direction:
            u += 0.4

        # 5) un poco de ruido para no ser 100% repetitivo
        u += self.rng.uniform(-0.25, 0.25)

        return (u, True, nxt, eats, proj)


# ============================================================
# Resolución simultánea y anti head-on
# ============================================================

def head_on_conflict(a_from: Point, a_to: Point, b_from: Point, b_to: Point) -> bool:
    # misma celda
    if a_to == b_to:
        return True
    # swap de cabezas
    if (a_to == b_from) and (b_to == a_from):
        return True
    return False


def choose_best_joint_move(
    bot_a: DuelBot,
    bot_b: DuelBot,
    state: GameState,
    n: int,
    wall: bool
) -> Tuple[Direction, Direction, Optional[Deque[Point]], Optional[Deque[Point]], bool, bool, Optional[Point], Optional[Point]]:
    """
    Evalúa las 16 combinaciones (4x4) y elige la mejor donde:
    - ambos movimientos sean seguros (incluye escape)
    - no haya head-on
    Devuelve dirs y proyecciones (para aplicar tick).
    """
    A = state.snakes[0]
    B = state.snakes[1]
    foods = state.foods

    best = None  # (score, dA, dB, projA, projB, eatsA, eatsB, nxtA, nxtB)
    best_fallback = None  # si no hay par totalmente seguro, elige el que “más sobreviva”

    for dA in DIRS:
        uA, okA, nxtA, eatsA, projA = bot_a.utility_for_move(A, B, dA, n, wall, foods)
        for dB in DIRS:
            uB, okB, nxtB, eatsB, projB = bot_b.utility_for_move(B, A, dB, n, wall, foods)

            # necesita nxt para evaluar conflicto
            if nxtA is None or nxtB is None:
                continue

            # prohibido head-on
            if head_on_conflict(A.body[0], nxtA, B.body[0], nxtB):
                continue

            # ambos seguros
            if okA and okB and projA is not None and projB is not None:
                # además: después de moverse, no pueden chocar con el cuerpo actualizado del otro
                # resolvemos aplicando simultáneo: cada uno bloquea su cuerpo proyectado
                if nxtA in set(projB):
                    continue
                if nxtB in set(projA):
                    continue

                score = uA + uB
                if (best is None) or (score > best[0]):
                    best = (score, dA, dB, projA, projB, eatsA, eatsB, nxtA, nxtB)
            else:
                # fallback: preferir que al menos uno sobreviva
                surv = (1 if okA else 0) + (1 if okB else 0)
                score = surv * 1e6 + (uA + uB)
                if (best_fallback is None) or (score > best_fallback[0]):
                    best_fallback = (score, dA, dB, projA, projB, eatsA, eatsB, nxtA, nxtB)

    if best is not None:
        _, dA, dB, projA, projB, eatsA, eatsB, nxtA, nxtB = best
        return dA, dB, projA, projB, eatsA, eatsB, nxtA, nxtB

    # si no hay forma de evitar muerte, usamos fallback (igual sin head-on)
    if best_fallback is not None:
        _, dA, dB, projA, projB, eatsA, eatsB, nxtA, nxtB = best_fallback
        return dA, dB, projA, projB, eatsA, eatsB, nxtA, nxtB

    # muy raro: no hay nada, quedarse
    return A.direction, B.direction, None, None, False, False, None, None


# ============================================================
# Aplicar tick del juego (simultáneo)
# ============================================================

def apply_tick(state: GameState, n: int, wall: bool, rng: random.Random, dA: Direction, dB: Direction) -> None:
    A = state.snakes[0]
    B = state.snakes[1]

    if not (A.alive and B.alive):
        return

    foods = state.foods

    # calcular next heads base
    nxtA = step_point(A.body[0], dA, n, wall)
    nxtB = step_point(B.body[0], dB, n, wall)

    # si alguna es None => choca muro
    if nxtA is None:
        A.alive = False
    if nxtB is None:
        B.alive = False

    if not (A.alive and B.alive):
        return

    # prohibido head-on (motor no lo permite; por seguridad)
    if head_on_conflict(A.body[0], nxtA, B.body[0], nxtB):
        # los dos “evitan”; si igual sucede, ambos pierden (pero esta rama no debería ocurrir)
        A.alive = False
        B.alive = False
        return

    eatsA = nxtA in foods
    eatsB = nxtB in foods

    # colisiones con cuerpos (considerando colas si no comen)
    bodyA = list(A.body)
    bodyB = list(B.body)
    tailA = A.body[-1]
    tailB = B.body[-1]

    # set de cuerpos efectivos (si no come, la cola se va)
    effA = set(bodyA[:-1]) if not eatsA else set(bodyA)
    effB = set(bodyB[:-1]) if not eatsB else set(bodyB)

    # choque con propio cuerpo
    if nxtA in effA:
        A.alive = False
    if nxtB in effB:
        B.alive = False

    # choque con rival
    if nxtA in effB:
        A.alive = False
    if nxtB in effA:
        B.alive = False

    if not (A.alive and B.alive):
        return

    # mover ambos
    A.direction = dA
    B.direction = dB

    A.body.appendleft(nxtA)
    B.body.appendleft(nxtB)

    if eatsA:
        A.score += 1
        foods.remove(nxtA)
    else:
        A.body.pop()

    if eatsB:
        B.score += 1
        # si ambos comen el mismo food, no debería pasar (head-on evitado)
        if nxtB in foods:
            foods.remove(nxtB)
    else:
        B.body.pop()

    # respawn comida
    spawn_foods(state, rng, n)

    state.tick += 1


# ============================================================
# Renderer
# ============================================================

class Renderer:
    def __init__(self):
        self.font: Optional["pygame.font.Font"] = None

    def window_size(self, n: int) -> Tuple[int, int]:
        w = n * CELL_PX + 2 * MARGIN_PX
        h = n * CELL_PX + 2 * MARGIN_PX + HUD_H
        return w, h

    def origin(self) -> Tuple[int, int]:
        return MARGIN_PX, MARGIN_PX + HUD_H

    def cell_center(self, p: Point) -> Tuple[int, int]:
        ox, oy = self.origin()
        return (ox + p.x * CELL_PX + CELL_PX // 2, oy + p.y * CELL_PX + CELL_PX // 2)

    def render(self, surface: "pygame.Surface", state: GameState, fps: int) -> None:
        if self.font is None:
            self.font = pygame.font.SysFont("consolas", 18)

        surface.fill((12, 12, 14))
        ox, oy = self.origin()
        n = GRID_SIZE
        board_w = n * CELL_PX
        board_h = n * CELL_PX

        # fondo tipo ajedrez suave
        for y in range(n):
            for x in range(n):
                col = (28, 28, 34) if (x + y) % 2 == 0 else (22, 22, 28)
                pygame.draw.rect(surface, col, pygame.Rect(ox + x * CELL_PX, oy + y * CELL_PX, CELL_PX, CELL_PX))

        # grid
        grid_color = (40, 40, 48)
        for x in range(n + 1):
            px = ox + x * CELL_PX
            pygame.draw.line(surface, grid_color, (px, oy), (px, oy + board_h), 1)
        for y in range(n + 1):
            py = oy + y * CELL_PX
            pygame.draw.line(surface, grid_color, (ox, py), (ox + board_w, py), 1)

        # HUD
        A, B = state.snakes
        pygame.draw.rect(surface, (18, 18, 22), pygame.Rect(0, 0, surface.get_width(), MARGIN_PX + HUD_H))
        self._text(surface, f"Tick: {state.tick}  FPS:{fps}", (MARGIN_PX, 10), (230, 230, 230))
        self._text(surface, f"A({A.name}) score={A.score} {'ALIVE' if A.alive else 'DEAD'}", (MARGIN_PX, 30), (120, 200, 255))
        self._text(surface, f"B({B.name}) score={B.score} {'ALIVE' if B.alive else 'DEAD'}", (MARGIN_PX + 320, 30), (255, 170, 100))

        # comida
        for f in state.foods:
            self._draw_food(surface, f)

        # snakes
        self._draw_snake(surface, list(A.body), A.direction, head_col=(120, 200, 255), body_col=(70, 140, 210))
        self._draw_snake(surface, list(B.body), B.direction, head_col=(255, 170, 100), body_col=(205, 120, 55))

        if not (A.alive and B.alive):
            msg = "FIN — ESC salir | R reiniciar"
            self._text(surface, msg, (MARGIN_PX, 52), (255, 220, 140))

    def _text(self, surface: "pygame.Surface", s: str, pos: Tuple[int, int], col: Tuple[int, int, int]) -> None:
        assert self.font is not None
        surface.blit(self.font.render(s, True, col), pos)

    def _draw_food(self, surface: "pygame.Surface", p: Point) -> None:
        cx, cy = self.cell_center(p)
        r = max(6, CELL_PX // 2 - 8)
        pygame.draw.circle(surface, (220, 70, 70), (cx, cy), r)
        pygame.draw.circle(surface, (245, 130, 130), (cx - r // 3, cy - r // 3), max(2, r // 3))

    def _draw_snake(self, surface: "pygame.Surface", pts: List[Point], direction: Direction,
                    head_col: Tuple[int, int, int], body_col: Tuple[int, int, int]) -> None:
        if not pts:
            return
        shadow = (12, 12, 14)
        r_body = max(6, CELL_PX // 2 - 7)
        r_head = r_body + 2
        r_tail = max(5, r_body - 2)

        centers = [self.cell_center(p) for p in pts]
        for i in range(len(centers) - 1):
            pygame.draw.line(surface, shadow, centers[i], centers[i + 1], r_body * 2 + 6)
        for i in range(len(centers) - 1):
            pygame.draw.line(surface, body_col, centers[i], centers[i + 1], r_body * 2)
        for i in range(1, len(centers) - 1):
            pygame.draw.circle(surface, body_col, centers[i], r_body)
        pygame.draw.circle(surface, body_col, centers[-1], r_tail)
        pygame.draw.circle(surface, head_col, centers[0], r_head)

        self._draw_eyes(surface, centers[0], direction, r_head)

    def _draw_eyes(self, surface: "pygame.Surface", c: Tuple[int, int], d: Direction, r: int) -> None:
        cx, cy = c
        if d == Direction.UP:
            o1 = (cx - r // 3, cy - r // 3); o2 = (cx + r // 3, cy - r // 3)
        elif d == Direction.DOWN:
            o1 = (cx - r // 3, cy + r // 3); o2 = (cx + r // 3, cy + r // 3)
        elif d == Direction.LEFT:
            o1 = (cx - r // 3, cy - r // 3); o2 = (cx - r // 3, cy + r // 3)
        else:
            o1 = (cx + r // 3, cy - r // 3); o2 = (cx + r // 3, cy + r // 3)

        pygame.draw.circle(surface, (10, 10, 10), o1, max(2, r // 6))
        pygame.draw.circle(surface, (10, 10, 10), o2, max(2, r // 6))


# ============================================================
# Game setup
# ============================================================

def make_initial_state(rng: random.Random) -> GameState:
    n = GRID_SIZE
    # Esquinas opuestas
    # A en (0,0) hacia RIGHT
    # B en (n-1, n-1) hacia LEFT
    A_body = deque([Point(0 + i, 0) for i in range(INITIAL_SNAKE_LEN)])
    B_body = deque([Point((n - 1) - i, (n - 1)) for i in range(INITIAL_SNAKE_LEN)])

    A = Snake(body=A_body, direction=Direction.RIGHT, alive=True, score=0, name="Territory")
    B = Snake(body=B_body, direction=Direction.LEFT, alive=True, score=0, name="Aggro")

    state = GameState(snakes=[A, B], foods=set(), tick=0)
    spawn_foods(state, rng, n)
    return state


# ============================================================
# Main loop
# ============================================================

def main() -> None:
    pygame.init()
    pygame.display.set_caption("Snake Duel — 2 Bots")
    rng = random.Random()

    renderer = Renderer()
    surface = pygame.display.set_mode(renderer.window_size(GRID_SIZE))
    clock = pygame.time.Clock()

    state = make_initial_state(rng)

    botA = DuelBot(rng, territory_w=A_TERRITORY, aggression_w=A_AGGRESSION)
    botB = DuelBot(rng, territory_w=B_TERRITORY, aggression_w=B_AGGRESSION)

    running = True
    while running:
        events = pygame.event.get()
        for e in events:
            if e.type == pygame.QUIT:
                running = False
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                if e.key == pygame.K_r:
                    state = make_initial_state(rng)

        A, B = state.snakes

        if A.alive and B.alive:
            dA, dB, _projA, _projB, _eA, _eB, _nA, _nB = choose_best_joint_move(
                botA, botB, state, GRID_SIZE, WALL_COLLISION
            )
            apply_tick(state, GRID_SIZE, WALL_COLLISION, rng, dA, dB)

        renderer.render(surface, state, FPS)
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()


if __name__ == "__main__":
    main()
