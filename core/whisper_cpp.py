"""Optional speech engine: a whisper.cpp server (whisper-server) on this computer, used instead of faster-whisper
for what you say to Nova. Nova starts it on first use with the program and ggml model chosen in settings, talks
to it on 127.0.0.1 only, and stops it when Nova quits. "Hey Nova" and spoken "allow / deny" still use faster-whisper.
"""
import io
import json
import socket
import subprocess
import threading
import time
import urllib.request
import uuid

from core import procs
import wave
from pathlib import Path

import numpy as np

from core.config import NO_WINDOW

# OpenWhispr's decoder thresholds: over 4,814 real dictations they cut Whisper's made-up endings
# ("Thank you for watching") from 2.25% to 0.06%. whisper.cpp's defaults are 2.4 and -1.0.
DECODER = {"entropy_thold": "2.8", "logprob_thold": "-1.25"}
START_TIMEOUT_S = 90  # a large model on a slow disk takes a while to load


def wav(audio, rate=16000):
    """16 kHz float32 samples as a 16-bit mono WAV file."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def multipart(fields, filename, data):
    """A multipart/form-data body: (bytes, content type)."""
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f"Content-Type: audio/wav\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, binary, model):
        self.binary, self.model = binary, model
        self.proc, self.port, self.lock = None, None, threading.Lock()

    def start(self):
        """Start whisper-server if it isn't running. Raises RuntimeError in plain words when it can't."""
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
            for path, what in ((self.binary, "whisper.cpp program (whisper-server)"), (self.model, "whisper.cpp model")):
                if not path or not Path(path).is_file():
                    raise RuntimeError(f"The {what} isn't set or wasn't found. Choose it in Nova's settings, Voice.")
            self.port = free_port()
            self.proc = subprocess.Popen([self.binary, "--model", self.model, "--host", "127.0.0.1", "--port",
                                          str(self.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         creationflags=NO_WINDOW)
            procs.kill_on_close(self.proc)  # not left running (and holding gigabytes) when Nova is killed
            deadline = time.monotonic() + START_TIMEOUT_S
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"whisper-server stopped right away (exit code {self.proc.returncode}). "
                                       "Check that the program and the model match.")
                try:
                    with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                        return
                except OSError:
                    time.sleep(0.25)
            self.stop()
            raise RuntimeError("whisper-server didn't start within 90 seconds.")

    def transcribe(self, audio, language, prompt):
        self.start()
        fields = {"response_format": "json", "temperature": "0.0", "temperature_inc": "0.2",
                  "language": language or "auto", **DECODER}
        if prompt:
            fields["prompt"] = prompt
        body, kind = multipart(fields, "speech.wav", wav(audio))
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/inference", data=body, method="POST",
                                     headers={"Content-Type": kind})
        with urllib.request.urlopen(req, timeout=max(30, len(audio) / 16000 * 2)) as r:  # twice real time, at least
            return " ".join(json.loads(r.read().decode("utf-8")).get("text", "").split())  # one line per segment

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
