"""Send an event to the running Nova (used by watch.py and on_stop.py). Stdlib only.

Nova listens on 127.0.0.1:47821 and only accepts events carrying the key it wrote to data/events.key,
so another program can't make Nova speak or start AI requests. Does nothing if Nova isn't running."""
import json
import socket
from pathlib import Path

KEY = Path(__file__).resolve().parents[1] / "data" / "events.key"


def send(event):
    try:
        payload = json.dumps({"key": KEY.read_text(encoding="utf-8").strip(), **event}).encode("utf-8")
        with socket.create_connection(("127.0.0.1", 47821), timeout=3) as s:
            s.sendall(payload)
            s.shutdown(socket.SHUT_WR)
    except OSError:
        pass  # Nova not running: the command or Claude still finished normally
