# ============================================================
# horse.py — El Caballo: Verificador Sagrado de Supervivencia
# ============================================================
# Implementación estricta de las normas de Bases.md:
# 1. Tolerancia cero al suicidio involuntario.
# 2. Verificación BFS de escape hacia la propia cola liberada.
# 3. Detección matemática de bucles y penalización anti-ciclos.
# 4. Consciencia temporal de modos y penalización de huecos vacíos.
# ============================================================

from collections import deque
from typing import List, Set, Deque
from models import (
    Point, Direction, DIRS, SnakeMode, ColosseumSnake, ColosseumState,
    in_bounds, wrap
)

class HorseVerifier:
    """
    El Caballo es el sustrato fisiológico de la serpiente.
    Filtra los movimientos físicamente posibles y descarta
    cualquier acción que viole la supervivencia sagrada.
    """

    @staticmethod
    def get_safe_moves(snake: ColosseumSnake, state: ColosseumState, now_ms: int, wall_col: bool, n: int) -> List[Direction]:
        head = snake.body[0]
        tail = snake.body[-1]
        golden = (snake.mode == SnakeMode.GOLDEN and snake.mode_until_ms > now_ms)

        # 1. Obstáculos mortales del entorno
        blocked: Set[Point] = set()
        if not golden:
            blocked |= set(state.bombs.keys())
            if state.nuclear and state.nuclear.affected_cells:
                blocked |= {p for p, (f, _) in state.nuclear.affected_cells.items() if f in ("HOT", "ASH")}

        # 2. Cuerpos de rivales
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

            # No entrar en bombas o fuego
            if nxt in blocked: continue

            eats = any(nxt == f.pos for f in state.foods) or (golden and nxt in state.bombs)
            if nxt in own_set:
                # Solo puede avanzar a la cola si no come y la cola se desplaza en este tick
                if not eats and snake.grow_pending == 0 and nxt == tail:
                    pass
                else:
                    continue

            # 3. Simular cuerpo proyectado en el siguiente tick
            proj = deque(own_body)
            proj.appendleft(nxt)
            if not eats and snake.grow_pending == 0:
                proj.pop()

            # MANDATO SAGRADO DE BASES.MD: VERIFICACIÓN BFS DE ESCAPE A LA COLA
            if not HorseVerifier.has_escape_to_tail(proj, blocked, wall_col, n):
                continue

            safe.append(d)

        # Alarma Sagrada del Caballo: Certificación estricta de Muerte Inevitable en t+1 (CERO falsas muertes)
        snake.imminent_death = HorseVerifier.is_next_tick_death_guaranteed(snake, state, wall_col, n)
        return safe

    @staticmethod
    def is_next_tick_death_guaranteed(snake: ColosseumSnake, state: ColosseumState, wall_col: bool, n: int) -> bool:
        """
        Verificación estricta de muerte en el siguiente tick (sin falsos positivos):
        Solo es True si TODAS las 4 direcciones conducen a colisión fatal inmediata
        contra pared, bomba, fuego nuclear o cuerpos inmóviles.
        Si alguna dirección permite avanzar a una casilla libre o a una cola que desocupa,
        la muerte NO está garantizada.
        """
        head = snake.body[0]
        golden = (snake.mode == SnakeMode.GOLDEN and snake.mode_until_ms > 0)

        for d in DIRS:
            cand = Point(head.x + d.dx, head.y + d.dy)
            if wall_col and not in_bounds(cand, n):
                continue

            nxt = cand if wall_col else wrap(cand, n)

            if not golden:
                if nxt in state.bombs: continue
                if state.nuclear and state.nuclear.affected_cells:
                    fase, _ = state.nuclear.affected_cells.get(nxt, ("", 0))
                    if fase in ("HOT", "ASH"): continue

            own_pts = list(snake.body)
            if nxt in set(own_pts[:-1]): continue
            if nxt == own_pts[-1] and snake.grow_pending > 0: continue

            collides_rival = False
            for other in state.snakes:
                if not other.alive or other.snake_id == snake.snake_id: continue
                other_pts = list(other.body)
                if nxt in set(other_pts[:-1]):
                    collides_rival = True; break
                if nxt == other_pts[-1] and other.grow_pending > 0:
                    collides_rival = True; break
            if collides_rival: continue

            # Hay al menos una casilla transitable inmediata: ¡No hay muerte segura en este tick!
            return False

        return True

    @staticmethod
    def has_escape_to_tail(proj_snake: Deque[Point], blocked_env: Set[Point], wall_col: bool, n: int) -> bool:
        head = proj_snake[0]
        tail = proj_snake[-1]

        snake_block = set(proj_snake)
        if tail in snake_block:
            snake_block.remove(tail)

        obstacles = snake_block | blocked_env
        q = deque([head])
        visited = {head}

        while q:
            cur = q.popleft()
            if cur == tail:
                return True

            for d in DIRS:
                cand = Point(cur.x + d.dx, cur.y + d.dy)
                if wall_col and not in_bounds(cand, n): continue
                nxt = cand if wall_col else wrap(cand, n)

                if nxt not in visited and nxt not in obstacles:
                    visited.add(nxt)
                    q.append(nxt)

        return False

    @staticmethod
    def detect_loop(snake: ColosseumSnake) -> bool:
        """
        Analiza el historial de la cabeza (head_history).
        Si un patrón de longitud L (entre 4 y 22 pasos) se repite 3 veces idénticas,
        certifica que el bot cayó en un bucle cerrado.
        """
        hist = list(snake.head_history)
        if len(hist) < 70:
            return False

        for L in range(4, 23):
            if len(hist) < 3 * L: continue
            a = hist[-L:]
            b = hist[-2 * L:-L]
            c = hist[-3 * L:-2 * L]
            if a == b == c:
                return True

        return False

    @staticmethod
    def loop_penalty(snake: ColosseumSnake, nxt: Point, state: ColosseumState) -> float:
        """
        Penalización aplicada cuando cycle_penalty_until está activo,
        desincentivando fuertemente transitar casillas recientes para romper el bucle.
        """
        if state.tick < snake.cycle_penalty_until:
            occ = sum(1 for p in list(snake.head_history)[-80:] if p == nxt)
            return -1.1 * min(4, occ)
        return 0.0

    @staticmethod
    def small_empty_components_penalty(nxt: Point, snake: ColosseumSnake, state: ColosseumState,
                                       wall_col: bool, now_ms: int, n: int) -> float:
        """
        Penaliza severamente dejar cavidades vacías de tamaño pequeño (1 a 3 celdas).
        En juego tardío (menos de 25 celdas libres), la penalización es implacable
        incluso si se come una manzana, previniendo islas de huecos solitarios.
        """
        golden = (snake.mode == SnakeMode.GOLDEN and snake.mode_until_ms > now_ms)
        eats = any(nxt == f.pos for f in state.foods) or (golden and nxt in state.bombs)

        free_cells = (n * n) - len(snake.body) - len(state.bombs)
        is_late_game = (free_cells < 25)

        # En juego temprano se perdona si come; en juego tardío NO para no aislar huecos muertos
        if eats and not is_late_game:
            return 0.0

        proj = deque(snake.body)
        proj.appendleft(nxt)
        if not eats and snake.grow_pending == 0:
            proj.pop()

        tail = proj[-1]
        occupied = set(proj) | {f.pos for f in state.foods}
        if not golden:
            occupied |= set(state.bombs.keys())

        visited: Set[Point] = set()
        penalty = 0.0

        for d in DIRS:
            cand = Point(nxt.x + d.dx, nxt.y + d.dy)
            if wall_col and not in_bounds(cand, n): continue
            start_p = cand if wall_col else wrap(cand, n)

            if start_p in occupied or start_p in visited:
                continue

            # BFS de componente conexo pequeño
            comp_size = 0
            has_tail = False
            q = deque([start_p])
            comp_visited = {start_p}

            while q and comp_size < 5:
                cur = q.popleft()
                comp_size += 1
                if cur == tail:
                    has_tail = True

                for d2 in DIRS:
                    c2 = Point(cur.x + d2.dx, cur.y + d2.dy)
                    if wall_col and not in_bounds(c2, n): continue
                    n2 = c2 if wall_col else wrap(c2, n)
                    if n2 not in occupied and n2 not in comp_visited:
                        comp_visited.add(n2)
                        q.append(n2)

            visited |= comp_visited
            # Si el componente pequeño no contiene la cola que se libera, es un hueco muerto aislado
            if not has_tail:
                if comp_size in (1, 2):
                    penalty -= 30.0 if is_late_game else 10.0
                elif comp_size == 3 and is_late_game:
                    penalty -= 20.0

        return penalty

    @staticmethod
    def best_delay_death(snake: ColosseumSnake, state: ColosseumState, wall_col: bool, n: int) -> Direction:
        """
        Si la serpiente es acorralada por factores externos (bombas o rivales),
        el caballo elige la dirección que maximice el espacio alcanzable para retrasar la muerte.
        """
        head = snake.body[0]
        occupied = set()
        for s in state.snakes:
            if s.alive: occupied |= set(s.body)
        occupied |= set(state.bombs.keys())

        best_d = snake.direction
        max_reach = -1

        for d in DIRS:
            cand = Point(head.x + d.dx, head.y + d.dy)
            if wall_col and not in_bounds(cand, n): continue
            nxt = cand if wall_col else wrap(cand, n)
            if nxt in occupied: continue

            # Medir alcance por BFS
            q = deque([nxt])
            seen = {nxt}
            while q and len(seen) < 40:
                cur = q.popleft()
                for d2 in DIRS:
                    c2 = Point(cur.x + d2.dx, cur.y + d2.dy)
                    if wall_col and not in_bounds(c2, n): continue
                    n2 = c2 if wall_col else wrap(c2, n)
                    if n2 not in occupied and n2 not in seen:
                        seen.add(n2)
                        q.append(n2)

            if len(seen) > max_reach:
                max_reach = len(seen)
                best_d = d

        return best_d
