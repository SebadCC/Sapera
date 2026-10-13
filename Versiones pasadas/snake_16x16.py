"""
Snake básico (16x16) con interfaz gráfica (Pygame).
Enfoque Open/Closed:
- GameEngine depende de interfaces (Rules, Renderer, Controller).
- Extiendes el juego creando nuevas clases sin modificar el motor.

Requisitos:
    Python 3.10+
    pip install pygame

Ejecutar:
    python snake_16x16.py
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Deque, List, Optional, Protocol, Set, Tuple
from collections import deque
import random
import sys

# --- Dependencia externa (pygame) con verificación clara ---
try:
    import pygame  # type: ignore
except Exception as e:
    print("ERROR: No se pudo importar 'pygame'.")
    print("Instálalo con:")
    print("  python -m pip install -U pip")
    print("  python -m pip install pygame")
    print("\nSi estás en Windows y 'python' no funciona, prueba:")
    print("  py -m pip install pygame")
    print("\nDetalle del error:", repr(e))
    sys.exit(1)


# =========================
# Dominio (modelo)
# =========================

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
    def dx(self) -> int:
        return self.value[0]

    @property
    def dy(self) -> int:
        return self.value[1]


@dataclass(slots=True)
class GameConfig:
    grid_w: int = 16
    grid_h: int = 16
    cell_px: int = 32
    fps: int = 10
    wall_collision: bool = True  # True: muere en paredes. False: wrap-around


@dataclass(slots=True)
class GameState:
    snake: Deque[Point]          # head = snake[0]
    direction: Direction
    food: Point
    alive: bool = True
    score: int = 0


# =========================
# Interfaces (Open/Closed)
# =========================

class IRuleSet(Protocol):
    def step(self, state: GameState, config: GameConfig) -> GameState:
        ...


class IRenderer(Protocol):
    def render(self, surface: "pygame.Surface", state: GameState, config: GameConfig) -> None:
        ...


class IInputController(Protocol):
    def update_direction(self, current: Direction, events: List["pygame.event.Event"]) -> Direction:
        ...


# =========================
# Control (teclado)
# =========================

class KeyboardController(IInputController):
    _key_to_dir = {
        pygame.K_UP: Direction.UP,
        pygame.K_w: Direction.UP,
        pygame.K_DOWN: Direction.DOWN,
        pygame.K_s: Direction.DOWN,
        pygame.K_LEFT: Direction.LEFT,
        pygame.K_a: Direction.LEFT,
        pygame.K_RIGHT: Direction.RIGHT,
        pygame.K_d: Direction.RIGHT,
    }

    @staticmethod
    def _is_opposite(a: Direction, b: Direction) -> bool:
        return (a.dx + b.dx == 0) and (a.dy + b.dy == 0)

    def update_direction(self, current: Direction, events: List["pygame.event.Event"]) -> Direction:
        new_dir = current
        for e in events:
            if e.type == pygame.KEYDOWN and e.key in self._key_to_dir:
                cand = self._key_to_dir[e.key]
                # evita reversa instantánea
                if not self._is_opposite(current, cand):
                    new_dir = cand
        return new_dir


# =========================
# Reglas clásicas
# =========================

class ClassicSnakeRules(IRuleSet):
    def __init__(self, rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()

    def step(self, state: GameState, config: GameConfig) -> GameState:
        if not state.alive:
            return state

        head = state.snake[0]
        nx = head.x + state.direction.dx
        ny = head.y + state.direction.dy

        # paredes o wrap
        if config.wall_collision:
            if nx < 0 or nx >= config.grid_w or ny < 0 or ny >= config.grid_h:
                state.alive = False
                return state
        else:
            nx %= config.grid_w
            ny %= config.grid_h

        new_head = Point(nx, ny)
        eats = (new_head == state.food)

        # colisión con el cuerpo:
        # si NO come, la cola se libera al final del tick, así que permitir caer en la celda de la cola
        body = list(state.snake)
        if not eats:
            body = body[:-1]

        if new_head in body:
            state.alive = False
            return state

        # mover
        state.snake.appendleft(new_head)

        if eats:
            state.score += 1
            state.food = self._spawn_food(state, config)
        else:
            state.snake.pop()

        return state

    def _spawn_food(self, state: GameState, config: GameConfig) -> Point:
        occupied: Set[Point] = set(state.snake)
        free: List[Point] = [
            Point(x, y)
            for y in range(config.grid_h)
            for x in range(config.grid_w)
            if Point(x, y) not in occupied
        ]
        # si no hay libres, ya llenaste el tablero (victoria práctica)
        if not free:
            return state.food
        return self.rng.choice(free)


# =========================
# Renderer Pygame
# =========================

class PygameGridRenderer(IRenderer):
    def __init__(self):
        self._font: Optional["pygame.font.Font"] = None

    def render(self, surface: "pygame.Surface", state: GameState, config: GameConfig) -> None:
        # inicializa fuente una sola vez
        if self._font is None:
            self._font = pygame.font.SysFont("consolas", 18)

        surface.fill((18, 18, 18))
        self._draw_grid(surface, config)

        # comida
        self._draw_cell(surface, state.food, config, color=(220, 70, 70))

        # snake
        snake_list = list(state.snake)
        if snake_list:
            self._draw_cell(surface, snake_list[0], config, color=(80, 220, 120))
            for p in snake_list[1:]:
                self._draw_cell(surface, p, config, color=(60, 170, 95))

        self._draw_text(surface, f"Score: {state.score}", (8, 6), (230, 230, 230))

        if not state.alive:
            self._draw_text(surface, "GAME OVER (R reinicia, ESC sale)", (8, 30), (255, 190, 80))

    def _draw_grid(self, surface: "pygame.Surface", config: GameConfig) -> None:
        w_px = config.grid_w * config.cell_px
        h_px = config.grid_h * config.cell_px
        grid_color = (35, 35, 35)

        for x in range(config.grid_w + 1):
            px = x * config.cell_px
            pygame.draw.line(surface, grid_color, (px, 0), (px, h_px), 1)

        for y in range(config.grid_h + 1):
            py = y * config.cell_px
            pygame.draw.line(surface, grid_color, (0, py), (w_px, py), 1)

    def _draw_cell(self, surface: "pygame.Surface", p: Point, config: GameConfig, color: Tuple[int, int, int]) -> None:
        rect = pygame.Rect(p.x * config.cell_px, p.y * config.cell_px, config.cell_px, config.cell_px)
        inner = rect.inflate(-4, -4)
        pygame.draw.rect(surface, color, inner, border_radius=6)

    def _draw_text(self, surface: "pygame.Surface", text: str, pos: Tuple[int, int], color: Tuple[int, int, int]) -> None:
        assert self._font is not None
        img = self._font.render(text, True, color)
        surface.blit(img, pos)


# =========================
# Motor (Open/Closed)
# =========================

class GameEngine:
    def __init__(self, config: GameConfig, rules: IRuleSet, renderer: IRenderer, controller: IInputController):
        self.config = config
        self.rules = rules
        self.renderer = renderer
        self.controller = controller
        self.state = self._new_game()

    def _new_game(self) -> GameState:
        cx, cy = self.config.grid_w // 2, self.config.grid_h // 2
        snake = deque([Point(cx, cy), Point(cx - 1, cy), Point(cx - 2, cy)])

        # comida inicial en una celda libre “razonable”
        preferred = [Point(2, 2), Point(self.config.grid_w - 3, 2), Point(2, self.config.grid_h - 3)]
        food = next((p for p in preferred if p not in snake), Point(0, 0))

        return GameState(
            snake=snake,
            direction=Direction.RIGHT,
            food=food,
            alive=True,
            score=0,
        )

    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption("Snake 16x16 (OCP)")
        surface = pygame.display.set_mode(
            (self.config.grid_w * self.config.cell_px, self.config.grid_h * self.config.cell_px)
        )
        clock = pygame.time.Clock()

        running = True
        while running:
            events = pygame.event.get()

            for e in events:
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                    running = False
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_r:
                    self.state = self._new_game()

            if self.state.alive:
                self.state.direction = self.controller.update_direction(self.state.direction, events)
                self.state = self.rules.step(self.state, self.config)

            self.renderer.render(surface, self.state, self.config)
            pygame.display.flip()
            clock.tick(self.config.fps)

        pygame.quit()


# =========================
# Main
# =========================

def main() -> None:
    config = GameConfig(grid_w=16, grid_h=16, cell_px=32, fps=10, wall_collision=True)
    rules = ClassicSnakeRules(rng=random.Random())
    renderer = PygameGridRenderer()
    controller = KeyboardController()

    engine = GameEngine(config, rules, renderer, controller)
    engine.run()


if __name__ == "__main__":
    main()
