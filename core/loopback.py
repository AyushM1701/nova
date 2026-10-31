"""The computer's own audio (a video, lecture or call): Windows WASAPI loopback, or on macOS 13+ a small
ScreenCaptureKit helper (helpers/mac_audio_tap.swift). Two users:
- SystemAudio remembers the last few minutes of what the computer played, so "what did they just say?" works
  whenever you ask. It lives in memory only and is never saved. It is transcribed when you ask (or as it plays,
  on a GPU, or after "listen to my computer"); Settings → Privacy & safety sets how long it is kept, or turns it off.
- Meeting recordings (core/meetings.py) mix it with the microphone.
"""
import collections
import queue
import shutil
import subprocess
import sys
import threading
import time

import numpy as np

from core import pa
from core.config import DATA, ROOT, log

KEEP_S, CHUNK_S = 15 * 60, 12  # transcript window; seconds of audio per transcription pass
RETRY_S, MAX_RETRY_S = 3, 60  # a capture that failed is tried again after this long, doubling up to the second
DEVICE_CHECK_S = 10  # how often a running capture looks whether the default speakers changed
IDLE_S = 30  # a stopped capture's transcriber ends after this long with nothing to do
ASK_S = 120  # transcribed on request (a CPU without eager transcription): ten minutes of music took about a minute
RATE = 16000
MAC_HELPER, MAC_SOURCE = DATA / "bin" / "mac-audio-tap", ROOT / "helpers" / "mac_audio_tap.swift"
# PortAudio (pyaudiowpatch) starting, opening or stopping in two threads at once corrupts memory and kills Nova:
# the "Hey Nova" speaker check and the computer-audio memory both start a capture when Nova starts. One lock for all
# of Nova's PortAudio use (core/pa.py), sounddevice's streams included.
_PORTAUDIO = pa.LOCK


def available():
    if sys.platform == "darwin":
        return MAC_HELPER.exists() or bool(shutil.which("swiftc"))
    try:
        import pyaudiowpatch  # noqa: F401
        return True
    except ImportError:
        return False


def mac_helper():
    """The capture helper, built from its Swift source on first use (needs Xcode's command-line tools)."""
    if not MAC_HELPER.exists():
        if not shutil.which("swiftc"):
            raise RuntimeError("Capturing the Mac's audio needs Apple's command-line tools. Install them with "
                               "\"xcode-select --install\" in Terminal, then try again.")
        MAC_HELPER.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["swiftc", "-O", str(MAC_SOURCE), "-o", str(MAC_HELPER)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"Couldn't build the Mac audio helper: {(r.stderr or r.stdout).strip()[-300:]}")
    return MAC_HELPER


def to16k(audio, rate):
    if rate == RATE:
        return audio.astype(np.float32)
    t = np.arange(int(len(audio) * RATE / rate)) / RATE
    return np.interp(t, np.arange(len(audio)) / rate, audio).astype(np.float32)


def _default_loopback():
    """The index of the loopback device of the speakers that are the default now. A fresh PortAudio: the one a
    stream is open on keeps the device list it started with."""
    import pyaudiowpatch as pyaudio
    with _PORTAUDIO:
        p = pyaudio.PyAudio()
        try:
            return p.get_default_wasapi_loopback()["index"]
        finally:
            p.terminate()


def blocks(running):
    """Yield the computer's audio as 16 kHz mono blocks of about 100 ms while running() is true. Yields None
    when nothing is playing (Windows loopback delivers nothing while the computer is silent)."""
    if sys.platform == "darwin":
        proc = subprocess.Popen([str(mac_helper())], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            while running():
                data = proc.stdout.read(RATE // 10 * 4)
                if not data:
                    err = proc.stderr.read().decode("utf-8", "replace").strip()
                    raise RuntimeError(err or "The Mac audio helper stopped. Allow Nova in System Settings, "
                                       "Privacy & Security, Screen Recording.")
                yield np.frombuffer(data[:len(data) // 4 * 4], dtype="<f4")
        finally:
            proc.kill()
        return
    import pyaudiowpatch as pa
    with _PORTAUDIO:
        p = pa.PyAudio()
    try:
        with _PORTAUDIO:
            dev = p.get_default_wasapi_loopback()
            rate, channels = int(dev["defaultSampleRate"]), dev["maxInputChannels"]
            stream = p.open(format=pa.paFloat32, channels=channels, rate=rate, input=True,
                            input_device_index=dev["index"], frames_per_buffer=rate // 10)
        block, checked = rate // 10, time.monotonic()
        try:
            while running():
                if time.monotonic() - checked > DEVICE_CHECK_S:  # headphones plugged in or out: the caller opens it again
                    checked = time.monotonic()
                    try:
                        if _default_loopback() != dev["index"]:
                            return
                    except Exception:
                        return
                if stream.get_read_available() < block:  # never block on a read: silence delivers nothing
                    time.sleep(0.05)
                    yield None
                    continue
                data = np.frombuffer(stream.read(block, exception_on_overflow=False), dtype=np.float32)
                yield to16k(data.reshape(-1, channels).mean(axis=1), rate)
        finally:
            with _PORTAUDIO:
                stream.close()
    finally:
        with _PORTAUDIO:
            p.terminate()


def follows(mic, computer, hop=160):
    """How closely the mic's loudness rises and falls with the computer's (0..1), at the best alignment: near 1
    when the mic only hears the speakers, low when a person in the room is talking."""
    envelope = lambda a: np.log(np.sqrt((a[:len(a) // hop * hop].reshape(-1, hop) ** 2).mean(axis=1)) + 1e-4)  # noqa: E731
    m, c = envelope(mic), envelope(computer)
    if len(m) < 20 or len(c) < len(m):
        return 0.0
    m = (m - m.mean()) / (m.std() + 1e-9)
    windows = np.lib.stride_tricks.sliding_window_view(c, len(m))
    windows = (windows - windows.mean(axis=1, keepdims=True)) / (windows.std(axis=1, keepdims=True) + 1e-9)
    return float(max(0.0, (windows @ m).max() / len(m)))


class Tail:
    """The last few seconds of what the computer is playing, while Nova talks: tells the user's voice apart from
    a video or call heard through the speakers (core/wake.py, is_echo)."""

    def __init__(self, seconds=4):
        # a silent moment is a 50 ms block, a sound a 100 ms one: room for the busiest case, trimmed in recent()
        self.seconds, self.blocks, self.running = seconds, collections.deque(maxlen=seconds * 20), False

    def start(self):
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        delay, failed = RETRY_S, False
        while self.running:
            try:
                for block in blocks(lambda: self.running):
                    failed, delay = False, RETRY_S
                    self.blocks.append(block if block is not None else np.zeros(RATE // 20, np.float32))
            except Exception as e:  # no loopback device (yet): Nova falls back to checking only its own voice
                if not failed:
                    log("error", error=f"computer audio for the speaker check, trying again: {e!r}")
                failed = True
            if self.running:  # the speakers changed, or none yet: open the capture again
                time.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_S)

    def recent(self):
        """The last few seconds as one array, or None when nothing audible played."""
        audio = np.concatenate(list(self.blocks))[-self.seconds * RATE:] if self.blocks else None
        return audio if audio is not None and float(np.abs(audio).max()) >= 2e-3 else None

    def stop(self):
        self.running = False


class SystemAudio:
    """The last `keep_s` seconds of what the computer played, as chunks of about CHUNK_S seconds. Each chunk keeps
    its audio until it's transcribed, then only the text. eager=True transcribes as it plays (a GPU handles that
    easily, or after "listen to my computer"); otherwise transcript() transcribes what's left when asked."""

    def __init__(self, stt, keep_s=KEEP_S, eager=False):
        self.stt, self.keep_s, self.eager, self.running, self.stopped = stt, keep_s, eager, False, False
        self.muted = False  # True while Nova talks: its own voice isn't something the computer "played"
        self.chunks = collections.deque()  # [start time, int16 audio or None, text or None]
        self.buf, self.buf_start, self.lock = [], time.time(), threading.Lock()  # audio not chunked yet
        self.jobs, self.decode = queue.Queue(), threading.Lock()  # one transcription at a time
        threading.Thread(target=self._transcriber, daemon=True).start()

    @property
    def lines(self):  # what the AI context check looks at: is there anything to tell?
        return bool(self.chunks or self.buf)

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running, self.stopped = False, True

    def _run(self):
        heard, delay, failed = time.time(), RETRY_S, False
        try:
            while self.running:
                try:
                    for block in blocks(lambda: self.running):
                        failed, delay = False, RETRY_S
                        heard = self._take(block, heard)
                except Exception as e:  # the speakers changed or the device went away: open it again, don't go deaf
                    if not failed:
                        log("error", error=f"computer audio capture, trying again: {e!r}")
                    failed = True
                if self.running:
                    time.sleep(delay)
                    delay = min(delay * 2, MAX_RETRY_S)
            with self.lock:
                if self.buf:  # stopping keeps the last few seconds too
                    self._cut(len(self.buf))
        finally:
            self.running = False

    def _take(self, block, heard):
        """One block from the capture. Returns when audio was last heard."""
        with self.lock:
            if block is None or self.muted:
                if self.buf and (self.muted or time.time() - heard > 1.5):  # playback stopped: close the chunk
                    self._cut(len(self.buf))
                return heard
            if not self.buf:
                self.buf_start = time.time()
            self.buf.append(block)
            if len(self.buf) * 0.1 >= CHUNK_S:
                # end the chunk at the quietest 100 ms of its last 3 s, so no word is cut in half
                tail = [float(np.sqrt(np.mean(b ** 2))) for b in self.buf[-30:]]
                self._cut(len(self.buf) - len(tail) + int(np.argmin(tail)) + 1)
            return time.time()

    def _cut(self, n):
        """Turn the first n buffered blocks into a chunk (caller holds the lock)."""
        audio = np.concatenate(self.buf[:n])
        self.buf, start, self.buf_start = self.buf[n:], self.buf_start, time.time()
        if float(np.abs(audio).max()) < 2e-3:  # silence: nothing playing
            return
        chunk = [start, (np.clip(audio, -1, 1) * 32767).astype(np.int16), None]
        self.chunks.append(chunk)
        while self.chunks and self.chunks[0][0] < time.time() - self.keep_s:
            self.chunks.popleft()
        if self.eager:
            self.jobs.put(chunk)

    def _transcriber(self):
        """Transcribes chunks as they come; ends once this capture was stopped and its work is done, so a stopped
        one (and its audio) doesn't stay in memory."""
        while True:
            try:
                self._fill(self.jobs.get(timeout=IDLE_S))
            except queue.Empty:
                if self.stopped:
                    return
            except Exception as e:  # one chunk that can't be transcribed: the next ones still are
                log("error", error=f"transcribing the computer's audio: {e!r}")

    def _fill(self, chunk):
        with self.decode:
            if chunk[2] is None and chunk[1] is not None:
                chunk[2] = self.stt.transcribe(chunk[1].astype(np.float32) / 32767) or ""
                chunk[1] = None  # the text is enough from now on

    def transcript(self, now=None):
        """Timestamped lines, oldest first, for the AI's context. Transcribes whatever isn't yet, including the
        last few seconds still being buffered, so "what did they just say?" covers the words just spoken."""
        with self.lock:
            if self.buf:
                self._cut(len(self.buf))
            while self.chunks and self.chunks[0][0] < time.time() - self.keep_s:  # silence cuts nothing: forget by the clock
                self.chunks.popleft()
            chunks = list(self.chunks)
        recent = time.time() - ASK_S
        for chunk in chunks:
            if chunk[0] >= recent:  # older audio not transcribed yet is left out: minutes of it would hold up the request
                self._fill(chunk)
        now = now or time.time()
        return "\n".join(f"[{int((now - t) // 60)} min ago] {text}" for t, _, text in chunks if text)[-8000:]
