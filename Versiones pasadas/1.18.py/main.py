# main.py
from __future__ import annotations

import sys
import random
from typing import Optional

try:
    import pygame  # type: ignore
except Exception as e:
    print("ERROR: No se pudo importar pygame.")
    print("Instala con: python -m pip install pygame")
    print("Detalle:", repr(e))
    sys.exit(1)

from game import (
    GameConfig,
    SnakeRules,
    random_free_cell,
    Food,
    GameState,
    Point,
    Direction,
)
from bot import (
    BotController,
    Pattern,
    SpiralPattern,
    PerimeterPattern,
    ZigZagPattern,
    DiagonalPattern,
    SmoothRandomPattern,
    HamiltonPattern,
    build_hamilton_cycle,
)
from ui import Renderer
from ex import EventBus, ActionSystem, ExternalInputController, GameEvent

# ============================================================
# CONFIG (mantengo el mismo set que venías usando en 1.16)
# ============================================================

INITIAL_SNAKE_LENGTH = 5

INITIAL_FOODS = 1  # “originales” (respawnean). Recomendado dejar en 1
MAX_EXTRA_FOODS_SIMULTANEOUS = 1  # tecla Z añade extras hasta este máximo; extras NO respawnean

BOMB_DURATION_MS = 5000
BOMB_SPAWN_COUNT = 1  # tecla X spawnea esta cantidad simultánea

GRID_SIZE = 16  # 16 => 16x16
WALL_COLLISION = True

INITIAL_FPS = 12

# BOT TUNING (SOLO estas dos variables)
PATTERN_VS_FOOD = 7       # 1..10
PATTERN_VS_DYNAMISM = 6   # 1..10


# ============================================================
# Scenes (menu + play)
# ============================================================

class Scene:
    def handle(self, events: list["pygame.event.Event"]) -> Optional["Scene"]:
        raise NotImplementedError

    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        raise NotImplementedError


class MenuScene(Scene):
    def __init__(self, app: "App"):
        self.app = app
        self.idx = 0
        self.items = [
            ("Play (Keyboard)", "kbd"),
            ("Watch Bot", "bot"),
            ("Quit", "quit"),
        ]
        self.font_t: Optional["pygame.font.Font"] = None
        self.font_i: Optional["pygame.font.Font"] = None
        self.font_s: Optional["pygame.font.Font"] = None

    def handle(self, events: list["pygame.event.Event"]) -> Optional["Scene"]:
        for e in events:
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return None
                if e.key in (pygame.K_UP, pygame.K_w):
                    self.idx = (self.idx - 1) % len(self.items)
                if e.key in (pygame.K_DOWN, pygame.K_s):
                    self.idx = (self.idx + 1) % len(self.items)
                if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    tag = self.items[self.idx][1]
                    if tag == "quit":
                        return None
                    if tag == "kbd":
                        return PlayScene(self.app, bot_mode=False)
                    return PlayScene(self.app, bot_mode=True)
        return self

    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        if self.font_t is None:
            self.font_t = pygame.font.SysFont("consolas", 30)
        if self.font_i is None:
            self.font_i = pygame.font.SysFont("consolas", 22)
        if self.font_s is None:
            self.font_s = pygame.font.SysFont("consolas", 16)

        surface.fill((12, 12, 14))
        surface.blit(self.font_t.render("SNAKE — BOT FOCUSED", True, (235, 235, 235)), (16, 16))

        y = 90
        for i, (label, _) in enumerate(self.items):
            sel = (i == self.idx)
            col = (255, 220, 120) if sel else (200, 200, 200)
            pref = "> " if sel else "  "
            surface.blit(self.font_i.render(pref + label, True, col), (16, y))
            y += 36

        surface.blit(self.font_s.render("UP/DOWN + ENTER | ESC quit", True, (150, 150, 150)),
                     (16, surface.get_height() - 30))


class PlayScene(Scene):
    def __init__(self, app: "App", bot_mode: bool):
        self.app = app
        self.bot_mode = bot_mode
        self.state = self.app.new_game_state()
        self.kbd_dir = self.state.direction

    def handle(self, events: list["pygame.event.Event"]) -> Optional["Scene"]:
        for e in events:
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return MenuScene(self.app)
                if e.key == pygame.K_r:
                    self.state = self.app.new_game_state()

                # acciones externas delegadas (teclado -> GameEvents)
                self.app.input_controller.handle_keydown(e.key)

                # teclado solo en modo humano
                if not self.bot_mode:
                    self._handle_dir_key(e.key)

        return self

    def _handle_dir_key(self, key: int) -> None:
        mapping = {
            pygame.K_UP: Direction.UP, pygame.K_w: Direction.UP,
            pygame.K_DOWN: Direction.DOWN, pygame.K_s: Direction.DOWN,
            pygame.K_LEFT: Direction.LEFT, pygame.K_a: Direction.LEFT,
            pygame.K_RIGHT: Direction.RIGHT, pygame.K_d: Direction.RIGHT,
        }
        if key not in mapping:
            return
        cand = mapping[key]
        # no permitir reversa
        if (cand.dx + self.kbd_dir.dx == 0) and (cand.dy + self.kbd_dir.dy == 0):
            return
        self.kbd_dir = cand

    def render(self, surface: "pygame.Surface", now_ms: int) -> None:
        pat_name = self.app.current_pattern_name()
        self.app.renderer.render(surface, self.state, self.app.cfg, now_ms, pat_name)


# ============================================================
# App (engine)
# ============================================================

class App:
    def __init__(self):
        self.rng = random.Random()

        self.cfg = GameConfig(
            n=int(GRID_SIZE),
            wall_collision=bool(WALL_COLLISION),
            fps=int(INITIAL_FPS),
        )

        self.renderer = Renderer(cell_px=32, margin_px=16, hud_h=44)

        self.event_bus = EventBus()
        self.actions = ActionSystem()
        self.input_controller = ExternalInputController(
            event_bus=self.event_bus,
            bomb_spawn_count=BOMB_SPAWN_COUNT,
            bomb_duration_ms=BOMB_DURATION_MS,
            max_extra_foods=MAX_EXTRA_FOODS_SIMULTANEOUS,
        )

        # reglas del juego (sin kwargs inventados)
        self.rules = SnakeRules(self.rng)

        # ✅ IMPORTANTE: primero patterns, luego bot
        cycle = build_hamilton_cycle(self.cfg.n)
        self.patterns: list[Pattern] = [
            SpiralPattern(),
            PerimeterPattern(),
            ZigZagPattern(),
            DiagonalPattern(),
            SmoothRandomPattern(),
            HamiltonPattern(cycle),
        ]
        self.bot = BotController(
            rng=self.rng,
            patterns=self.patterns,
            pattern_vs_food=PATTERN_VS_FOOD,
            pattern_vs_dyn=PATTERN_VS_DYNAMISM,
        )

    def current_pattern_name(self) -> str:
        return self.patterns[self.bot.current_idx].name

    def new_game_state(self) -> GameState:
        n = self.cfg.n
        cx, cy = n // 2, n // 2
        snake = deque([Point(cx - i, cy) for i in range(INITIAL_SNAKE_LENGTH)])

        state = GameState(
            snake=snake,
            direction=Direction.RIGHT,
            foods=[],
            bombs={},
            alive=True,
            score=0,
            snake_color_index=self.rng.randrange(0, 8),
            tick=0,
            head_history=deque(maxlen=180),
            cycle_penalty_until=0,
        )

        # spawn originales (respawn=True)
        for _ in range(max(1, int(INITIAL_FOODS))):
            p = random_free_cell(state, self.cfg, self.rng)
            if p is None:
                break
            state.foods.append(Food(pos=p, respawn=True))

        state.head_history.append(state.snake[0])
        return state

    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption("Snake — Bot Focused")
        surface = pygame.display.set_mode(self.renderer.window_size(self.cfg.n))
        clock = pygame.time.Clock()

        scene: Optional[Scene] = MenuScene(self)

        while scene is not None:
            now_ms = pygame.time.get_ticks()
            events = pygame.event.get()

            scene = scene.handle(events)
            if scene is None:
                break

            if isinstance(scene, PlayScene):
                drained = self.event_bus.drain()
                if drained:
                    self.actions.dispatch(drained, scene.state, self.cfg, self.rng, now_ms)

                if scene.state.alive:
                    if scene.bot_mode:
                        d = self.bot.choose_direction(scene.state, self.cfg)
                        scene.state.direction = d
                    else:
                        scene.state.direction = scene.kbd_dir

                    self.rules.step(scene.state, self.cfg, now_ms)

            scene.render(surface, now_ms)
            pygame.display.flip()
            clock.tick(self.cfg.fps)

        pygame.quit()


def main() -> None:
    if not (1 <= PATTERN_VS_FOOD <= 10 and 1 <= PATTERN_VS_DYNAMISM <= 10):
        print("ERROR: PATTERN_VS_FOOD y PATTERN_VS_DYNAMISM deben estar en 1..10")
        sys.exit(1)

    App().run()


if __name__ == "__main__":
    main()
