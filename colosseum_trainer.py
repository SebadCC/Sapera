# Snake — The Colosseum & SaperaAI — Parallel Headless Trainer
# Simulación masiva ultra-rápida (6 Arenas en Paralelo) con Evolución Genética (ES)

from __future__ import annotations

import os
import sys
import json
import time
import math
import random
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import deque
from typing import Deque, Dict, List, Optional, Set, Tuple, Any
import multiprocessing as mp

# ============================================================
# Estructuras de Dominio (Sin Dependencia de Pantalla)
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

def dist_plane(a: Point, b: Point) -> int: return abs(a.x - b.x) + abs(a.y - b.y)
def dist_toroidal(a: Point, b: Point, n: int) -> int:
    dx = abs(a.x - b.x)
    dy = abs(a.y - b.y)
    return min(dx, n - dx) + min(dy, n - dy)

def dist_calc(a: Point, b: Point, wall_col: bool, n: int) -> int:
    return dist_plane(a, b) if wall_col else dist_toroidal(a, b, n)

def layer_idx(p: Point, n: int) -> int:
    return min(p.x, p.y, n - 1 - p.x, n - 1 - p.y)

# ============================================================
# Facciones del Coliseo (5 Facciones)
# ============================================================

class FactionId(Enum):
    RED = "RED"       # Fénix Carmesí (Voraz / Depredador)
    GREEN = "GREEN"   # Cobra Esmeralda (Zen / Aikido)
    BLUE = "BLUE"     # Dragón Zafiro (Territorial / Centro)
    PURPLE = "PURPLE" # Víbora Amatista (Mística / Emboscada)
    GOLD = "GOLD"     # Basilisco Ámbar (El Titán / Kingmaker Maquiavélico)

# Genoma del Jinete (Vector de Pesos Estratégicos)
@dataclass
class JineteWeights:
    w_voronoi: float = 1.0         # Peso de dominancia territorial
    w_hunger: float = 1.0          # Apetito por comida
    w_holgura: float = 1.5         # Preferencia por pasillos de 2-3 casillas
    w_agresion: float = 1.0        # Tendencia a cortar cabezas rivales
    w_bomb_buffer: float = 2.0     # Margen de seguridad preventivo ante bombas
    w_center_drift: float = 0.5    # Preferencia por controlar el centro
    w_straight: float = 0.3        # Inercia de movimiento (fluidez visual)
    w_tail_avoid: float = 1.2      # Distancia preventiva a colas
    w_pot_ambition: float = 0.8    # Tendencia a ejecutar la "Olla"

DEFAULT_WEIGHTS: Dict[FactionId, JineteWeights] = {
    FactionId.RED: JineteWeights(w_voronoi=0.9, w_hunger=2.5, w_holgura=0.8, w_agresion=2.8, w_bomb_buffer=1.2, w_center_drift=0.3, w_straight=0.4, w_tail_avoid=0.9, w_pot_ambition=1.8),
    FactionId.GREEN: JineteWeights(w_voronoi=1.4, w_hunger=0.6, w_holgura=3.5, w_agresion=0.3, w_bomb_buffer=3.2, w_center_drift=0.5, w_straight=0.6, w_tail_avoid=2.2, w_pot_ambition=0.3),
    FactionId.BLUE: JineteWeights(w_voronoi=2.2, w_hunger=1.0, w_holgura=1.8, w_agresion=1.4, w_bomb_buffer=2.0, w_center_drift=2.2, w_straight=0.3, w_tail_avoid=1.5, w_pot_ambition=1.4),
    FactionId.PURPLE: JineteWeights(w_voronoi=1.3, w_hunger=1.4, w_holgura=1.6, w_agresion=1.9, w_bomb_buffer=1.8, w_center_drift=0.8, w_straight=0.2, w_tail_avoid=1.1, w_pot_ambition=1.5),
    FactionId.GOLD: JineteWeights(w_voronoi=1.8, w_hunger=1.2, w_holgura=2.2, w_agresion=1.5, w_bomb_buffer=2.4, w_center_drift=1.5, w_straight=0.5, w_tail_avoid=1.8, w_pot_ambition=1.6),
}

# ============================================================
# Estado y Simulación Ligera del Coliseo
# ============================================================

class SnakeMode(Enum):
    NORMAL = "NORMAL"
    EXTASIS = "EXTASIS"
    GOLDEN = "GOLDEN"

@dataclass
class SimSnake:
    snake_id: int
    faction: FactionId
    body: Deque[Point]
    direction: Direction
    alive: bool = True
    score: int = 0
    grow_pending: int = 0
    mode: SnakeMode = SnakeMode.NORMAL
    mode_until_tick: int = 0
    kills: int = 0
    ticks_survived: int = 0
    bombs_survived_near: int = 0
    voronoi_accum: float = 0.0

@dataclass
class ArenaConfig:
    arena_id: str
    name: str
    grid_size: int
    num_snakes: int

ARENA_CONFIGS: List[ArenaConfig] = [
    ArenaConfig("arena_4p_normal", "4P Normal (22x22)", 22, 4),
    ArenaConfig("arena_4p_reduced", "4P Reducido (16x16)", 16, 4),
    ArenaConfig("arena_4p_expanded", "4P Ampliado (32x32)", 32, 4),
    ArenaConfig("arena_5p_normal", "5P Normal (22x22)", 22, 5),
    ArenaConfig("arena_5p_expanded", "5P Ampliado (32x32)", 32, 5),
    ArenaConfig("arena_5p_mega", "5P Mega (48x48)", 48, 5)
]

# ============================================================
# El Caballo Sagrado (Filtro Anti-Suicidio BFS) y el Jinete
# ============================================================

class BotEngine:
    @staticmethod
    def safe_moves(snake: SimSnake, all_snakes: List[SimSnake], bombs: Set[Point], foods: Set[Point], n: int, wall_col: bool) -> List[Direction]:
        head = snake.body[0]
        tail = snake.body[-1]
        golden = (snake.mode == SnakeMode.GOLDEN)

        blocked: Set[Point] = set()
        if not golden:
            blocked |= bombs
        for s in all_snakes:
            if s.alive and s.snake_id != snake.snake_id:
                blocked |= set(s.body)

        own_body = list(snake.body)
        own_set = set(own_body)

        safe = []
        for d in DIRS:
            cand = Point(head.x + d.dx, head.y + d.dy)
            if wall_col and not in_bounds(cand, n): continue
            nxt = cand if wall_col else wrap(cand, n)

            if nxt in blocked: continue

            eats = (nxt in foods) or (golden and nxt in bombs)
            if nxt in own_set:
                if not eats and snake.grow_pending == 0 and nxt == tail:
                    pass
                else:
                    continue

            # Simular serpiente proyectada
            proj = deque(own_body)
            proj.appendleft(nxt)
            if not eats and snake.grow_pending == 0:
                proj.pop()

            # Mandato de Escape a la Cola
            if not BotEngine._has_escape(proj, blocked, n, wall_col):
                continue

            safe.append(d)
        return safe

    @staticmethod
    def _has_escape(proj_snake: Deque[Point], blocked_env: Set[Point], n: int, wall_col: bool) -> bool:
        head = proj_snake[0]
        tail = proj_snake[-1]

        snake_block = set(proj_snake)
        if tail in snake_block: snake_block.remove(tail)
        total_block = snake_block | blocked_env
        if tail in total_block: total_block.remove(tail)

        q = deque([head])
        seen = {head}
        while q:
            cur = q.popleft()
            if cur == tail: return True
            for d in DIRS:
                cand = Point(cur.x + d.dx, cur.y + d.dy)
                if wall_col and not in_bounds(cand, n): continue
                nxt = cand if wall_col else wrap(cand, n)
                if nxt in seen or nxt in total_block: continue
                seen.add(nxt)
                q.append(nxt)
        return False

    @staticmethod
    def decide_move(snake: SimSnake, all_snakes: List[SimSnake], bombs: Set[Point], foods: Set[Point],
                    n: int, wall_col: bool, weights: JineteWeights, rng: random.Random) -> Direction:
        safe_moves = BotEngine.safe_moves(snake, all_snakes, bombs, foods, n, wall_col)
        if not safe_moves:
            # Demorar muerte lo máximo posible
            head = snake.body[0]
            blocked = set(bombs)
            for s in all_snakes:
                if s.alive: blocked |= set(s.body)
            best_d, best_free = snake.direction, -1
            for d in DIRS:
                cand = Point(head.x + d.dx, head.y + d.dy)
                if wall_col and not in_bounds(cand, n): continue
                nxt = cand if wall_col else wrap(cand, n)
                if nxt in blocked: continue
                free = sum(1 for dd in DIRS if (wrap(Point(nxt.x + dd.dx, nxt.y + dd.dy), n) not in blocked))
                if free > best_free: best_free, best_d = free, d
            return best_d

        if len(safe_moves) == 1:
            return safe_moves[0]

        head = snake.body[0]
        tail = snake.body[-1]
        golden = (snake.mode == SnakeMode.GOLDEN)

        # Destino prioritario de comida
        targets = list(foods)
        if golden and bombs: targets += list(bombs)
        food_target = min(targets, key=lambda p: dist_calc(head, p, wall_col, n)) if targets else head

        best_score = -1e18
        best_d = safe_moves[0]

        for d in safe_moves:
            cand = Point(head.x + d.dx, head.y + d.dy)
            nxt = cand if wall_col else wrap(cand, n)

            dist_food = dist_calc(nxt, food_target, wall_col, n)
            score = (-dist_food) * (1.8 * weights.w_hunger)

            if d == snake.direction: score += 0.5 * weights.w_straight

            # Distancia preventiva a bombas
            if not golden and bombs:
                min_b_dist = min(dist_calc(nxt, b, wall_col, n) for b in bombs)
                if min_b_dist <= 2: score -= (3 - min_b_dist) * (3.0 * weights.w_bomb_buffer)

            # Control de centro
            lyr = layer_idx(nxt, n)
            if 2 <= lyr <= n // 3: score += 1.2 * weights.w_center_drift

            # Holgura de pasillo (contar salidas abiertas a 2 pasos)
            open_neighbors = 0
            for dd in DIRS:
                c2 = Point(nxt.x + dd.dx, nxt.y + dd.dy)
                if wall_col and not in_bounds(c2, n): continue
                p2 = c2 if wall_col else wrap(c2, n)
                if p2 not in bombs and not any(p2 in s.body for s in all_snakes if s.alive):
                    open_neighbors += 1
            if open_neighbors >= 3: score += 1.5 * weights.w_holgura
            elif open_neighbors == 1: score -= 2.0 * weights.w_holgura

            # Agresión / Anti-choque
            for other in all_snakes:
                if other.alive and other.snake_id != snake.snake_id:
                    d_rival = dist_calc(nxt, other.body[0], wall_col, n)
                    if d_rival <= 1:
                        # Si somos mucho más grandes, intentar cortar; si no, evitar choque frontal
                        if len(snake.body) > len(other.body) + 4: score += 3.0 * weights.w_agresion
                        else: score -= 9.0
                    elif d_rival == 2 and weights.w_pot_ambition > 1.2:
                        score += 2.0 * weights.w_pot_ambition

            score += rng.uniform(-0.02, 0.02)

            if score > best_score:
                best_score = score
                best_d = d

        return best_d

# ============================================================
# Simulador de Partida Headless con Eventos TikTok
# ============================================================

class ArenaMatch:
    def __init__(self, config: ArenaConfig, weights_map: Dict[FactionId, JineteWeights], rng: random.Random):
        self.config = config
        self.weights = weights_map
        self.rng = rng
        self.n = config.grid_size
        self.wall_collision = True
        self.wrap_until_tick = 0
        self.bombs: Dict[Point, int] = {} # pos -> expire_tick
        self.foods: Set[Point] = set()
        self.snakes: List[SimSnake] = []
        self._init_snakes()
        target_foods = max(4, (self.n * self.n) // 100)
        self._spawn_foods(target_foods)

    def _init_snakes(self) -> None:
        factions = [FactionId.RED, FactionId.GREEN, FactionId.BLUE, FactionId.PURPLE, FactionId.GOLD][:self.config.num_snakes]
        n = self.n
        starts = [
            (Point(3, 3), Direction.RIGHT),
            (Point(n - 4, 3), Direction.DOWN),
            (Point(n - 4, n - 4), Direction.LEFT),
            (Point(3, n - 4), Direction.UP),
            (Point(n // 2, n // 2), Direction.RIGHT)
        ]
        for i, fac in enumerate(factions):
            st, dir_ = starts[i]
            body = deque([Point(st.x - dir_.dx * k, st.y - dir_.dy * k) for k in range(5)])
            self.snakes.append(SimSnake(snake_id=i, faction=fac, body=body, direction=dir_))

    def _spawn_foods(self, count: int) -> None:
        occupied = set(self.foods) | set(self.bombs.keys())
        for s in self.snakes:
            if s.alive: occupied |= set(s.body)
        attempts = 0
        while len(self.foods) < count and attempts < 100:
            attempts += 1
            p = Point(self.rng.randint(0, self.n - 1), self.rng.randint(0, self.n - 1))
            if p not in occupied: self.foods.add(p)

    def run_match(self, max_ticks: int = 1500) -> Dict[str, Any]:

        bomb_set = set(self.bombs.keys())
        for tick in range(1, max_ticks + 1):
            # 1. Eventos estocásticos de TikTok (Poisson)
            self._simulate_tiktok_events(tick)

            # Limpiar bombas expiradas
            expired = [p for p, exp in self.bombs.items() if tick >= exp]
            for p in expired: del self.bombs[p]
            bomb_set = set(self.bombs.keys())

            effective_wall_col = self.wall_collision
            if not self.wall_collision and self.wrap_until_tick > 0:
                if self.wrap_until_tick - tick < 15: effective_wall_col = True
                if tick >= self.wrap_until_tick: self.wall_collision = True

            # 2. Decisiones de las serpientes
            for s in self.snakes:
                if s.alive:
                    s.direction = BotEngine.decide_move(s, self.snakes, bomb_set, self.foods,
                                                        self.n, effective_wall_col, self.weights[s.faction], self.rng)

            # 3. Mover y evaluar
            self._step_snakes(tick, effective_wall_col)

            # Calcular Voronoi simple cada 5 ticks para métricas
            if tick % 5 == 0:
                self._update_voronoi()

            alive = [s for s in self.snakes if s.alive]
            if len(alive) <= 1:
                break

        # Fin de partida: compilar resultados
        winner = next((s for s in self.snakes if s.alive), None)
        return {
            "ticks": tick,
            "winner_faction": winner.faction.value if winner else "DRAW",
            "stats": {s.faction.value: {
                "score": s.score,
                "length": len(s.body),
                "kills": s.kills,
                "ticks": s.ticks_survived,
                "voronoi": s.voronoi_accum
            } for s in self.snakes}
        }

    def _simulate_tiktok_events(self, tick: int) -> None:
        # Rosas (1 moneda): Bomba o Manzana frecuente (~cada 30 ticks)
        if self.rng.random() < 0.035:
            p = Point(self.rng.randint(1, self.n - 2), self.rng.randint(1, self.n - 2))
            if self.rng.random() < 0.6:
                self.bombs[p] = tick + 60
            else:
                self.foods.add(p)

        # Corazón (5 monedas): Modo Éxtasis (~cada 400 ticks)
        if self.rng.random() < 0.0025:
            alive_s = [s for s in self.snakes if s.alive]
            if alive_s:
                tgt = self.rng.choice(alive_s)
                tgt.mode = SnakeMode.EXTASIS
                tgt.mode_until_tick = tick + 100

        # Dragón / Corona (1000 monedas): Modo Dorado (~cada 1000 ticks)
        if self.rng.random() < 0.0010:
            alive_s = [s for s in self.snakes if s.alive]
            if alive_s:
                tgt = self.rng.choice(alive_s)
                tgt.mode = SnakeMode.GOLDEN
                tgt.mode_until_tick = tick + 80

        # León (30000 monedas): Bomba Atómica (~cada 2000 ticks)
        if self.rng.random() < 0.0005:
            cx, cy = self.n // 2, self.n // 2
            r = min(6, self.n // 3)
            for s in self.snakes:
                if s.alive and s.mode != SnakeMode.GOLDEN:
                    h = s.body[0]
                    if abs(h.x - cx) <= r and abs(h.y - cy) <= r:
                        s.alive = False

    def _step_snakes(self, tick: int, wall_col: bool) -> None:
        new_heads: Dict[int, Point] = {}
        for s in self.snakes:
            if not s.alive: continue
            s.ticks_survived += 1
            if s.mode_until_tick > 0 and tick >= s.mode_until_tick:
                s.mode = SnakeMode.NORMAL
            cand = Point(s.body[0].x + s.direction.dx, s.body[0].y + s.direction.dy)
            if wall_col and not in_bounds(cand, self.n):
                s.alive = False
                continue
            nxt = cand if wall_col else wrap(cand, self.n)
            new_heads[s.snake_id] = nxt

        # Choques con bombas
        for s in self.snakes:
            if not s.alive: continue
            nxt = new_heads[s.snake_id]
            if nxt in self.bombs:
                if s.mode == SnakeMode.GOLDEN:
                    del self.bombs[nxt]
                    s.score += 2
                else:
                    s.alive = False

        # Choques cabeza-cabeza y cuerpos
        for s in self.snakes:
            if not s.alive: continue
            h = new_heads[s.snake_id]
            # Con cuerpos ajenos
            for other in self.snakes:
                if other.snake_id == s.snake_id or not other.alive: continue
                if h in other.body:
                    s.alive = False
                    other.kills += 1
                elif other.snake_id in new_heads and h == new_heads[other.snake_id]:
                    # Choque frontal: gana la de mayor tamaño o mueren ambas
                    if len(s.body) > len(other.body):
                        other.alive = False; s.kills += 1
                    elif len(other.body) > len(s.body):
                        s.alive = False; other.kills += 1
                    else:
                        s.alive = False; other.alive = False

        # Mover vivos
        for s in self.snakes:
            if not s.alive: continue
            nxt = new_heads[s.snake_id]
            s.body.appendleft(nxt)
            if nxt in self.foods:
                s.score += 1
                s.grow_pending += 1
                self.foods.remove(nxt)
            if s.grow_pending > 0:
                s.grow_pending -= 1
            else:
                s.body.pop()

        self._spawn_foods(max(4, (self.n * self.n) // 100))

    def _update_voronoi(self) -> None:
        alive = [s for s in self.snakes if s.alive]
        if not alive: return
        sample_count = min(36, self.n * 2)
        for _ in range(sample_count):
            p = Point(self.rng.randint(0, self.n - 1), self.rng.randint(0, self.n - 1))
            closest = min(alive, key=lambda s: dist_calc(s.body[0], p, self.wall_collision, self.n))
            closest.voronoi_accum += 1.0

# ============================================================
# Proceso Worker Paralelo para una Arena Específica
# ============================================================

def worker_arena(config: ArenaConfig, duration_sec: float, out_dir: str, seed: int) -> None:
    rng = random.Random(seed)
    weights: Dict[FactionId, JineteWeights] = {fac: JineteWeights(**asdict(DEFAULT_WEIGHTS[fac])) for fac in DEFAULT_WEIGHTS}

    os.makedirs(out_dir, exist_ok=True)
    chk_file = os.path.join(out_dir, f"weights_{config.arena_id}.json")
    csv_file = os.path.join(out_dir, f"stats_{config.arena_id}.csv")

    match_count = 0
    wins: Dict[str, int] = {}

    # 1. Cargar Checkpoint previo para Aprendizaje Continuo (Fine-Tuning)
    if os.path.exists(chk_file):
        try:
            with open(chk_file, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            if "weights" in old_data:
                for fac_str, w_dict in old_data["weights"].items():
                    try:
                        fac_enum = FactionId(fac_str)
                        weights[fac_enum] = JineteWeights(**w_dict)
                    except Exception:
                        pass
            match_count = old_data.get("matches", 0)
            wins = old_data.get("wins", {})
            print(f"[{config.name}] 🔄 Reanudando entrenamiento desde checkpoint previo: {match_count} partidas, victorias previas: {wins}")
        except Exception as e:
            print(f"[{config.name}] Aviso al leer checkpoint: {e}")

    # 2. Inicializar CSV si no existe
    csv_exists = os.path.exists(csv_file) and os.path.getsize(csv_file) > 0
    if not csv_exists:
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write("match_id,duration_ticks,winner,red_score,green_score,blue_score,purple_score,gold_score\n")

    start_time = time.time()
    last_chk_time = start_time
    print(f"[{config.name}] Iniciando simulación paralela...")

    while time.time() - start_time < duration_sec:
        match_count += 1
        # Pequeña perturbación evolutiva (Evolutionary Strategies)
        mutated_weights = {}
        for fac, w in weights.items():
            w_dict = asdict(w)
            k = rng.choice(list(w_dict.keys()))
            w_dict[k] = max(0.1, w_dict[k] + rng.gauss(0, 0.05))
            mutated_weights[fac] = JineteWeights(**w_dict)

        try:
            match = ArenaMatch(config, mutated_weights, rng)
            res = match.run_match()
        except Exception as err:
            print(f"[{config.name}] Error no fatal en partida {match_count} (recuperado): {err}")
            continue

        w_fac = res["winner_faction"]
        wins[w_fac] = wins.get(w_fac, 0) + 1

        # Si el ganador usó los pesos mutados con buen desempeño, adoptar mutación
        if w_fac in [f.value for f in mutated_weights.keys()]:
            fac_enum = FactionId(w_fac)
            weights[fac_enum] = mutated_weights[fac_enum]

        # Guardar en CSV inmediatamente
        st = res["stats"]
        scores = [str(st.get(fac.value, {}).get("score", 0)) for fac in [FactionId.RED, FactionId.GREEN, FactionId.BLUE, FactionId.PURPLE, FactionId.GOLD]]
        try:
            with open(csv_file, "a", encoding="utf-8") as f:
                f.write(f"{match_count},{res['ticks']},{w_fac},{','.join(scores)}\n")
        except Exception:
            pass

        # Guardar Checkpoint cada 10 partidas o cada 15 segundos (a prueba de cortes)
        now_t = time.time()
        if match_count % 10 == 0 or (now_t - last_chk_time > 15.0):
            last_chk_time = now_t
            data = {
                "arena_id": config.arena_id,
                "matches": match_count,
                "elapsed_sec": round(now_t - start_time, 1),
                "wins": wins,
                "weights": {fac.value: asdict(w) for fac, w in weights.items()}
            }
            try:
                with open(chk_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass

    # Checkpoint final
    data = {
        "arena_id": config.arena_id,
        "matches": match_count,
        "elapsed_sec": round(time.time() - start_time, 1),
        "wins": wins,
        "weights": {fac.value: asdict(w) for fac, w in weights.items()}
    }
    with open(chk_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[{config.name}] COMPLETADO: {match_count} partidas simuladas en {round(time.time() - start_time, 1)}s. Victorias: {wins}")


# ============================================================
# Orquestador Principal Multi-Core
# ============================================================

def run_multi_arena_sim(duration_sec: float = 30.0, out_dir: str = "training_results") -> None:
    print("=" * 70)
    print("  COLESEO SAPERAAI — SIMULACIÓN MASIVA EN PARALELO (6 ARENAS)")
    print("=" * 70)
    print(f"CPU Cores detectados : {mp.cpu_count()}")
    print(f"Arenas simultáneas   : {len(ARENA_CONFIGS)}")
    print(f"Duración programada  : {duration_sec} segundos ({round(duration_sec / 3600, 2)} horas)")
    print(f"Directorio salida    : {os.path.abspath(out_dir)}")
    print("-" * 70)

    processes = []
    base_seed = int(time.time())
    for i, cfg in enumerate(ARENA_CONFIGS):
        p = mp.Process(target=worker_arena, args=(cfg, duration_sec, out_dir, base_seed + i * 100))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()

    print("=" * 70)
    print("  SIMULACIÓN COMPLETADA CON ÉXITO EN TODAS LAS ARENAS")
    print("=" * 70)

if __name__ == "__main__":
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    run_multi_arena_sim(duration_sec=dur)
