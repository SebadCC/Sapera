import math
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from models import (
    ColosseumSnake, ColosseumState, Point, Direction, Food, SnakeMode,
    FACTION_OFFENSIVE_PHRASES, FACTION_KILL_PHRASES, PRE_DEATH_CRIES, FactionId,
    HEAD_ON_CLASH_CHALLENGES, HEAD_ON_CLASH_PANIC, HEAD_ON_CRUSH_VICTORY,
    WALL_CRASH_PANIC, in_bounds
)

class DirectorEngine:
    """
    MODO DIRECTOR DE RETRANSMISIÓN (Observer Lookahead Buffer).
    
    Arquitectura de emisión profesional (Broadcast Delay):
    - Simula la partida con ~15-18 ticks de anticipación (~1.5 segundos en el futuro).
    - Los espectadores visualizan el flujo con retraso imperceptible.
    - Utiliza la cuenta regresiva de 3 segundos para sincronizar y llenar el buffer
      en segundo plano: el futuro arranca 1.5s antes, de modo que al llegar a "¡PELEA!",
      el buffer ya contiene el metraje futuro y el movimiento comienza con fluidez total.
    - Gestión Limpia de Partículas: Cada tick en el futuro genera partículas que se transfieren
      al snapshot correspondiente y se vacían del futuro, impidiendo acumulación de efectos congelados.
    - Kill Cam Punchy & Dinámica: Enfoque y desaceleración quirúrgica de ~750ms que se normaliza
      inmediatamente tras el impacto letal para mantener 60 FPS fluidos.
    """

    def __init__(self, app: Any, initial_state: ColosseumState, buffer_ticks: int = 18):
        self.app = app
        self.buffer_ticks = buffer_ticks
        self.future_state: ColosseumState = initial_state.clone()
        self.buffer: Deque[ColosseumState] = deque()
        self.current_state: ColosseumState = initial_state
        
        # Historial de eventos cinematográficos para no repetir spam
        self.last_threat_tick: int = -100
        self.scheduled_deaths: Dict[int, Dict[str, Any]] = {}

        self._init_countdown_sync(now_ms=initial_state.countdown_start_ms)

    def _init_countdown_sync(self, now_ms: int) -> None:
        """Sincroniza la cuenta regresiva visual y el pre-llenado del buffer futuro."""
        fps = max(4, self.future_state.fps_base)
        buffer_delay_ms = int((self.buffer_ticks / fps) * 1000)

        if not self.current_state.countdown_active:
            self.future_state.countdown_active = False
            self.prefill(now_ms)
        else:
            # Con cuenta regresiva activa (3000ms visual):
            # El futuro termina su cuenta regresiva buffer_delay_ms antes que el presente.
            # Durante los últimos segundos de cuenta regresiva (3, 2, 1...), el futuro
            # simula en segundo plano y precarga el buffer.
            self.future_state.countdown_start_ms = self.current_state.countdown_start_ms - buffer_delay_ms
            self.future_state.countdown_active = True
            self.buffer.clear()
            self.scheduled_deaths.clear()
            self.future_state.particles.clear()
            # Añadir el estado inicial a tick 0 en el buffer
            init_snap = self.future_state.clone()
            init_snap.countdown_active = False
            self.buffer.append(init_snap)

    def prefill(self, now_ms: int = 0) -> None:
        """Llena el buffer inicial con exactamente buffer_ticks estados del futuro."""
        self.buffer.clear()
        self.scheduled_deaths.clear()
        self.future_state.countdown_active = False
        self.future_state.particles.clear()
        for _ in range(self.buffer_ticks):
            self.buffer.append(self.future_state.clone())
            if not self.future_state.paused and self.future_state.round_winner is None:
                self.app.bot.decide_all(self.future_state, now_ms)
                self.app.rules.step(self.future_state, now_ms)
            self.future_state.particles.clear()
        if self.buffer:
            self.current_state = self.buffer[0]

    def reset_round(self, now_ms: int = 0) -> None:
        """Reinicia el buffer y la simulación futura cuando una ronda concluye."""
        self.app.rules.reset_round(self.future_state, now_ms)
        self.future_state.particles.clear()
        self.last_threat_tick = -100
        self.scheduled_deaths.clear()
        self.buffer.clear()

        # Configurar estado visual presente para la nueva ronda
        self.current_state = self.future_state.clone()
        self.current_state.countdown_active = True
        self.current_state.countdown_start_ms = now_ms
        self.current_state.particles.clear()

        if hasattr(self.app, "renderer") and hasattr(self.app.renderer, "clear_particles"):
            self.app.renderer.clear_particles()

        self._init_countdown_sync(now_ms)

    def inject_events(self, events: List[Any], now_ms: int) -> None:
        """Inyecta eventos externos (teclado / TikTok) en el futuro y en todos los snapshots en búfer."""
        self.app.actions.dispatch(events, self.future_state, now_ms)
        for snap in self.buffer:
            self.app.actions.dispatch(events, snap, now_ms)
        self.app.actions.dispatch(events, self.current_state, now_ms)

    def advance(self, now_ms: int) -> ColosseumState:
        """
        Avanza un paso de reproducción en el presente y repone el buffer futuro.
        Inspecciona el futuro para orquestar la Kill Cam y diálogos cinematográficos.
        """
        # A. FASE DE CUENTA REGRESIVA VISUAL (3... 2... 1...)
        if self.current_state.countdown_active:
            if now_ms >= self.current_state.countdown_start_ms + 3000:
                self.current_state.countdown_active = False
            else:
                # Durante la cuenta regresiva visual:
                # Verificar si el futuro ya puede simular para precargar el buffer
                if self.future_state.countdown_active:
                    if now_ms >= self.future_state.countdown_start_ms + 3000:
                        self.future_state.countdown_active = False

                if not self.future_state.countdown_active and len(self.buffer) < self.buffer_ticks:
                    if not self.future_state.paused and self.future_state.round_winner is None:
                        self.app.bot.decide_all(self.future_state, now_ms)
                        self.app.rules.step(self.future_state, now_ms)
                    self.buffer.append(self.future_state.clone())
                    self.future_state.particles.clear()

                return self.current_state

        # B. FASE DE COMBATE ACTIVO
        if self.future_state.countdown_active:
            self.future_state.countdown_active = False

        # Si faltan ticks para buffer_ticks por cualquier irregularidad, completar buffer
        while len(self.buffer) < self.buffer_ticks:
            if not self.future_state.paused and self.future_state.round_winner is None:
                self.app.bot.decide_all(self.future_state, now_ms)
                self.app.rules.step(self.future_state, now_ms)
            self.buffer.append(self.future_state.clone())
            self.future_state.particles.clear()

        # 1. Extraer el snapshot presente
        if len(self.buffer) > 0:
            self.current_state = self.buffer.popleft()

        self.current_state.countdown_active = False

        # Si este snapshot presente es el fin de ronda (victoria), asegurar temporizador de reset
        if self.current_state.round_winner and self.current_state.round_reset_ms <= now_ms:
            self.current_state.round_reset_ms = now_ms + 3500

        # 2. Mantener el buffer rellenando el futuro
        while len(self.buffer) < self.buffer_ticks:
            if not self.future_state.paused and self.future_state.round_winner is None:
                self.app.bot.decide_all(self.future_state, now_ms)
                self.app.rules.step(self.future_state, now_ms)
            self.buffer.append(self.future_state.clone())
            self.future_state.particles.clear()

        # 3. MODO DIRECTOR: Inspeccionar eventos futuros en el buffer
        self._orchestrate_cinematics(now_ms)

        return self.current_state

    def _orchestrate_cinematics(self, now_ms: int) -> None:
        """
        Escanea el buffer de snapshots para detectar muertes futuras
        y programar diálogos, spotlight y cámara lenta en el presente con 100% de precisión.
        Distingue claramente entre Choque Frontal (Duelo de Titanes), Acorralado en Cuerpo, y Muros.
        """
        buf_list = [self.current_state] + list(self.buffer)
        if len(buf_list) < 2:
            return

        cur_tick = self.current_state.tick

        # 1. Escanear el buffer para registrar muertes futuras en scheduled_deaths
        for i in range(len(buf_list) - 1):
            snap_a, snap_b = buf_list[i], buf_list[i + 1]
            for sa, sb in zip(snap_a.snakes, snap_b.snakes):
                if sa.alive and not sb.alive:
                    death_tick = snap_b.tick
                    if death_tick not in self.scheduled_deaths:
                        self.scheduled_deaths[death_tick] = self._analyze_death(snap_a, snap_b, sa, sb)

        # 2. Orquestar el estado presente según los eventos agendados
        active_deaths = list(self.scheduled_deaths.items())
        for death_tick, info in active_deaths:
            ticks_until = death_tick - cur_tick
            vic_name = info["victim_name"]
            killer_name = info["killer_name"]
            clash_type = info.get("clash_type", "TRAPPED_BODY")
            clash_reason = info.get("clash_reason", "SIZE")
            vic_len = info.get("victim_len", 0)
            killer_len = info.get("killer_len", 0)
            vic_score = info.get("victim_score", 0)
            killer_score = info.get("killer_score", 0)

            curr_victim = next((s for s in self.current_state.snakes if s.snake_id == info["victim_id"]), None)
            curr_killer = next((s for s in self.current_state.snakes if s.snake_id == info["killer_id"]), None) if info["killer_id"] is not None else None

            # ETAPA 1: ACECHO / DESAFÍO INMINENTE (10 a 16 ticks antes, ~1.0s - 1.6s)
            if 10 <= ticks_until <= 16:
                if cur_tick - self.last_threat_tick > 20:
                    self.last_threat_tick = cur_tick
                    if clash_type == "HEAD_ON_CLASH" and curr_killer and curr_killer.alive:
                        challenge = self.app.rng.choice(HEAD_ON_CLASH_CHALLENGES)
                        curr_killer.speech_text = challenge
                        curr_killer.speech_until_ms = now_ms + 2400
                        self.current_state.director_banner_text = f"⚔️ DUELO FRONTAL — ¡{killer_name} ({killer_len}) VS {vic_name} ({vic_len})! ⚔️"
                        self.current_state.director_banner_until_ms = now_ms + 2400
                        self.current_state.director_stage = "CHALLENGE"
                    elif clash_type == "TRAPPED_BODY" and curr_killer and curr_killer.alive:
                        threat = self.app.rng.choice(FACTION_OFFENSIVE_PHRASES.get(info["killer_fid"], ["¡No escaparás! ⚔️"]))
                        curr_killer.speech_text = threat
                        curr_killer.speech_until_ms = now_ms + 2400
                        self.current_state.director_banner_text = f"🎬 MODO DIRECTOR — ¡{killer_name} ACECHA A {vic_name}! 🎯"
                        self.current_state.director_banner_until_ms = now_ms + 2400
                        self.current_state.director_stage = "STALKING"

            # ETAPA 2: FOCO SPOTLIGHT, RETÍCULA Y PÁNICO PRE-MUERTE (1 a 8 ticks antes, ~0.1s - 0.8s)
            elif 1 <= ticks_until <= 8 and curr_victim and curr_victim.alive:
                # Activar slow motion quirúrgico manteniendo 60 FPS de visualización
                if self.current_state.slow_mo_until_ms <= now_ms:
                    self.current_state.slow_mo_until_ms = now_ms + 850
                    self.current_state.slow_mo_factor = 0.38

                self.current_state.kill_cam_target_id = curr_victim.snake_id
                self.current_state.kill_cam_anticipation_until_ms = now_ms + 450

                if clash_type == "HEAD_ON_CLASH":
                    # Foco en el punto medio de ambas cabezas en colisión frontal
                    if curr_killer and curr_killer.body and curr_victim.body:
                        vx, vy = curr_victim.body[0].x, curr_victim.body[0].y
                        kx, ky = curr_killer.body[0].x, curr_killer.body[0].y
                        self.current_state.kill_cam_focus_pt = Point((vx + kx) // 2, (vy + ky) // 2)
                    else:
                        self.current_state.kill_cam_focus_pt = info["impact_pt"]

                    self.current_state.kill_cam_victim_name = f"{killer_name} VS {vic_name}"
                    self.current_state.director_banner_text = f"⚡ ¡CHOQUE DE TITANES — {killer_name} VS {vic_name}! ⚡"
                    self.current_state.director_banner_until_ms = now_ms + 2200
                    self.current_state.director_stage = "CLASH_FOCUS"

                    if not curr_victim.speech_text or curr_victim.speech_until_ms <= now_ms:
                        curr_victim.speech_text = self.app.rng.choice(HEAD_ON_CLASH_PANIC)
                        curr_victim.speech_until_ms = now_ms + 2200
                elif clash_type == "TRAPPED_BODY":
                    self.current_state.kill_cam_focus_pt = curr_victim.body[0] if curr_victim.body else info["impact_pt"]
                    self.current_state.kill_cam_victim_name = vic_name
                    self.current_state.director_banner_text = f"🎬 IMPACTO INMINENTE — ¡{vic_name} ACORRALADO! ⚠️"
                    self.current_state.director_banner_until_ms = now_ms + 2200
                    self.current_state.director_stage = "PANIC"

                    if not curr_victim.speech_text or curr_victim.speech_until_ms <= now_ms:
                        curr_victim.speech_text = self.app.rng.choice(PRE_DEATH_CRIES)
                        curr_victim.speech_until_ms = now_ms + 2200
                elif clash_type == "WALL":
                    self.current_state.kill_cam_focus_pt = curr_victim.body[0] if curr_victim.body else info["impact_pt"]
                    self.current_state.kill_cam_victim_name = vic_name
                    self.current_state.director_banner_text = f"⚠️ PELIGRO CRÍTICO — ¡{vic_name} A PUNTO DE ESTRELLARSE! ⚠️"
                    self.current_state.director_banner_until_ms = now_ms + 2200
                    self.current_state.director_stage = "PANIC"

                    if not curr_victim.speech_text or curr_victim.speech_until_ms <= now_ms:
                        curr_victim.speech_text = self.app.rng.choice(WALL_CRASH_PANIC)
                        curr_victim.speech_until_ms = now_ms + 2200
                else:
                    self.current_state.kill_cam_focus_pt = curr_victim.body[0] if curr_victim.body else info["impact_pt"]
                    self.current_state.kill_cam_victim_name = vic_name
                    self.current_state.director_banner_text = f"⚠️ PELIGRO CRÍTICO — ¡{vic_name} EN PELIGRO INMINENTE! ⚠️"
                    self.current_state.director_banner_until_ms = now_ms + 2200
                    self.current_state.director_stage = "PANIC"

                    if not curr_victim.speech_text or curr_victim.speech_until_ms <= now_ms:
                        curr_victim.speech_text = self.app.rng.choice(PRE_DEATH_CRIES)
                        curr_victim.speech_until_ms = now_ms + 2200

            # ETAPA 3: IMPACTO FATAL Y CELEBRACIÓN (Momento de la eliminación)
            elif ticks_until <= 0:
                self.current_state.director_stage = "IMPACT"
                # Al producirse el impacto letal, acortar el slow-mo residual para retomar la fluidez inmediata
                if self.current_state.slow_mo_until_ms > now_ms + 350:
                    self.current_state.slow_mo_until_ms = now_ms + 350

                if clash_type == "HEAD_ON_CLASH":
                    if clash_reason == "SIZE":
                        self.current_state.director_banner_text = f"💥 ¡{killer_name} ({killer_len}) APLASTA POR TAMAÑO A {vic_name} ({vic_len})! 💥"
                        if curr_killer and curr_killer.alive:
                            curr_killer.speech_text = self.app.rng.choice(HEAD_ON_CRUSH_VICTORY)
                            curr_killer.speech_until_ms = now_ms + 3200
                    elif clash_reason == "GOLDEN":
                        self.current_state.director_banner_text = f"✨ ¡{killer_name} DESINTEGRA A {vic_name} CON SU AURA DORADA! ✨"
                        if curr_killer and curr_killer.alive:
                            curr_killer.speech_text = "¡Poder dorado invencible! 🌟"
                            curr_killer.speech_until_ms = now_ms + 3200
                    elif clash_reason == "SCORE":
                        self.current_state.director_banner_text = f"👑 ¡{killer_name} VENCE POR PUNTUACIÓN TÁCTICA ({killer_score} vs {vic_score})! 👑"
                        if curr_killer and curr_killer.alive:
                            curr_killer.speech_text = "¡Superioridad táctica en el choque! 👑"
                            curr_killer.speech_until_ms = now_ms + 3200
                    elif clash_reason == "MUTUAL_TIE":
                        self.current_state.director_banner_text = f"💥 ¡DESTRUCCIÓN MUTUA — CHOQUE FRONTAL SIN SUPERVIVIENTES! 💥"
                    else:
                        self.current_state.director_banner_text = f"💥 ¡{killer_name} DESTRUYE A {vic_name} EN EL CHOQUE FRONTAL! 💥"
                elif clash_type == "TRAPPED_BODY":
                    if curr_killer and curr_killer.alive:
                        kill_shout = self.app.rng.choice(FACTION_KILL_PHRASES.get(info["killer_fid"], ["¡Victoria! 🔥"]))
                        curr_killer.speech_text = kill_shout
                        curr_killer.speech_until_ms = now_ms + 3200
                        self.current_state.director_banner_text = f"🎬 ELIMINACIÓN CONFIRMADA — ¡{vic_name} COLISIONA CONTRA {killer_name}! 💥"
                    else:
                        self.current_state.director_banner_text = f"🎬 IMPACTO FATAL — ¡{vic_name} DESTRUIDO! 💥"
                elif clash_type == "WALL":
                    self.current_state.director_banner_text = f"💥 ¡{vic_name} SE ESTRELLÓ CONTRA EL MURO EXTERIOR! 💥"
                elif clash_type == "SELF_COLLISION":
                    self.current_state.director_banner_text = f"💥 ¡{vic_name} MORDIO SU PROPIO CUERPO! 💥"
                else:
                    self.current_state.director_banner_text = f"💥 ¡{vic_name} FUE DESTRUIDO! 💥"

                self.current_state.director_banner_until_ms = now_ms + 3000

                if ticks_until < -4:
                    self.scheduled_deaths.pop(death_tick, None)

    def _analyze_death(self, snap_a: ColosseumState, snap_b: ColosseumState, sa: ColosseumSnake, sb: ColosseumSnake) -> Dict[str, Any]:
        """
        Analiza a fondo las circunstancias exactas de la muerte futura de una serpiente
        comparando el estado snap_a (instante previo) con snap_b (instante del deceso).
        Distingue con precisión matemática:
        - HEAD_ON_CLASH (Duelo frontal de cabezas)
        - TRAPPED_BODY (Atrapada o emboscada contra cuerpo rival)
        - WALL (Impacto contra muro del perímetro)
        - SELF_COLLISION (Choque contra su propio cuerpo)
        - ENVIRONMENT (Detonación de bomba o impacto nuclear)
        """
        if not sa.body:
            return {
                "victim_id": sa.snake_id,
                "victim_name": sa.faction.name.upper(),
                "killer_id": None,
                "killer_name": None,
                "killer_fid": None,
                "clash_type": "ENVIRONMENT",
                "clash_reason": "HAZARD",
                "victim_len": 0,
                "killer_len": 0,
                "victim_score": sa.score,
                "killer_score": 0,
                "impact_pt": Point(0, 0),
            }

        head_a = sa.body[0]
        da = sa.direction
        target_a = Point(head_a.x + da.dx, head_a.y + da.dy)
        grid_n = snap_a.grid_size

        # 1. EVALUAR CHOQUE FRONTAL DE CABEZAS (DUELO DE TITANES)
        for sk in snap_a.snakes:
            if sk.snake_id == sa.snake_id or not sk.alive or not sk.body:
                continue
            head_k = sk.body[0]
            dk = sk.direction
            target_k = Point(head_k.x + dk.dx, head_k.y + dk.dy)

            # Las cabezas van al mismo punto o se cruzan directamente (distancia Manhattan <= 2)
            is_head_on = (target_a == target_k) or (target_a == head_k and target_k == head_a)
            if not is_head_on:
                dist_heads = abs(head_a.x - head_k.x) + abs(head_a.y - head_k.y)
                dist_targets = abs(target_a.x - target_k.x) + abs(target_a.y - target_k.y)
                if dist_heads <= 2 and dist_targets <= 1:
                    is_head_on = True

            if is_head_on:
                len_a = len(sa.body)
                len_k = len(sk.body)
                gold_a = (sa.mode == SnakeMode.GOLDEN)
                gold_k = (sk.mode == SnakeMode.GOLDEN)

                # Verificar si sk también murió en snap_b (empate)
                sk_b = next((s for s in snap_b.snakes if s.snake_id == sk.snake_id), None)
                mutual_tie = (sk_b is not None and not sk_b.alive)

                if mutual_tie:
                    reason = "MUTUAL_TIE"
                elif gold_k and not gold_a:
                    reason = "GOLDEN"
                elif len_k > len_a:
                    reason = "SIZE"
                elif sk.score > sa.score:
                    reason = "SCORE"
                else:
                    reason = "SIZE"

                impact_pt = target_a if in_bounds(target_a, grid_n) else head_a
                return {
                    "victim_id": sa.snake_id,
                    "victim_name": sa.faction.name.upper(),
                    "killer_id": sk.snake_id,
                    "killer_name": sk.faction.name.upper(),
                    "killer_fid": sk.faction.faction_id,
                    "clash_type": "HEAD_ON_CLASH",
                    "clash_reason": reason,
                    "victim_len": len_a,
                    "killer_len": len_k,
                    "victim_score": sa.score,
                    "killer_score": sk.score,
                    "impact_pt": impact_pt,
                }

        # 2. EVALUAR COLISIÓN CONTRA CUERPO RIVAL (EMBOSCADA / ACORRALADO)
        for sk in snap_a.snakes:
            if sk.snake_id == sa.snake_id or not sk.alive or not sk.body:
                continue
            body_set = set(sk.body)
            if target_a in body_set or any(Point(head_a.x + d[0], head_a.y + d[1]) in body_set for d in [(1,0), (-1,0), (0,1), (0,-1)]):
                return {
                    "victim_id": sa.snake_id,
                    "victim_name": sa.faction.name.upper(),
                    "killer_id": sk.snake_id,
                    "killer_name": sk.faction.name.upper(),
                    "killer_fid": sk.faction.faction_id,
                    "clash_type": "TRAPPED_BODY",
                    "clash_reason": "BODY_BLOCK",
                    "victim_len": len(sa.body),
                    "killer_len": len(sk.body),
                    "victim_score": sa.score,
                    "killer_score": sk.score,
                    "impact_pt": target_a if in_bounds(target_a, grid_n) else head_a,
                }

        # 3. EVALUAR IMPACTO CONTRA EL MURO EXTERIOR
        if not in_bounds(target_a, grid_n):
            return {
                "victim_id": sa.snake_id,
                "victim_name": sa.faction.name.upper(),
                "killer_id": None,
                "killer_name": None,
                "killer_fid": None,
                "clash_type": "WALL",
                "clash_reason": "WALL",
                "victim_len": len(sa.body),
                "killer_len": 0,
                "victim_score": sa.score,
                "killer_score": 0,
                "impact_pt": head_a,
            }

        # 4. EVALUAR IMPACTO CONTRA SU PROPIO CUERPO
        if target_a in set(list(sa.body)[:-1]):
            return {
                "victim_id": sa.snake_id,
                "victim_name": sa.faction.name.upper(),
                "killer_id": None,
                "killer_name": None,
                "killer_fid": None,
                "clash_type": "SELF_COLLISION",
                "clash_reason": "SELF",
                "victim_len": len(sa.body),
                "killer_len": 0,
                "victim_score": sa.score,
                "killer_score": 0,
                "impact_pt": target_a,
            }

        # 5. AMBIENTAL (BOMBA O IMPACTO NUCLEAR)
        return {
            "victim_id": sa.snake_id,
            "victim_name": sa.faction.name.upper(),
            "killer_id": None,
            "killer_name": None,
            "killer_fid": None,
            "clash_type": "ENVIRONMENT",
            "clash_reason": "HAZARD",
            "victim_len": len(sa.body),
            "killer_len": 0,
            "victim_score": sa.score,
            "killer_score": 0,
            "impact_pt": head_a,
        }

