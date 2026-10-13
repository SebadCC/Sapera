# ex.py
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Protocol

import pygame  # type: ignore

from game import GameConfig, GameState


# =========================
# EventBus
# =========================

@dataclass(frozen=True, slots=True)
class GameEvent:
    type: str
    payload: Dict[str, Any] | None = None


class EventBus:
    def __init__(self) -> None:
        self._q: Deque[GameEvent] = deque()

    def emit(self, ev: GameEvent) -> None:
        self._q.append(ev)

    def drain(self) -> List[GameEvent]:
        out: List[GameEvent] = []
        while self._q:
            out.append(self._q.popleft())
        return out


# =========================
# Actions
# =========================

class IGameAction(Protocol):
    def apply(self, state: GameState, cfg: GameConfig, rng, now_ms: int) -> None:
        ...


class SpawnBombAction:
    def __init__(self, count: int, ttl_ms: int):
        self.count = max(1, int(count))
        self.ttl_ms = max(200, int(ttl_ms))

    def apply(self, state: GameState, cfg: GameConfig, rng, now_ms: int) -> None:
        from game import random_free_cell  # local import para evitar ciclos
        for _ in range(self.count):
            p = random_free_cell(state, cfg, rng)
            if p is None:
                break
            state.bombs[p] = now_ms + self.ttl_ms


class SpawnExtraFoodAction:
    def __init__(self, max_extra: int):
        self.max_extra = max(0, int(max_extra))

    def apply(self, state: GameState, cfg: GameConfig, rng, now_ms: int) -> None:
        from game import Food, random_free_cell  # local import para evitar ciclos

        extras = [f for f in state.foods if not f.respawn]
        if len(extras) >= self.max_extra:
            return

        p = random_free_cell(state, cfg, rng)
        if p is None:
            return
        state.foods.append(Food(pos=p, respawn=False))


class SpeedUpAction:
    def __init__(self, delta: int):
        self.delta = int(delta)

    def apply(self, state: GameState, cfg: GameConfig, rng, now_ms: int) -> None:
        cfg.fps = min(60, cfg.fps + self.delta)


class SlowDownAction:
    def __init__(self, delta: int):
        self.delta = int(delta)

    def apply(self, state: GameState, cfg: GameConfig, rng, now_ms: int) -> None:
        cfg.fps = max(1, cfg.fps - self.delta)


class ChangeSnakeColorAction:
    def apply(self, state: GameState, cfg: GameConfig, rng, now_ms: int) -> None:
        state.snake_color_index = (state.snake_color_index + 1) % 8


class ActionSystem:
    """
    Registro O/C: agrega nuevos eventos/actions sin tocar el engine.
    """
    def __init__(
        self,
        *,
        bomb_spawn_count: int,
        bomb_duration_ms: int,
        max_extra_foods_simultaneous: int,
    ):
        self._bomb_spawn_count = int(bomb_spawn_count)
        self._bomb_duration_ms = int(bomb_duration_ms)
        self._max_extra_foods = int(max_extra_foods_simultaneous)

        self.registry = {
            "SPAWN_BOMB": lambda ev: SpawnBombAction(
                count=int((ev.payload or {}).get("count", self._bomb_spawn_count)),
                ttl_ms=int((ev.payload or {}).get("ttl_ms", self._bomb_duration_ms)),
            ),
            "SPAWN_EXTRA_FOOD": lambda ev: SpawnExtraFoodAction(
                max_extra=int((ev.payload or {}).get("max_extra", self._max_extra_foods)),
            ),
            "SPEED_UP": lambda ev: SpeedUpAction(delta=int((ev.payload or {}).get("delta", 1))),
            "SLOW_DOWN": lambda ev: SlowDownAction(delta=int((ev.payload or {}).get("delta", 1))),
            "CHANGE_SNAKE_COLOR": lambda ev: ChangeSnakeColorAction(),
        }

    def dispatch(self, events: List[GameEvent], state: GameState, cfg: GameConfig, rng, now_ms: int) -> None:
        for ev in events:
            factory = self.registry.get(ev.type)
            if factory is None:
                continue
            action: IGameAction = factory(ev)
            action.apply(state, cfg, rng, now_ms)


# =========================
# External Input Controller
# =========================

class ExternalInputController:
    """
    Teclado -> GameEvents.
    Mantiene bindings de tu 1.16.
    """
    def __init__(
        self,
        event_bus: EventBus,
        *,
        bomb_spawn_count: int,
        bomb_duration_ms: int,
        max_extra_foods_simultaneous: int,
    ):
        self.event_bus = event_bus
        self._bomb_spawn_count = int(bomb_spawn_count)
        self._bomb_duration_ms = int(bomb_duration_ms)
        self._max_extra_foods = int(max_extra_foods_simultaneous)

    def handle_keydown(self, key: int) -> None:
        if key == pygame.K_j:
            self.event_bus.emit(GameEvent("SPEED_UP", {"delta": 1}))
        if key == pygame.K_l:
            self.event_bus.emit(GameEvent("SLOW_DOWN", {"delta": 1}))
        if key == pygame.K_x:
            self.event_bus.emit(
                GameEvent(
                    "SPAWN_BOMB",
                    {"count": self._bomb_spawn_count, "ttl_ms": self._bomb_duration_ms},
                )
            )
        if key == pygame.K_z:
            self.event_bus.emit(
                GameEvent(
                    "SPAWN_EXTRA_FOOD",
                    {"max_extra": self._max_extra_foods},
                )
            )
        if key == pygame.K_c:
            self.event_bus.emit(GameEvent("CHANGE_SNAKE_COLOR"))
