"""What Nova hears in each recording: python helpers/stt_bench.py <folder of .wav files> [language]. Record real commands
(a song title, a Hinglish sentence), put the wanted text in a same-named .txt, and compare settings by their output."""
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.stt import STT  # noqa: E402

cfg = json.load(open(Path(__file__).resolve().parent.parent / "config.default.json", encoding="utf-8"))["voice"]
stt = STT(cfg["stt_model"], cfg["stt_accurate_model"])
for wav in sorted(Path(sys.argv[1]).glob("*.wav")):
    with wave.open(str(wav)) as f:  # 16-bit PCM, as Nova records
        rate, channels, raw = f.getframerate(), f.getnchannels(), f.readframes(f.getnframes())
    audio = np.frombuffer(raw, np.int16).astype(np.float32).reshape(-1, channels).mean(axis=1) / 32768
    if rate != 16000:
        audio = np.interp(np.linspace(0, len(audio), int(len(audio) * 16000 / rate), endpoint=False), np.arange(len(audio)), audio).astype(np.float32)
    want = wav.with_suffix(".txt")
    print(f"{wav.name}: peak {np.abs(audio).max():.2f} | {stt.transcribe(audio, sys.argv[2] if len(sys.argv) > 2 else 'auto')!r}"
          + (f" | wanted {want.read_text(encoding='utf-8').strip()!r}" if want.exists() else ""))
