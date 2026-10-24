"""Crash-safe dictation: each dictation's audio is kept in data/last-dictation.wav until it has been typed, so
Nova closing mid-dictation never loses what was said. The next start transcribes it onto the clipboard."""
import wave

import numpy as np

from core.config import DATA

RESCUE = DATA / "last-dictation.wav"
RATE = 16000


def keep(clip, path=RESCUE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(clip, -1, 1) * 32767).astype("<i2").tobytes())


def pending(path=RESCUE):
    """The kept audio, or None. A file that can't be read is deleted, so it isn't retried at every start."""
    if not path.exists():
        return None
    try:
        with wave.open(str(path), "rb") as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32767
    except (OSError, EOFError, wave.Error):
        clear(path)
        return None


def clear(path=RESCUE):
    path.unlink(missing_ok=True)
