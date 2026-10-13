import asyncio
import json
import socket
import sys
import logging

from TikTokLive import TikTokLiveClient
from TikTokLive.events import GiftEvent, ConnectEvent

# ==============================
# CONFIG
# ==============================

TIKTOK_UNIQUE_ID = "@ventabrainrot7777"
UDP_HOST = "127.0.0.1"
UDP_PORT = 8765

# TTL default para bombas (ms)
BOMB_TTL_MS = 5000

# ==============================
# LOGGING
# ==============================

logging.basicConfig(level=logging.DEBUG)

# ==============================
# UDP sender
# ==============================

def send_udp(ev_type: str, payload: dict | None = None) -> None:
    try:
        msg = {"type": ev_type, "payload": payload or {}}
        data = json.dumps(msg).encode("utf-8")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(data, (UDP_HOST, UDP_PORT))
        sock.close()
        print(f"[UDP] Sent -> {ev_type} {payload}")
    except Exception as e:
        print("[UDP ERROR]", repr(e))

# ==============================
# HELPERS
# ==============================

def norm_name(x) -> str:
    return (x or "").strip().lower()

def safe_int(x, default=1) -> int:
    try:
        v = int(x)
        return v if v > 0 else default
    except Exception:
        return default

# ==============================
# MAIN
# ==============================

async def main():
    print("===================================")
    print(" TikTok Listener iniciado")
    print(" Usuario:", TIKTOK_UNIQUE_ID)
    print(" UDP:", UDP_HOST, UDP_PORT)
    print("===================================")

    client = TikTokLiveClient(unique_id=TIKTOK_UNIQUE_ID)

    @client.on(ConnectEvent)
    async def on_connect(event: ConnectEvent):
        print("🟢 ConnectEvent recibido")

    @client.on(GiftEvent)
    async def on_gift(event: GiftEvent):
        """
        Reglas:
        - Solo actuamos cuando streaking == False (evento final del streak).
        - repeat_count indica cuántas veces se repitió el mismo regalo en el streak.
        """

        try:
            gift_name_raw = getattr(event.gift, "name", None)
            sender = getattr(event.user, "nickname", "unknown")

            streaking = getattr(event, "streaking", None)       # True mientras repite, False al final
            repeat_count = getattr(event, "repeat_count", None) # puede ser 1,2,3...
            diamond_count = getattr(event.gift, "diamond_count", None)

            print(f"[GIFT] from={sender} name={gift_name_raw} diamonds={diamond_count} streaking={streaking} repeat={repeat_count}")

            # Si viene streaking=True, aún no ejecutamos (esperamos el final)
            if streaking is True:
                return

            gift_name = norm_name(gift_name_raw)
            n = safe_int(repeat_count, default=1)

            # ----------------------------
            # 1) ROSE -> n bombas
            # ----------------------------
            if gift_name == "rose":
                print(f"🌹 ROSE confirmada -> spawn {n} bomba(s)")
                send_udp("SPAWN_BOMB", {"count": n, "ttl_ms": BOMB_TTL_MS})
                return

            # ----------------------------
            # 2) GG -> cambiar color serpiente
            # ----------------------------
            if gift_name == "gg":
                print("🎨 GG -> cambiar color serpiente")
                send_udp("SNAKE_COLOR_CYCLE", {"times": n})
                return

            # ----------------------------
            # 3) FIREWORK -> restablecer / reset
            #    (tu caso mostró 'Wave Firework', así que usamos contains)
            # ----------------------------
            if "firework" in gift_name:
                print("🎆 FIREWORK -> reset/restablecer juego")
                send_udp("RESET_GAME", {"times": n})
                return

            # ----------------------------
            # 4) TIKTOK -> generar comida extra
            # ----------------------------
            if gift_name == "tiktok":
                print("🍎 TIKTOK -> comida extra")
                send_udp("SPAWN_EXTRA_FOOD", {"count": n})
                return

        except Exception as e:
            print("[GIFT HANDLER ERROR]", repr(e))

    print("Intentando conectar a TikTok LIVE...")

    try:
        await client.start()
        print("⚠️ client.start() retornó. Manteniendo el proceso vivo...")
        while True:
            await asyncio.sleep(3600)

    except Exception as e:
        print("❌ ERROR en client.start():", repr(e))
        sys.exit(1)

# ==============================
# ENTRYPOINT
# ==============================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nListener detenido por usuario")
