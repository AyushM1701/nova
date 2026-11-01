"""Send an event to the running Nova (used by watch.py and on_stop.py). Stdlib only.

Nova listens on 127.0.0.1:47821 and only accepts events carrying the key it wrote to data/events.key,
so a program that can't read that file can't make Nova speak or start anything. A program that can read it can also
start one of the user's skills by name: send({"event": "skill", "name": "content-cascade"}). Does nothing if Nova isn't
running."""
import json
import socket
import sys
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


if __name__ == "__main__":  # python notify.py skill morning-intel
    if len(sys.argv) != 3 or sys.argv[1] != "skill":
        sys.exit("usage: python notify.py skill <skill name>")
    send({"event": "skill", "name": sys.argv[2]})
