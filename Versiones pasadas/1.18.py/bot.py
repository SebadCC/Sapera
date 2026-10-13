# bot.py
from __future__ import annotations

import random
from collections import deque
from typing import Deque, List, Optional, Protocol, Set, Tuple, Dict

from game import (
    Point,
    Direction,
    DIRS,
    GameConfig,
    GameState,
    Food,
    head_step,
    manhattan,
    layer_index,
)

# BOT TUNING (SOLO estas dos variables)
PATTERN_VS_FOOD = 7       # 1..10
PATTERN_VS_DYNAMISM = 6   # 1..10


# ============================================================
# Patrones (igual que tu versión)
# ============================================================

class Pattern(Protocol):
    name: str
    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        ...


class SpiralPattern:
    name = "spiral"

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

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        best = state.direction
        best_score = -1e9
        for d in DIRS:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue
            lyr = layer_index(nxt, cfg.n)
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
        head = state.snake[0]
        prefer_horizontal = (state.tick // 20) % 2 == 0
        if prefer_horizontal:
            return Direction.RIGHT if head.x < cfg.n - 1 else Direction.LEFT
        return Direction.DOWN if head.y < cfg.n - 1 else Direction.UP


class DiagonalPattern:
    name = "diagonal"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        head = state.snake[0]
        t = state.tick // 25
        if t % 2 == 0:
            return Direction.RIGHT if head.x < cfg.n - 1 else Direction.DOWN
        return Direction.LEFT if head.x > 0 else Direction.DOWN


class SmoothRandomPattern:
    name = "smooth_random"

    def preferred_direction(self, state: GameState, cfg: GameConfig, rng: random.Random) -> Direction:
        if rng.random() < 0.75:
            return state.direction
        turns = {
            Direction.UP: [Direction.LEFT, Direction.RIGHT],
            Direction.DOWN: [Direction.LEFT, Direction.RIGHT],
            Direction.LEFT: [Direction.UP, Direction.DOWN],
            Direction.RIGHT: [Direction.UP, Direction.DOWN],
        }
        return rng.choice(turns[state.direction])


class HamiltonPattern:
    name = "hamilton"

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
# BOT (v1.17): evita bucles con “goal forcing” suave
# - Si detecta loop, entra en "escape_mode" por X ticks.
# - En escape_mode fuerza target = comida más cercana (y sube peso comida),
#   siempre respetando safe_moves.
# ============================================================

class BotController:
    def __init__(self, rng: random.Random, patterns: List[Pattern]):
        self.rng = rng
        self.patterns = patterns
        self.current_idx = 0
        self.next_switch_tick = 0

        self.pattern_vs_food = max(1, min(10, int(PATTERN_VS_FOOD)))
        self.pattern_vs_dyn = max(1, min(10, int(PATTERN_VS_DYNAMISM)))

        # anti-loop forcing
        self.escape_until_tick: int = 0
        self.last_forced_target: Optional[Point] = None

    def choose_direction(self, state: GameState, cfg: GameConfig) -> Direction:
        self._maybe_switch_pattern(state)

        safe_moves = self._safe_moves(state, cfg)
        if not safe_moves:
            return self._best_delay_death_move(state, cfg)

        loop_detected = self._detect_loop(state)
        if loop_detected and state.tick >= state.cycle_penalty_until:
            # mantiene tu castigo original
            state.cycle_penalty_until = state.tick + 40
            # NUEVO: forzar “salida” unos ticks
            self.escape_until_tick = max(self.escape_until_tick, state.tick + 30)
            self.last_forced_target = None

        pat = self.patterns[self.current_idx]
        pat_dir = pat.preferred_direction(state, cfg, self.rng)

        food_targets = [f.pos for f in state.foods]
        food_target = (
            min(food_targets, key=lambda p: manhattan(state.snake[0], p))
            if food_targets else state.snake[0]
        )

        # base weights
        pattern_weight = (11 - self.pattern_vs_dyn) / 10.0
        food_weight = self.pattern_vs_food / 10.0

        # EN ESCAPE: empujar a comida y bajar patrón (pero sin suicidarse)
        if state.tick < self.escape_until_tick and food_targets:
            food_weight *= 1.45
            pattern_weight *= 0.65
            self.last_forced_target = food_target

        head = state.snake[0]
        tail = state.snake[-1]

        best_d = safe_moves[0]
        best_score = -1e18

        for d in safe_moves:
            nxt = head_step(head, d, cfg)
            if nxt is None:
                continue

            dist_food = manhattan(nxt, food_target)
            pat_bonus = 1.0 if d == pat_dir else 0.0

            jitter = (self.pattern_vs_dyn / 10.0) * 0.35
            rand_j = self.rng.uniform(-jitter, jitter)

            straight_bonus = 0.25 if d == state.direction else 0.0

            head_tail_dist = manhattan(nxt, tail)
            tail_avoid = 0.0
            if head_tail_dist <= 2:
                tail_avoid = -1.2 * (3 - head_tail_dist)

            loop_pen = 0.0
            if state.tick < state.cycle_penalty_until:
                occ = sum(1 for p in list(state.head_history)[-80:] if p == nxt)
                loop_pen = -0.8 * min(4, occ)

            score = 0.0
            score += (-dist_food) * (2.3 * food_weight)
            score += pat_bonus * (2.0 * pattern_weight)
            score += straight_bonus
            score += tail_avoid
            score += loop_pen
            score += rand_j

            # bonus por comer ya
            if any(nxt == f.pos for f in state.foods):
                score += 6.0

            # (este helper venía en 1.16 como único cambio: lo dejamos)
            score += self._small_empty_components_penalty(state, cfg, proposed_dir=d)

            # EN ESCAPE: evitar “volver” a la celda de hace 2 ticks si hay alternativa
            if state.tick < self.escape_until_tick:
                hist = list(state.head_history)
                if len(hist) >= 3:
                    back2 = hist[-3]
                    if nxt == back2:
                        score -= 2.2

            if score > best_score:
                best_score = score
                best_d = d

        return best_d

    # --------------------------------------------------------

    def _maybe_switch_pattern(self, state: GameState) -> None:
        dyn = self.pattern_vs_dyn / 10.0
        base = 55
        interval = int(base * (1.10 - 0.70 * dyn))
        interval = max(18, interval)

        if state.tick >= self.next_switch_tick:
            p = 0.25 + 0.60 * dyn
            if self.rng.random() < p:
                self.current_idx = self.rng.randrange(0, len(self.patterns))
            self.next_switch_tick = state.tick + interval

    def _safe_moves(self, state: GameState, cfg: GameConfig) -> List[Direction]:
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

            eats = any(nxt == f.pos for f in state.foods)

            if nxt in snake_set:
                if not eats and nxt == tail:
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
            b = hist[-2*L:-L]
            c = hist[-3*L:-2*L]
            if a == b == c:
                return True
        return False

    # -------------------- helper (igual a 1.16) --------------------

    def _small_empty_components_penalty(self, state: GameState, cfg: GameConfig, proposed_dir: Direction) -> float:
        head = state.snake[0]
        nxt = head_step(head, proposed_dir, cfg)
        if nxt is None:
            return 0.0

        eats = any(nxt == f.pos for f in state.foods)

        projected = deque(state.snake)
        projected.appendleft(nxt)
        if not eats:
            projected.pop()

        occupied = set(projected) | set(state.bombs.keys()) | {f.pos for f in state.foods}
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
