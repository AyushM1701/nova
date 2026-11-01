"""Your voice: a recording of you reading a short passage, which the Pocket voice (core/tts.py) copies when Nova speaks.

The recording is made in Nova's window, from your microphone, and nowhere else: there is no way to load a file, so the
voice can only be your own (the voice model's terms forbid cloning anyone without their consent). It stays in data/voice on
this computer, nothing is sent anywhere, and Settings → Voice deletes it. Nothing the AI can do reaches it.
"""
import os
import wave
from pathlib import Path

from core.config import DATA

DIR = DATA / "voice"
REFERENCE = DIR / "yours.wav"
MIN_S, MAX_S = 8, 60  # seconds of speech: less is too little to copy; the recording stops at the longest
USE_S = 15  # the model listens to this much of the recording
QUIET = 0.01  # RMS below this (of 1.0) is a microphone that heard nothing
PASSAGE = ("Please read this out loud in your normal voice, at your own pace. The harbour was quiet before sunrise, and a "
           "thin mist lay over the water. Maria packed a flask of tea, two books and her father's old camera, then walked "
           "down to the pier. Why does everything look so different when nobody else is awake? She smiled, checked the "
           "time, and decided that today she would take her time. Seven boats, one gull, and a long, slow morning.")


def exists():
    return REFERENCE.is_file()


def _trim(x, rate):
    """Without the silence before and after the speech."""
    import numpy as np
    frame = max(1, rate // 50)
    n = len(x) // frame
    if n == 0:
        return x
    loud = np.sqrt((x[:n * frame].reshape(n, frame) ** 2).mean(axis=1))
    spoken = np.flatnonzero(loud > max(QUIET, loud.max() * 0.08))
    return x[spoken[0] * frame:(spoken[-1] + 1) * frame] if len(spoken) else x[:0]


def save(samples, rate):
    """Keep a recording (float samples, mono) as your voice. Returns the seconds of speech kept, or raises ValueError saying
    what to fix."""
    import numpy as np
    x = _trim(np.asarray(samples, dtype=np.float32).reshape(-1), rate)
    if len(x) == 0 or float(np.sqrt((x ** 2).mean())) < QUIET:
        raise ValueError("Nova couldn't hear you. Check the microphone in Settings → Microphone and try again.")
    seconds = len(x) / rate
    if seconds < MIN_S:
        raise ValueError(f"That was only {seconds:.0f} seconds. Read the whole passage, about {MIN_S + 12} seconds or more.")
    x = x[:int(MAX_S * rate)]
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = REFERENCE.with_name(f"yours.{os.getpid()}.tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    os.replace(tmp, REFERENCE)
    return round(len(x) / rate, 1)


def reference():
    """(the first USE_S seconds of your voice as float32, its sample rate); None if there is no recording."""
    import numpy as np
    try:
        with wave.open(str(REFERENCE), "rb") as w:
            rate = w.getframerate()
            x = np.frombuffer(w.readframes(min(w.getnframes(), USE_S * rate)), dtype="<i2").astype(np.float32) / 32768
    except (OSError, EOFError, wave.Error):
        return None
    return x, rate


def remove():
    """Delete your voice."""
    REFERENCE.unlink(missing_ok=True)
    for tmp in Path(DIR).glob("yours.*.tmp") if DIR.is_dir() else []:
        tmp.unlink(missing_ok=True)
