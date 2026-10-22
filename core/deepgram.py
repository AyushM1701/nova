"""Optional cloud speech recognition: Deepgram, streamed while you speak, so the text is ready the moment you stop.

Opt-in only. When chosen, what you say to Nova is sent to Deepgram (a paid service; new accounts get sign-up
credit). The key lives in data/deepgram.key, which the safety guard won't let the AI read, and travels in a
request header, never in a URL. If Deepgram can't be reached, Nova transcribes on this computer instead.
"""
import json
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
from websockets.sync.client import connect

from core.config import DATA

KEY_FILE = DATA / "deepgram.key"
LISTEN = "wss://api.deepgram.com/v1/listen"
FINISH_TIMEOUT_S = 8  # for the last results after you stop; past this Nova transcribes locally


def key():
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def check(api_key):
    """'' if Deepgram accepts the key, else what's wrong, in plain words."""
    req = urllib.request.Request("https://api.deepgram.com/v1/projects", headers={"Authorization": f"Token {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=20):
            return ""
    except urllib.error.HTTPError as e:
        return "Deepgram didn't accept that key." if e.code in (401, 403) else f"Deepgram answered with error {e.code}."
    except OSError:
        return "Couldn't reach Deepgram. Check your internet connection."


def query(language, vocabulary, model):
    """The listen URL's settings. "auto" is Deepgram's multilingual mode, which follows English/Hindi switches."""
    q = [("model", model or "nova-3"), ("encoding", "linear16"), ("sample_rate", "16000"), ("channels", "1"),
         ("smart_format", "true"), ("punctuate", "true"), ("language", "multi" if language == "auto" else language)]
    if language == "en":  # shortcut: key terms are sent for English only, until other languages are tried
        q += [("keyterm", w) for w in list(vocabulary)[:50]]
    return urllib.parse.urlencode(q)


def pcm(block):
    return (np.clip(block, -1, 1) * 32767).astype("<i2").tobytes()


class Stream:
    """One utterance. send() audio blocks while recording (it never waits on the network: blocks queue until the
    connection is up), then finish() for the text, or close() to drop it."""

    def __init__(self, api_key, language, vocabulary, model="nova-3"):
        self.url, self.headers = f"{LISTEN}?{query(language, vocabulary, model)}", {"Authorization": f"Token {api_key}"}
        self.blocks, self.parts, self.error = queue.Queue(), [], None
        self.dropped, self.done = threading.Event(), threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, block):
        self.blocks.put(block)

    def finish(self):
        self.blocks.put(None)
        if not self.done.wait(FINISH_TIMEOUT_S):
            self.close()
            raise TimeoutError("Deepgram didn't answer in time.")
        if self.error:
            raise self.error
        return " ".join(self.parts).strip()

    def close(self):
        self.dropped.set()
        self.blocks.put(None)

    def _run(self):
        try:
            with connect(self.url, additional_headers=self.headers, open_timeout=5) as ws:
                reader = threading.Thread(target=self._read, args=(ws,), daemon=True)
                reader.start()
                while (block := self.blocks.get()) is not None:
                    ws.send(pcm(block))
                if not self.dropped.is_set():
                    ws.send(json.dumps({"type": "CloseStream"}))  # Deepgram sends the last results, then closes
                    reader.join(FINISH_TIMEOUT_S)
        except Exception as e:
            self.error = self.error or e
        finally:
            self.done.set()

    def _read(self, ws):
        try:
            for message in ws:
                data = json.loads(message)
                if data.get("type") == "Results" and data.get("is_final"):
                    text = data["channel"]["alternatives"][0]["transcript"].strip()
                    if text:
                        self.parts.append(text)
        except Exception as e:
            if not self.dropped.is_set():
                self.error = self.error or e
