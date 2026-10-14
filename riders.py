# ============================================================
# riders.py — Los Jinetes: Inteligencia Táctica, Patrones y Toma de Decisiones
# ============================================================
# El Jinete recibe del Caballo el conjunto de movimientos seguros
# y evalúa cuál satisface mejor su deseo (comida, geometría o combate)
# sin violar la supervivencia.
# ============================================================

import random
from typing import List, Protocol
from config import WRAP_SAFE_WARNING_MS
from models import (
    Point, Direction, DIRS, SnakeMode, GameMode, ColosseumSnake, ColosseumState,
    in_bounds, wrap, dist_for_config, layer_index, FACTION_OFFENSIVE_PHRASES
)
from horse import HorseVerifier

# ============================================================
# Protocolo y Familias de Patrones Geométricos
# ============================================================

class Pattern(Protocol):
    name: str
    display: str
    def preferred_direction(self, head: Point, cur_dir: Direction, n: int, wall_col: bool, tick: int, rng: random.Random) -> Direction: ...

class SpiralPattern:
    """
    Espiral Oscilante (Inward / Outward):
    Alterna entre espiral centrípeta (hacia el núcleo) y centrífuga (hacia afuera)
    para barrer armónicamente todo el tablero sin atascarse en la pared.
    """
    name = "spiral"
    display = "Espiral Zen"

    def preferred_direction(self, head: Point, cur_dir: Direction, n: int, wall_col: bool, tick: int, rng: random.Random) -> Direction:
        cur_lyr = layer_index(head, n)
        # Cada 140 ticks alterna el flujo: hacia el centro o hacia la periferia
        flow_inward = ((tick // 140) % 2 == 0)

        best, best_score = cur_dir, -1e9
        for d in DIRS:
            nxt = Point(head.x + d.dx, head.y + d.dy)
            if wall_col and not in_bounds(nxt, n): continue
            nxt = wrap(nxt, n)

            nxt_lyr = layer_index(nxt, n)
            if flow_inward:
                lyr_diff = (nxt_lyr - cur_lyr) # Premia entrar al centro
            else:
                lyr_diff = (cur_lyr - nxt_lyr) # Premia salir hacia el borde

            score = lyr_diff * 3.0 + (1.0 if d == cur_dir else 0.0) * 0.7 + rng.uniform(-0.05, 0.05)
            if score > best_score:
                best_score, best = score, d

        return best

class PerimeterPattern:
    """
    Loop Perimetral:
    Prioriza orbitar la capa exterior del tablero.
    """
    name = "perimeter"
    display = "Loop Perimetral"

    def preferred_direction(self, head: Point, cur_dir: Direction, n: int, wall_col: bool, tick: int, rng: random.Random) -> Direction:
        best, best_score = cur_dir, -1e9
        for d in DIRS:
            nxt = Point(head.x + d.dx, head.y + d.dy)
            if wall_col and not in_bounds(nxt, n): continue
            nxt = wrap(nxt, n)
            score = -(layer_index(nxt, n) * 2.2) + (1.0 if d == cur_dir else 0.0) * 0.6 + rng.uniform(-0.05, 0.05)
            if score > best_score:
                best_score, best = score, d
        return best

class ZigZagPattern:
    """
    Onda Sinusoidal:
    Barrer horizontalmente y verticalmente en zigzag.
    """
    name = "zigzag"
    display = "ZigZag"

    def preferred_direction(self, head: Point, cur_dir: Direction, n: int, wall_col: bool, tick: int, rng: random.Random) -> Direction:
        if (tick // 22) % 2 == 0:
            return Direction.RIGHT if head.x < n - 1 else Direction.LEFT
        return Direction.DOWN if head.y < n - 1 else Direction.UP

class SmoothFlowPattern:
    """
    Flujo Suave:
    Inercia y curvas abiertas de bajo ángulo.
    """
    name = "smooth"
    display = "Flujo Suave"

    def preferred_direction(self, head: Point, cur_dir: Direction, n: int, wall_col: bool, tick: int, rng: random.Random) -> Direction:
        if rng.random() < 0.88: return cur_dir
        turns = {
            Direction.UP: [Direction.LEFT, Direction.RIGHT],
            Direction.DOWN: [Direction.LEFT, Direction.RIGHT],
            Direction.LEFT: [Direction.UP, Direction.DOWN],
            Direction.RIGHT: [Direction.UP, Direction.DOWN]
        }
        return rng.choice(turns[cur_dir])

# ============================================================
# Controlador Multi-Agente (Orquestador de Caballos y Jinetes)
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
        n = state.grid_size

        # 1. Consciencia temporal de paredes (anticipación de 1.5s antes del fin del wrap)
        effective_wall_col = state.wall_collision
        if not state.wall_collision and state.wrap_mode_until_ms > 0:
            if state.wrap_mode_until_ms - now_ms < WRAP_SAFE_WARNING_MS:
                effective_wall_col = True

        # 2. Detección de bucles mediante el Caballo
        loop_detected = HorseVerifier.detect_loop(snake)
        if loop_detected and state.tick >= snake.cycle_penalty_until:
            snake.cycle_penalty_until = state.tick + 50
            # Conmutar forzosamente de patrón para romper la geometría cíclica
            snake.pattern_idx = (snake.pattern_idx + 1) % len(self.patterns)
            snake.last_switch_tick = state.tick

        # 3. Petición al Caballo de movimientos seguros
        safe_moves = HorseVerifier.get_safe_moves(snake, state, now_ms, effective_wall_col, n)
        if not safe_moves:
            return HorseVerifier.best_delay_death(snake, state, effective_wall_col, n)

        # 4. Objetivos de atracción
        targets = [f.pos for f in state.foods]
        golden = (snake.mode == SnakeMode.GOLDEN and snake.mode_until_ms > now_ms)
        if golden and state.bombs: targets += list(state.bombs.keys())

        head = snake.body[0]
        tail = snake.body[-1]
        food_target = min(targets, key=lambda p: dist_for_config(head, p, effective_wall_col, n)) if targets else head

        # 5. Ponderaciones del Jinete según Modo de Juego
        if state.game_mode == GameMode.SPEEDRUN:
            # Codicia voraz pura
            pat_dir = snake.direction
            pat_weight = 0.05
            food_weight = 2.80
        elif state.game_mode == GameMode.HYPNOTIC:
            L = len(snake.body)
            if L < 10:
                # Caza temprana rápida para ganar presencia inicial
                pat_weight = 0.35
                food_weight = 2.10
            else:
                # Conmutación temporal regular de patrones cada 280 ticks
                if state.tick - snake.last_switch_tick >= 280:
                    snake.pattern_idx = (snake.pattern_idx + 1) % len(self.patterns)
                    snake.last_switch_tick = state.tick

                # Pulso de Hambre Zen: Si pasa más de 120 ticks sin comer, se desvía suavemente
                if snake.hunger_ticks > 120:
                    urgency = min(1.0, (snake.hunger_ticks - 120) / 100.0)
                    pat_weight = 1.10 - 0.50 * urgency
                    food_weight = 0.90 + 1.30 * urgency
                else:
                    pat_weight = 1.35
                    food_weight = 0.95

            pat = self.patterns[snake.pattern_idx % len(self.patterns)]
            pat_dir = pat.preferred_direction(head, snake.direction, n, effective_wall_col, state.tick, self.rng)
        else:
            # Coliseo / Battle Royale & Duelo 1v1
            L = len(snake.body)
            pers_scale = min(1.0, L / 16.0)
            pat_weight = 0.8 + (profile.pattern_weight - 0.8) * pers_scale
            food_weight = 1.0 + (profile.food_weight - 1.0) * pers_scale
            pat = self.patterns[snake.pattern_idx % len(self.patterns)]
            pat_dir = pat.preferred_direction(head, snake.direction, n, effective_wall_col, state.tick, self.rng)

        # 6. Evaluación de las opciones seguras del Caballo
        best_d = safe_moves[0]
        best_score = -1e18

        for d in safe_moves:
            cand = Point(head.x + d.dx, head.y + d.dy)
            nxt = cand if effective_wall_col else wrap(cand, n)

            dist_food = dist_for_config(nxt, food_target, effective_wall_col, n)
            pat_bonus = 1.0 if d == pat_dir else 0.0
            straight_bonus = 0.40 if d == snake.direction else -0.25

            free_cells = (n * n) - len(snake.body) - len(state.bombs)
            is_late_game = (free_cells < 25)

            tail_dist = dist_for_config(nxt, tail, effective_wall_col, n)
            if is_late_game:
                # En juego tardío (<25 celdas libres), seguir la cola mantiene el espacio continuo entre cabeza y cola
                tail_avoid = (10 - min(10, tail_dist)) * 1.8
            else:
                tail_avoid = -profile.tail_avoid_factor * (3 - tail_dist) if tail_dist <= 2 else 0.0

            # Anti-choque frontal con cabezas rivales
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

            loop_pen = HorseVerifier.loop_penalty(snake, nxt, state)
            jitter = self.rng.uniform(-0.04, 0.04)

            score = 0.0
            score += (-dist_food) * (2.2 * food_weight)
            score += pat_bonus * (2.0 * pat_weight)
            score += straight_bonus + tail_avoid + rival_danger_pen + center_bonus + loop_pen + jitter

            if any(nxt == f.pos for f in state.foods): score += 7.0
            if golden and (nxt in state.bombs): score += 7.0

            # Penalización por huecos pequeños verificada por el Caballo
            score += HorseVerifier.small_empty_components_penalty(nxt, snake, state, effective_wall_col, now_ms, n)

            if score > best_score:
                best_score = score
                best_d = d

        return best_d
