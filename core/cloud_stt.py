"""Speech recognition with your own cloud API key: OpenAI, Groq, Mistral, or any server that speaks OpenAI's
/audio/transcriptions API (Ollama bridges, LocalAI, a self-hosted Whisper). Opt-in: what you say to Nova is sent
to that provider under your own account and their privacy policy. Keys live in data/stt-<provider>.key, which the
safety guard won't let the AI read, and travel in a request header.
"""
import http.client
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from core import vault
from core.config import DATA
from core.whisper_cpp import multipart, wav

# provider: (transcriptions URL, default model, where to get a key)
PROVIDERS = {
    "openai": ("https://api.openai.com/v1/audio/transcriptions", "gpt-4o-mini-transcribe",
               "https://platform.openai.com/api-keys"),
    "groq": ("https://api.groq.com/openai/v1/audio/transcriptions", "whisper-large-v3-turbo",
             "https://console.groq.com/keys"),
    "mistral": ("https://api.mistral.ai/v1/audio/transcriptions", "voxtral-mini-latest",
                "https://console.mistral.ai/api-keys"),
    "custom": ("", "whisper-1", ""),
}
# one kept-open connection per service (from Clicky): the TLS handshake happens while you speak, not after
_pool, _pool_lock = {}, threading.Lock()
DROPPED = (http.client.RemoteDisconnected, http.client.CannotSendRequest, ConnectionResetError,
           ConnectionAbortedError, BrokenPipeError)  # the service closed an idle connection: open a new one


def key_file(provider):
    return DATA / ("deepgram.key" if provider == "deepgram" else f"stt-{provider}.key")


def key(provider):
    return vault.read(key_file(provider))  # the OS's credential store; a key file from before is moved there


def check(provider, api_key, url=""):
    """'' if the provider accepts the key, else what's wrong, in plain words."""
    base = (url or PROVIDERS[provider][0]).rsplit("/audio/", 1)[0]
    req = urllib.request.Request(f"{base}/models", headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=20):
            return ""
    except urllib.error.HTTPError as e:
        return "That key wasn't accepted." if e.code in (401, 403) else f"The service answered with error {e.code}."
    except (OSError, ValueError):
        return "Couldn't reach the service. Check the address and your internet connection."


def _slot(url):
    """(parts of url, [its kept-open connection or None, a lock so one request uses it at a time])."""
    u = urllib.parse.urlsplit(url)
    with _pool_lock:
        return u, _pool.setdefault((u.scheme, u.netloc), [None, threading.Lock()])


def _open(u):
    return (http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection)(u.netloc, timeout=120)


def warm(url):
    """Open a fresh connection to the service now (Nova calls this as you start speaking), so transcribing when
    you stop skips the handshake. Errors are left for the real request to report."""
    u, slot = _slot(url)
    if not slot[1].acquire(blocking=False):  # in use right now: it's already open
        return
    try:
        if slot[0]:
            slot[0].close()  # one left from earlier may have been dropped by the service while idle
        slot[0] = _open(u)
        slot[0].connect()
    except OSError:
        slot[0] = None
    finally:
        slot[1].release()


def post(url, body, headers):
    """(status, response bytes) over the kept-open connection, or a connection of its own while that one is
    busy (a meeting being transcribed)."""
    u, slot = _slot(url)
    path = u.path + (f"?{u.query}" if u.query else "")

    def send(conn):
        conn.request("POST", path, body, headers)
        r = conn.getresponse()
        return r.status, r.read()
    if not slot[1].acquire(blocking=False):
        conn = _open(u)
        try:
            return send(conn)
        finally:
            conn.close()
    try:
        for retry in (False, True):
            slot[0] = slot[0] or _open(u)
            try:
                return send(slot[0])
            except DROPPED:
                slot[0].close()
                slot[0] = None
                if retry:
                    raise
    except BaseException:
        if slot[0]:  # a timeout or half-read reply leaves it unusable
            slot[0].close()
            slot[0] = None
        raise
    finally:
        slot[1].release()


class Cloud:
    """Same interface as whisper_cpp.Server: transcribe(audio, language, prompt) -> text."""

    def __init__(self, provider, api_key, url="", model=""):
        default_url, default_model, _ = PROVIDERS[provider]
        self.url, self.model, self.api_key = url or default_url, model or default_model, api_key
        if not self.url:
            raise RuntimeError("Set the server address for the custom speech service in Nova's settings, Voice.")
        if not api_key and provider != "custom":  # a local OpenAI-compatible server may need no key
            raise RuntimeError(f"Add your {provider.title()} key in Nova's settings, Voice.")

    def transcribe(self, audio, language, prompt):
        fields = {"model": self.model, "response_format": "json"}
        if language:
            fields["language"] = language
        if prompt:
            fields["prompt"] = prompt
        body, kind = multipart(fields, "speech.wav", wav(audio))
        headers = {"Content-Type": kind, **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})}
        status, data = post(self.url, body, headers)
        if status >= 400:
            detail = data.decode("utf-8", "replace")[:200]
            raise RuntimeError(f"The speech service answered with error {status}: {detail}")
        return " ".join(json.loads(data.decode("utf-8")).get("text", "").split())
