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

TIKTOK_UNIQUE_ID = "@altop_sw"

# Puerto estándar unificado para Snake Bot & Colosseum:
UDP_HOST = "127.0.0.1"
UDP_PORT = 8765

BOMB_TTL_MS = 5000

# ==============================
# LOGGING
# ==============================

logging.basicConfig(level=logging.INFO)

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
# HEARTBEAT TASK
# ==============================

async def heartbeat_loop():
    """Envía un ping periódico cada 2 segundos para que el HUD del juego muestre conexión activa."""
    while True:
        try:
            send_udp("PING", {"status": "connected", "user": TIKTOK_UNIQUE_ID})
        except Exception:
            pass
        await asyncio.sleep(2.0)

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
        print("🟢 ConnectEvent recibido — Conectado a TikTok LIVE")
        send_udp("UPDATE_DONOR", {"donor": f"LIVE: {TIKTOK_UNIQUE_ID}"})

    @client.on(GiftEvent)
    async def on_gift(event: GiftEvent):
        """
        Reglas:
        - Solo actuamos cuando streaking == False (evento final del streak).
        - repeat_count indica cuántas veces se repitió el mismo regalo en el streak.
        """
        try:
            gift_name_raw = getattr(event.gift, "name", None)
            sender = getattr(event.user, "nickname", "Fan")
            streaking = getattr(event, "streaking", None)
            repeat_count = getattr(event, "repeat_count", None)
            diamond_count = getattr(event.gift, "diamond_count", None) or 1

            print(f"[GIFT] from={sender} name={gift_name_raw} diamonds={diamond_count} streaking={streaking} repeat={repeat_count}")

            if streaking is True:
                return

            gift_name = norm_name(gift_name_raw)
            n = safe_int(repeat_count, default=1)

            # Notificar al donante en el juego
            send_udp("UPDATE_DONOR", {"donor": sender})

            # ----------------------------
            # 1) ROSE -> Bombas normales
            # ----------------------------
            if gift_name == "rose":
                print(f"🌹 ROSE confirmada de {sender} -> spawn {n} bomba(s)")
                send_udp("SPAWN_BOMB", {"count": n, "ttl_ms": BOMB_TTL_MS, "donor": sender})
                return

            # ----------------------------
            # 2) TIKTOK -> Comida extra
            # ----------------------------
            if gift_name == "tiktok":
                print(f"🍎 TIKTOK -> comida extra x{n} de {sender}")
                send_udp("SPAWN_EXTRA_FOOD", {"count": n, "donor": sender})
                return

            # ----------------------------
            # 3) GG -> Cambiar color de serpiente
            # ----------------------------
            if gift_name == "gg":
                print(f"🎨 GG -> cambiar color x{n} de {sender}")
                send_udp("SNAKE_COLOR_CYCLE", {"times": n, "donor": sender})
                return

            # ----------------------------
            # 4) FIREWORK -> Reset inmediato
            # ----------------------------
            if "firework" in gift_name:
                print(f"🎆 FIREWORK -> reset juego de {sender}")
                send_udp("RESET_GAME", {"donor": sender})
                return

            # ----------------------------
            # 5) CORAZÓN / CAP / DOUGHNUT -> Modo Éxtasis
            # ----------------------------
            if any(k in gift_name for k in ("heart", "corazon", "cap", "doughnut")):
                print(f"🌈 Regalo ÉXTASIS de {sender}")
                send_udp("ACTIVATE_EXTASIS", {"donor": sender})
                return

            # ----------------------------
            # 6) CORONA / DRAGÓN / LEÓN / GALAXY -> Modo Golden o Bomba Nuclear
            # ----------------------------
            if any(k in gift_name for k in ("crown", "dragon", "lion", "galaxy", "universe")):
                if "lion" in gift_name or "galaxy" in gift_name or "universe" in gift_name:
                    print(f"☢️ NUCLEAR BOMB desatada por {sender}!")
                    send_udp("SPAWN_NUCLEAR_BOMB", {"donor": sender})
                else:
                    print(f"✨ MODO GOLDEN activado por {sender}!")
                    send_udp("ACTIVATE_GOLDEN", {"donor": sender})
                return

            # ----------------------------
            # 7) Regalos por diamantes acumulados (fallback)
            # ----------------------------
            if diamond_count >= 100:
                print(f"💎 Mega regalo ({diamond_count} diamonds) -> Bomba Nuclear")
                send_udp("SPAWN_NUCLEAR_BOMB", {"donor": sender})
            elif diamond_count >= 10:
                print(f"⭐ Regalo intermedio ({diamond_count} diamonds) -> Modo Golden")
                send_udp("ACTIVATE_GOLDEN", {"donor": sender})
            else:
                # Fallback genérico: comida extra
                send_udp("SPAWN_EXTRA_FOOD", {"count": 1, "donor": sender})

        except Exception as e:
            print("[GIFT HANDLER ERROR]", repr(e))

    print("Iniciando tarea de latido UDP...")
    asyncio.create_task(heartbeat_loop())

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
