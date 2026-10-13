# send_test.py
import json, socket

def send(ev_type, payload=None):
    msg = {"type": ev_type, "payload": payload or {}}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(json.dumps(msg).encode("utf-8"), ("127.0.0.1", 8765))
    sock.close()

send("CHANGE_SNAKE_COLOR")
send("SPAWN_BOMB", {"count": 5, "ttl_ms": 5000})
send("SPAWN_EXTRA_FOOD", {"max_extra": 2})
send("SPEED_UP", {"delta": 1})
