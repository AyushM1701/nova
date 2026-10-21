"""Nova on your phone: a small web page Nova serves on your home network (and over Tailscale), with the same live
conversation as the Nova window, a box to type in (or dictate with the phone keyboard's mic) and Allow / Deny.

Off until you turn it on in Settings → Phone. Only a phone that opened the pairing link (the QR code there) has the
key; anything else on the network gets the page but can't connect. The key travels in the link's #fragment, which
browsers never send to a server, and then only in the first message of the connection.
"""
import asyncio
import base64
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

from websockets.datastructures import Headers
from websockets.http11 import Response

from core.config import DATA, WORKSPACE, write_private

PORT = 47823
SIRI_WAIT_S = 50
DROP = WORKSPACE / "phone"  # what the phone sends: images and files, put on this computer's clipboard
MAX_UPLOAD = 25 * 2 ** 20
TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/heic": "heic", "image/heif": "heif", "image/gif": "gif",
         "image/webp": "webp", "application/pdf": "pdf", "text/plain": "txt"}
PAGE = Path(__file__).with_name("phone.html")
TOKEN = DATA / "phone-token"
# the page only talks to the Nova that served it; nothing loads from the internet
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self' ws: wss:; frame-ancestors 'none'")


def token(new=False):
    """The pairing key; new=True replaces it, so every paired phone has to scan again."""
    if new or not TOKEN.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        write_private(TOKEN, secrets.token_urlsafe(24))
    return TOKEN.read_text(encoding="utf-8").strip()


def addresses():
    """This computer's addresses a phone can reach: the home network's, then Tailscale's (100.64.0.0/10)."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # only picks the outgoing network; nothing is sent
            found.append(s.getsockname()[0])
    except OSError:
        pass
    for ip in _tailscale_ips():
        a, b = map(int, ip.split(".")[:2])
        if a == 100 and 64 <= b <= 127 and ip not in found:
            found.append(ip)
    return found


def _tailscale_ips():
    """This computer's Tailscale address, from the Tailscale app itself (Windows doesn't list it under the computer's
    name); else whatever the computer's name resolves to."""
    exe = shutil.which("tailscale") or next((p for p in (r"C:\Program Files\Tailscale\tailscale.exe",
                                                         "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
                                             if Path(p).exists()), None)
    if exe:
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5,
                                 creationflags=0x08000000 if os.name == "nt" else 0).stdout.split()
            if out:
                return out
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        return [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        return []


def save_upload(data_url, name="", folder=DROP, keep=30):
    """Write a file the phone sent (a data: URL) into workspace/phone and return its path. Only the newest `keep`
    stay; the phone's own file name is cleaned and only gives the name and extension."""
    m = re.match(r"data:([\w.+-]+/[\w.+-]+)?(?:;[^,;]*)*;base64,(.*)$", str(data_url), re.S)
    if not m:
        raise ValueError("That didn't arrive as a file. Try again.")
    raw = base64.b64decode(m.group(2))
    if len(raw) > MAX_UPLOAD:
        raise ValueError(f"That's {len(raw) >> 20} MB; Nova takes up to {MAX_UPLOAD >> 20} MB.")
    stem = re.sub(r"[^\w\- ]", "_", Path(str(name)).stem).strip()[:60] or "from-phone"
    ext = Path(str(name)).suffix.lstrip(".").lower()
    if not re.fullmatch(r"[a-z0-9]{1,8}", ext):
        ext = TYPES.get((m.group(1) or "").lower(), "bin")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}-{stem}.{ext}"
    path.write_bytes(raw)
    for old in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[keep:]:
        old.unlink(missing_ok=True)
    return path


def links():
    return [f"http://{ip}:{PORT}/#{token()}" for ip in addresses()]


def _icon():
    from core.icon import draw
    buf = io.BytesIO()
    draw(180).save(buf, "PNG")
    return buf.getvalue()


class Phone:
    """The phone page's server. Thread-safe: enable(), broadcast() and disconnect_all() work from any thread."""

    def __init__(self, on_msg):
        self.on_msg, self.clients, self.server, self.error = on_msg, set(), None, ""
        self.waiters = []  # Siri requests waiting for Nova's answer
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def enable(self, on):
        """Listen on the network (Settings → Phone on), or stop and drop every phone."""
        asyncio.run_coroutine_threadsafe(self._enable(bool(on)), self.loop)

    async def _enable(self, on):
        from websockets.asyncio.server import serve
        if on and not self.server:
            try:
                # room for a 25 MB photo or file from the phone (sent base64-encoded, a third bigger)
                self.server = await serve(self._client, "0.0.0.0", PORT, process_request=self._http,
                                          max_size=MAX_UPLOAD * 4 // 3 + 2 ** 16)
                self.error = ""
            except OSError as e:  # the port is taken: Settings shows why
                self.error = f"Port {PORT} is in use by another program ({e.strerror})."
        elif not on and self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    def _http(self, connection, request):
        path, _, query = request.path.partition("?")
        if path == "/ws":
            return None  # the live connection
        if path == "/ask":  # Siri: "Hey Siri, ask Nova" (a Shortcut opens this link and speaks what comes back)
            return self._ask(connection, urllib.parse.parse_qs(query))
        if path in ("/", "/index.html"):
            body, kind = PAGE.read_bytes(), "text/html; charset=utf-8"
        elif path in ("/icon.png", "/apple-touch-icon.png"):
            body, kind = _icon(), "image/png"
        else:
            return connection.respond(404, "Not found\n")
        return Response(200, "OK", Headers([("Content-Type", kind), ("Content-Length", str(len(body))),
                                            ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                                            ("Referrer-Policy", "no-referrer"), ("Content-Security-Policy", CSP)]), body)

    async def _ask(self, connection, query):
        """Run one request like a typed one and answer with the line to speak, once Nova replies."""
        if not secrets.compare_digest(query.get("key", [""])[0].encode(), token().encode()):  # bytes: any key is just wrong
            return connection.respond(401, "This Siri shortcut isn't paired with Nova. Set it up again from the Nova "
                                           "app on your phone.\n")
        text = query.get("text", [""])[0].strip()[:4000]
        if not text:
            return connection.respond(400, "Tell me what you'd like Nova to do.\n")
        future = self.loop.create_future()
        self.waiters.append(future)
        self._handle({"op": "ask", "text": text}, lambda msg: None)
        try:
            answer = await asyncio.wait_for(future, SIRI_WAIT_S)
        except asyncio.TimeoutError:  # Siri gives up on a link after about a minute
            answer = "Still working on it. The answer will be in the Nova app."
        finally:
            if future in self.waiters:
                self.waiters.remove(future)
        return connection.respond(200, answer + "\n")

    def _answered(self, text):
        for future in self.waiters:
            if not future.done():
                future.set_result(text)

    async def _client(self, ws):
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if not (isinstance(hello, dict) and secrets.compare_digest(str(hello.get("token", "")).encode(), token().encode())):
                return await ws.close(4001, "not paired")
            self.clients.add(ws)
            reply = lambda msg: self.send(ws, msg)  # noqa: E731
            self._handle({"op": "connected"}, reply)
            async for raw in ws:
                msg = json.loads(raw)
                if isinstance(msg, dict) and msg.get("op") == "ping":  # the page's heartbeat: it reconnects without one
                    await ws.send('{"type": "pong"}')
                elif isinstance(msg, dict):
                    self._handle(msg, reply)
        except Exception:  # a dropped connection or a bad message: the phone reconnects on its own
            pass
        finally:
            if ws in self.clients:
                self.clients.discard(ws)
                self._handle({"op": "connected"}, lambda msg: None)

    def _handle(self, msg, reply):
        threading.Thread(target=self.on_msg, args=(msg, reply), daemon=True).start()

    def send(self, ws, msg):
        asyncio.run_coroutine_threadsafe(ws.send(json.dumps(msg, default=str)), self.loop)

    def broadcast(self, event):
        # a Siri request waiting for its answer: the reply (its spoken line), or a note such as "It's 6:05 PM."
        # (only a request's own error: a background one, like a failed browser repair, isn't Siri's answer)
        if self.waiters and (event.get("event") in ("reply", "note") or event.get("event") == "error" and event.get("request")):
            text = event.get("say") or event.get("text") or event.get("reply") or event.get("error") or "Done."
            self.loop.call_soon_threadsafe(self._answered, str(text))
        for ws in list(self.clients):
            self.send(ws, {"type": "event", "event": event})

    def disconnect_all(self):
        """After a new pairing key: every phone has to scan the new QR code."""
        for ws in list(self.clients):
            asyncio.run_coroutine_threadsafe(ws.close(4001, "not paired"), self.loop)
