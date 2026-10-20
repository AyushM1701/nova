"""'Hey Nova' wake word, fully on-device.

The first 2.5 s of each utterance is transcribed locally and checked for the wake phrase. Nothing leaves
the laptop and nothing is logged unless the phrase is heard. "Hey Nova, play some music" in one
breath works too: the audio after "Nova" becomes the request, transcribed by the full (Hindi-aware) pipeline.
"""
import collections
import queue
import re

import numpy as np
import sounddevice as sd

from core.audio import BLOCK, RATE

# Whisper's usual spellings of the phrase; "noah"/"nava" only count after a greeting
WAKE_RE = re.compile(r"^\W*(?:(?:hey|hi|hay|ay|ok|okay|hello)[\s,]+(?:nova|novah|nover|noba|noah|nava)|nova)\b"
                     r"[\s,.!?]*(.*)$", re.I | re.S)
NAME_RE = re.compile(r"nov|noah|nava|noba", re.I)
CHECK_S, MAX_S, MIN_S, END_SILENCE_MS = 2.5, 20.0, 0.4, 700


def match(text):
    """None if `text` isn't a wake phrase, else the request that followed it ('' if none)."""
    m = WAKE_RE.match(text or "")
    return m.group(1).strip() if m else None


def listen(transcribe, on_wake, enabled):
    """Run forever (own thread). on_wake(None) = start listening, on_wake(audio) = this audio is the request.
    `enabled()` is False while Nova is busy, so its own voice can't wake it."""
    blocks = queue.Queue()
    before = collections.deque(maxlen=10)  # 300 ms of audio before speech, so "hey" isn't clipped
    seg, floor, quiet = [], 0.01, 0
    woke = None  # None: not checked yet, False: not a wake phrase, else (end of "Nova" in s, words after it)
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK,
                        callback=lambda data, *_: blocks.put(data[:, 0].copy())):
        while True:
            block = blocks.get()
            if not enabled():
                seg, quiet, woke = [], 0, None
                before.clear()
                continue
            rms = float(np.sqrt(np.mean(block ** 2)))
            loud = rms > max(0.012, floor * 3)
            if not seg:
                if loud:
                    seg, quiet = list(before) + [block], 0
                else:
                    floor = 0.98 * floor + 0.02 * rms  # track the room's noise level
                    before.append(block)
                continue
            seg.append(block)
            quiet = 0 if loud else quiet + 30
            ended, seconds = quiet >= END_SILENCE_MS, len(seg) * BLOCK / RATE
            if woke is None and seconds >= MIN_S and (ended or seconds >= CHECK_S):
                words = transcribe(np.concatenate(seg))
                rest = match(" ".join(word for word, _ in words))
                woke = False if rest is None else (next(e for word, e in words if NAME_RE.search(word)), rest)
            if woke is False:
                seg = seg[-1:]  # ordinary talk: just wait for the pause, don't keep the audio
            if ended or (woke and seconds >= MAX_S):
                if woke:
                    end, rest = woke
                    # more speech after "Nova" (heard, or still going past the check): that audio is the request.
                    # +0.12 s because Whisper's word end times run slightly early
                    on_wake(np.concatenate(seg)[int((end + 0.12) * RATE):] if rest or seconds > CHECK_S + 1 else None)
                seg, woke = [], None
                before.clear()
