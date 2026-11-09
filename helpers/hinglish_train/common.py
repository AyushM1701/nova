"""Where a training run keeps its data: data/hinglish-ship by default (the licensed run that ships with Nova), or
HINGLISH_DIR=hinglish-train for the first, private pilot."""
import os
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[2] / "data" / os.environ.get("HINGLISH_DIR", "hinglish-ship")


def splice(a, b, rate=16000, fade_ms=80):
    """Two clips as one, crossfaded where they meet: a Hindi clip and an English one become a sentence that switches
    language, which real recordings have too few of (code-mix splicing, Biswas et al., Interspeech 2025)."""
    n = min(int(rate * fade_ms / 1000), len(a), len(b))
    if not n:
        return np.concatenate([a, b])
    ramp = np.linspace(1.0, 0.0, n, dtype=a.dtype)
    return np.concatenate([a[:-n], a[-n:] * ramp + b[:n] * (1 - ramp), b[n:]])
