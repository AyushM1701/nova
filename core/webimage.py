"""The one picture a sketch note may show (core/sketchpad.py), fetched from a link the AI wrote.

That link can come from a web page, so this is the only thing between it and the user's network, and Nova's guard
never sees it (it happens in Nova, not through the AI's tools). So it is strict: https on port 443 to a named host,
the host's addresses all public (never the user's router, a laptop on the LAN or a cloud metadata address), the
connection pinned to the address that was checked, every redirect checked again, a size and time limit, an image
type, and only JPEG, PNG, WebP or GIF decoded, in memory. Nothing is written to disk and no cookies or Referer are
sent. (It connects by itself, so the system proxy setting doesn't apply.)"""
import http.client
import io
import ipaddress
import json
import socket
import ssl
import threading
import time
from urllib.parse import quote, urljoin, urlsplit

from PIL import Image

from core.config import log

MAX_BYTES = 2_500_000
DEADLINE_S = 3.0  # in all, for every redirect and the download
MAX_REDIRECTS = 3
MAX_PIXELS = 25_000_000  # checked from the header, before the picture is decoded
MAX_SIDE = 640  # kept at most this big
FORMATS = ["JPEG", "PNG", "WEBP", "GIF"]
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKI_IMAGE_HOSTS = ("upload.wikimedia.org", "thumb.wikimedia.org")  # a page's photo is only taken from these


def _public(ip):
    address = ipaddress.ip_address(ip.split("%")[0])
    if address.version == 6 and address.ipv4_mapped:  # ::ffff:127.0.0.1 is 127.0.0.1
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def _resolve(host):
    return sorted({info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})


def _request(host, ip, path, timeout):
    """GET `path` from `host`, connecting to `ip` itself so a second DNS answer can't change where it goes."""
    sock = socket.create_connection((ip, 443), timeout)
    conn = http.client.HTTPSConnection(host, 443, timeout=timeout)
    conn.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    conn.request("GET", path, headers={"Host": host, "User-Agent": "Nova/1 (desktop voice assistant; fetches one picture for a note)", "Accept-Encoding": "identity",
                                       "Accept": "image/jpeg,image/png,image/webp,image/gif", "Connection": "close"})
    return conn.getresponse()


def _resolved(resolve, host, seconds):
    """The host's addresses, but giving up after `seconds`: a name lookup has no timeout of its own."""
    box = []

    def look():
        try:
            box.append(resolve(host))
        except Exception as e:  # handed back to the caller
            box.append(e)
    thread = threading.Thread(target=look, daemon=True)
    thread.start()
    thread.join(max(0.1, seconds))
    if not box:
        raise ValueError("the name lookup took too long")
    if isinstance(box[0], Exception):
        raise box[0]
    return box[0]


def _check(url):
    """(host, path) of a link that is safe to ask for, or ValueError."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc:
        raise ValueError("not a plain https link")
    if (parts.port or 443) != 443:
        raise ValueError("not port 443")
    try:
        ipaddress.ip_address(parts.hostname)
    except ValueError:
        pass
    else:
        raise ValueError("an address, not a name")
    return parts.hostname.encode("idna").decode("ascii"), (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def _decode(body, max_pixels):
    image = Image.open(io.BytesIO(body), formats=FORMATS)  # raises for anything else, including SVG
    if image.width * image.height > max_pixels or min(image.size) < 16:
        raise ValueError("picture size")
    image = image.convert("RGB")  # the first frame only
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return image


def _download(url, accept, resolve, request, max_bytes, deadline):
    """The body at `url` (every check above applied to it and to each redirect), or ValueError / OSError.
    `accept(content_type)` says which kinds of answer are wanted."""
    for _ in range(MAX_REDIRECTS + 1):
        host, path = _check(url)
        ips = _resolved(resolve, host, deadline - time.monotonic())
        if not ips or not all(_public(ip) for ip in ips):
            raise ValueError("not a public address")
        response = request(host, ips[0], path, max(0.5, deadline - time.monotonic()))
        try:
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(f"https://{host}{path}", response.getheader("Location") or "")
                continue
            kind = (response.getheader("Content-Type") or "").lower()
            if response.status != 200 or not accept(kind):
                raise ValueError(f"not what was asked for ({response.status} {kind[:30]})")
            body = b""
            while chunk := response.read(65536):
                body += chunk
                if len(body) > max_bytes or time.monotonic() > deadline:
                    raise ValueError("too big or too slow")
        finally:
            response.close()
        return body
    raise ValueError("too many redirects")


def _image(url, resolve, request, max_bytes, deadline, max_pixels):
    """The picture at `url` as an RGB image, or ValueError (OSError for the network): every check on it and on each
    redirect. Nova only calls it with an address it read from Wikipedia's own answer (fetch_wikipedia)."""
    body = _download(url, lambda kind: kind.startswith("image/") and "svg" not in kind, resolve, request, max_bytes, deadline)
    return _decode(body, max_pixels)


def fetch_wikipedia(title, resolve=_resolve, request=_request, max_bytes=MAX_BYTES, deadline_s=DEADLINE_S,
                    max_pixels=MAX_PIXELS):
    """The lead photo of a Wikipedia page, found by Nova itself (the page summary's thumbnail), so the AI only has to
    name the page and never writes a link. The photo must come from Wikimedia's own image hosts."""
    deadline = time.monotonic() + deadline_s
    title = " ".join(title.split())
    if not title or len(title) > 100:
        raise ValueError("no page title")
    body = _download(WIKI_SUMMARY + quote(title.replace(" ", "_"), safe=""), lambda kind: kind.startswith("application/json"),
                     resolve, request, 200_000, deadline)
    source = ((json.loads(body).get("thumbnail") or {}).get("source")) or ""
    parts = urlsplit(source)
    if parts.scheme != "https" or parts.hostname not in WIKI_IMAGE_HOSTS:
        raise ValueError("the page has no photo")
    return _image(source, resolve, request, max_bytes, deadline, max_pixels)


def get(spec):
    """The picture for a note's `img` line, "wiki:<page title>": that page's lead photo. Never a link from the AI (it
    may have been copied from a web page). None (and a log line) on any failure: the note then shows without it."""
    try:
        if not spec.startswith("wiki:"):
            raise ValueError("only a Wikipedia page's photo")
        return fetch_wikipedia(spec[5:])
    except Exception as e:  # a bad link, the network, a refused host
        log("image", url=spec[:200], ok=False, error=repr(e)[:200])
        return None
