"""Nova on your phone: a small web page Nova serves on your home network (and over Tailscale), with the same live
conversation as the Nova window, a box to type in (or dictate with the phone keyboard's mic) and Allow / Deny.

Off until you turn it on in Settings → Phone. Only a phone that opened the pairing link (the QR code there) has the
key; anything else on the network gets the page but can't connect. The key travels in the link's #fragment, which
browsers never send to a server, and then only in the first message of the connection.

That message isn't encrypted on Wi-Fi, so Phone listens on the home network only on the network it was turned on in
(known by its router). On any other Wi-Fi (a café, a hotel) only Tailscale, which is encrypted, still works.
"""
import asyncio
import base64
import io
import json
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from websockets.datastructures import Headers
from websockets.http11 import Response

from core.config import DATA, NO_WINDOW, WORKSPACE, write_private

PORT = 47823
SIRI_WAIT_S = 50
DROP = WORKSPACE / "phone"  # what the phone sends: images and files, put on this computer's clipboard
MAX_UPLOAD = 25 * 2 ** 20
TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/heic": "heic", "image/heif": "heif", "image/gif": "gif",
         "image/webp": "webp", "application/pdf": "pdf", "text/plain": "txt"}
PAGE = Path(__file__).with_name("phone.html")
TOKEN = DATA / "phone-token"
NETWORK = DATA / "phone-network"  # the router of the network Phone was turned on in
CHECK_S = 30  # how often Phone checks which network this computer is on
PAUSED = ("Phone is paused on this Wi-Fi: it isn't the network you turned Phone on in, and anyone on it could "
          "read the pairing key. Tailscale still works. To use Phone here, turn it off and on again.")
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
    return found + [ip for ip in _tailscale_ips() if _tailscale(ip) and ip not in found]


def _tailscale(ip):
    a, b = map(int, ip.split(".")[:2])
    return a == 100 and 64 <= b <= 127


def router():
    """The network this computer is on, known by its router's hardware address ('' if it can't be told)."""
    try:
        if sys.platform == "darwin":
            gateway = re.search(r"gateway: (\S+)", subprocess.run(["route", "-n", "get", "default"],
                                capture_output=True, text=True, timeout=5).stdout).group(1)
            return re.search(r" at ([0-9a-f:]+)", subprocess.run(["arp", "-n", gateway], capture_output=True,
                             text=True, timeout=5).stdout).group(1)
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "$r = Get-NetRoute -DestinationPrefix 0.0.0.0/0 | Sort-Object RouteMetric | "
                              "Select-Object -First 1; (Get-NetNeighbor -IPAddress $r.NextHop -InterfaceIndex "
                              "$r.ifIndex).LinkLayerAddress"], capture_output=True, text=True, timeout=10,
                             creationflags=NO_WINDOW).stdout.split()
        return out[0].lower() if out else ""
    except (OSError, AttributeError, subprocess.SubprocessError):
        return ""


def hosts():
    """Where Phone listens, and why it's paused ('' if it isn't): everywhere on the network it was turned on in,
    else only on Tailscale."""
    now = router()
    try:
        home = NETWORK.read_text(encoding="utf-8").strip()
    except OSError:
        home = ""
    if not home and now:  # Phone was on before Nova knew networks: this one is home
        NETWORK.write_text(now, encoding="utf-8")
        home = now
    if not home or now == home:  # shortcut: no router found either time (wired with no ARP entry), trust it
        return ["0.0.0.0"], ""
    return [ip for ip in _tailscale_ips() if _tailscale(ip)] or ["127.0.0.1"], PAUSED


def _tailscale_ips():
    """This computer's Tailscale address, from the Tailscale app itself (Windows doesn't list it under the computer's
    name); else whatever the computer's name resolves to."""
    exe = shutil.which("tailscale") or next((p for p in (r"C:\Program Files\Tailscale\tailscale.exe",
                                                         "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
                                             if Path(p).exists()), None)
    if exe:
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5,
                                 creationflags=NO_WINDOW).stdout.split()
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


def page(path):
    """An HTML page (this phone page, or the Nova window) with the shared reply formatter, core/md.js, put in."""
    md = Path(__file__).with_name("md.js").read_text(encoding="utf-8")
    return path.read_text(encoding="utf-8").replace("<!-- md.js -->", f"<script>{md}</script>", 1)


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
        self.on, self.hosts, self.watching = False, None, False
        self.lock = asyncio.Lock()
        self.waiters = []  # Siri requests waiting for Nova's answer
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def enable(self, on, here=False):
        """Listen on the network (Settings → Phone on), or stop and drop every phone. `here`: the user just turned
        Phone on, so this network is the one to trust."""
        if on and here:
            DATA.mkdir(parents=True, exist_ok=True)
            NETWORK.write_text(router(), encoding="utf-8")
        asyncio.run_coroutine_threadsafe(self._enable(bool(on)), self.loop)

    async def _enable(self, on):
        self.on = on
        await self._listen()
        if on and not self.watching:  # moved to another Wi-Fi (or back home): listen where it's safe
            self.watching = True
            while self.on:
                await asyncio.sleep(CHECK_S)
                if self.on:
                    await self._listen()
            self.watching = False

    async def _listen(self):
        async with self.lock:  # the network check and a Settings toggle never start two servers
            await self._relisten()

    async def _relisten(self):
        from websockets.asyncio.server import serve
        where, why = await self.loop.run_in_executor(None, hosts) if self.on else (None, "")
        if where == self.hosts and (self.server or not self.on):
            return
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        self.hosts, self.error = where, why
        if self.on:
            try:
                # room for a 25 MB photo or file from the phone (sent base64-encoded, a third bigger)
                self.server = await serve(self._client, where, PORT, process_request=self._http,
                                          max_size=MAX_UPLOAD * 4 // 3 + 2 ** 16)
            except OSError as e:  # the port is taken: Settings shows why
                self.error = f"Port {PORT} is in use by another program ({e.strerror})."

    def _http(self, connection, request):
        path, _, query = request.path.partition("?")
        if path == "/ws":
            return None  # the live connection
        if path == "/ask":  # Siri: "Hey Siri, ask Nova" (a Shortcut opens this link and speaks what comes back)
            return self._ask(connection, urllib.parse.parse_qs(query))
        if path in ("/", "/index.html"):
            body, kind = page(PAGE).encode("utf-8"), "text/html; charset=utf-8"
        elif path in ("/icon.png", "/apple-touch-icon.png"):
            body, kind = _icon(), "image/png"
        else:
            return connection.respond(404, "Not found\n")
        # websockets hangs up after every plain HTTP response; without saying so, Safari keeps the socket and its
        # reload goes down the dead one ("the network connection was lost")
        return Response(200, "OK", Headers([("Connection", "close"), ("Content-Type", kind),
                                            ("Content-Length", str(len(body))), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
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
