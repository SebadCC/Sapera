# ============================================================
# events.py — Receptor UDP, Bus de Eventos y Sistema de Acciones
# ============================================================

import socket
import json
import pygame
from collections import deque
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from config import (
    UDP_HOST, UDP_PORT, BOMB_DURATION_MS, EXTASIS_DURATION_MS,
    GOLDEN_DURATION_MS, WRAP_EVENT_DURATION_MS
)
from models import Point, Food, SnakeMode, NuclearStrike, ColosseumState

@dataclass(frozen=True, slots=True)
class GameEvent:
    type: str
    payload: Dict[str, Any] | None = None

class EventBus:
    def __init__(self):
        self._q: deque[GameEvent] = deque()

    def emit(self, ev: GameEvent) -> None:
        self._q.append(ev)

    def drain(self) -> List[GameEvent]:
        out = []
        while self._q:
            out.append(self._q.popleft())
        return out

class UDPReceiver:
    def __init__(self, host: str = UDP_HOST, port: int = UDP_PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.is_bound = False
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((host, port))
            self.sock.setblocking(False)
            self.is_bound = True
        except OSError:
            self.is_bound = False

    def poll(self, bus: EventBus) -> None:
        if not self.is_bound: return
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
                msg = json.loads(data.decode("utf-8"))
                if isinstance(msg, dict):
                    t = str(msg.get("type", "")).strip()
                    payload = msg.get("payload", {})
                    if t:
                        bus.emit(GameEvent(t, payload if isinstance(payload, dict) else {}))
            except (BlockingIOError, Exception):
                break

class ActionSystem:
    def __init__(self, app_or_rules: Any):
        self.target = app_or_rules

    def dispatch(self, events: List[GameEvent], state: ColosseumState, now_ms: int) -> None:
        for ev in events:
            t = ev.type
            payload = ev.payload or {}
            donor = payload.get("donor") or payload.get("sender") or payload.get("user")
            if donor:
                state.last_donor = str(donor).strip()
            state.last_udp_ms = now_ms

            if t == "PING":
                pass

            elif t == "SPAWN_BOMB":
                count = max(1, int(payload.get("count", 1)))
                ttl = max(1000, int(payload.get("ttl_ms", BOMB_DURATION_MS)))
                for _ in range(count):
                    p = self._random_free_cell(state)
                    if p: state.bombs[p] = now_ms + ttl

            # Manzana Dorada (Respawnable) — TECLA Z
            elif t == "SPAWN_GOLDEN_FOOD":
                count = max(1, int(payload.get("count", 1)))
                for _ in range(count):
                    p = self._random_free_cell(state)
                    if p: state.foods.append(Food(pos=p, value=1, golden=True))

            # Manzana Normal (Roja-Verde, consumible no respawneable) — TECLA C
            elif t in ("SPAWN_NORMAL_FOOD", "SPAWN_EXTRA_FOOD"):
                count = max(1, int(payload.get("count", 1)))
                for _ in range(count):
                    p = self._random_free_cell(state)
                    if p: state.foods.append(Food(pos=p, value=1, golden=False))

            # Eliminar Manzana Dorada — TECLA V
            elif t == "REMOVE_GOLDEN_FOOD":
                golden_idx = next((i for i, f in enumerate(state.foods) if f.golden), None)
                if golden_idx is not None:
                    state.foods.pop(golden_idx)

            elif t == "WRAP_TOGGLE":
                state.wall_collision = not state.wall_collision
                if not state.wall_collision:
                    state.wrap_mode_until_ms = now_ms + WRAP_EVENT_DURATION_MS
                else:
                    state.wrap_mode_until_ms = 0

            elif t == "SLOW_DOWN":
                delta = int(payload.get("delta", 2))
                state.fps_base = max(4, state.fps_base - delta)

            elif t == "SPEED_UP":
                delta = int(payload.get("delta", 2))
                state.fps_base = min(60, state.fps_base + delta)

            elif t in ("EXTASIS", "ACTIVATE_EXTASIS"):
                target_f = str(payload.get("faction", "")).upper()
                for s in state.snakes:
                    if not target_f or s.faction.faction_id.value == target_f:
                        s.mode = SnakeMode.EXTASIS
                        s.mode_until_ms = now_ms + EXTASIS_DURATION_MS

            elif t in ("GOLDEN_MODE", "ACTIVATE_GOLDEN"):
                target_f = str(payload.get("faction", "")).upper()
                for s in state.snakes:
                    if not target_f or s.faction.faction_id.value == target_f:
                        s.mode = SnakeMode.GOLDEN
                        s.mode_until_ms = now_ms + GOLDEN_DURATION_MS

            elif t == "SPAWN_NUCLEAR_BOMB":
                if state.nuclear is None or state.nuclear.state == "FINISHED":
                    center = Point(state.grid_size // 2, state.grid_size // 2)
                    blast_r = max(5, int(state.grid_size * 0.35))
                    state.nuclear = NuclearStrike(
                        center=center, state="FALLING", start_ms=now_ms, fall_y=-180.0,
                        blast_radius=blast_r, fall_duration_ms=900
                    )

    def _random_free_cell(self, state: ColosseumState) -> Optional[Point]:
        if hasattr(self.target, "random_free_cell"):
            return self.target.random_free_cell(state)
        occupied = set(state.bombs.keys()) | {f.pos for f in state.foods}
        for s in state.snakes: occupied |= set(s.body)
        free = [Point(x, y) for y in range(state.grid_size) for x in range(state.grid_size) if Point(x, y) not in occupied]
        return random.choice(free) if free else None

class ExternalInputController:
    def __init__(self, bus: EventBus):
        self.bus = bus

    def handle_keydown(self, key: int) -> None:
        if key == pygame.K_z:
            # Spawnear Manzana Dorada (respawnable continua)
            self.bus.emit(GameEvent("SPAWN_GOLDEN_FOOD"))
        elif key == pygame.K_c:
            # Spawnear Manzana Normal (roja-verde, consumible no respawneable)
            self.bus.emit(GameEvent("SPAWN_NORMAL_FOOD"))
        elif key == pygame.K_v:
            # Eliminar una Manzana Dorada del tablero
            self.bus.emit(GameEvent("REMOVE_GOLDEN_FOOD"))
        elif key == pygame.K_x:
            self.bus.emit(GameEvent("SPAWN_BOMB"))
        elif key == pygame.K_b:
            self.bus.emit(GameEvent("SPAWN_NUCLEAR_BOMB"))
        elif key == pygame.K_w:
            self.bus.emit(GameEvent("WRAP_TOGGLE"))
        elif key == pygame.K_e:
            self.bus.emit(GameEvent("EXTASIS"))
        elif key == pygame.K_g:
            self.bus.emit(GameEvent("GOLDEN_MODE"))
        elif key == pygame.K_j:
            self.bus.emit(GameEvent("SLOW_DOWN", {"delta": 2}))
        elif key == pygame.K_l:
            self.bus.emit(GameEvent("SPEED_UP", {"delta": 2}))
        elif key == pygame.K_k:
            self.bus.emit(GameEvent("PAUSE_TOGGLE"))

