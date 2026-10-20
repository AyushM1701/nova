"""Mic capture: 16 kHz mono raw audio (no DSP, as Wispr does), stops on silence after speech."""
import queue
import time

import numpy as np
import sounddevice as sd

RATE = 16000
BLOCK = 480  # 30 ms


def record(silence_ms, max_s, stop, on_level=None):
    """Record until `silence_ms` of quiet after speech, `stop` is set, or `max_s`. None if nothing said."""
    blocks, floor, speaking, quiet_ms = queue.Queue(), [], False, 0
    chunks = []
    start = time.monotonic()
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK,
                        callback=lambda data, *_: blocks.put(data[:, 0].copy())):
        while not stop.is_set() and time.monotonic() - start < max_s:
            try:
                block = blocks.get(timeout=0.1)
            except queue.Empty:
                continue
            chunks.append(block)
            rms = float(np.sqrt(np.mean(block ** 2)))
            if on_level:
                on_level(min(1.0, rms * 12))
            if len(floor) < 10:  # first 300 ms calibrates the room's noise floor
                floor.append(rms)
                continue
            if rms > max(0.01, float(np.median(floor)) * 3):
                speaking, quiet_ms = True, 0
            elif speaking:
                quiet_ms += 30
                if quiet_ms >= silence_ms:
                    break
            elif time.monotonic() - start > 6:
                break  # never started speaking
    if chunks and (speaking or stop.is_set()):
        return np.concatenate(chunks)
    return None
