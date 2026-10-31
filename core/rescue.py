"""Crash-safe dictation: each dictation's audio is kept in data/last-dictation.wav until it has been typed, so
Nova closing mid-dictation never loses what was said. The next start transcribes it onto the clipboard."""
import wave

import numpy as np

from core.config import DATA, log

RESCUE = DATA / "last-dictation.wav"
RATE = 16000


def keep(clip, path=RESCUE):
    """True if saved. A copy that can't be written (antivirus lock, full disk) is skipped: the dictation goes on."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")  # whole or not at all: a power cut mid-write leaves the last one
        with open(tmp, "wb") as f, wave.open(f, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes((np.clip(clip, -1, 1) * 32767).astype("<i2").tobytes())
        tmp.replace(path)
        return True
    except OSError as e:
        log("error", error=f"couldn't keep a rescue copy of the dictation: {e!r}")
        return False


def pending(path=RESCUE):
    """The kept audio, or None. A file that can't be read is deleted, so it isn't retried at every start."""
    if not path.exists():
        return None
    try:
        with wave.open(str(path), "rb") as w:
            raw = w.readframes(w.getnframes())
            return np.frombuffer(raw[:len(raw) // 2 * 2], dtype="<i2").astype(np.float32) / 32767  # cut mid-sample
    except (OSError, EOFError, wave.Error, ValueError):
        clear(path)
        return None


def clear(path=RESCUE):
    path.unlink(missing_ok=True)
