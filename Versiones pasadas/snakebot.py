# snakebot.py — SnakeBot V1.15 (bot-focused + TikTok-ready via UDP)
# ---------------------------------------------------------------
# REQUISITOS DE ESTA VERSIÓN (según lo que pediste):
# - Ventana SIEMPRE del mismo tamaño (como te gusta cuando Grid=18x18).
# - Fondo: si no hay carpeta Background o está vacía -> SOLO "DARK".
#   Si hay backgrounds -> tecla W cicla.
# - Teclas (mantener TODAS y sumar):
#   J = bajar velocidad | L = subir velocidad | Z = spawn comida extra | X = spawn bomba normal
#   C = ciclo de color | R = restart inmediato | B = bomba nuclear | K = pausa | W = cambiar fondo
# - NO mostrar “hints de teclas” arriba (solo stats).
# - Serpiente con cuerpo conectado (estilo “Snake — Bot Focused”).
# - Nuclear: bomba VERTICAL + animación caída + espera 2s + explosión por anillos con estados (amarillo->ceniza->carbón).
#   La serpiente SOLO muere cuando su CABEZA entra a un anillo ya alcanzado por la explosión.
# - Barra inferior: última donación/acción (texto).
# - UDP listener: el juego recibe comandos (el listener lo ajustamos luego).

import os
import sys
import json
import math
import time
import socket
import random
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Set, Deque
from collections import deque

# ===============================================================
# ======================= USER CONFIG ===========================
# ===============================================================

# --- Ajustables (los importantes) ---
INITIAL_SNAKE_LENGTH = 6

INITIAL_RESPAWN_FOODS = 1          # comida “original” reespawneable (normalmente 1)
INITIAL_EXTRA_FOODS = 0            # comidas extra al inicio (NO reespawnean)
MAX_EXTRA_FOODS = 3                # límite de comidas extra simultáneas

BOMB_TTL_MS = 5000                 # duración de bombas normales
SIMULTANEOUS_BOMBS = 1             # cuántas bombas spawnea un comando (X o donación)

GRID_SIZE = 16                     # tamaño de cuadrícula (NxN)
WALL_COLLISION = True              # colisión con muro (True = muere al tocar borde)

INITIAL_FPS = 18                   # velocidad inicial (fps lógico del juego)

# Bot: balance
PATTERN_VS_FOOD = 7                # 1..10 (1=patrón, 10=camino más rápido seguro a comida)
PATTERN_VS_DYNAMISM = 6            # 1..10 (1=mantener patrón, 10=sin patrón / cambia mucho)

# Punto de quiebre “final rápido”: cuando queden <= X celdas vacías
# (acelera cierre y evita finales eternos)
FAST_END_EMPTY_CELLS_TRIGGER = 12

# ===============================================================
# ===================== INTERNAL CONSTANTS ======================
# ===============================================================

VERSION = "V1.15"

# Ventana fija: “tamaño que te gusta cuando Grid=18x18”
_BASE_GRID_FOR_WINDOW = 18
_BASE_CELL_PX = 30  # 18*30 = 540 (play area)
PLAY_AREA_PX = _BASE_GRID_FOR_WINDOW * _BASE_CELL_PX

WINDOW_MARGIN_PX = 24
HEADER_H = 92
FOOTER_H = 64

WINDOW_W = PLAY_AREA_PX + WINDOW_MARGIN_PX * 2
WINDOW_H = PLAY_AREA_PX + WINDOW_MARGIN_PX * 2 + HEADER_H + FOOTER_H

# Colores UI
COL_BG_DARK_1 = (20, 21, 24)
COL_BG_DARK_2 = (28, 29, 33)
COL_GRID_LINE = (10, 10, 12)

COL_TEXT_1 = (235, 235, 235)
COL_TEXT_2 = (210, 210, 210)
COL_TEXT_3 = (185, 185, 185)

COL_APPLE_RED = (220, 40, 45)
COL_APPLE_LEAF = (60, 200, 90)
COL_BOMB_DARK = (35, 35, 40)
COL_BOMB_FUSE = (240, 180, 60)

# Nuclear colors (hot -> ash -> char)
NUKE_COL_HOT_A = (255, 205, 50)
NUKE_COL_HOT_B = (255, 170, 40)
NUKE_COL_ASH_A = (165, 165, 165)
NUKE_COL_ASH_B = (120, 120, 120)
NUKE_COL_CHAR_A = (45, 45, 45)
NUKE_COL_CHAR_B = (25, 25, 25)

# Nuclear timing
NUKE_FALL_MS = 900            # caída hasta el centro
NUKE_ARM_MS = 2000            # espera en el centro antes de explotar
NUKE_RING_STEP_MS = 180       # tiempo entre anillos (animación visible)
NUKE_POST_MS = 900            # tiempo final “carbonizado” antes de terminar

# UDP
UDP_HOST = "127.0.0.1"
UDP_PORT = 8765
UDP_MAX_BYTES = 4096

Vec2 = Tuple[int, int]
DIRS: List[Vec2] = [(1, 0), (-1, 0), (0, 1), (0, -1)]
DIR_NAME = {(1, 0): "R", (-1, 0): "L", (0, 1): "D", (0, -1): "U"}


def clamp(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def add(a: Vec2, b: Vec2) -> Vec2:
    return (a[0] + b[0], a[1] + b[1])


def manhattan(a: Vec2, b: Vec2) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def chebyshev(a: Vec2, b: Vec2) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def in_bounds(p: Vec2, n: int) -> bool:
    return 0 <= p[0] < n and 0 <= p[1] < n


@dataclass
class ExternalEvent:
    who: str
    gift: str
    action: str
    ts_ms: int


# ===============================================================
# ===================== BACKGROUND LOADER =======================
# ===============================================================

class BackgroundManager:
    """
    Si ./Background tiene imágenes -> se cargan como pixelart:
    - Se recorta al cuadrado central
    - Se reduce a (bgN x bgN) donde bgN = min(w,h) (en pixeles)
    - Para el grid actual n: toma el recorte central n x n
    - Luego escala a PLAY_AREA_PX con nearest-neighbor
    Si no hay nada -> DARK.
    """
    def __init__(self, pygame, rng: random.Random):
        self.pygame = pygame
        self.rng = rng
        self.bg_folder = os.path.join(os.path.dirname(__file__), "Background")
        self.bg_name = "DARK"
        self._images: List[Tuple[str, "pygame.Surface"]] = []
        self._idx = 0
        self._scan()

    def _scan(self):
        self._images.clear()
        if not os.path.isdir(self.bg_folder):
            return
        exts = (".png", ".jpg", ".jpeg", ".bmp")
        for fn in sorted(os.listdir(self.bg_folder)):
            if fn.lower().endswith(exts):
                path = os.path.join(self.bg_folder, fn)
                try:
                    img = self.pygame.image.load(path).convert()
                    self._images.append((fn, img))
                except Exception:
                    pass

    def has_images(self) -> bool:
        return len(self._images) > 0

    def next_bg(self):
        if not self.has_images():
            self.bg_name = "DARK"
            return
        self._idx = (self._idx + 1) % len(self._images)
        self.bg_name = self._images[self._idx][0]

    def render_bg(self, target_surf, n: int, x0: int, y0: int):
        pygame = self.pygame
        if not self.has_images():
            self.bg_name = "DARK"
            self._draw_dark(target_surf, n, x0, y0)
            return

        name, img = self._images[self._idx]
        self.bg_name = name

        w, h = img.get_width(), img.get_height()
        s = min(w, h)
        cx, cy = w // 2, h // 2
        left = clamp(cx - s // 2, 0, w - s)
        top = clamp(cy - s // 2, 0, h - s)
        sq = img.subsurface((left, top, s, s))

        # downscale to s x s (keeps as “pixel grid”)
        small = pygame.transform.scale(sq, (s, s))

        # take central n x n
        if n <= s:
            left2 = (s - n) // 2
            top2 = (s - n) // 2
            crop = small.subsurface((left2, top2, n, n))
        else:
            # if background smaller, just scale it up; not ideal, but robust
            crop = pygame.transform.scale(small, (n, n))

        # scale up to play area with nearest-neighbor
        scaled = pygame.transform.scale(crop, (PLAY_AREA_PX, PLAY_AREA_PX))
        target_surf.blit(scaled, (x0, y0))

    def _draw_dark(self, surf, n: int, x0: int, y0: int):
        cell = PLAY_AREA_PX / n
        for y in range(n):
            for x in range(n):
                col = COL_BG_DARK_1 if (x + y) % 2 == 0 else COL_BG_DARK_2
                rx = int(x0 + x * cell)
                ry = int(y0 + y * cell)
                rw = int(math.ceil(cell))
                rh = int(math.ceil(cell))
                self.pygame.draw.rect(surf, col, (rx, ry, rw, rh))


# ===============================================================
# ======================== BOT PATTERNS =========================
# ===============================================================

class Pattern:
    name = "base"
    def target_dir(self, head: Vec2, n: int, tick: int) -> Vec2:
        return (1, 0)

class ZigZagPattern(Pattern):
    name = "zigzag"
    def target_dir(self, head: Vec2, n: int, tick: int) -> Vec2:
        x, y = head
        # serpentine scan: even rows go right, odd rows go left, drop at row end
        if y % 2 == 0:
            if x < n - 1:
                return (1, 0)
            else:
                return (0, 1)
        else:
            if x > 0:
                return (-1, 0)
            else:
                return (0, 1)

class PerimeterPattern(Pattern):
    name = "perimeter"
    def target_dir(self, head: Vec2, n: int, tick: int) -> Vec2:
        x, y = head
        # clockwise perimeter bias
        if y == 0 and x < n - 1:
            return (1, 0)
        if x == n - 1 and y < n - 1:
            return (0, 1)
        if y == n - 1 and x > 0:
            return (-1, 0)
        if x == 0 and y > 0:
            return (0, -1)
        # inside: push outward
        if x < n // 2:
            return (-1, 0)
        return (1, 0)

class SpiralPattern(Pattern):
    name = "spiral"
    def target_dir(self, head: Vec2, n: int, tick: int) -> Vec2:
        # deterministic but “hipnotizante”: follow a simple inward spiral field
        x, y = head
        # distance to borders
        dL, dR = x, n - 1 - x
        dU, dD = y, n - 1 - y
        m = min(dL, dR, dU, dD)
        # choose direction depending on ring
        # ring 0: go right on top, down on right, left on bottom, up on left
        if y == m and x < n - 1 - m:
            return (1, 0)
        if x == n - 1 - m and y < n - 1 - m:
            return (0, 1)
        if y == n - 1 - m and x > m:
            return (-1, 0)
        if x == m and y > m:
            return (0, -1)
        # otherwise fallback
        return (1, 0)

class RandomWeavePattern(Pattern):
    name = "weave"
    def __init__(self, rng: random.Random):
        self.rng = rng

    def target_dir(self, head: Vec2, n: int, tick: int) -> Vec2:
        # slight bias to keep moving, not oscillating too hard
        return self.rng.choice(DIRS)

PATTERN_BUILDERS = [
    lambda rng: ZigZagPattern(),
    lambda rng: SpiralPattern(),
    lambda rng: PerimeterPattern(),
    lambda rng: RandomWeavePattern(rng),
]

# ===============================================================
# ============================ BOT ==============================
# ===============================================================

class SnakeBot:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.pattern = PATTERN_BUILDERS[0](rng)
        self.pattern_ticks_left = 0
        self.last_heads: Deque[Vec2] = deque(maxlen=64)
        self.loop_flag = False

    def _maybe_switch_pattern(self, tick: int):
        # PATTERN_VS_DYNAMISM high => switch more often
        dyn = clamp(PATTERN_VS_DYNAMISM, 1, 10)
        base = int(180 - dyn * 14)  # 180..40
        base = clamp(base, 35, 220)
        if self.pattern_ticks_left <= 0:
            self.pattern = self.rng.choice(PATTERN_BUILDERS)(self.rng)
            # randomize duration a bit
            self.pattern_ticks_left = base + self.rng.randint(-base // 4, base // 4)
        else:
            self.pattern_ticks_left -= 1

    def choose_dir(self, game: "Game") -> Vec2:
        n = game.n
        head = game.snake[0]
        self._maybe_switch_pattern(game.tick)

        # loop detection: if head repeats a small cycle > 2 times, force pattern switch
        self.last_heads.append(head)
        self.loop_flag = self._detect_loop()
        if self.loop_flag:
            self.pattern_ticks_left = 0  # force switch now

        # Candidate moves
        best_dir = game.dir
        best_score = -10**18
        candidates = self._legal_dirs(game)

        # If nothing legal, return current dir (will die)
        if not candidates:
            return game.dir

        # Precompute food targets
        foods = list(game.respawn_foods) + list(game.extra_foods)
        food_target = min(foods, key=lambda f: manhattan(head, f)) if foods else None

        # Weights
        w_food = clamp(PATTERN_VS_FOOD, 1, 10) / 10.0  # 0.1..1.0
        w_pat = 1.0 - w_food

        # Fast-end mode trigger
        empty_cells = game.count_empty_cells()
        fast_end = empty_cells <= FAST_END_EMPTY_CELLS_TRIGGER

        for d in candidates:
            sim = game.simulate_step(d)

            # survival priority always
            if not sim["alive"]:
                # extend death: prefer the one that maximizes free-space reach
                sc = sim.get("survival_score", -10**9)
                if sc > best_score:
                    best_score = sc
                    best_dir = d
                continue

            # Safe return: must keep path to tail
            if not sim["tail_reachable"]:
                continue

            # Base score
            score = 0.0

            # Food: prefer shorter path, but only if safe
            if food_target is not None:
                dist = sim["food_dist"]
                score += (1000.0 - dist * 30.0) * w_food

            # Pattern following
            td = self.pattern.target_dir(head, n, game.tick)
            score += (250.0 if d == td else 0.0) * w_pat

            # Anti “head glued to tail”: gentle penalty (not forbidden)
            # (you said ya no es norma estricta, pero visualmente se ayuda)
            ht = manhattan(sim["new_head"], sim["new_tail"])
            score -= max(0, 4 - ht) * 35.0

            # Stack empty spaces: prefer fewer empty components (cluster empties),
            # and prefer larger largest component.
            score += (sim["empty_largest_cc"] * 2.0) + (-(sim["empty_cc_count"] * 55.0))

            # In fast-end: strongly prefer moves that reduce components and move toward food
            if fast_end:
                score += (-(sim["empty_cc_count"] * 140.0))
                if food_target is not None:
                    score += (1000.0 - sim["food_dist"] * 40.0)

            # Avoid infinite loops: if loop detected, penalize repeating same direction
            if self.loop_flag:
                score -= (120.0 if d == game.dir else 0.0)

            # Slight randomness (controlled)
            dyn = clamp(PATTERN_VS_DYNAMISM, 1, 10)
            score += self.rng.uniform(-8.0, 8.0) * (dyn / 10.0)

            if score > best_score:
                best_score = score
                best_dir = d

        # If everything got filtered by tail_reachable, fall back to best alive candidate
        if best_score < -10**17:
            best_dir = candidates[0]
        return best_dir

    def _legal_dirs(self, game: "Game") -> List[Vec2]:
        n = game.n
        head = game.snake[0]
        res = []
        for d in DIRS:
            if add(head, d) == game.snake[1] if len(game.snake) > 1 else False:
                continue
            np = add(head, d)
            if WALL_COLLISION:
                if not in_bounds(np, n):
                    continue
            else:
                np = (np[0] % n, np[1] % n)
            # do not go into own body (tail is special when moving)
            if game.would_hit_body(np, eating=game.is_food(np)):
                continue
            # do not go into bomb
            if np in game.bombs:
                continue
            res.append(d)
        return res

    def _detect_loop(self) -> bool:
        # Detect small head-cycle repeated > 2 times (simple heuristic)
        if len(self.last_heads) < 24:
            return False
        arr = list(self.last_heads)
        # try loop lengths 4..10
        for L in range(4, 11):
            if len(arr) < 3 * L:
                continue
            a = arr[-L:]
            b = arr[-2*L:-L]
            c = arr[-3*L:-2*L]
            if a == b == c:
                return True
        return False


# ===============================================================
# ============================ GAME =============================
# ===============================================================

class Game:
    def __init__(self, pygame, rng: random.Random):
        self.pygame = pygame
        self.rng = rng

        self.n = GRID_SIZE
        self.tick = 0

        # Dynamic cell size to keep play area fixed
        self.cell = PLAY_AREA_PX / self.n

        self.fps = INITIAL_FPS
        self.paused = False

        self.bg = BackgroundManager(pygame, rng)

        self.snake: List[Vec2] = []
        self.dir: Vec2 = (0, 1)

        self.respawn_foods: Set[Vec2] = set()
        self.extra_foods: Set[Vec2] = set()

        self.bombs: Dict[Vec2, int] = {}  # pos -> expire_ms

        self.bot = SnakeBot(rng)
        self.snake_colors = [
            (70, 210, 110),
            (60, 190, 240),
            (240, 140, 60),
            (220, 80, 160),
            (180, 110, 255),
        ]
        self.snake_color_idx = 0

        # External events
        self.last_events: Deque[ExternalEvent] = deque(maxlen=2)
        self.last_footer_msg = ""
        self.last_footer_until = 0

        # Victory/defeat overlay
        self.overlay_until = 0
        self.overlay_type = None  # "WIN" / "LOSE"
        self.overlay_img_win = None
        self.overlay_img_lose = None
        self._load_signs()

        # Nuclear state
        self.nuke_active = False
        self.nuke_center = (self.n // 2, self.n // 2)
        self.nuke_start_ms = 0
        self.nuke_phase = "NONE"  # FALL, ARM, RINGS, POST
        self.nuke_radius = 0
        self.nuke_last_step_ms = 0
        self.nuke_cell_state: Dict[Vec2, str] = {}  # pos -> hot/ash/char
        self.nuke_bomb_visible = False

        self.reset(hard=True)

    # ------------------- init assets -------------------
    def _load_signs(self):
        pygame = self.pygame
        base = os.path.dirname(__file__)
        folder = os.path.join(base, "letreros")
        if not os.path.isdir(folder):
            return
        # Best effort: look for win/lose files
        cand_win = ["win.png", "victory.png", "snake_win.png"]
        cand_lose = ["lose.png", "defeat.png", "spectators_win.png"]
        for fn in cand_win:
            p = os.path.join(folder, fn)
            if os.path.isfile(p):
                try:
                    self.overlay_img_win = pygame.image.load(p).convert_alpha()
                    break
                except Exception:
                    pass
        for fn in cand_lose:
            p = os.path.join(folder, fn)
            if os.path.isfile(p):
                try:
                    self.overlay_img_lose = pygame.image.load(p).convert_alpha()
                    break
                except Exception:
                    pass

    # ------------------- gameplay -------------------
    def reset(self, hard: bool = False):
        self.tick = 0
        self.cell = PLAY_AREA_PX / self.n

        self.paused = False
        self.nuke_active = False
        self.nuke_phase = "NONE"
        self.nuke_radius = 0
        self.nuke_cell_state.clear()
        self.nuke_bomb_visible = False

        self.bombs.clear()
        self.respawn_foods.clear()
        self.extra_foods.clear()
        self.overlay_until = 0
        self.overlay_type = None

        # Snake spawns near top-middle, going down (classic)
        cx = self.n // 2
        start = [(cx, 2 + i) for i in range(INITIAL_SNAKE_LENGTH)][::-1]
        self.snake = start
        self.dir = (0, 1)

        # foods
        for _ in range(INITIAL_RESPAWN_FOODS):
            self._spawn_respawn_food()
        for _ in range(min(INITIAL_EXTRA_FOODS, MAX_EXTRA_FOODS)):
            self._spawn_extra_food()

    def score(self) -> int:
        return max(0, len(self.snake) - INITIAL_SNAKE_LENGTH)

    def is_food(self, p: Vec2) -> bool:
        return p in self.respawn_foods or p in self.extra_foods

    def would_hit_body(self, p: Vec2, eating: bool) -> bool:
        # If not eating, tail moves away -> allow stepping onto current tail
        body = set(self.snake)
        if not eating:
            body.discard(self.snake[-1])
        return p in body

    def count_empty_cells(self) -> int:
        occ = set(self.snake) | set(self.respawn_foods) | set(self.extra_foods) | set(self.bombs.keys())
        return self.n * self.n - len(occ)

    def _random_empty_cell(self) -> Optional[Vec2]:
        occ = set(self.snake) | set(self.respawn_foods) | set(self.extra_foods) | set(self.bombs.keys())
        tries = 2000
        for _ in range(tries):
            p = (self.rng.randrange(self.n), self.rng.randrange(self.n))
            if p not in occ:
                return p
        # fallback: brute scan
        for y in range(self.n):
            for x in range(self.n):
                p = (x, y)
                if p not in occ:
                    return p
        return None

    def _spawn_respawn_food(self):
        p = self._random_empty_cell()
        if p is not None:
            self.respawn_foods.add(p)

    def _spawn_extra_food(self):
        if len(self.extra_foods) >= MAX_EXTRA_FOODS:
            return
        p = self._random_empty_cell()
        if p is not None:
            self.extra_foods.add(p)

    def spawn_bomb(self, count: int, ttl_ms: int):
        now = self.pygame.time.get_ticks()
        for _ in range(count):
            p = self._random_empty_cell()
            if p is None:
                return
            self.bombs[p] = now + ttl_ms

    def cycle_color(self, times: int = 1):
        self.snake_color_idx = (self.snake_color_idx + times) % len(self.snake_colors)

    def restart_immediate(self):
        self.reset(hard=True)

    def toggle_pause(self):
        self.paused = not self.paused

    def next_background(self):
        if self.bg.has_images():
            self.bg.next_bg()

    def trigger_nuke(self):
        if self.nuke_active:
            return
        self.nuke_active = True
        self.nuke_center = (self.n // 2, self.n // 2)
        self.nuke_start_ms = self.pygame.time.get_ticks()
        self.nuke_phase = "FALL"
        self.nuke_radius = 0
        self.nuke_last_step_ms = self.nuke_start_ms
        self.nuke_cell_state.clear()
        self.nuke_bomb_visible = True

    # ------------------- simulation helpers for bot -------------------
    def simulate_step(self, d: Vec2) -> Dict:
        """
        Simulate one move to score candidates:
        - returns alive, tail_reachable, food_dist, empty CC stats, survival_score
        """
        n = self.n
        head = self.snake[0]
        new_head = add(head, d)
        if not WALL_COLLISION:
            new_head = (new_head[0] % n, new_head[1] % n)

        alive = True
        if WALL_COLLISION and not in_bounds(new_head, n):
            alive = False

        eating = self.is_food(new_head)

        if alive:
            if self.would_hit_body(new_head, eating=eating):
                alive = False
        if alive:
            if new_head in self.bombs:
                alive = False

        # if nuke explosion reached this cell, it's lethal only when reached
        if alive and self.nuke_active and self.nuke_phase in ("RINGS", "POST"):
            if chebyshev(new_head, self.nuke_center) <= self.nuke_radius:
                alive = False

        if not alive:
            # survival_score: how many free cells are reachable from head (rough)
            surv = -10**9
            if WALL_COLLISION and not in_bounds(new_head, n):
                return {"alive": False, "survival_score": -10**9}
            # approximate: BFS in current grid (without moving) from new_head
            occ = set(self.snake)
            # allow tail if not eating
            if not eating:
                occ.discard(self.snake[-1])
            occ |= set(self.bombs.keys())
            if self.nuke_active and self.nuke_phase in ("RINGS", "POST"):
                # treat nuked area as blocked
                for y in range(n):
                    for x in range(n):
                        p = (x, y)
                        if chebyshev(p, self.nuke_center) <= self.nuke_radius:
                            occ.add(p)
            if new_head in occ:
                return {"alive": False, "survival_score": -10**9}
            q = deque([new_head])
            seen = {new_head}
            while q:
                p = q.popleft()
                for dd in DIRS:
                    np = add(p, dd)
                    if WALL_COLLISION:
                        if not in_bounds(np, n):
                            continue
                    else:
                        np = (np[0] % n, np[1] % n)
                    if np in occ or np in seen:
                        continue
                    seen.add(np)
                    q.append(np)
            surv = len(seen)
            return {"alive": False, "survival_score": surv}

        # Build new snake list after move
        new_snake = [new_head] + self.snake[:]
        if eating:
            # do not pop tail
            pass
        else:
            new_snake.pop()

        new_tail = new_snake[-1]

        # tail reachable check
        tail_reach = self._reachable(new_head, new_tail, new_snake)

        # food dist (to nearest food)
        foods = list(self.respawn_foods) + list(self.extra_foods)
        if eating:
            # in simulation, that food would be gone; respawnable food respawns but unknown -> ignore
            foods = [f for f in foods if f != new_head]
        if foods:
            fd = min(manhattan(new_head, f) for f in foods)
        else:
            fd = 999

        # empty clustering stats after move
        cc_cnt, cc_max = self._empty_cc_stats(new_snake)

        return {
            "alive": True,
            "tail_reachable": tail_reach,
            "food_dist": fd,
            "new_head": new_head,
            "new_tail": new_tail,
            "empty_cc_count": cc_cnt,
            "empty_largest_cc": cc_max,
        }

    def _reachable(self, start: Vec2, goal: Vec2, snake_state: List[Vec2]) -> bool:
        n = self.n
        occ = set(snake_state)
        # allow goal cell
        occ.discard(goal)
        occ |= set(self.bombs.keys())
        if self.nuke_active and self.nuke_phase in ("RINGS", "POST"):
            for y in range(n):
                for x in range(n):
                    p = (x, y)
                    if chebyshev(p, self.nuke_center) <= self.nuke_radius:
                        occ.add(p)

        q = deque([start])
        seen = {start}
        while q:
            p = q.popleft()
            if p == goal:
                return True
            for d in DIRS:
                np = add(p, d)
                if WALL_COLLISION:
                    if not in_bounds(np, n):
                        continue
                else:
                    np = (np[0] % n, np[1] % n)
                if np in occ or np in seen:
                    continue
                seen.add(np)
                q.append(np)
        return False

    def _empty_cc_stats(self, snake_state: List[Vec2]) -> Tuple[int, int]:
        n = self.n
        occ = set(snake_state) | set(self.respawn_foods) | set(self.extra_foods) | set(self.bombs.keys())
        if self.nuke_active and self.nuke_phase in ("RINGS", "POST"):
            for y in range(n):
                for x in range(n):
                    p = (x, y)
                    if chebyshev(p, self.nuke_center) <= self.nuke_radius:
                        occ.add(p)

        seen: Set[Vec2] = set()
        cc_cnt = 0
        cc_max = 0
        for y in range(n):
            for x in range(n):
                p = (x, y)
                if p in occ or p in seen:
                    continue
                cc_cnt += 1
                q = deque([p])
                seen.add(p)
                sz = 0
                while q:
                    u = q.popleft()
                    sz += 1
                    for d in DIRS:
                        v = add(u, d)
                        if not in_bounds(v, n):
                            continue
                        if v in occ or v in seen:
                            continue
                        seen.add(v)
                        q.append(v)
                cc_max = max(cc_max, sz)
        return cc_cnt, cc_max

    # ------------------- main tick -------------------
    def update(self):
        now = self.pygame.time.get_ticks()
        if self.overlay_until > 0:
            if now >= self.overlay_until:
                self.restart_immediate()
            return

        # bombs expire
        expired = [p for p, t in self.bombs.items() if now >= t]
        for p in expired:
            self.bombs.pop(p, None)

        # nuke state update
        if self.nuke_active:
            self._update_nuke(now)

        if self.paused:
            return

        self.tick += 1

        # BOT decides
        self.dir = self.bot.choose_dir(self)

        # apply move
        self._step(self.dir)

    def _step(self, d: Vec2):
        n = self.n
        head = self.snake[0]
        new_head = add(head, d)
        if not WALL_COLLISION:
            new_head = (new_head[0] % n, new_head[1] % n)

        # wall
        if WALL_COLLISION and not in_bounds(new_head, n):
            self._lose("Choque con muro")
            return

        # nuke lethal only when reached
        if self.nuke_active and self.nuke_phase in ("RINGS", "POST"):
            if chebyshev(new_head, self.nuke_center) <= self.nuke_radius:
                self._lose("Explosión nuclear")
                return

        eating_respawn = new_head in self.respawn_foods
        eating_extra = new_head in self.extra_foods
        eating = eating_respawn or eating_extra

        # body collision
        if self.would_hit_body(new_head, eating=eating):
            self._lose("Choque con cuerpo")
            return

        # bomb collision
        if new_head in self.bombs:
            self._lose("Bomba normal")
            return

        # move
        self.snake.insert(0, new_head)
        if not eating:
            self.snake.pop()

        # eat handling
        if eating_respawn:
            self.respawn_foods.discard(new_head)
            # respawn one (maintain count)
            while len(self.respawn_foods) < INITIAL_RESPAWN_FOODS:
                self._spawn_respawn_food()

        if eating_extra:
            # extra does NOT respawn
            self.extra_foods.discard(new_head)

        # win condition: fill grid without bombs (we allow win even if bombs exist? keep simple: must fill all cells)
        if len(self.snake) >= self.n * self.n:
            self._win()

    # ------------------- end states -------------------
    def _win(self):
        self.overlay_type = "WIN"
        self.overlay_until = self.pygame.time.get_ticks() + 7000

    def _lose(self, reason: str):
        self.overlay_type = "LOSE"
        self.overlay_until = self.pygame.time.get_ticks() + 7000

    # ------------------- nuke animation -------------------
    def _update_nuke(self, now: int):
        # phases: FALL -> ARM -> RINGS -> POST
        if self.nuke_phase == "FALL":
            if now - self.nuke_start_ms >= NUKE_FALL_MS:
                self.nuke_phase = "ARM"
                self.nuke_last_step_ms = now
            return

        if self.nuke_phase == "ARM":
            if now - self.nuke_last_step_ms >= NUKE_ARM_MS:
                self.nuke_phase = "RINGS"
                self.nuke_radius = 0
                self.nuke_last_step_ms = now
                self.nuke_cell_state.clear()
            return

        if self.nuke_phase == "RINGS":
            if now - self.nuke_last_step_ms >= NUKE_RING_STEP_MS:
                self.nuke_last_step_ms = now
                self.nuke_radius += 1

                # update states:
                # - new ring becomes HOT
                # - previous HOT becomes ASH
                # - previous ASH becomes CHAR (after one step)
                # We track per cell by its chebyshev distance to center.
                c = self.nuke_center
                r = self.nuke_radius

                # First: degrade existing states
                for p, st in list(self.nuke_cell_state.items()):
                    if st == "hot":
                        self.nuke_cell_state[p] = "ash"
                    elif st == "ash":
                        self.nuke_cell_state[p] = "char"

                # Add hot ring cells for this radius
                for y in range(self.n):
                    for x in range(self.n):
                        p = (x, y)
                        if chebyshev(p, c) == r:
                            self.nuke_cell_state[p] = "hot"

                # When radius exceeds board max, go to POST
                if r >= max(self.n, self.n):
                    self.nuke_phase = "POST"
                    self.nuke_last_step_ms = now
            return

        if self.nuke_phase == "POST":
            if now - self.nuke_last_step_ms >= NUKE_POST_MS:
                # Finish by forcing a lose if not already
                self._lose("Nuke final")
                self.nuke_active = False
                self.nuke_phase = "NONE"
            return


# ===============================================================
# =========================== RENDER ============================
# ===============================================================

class Renderer:
    def __init__(self, pygame):
        self.pygame = pygame
        pygame.font.init()
        self.font_small = pygame.font.SysFont("consolas", 18)
        self.font_tiny = pygame.font.SysFont("consolas", 15)
        self.font_footer = pygame.font.SysFont("consolas", 18, bold=True)

    def draw(self, screen, g: Game):
        pygame = self.pygame
        screen.fill((12, 12, 14))

        # Layout
        x0 = WINDOW_MARGIN_PX
        y0 = WINDOW_MARGIN_PX + HEADER_H
        play_x = x0
        play_y = y0

        # Background
        g.bg.render_bg(screen, g.n, play_x, play_y)

        # Grid lines (subtle)
        cell = g.cell
        for i in range(g.n + 1):
            px = int(play_x + i * cell)
            pygame.draw.line(screen, COL_GRID_LINE, (px, play_y), (px, play_y + PLAY_AREA_PX), 1)
            py = int(play_y + i * cell)
            pygame.draw.line(screen, COL_GRID_LINE, (play_x, py), (play_x + PLAY_AREA_PX, py), 1)

        # Nuclear overlay (cells) behind snake? (pero bomba encima)
        if g.nuke_active and g.nuke_phase in ("RINGS", "POST"):
            self._draw_nuke_cells(screen, g, play_x, play_y)

        # Foods
        for p in g.respawn_foods:
            self._draw_apple(screen, g, p, play_x, play_y, big=True)
        for p in g.extra_foods:
            self._draw_apple(screen, g, p, play_x, play_y, big=False)

        # Bombs
        for p in g.bombs.keys():
            self._draw_bomb(screen, g, p, play_x, play_y)

        # Snake (connected)
        self._draw_snake_connected(screen, g, play_x, play_y)

        # Nuclear bomb on top of everything (must be visible even if snake is there)
        if g.nuke_active and g.nuke_phase in ("FALL", "ARM", "RINGS", "POST"):
            self._draw_nuke_bomb(screen, g, play_x, play_y)

        # Header stats
        self._draw_header(screen, g)

        # Footer donation/action message
        self._draw_footer(screen, g)

        # Overlay (win/lose) banner
        self._draw_overlay(screen, g)

    # ------------------- header/footer -------------------
    def _wrap_text(self, text: str, max_w: int, font) -> List[str]:
        pygame = self.pygame
        words = text.split(" ")
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if font.size(test)[0] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def _draw_header(self, screen, g: Game):
        pygame = self.pygame
        x0 = WINDOW_MARGIN_PX
        y0 = WINDOW_MARGIN_PX
        max_w = WINDOW_W - WINDOW_MARGIN_PX * 2

        score = g.score()
        prim = len(g.respawn_foods)
        extra = len(g.extra_foods)
        bombs = len(g.bombs)
        pat = g.bot.pattern.name
        bgname = g.bg.bg_name if g.bg.has_images() else "DARK"

        line1 = f"SnakeBot {VERSION} | Grid {g.n}x{g.n} | Fondo {bgname} | Vel {g.fps} | Patrón {pat}"
        line2 = f"Score {score} | Comida respawn {prim} | Comida extra {extra}/{MAX_EXTRA_FOODS} | Bombas activas {bombs} | Pausa {'Sí' if g.paused else 'No'}"

        a1 = g.last_events[0] if len(g.last_events) >= 1 else None
        a2 = g.last_events[1] if len(g.last_events) >= 2 else None
        if a1 or a2:
            parts = []
            if a1:
                parts.append(f"1) {a1.who}:{a1.gift}->{a1.action}")
            if a2:
                parts.append(f"2) {a2.who}:{a2.gift}->{a2.action}")
            line3 = "Acciones ext: " + " | ".join(parts)
        else:
            line3 = "Acciones ext: (ninguna)"

        # wrap to avoid cutting
        yy = y0
        for line, col in [(line1, COL_TEXT_1), (line2, COL_TEXT_2), (line3, COL_TEXT_3)]:
            lines = self._wrap_text(line, max_w, self.font_tiny)
            for l in lines[:2]:  # keep header compact
                screen.blit(self.font_tiny.render(l, True, col), (x0, yy))
                yy += 18

    def _draw_footer(self, screen, g: Game):
        pygame = self.pygame
        y = WINDOW_H - WINDOW_MARGIN_PX - FOOTER_H + 14
        x = WINDOW_MARGIN_PX

        # background bar
        pygame.draw.rect(screen, (10, 10, 12), (0, WINDOW_H - FOOTER_H, WINDOW_W, FOOTER_H))

        msg = g.last_footer_msg or ""
        if not msg:
            msg = "Listo. Esperando donaciones / acciones..."
        # wrap if needed
        max_w = WINDOW_W - WINDOW_MARGIN_PX * 2
        lines = self._wrap_text(msg, max_w, self.font_footer)
        for i, l in enumerate(lines[:2]):
            screen.blit(self.font_footer.render(l, True, (220, 220, 220)), (x, y + i * 22))

    def _draw_overlay(self, screen, g: Game):
        if g.overlay_until <= 0 or g.overlay_type is None:
            return
        pygame = self.pygame

        # dim
        s = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        s.fill((0, 0, 0, 140))
        screen.blit(s, (0, 0))

        # banner image from ./letreros if exists, else fallback text
        img = None
        if g.overlay_type == "WIN":
            img = g.overlay_img_win
        else:
            img = g.overlay_img_lose

        if img is not None:
            # scale to fit nicely
            max_w = int(WINDOW_W * 0.78)
            max_h = int(WINDOW_H * 0.35)
            iw, ih = img.get_width(), img.get_height()
            scale = min(max_w / iw, max_h / ih)
            nw, nh = int(iw * scale), int(ih * scale)
            s2 = pygame.transform.smoothscale(img, (nw, nh))
            screen.blit(s2, ((WINDOW_W - nw) // 2, (WINDOW_H - nh) // 2))
        else:
            text = "La serpiente ha ganado" if g.overlay_type == "WIN" else "Los espectadores han ganado"
            f = pygame.font.SysFont("consolas", 40, bold=True)
            t = f.render(text, True, (255, 255, 255))
            pygame.draw.rect(screen, (25, 25, 30), (WINDOW_W*0.12, WINDOW_H*0.42, WINDOW_W*0.76, 72), border_radius=16)
            screen.blit(t, ((WINDOW_W - t.get_width()) // 2, int(WINDOW_H * 0.44)))

    # ------------------- drawing helpers -------------------
    def _cell_rect(self, g: Game, p: Vec2, play_x: int, play_y: int) -> Tuple[int, int, int, int]:
        x, y = p
        cx = int(play_x + x * g.cell)
        cy = int(play_y + y * g.cell)
        size = int(math.ceil(g.cell))
        return (cx, cy, size, size)

    def _center_of_cell(self, g: Game, p: Vec2, play_x: int, play_y: int) -> Tuple[float, float]:
        x, y = p
        cx = play_x + (x + 0.5) * g.cell
        cy = play_y + (y + 0.5) * g.cell
        return (cx, cy)

    def _draw_apple(self, screen, g: Game, p: Vec2, play_x: int, play_y: int, big: bool):
        pygame = self.pygame
        cx, cy = self._center_of_cell(g, p, play_x, play_y)
        r = g.cell * (0.30 if big else 0.24)
        pygame.draw.circle(screen, COL_APPLE_RED, (int(cx), int(cy)), int(r))
        # highlight
        pygame.draw.circle(screen, (255, 120, 120), (int(cx - r*0.25), int(cy - r*0.2)), int(r*0.28))
        # leaf
        pygame.draw.ellipse(screen, COL_APPLE_LEAF, (int(cx + r*0.05), int(cy - r*0.65), int(r*0.8), int(r*0.45)))
        # stem
        pygame.draw.line(screen, (120, 80, 40), (int(cx), int(cy - r*0.9)), (int(cx), int(cy - r*0.25)), 2)

    def _draw_bomb(self, screen, g: Game, p: Vec2, play_x: int, play_y: int):
        pygame = self.pygame
        cx, cy = self._center_of_cell(g, p, play_x, play_y)
        r = g.cell * 0.28
        pygame.draw.circle(screen, COL_BOMB_DARK, (int(cx), int(cy)), int(r))
        pygame.draw.circle(screen, (90, 90, 95), (int(cx - r*0.2), int(cy - r*0.2)), int(r*0.25))
        # fuse
        pygame.draw.line(screen, COL_BOMB_FUSE, (int(cx + r*0.1), int(cy - r*0.9)), (int(cx + r*0.55), int(cy - r*0.35)), 3)
        pygame.draw.circle(screen, (255, 70, 70), (int(cx + r*0.55), int(cy - r*0.35)), 4)

    def _draw_snake_connected(self, screen, g: Game, play_x: int, play_y: int):
        pygame = self.pygame
        col = g.snake_colors[g.snake_color_idx]

        # Draw body segments as rounded rects + connectors between centers
        # This makes it look continuous (like your “Bot Focused” screenshot).
        rad = int(max(6, g.cell * 0.22))
        thick = int(max(10, g.cell * 0.62))

        centers = [self._center_of_cell(g, p, play_x, play_y) for p in g.snake]

        # connectors
        for i in range(len(centers) - 1):
            x1, y1 = centers[i]
            x2, y2 = centers[i + 1]
            # draw a thick line as rectangle between points
            dx, dy = x2 - x1, y2 - y1
            if abs(dx) > abs(dy):
                # horizontal
                left = min(x1, x2)
                top = y1 - thick / 2
                w = abs(dx)
                h = thick
                pygame.draw.rect(screen, col, (left, top, w, h), border_radius=rad)
            else:
                # vertical
                left = x1 - thick / 2
                top = min(y1, y2)
                w = thick
                h = abs(dy)
                pygame.draw.rect(screen, col, (left, top, w, h), border_radius=rad)

        # segment blobs
        for i, (cx, cy) in enumerate(centers):
            r = thick * (0.52 if i == 0 else 0.48)
            pygame.draw.circle(screen, col, (int(cx), int(cy)), int(r))

        # Head face
        if g.snake:
            hx, hy = centers[0]
            face_r = thick * 0.28
            pygame.draw.circle(screen, (20, 30, 25), (int(hx - face_r*0.45), int(hy - face_r*0.15)), int(face_r*0.32))
            pygame.draw.circle(screen, (20, 30, 25), (int(hx + face_r*0.45), int(hy - face_r*0.15)), int(face_r*0.32))
            pygame.draw.circle(screen, (120, 255, 170), (int(hx - face_r*0.45), int(hy - face_r*0.15)), int(face_r*0.14))
            pygame.draw.circle(screen, (120, 255, 170), (int(hx + face_r*0.45), int(hy - face_r*0.15)), int(face_r*0.14))
            pygame.draw.circle(screen, (20, 30, 25), (int(hx), int(hy + face_r*0.35)), int(face_r*0.18))

    def _draw_nuke_bomb(self, screen, g: Game, play_x: int, play_y: int):
        pygame = self.pygame
        cx, cy = self._center_of_cell(g, g.nuke_center, play_x, play_y)

        # Determine fall offset
        now = pygame.time.get_ticks()
        if g.nuke_phase == "FALL":
            t = clamp(now - g.nuke_start_ms, 0, NUKE_FALL_MS) / float(NUKE_FALL_MS)
            # from above play area to center
            start_y = play_y - 120
            y = start_y + (cy - start_y) * t
        else:
            y = cy

        # Draw vertical nuke sprite (side view)
        # Body
        body_h = g.cell * 1.35
        body_w = g.cell * 0.55
        x = cx - body_w / 2
        top = y - body_h / 2

        pygame.draw.rect(screen, (210, 210, 215), (x, top, body_w, body_h), border_radius=10)
        # nose cone
        pygame.draw.polygon(screen, (235, 235, 240), [
            (cx, top - body_w*0.55),
            (x, top + body_w*0.15),
            (x + body_w, top + body_w*0.15)
        ])
        # fins
        fin_w = body_w * 0.55
        fin_h = body_w * 0.55
        pygame.draw.polygon(screen, (190, 190, 195), [
            (x, top + body_h*0.78),
            (x - fin_w, top + body_h*0.92),
            (x, top + body_h*0.92),
        ])
        pygame.draw.polygon(screen, (190, 190, 195), [
            (x + body_w, top + body_h*0.78),
            (x + body_w + fin_w, top + body_h*0.92),
            (x + body_w, top + body_h*0.92),
        ])
        # radiation symbol (simple)
        r = body_w * 0.22
        pygame.draw.circle(screen, (40, 40, 45), (int(cx), int(top + body_h*0.52)), int(r*2.1))
        pygame.draw.circle(screen, (250, 220, 60), (int(cx), int(top + body_h*0.52)), int(r*1.75))
        pygame.draw.circle(screen, (40, 40, 45), (int(cx), int(top + body_h*0.52)), int(r*0.55))

        # little “warning stripes”
        pygame.draw.rect(screen, (50, 50, 55), (x, top + body_h*0.62, body_w, body_h*0.08))
        pygame.draw.rect(screen, (50, 50, 55), (x, top + body_h*0.72, body_w, body_h*0.08))

    def _draw_nuke_cells(self, screen, g: Game, play_x: int, play_y: int):
        pygame = self.pygame
        # Draw states in cell grid with slight noise for texture
        for p, st in g.nuke_cell_state.items():
            r = self._cell_rect(g, p, play_x, play_y)
            x, y, w, h = r

            # pick base colors
            if st == "hot":
                c1, c2 = NUKE_COL_HOT_A, NUKE_COL_HOT_B
            elif st == "ash":
                c1, c2 = NUKE_COL_ASH_A, NUKE_COL_ASH_B
            else:
                c1, c2 = NUKE_COL_CHAR_A, NUKE_COL_CHAR_B

            # checker noise
            col = c1 if ((p[0] * 17 + p[1] * 31 + g.nuke_radius * 13) % 2 == 0) else c2
            pygame.draw.rect(screen, col, (x, y, w, h))

            # sprinkle
            if st == "hot":
                pygame.draw.circle(screen, (255, 240, 210), (x + w//2, y + h//2), max(1, int(min(w,h)*0.10)))

# ===============================================================
# ========================= UDP INPUT ===========================
# ===============================================================

class UDPReceiver:
    """
    Soporta mensajes como:
    1) JSON puro:
       {"cmd":"SPAWN_BOMB","count":2,"ttl_ms":5000,"who":"X","gift":"Rose"}
    2) Texto + JSON:
       SPAWN_BOMB {"count":2,"ttl_ms":5000,"who":"X","gift":"Rose"}
    3) Texto simple:
       RESET_GAME
    """
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.sock.bind((host, port))

    def poll(self) -> List[Dict]:
        out = []
        while True:
            try:
                data, _addr = self.sock.recvfrom(UDP_MAX_BYTES)
            except BlockingIOError:
                break
            except Exception:
                break
            try:
                msg = data.decode("utf-8", errors="ignore").strip()
                if not msg:
                    continue
                out.append(self._parse(msg))
            except Exception:
                continue
        return [m for m in out if m is not None]

    def _parse(self, msg: str) -> Optional[Dict]:
        # JSON-only
        if msg.startswith("{") and msg.endswith("}"):
            try:
                d = json.loads(msg)
                if isinstance(d, dict):
                    if "cmd" not in d and "command" in d:
                        d["cmd"] = d["command"]
                    return d
            except Exception:
                return None

        # CMD + JSON
        parts = msg.split(" ", 1)
        cmd = parts[0].strip().upper()
        payload = {}
        if len(parts) == 2:
            rest = parts[1].strip()
            if rest.startswith("{") and rest.endswith("}"):
                try:
                    payload = json.loads(rest)
                except Exception:
                    payload = {}
        payload = payload if isinstance(payload, dict) else {}
        payload["cmd"] = payload.get("cmd", cmd)
        return payload


# ===============================================================
# ========================= MAIN LOOP ===========================
# ===============================================================

def apply_udp(game: Game, cmd: Dict):
    """
    Ajusta snakebot como receptor. Listener lo cuadramos después.
    Comandos aceptados (case-insensitive):
    - SPAWN_BOMB / BOMB: {count, ttl_ms, who, gift}
    - SNAKE_COLOR_CYCLE / COLOR_CYCLE: {times, who, gift}
    - SPAWN_EXTRA_FOOD: {count, who, gift}
    - RESET_GAME / RESTART: {who, gift} -> restart inmediato
    - NUKE / NUCLEAR: {who, gift} -> bomba nuclear
    - SPEED_DELTA: {delta, who, gift}
    - PAUSE_TOGGLE: {who, gift}
    - BG_NEXT: {who, gift}
    """
    now = game.pygame.time.get_ticks()
    c = str(cmd.get("cmd", "")).upper()

    who = str(cmd.get("who", "BOT")).strip() or "BOT"
    gift = str(cmd.get("gift", c)).strip() or c

    def push_event(action: str):
        game.last_events.appendleft(ExternalEvent(who=who, gift=gift, action=action, ts_ms=now))
        # footer message for ~7s
        game.last_footer_msg = f'{who} donó "{gift}" → {action}. Gracias.'
        game.last_footer_until = now + 7000

    if c in ("SPAWN_BOMB", "BOMB"):
        count = int(cmd.get("count", SIMULTANEOUS_BOMBS))
        ttl = int(cmd.get("ttl_ms", BOMB_TTL_MS))
        game.spawn_bomb(max(1, count), ttl)
        push_event(f"spawn bomba x{max(1, count)}")

    elif c in ("SNAKE_COLOR_CYCLE", "COLOR_CYCLE"):
        times = int(cmd.get("times", 1))
        game.cycle_color(max(1, times))
        push_event("cambio de color")

    elif c in ("SPAWN_EXTRA_FOOD", "EXTRA_FOOD"):
        count = int(cmd.get("count", 1))
        for _ in range(max(1, count)):
            game._spawn_extra_food()
        push_event(f"comida extra x{max(1, count)}")

    elif c in ("RESET_GAME", "RESTART"):
        game.restart_immediate()
        push_event("restart inmediato")

    elif c in ("NUKE", "NUCLEAR"):
        game.trigger_nuke()
        push_event("bomba nuclear activada")

    elif c == "SPEED_DELTA":
        delta = int(cmd.get("delta", 0))
        game.fps = clamp(game.fps + delta, 4, 60)
        push_event(f"velocidad {game.fps}")

    elif c == "PAUSE_TOGGLE":
        game.toggle_pause()
        push_event("pausa" if game.paused else "reanudar")

    elif c == "BG_NEXT":
        game.next_background()
        push_event(f"fondo -> {game.bg.bg_name if game.bg.has_images() else 'DARK'}")


def main():
    import pygame

    pygame.init()
    pygame.display.set_caption(f"SnakeBot {VERSION}")
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))

    rng = random.Random()
    rng.seed(int(time.time() * 1000) ^ 0xA55A5AA5)

    g = Game(pygame, rng)
    r = Renderer(pygame)

    udp = UDPReceiver(UDP_HOST, UDP_PORT)

    clock = pygame.time.Clock()

    while True:
        now = pygame.time.get_ticks()

        # keep footer message alive window
        if g.last_footer_until and now > g.last_footer_until:
            g.last_footer_until = 0
            # keep last message faintly? no, clear
            g.last_footer_msg = ""

        # events
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    pygame.quit()
                    return

                # --- Required keys ---
                if ev.key == pygame.K_j:  # J = disminuir velocidad
                    g.fps = clamp(g.fps - 1, 4, 60)
                elif ev.key == pygame.K_l:  # L = aumentar velocidad
                    g.fps = clamp(g.fps + 1, 4, 60)
                elif ev.key == pygame.K_z:  # Z = comida extra (no respawn)
                    g._spawn_extra_food()
                    # log action
                    g.last_events.appendleft(ExternalEvent("BOT", "Key Z", "comida extra", now))
                    g.last_footer_msg = 'BOT donó "Key Z" → comida extra. Gracias.'
                    g.last_footer_until = now + 2500
                elif ev.key == pygame.K_x:  # X = bomba normal
                    g.spawn_bomb(SIMULTANEOUS_BOMBS, BOMB_TTL_MS)
                    g.last_events.appendleft(ExternalEvent("BOT", "Key X", "spawn bomba", now))
                    g.last_footer_msg = 'BOT donó "Key X" → spawn bomba. Gracias.'
                    g.last_footer_until = now + 2500
                elif ev.key == pygame.K_c:  # C = ciclo color
                    g.cycle_color(1)
                    g.last_events.appendleft(ExternalEvent("BOT", "Key C", "cambio de color", now))
                    g.last_footer_msg = 'BOT donó "Key C" → cambio de color. Gracias.'
                    g.last_footer_until = now + 2500
                elif ev.key == pygame.K_r:  # R = restart inmediato
                    g.restart_immediate()
                    g.last_events.appendleft(ExternalEvent("BOT", "Key R", "restart inmediato", now))
                    g.last_footer_msg = 'BOT donó "Key R" → restart inmediato. Gracias.'
                    g.last_footer_until = now + 2500
                elif ev.key == pygame.K_b:  # B = bomba nuclear
                    g.trigger_nuke()
                    g.last_events.appendleft(ExternalEvent("BOT", "Key B", "bomba nuclear activada", now))
                    g.last_footer_msg = 'BOT donó "Key B" → bomba nuclear activada. Gracias.'
                    g.last_footer_until = now + 2500
                elif ev.key == pygame.K_k:  # K = pausa
                    g.toggle_pause()
                    g.last_events.appendleft(ExternalEvent("BOT", "Key K", "pausa" if g.paused else "reanudar", now))
                    g.last_footer_msg = f'BOT donó "Key K" → {"pausa" if g.paused else "reanudar"}. Gracias.'
                    g.last_footer_until = now + 2500
                elif ev.key == pygame.K_w:  # W = cambiar fondo (si hay)
                    g.next_background()
                    g.last_events.appendleft(ExternalEvent("BOT", "Key W", f"fondo -> {g.bg.bg_name if g.bg.has_images() else 'DARK'}", now))
                    g.last_footer_msg = f'BOT donó "Key W" → fondo -> {g.bg.bg_name if g.bg.has_images() else "DARK"}.'
                    g.last_footer_until = now + 2500

        # UDP commands
        for cmd in udp.poll():
            apply_udp(g, cmd)

        # update game
        g.update()

        # render
        r.draw(screen, g)
        pygame.display.flip()

        # fps: use g.fps, but animations are time-based (not tied to fps)
        clock.tick(g.fps)

if __name__ == "__main__":
    main()