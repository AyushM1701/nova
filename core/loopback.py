"""Listen to the computer's own audio (a video, lecture or call) and keep a rolling transcript of the last
15 minutes, so "what did they just say?" works. Windows only (WASAPI loopback); the transcript lives in memory
and is never saved. Only you start it ("listen to my computer"), and it stops when you say so or Nova quits.
"""
import collections
import queue
import threading
import time

import numpy as np

KEEP_S, CHUNK_S = 15 * 60, 12  # transcript window; seconds of audio per transcription pass


def available():
    try:
        import pyaudiowpatch  # noqa: F401
        return True
    except ImportError:
        return False


class SystemAudio:
    def __init__(self, stt):
        self.stt, self.lines, self.running = stt, collections.deque(), False
        self.jobs = queue.Queue()  # chunks wait here, so capture never pauses (a paused stream drops audio)
        threading.Thread(target=self._transcriber, daemon=True).start()

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False

    def _run(self):
        import pyaudiowpatch as pa
        p = pa.PyAudio()
        try:
            dev = p.get_default_wasapi_loopback()
            rate, channels = int(dev["defaultSampleRate"]), dev["maxInputChannels"]
            stream = p.open(format=pa.paFloat32, channels=channels, rate=rate, input=True,
                            input_device_index=dev["index"], frames_per_buffer=rate // 10)
            buf, start, block, heard = [], time.time(), rate // 10, time.time()
            while self.running:
                # loopback delivers nothing while the computer is silent, so never block on a read
                if stream.get_read_available() < block:
                    if buf and time.time() - heard > 1.5:  # playback stopped: transcribe what we have
                        self._transcribe(np.concatenate(buf), rate, start)
                        buf = []
                    time.sleep(0.05)
                    continue
                if not buf:
                    start = time.time()
                heard = time.time()
                data = np.frombuffer(stream.read(block, exception_on_overflow=False), dtype=np.float32)
                buf.append(data.reshape(-1, channels).mean(axis=1))
                if len(buf) * 0.1 >= CHUNK_S:
                    # end the chunk at the quietest 100 ms of its last 3 s, so no word is cut in half
                    tail = [float(np.sqrt(np.mean(b ** 2))) for b in buf[-30:]]
                    cut = len(buf) - len(tail) + int(np.argmin(tail)) + 1
                    self._transcribe(np.concatenate(buf[:cut]), rate, start)
                    buf, start = buf[cut:], time.time()
            if buf:  # stopping keeps the last few seconds too
                self._transcribe(np.concatenate(buf), rate, start)
            stream.close()
        finally:
            p.terminate()
            self.running = False

    def _transcribe(self, audio, rate, start):
        self.jobs.put((audio, rate, start))

    def _transcriber(self):
        while True:
            self._transcribe_now(*self.jobs.get())

    def _transcribe_now(self, audio, rate, start):
        if float(np.abs(audio).max()) < 2e-3:  # silence: nothing playing
            return
        t = np.arange(int(len(audio) * 16000 / rate)) / 16000
        audio16 = np.interp(t, np.arange(len(audio)) / rate, audio).astype(np.float32)
        text = self.stt.transcribe(audio16)
        if text:
            self.lines.append((start, text))
        while self.lines and self.lines[0][0] < time.time() - KEEP_S:
            self.lines.popleft()

    def transcript(self, now=None):
        """Timestamped lines, oldest first, for the AI's context."""
        now = now or time.time()
        return "\n".join(f"[{int((now - t) // 60)} min ago] {text}" for t, text in self.lines)[-8000:]
