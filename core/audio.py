"""Mic capture: 16 kHz mono raw audio (no DSP, as Wispr does), stops on silence after speech."""
import collections
import queue
import time

import numpy as np
import sounddevice as sd

RATE = 16000
BLOCK = 480  # 30 ms
# Speech is anything this many times louder than the room, and at least MIN_SPEECH. The floor is low on
# purpose: quiet USB and laptop mics hear normal talking at 0.0005-0.003 RMS; Whisper still transcribes 0.0004.
SPEECH_OVER_FLOOR, MIN_SPEECH = 4, 0.0003


def is_speech(rms, floor):
    return rms > max(MIN_SPEECH, floor * SPEECH_OVER_FLOOR)


def level(rms):
    """0..1 for the waveform; the square root lets quiet mics still move the bars."""
    return min(1.0, (rms / 0.03) ** 0.5)


def record(silence_ms, max_s, stop, on_level=None, prefix=None, floor_rms=None):
    """Record until `silence_ms` of quiet after speech, `stop` is set, or `max_s`. None if nothing said.
    `prefix` is speech already captured (an interruption): recording continues from it."""
    blocks, floor, speaking, quiet_ms = queue.Queue(), [], False, 0
    chunks = []
    if prefix is not None:  # mid-sentence already: the room's level comes from before the user spoke
        chunks, speaking, floor = [prefix], True, [floor_rms or MIN_SPEECH] * 10
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
                on_level(level(rms))
            if len(floor) < 10:  # first 300 ms calibrates the room's noise floor
                floor.append(rms)
                continue
            if is_speech(rms, float(np.median(floor))):
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


def watch(done, min_ms=360):
    """While Nova talks: wait for someone to speak for `min_ms`. Returns (the last ~1 s of audio, the room's
    level) so no word is lost, or None once `done` is set. The caller checks it isn't Nova's own voice."""
    blocks, recent = queue.Queue(), collections.deque(maxlen=34)
    floor, run_ms = None, 0
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK,
                        callback=lambda data, *_: blocks.put(data[:, 0].copy())):
        while not done.is_set():
            try:
                block = blocks.get(timeout=0.1)
            except queue.Empty:
                continue
            recent.append(block)
            rms = float(np.sqrt(np.mean(block ** 2)))
            floor = rms if floor is None else floor
            if is_speech(rms, floor):
                run_ms += 30
                if run_ms >= min_ms:
                    return np.concatenate(recent), floor
            else:
                run_ms = max(0, run_ms - 60)  # a short gap between syllables doesn't reset it
                floor = 0.98 * floor + 0.02 * rms
    return None
