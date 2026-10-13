# tk.py
from __future__ import annotations

import asyncio
from typing import Optional

# TikTokLive
from TikTokLive import TikTokLiveClient
from TikTokLive.events import GiftEvent, ConnectEvent, DisconnectEvent

# Integración con el sistema del juego
from ex import EventBus
from game import GameEvent


class TikTokListener:
    """
    Listener de TikTok Live.
    Única responsabilidad:
    traducir eventos de TikTok -> GameEvent
    """

    def __init__(self, username: str, event_bus: EventBus):
        self.username = username.lstrip("@")
        self.event_bus = event_bus
        self.client = TikTokLiveClient(unique_id=self.username)

        # bindings
        self.client.on("connect")(self.on_connect)
        self.client.on("disconnect")(self.on_disconnect)
        self.client.on("gift")(self.on_gift)

    # =========================
    # Eventos base
    # =========================

    async def on_connect(self, event: ConnectEvent):
        print(f"[TikTok] Conectado a @{self.username}")

    async def on_disconnect(self, event: DisconnectEvent):
        print(f"[TikTok] Desconectado de @{self.username}")

    # =========================
    # Gifts
    # =========================

    async def on_gift(self, event: GiftEvent):
        """
        Traducción directa TikTok -> acciones del juego
        """
        gift_name = event.gift.name.lower()
        user = event.user.nickname if event.user else "anon"
        diamonds = event.gift.diamond_count

        print(f"[GIFT] {user} -> {event.gift.name} ({diamonds})")

        # =========================
        # Mapeo de gifts
        # =========================
        # Puedes cambiar esto libremente sin tocar el resto del sistema

        # 🌹 Rose -> bomba
        if "rose" in gift_name:
            self.event_bus.emit(GameEvent(
                "SPAWN_BOMB",
                {"count": 1, "ttl_ms": 5000}
            ))
            print(" -> acción: SPAWN_BOMB")

        # 🍎 TikTok (logo) -> comida extra
        elif "tiktok" in gift_name:
            self.event_bus.emit(GameEvent(
                "SPAWN_EXTRA_FOOD",
                {"max_extra": 1}
            ))
            print(" -> acción: SPAWN_EXTRA_FOOD")

        # 🎨 GG -> cambiar color
        elif "gg" in gift_name:
            self.event_bus.emit(GameEvent(
                "CHANGE_SNAKE_COLOR",
                {}
            ))
            print(" -> acción: CHANGE_SNAKE_COLOR")

        # 🚀 Firework -> restart limpio
        elif "firework" in gift_name:
            self.event_bus.emit(GameEvent(
                "RESTART",
                {}
            ))
            print(" -> acción: RESTART")

        # ⚡ velocidad
        elif "heart" in gift_name:
            self.event_bus.emit(GameEvent(
                "SPEED_UP",
                {"delta": 1}
            ))
            print(" -> acción: SPEED_UP")

        # default (debug)
        else:
            print(" -> acción: ninguna asignada")

    # =========================
    # Loop
    # =========================

    def run(self):
        print(f"[TikTok] Listener iniciado para @{self.username}")
        asyncio.run(self.client.start())


# =========================
# Standalone run
# =========================

if __name__ == "__main__":
    # modo test independiente
    bus = EventBus()
    listener = TikTokListener(username="tu_usuario_tiktok", event_bus=bus)
    listener.run()
