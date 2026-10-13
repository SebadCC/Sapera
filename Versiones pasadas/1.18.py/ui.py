# ui.py
from __future__ import annotations

from typing import List, Optional, Tuple

import pygame  # type: ignore

from game import Point, Direction, GameConfig, GameState, Food


class Renderer:
    def __init__(self, cell_px: int = 32, margin_px: int = 16, hud_h: int = 44):
        self.cell_px = cell_px
        self.margin_px = margin_px
        self.hud_h = hud_h
        self.font: Optional["pygame.font.Font"] = None

        self.snake_palettes = [
            ((95, 235, 140), (65, 175, 105)),
            ((120, 190, 255), (60, 130, 210)),
            ((255, 175, 90), (205, 120, 55)),
            ((255, 120, 170), (200, 75, 125)),
            ((220, 220, 220), (140, 140, 140)),
            ((210, 140, 255), (145, 85, 200)),
            ((255, 235, 110), (205, 175, 60)),
            ((120, 255, 220), (70, 200, 170)),
        ]

    def window_size(self, n: int) -> Tuple[int, int]:
        w = n * self.cell_px + 2 * self.margin_px
        h = n * self.cell_px + 2 * self.margin_px + self.hud_h
        return w, h

    def render(self, surface: "pygame.Surface", state: GameState, cfg: GameConfig, now_ms: int, current_pattern_name: str) -> None:
        if self.font is None:
            self.font = pygame.font.SysFont("consolas", 18)

        surface.fill((12, 12, 14))
        self._draw_background(surface, cfg)

        pygame.draw.rect(surface, (18, 18, 22), pygame.Rect(0, 0, surface.get_width(), self.margin_px + self.hud_h))
        self._text(surface, f"Score: {state.score}   FPS: {cfg.fps}   Pattern: {current_pattern_name}", (self.margin_px, 10), (235, 235, 235))
        self._text(
            surface,
            "J/L speed | X bombs | Z extra food | C color | R restart | ESC menu",
            (self.margin_px, 28),
            (160, 160, 160),
        )

        for p, exp in state.bombs.items():
            self._draw_bomb(surface, p, exp, now_ms, cfg)

        for f in state.foods:
            if f.respawn:
                self._draw_apple(surface, f.pos, cfg)
            else:
                self._draw_berry(surface, f.pos, cfg)

        self._draw_snake(surface, list(state.snake), state.direction, state.snake_color_index, cfg)

        if not state.alive:
            self._text(surface, "GAME OVER — R reinicia | ESC menú", (self.margin_px, 50), (255, 200, 120))

    # ------------------------------------------------------------

    def _origin(self) -> Tuple[int, int]:
        return self.margin_px, self.margin_px + self.hud_h

    def _cell_center(self, p: Point, cfg: GameConfig) -> Tuple[int, int]:
        ox, oy = self._origin()
        return (
            ox + p.x * self.cell_px + self.cell_px // 2,
            oy + p.y * self.cell_px + self.cell_px // 2,
        )

    def _draw_background(self, surface: "pygame.Surface", cfg: GameConfig) -> None:
        ox, oy = self._origin()
        n = cfg.n
        board_w = n * self.cell_px
        board_h = n * self.cell_px
        board_rect = pygame.Rect(ox - 6, oy - 6, board_w + 12, board_h + 12)
        pygame.draw.rect(surface, (20, 20, 24), board_rect, border_radius=14)

        # fondo chess oscuro
        for y in range(n):
            for x in range(n):
                col = (34, 34, 40) if (x + y) % 2 == 0 else (26, 26, 32)
                pygame.draw.rect(
                    surface,
                    col,
                    pygame.Rect(ox + x * self.cell_px, oy + y * self.cell_px, self.cell_px, self.cell_px),
                )

        # grid sutil encima
        grid_color = (38, 38, 44)
        for x in range(n + 1):
            px = ox + x * self.cell_px
            pygame.draw.line(surface, grid_color, (px, oy), (px, oy + board_h), 1)
        for y in range(n + 1):
            py = oy + y * self.cell_px
            pygame.draw.line(surface, grid_color, (ox, py), (ox + board_w, py), 1)

    def _draw_snake(self, surface: "pygame.Surface", pts: List[Point], direction: Direction, color_idx: int, cfg: GameConfig) -> None:
        if not pts:
            return
        head_col, body_col = self.snake_palettes[color_idx % len(self.snake_palettes)]
        shadow = (14, 14, 16)

        r_body = max(6, self.cell_px // 2 - 7)
        r_head = r_body + 2
        r_tail = max(5, r_body - 2)

        centers = [self._cell_center(p, cfg) for p in pts]

        for i in range(len(centers) - 1):
            pygame.draw.line(surface, shadow, centers[i], centers[i + 1], r_body * 2 + 6)
        for i in range(len(centers) - 1):
            pygame.draw.line(surface, body_col, centers[i], centers[i + 1], r_body * 2)

        for i in range(1, len(centers) - 1):
            pygame.draw.circle(surface, body_col, centers[i], r_body)

        pygame.draw.circle(surface, body_col, centers[-1], r_tail)

        pygame.draw.circle(surface, head_col, centers[0], r_head)
        self._draw_head_eyes(surface, centers[0], direction, r_head)

    def _draw_head_eyes(self, surface: "pygame.Surface", c: Tuple[int, int], d: Direction, r: int) -> None:
        cx, cy = c
        if d == Direction.UP:
            o1 = (cx - r // 3, cy - r // 3)
            o2 = (cx + r // 3, cy - r // 3)
        elif d == Direction.DOWN:
            o1 = (cx - r // 3, cy + r // 3)
            o2 = (cx + r // 3, cy + r // 3)
        elif d == Direction.LEFT:
            o1 = (cx - r // 3, cy - r // 3)
            o2 = (cx - r // 3, cy + r // 3)
        else:
            o1 = (cx + r // 3, cy - r // 3)
            o2 = (cx + r // 3, cy + r // 3)

        pygame.draw.circle(surface, (12, 12, 12), o1, max(2, r // 6))
        pygame.draw.circle(surface, (12, 12, 12), o2, max(2, r // 6))

    def _draw_apple(self, surface: "pygame.Surface", p: Point, cfg: GameConfig) -> None:
        cx, cy = self._cell_center(p, cfg)
        r = max(6, self.cell_px // 2 - 8)
        pygame.draw.circle(surface, (220, 70, 70), (cx, cy), r)
        pygame.draw.circle(surface, (245, 120, 120), (cx - r // 3, cy - r // 3), max(2, r // 3))
        pygame.draw.rect(surface, (110, 75, 45), pygame.Rect(cx - 2, cy - r - 4, 4, 10), border_radius=2)
        leaf = [(cx + 2, cy - r - 2), (cx + r // 2 + 6, cy - r - 8), (cx + r // 2, cy - r + 6)]
        pygame.draw.polygon(surface, (70, 190, 90), leaf)

    def _draw_berry(self, surface: "pygame.Surface", p: Point, cfg: GameConfig) -> None:
        cx, cy = self._cell_center(p, cfg)
        r = max(6, self.cell_px // 2 - 9)
        pygame.draw.circle(surface, (190, 120, 255), (cx, cy), r)
        pygame.draw.circle(surface, (230, 190, 255), (cx - r // 4, cy - r // 4), max(2, r // 3))

    def _draw_bomb(self, surface: "pygame.Surface", p: Point, exp_ms: int, now_ms: int, cfg: GameConfig) -> None:
        cx, cy = self._cell_center(p, cfg)
        r = max(6, self.cell_px // 2 - 9)

        pygame.draw.circle(surface, (60, 60, 70), (cx, cy), r)
        pygame.draw.circle(surface, (90, 90, 105), (cx - r // 4, cy - r // 4), max(2, r // 3))

        tleft = max(0, exp_ms - now_ms)
        blink = (tleft // 200) % 2 == 0
        spark_color = (255, 200, 80) if blink else (255, 140, 60)

        pygame.draw.line(surface, (160, 130, 90), (cx + r // 2, cy - r // 2), (cx + r + 6, cy - r - 6), 3)
        pygame.draw.circle(surface, spark_color, (cx + r + 6, cy - r - 6), 4)

    def _text(self, surface: "pygame.Surface", s: str, pos: Tuple[int, int], col: Tuple[int, int, int]) -> None:
        assert self.font is not None
        img = self.font.render(s, True, col)
        surface.blit(img, pos)
