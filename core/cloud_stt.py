"""Speech recognition with your own cloud API key: OpenAI, Groq, Mistral, or any server that speaks OpenAI's
/audio/transcriptions API (Ollama bridges, LocalAI, a self-hosted Whisper). Opt-in: what you say to Nova is sent
to that provider under your own account and their privacy policy. Keys live in data/stt-<provider>.key, which the
safety guard won't let the AI read, and travel in a request header.
"""
import json
import urllib.error
import urllib.request

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


def key_file(provider):
    return DATA / ("deepgram.key" if provider == "deepgram" else f"stt-{provider}.key")


def key(provider):
    try:
        return key_file(provider).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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
        req = urllib.request.Request(self.url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return " ".join(json.loads(r.read().decode("utf-8")).get("text", "").split())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"The speech service answered with error {e.code}: {detail}") from None
