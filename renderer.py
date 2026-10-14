# ============================================================
# renderer.py — Motor de Renderizado Gráfico y Efectos Visuales
# ============================================================

import pygame
import math
from typing import Optional, Tuple
from config import (
    GRID_SIZE, CELL_PX, MARGIN_PX, HUD_HEIGHT,
    COLOR_BG, COLOR_GOLD
)
from models import (
    Point, Food, SnakeMode, ColosseumSnake, ColosseumState,
    NuclearStrike, GameMode
)

class ColosseumRenderer:
    def __init__(self):
        self.font_title: Optional[pygame.font.Font] = None
        self.font_hud: Optional[pygame.font.Font] = None
        self.font_sub: Optional[pygame.font.Font] = None
        self.font_bubble: Optional[pygame.font.Font] = None
        self.particles: List[VisualParticle] = []
        self._dark_surf: Optional[pygame.Surface] = None

    def clear_particles(self) -> None:
        self.particles.clear()

    def window_size(self) -> Tuple[int, int]:
        return GRID_SIZE * CELL_PX + 2 * MARGIN_PX, GRID_SIZE * CELL_PX + 2 * MARGIN_PX + HUD_HEIGHT

    def render(self, surface: pygame.Surface, state: ColosseumState, now_ms: int) -> None:
        if not self.font_hud:
            self.font_title = pygame.font.SysFont("consolas", 20, bold=True)
            self.font_hud = pygame.font.SysFont("consolas", 13, bold=True)
            self.font_sub = pygame.font.SysFont("consolas", 12)
            self.font_bubble = pygame.font.SysFont("segoeuisymbol,arial,consolas", 14, bold=True)

        surface.fill(COLOR_BG)
        self._draw_board(surface, state)
        self._draw_hud_strict(surface, state, now_ms)

        if state.nuclear: self._draw_nuclear_3d(surface, state.nuclear, state, now_ms)
        for p, exp in state.bombs.items(): self._draw_bomb(surface, p, exp, state, now_ms)
        for f in state.foods: self._draw_food(surface, f, state)

        for s in state.snakes:
            if s.alive:
                self._draw_organic_snake(surface, s, state, now_ms)
            elif state.slow_mo_until_ms > now_ms and s.snake_id == state.kill_cam_target_id and getattr(state, "director_stage", "") == "PANIC":
                self._draw_organic_snake(surface, s, state, now_ms, is_impact=True)

        if state.slow_mo_until_ms > now_ms:
            self._draw_kill_camera_fx(surface, state, now_ms)
        elif state.director_banner_text and state.director_banner_until_ms > now_ms:
            self._draw_director_hud_toast(surface, state, now_ms)

        self._update_and_draw_particles(surface, state)

        if state.countdown_active or (state.countdown_start_ms > 0 and now_ms - state.countdown_start_ms < 3700):
            self._draw_countdown(surface, state, now_ms)

        if state.round_winner and not state.countdown_active:
            self._draw_winner_banner(surface, state.round_winner)

    def _origin(self, state: Optional[ColosseumState] = None) -> Tuple[int, int]:
        if state:
            bw = state.grid_size * state.cell_px
            ox = max(MARGIN_PX, (648 - bw) // 2)
            return ox, MARGIN_PX + HUD_HEIGHT
        return MARGIN_PX, MARGIN_PX + HUD_HEIGHT

    def _cell_center(self, p: Point, state: Optional[ColosseumState] = None) -> Tuple[int, int]:
        cpx = state.cell_px if state else CELL_PX
        ox, oy = self._origin(state)
        return ox + p.x * cpx + cpx // 2, oy + p.y * cpx + cpx // 2

    def _draw_board(self, surface: pygame.Surface, state: ColosseumState) -> None:
        ox, oy = self._origin(state)
        bw, bh = state.grid_size * state.cell_px, state.grid_size * state.cell_px
        border_col = (150, 75, 235) if not state.wall_collision else (32, 33, 40)
        pygame.draw.rect(surface, (18, 18, 22), pygame.Rect(ox - 6, oy - 6, bw + 12, bh + 12), border_radius=14)
        if not state.wall_collision:
            pygame.draw.rect(surface, border_col, pygame.Rect(ox - 6, oy - 6, bw + 12, bh + 12), width=2, border_radius=14)

        for y in range(state.grid_size):
            for x in range(state.grid_size):
                col = (28, 29, 34) if (x + y) % 2 == 0 else (22, 23, 27)
                pygame.draw.rect(surface, col, pygame.Rect(ox + x * state.cell_px, oy + y * state.cell_px, state.cell_px, state.cell_px))

    def _draw_hud_strict(self, surface: pygame.Surface, state: ColosseumState, now_ms: int) -> None:
        """
        HUD ESTRICTO:
        Contiene los 5 elementos exigidos:
        1. Estado de TikTok
        2. Modo de juego
        3. FPS
        4. Nombre de patrón
        5. Evento activo
        """
        w = surface.get_width()
        pygame.draw.rect(surface, (18, 18, 24), pygame.Rect(0, 0, w, HUD_HEIGHT))
        pygame.draw.line(surface, (35, 36, 45), (0, HUD_HEIGHT - 1), (w, HUD_HEIGHT - 1), 1)

        # 1. Estado de TikTok
        is_live = (now_ms - state.last_udp_ms < 4000) and (state.last_udp_ms > 0)
        led_col = (60, 235, 120) if is_live else (200, 160, 50)
        pygame.draw.circle(surface, led_col, (24, 18), 5)
        live_txt = "TIKTOK: LIVE" if is_live else "TIKTOK: ESPERA"
        surface.blit(self.font_hud.render(live_txt, True, led_col), (34, 10))

        # 2. Modo de Juego
        mode_names = {
            GameMode.BATTLE_ROYALE: f"BATTLE ROYALE ({len(state.snakes)}P)",
            GameMode.DUEL_1V1: "DUELO 1V1 (2P)",
            GameMode.HYPNOTIC: "HIPNÓTICO (1P)",
            GameMode.SPEEDRUN: "SPEEDRUN (1P)"
        }
        mode_txt = f"MODO: {mode_names[state.game_mode]}"
        surface.blit(self.font_hud.render(mode_txt, True, (240, 240, 245)), (185, 10))

        # 3. FPS
        fps_txt = f"FPS: {state.fps_base}"
        surface.blit(self.font_hud.render(fps_txt, True, COLOR_GOLD), (w - 90, 10))

        # 4. Nombre de Patrón
        active_snake = next((s for s in state.snakes if s.alive), state.snakes[0])
        if state.game_mode == GameMode.SPEEDRUN: pat_name = "Caza Voraz"
        elif state.game_mode == GameMode.HYPNOTIC:
            pat_name = "Caza Temprana" if len(active_snake.body) < 10 else "Espiral / Geometría"
        else:
            pat_name = active_snake.faction.personality_title

        pat_txt = f"PATRÓN: {pat_name}"
        surface.blit(self.font_sub.render(pat_txt, True, (170, 175, 195)), (24, 32))

        # 5. Evento Activo
        event_str = "EVENTO: NINGUNO"
        event_col = (130, 135, 150)

        if not state.wall_collision and state.wrap_mode_until_ms > now_ms:
            t_rem = (state.wrap_mode_until_ms - now_ms) / 1000.0
            event_str = f"EVENTO: TRASCENDENTE ({t_rem:.1f}s)"
            event_col = (210, 130, 255)
        else:
            for s in state.snakes:
                if s.alive and s.mode != SnakeMode.NORMAL and s.mode_until_ms > now_ms:
                    t_rem = (s.mode_until_ms - now_ms) / 1000.0
                    event_str = f"EVENTO: {s.mode.value} ({t_rem:.1f}s)"
                    event_col = (255, 220, 80) if s.mode == SnakeMode.GOLDEN else (255, 120, 200)
                    break

        surface.blit(self.font_sub.render(event_str, True, event_col), (260, 32))

    def _draw_food(self, surface: pygame.Surface, f: Food, state: Optional[ColosseumState] = None) -> None:
        cpx = state.cell_px if state else CELL_PX
        cx, cy = self._cell_center(f.pos, state)
        r = max(2.5, cpx // 2 - 4)

        if getattr(f, "golden", True):
            # MANZANA DORADA (Resplandor áureo, halo y destello brillante)
            pygame.draw.circle(surface, (180, 140, 20), (cx, cy), int(r + 1))
            pygame.draw.circle(surface, (255, 215, 50), (cx, cy), int(r))
            pygame.draw.circle(surface, (255, 245, 130), (cx - 1, cy - 1), max(2, int(r - 2)))
            pygame.draw.circle(surface, (255, 255, 220), (int(cx - r // 2), int(cy - r // 2)), max(1, int(r * 0.25)))
            # Tallo dorado / verde
            pygame.draw.line(surface, (130, 225, 90), (cx, cy - r), (cx + 2, cy - r - 3), 2)
        else:
            # MANZANA NORMAL (Cuerpo carmesí con tallo marrón y hoja verde)
            pygame.draw.circle(surface, (180, 25, 30), (cx, cy), int(r))
            pygame.draw.circle(surface, (235, 45, 50), (cx - 1, cy - 1), max(2, int(r - 1)))
            pygame.draw.circle(surface, (255, 120, 125), (int(cx - r // 2), int(cy - r // 2)), max(1, int(r * 0.25)))
            # Tallo marrón y hoja verde brillante
            pygame.draw.line(surface, (130, 80, 35), (cx, cy - r), (cx + 1, cy - r - 3), 2)
            pygame.draw.circle(surface, (65, 220, 95), (cx + 3, cy - r - 2), max(1, int(r * 0.35)))

    def _draw_organic_snake(self, surface: pygame.Surface, s: ColosseumSnake, state: ColosseumState, now_ms: int, is_impact: bool = False) -> None:
        pts = list(s.body)
        if not pts: return
        L = len(pts)
        centers = [self._cell_center(p, state) for p in pts]
        base_r = max(3.0, state.cell_px * 0.44)

        golden = (s.mode == SnakeMode.GOLDEN and s.mode_until_ms > now_ms)
        extasis = (s.mode == SnakeMode.EXTASIS and s.mode_until_ms > now_ms)

        # Radios redondeados continuos:
        # Cabeza ligeramente más ancha para porte gladiador, cuerpo redondeado uniforme y cola cónica suave
        taper_len = max(3, int(L * 0.22))
        radii = []
        for i in range(L):
            if i == 0:
                radii.append(base_r + 1.2)
            elif i >= L - taper_len:
                factor = 0.35 + 0.65 * ((L - 1 - i) / float(taper_len))
                radii.append(max(2.0, base_r * factor))
            else:
                radii.append(base_r)

        # Trazador de cápsulas 100% redondeadas (interpolación pura de círculos equidistantes)
        # Elimina las líneas cuadradas de Pygame y cualquier punta ancha en las esquinas y giros
        def draw_round_capsule(p1: Tuple[int, int], p2: Tuple[int, int], r1: float, r2: float, col: Tuple[int, int, int]):
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            dist = math.hypot(dx, dy)
            if dist < 1.0:
                pygame.draw.circle(surface, col, (int(p1[0]), int(p1[1])), int(r1))
                return
            steps = max(2, int(dist / 2.5))
            for st in range(steps + 1):
                t = st / float(steps)
                cx = int(p1[0] + dx * t)
                cy = int(p1[1] + dy * t)
                cr = int(r1 + (r2 - r1) * t)
                pygame.draw.circle(surface, col, (cx, cy), cr)

        # 1. Pasada de sombra redondeada inferior
        for i in range(L - 1):
            if abs(pts[i].x - pts[i+1].x) > 1 or abs(pts[i].y - pts[i+1].y) > 1: continue
            c1_sh = (centers[i][0] + 1, centers[i][1] + 2)
            c2_sh = (centers[i+1][0] + 1, centers[i+1][1] + 2)
            draw_round_capsule(c1_sh, c2_sh, radii[i] + 1.0, radii[i+1] + 1.0, (10, 11, 16))

        # 2. Pasada del cuerpo principal redondeado
        for i in range(L - 1, -1, -1):
            r = radii[i]
            if is_impact:
                pulse_col = (255, 120, 120) if (now_ms // 120) % 2 == 0 else (210, 55, 55)
                col = pulse_col if i == 0 else (140, 45, 45)
            elif golden:
                col = (255, 220, 80) if i == 0 else (220, 180, 50)
            elif extasis:
                phase = ((state.tick * 0.2) + i * 0.1) % 1.0
                col = self._hsv_to_rgb(phase, 0.95, 1.0)
            else:
                col = s.faction.head_color if i == 0 else s.faction.body_color

            if i < L - 1 and not (abs(pts[i].x - pts[i+1].x) > 1 or abs(pts[i].y - pts[i+1].y) > 1):
                draw_round_capsule(centers[i], centers[i+1], radii[i], radii[i+1], col)
            else:
                pygame.draw.circle(surface, col, centers[i], int(r))

        # 3. Pasada de brillo espinal suave (cresta 3D redondeada)
        for i in range(L - 1):
            if abs(pts[i].x - pts[i+1].x) > 1 or abs(pts[i].y - pts[i+1].y) > 1: continue
            h1 = (centers[i][0], centers[i][1] - 1)
            h2 = (centers[i+1][0], centers[i+1][1] - 1)
            base_col = s.faction.head_color if i == 0 else s.faction.body_color
            if is_impact: highlight_col = (255, 180, 180)
            elif golden: highlight_col = (255, 255, 180)
            elif extasis: highlight_col = (255, 255, 255)
            else:
                highlight_col = (
                    min(255, base_col[0] + 50),
                    min(255, base_col[1] + 50),
                    min(255, base_col[2] + 50)
                )
            hr1 = max(1.0, radii[i] * 0.42)
            hr2 = max(1.0, radii[i+1] * 0.42)
            draw_round_capsule(h1, h2, hr1, hr2, highlight_col)

        self._draw_snake_head_features(surface, s, centers[0], radii[0], state)
        self._draw_speech_bubble(surface, s, centers[0], state, now_ms)

    def _draw_speech_bubble(self, surface: pygame.Surface, s: ColosseumSnake, head_c: Tuple[int, int], state: ColosseumState, now_ms: int) -> None:
        if not s.speech_text or s.speech_until_ms <= now_ms:
            s.speech_text = None
            return

        font = self.font_bubble or pygame.font.SysFont("segoeuisymbol,arial,consolas", 14, bold=True)
        txt_surf = font.render(s.speech_text, True, (15, 16, 22))
        tw, th = txt_surf.get_width(), txt_surf.get_height()
        bw, bh = tw + 18, th + 10

        hx, hy = head_c
        bx = max(10, min(surface.get_width() - bw - 10, hx - bw // 2))
        by = max(40, hy - bh - 16)

        is_danger = getattr(s, "imminent_death", False)
        border_col = (255, 55, 55) if is_danger else s.faction.head_color
        border_width = 3 if is_danger else 2

        bubble_rect = pygame.Rect(bx, by, bw, bh)

        # Sombra sutil para máxima legibilidad sobre cualquier fondo
        shadow_surf = pygame.Surface((bw + 4, bh + 4), pygame.SRCALPHA)
        pygame.draw.rect(shadow_surf, (0, 0, 0, 110), pygame.Rect(2, 2, bw, bh), border_radius=8)
        surface.blit(shadow_surf, (bx, by))

        pygame.draw.rect(surface, (255, 255, 255), bubble_rect, border_radius=7)
        pygame.draw.rect(surface, border_col, bubble_rect, width=border_width, border_radius=7)

        # Pico del globo apuntando a la cabeza
        tail_p1 = (max(bx + 6, min(bx + bw - 14, hx - 5)), by + bh)
        tail_p2 = (max(bx + 14, min(bx + bw - 6, hx + 5)), by + bh)
        tail_tip = (hx, hy - 3)
        pygame.draw.polygon(surface, (255, 255, 255), [tail_p1, tail_p2, tail_tip])
        pygame.draw.line(surface, border_col, tail_p1, tail_tip, border_width)
        pygame.draw.line(surface, border_col, tail_p2, tail_tip, border_width)

        surface.blit(txt_surf, (bx + 9, by + 5))

    def _draw_kill_camera_fx(self, surface: pygame.Surface, state: ColosseumState, now_ms: int) -> None:
        if state.slow_mo_until_ms <= now_ms or not state.kill_cam_focus_pt:
            return

        w, h = surface.get_width(), surface.get_height()
        target_snake = next((s for s in state.snakes if s.snake_id == state.kill_cam_target_id and s.body), None)
        focus_pt = target_snake.body[0] if (target_snake and target_snake.alive) else state.kill_cam_focus_pt
        if not focus_pt: return
        fcx, fcy = self._cell_center(focus_pt, state)

        # 1. Viñeta oscura cinematográfica con foco en la víctima
        spot_r = max(32, int(state.cell_px * 2.4))
        if self._dark_surf is None or self._dark_surf.get_size() != (w, h):
            self._dark_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        self._dark_surf.fill((8, 8, 14, 110))
        pygame.draw.circle(self._dark_surf, (0, 0, 0, 0), (fcx, fcy), spot_r)
        surface.blit(self._dark_surf, (0, 0))

        # 2. Retícula táctica de impacto (Crosshair / Reticle)
        pulse = 1.0 + 0.12 * math.sin(now_ms * 0.018)
        ret_size = int(spot_r * 0.75 * pulse)
        ret_col = (255, 65, 65)
        d = ret_size
        arm = max(6, int(d * 0.35))
        # Top-left
        pygame.draw.line(surface, ret_col, (fcx - d, fcy - d), (fcx - d + arm, fcy - d), 2)
        pygame.draw.line(surface, ret_col, (fcx - d, fcy - d), (fcx - d, fcy - d + arm), 2)
        # Top-right
        pygame.draw.line(surface, ret_col, (fcx + d, fcy - d), (fcx + d - arm, fcy - d), 2)
        pygame.draw.line(surface, ret_col, (fcx + d, fcy - d), (fcx + d, fcy - d + arm), 2)
        # Bottom-left
        pygame.draw.line(surface, ret_col, (fcx - d, fcy + d), (fcx - d + arm, fcy + d), 2)
        pygame.draw.line(surface, ret_col, (fcx - d, fcy + d), (fcx - d, fcy + d - arm), 2)
        # Bottom-right
        pygame.draw.line(surface, ret_col, (fcx + d, fcy + d), (fcx + d - arm, fcy + d), 2)
        pygame.draw.line(surface, ret_col, (fcx + d, fcy + d), (fcx + d, fcy + d - arm), 2)
        # Centro
        pygame.draw.circle(surface, (255, 40, 40), (fcx, fcy), 3)

        # 3. Barras cinematográficas widescreen
        bar_h = 18
        pygame.draw.rect(surface, (10, 11, 15), pygame.Rect(0, 0, w, bar_h))
        pygame.draw.rect(surface, (10, 11, 15), pygame.Rect(0, h - bar_h, w, bar_h))

        # 4. Badge dramático Slow-Mo / Kill Cam (Pre-Death vs Post-Death / Director Mode)
        if self.font_hud:
            vic_name = state.kill_cam_victim_name or "GLADIADOR"
            is_pre_death = (getattr(state, "kill_cam_anticipation_until_ms", 0) > now_ms) or (target_snake and target_snake.alive)

            if state.director_banner_text and state.director_banner_until_ms > now_ms:
                badge_txt = state.director_banner_text
                badge_col = (255, 110, 110) if any(w in badge_txt for w in ("ACORRALADO", "PELIGRO", "ACECHA")) else (255, 220, 80)
                b_border = (230, 50, 50) if any(w in badge_txt for w in ("ACORRALADO", "PELIGRO")) else COLOR_GOLD
            elif is_pre_death:
                badge_txt = f"🎬 SLOW MOTION — {vic_name.upper()} EN PELIGRO INMINENTE ⚠️"
                badge_col = (255, 95, 95)
                b_border = (230, 50, 50)
            else:
                badge_txt = f"🎬 SLOW MOTION — ¡{vic_name.upper()} ELIMINADO! 💥"
                badge_col = (255, 220, 80)
                b_border = COLOR_GOLD

            badge_surf = self.font_hud.render(badge_txt, True, badge_col)
            badge_rect = badge_surf.get_rect(center=(w // 2, bar_h + 12))
            bg_rect = badge_rect.inflate(18, 6)
            pygame.draw.rect(surface, (18, 18, 24), bg_rect, border_radius=6)
            pygame.draw.rect(surface, b_border, bg_rect, width=1, border_radius=6)
            surface.blit(badge_surf, badge_rect)

            # Si la víctima o verdugo tiene un diálogo activo, destacarlo en el HUD superior widescreen
            speaking = next((s for s in state.snakes if s.speech_text and s.speech_until_ms > now_ms), None)
            if speaking:
                quote_txt = f"{speaking.faction.tag} {speaking.faction.name.upper()}: {speaking.speech_text}"
                q_surf = self.font_hud.render(quote_txt, True, (255, 240, 140))
                q_rect = q_surf.get_rect(center=(w // 2, bar_h + 34))
                bg_q = q_rect.inflate(20, 8)
                pygame.draw.rect(surface, (14, 15, 20), bg_q, border_radius=6)
                pygame.draw.rect(surface, speaking.faction.head_color, bg_q, width=1, border_radius=6)
                surface.blit(q_surf, q_rect)

    def _draw_director_hud_toast(self, surface: pygame.Surface, state: ColosseumState, now_ms: int) -> None:
        """Renderiza una notificación del Modo Director en el HUD cuando el slow motion aún no ha empezado."""
        if not self.font_hud or not state.director_banner_text: return
        w = surface.get_width()
        txt = state.director_banner_text
        badge_surf = self.font_hud.render(txt, True, (255, 225, 110))
        badge_rect = badge_surf.get_rect(center=(w // 2, HUD_HEIGHT + 20))
        bg_rect = badge_rect.inflate(22, 8)
        pygame.draw.rect(surface, (18, 19, 26), bg_rect, border_radius=6)
        pygame.draw.rect(surface, (215, 175, 45), bg_rect, width=1, border_radius=6)
        surface.blit(badge_surf, badge_rect)


    def _draw_snake_head_features(self, surface: pygame.Surface, s: ColosseumSnake, head_c: Tuple[int, int], r: float, state: ColosseumState) -> None:
        hx, hy = head_c
        dx, dy = s.direction.dx, s.direction.dy

        if s.tongue_timer > 0:
            tx = hx + dx * (r + 7)
            ty = hy + dy * (r + 7)
            pygame.draw.line(surface, (230, 40, 60), (hx + dx * r, hy + dy * r), (tx, ty), 2)
            if dx != 0:
                pygame.draw.line(surface, (230, 40, 60), (tx, ty), (tx + dx * 3, ty - 3), 1)
                pygame.draw.line(surface, (230, 40, 60), (tx, ty), (tx + dx * 3, ty + 3), 1)
            else:
                pygame.draw.line(surface, (230, 40, 60), (tx, ty), (tx - 3, ty + dy * 3), 1)
                pygame.draw.line(surface, (230, 40, 60), (tx, ty), (tx + 3, ty + dy * 3), 1)

        offset_fwd = r * 0.35
        offset_side = r * 0.45
        if dx != 0:
            eye1 = (hx + dx * offset_fwd, hy - offset_side)
            eye2 = (hx + dx * offset_fwd, hy + offset_side)
        else:
            eye1 = (hx - offset_side, hy + dy * offset_fwd)
            eye2 = (hx + offset_side, hy + dy * offset_fwd)

        eye_r = max(1.8, r * 0.32)
        for e in (eye1, eye2):
            ex, ey = int(e[0]), int(e[1])
            if s.blink_timer > 0:
                pygame.draw.line(surface, (20, 20, 25), (ex - eye_r, ey), (ex + eye_r, ey), 2)
            else:
                pygame.draw.circle(surface, (250, 250, 250), (ex, ey), int(eye_r))
                pygame.draw.circle(surface, (15, 15, 20), (ex, ey), max(1, int(eye_r * 0.55)))

    def _draw_bomb(self, surface: pygame.Surface, p: Point, exp_ms: int, state: Optional[ColosseumState] = None, now_ms: int = 0) -> None:
        cpx = state.cell_px if state else CELL_PX
        cx, cy = self._cell_center(p, state)
        r = max(2.5, cpx // 2 - 5)
        pygame.draw.circle(surface, (45, 45, 55), (cx, cy), int(r))
        spark = (255, 220, 50) if ((exp_ms - now_ms) // 150) % 2 == 0 else (255, 90, 30)
        pygame.draw.circle(surface, spark, (int(cx + r + 3), int(cy - r - 3)), 3)

    def _draw_nuclear_3d(self, surface: pygame.Surface, nuke: NuclearStrike, state: Optional[ColosseumState] = None, now_ms: int = 0) -> None:
        cpx = state.cell_px if state else CELL_PX
        for pt, (fase, _) in nuke.affected_cells.items():
            cx, cy = self._cell_center(pt, state)
            rect = pygame.Rect(cx - cpx // 2, cy - cpx // 2, cpx, cpx)
            if fase == "HOT":
                pygame.draw.rect(surface, (230, 95, 20), rect)
                inner = rect.inflate(-4, -4)
                if inner.width > 0 and inner.height > 0:
                    pygame.draw.rect(surface, (255, 175, 40), inner)
            elif fase == "ASH":
                pygame.draw.rect(surface, (95, 90, 100), rect)
            else:
                pygame.draw.rect(surface, (35, 35, 40), rect)

        if nuke.state == "FALLING":
            cx, target_y = self._cell_center(nuke.center, state)
            duration = nuke.fall_duration_ms or 900
            elapsed = max(0, now_ms - nuke.start_ms)
            prog = min(1.0, elapsed / float(duration))
            start_y = target_y - 340
            cur_y = int(start_y + (target_y - start_y) * (prog ** 1.6))

            dist_to_ground = max(0, target_y - cur_y)
            shadow_w = max(4, int(32 * (1.0 - dist_to_ground / 340.0)))
            pygame.draw.ellipse(surface, (10, 10, 14), pygame.Rect(cx - shadow_w // 2, target_y - 4, shadow_w, 8))

            # Estela de propulsión hipersuave
            pygame.draw.line(surface, (255, 195, 50), (cx, cur_y - 14), (cx, cur_y - 48), 5)
            pygame.draw.line(surface, (255, 90, 20), (cx, cur_y - 22), (cx, cur_y - 70), 3)

            # Ojiva balística táctica
            body_rect = pygame.Rect(cx - 7, cur_y - 18, 14, 28)
            pygame.draw.rect(surface, (220, 35, 35), body_rect, border_radius=6)
            pygame.draw.polygon(surface, (250, 70, 70), [(cx - 7, cur_y - 18), (cx + 7, cur_y - 18), (cx, cur_y - 30)])
            pygame.draw.rect(surface, (255, 220, 50), pygame.Rect(cx - 2, cur_y - 10, 4, 14))

        elif nuke.state == "IMPACT_FLASH":
            elapsed_flash = now_ms - (nuke.impact_ms or now_ms)
            alpha = max(0, int(220 * (1.0 - elapsed_flash / 350.0)))
            if alpha > 0:
                flash_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
                flash_surf.fill((255, 255, 255, alpha))
                surface.blit(flash_surf, (0, 0))

        elif nuke.state == "SHOCKWAVE":
            cx, cy = self._cell_center(nuke.center, state)
            elapsed_sw = now_ms - (nuke.impact_ms or now_ms)
            sw_prog = min(1.0, elapsed_sw / 1800.0)
            max_r = int(nuke.blast_radius * cpx * 1.15)
            cur_r = int(max_r * (sw_prog ** 0.8))
            if cur_r > 4:
                alpha = max(0, int(180 * (1.0 - sw_prog)))
                sw_surf = pygame.Surface((cur_r * 2 + 10, cur_r * 2 + 10), pygame.SRCALPHA)
                pygame.draw.circle(sw_surf, (255, 150, 35, alpha), (cur_r + 5, cur_r + 5), cur_r, width=max(2, int(6 * (1.0 - sw_prog))))
                pygame.draw.circle(sw_surf, (255, 230, 100, int(alpha * 0.5)), (cur_r + 5, cur_r + 5), max(1, cur_r - 4), width=2)
                surface.blit(sw_surf, (cx - cur_r - 5, cy - cur_r - 5))


    def _draw_countdown(self, surface: pygame.Surface, state: ColosseumState, now_ms: int) -> None:
        elapsed = now_ms - state.countdown_start_ms
        if elapsed >= 3700:
            state.countdown_active = False
            return
        if elapsed >= 3000:
            state.countdown_active = False
            anim_font = pygame.font.SysFont("consolas", 64, bold=True)
            img = anim_font.render("¡PELEA!", True, (255, 230, 80))
            rect = img.get_rect(center=(surface.get_width() // 2, surface.get_height() // 2))
            surface.blit(img, rect)
            return

        rem = 3 - (elapsed // 1000)
        phase = (elapsed % 1000) / 1000.0
        txt = str(rem)
        scale_factor = 1.0 + 0.35 * (1.0 - phase)

        font_size = int(64 * scale_factor)
        anim_font = pygame.font.SysFont("consolas", font_size, bold=True)
        img = anim_font.render(txt, True, COLOR_GOLD)
        rect = img.get_rect(center=(surface.get_width() // 2, surface.get_height() // 2))
        surface.blit(img, rect)

    def _update_and_draw_particles(self, surface: pygame.Surface, state: ColosseumState) -> None:
        if state.particles:
            self.particles.extend(state.particles)
            state.particles.clear()

        alive_p = []
        for p in self.particles:
            p.x += p.vx
            p.y += p.vy
            p.life_ms -= 16
            if p.life_ms > 0:
                r = max(1.0, p.radius * (p.life_ms / p.max_life_ms))
                pygame.draw.circle(surface, p.color, (int(p.x), int(p.y)), int(r))
                alive_p.append(p)
        self.particles = alive_p

    def _draw_winner_banner(self, surface: pygame.Surface, txt: str) -> None:
        assert self.font_title is not None
        img = self.font_title.render(txt, True, COLOR_GOLD)
        rect = img.get_rect(center=(surface.get_width() // 2, surface.get_height() // 2))
        bg = rect.inflate(36, 20)
        pygame.draw.rect(surface, (18, 18, 26), bg, border_radius=10)
        pygame.draw.rect(surface, COLOR_GOLD, bg, width=3, border_radius=10)
        surface.blit(img, rect)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> Tuple[int, int, int]:
        i = int(h * 6.0); f = (h * 6.0) - i
        p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
        i = i % 6
        if i == 0: r, g, b = v, t, p
        elif i == 1: r, g, b = q, v, p
        elif i == 2: r, g, b = p, v, t
        elif i == 3: r, g, b = p, q, v
        elif i == 4: r, g, b = t, p, v
        else: r, g, b = v, p, q
        return int(r * 255), int(g * 255), int(b * 255)
