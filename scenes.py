# ============================================================
# scenes.py — Escenas de Interfaz, Menús y Configuración del Coliseo
# ============================================================

import pygame
from typing import Protocol, Optional, List, Tuple, Any
from config import COLOR_GOLD, COLOR_BG, COLOR_PANEL_BG, COLOR_PANEL_BORDER
from models import GameMode, FactionId, FACTION_CONFIGS, FACTION_TACTICAL_DESCS, ColosseumMatchSetup

class Scene(Protocol):
    def handle(self, events: List[pygame.event.Event]) -> Optional["Scene"]: ...
    def render(self, surface: pygame.Surface, now_ms: int) -> None: ...

class MainMenuScene:
    def __init__(self, app: Any):
        self.app = app
        self.font_title: Optional[pygame.font.Font] = None
        self.font_btn: Optional[pygame.font.Font] = None
        self.font_sub: Optional[pygame.font.Font] = None
        self.buttons = [
            ("⚔️ INICIAR PARTIDA", "play"),
            ("🎮 SELECCIONAR MODO", "modes"),
            ("⌨️ CONTROLES DE TECLADO", "controls"),
            ("🎁 GUÍA DE REGALOS TIKTOK", "tiktok"),
            ("🚪 SALIR AL ESCRITORIO", "exit")
        ]
        self.hover_idx = -1

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE: return None
            if e.type == pygame.MOUSEMOTION:
                self.hover_idx = self._get_btn_at(e.pos)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                idx = self._get_btn_at(e.pos)
                if idx == 0: return PlayScene(self.app, GameMode.BATTLE_ROYALE)
                elif idx == 1: return ModeSelectScene(self.app)
                elif idx == 2: return ControlsScene(self.app)
                elif idx == 3: return TikTokGuideScene(self.app)
                elif idx == 4: return None
        return self

    def _get_btn_at(self, pos: Tuple[int, int]) -> int:
        w, h = self.app.renderer.window_size()
        bw, bh = min(420, w - 60), 52
        bx = (w - bw) // 2
        start_y = 195
        for i in range(len(self.buttons)):
            by = start_y + i * 68
            if bx <= pos[0] <= bx + bw and by <= pos[1] <= by + bh: return i
        return -1

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if not self.font_title:
            self.font_title = pygame.font.SysFont("consolas", 25, bold=True)
            self.font_btn = pygame.font.SysFont("consolas", 15, bold=True)
            self.font_sub = pygame.font.SysFont("consolas", 12)

        surface.fill(COLOR_BG)
        w, h = surface.get_width(), surface.get_height()

        title = self.font_title.render("SNAKE — THE COLOSSEUM", True, COLOR_GOLD)
        surface.blit(title, title.get_rect(center=(w // 2, 75)))
        sub = self.font_sub.render("SaperaAI v2.0 — Arena de Facciones & TikTok Live", True, (160, 165, 180))
        surface.blit(sub, sub.get_rect(center=(w // 2, 108)))

        bw, bh = min(420, w - 60), 52
        bx = (w - bw) // 2
        start_y = 195
        for i, (label, _) in enumerate(self.buttons):
            by = start_y + i * 68
            is_hover = (i == self.hover_idx)
            btn_col = (36, 38, 48) if is_hover else COLOR_PANEL_BG
            border_col = COLOR_GOLD if is_hover else COLOR_PANEL_BORDER
            text_col = (255, 235, 120) if is_hover else (225, 230, 240)

            pygame.draw.rect(surface, btn_col, pygame.Rect(bx, by, bw, bh), border_radius=10)
            pygame.draw.rect(surface, border_col, pygame.Rect(bx, by, bw, bh), width=2 if is_hover else 1, border_radius=10)
            btn_surf = self.font_btn.render(label, True, text_col)
            surface.blit(btn_surf, btn_surf.get_rect(center=(bx + bw // 2, by + bh // 2)))

        footer = self.font_sub.render("Desarrollado con arquitectura SaperaAI", True, (100, 105, 125))
        surface.blit(footer, footer.get_rect(center=(w // 2, h - 30)))

class ModeSelectScene:
    def __init__(self, app: Any):
        self.app = app
        self.font_title: Optional[pygame.font.Font] = None
        self.font_btn: Optional[pygame.font.Font] = None
        self.font_desc: Optional[pygame.font.Font] = None
        self.modes = [
            (GameMode.BATTLE_ROYALE, "⚔️ BATTLE ROYALE (COLISEO PERSONALIZADO)", "Configura tamaño de arena, gladiadores y jinetes."),
            (GameMode.DUEL_1V1, "🔥 DUELO 1V1 (2 SERPIENTES)", "Duelo directo Fénix Carmesí vs Cobra Esmeralda."),
            (GameMode.HYPNOTIC, "🌀 MODO HIPNÓTICO (1 SERPIENTE)", "Espectáculo zen: espiral respiratoria y patrones anti-bucle."),
            (GameMode.SPEEDRUN, "⚡ MODO RÁPIDO / SPEEDRUN (1P)", "IA voraz cazando comida a máxima velocidad.")
        ]
        self.hover_idx = -1

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE: return MainMenuScene(self.app)
            if e.type == pygame.MOUSEMOTION:
                self.hover_idx = self._get_mode_at(e.pos)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                idx = self._get_mode_at(e.pos)
                if idx == 99: return MainMenuScene(self.app)
                if idx == 0:
                    return ColosseumSetupScene(self.app)
                if 0 < idx < len(self.modes):
                    return PlayScene(self.app, self.modes[idx][0])
        return self

    def _get_mode_at(self, pos: Tuple[int, int]) -> int:
        w = self.app.renderer.window_size()[0]
        if 20 <= pos[0] <= 130 and 20 <= pos[1] <= 56: return 99
        bw, bh = min(560, w - 40), 70
        bx = (w - bw) // 2
        start_y = 110
        for i in range(len(self.modes)):
            by = start_y + i * 86
            if bx <= pos[0] <= bx + bw and by <= pos[1] <= by + bh: return i
        return -1

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if not self.font_title:
            self.font_title = pygame.font.SysFont("consolas", 22, bold=True)
            self.font_btn = pygame.font.SysFont("consolas", 15, bold=True)
            self.font_desc = pygame.font.SysFont("consolas", 12)

        surface.fill(COLOR_BG)
        w = surface.get_width()

        pygame.draw.rect(surface, (28, 29, 36), pygame.Rect(20, 20, 100, 34), border_radius=8)
        pygame.draw.rect(surface, (80, 85, 105), pygame.Rect(20, 20, 100, 34), width=1, border_radius=8)
        surface.blit(self.font_desc.render("⬅ VOLVER", True, (220, 220, 230)), (32, 29))

        title = self.font_title.render("ELIGE EL MODO DE JUEGO", True, (245, 245, 245))
        surface.blit(title, title.get_rect(center=(w // 2, 40)))

        bw, bh = min(560, w - 40), 70
        bx = (w - bw) // 2
        start_y = 110
        for i, (_, label, desc) in enumerate(self.modes):
            by = start_y + i * 86
            is_hover = (i == self.hover_idx)
            btn_col = (38, 40, 50) if is_hover else COLOR_PANEL_BG
            border_col = COLOR_GOLD if is_hover else (50, 55, 70)
            text_col = (255, 235, 120) if is_hover else (230, 230, 240)

            pygame.draw.rect(surface, btn_col, pygame.Rect(bx, by, bw, bh), border_radius=10)
            pygame.draw.rect(surface, border_col, pygame.Rect(bx, by, bw, bh), width=2, border_radius=10)
            surface.blit(self.font_btn.render(label, True, text_col), (bx + 18, by + 12))
            surface.blit(self.font_desc.render(desc, True, (160, 165, 180)), (bx + 18, by + 40))

class ColosseumSetupScene:
    def __init__(self, app: Any):
        self.app = app
        self.font_title: Optional[pygame.font.Font] = None
        self.font_section: Optional[pygame.font.Font] = None
        self.font_btn: Optional[pygame.font.Font] = None
        self.font_desc: Optional[pygame.font.Font] = None
        self.font_tag: Optional[pygame.font.Font] = None

        self.grid_options = [
            (16, "16x16", "Reducido"),
            (22, "22x22", "Normal"),
            (32, "32x32", "Ampliado"),
            (48, "48x48", "Mega Arena"),
        ]
        self.selected_grid_idx = 1

        self.count_options = [2, 3, 4, 5]
        self.selected_count = 4

        self.available_factions: List[FactionId] = [
            FactionId.RED,
            FactionId.GREEN,
            FactionId.BLUE,
            FactionId.PURPLE,
            FactionId.GOLD
        ]

        self.slot_factions: List[FactionId] = [
            FactionId.RED,
            FactionId.GREEN,
            FactionId.BLUE,
            FactionId.PURPLE,
            FactionId.GOLD
        ]

        self.hover_element: Optional[str] = None

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return ModeSelectScene(self.app)
                elif e.key in (pygame.K_RETURN, pygame.K_SPACE):
                    return self._start_game()
            if e.type == pygame.MOUSEMOTION:
                self.hover_element = self._get_element_at(e.pos)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                elem = self._get_element_at(e.pos)
                if elem == "back":
                    return ModeSelectScene(self.app)
                elif elem == "start":
                    return self._start_game()
                elif elem and elem.startswith("grid_"):
                    self.selected_grid_idx = int(elem.split("_")[1])
                elif elem and elem.startswith("count_"):
                    self.selected_count = int(elem.split("_")[1])
                elif elem and elem.startswith("slot_prev_"):
                    slot_idx = int(elem.split("_")[2])
                    cur_f = self.slot_factions[slot_idx]
                    idx = self.available_factions.index(cur_f)
                    self.slot_factions[slot_idx] = self.available_factions[(idx - 1) % len(self.available_factions)]
                elif elem and (elem.startswith("slot_next_") or elem.startswith("slot_")):
                    slot_idx = int(elem.split("_")[-1])
                    cur_f = self.slot_factions[slot_idx]
                    idx = self.available_factions.index(cur_f)
                    self.slot_factions[slot_idx] = self.available_factions[(idx + 1) % len(self.available_factions)]
        return self

    def _start_game(self) -> Scene:
        factions = [self.slot_factions[i] for i in range(self.selected_count)]
        grid_size = self.grid_options[self.selected_grid_idx][0]
        setup = ColosseumMatchSetup(grid_size=grid_size, factions=factions)
        return PlayScene(self.app, GameMode.BATTLE_ROYALE, setup=setup)

    def _get_element_at(self, pos: Tuple[int, int]) -> Optional[str]:
        if 20 <= pos[0] <= 115 and 16 <= pos[1] <= 48:
            return "back"

        bw, bh, gap = 136, 36, 12
        start_x, y1 = 34, 88
        for i in range(len(self.grid_options)):
            bx = start_x + i * (bw + gap)
            if bx <= pos[0] <= bx + bw and y1 <= pos[1] <= y1 + bh:
                return f"grid_{i}"

        y2 = 152
        for i, cnt in enumerate(self.count_options):
            bx = start_x + i * (bw + gap)
            if bx <= pos[0] <= bx + bw and y2 <= pos[1] <= y2 + 32:
                return f"count_{cnt}"

        start_y = 232
        card_w, card_h, gap_card = 580, 58, 7
        for i in range(self.selected_count):
            by = start_y + i * (card_h + gap_card)
            if 34 <= pos[0] <= 34 + card_w and by <= pos[1] <= by + card_h:
                if pos[0] <= 110:
                    return f"slot_prev_{i}"
                elif pos[0] >= 34 + card_w - 40:
                    return f"slot_next_{i}"
                else:
                    return f"slot_{i}"

        btn_w, btn_h = 460, 50
        btn_x = (648 - btn_w) // 2
        btn_y = 574
        if btn_x <= pos[0] <= btn_x + btn_w and btn_y <= pos[1] <= btn_y + btn_h:
            return "start"

        return None

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if not self.font_title:
            self.font_title = pygame.font.SysFont("consolas", 20, bold=True)
            self.font_section = pygame.font.SysFont("consolas", 13, bold=True)
            self.font_btn = pygame.font.SysFont("consolas", 13, bold=True)
            self.font_desc = pygame.font.SysFont("consolas", 11)
            self.font_tag = pygame.font.SysFont("consolas", 10, bold=True)

        surface.fill(COLOR_BG)
        w = surface.get_width()

        is_back_hov = (self.hover_element == "back")
        back_col = (42, 44, 56) if is_back_hov else (28, 29, 36)
        back_border = COLOR_GOLD if is_back_hov else (60, 65, 80)
        pygame.draw.rect(surface, back_col, pygame.Rect(20, 16, 95, 32), border_radius=8)
        pygame.draw.rect(surface, back_border, pygame.Rect(20, 16, 95, 32), width=1, border_radius=8)
        surface.blit(self.font_desc.render("⬅ VOLVER", True, (220, 220, 235)), (32, 25))

        title = self.font_title.render("⚔️ CONFIGURACIÓN DEL COLISEO", True, COLOR_GOLD)
        surface.blit(title, title.get_rect(center=(w // 2, 24)))
        sub = self.font_desc.render("Personaliza la arena, gladiadores y personalidades tácticas.", True, (160, 165, 180))
        surface.blit(sub, sub.get_rect(center=(w // 2, 46)))

        # 1. Tamaño
        surface.blit(self.font_section.render("1. TAMAÑO DE LA ARENA", True, (240, 240, 245)), (34, 68))
        bw, bh, gap = 136, 36, 12
        start_x, y1 = 34, 88
        for i, (gsize, label, sub_lbl) in enumerate(self.grid_options):
            bx = start_x + i * (bw + gap)
            is_sel = (i == self.selected_grid_idx)
            is_hov = (self.hover_element == f"grid_{i}")
            if is_sel:
                bg = (48, 42, 28); b_border = COLOR_GOLD; txt_c = (255, 235, 130)
            elif is_hov:
                bg = (34, 36, 46); b_border = (130, 135, 160); txt_c = (245, 245, 255)
            else:
                bg = (22, 23, 30); b_border = (50, 52, 65); txt_c = (190, 195, 210)

            pygame.draw.rect(surface, bg, pygame.Rect(bx, y1, bw, bh), border_radius=8)
            pygame.draw.rect(surface, b_border, pygame.Rect(bx, y1, bw, bh), width=2 if is_sel else 1, border_radius=8)
            l_s = self.font_btn.render(label, True, txt_c)
            surface.blit(l_s, l_s.get_rect(center=(bx + bw // 2, y1 + 12)))
            sub_s = self.font_tag.render(sub_lbl, True, (160, 165, 180) if not is_sel else (255, 220, 100))
            surface.blit(sub_s, sub_s.get_rect(center=(bx + bw // 2, y1 + 25)))

        # 2. Cantidad
        surface.blit(self.font_section.render("2. CANTIDAD DE GLADIADORES", True, (240, 240, 245)), (34, 134))
        y2 = 152
        for i, cnt in enumerate(self.count_options):
            bx = start_x + i * (bw + gap)
            is_sel = (cnt == self.selected_count)
            is_hov = (self.hover_element == f"count_{cnt}")
            if is_sel:
                bg = (24, 46, 36); b_border = (80, 235, 150); txt_c = (140, 255, 190)
            elif is_hov:
                bg = (34, 36, 46); b_border = (130, 135, 160); txt_c = (245, 245, 255)
            else:
                bg = (22, 23, 30); b_border = (50, 52, 65); txt_c = (190, 195, 210)

            pygame.draw.rect(surface, bg, pygame.Rect(bx, y2, bw, 32), border_radius=8)
            pygame.draw.rect(surface, b_border, pygame.Rect(bx, y2, bw, 32), width=2 if is_sel else 1, border_radius=8)
            c_s = self.font_btn.render(f"{cnt} GLADIADORES", True, txt_c)
            surface.blit(c_s, c_s.get_rect(center=(bx + bw // 2, y2 + 16)))

        # 3. Ranuras de Facciones
        surface.blit(self.font_section.render("3. JINETES Y PERSONALIDADES (CLIC EN RANURA PARA ROTAR)", True, (240, 240, 245)), (34, 194))
        tip_s = self.font_desc.render("Toca cualquier gladiador o sus flechas para cambiar su personalidad:", True, (150, 155, 170))
        surface.blit(tip_s, (34, 212))

        start_y = 232
        card_w, card_h, gap_card = 580, 58, 7
        for i in range(self.selected_count):
            by = start_y + i * (card_h + gap_card)
            fid = self.slot_factions[i]
            cfg = FACTION_CONFIGS[fid]

            is_card_hov = (self.hover_element in (f"slot_{i}", f"slot_prev_{i}", f"slot_next_{i}"))
            c_bg = (32, 34, 46) if is_card_hov else (22, 23, 31)
            c_border = cfg.head_color if is_card_hov else (55, 60, 75)

            pygame.draw.rect(surface, c_bg, pygame.Rect(34, by, card_w, card_h), border_radius=10)
            pygame.draw.rect(surface, c_border, pygame.Rect(34, by, card_w, card_h), width=2 if is_card_hov else 1, border_radius=10)

            pygame.draw.rect(surface, (16, 17, 24), pygame.Rect(44, by + 12, 34, 34), border_radius=6)
            pygame.draw.rect(surface, cfg.head_color, pygame.Rect(44, by + 12, 34, 34), width=1, border_radius=6)
            p_s = self.font_btn.render(f"P{i+1}", True, cfg.head_color)
            surface.blit(p_s, p_s.get_rect(center=(44 + 17, by + 12 + 17)))

            prev_hov = (self.hover_element == f"slot_prev_{i}")
            pygame.draw.rect(surface, (45, 48, 62) if prev_hov else (28, 30, 40), pygame.Rect(84, by + 14, 24, 30), border_radius=4)
            pygame.draw.rect(surface, COLOR_GOLD if prev_hov else (60, 65, 80), pygame.Rect(84, by + 14, 24, 30), width=1, border_radius=4)
            arr_l = self.font_btn.render("<", True, (255, 235, 120) if prev_hov else (200, 205, 220))
            surface.blit(arr_l, arr_l.get_rect(center=(84 + 12, by + 14 + 15)))

            cx, cy = 124, by + 29
            pygame.draw.circle(surface, cfg.head_color, (cx, cy), 10)
            pygame.draw.circle(surface, (255, 255, 255), (cx + 3, cy - 3), 3)
            pygame.draw.circle(surface, (10, 10, 15), (cx + 4, cy - 3), 1)
            pygame.draw.circle(surface, (255, 255, 255), (cx + 3, cy + 3), 3)
            pygame.draw.circle(surface, (10, 10, 15), (cx + 4, cy + 3), 1)

            name_s = self.font_btn.render(cfg.name, True, cfg.head_color)
            surface.blit(name_s, (142, by + 10))

            tag_s = self.font_tag.render(cfg.tag, True, (240, 240, 245))
            tag_rect = pygame.Rect(142 + name_s.get_width() + 8, by + 12, tag_s.get_width() + 10, 16)
            pygame.draw.rect(surface, (36, 38, 50), tag_rect, border_radius=4)
            pygame.draw.rect(surface, (70, 75, 95), tag_rect, width=1, border_radius=4)
            surface.blit(tag_s, (tag_rect.x + 5, tag_rect.y + 1))

            pers_text = f"[{cfg.personality_title.upper()}]"
            pers_s = self.font_tag.render(pers_text, True, (255, 220, 90))
            pers_rect = pygame.Rect(tag_rect.right + 6, by + 12, pers_s.get_width() + 10, 16)
            pygame.draw.rect(surface, (44, 40, 25), pers_rect, border_radius=4)
            pygame.draw.rect(surface, (180, 145, 40), pers_rect, width=1, border_radius=4)
            surface.blit(pers_s, (pers_rect.x + 5, pers_rect.y + 1))

            desc_text = FACTION_TACTICAL_DESCS.get(fid, "")
            surface.blit(self.font_desc.render(desc_text, True, (165, 170, 185)), (142, by + 34))

            next_hov = (self.hover_element == f"slot_next_{i}")
            next_x = 34 + card_w - 36
            pygame.draw.rect(surface, (45, 48, 62) if next_hov else (28, 30, 40), pygame.Rect(next_x, by + 14, 24, 30), border_radius=4)
            pygame.draw.rect(surface, COLOR_GOLD if next_hov else (60, 65, 80), pygame.Rect(next_x, by + 14, 24, 30), width=1, border_radius=4)
            arr_r = self.font_btn.render(">", True, (255, 235, 120) if next_hov else (200, 205, 220))
            surface.blit(arr_r, arr_r.get_rect(center=(next_x + 12, by + 14 + 15)))

        # 4. Botón Iniciar Batalla
        btn_w, btn_h = 460, 50
        btn_x = (w - btn_w) // 2
        btn_y = 574
        is_start_hov = (self.hover_element == "start")
        s_bg = (255, 195, 45) if is_start_hov else (215, 155, 25)
        s_border = (255, 235, 140) if is_start_hov else COLOR_GOLD
        s_txt_col = (15, 15, 20) if is_start_hov else (12, 12, 16)

        pygame.draw.rect(surface, s_bg, pygame.Rect(btn_x, btn_y, btn_w, btn_h), border_radius=12)
        pygame.draw.rect(surface, s_border, pygame.Rect(btn_x, btn_y, btn_w, btn_h), width=2, border_radius=12)

        start_txt = pygame.font.SysFont("consolas", 16, bold=True).render("⚔️ ¡ENTRAR AL COLISEO! (INICIAR BATALLA)", True, s_txt_col)
        surface.blit(start_txt, start_txt.get_rect(center=(w // 2, btn_y + btn_h // 2)))

        info_lbl = self.font_desc.render("Presiona [ENTER] para iniciar rápido o [ESC] para volver a selección de modos", True, (130, 135, 150))
        surface.blit(info_lbl, info_lbl.get_rect(center=(w // 2, btn_y + btn_h + 16)))

class ControlsScene:
    def __init__(self, app: Any):
        self.app = app
        self.font: Optional[pygame.font.Font] = None
        self.font_desc: Optional[pygame.font.Font] = None

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE: return MainMenuScene(self.app)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if 20 <= e.pos[0] <= 130 and 20 <= e.pos[1] <= 56: return MainMenuScene(self.app)
        return self

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if not self.font:
            self.font = pygame.font.SysFont("consolas", 13, bold=True)
            self.font_desc = pygame.font.SysFont("consolas", 12)

        surface.fill(COLOR_BG)
        pygame.draw.rect(surface, (28, 29, 36), pygame.Rect(20, 20, 100, 34), border_radius=8)
        surface.blit(self.font_desc.render("⬅ VOLVER", True, (220, 220, 230)), (32, 29))

        title = pygame.font.SysFont("consolas", 22, bold=True).render("CONTROLES DE TECLADO", True, (245, 245, 245))
        surface.blit(title, title.get_rect(center=(surface.get_width() // 2, 40)))

        controls = [
            ("TECLA [ Z ]", "Spawnear Manzana Dorada (Áurea continua, re-spawneable)"),
            ("TECLA [ C ]", "Spawnear Manzana Normal (Roja-verde, consumible temporal)"),
            ("TECLA [ V ]", "Eliminar una Manzana Dorada del tablero"),
            ("TECLA [ K ]", "Pausar / Reanudar (Abre panel modal)"),
            ("TECLA [ J ]", "Disminuir velocidad (-2 FPS)"),
            ("TECLA [ L ]", "Aumentar velocidad (+2 FPS)"),
            ("TECLA [ W ]", "Alternar Modo Trascendente (Sin Paredes)"),
            ("TECLA [ X ]", "Spawnear Bomba con cuenta regresiva"),
            ("TECLA [ B ]", "Desatar Ataque de BOMBA ATÓMICA en 3D"),
            ("TECLA [ E ]", "Activar MODO ÉXTASIS (Arcoíris a 2x)"),
            ("TECLA [ G ]", "Activar MODO DORADO (Invulnerable a 3x)"),
            ("TECLA [ R ]", "Reiniciar ronda actual"),
            ("TECLA [ ESC ]", "Pausar / Volver al Menú Principal")
        ]

        start_y = 90
        for i, (kname, desc) in enumerate(controls):
            y = start_y + i * 36
            surface.blit(self.font.render(kname, True, COLOR_GOLD), (36, y))
            surface.blit(self.font_desc.render(f"➜ {desc}", True, (200, 205, 220)), (175, y))

class TikTokGuideScene:
    def __init__(self, app: Any):
        self.app = app
        self.font: Optional[pygame.font.Font] = None
        self.font_desc: Optional[pygame.font.Font] = None

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE: return MainMenuScene(self.app)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if 20 <= e.pos[0] <= 130 and 20 <= e.pos[1] <= 56: return MainMenuScene(self.app)
        return self

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if not self.font:
            self.font = pygame.font.SysFont("consolas", 13, bold=True)
            self.font_desc = pygame.font.SysFont("consolas", 12)

        surface.fill(COLOR_BG)
        pygame.draw.rect(surface, (28, 29, 36), pygame.Rect(20, 20, 100, 34), border_radius=8)
        surface.blit(self.font_desc.render("⬅ VOLVER", True, (220, 220, 230)), (32, 29))

        title = pygame.font.SysFont("consolas", 22, bold=True).render("GUÍA DE TIKTOK LIVE", True, (245, 245, 245))
        surface.blit(title, title.get_rect(center=(surface.get_width() // 2, 40)))

        gifts = [
            ("🌹 ROSA", "Spawnea Bombas normales letales"),
            ("🍎 TIKTOK", "Spawnea Manzanas Normales consumibles"),
            ("🎨 GG", "Cambia el color de la serpiente"),
            ("💖 CORAZÓN / CAP", "Activa MODO ÉXTASIS (Arcoíris a 2x)"),
            ("👑 CORONA / DRAGÓN", "Activa MODO DORADO (Invulnerable a 3x)"),
            ("☢️ LEÓN / UNIVERSO", "Ataque Cinematográfico BOMBA ATÓMICA"),
            ("🎆 FIREWORK", "Reinicia la ronda del juego"),
            ("💬 FACCIONES", "Apoya con #Rojo, #Verde, #Azul, #Morado, #Dorado")
        ]

        start_y = 100
        for i, (gname, desc) in enumerate(gifts):
            y = start_y + i * 42
            surface.blit(self.font.render(gname, True, (255, 120, 160)), (36, y))
            surface.blit(self.font_desc.render(f"➜ {desc}", True, (210, 215, 230)), (240, y))

class PlayScene:
    def __init__(self, app: Any, game_mode: GameMode, setup: Optional[ColosseumMatchSetup] = None):
        self.app = app
        self.game_mode = game_mode
        self.setup = setup
        self.state = self.app.create_initial_state(game_mode, setup=setup)
        self.pause_overlay_open = False
        self.pause_buttons = [("▶ REANUDAR", "resume"), ("🔄 REINICIAR", "restart"), ("🚪 MENÚ PRINCIPAL", "menu")]
        self.pause_hover = -1

        # MODO DIRECTOR DE RETRANSMISIÓN (Observer Lookahead Buffer)
        self.director: Any = None
        if game_mode in (GameMode.BATTLE_ROYALE, GameMode.DUEL_1V1):
            from director import DirectorEngine
            self.director = DirectorEngine(self.app, self.state, buffer_ticks=18)

    def handle(self, events: List[pygame.event.Event]) -> Optional[Scene]:
        for e in events:
            if e.type == pygame.QUIT: return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE or e.key == pygame.K_k:
                    self.pause_overlay_open = not self.pause_overlay_open
                    self.state.paused = self.pause_overlay_open
                elif e.key == pygame.K_r:
                    if hasattr(self.app, "renderer"):
                        self.app.renderer.clear_particles()
                    if self.director:
                        self.director.reset_round(pygame.time.get_ticks())
                        self.state = self.director.current_state
                    else:
                        self.app.rules.reset_round(self.state, pygame.time.get_ticks())

                self.app.input.handle_keydown(e.key)

            if self.pause_overlay_open:
                if e.type == pygame.MOUSEMOTION:
                    self.pause_hover = self._get_pause_btn(e.pos)
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    idx = self._get_pause_btn(e.pos)
                    if idx == 0:
                        self.pause_overlay_open = False
                        self.state.paused = False
                    elif idx == 1:
                        if hasattr(self.app, "renderer"):
                            self.app.renderer.clear_particles()
                        if self.director:
                            self.director.reset_round(pygame.time.get_ticks())
                            self.state = self.director.current_state
                        else:
                            self.app.rules.reset_round(self.state, pygame.time.get_ticks())
                        self.pause_overlay_open = False
                        self.state.paused = False
                    elif idx == 2:
                        return MainMenuScene(self.app)

        return self

    def _get_pause_btn(self, pos: Tuple[int, int]) -> int:
        w, h = self.app.renderer.window_size()
        bw, bh = 260, 42
        bx = (w - bw) // 2
        start_y = (h - 200) // 2 + 50
        for i in range(len(self.pause_buttons)):
            by = start_y + i * 54
            if bx <= pos[0] <= bx + bw and by <= pos[1] <= by + bh: return i
        return -1

    def render(self, surface: pygame.Surface, now_ms: int) -> None:
        if self.director:
            self.state = self.director.current_state
        self.app.renderer.render(surface, self.state, now_ms)
        if self.pause_overlay_open:
            self._render_pause_menu(surface)

    def _render_pause_menu(self, surface: pygame.Surface) -> None:
        w, h = surface.get_width(), surface.get_height()
        dark = pygame.Surface((w, h), pygame.SRCALPHA)
        dark.fill((10, 10, 14, 190))
        surface.blit(dark, (0, 0))

        pw, ph = 320, 230
        px, py = (w - pw) // 2, (h - ph) // 2
        pygame.draw.rect(surface, (20, 21, 28), pygame.Rect(px, py, pw, ph), border_radius=14)
        pygame.draw.rect(surface, COLOR_GOLD, pygame.Rect(px, py, pw, ph), width=2, border_radius=14)

        title = pygame.font.SysFont("consolas", 18, bold=True).render("JUEGO EN PAUSA", True, (255, 220, 90))
        surface.blit(title, title.get_rect(center=(w // 2, py + 26)))

        bw, bh = 260, 42
        bx = (w - bw) // 2
        start_y = py + 56
        btn_font = pygame.font.SysFont("consolas", 14, bold=True)
        for i, (label, _) in enumerate(self.pause_buttons):
            by = start_y + i * 54
            is_hover = (i == self.pause_hover)
            bcol = (38, 40, 52) if is_hover else (26, 27, 34)
            b_border = COLOR_GOLD if is_hover else (60, 65, 80)
            txt_col = (255, 235, 120) if is_hover else (220, 225, 235)

            pygame.draw.rect(surface, bcol, pygame.Rect(bx, by, bw, bh), border_radius=8)
            pygame.draw.rect(surface, b_border, pygame.Rect(bx, by, bw, bh), width=2, border_radius=8)
            txt_s = btn_font.render(label, True, txt_col)
            surface.blit(txt_s, txt_s.get_rect(center=(bx + bw // 2, by + bh // 2)))
