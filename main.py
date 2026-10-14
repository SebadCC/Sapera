# ============================================================
# main.py — Aplicación Principal y Bucle de Ejecución (SaperaAI v2.0)
# ============================================================

import sys
import random
from collections import deque
from typing import Optional, List

try:
    import pygame
except ImportError as e:
    print("ERROR: No se pudo importar pygame.")
    print("Instala con: python -m pip install pygame")
    print("Detalle:", repr(e))
    sys.exit(1)

from config import (
    GRID_SIZE, CELL_PX, INITIAL_FPS, INITIAL_SNAKE_LENGTH,
    UDP_HOST, UDP_PORT
)
from models import (
    Point, Direction, Food, FactionId, FACTION_CONFIGS,
    ColosseumSnake, ColosseumState, ColosseumMatchSetup, GameMode
)
from rules import ColosseumRules
from horse import HorseVerifier
from riders import (
    SpiralPattern, PerimeterPattern, ZigZagPattern, SmoothFlowPattern,
    MultiAgentBotController
)
from events import EventBus, UDPReceiver, ActionSystem, ExternalInputController
from renderer import ColosseumRenderer
from scenes import Scene, MainMenuScene, PlayScene

class ColosseumApp:
    def __init__(self):
        self.rng = random.Random()
        self.renderer = ColosseumRenderer()
        self.rules = ColosseumRules(self.rng)
        self.event_bus = EventBus()
        self.actions = ActionSystem(self)
        self.input = ExternalInputController(self.event_bus)
        self.udp = UDPReceiver(UDP_HOST, UDP_PORT)

        self.patterns = [
            SpiralPattern(),
            PerimeterPattern(),
            ZigZagPattern(),
            SmoothFlowPattern()
        ]
        self.bot = MultiAgentBotController(self.rng, self.patterns)

    def create_initial_state(self, game_mode: GameMode = GameMode.BATTLE_ROYALE,
                             setup: Optional[ColosseumMatchSetup] = None) -> ColosseumState:
        g_size = setup.grid_size if setup else GRID_SIZE
        c_px = max(10, 616 // g_size)

        starts_all = [
            (Point(4, 4), Direction.RIGHT),
            (Point(g_size - 5, 4), Direction.DOWN),
            (Point(g_size - 5, g_size - 5), Direction.LEFT),
            (Point(4, g_size - 5), Direction.UP),
            (Point(g_size // 2, g_size // 2), Direction.RIGHT),
        ]
        starts_2p = [
            (Point(4, g_size // 2), Direction.RIGHT),
            (Point(g_size - 5, g_size // 2), Direction.LEFT),
        ]
        starts_1p = [
            (Point(g_size // 2, g_size // 2), Direction.RIGHT)
        ]

        if game_mode == GameMode.BATTLE_ROYALE:
            factions = setup.factions if (setup and setup.factions) else [
                FactionId.RED, FactionId.GREEN, FactionId.BLUE, FactionId.PURPLE
            ]
            starts = starts_all
        elif game_mode == GameMode.DUEL_1V1:
            factions = [FactionId.RED, FactionId.GREEN]
            starts = starts_2p
        else:
            factions = [FactionId.GREEN] if game_mode == GameMode.HYPNOTIC else [FactionId.RED]
            starts = starts_1p

        snakes: List[ColosseumSnake] = []
        for i, fid in enumerate(factions):
            cfg = FACTION_CONFIGS[fid]
            start_p, start_d = starts[i % len(starts)]
            body = deque([
                Point(start_p.x - start_d.dx * j, start_p.y - start_d.dy * j)
                for j in range(INITIAL_SNAKE_LENGTH)
            ])
            snakes.append(ColosseumSnake(
                snake_id=i, faction=cfg, body=body, direction=start_d, pattern_idx=i
            ))

        now_ms = pygame.time.get_ticks() if pygame.get_init() else 0
        state = ColosseumState(
            game_mode=game_mode, snakes=snakes, foods=[], bombs={}, wall_collision=True,
            grid_size=g_size, cell_px=c_px,
            fps_base=INITIAL_FPS, countdown_active=True, countdown_start_ms=now_ms
        )

        # 1 Manzana Dorada por cada serpiente activa (re-spawneable)
        for _ in range(len(snakes)):
            p = self.random_free_cell(state)
            if p: state.foods.append(Food(pos=p, value=1, golden=True))

        return state

    def random_free_cell(self, state: ColosseumState) -> Optional[Point]:
        return self.rules.random_free_cell(state)

    def reset_round(self, state: ColosseumState, hard: bool = False, now_ms: int = 0) -> None:
        self.rules.reset_round(state, now_ms)
        if hard:
            for s in state.snakes:
                s.wins = 0
                s.score = 0

    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption("Snake — The Colosseum & SaperaAI v2.0")
        surface = pygame.display.set_mode(self.renderer.window_size())
        clock = pygame.time.Clock()

        scene: Optional[Scene] = MainMenuScene(self)
        last_sim_tick_ms = 0

        while scene is not None:
            now_ms = pygame.time.get_ticks()
            events = pygame.event.get()
            scene = scene.handle(events)
            if scene is None: break

            self.udp.poll(self.event_bus)

            if isinstance(scene, PlayScene):
                drained = self.event_bus.drain()
                if drained:
                    self.actions.dispatch(drained, scene.state, now_ms)
                    if scene.director:
                        scene.director.inject_events(drained, now_ms)

                # Control Independiente de Tics de Simulación (TPS)
                base_tps = max(4, scene.state.fps_base)
                if scene.state.slow_mo_until_ms > now_ms:
                    effective_tps = max(2.5, base_tps * scene.state.slow_mo_factor)
                else:
                    effective_tps = base_tps

                sim_interval_ms = 1000.0 / effective_tps

                if now_ms - last_sim_tick_ms >= sim_interval_ms:
                    if scene.state.round_winner is not None:
                        # Gestión de reinicio automático tras mostrar el letrero de victoria
                        if scene.state.round_reset_ms > 0 and now_ms >= scene.state.round_reset_ms:
                            if scene.director:
                                scene.director.reset_round(now_ms)
                                scene.state = scene.director.current_state
                            else:
                                self.rules.reset_round(scene.state, now_ms)
                    elif not scene.state.paused:
                        if scene.director:
                            # MODO DIRECTOR: Reproducción del presente orquestada por el Lookahead Buffer
                            scene.state = scene.director.advance(now_ms)
                        else:
                            self.bot.decide_all(scene.state, now_ms)
                            triggered_anticipation = self.rules.check_impending_killcam(scene.state, now_ms)
                            if not triggered_anticipation:
                                self.rules.step(scene.state, now_ms)
                    last_sim_tick_ms = now_ms

            # Renderizado continuo y fluido a 60 FPS
            scene.render(surface, now_ms)
            pygame.display.flip()
            clock.tick(60)

        pygame.quit()

def main():
    print("==========================================================")
    print(" Snake — The Colosseum v2.0 (Modular Edition — SaperaAI)")
    print(f" UDP Listening: {UDP_HOST}:{UDP_PORT}")
    print("==========================================================")
    ColosseumApp().run()

if __name__ == "__main__":
    main()
