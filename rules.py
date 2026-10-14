# ============================================================
# rules.py — Reglas del Juego, Física, Colisiones y Comida
# ============================================================

import random
import math
from collections import deque
from typing import Optional, Tuple, Dict, List
from config import MARGIN_PX, HUD_HEIGHT, INITIAL_SNAKE_LENGTH
from models import (
    Point, Direction, Food, SnakeMode, ColosseumSnake, ColosseumState,
    VisualParticle, in_bounds, wrap, GameMode,
    FACTION_OFFENSIVE_PHRASES, FACTION_KILL_PHRASES,
    FOOD_RELIEF_PHRASES, HUNGER_TIER1_PHRASES, HUNGER_TIER2_PHRASES,
    PRE_DEATH_CRIES
)

class ColosseumRules:
    def __init__(self, rng: random.Random):
        self.rng = rng

    def _activate_kill_cam(self, state: ColosseumState, victim: ColosseumSnake, focus_pt: Point, now_ms: int) -> None:
        state.slow_mo_until_ms = now_ms + 1800
        state.slow_mo_factor = 0.28 # Cámara lenta (~28% de la velocidad base)
        state.slow_mo_cooldown_until_ms = now_ms + 5000
        state.kill_cam_target_id = victim.snake_id
        state.kill_cam_focus_pt = focus_pt
        state.kill_cam_victim_name = victim.faction.name
        state.kill_cam_anticipation_until_ms = now_ms + 480 # 480ms de anticipación y enfoque PREVIO a la muerte
        victim.speech_text = self.rng.choice(PRE_DEATH_CRIES)
        victim.speech_until_ms = now_ms + 2500

    def check_impending_killcam(self, state: ColosseumState, now_ms: int) -> bool:
        """
        Verifica ANTES de ejecutar el siguiente movimiento de física si una serpiente
        está acorralada (alarma del caballo) o en curso de colisión letal inevitable.
        Si se detecta muerte inminente, activa la Kill Cam con anticipación (slow motion
        y enfoque mientras la víctima sigue viva en pantalla).
        Retorna True si se activó una nueva anticipación (para pausar la física y renderizar a 60 FPS).
        """
        if len(state.snakes) <= 1 or state.game_mode not in (GameMode.BATTLE_ROYALE, GameMode.DUEL_1V1):
            return False
        if state.paused or state.countdown_active or state.round_winner:
            return False
        if state.slow_mo_until_ms > now_ms or now_ms < state.slow_mo_cooldown_until_ms:
            return False

        alive_snakes = [s for s in state.snakes if s.alive]
        if len(alive_snakes) <= 1:
            return False

        # 1. Alarma del Caballo: Serpiente acorralada sin movimientos seguros
        for s in alive_snakes:
            if getattr(s, "imminent_death", False):
                self._activate_kill_cam(state, s, s.body[0], now_ms)
                return True

        # 2. Proyección de movimientos inmediatos para detectar colisión fatal en t+1
        projections: Dict[int, Optional[Point]] = {}
        for s in alive_snakes:
            cand = Point(s.body[0].x + s.direction.dx, s.body[0].y + s.direction.dy)
            if state.wall_collision:
                projections[s.snake_id] = cand if in_bounds(cand, state.grid_size) else None
            else:
                projections[s.snake_id] = wrap(cand, state.grid_size)

        # A. Choque contra pared
        for s in alive_snakes:
            if projections.get(s.snake_id) is None:
                self._activate_kill_cam(state, s, s.body[0], now_ms)
                return True

        # B. Choque contra bomba
        for s in alive_snakes:
            nxt = projections.get(s.snake_id)
            if nxt and nxt in state.bombs and s.mode != SnakeMode.GOLDEN:
                self._activate_kill_cam(state, s, nxt, now_ms)
                return True

        # C. Choque contra fuego nuclear
        for s in alive_snakes:
            nxt = projections.get(s.snake_id)
            if nxt and state.nuclear and nxt in state.nuclear.affected_cells:
                fase, _ = state.nuclear.affected_cells[nxt]
                if fase in ("HOT", "ASH"):
                    self._activate_kill_cam(state, s, nxt, now_ms)
                    return True

        # D. Choque frontal de cabezas (p1 == p2)
        active = [s for s in alive_snakes if projections.get(s.snake_id) is not None]
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                s1, s2 = active[i], active[j]
                p1, p2 = projections[s1.snake_id], projections[s2.snake_id]
                if p1 == p2:
                    if s1.mode == SnakeMode.GOLDEN and s2.mode != SnakeMode.GOLDEN: victim = s2
                    elif s2.mode == SnakeMode.GOLDEN and s1.mode != SnakeMode.GOLDEN: victim = s1
                    elif len(s1.body) > len(s2.body): victim = s2
                    elif len(s2.body) > len(s1.body): victim = s1
                    elif s1.score > s2.score: victim = s2
                    else: victim = s1
                    self._activate_kill_cam(state, victim, p1, now_ms)
                    return True

        # E. Choque contra cuerpos
        for s in alive_snakes:
            nxt = projections.get(s.snake_id)
            if not nxt: continue
            eats = any(nxt == f.pos for f in state.foods)
            for other in alive_snakes:
                body_pts = list(other.body)
                tail_pt = body_pts[-1]
                if other.snake_id == s.snake_id:
                    if nxt in set(body_pts[:-1]) or (nxt == tail_pt and (eats or s.grow_pending > 0)):
                        self._activate_kill_cam(state, s, nxt, now_ms)
                        return True
                else:
                    other_eats = any(projections.get(other.snake_id) == f.pos for f in state.foods)
                    if nxt in set(body_pts[:-1]) or (nxt == tail_pt and (other_eats or other.grow_pending > 0)):
                        self._activate_kill_cam(state, s, nxt, now_ms)
                        return True

        return False

    def step(self, state: ColosseumState, now_ms: int) -> None:
        if state.paused: return
        if state.countdown_active:
            if state.countdown_start_ms > 0 and now_ms >= state.countdown_start_ms + 3000:
                state.countdown_active = False
            else:
                return

        # 1. Expiración del modo Trascendente (Wrap)
        if not state.wall_collision and state.wrap_mode_until_ms > 0:
            if now_ms >= state.wrap_mode_until_ms:
                state.wall_collision = True
                state.wrap_mode_until_ms = 0

        # Actualización de Cámara Lenta / Kill Cam
        if state.slow_mo_until_ms > 0 and now_ms >= state.slow_mo_until_ms:
            state.slow_mo_until_ms = 0
            state.slow_mo_factor = 1.0
            state.kill_cam_target_id = None
            state.kill_cam_focus_pt = None
            state.kill_cam_victim_name = None
            state.kill_cam_anticipation_until_ms = 0

        # 2. Verificación de fin de ronda
        alive_snakes = [s for s in state.snakes if s.alive]
        total_snakes = len(state.snakes)

        # Alarma del Caballo: Detección de Muerte Inminente para Slow Motion y Foco Kill Cam
        if total_snakes > 1 and state.game_mode in (GameMode.BATTLE_ROYALE, GameMode.DUEL_1V1):
            if state.slow_mo_until_ms == 0 and now_ms >= state.slow_mo_cooldown_until_ms:
                for s in alive_snakes:
                    if getattr(s, "imminent_death", False):
                        self._activate_kill_cam(state, s, s.body[0], now_ms)
                        break

        if total_snakes > 1 and len(alive_snakes) <= 1 and state.round_winner is None:
            if len(alive_snakes) == 1:
                winner = alive_snakes[0]
                winner.wins += 1
                state.round_winner = f"¡{winner.faction.name.upper()} GANA!"
            else:
                # Desempate técnico por Puntuación y Longitud para eliminar empates al 90%
                sorted_by_merit = sorted(state.snakes, key=lambda s: (s.score, len(s.body)), reverse=True)
                top_1 = sorted_by_merit[0]
                top_2 = sorted_by_merit[1] if len(sorted_by_merit) > 1 else None

                if top_2 is None or (top_1.score, len(top_1.body)) > (top_2.score, len(top_2.body)):
                    top_1.wins += 1
                    state.round_winner = f"¡VICTORIA POR PUNTOS: {top_1.faction.name.upper()}!"
                else:
                    state.round_winner = "¡EMPATE TOTAL!"
            state.round_reset_ms = now_ms + 3500

        if total_snakes == 1 and not alive_snakes and state.round_winner is None:
            state.round_winner = "FIN DE PARTIDA"
            state.round_reset_ms = now_ms + 3000

        if state.round_winner and now_ms >= state.round_reset_ms:
            self.reset_round(state, now_ms)
            return

        # 3. Expiración de bombas normales
        if state.bombs:
            expired = [p for p, exp in state.bombs.items() if exp <= now_ms]
            for p in expired:
                state.bombs.pop(p, None)
                self._spawn_explosion(state, p, count=16)

        # 4. Actualización del Ataque Nuclear
        self._update_nuclear(state, now_ms)

        # 5. Proyectar pasos según dirección
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

        # 6. Impacto contra paredes
        for s in state.snakes:
            if not s.alive: continue
            if projections[s.snake_id] is None:
                s.alive = False
                s.speech_text = self.rng.choice(PRE_DEATH_CRIES)
                s.speech_until_ms = now_ms + 2200
                self._spawn_death_debris(state, s)
                if state.slow_mo_until_ms <= now_ms:
                    state.slow_mo_until_ms = now_ms + 1200
                    state.slow_mo_factor = 0.28
                    state.kill_cam_target_id = s.snake_id
                    state.kill_cam_focus_pt = s.body[0]
                    state.kill_cam_victim_name = s.faction.name

        # 7. Impacto con Bombas y Zona Cero Nuclear
        for s in state.snakes:
            if not s.alive: continue
            nxt = projections[s.snake_id]
            if nxt is None: continue

            # Bomba
            if nxt in state.bombs:
                if s.mode == SnakeMode.GOLDEN:
                    state.bombs.pop(nxt, None)
                    s.score += 2
                    s.grow_pending += 2
                    self._spawn_explosion(state, nxt, count=10, col=(255, 215, 60))
                else:
                    s.alive = False
                    state.bombs.pop(nxt, None)
                    s.speech_text = self.rng.choice(PRE_DEATH_CRIES)
                    s.speech_until_ms = now_ms + 2200
                    self._spawn_explosion(state, nxt, count=24, col=(255, 70, 30))
                    self._spawn_death_debris(state, s)
                    if state.slow_mo_until_ms <= now_ms:
                        state.slow_mo_until_ms = now_ms + 1200
                        state.slow_mo_factor = 0.28
                        state.kill_cam_target_id = s.snake_id
                        state.kill_cam_focus_pt = nxt
                        state.kill_cam_victim_name = s.faction.name
                    continue

            # Nuclear
            if state.nuclear and nxt in state.nuclear.affected_cells:
                fase, _ = state.nuclear.affected_cells[nxt]
                if fase in ("HOT", "ASH"):
                    s.alive = False
                    s.speech_text = self.rng.choice(PRE_DEATH_CRIES)
                    s.speech_until_ms = now_ms + 2200
                    self._spawn_death_debris(state, s)
                    if state.slow_mo_until_ms <= now_ms:
                        state.slow_mo_until_ms = now_ms + 1200
                        state.slow_mo_factor = 0.28
                        state.kill_cam_target_id = s.snake_id
                        state.kill_cam_focus_pt = nxt
                        state.kill_cam_victim_name = s.faction.name
                    continue

        # 8. Choque frontal de cabezas (Resolución por Modo, Longitud y Puntuación)
        active_snakes = [s for s in state.snakes if s.alive and projections[s.snake_id] is not None]
        for i in range(len(active_snakes)):
            for j in range(i + 1, len(active_snakes)):
                s1, s2 = active_snakes[i], active_snakes[j]
                if not s1.alive or not s2.alive: continue
                p1, p2 = projections[s1.snake_id], projections[s2.snake_id]
                if p1 == p2:
                    # Choque frontal: evaluar superioridad
                    if s1.mode == SnakeMode.GOLDEN and s2.mode != SnakeMode.GOLDEN:
                        s2.alive = False
                        s1.score += max(3, s2.score // 2)
                        s1.speech_text = self.rng.choice(FACTION_KILL_PHRASES.get(s1.faction.faction_id, ["¡Victoria! 🔥"]))
                        s1.speech_until_ms = now_ms + 3200
                        s2.speech_text = self.rng.choice(PRE_DEATH_CRIES)
                        s2.speech_until_ms = now_ms + 2200
                        # Kill Camera en el choque frontal letal
                        state.slow_mo_until_ms = now_ms + 1200
                        state.slow_mo_factor = 0.28
                        state.kill_cam_target_id = s2.snake_id
                        state.kill_cam_focus_pt = p1
                        state.kill_cam_victim_name = s2.faction.name
                        self._spawn_death_debris(state, s2)
                        self._spawn_bite_sparks(state, p1, s1.faction.head_color)
                    elif s2.mode == SnakeMode.GOLDEN and s1.mode != SnakeMode.GOLDEN:
                        s1.alive = False
                        s2.score += max(3, s1.score // 2)
                        s2.speech_text = self.rng.choice(FACTION_KILL_PHRASES.get(s2.faction.faction_id, ["¡Victoria! 🔥"]))
                        s2.speech_until_ms = now_ms + 3200
                        s1.speech_text = self.rng.choice(PRE_DEATH_CRIES)
                        s1.speech_until_ms = now_ms + 2200
                        state.slow_mo_until_ms = now_ms + 1200
                        state.slow_mo_factor = 0.28
                        state.kill_cam_target_id = s1.snake_id
                        state.kill_cam_focus_pt = p2
                        state.kill_cam_victim_name = s1.faction.name
                        self._spawn_death_debris(state, s1)
                        self._spawn_bite_sparks(state, p2, s2.faction.head_color)
                    elif len(s1.body) > len(s2.body):
                        # La serpiente más grande aplasta a la más pequeña
                        s2.alive = False
                        s1.score += max(2, s2.score // 2)
                        s1.grow_pending += 1
                        s1.speech_text = self.rng.choice(FACTION_KILL_PHRASES.get(s1.faction.faction_id, ["¡Aplaste total! 💥"]))
                        s1.speech_until_ms = now_ms + 3200
                        s2.speech_text = self.rng.choice(PRE_DEATH_CRIES)
                        s2.speech_until_ms = now_ms + 2200
                        state.slow_mo_until_ms = now_ms + 1200
                        state.slow_mo_factor = 0.28
                        state.kill_cam_target_id = s2.snake_id
                        state.kill_cam_focus_pt = p1
                        state.kill_cam_victim_name = s2.faction.name
                        self._spawn_death_debris(state, s2)
                        self._spawn_bite_sparks(state, p1, s1.faction.head_color)
                    elif len(s2.body) > len(s1.body):
                        # s2 es más grande y aplasta a s1
                        s1.alive = False
                        s2.score += max(2, s1.score // 2)
                        s2.grow_pending += 1
                        s2.speech_text = self.rng.choice(FACTION_KILL_PHRASES.get(s2.faction.faction_id, ["¡Aplaste total! 💥"]))
                        s2.speech_until_ms = now_ms + 3200
                        s1.speech_text = self.rng.choice(PRE_DEATH_CRIES)
                        s1.speech_until_ms = now_ms + 2200
                        state.slow_mo_until_ms = now_ms + 1200
                        state.slow_mo_factor = 0.28
                        state.kill_cam_target_id = s1.snake_id
                        state.kill_cam_focus_pt = p2
                        state.kill_cam_victim_name = s1.faction.name
                        self._spawn_death_debris(state, s1)
                        self._spawn_bite_sparks(state, p2, s2.faction.head_color)
                    elif s1.score > s2.score:
                        # Mismo tamaño: desempate por puntos
                        s2.alive = False
                        s1.score += max(1, s2.score // 2)
                        s1.speech_text = self.rng.choice(FACTION_KILL_PHRASES.get(s1.faction.faction_id, ["¡Superioridad táctica! 👑"]))
                        s1.speech_until_ms = now_ms + 3200
                        s2.speech_text = self.rng.choice(PRE_DEATH_CRIES)
                        s2.speech_until_ms = now_ms + 2200
                        state.slow_mo_until_ms = now_ms + 1200
                        state.slow_mo_factor = 0.28
                        state.kill_cam_target_id = s2.snake_id
                        state.kill_cam_focus_pt = p1
                        state.kill_cam_victim_name = s2.faction.name
                        self._spawn_death_debris(state, s2)
                        self._spawn_bite_sparks(state, p1, s1.faction.head_color)
                    elif s2.score > s1.score:
                        s1.alive = False
                        s2.score += max(1, s1.score // 2)
                        s2.speech_text = self.rng.choice(FACTION_KILL_PHRASES.get(s2.faction.faction_id, ["¡Superioridad táctica! 👑"]))
                        s2.speech_until_ms = now_ms + 3200
                        s1.speech_text = self.rng.choice(PRE_DEATH_CRIES)
                        s1.speech_until_ms = now_ms + 2200
                        state.slow_mo_until_ms = now_ms + 1200
                        state.slow_mo_factor = 0.28
                        state.kill_cam_target_id = s1.snake_id
                        state.kill_cam_focus_pt = p2
                        state.kill_cam_victim_name = s1.faction.name
                        self._spawn_death_debris(state, s1)
                        self._spawn_bite_sparks(state, p2, s2.faction.head_color)
                    else:
                        # Estricto empate absoluto: ambas perecen
                        s1.alive = False
                        s2.alive = False
                        state.slow_mo_until_ms = now_ms + 1200
                        state.slow_mo_factor = 0.28
                        state.kill_cam_target_id = s1.snake_id
                        state.kill_cam_focus_pt = p1
                        state.kill_cam_victim_name = "AMBOS"
                        self._spawn_death_debris(state, s1)
                        self._spawn_death_debris(state, s2)

        # 9. Choque con cuerpos ajenos o propio
        for s in state.snakes:
            if not s.alive: continue
            nxt = projections[s.snake_id]
            if nxt is None: continue

            eats_something = any(nxt == f.pos for f in state.foods)
            hit = False
            killer = None

            for other in state.snakes:
                if not other.alive: continue
                body_pts = list(other.body)
                tail_pt = body_pts[-1]

                if other.snake_id == s.snake_id:
                    # Propio cuerpo
                    if nxt in set(body_pts[:-1]):
                        hit = True; break
                    elif nxt == tail_pt:
                        if eats_something or s.grow_pending > 0:
                            hit = True; break
                else:
                    # Cuerpo rival
                    other_eats = any(projections.get(other.snake_id) == f.pos for f in state.foods)
                    if nxt in set(body_pts[:-1]):
                        hit = True; killer = other; break
                    elif nxt == tail_pt:
                        if other_eats or other.grow_pending > 0:
                            hit = True; killer = other; break

            if hit:
                s.alive = False
                s.speech_text = self.rng.choice(PRE_DEATH_CRIES)
                s.speech_until_ms = now_ms + 2200
                self._spawn_death_debris(state, s)

                # Kill Camera al morir en impacto contra cuerpo rival
                state.slow_mo_until_ms = now_ms + 1200
                state.slow_mo_factor = 0.28
                state.kill_cam_target_id = s.snake_id
                state.kill_cam_focus_pt = nxt
                state.kill_cam_victim_name = s.faction.name

                if killer and killer.alive and killer.snake_id != s.snake_id:
                    killer.speech_text = self.rng.choice(FACTION_KILL_PHRASES.get(killer.faction.faction_id, ["¡Uno menos!"]))
                    killer.speech_until_ms = now_ms + 3200

        # 10. Desplazamiento y Alimentación
        for s in state.snakes:
            if not s.alive: continue
            nxt = projections[s.snake_id]
            if nxt is None: continue

            food = next((f for f in state.foods if f.pos == nxt), None)
            if food:
                state.foods.remove(food)
                mult = 2 if s.mode in (SnakeMode.EXTASIS, SnakeMode.GOLDEN) else 1
                s.score += food.value * mult
                s.grow_pending += food.value * mult
                was_starving = (s.hunger_ticks >= 200)
                had_complaint = (s.speech_text is not None and any(w in s.speech_text.lower() for w in ("hambre", "ayuda", "estómago", "socorro", "piedad", "espagueti")))
                s.hunger_ticks = 0 # Reiniciar contador de hambre
                self._spawn_bite_sparks(state, nxt, s.faction.head_color)

                # Si es Manzana Dorada, respawnea inmediatamente otra
                if food.golden:
                    new_p = self.random_free_cell(state)
                    if new_p: state.foods.append(Food(pos=new_p, value=1, golden=True))
                # Si es Manzana Normal (roja-verde), NO respawnea (consumible)

                # Si tenía hambre real o letrero quejándose, el letrero anterior DESAPARECE
                # e inserta una frase cómica de alivio instantáneo
                if was_starving or had_complaint:
                    s.speech_text = self.rng.choice(FOOD_RELIEF_PHRASES)
                    s.speech_until_ms = now_ms + 2800
                elif s.speech_text and now_ms < s.speech_until_ms and "hambre" in s.speech_text.lower():
                    s.speech_text = None
                    s.speech_until_ms = 0
            else:
                s.hunger_ticks += 1

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

            # 11. Frases Cómicas de Hambre Escalonadas (exclusivamente en verdadera inanición >= 200 ticks)
            if s.alive and now_ms > s.speech_until_ms and (state.tick - s.last_speech_tick >= 80):
                if s.hunger_ticks >= 200:
                    s.speech_text = self.rng.choice(HUNGER_TIER2_PHRASES)
                    s.speech_until_ms = now_ms + 3400
                    s.last_speech_tick = state.tick

        state.tick += 1

    def reset_round(self, state: ColosseumState, now_ms: int) -> None:
        state.round_number += 1
        state.round_winner = None
        state.round_reset_ms = 0
        state.tick = 0
        state.foods = []
        state.bombs = {}
        state.nuclear = None
        state.particles.clear()
        state.slow_mo_until_ms = 0
        state.slow_mo_factor = 1.0
        state.kill_cam_target_id = None
        state.kill_cam_focus_pt = None
        state.director_banner_text = None
        state.director_stage = None
        state.countdown_active = True
        state.countdown_start_ms = now_ms

        # Coordenadas iniciales seguras a distancia 4 de los bordes (evita desbordes de longitud 5)
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
            s.cycle_penalty_until = 0
            s.hunger_ticks = 0

        # Spawneo inicial de Manzanas Doradas Re-spawneables (1 por cada serpiente)
        target_food_count = len(state.snakes)
        for _ in range(target_food_count):
            p = self.random_free_cell(state)
            if p: state.foods.append(Food(pos=p, value=1, golden=True))

    def random_free_cell(self, state: ColosseumState) -> Optional[Point]:
        occupied = set(state.bombs.keys()) | {f.pos for f in state.foods}
        for s in state.snakes: occupied |= set(s.body)
        free = [Point(x, y) for y in range(state.grid_size) for x in range(state.grid_size) if Point(x, y) not in occupied]
        return self.rng.choice(free) if free else None

    def _spawn_death_debris(self, state: ColosseumState, s: ColosseumSnake) -> None:
        for i, p in enumerate(s.body):
            # Dejar restos de manzana normal (no respawnable)
            if i % 3 == 0: state.foods.append(Food(pos=p, value=1, golden=False))
            self._spawn_explosion(state, p, count=6, col=s.faction.body_color)

    def _spawn_bite_sparks(self, state: ColosseumState, p: Point, col: Tuple[int, int, int]) -> None:
        bw = state.grid_size * state.cell_px
        ox = max(MARGIN_PX, (648 - bw) // 2) + p.x * state.cell_px + state.cell_px // 2
        oy = HUD_HEIGHT + MARGIN_PX + p.y * state.cell_px + state.cell_px // 2
        for _ in range(8):
            ang = self.rng.uniform(0, 2 * math.pi)
            spd = self.rng.uniform(1.0, 3.5)
            state.particles.append(VisualParticle(
                x=ox, y=oy, vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                color=col, radius=self.rng.uniform(2.0, 4.0),
                life_ms=350, max_life_ms=350
            ))

    def _spawn_explosion(self, state: ColosseumState, p: Point, count: int = 14, col: Optional[Tuple[int, int, int]] = None) -> None:
        bw = state.grid_size * state.cell_px
        ox = max(MARGIN_PX, (648 - bw) // 2) + p.x * state.cell_px + state.cell_px // 2
        oy = HUD_HEIGHT + MARGIN_PX + p.y * state.cell_px + state.cell_px // 2
        for _ in range(count):
            ang = self.rng.uniform(0, 2 * math.pi)
            spd = self.rng.uniform(1.2, 5.0)
            c = col or (255, self.rng.randint(80, 220), 40)
            state.particles.append(VisualParticle(
                x=ox, y=oy, vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                color=c, radius=self.rng.uniform(2.5, 6.0),
                life_ms=450, max_life_ms=450
            ))

    def _update_nuclear(self, state: ColosseumState, now_ms: int) -> None:
        if not state.nuclear: return
        nuke = state.nuclear

        if nuke.state == "FALLING":
            fall_duration = nuke.fall_duration_ms or 900
            if now_ms >= nuke.start_ms + fall_duration:
                nuke.state = "IMPACT_FLASH"
                nuke.impact_ms = now_ms
                self._apply_nuclear_blast(state, nuke.center, nuke.blast_radius)
        elif nuke.state == "IMPACT_FLASH":
            if now_ms - nuke.impact_ms > 350:
                nuke.state = "SHOCKWAVE"
        elif nuke.state == "SHOCKWAVE":
            if now_ms - nuke.impact_ms > 2200:
                nuke.state = "FINISHED"
                state.nuclear = None

        if state.nuclear and state.nuclear.affected_cells:
            to_del = []
            for pt, (fase, exp) in state.nuclear.affected_cells.items():
                if now_ms >= exp:
                    if fase == "HOT": state.nuclear.affected_cells[pt] = ("ASH", now_ms + 4000)
                    else: to_del.append(pt)
            for pt in to_del: state.nuclear.affected_cells.pop(pt, None)

    def _apply_nuclear_blast(self, state: ColosseumState, center: Point, radius: int) -> None:
        if not state.nuclear: return
        now_ms = state.nuclear.impact_ms or state.nuclear.start_ms
        n = state.grid_size
        blast_cells = set()
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    pt = Point(center.x + dx, center.y + dy)
                    if in_bounds(pt, n):
                        blast_cells.add(pt)
                        state.nuclear.affected_cells[pt] = ("HOT", now_ms + 5000)
                        state.bombs.pop(pt, None)
                        state.foods = [f for f in state.foods if f.pos != pt]

        # Amputación Atómica Limpia o Muerte según Posición de la Cabeza
        for s in state.snakes:
            if not s.alive or not s.body: continue
            head = s.body[0]
            if head in blast_cells:
                # La cabeza fue alcanzada directamente en la zona cero: muerte total
                s.alive = False
                self._spawn_death_debris(state, s)
            else:
                # La cabeza sobrevivió fuera del cráter.
                # Detectar si alguna sección del cuerpo quedó atrapada en la detonación
                hit_indices = [i for i, p in enumerate(s.body) if p in blast_cells]
                if hit_indices:
                    cut_idx = min(hit_indices)
                    if cut_idx < 3:
                        # Si quedan menos de 3 segmentos conectados a la cabeza, la serpiente no sobrevive
                        s.alive = False
                        self._spawn_death_debris(state, s)
                    else:
                        # Amputación biológica continua: se conserva intacto s.body[:cut_idx]
                        # garantizando que la serpiente resultante esté 100% unida a su cabeza
                        amputated_parts = list(s.body)[cut_idx:]
                        s.body = deque(list(s.body)[:cut_idx])
                        for j, p in enumerate(amputated_parts):
                            if j % 2 == 0:
                                state.foods.append(Food(pos=p, value=1, golden=False))
                            self._spawn_explosion(state, p, count=8, col=(255, 140, 20))
