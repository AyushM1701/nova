"""How well Nova hears you, measured on your own voice.

  python helpers/stt_bench.py record            read the phrases aloud, one at a time (saved in data/hearing-test)
  python helpers/stt_bench.py score [--label X] [--hindi en-prompt|hi-prompt|hi|both]
                                                what Nova hears in each one now: word and letter error rates, wrong
                                                script (Devanagari when Roman letters were wanted), milliseconds
  python helpers/stt_bench.py <folder> [lang]   the old use: print what is heard in every .wav (a same-named .txt is
                                                the wanted text)

Scores are added to data/hearing-test/scores.csv, so a change can be compared with the run before it."""
import csv
import json
import re
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.cleanup import DEVANAGARI_RE  # noqa: E402

FOLDER = ROOT / "data" / "hearing-test"
# what people say to Nova: commands, dictation with fillers and corrections, Hindi, Hinglish, names Whisper doesn't know
PHRASES = [
    "open spotify and play blinding lights by the weeknd",
    "play goosebumps by travis scott",
    "play char diwari ek banda kaam ka",
    "play tum hi ho by arijit singh",
    "pause the music",
    "turn the volume up",
    "open vs code",
    "what's the time",
    "set a timer for five minutes",
    "close chrome",
    "search for cheap flights to goa",
    "send a message to rahul saying i'll be late",
    "um so i think we should uh push the release to friday",
    "meet me at four, actually make it five",
    "the build failed because the api key was missing from the env file",
    "can you summarize this page for me",
    "mujhe kal subah chhe baje utha dena",
    "aaj ka weather kaisa hai",
    "yaar ye code kaam nahi kar raha, check karo",
    "mera github open karo",
    "bhai meeting ko kal tak postpone kar do",
    "spotify pe arijit singh ke gaane chalao",
    "ek email likho manager ko ki main aaj late aaunga",
    "kya tum is error ko fix kar sakte ho",
    "main ghar ja raha hoon, baad mein baat karte hain",
    "fastapi aur postgresql ka setup kaise karte hain",
    "open my endpaper project in vs code",
    "deploy the nova branch to staging, no wait, to production",
    "theek hai, next song lagao",
    "remind me to call mom at eight pm",
]


def load(wav):
    with wave.open(str(wav)) as f:  # 16-bit PCM, as Nova records
        rate, channels, raw = f.getframerate(), f.getnchannels(), f.readframes(f.getnframes())
    audio = np.frombuffer(raw, np.int16).astype(np.float32).reshape(-1, channels).mean(axis=1) / 32768
    if rate != 16000:
        audio = np.interp(np.linspace(0, len(audio), int(len(audio) * 16000 / rate), endpoint=False),
                          np.arange(len(audio)), audio).astype(np.float32)
    return audio


def save(path, audio):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def _distance(a, b):
    """Edits (insert, delete, change) that turn sequence a into b."""
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def words(text):
    return re.findall(r"\w+", text.lower().replace("'", ""))


def error_rates(heard, wanted):
    """(word error rate, letter error rate): the letter rate forgives Roman spellings of Hindi ("kaam" / "kam")."""
    w, h = words(wanted), words(heard)
    letters = lambda ws: "".join(ws)  # noqa: E731
    return _distance(h, w) / max(1, len(w)), _distance(letters(h), letters(w)) / max(1, len(letters(w)))


def config():
    from core.config import merged
    cfg = json.loads((ROOT / "config.default.json").read_text(encoding="utf-8"))
    mine = ROOT / "config.json"
    return merged(cfg, json.loads(mine.read_text(encoding="utf-8"))) if mine.exists() else cfg


def record():
    from core import audio
    FOLDER.mkdir(parents=True, exist_ok=True)
    only = {int(n) for n in sys.argv[2:] if n.isdigit()}  # "record 3 7": just those again
    audio.apply_devices(config()["voice"])
    print("Read each phrase the way you'd say it to Nova. It records until you pause.\n")
    for n, phrase in enumerate(PHRASES, 1):
        if only and n not in only:
            continue
        input(f"[{n}/{len(PHRASES)}]  \"{phrase}\"   press Enter, then speak ")
        clip = audio.record(1200, 15, threading.Event())
        if clip is None:
            print("    didn't hear anything; run 'record", n, "' later to redo it")
            continue
        save(FOLDER / f"{n:02}.wav", clip)
        (FOLDER / f"{n:02}.txt").write_text(phrase, encoding="utf-8")
        print(f"    saved ({len(clip) / 16000:.1f} s)")


def score():
    from core import stt as stt_mod
    from core.stt import STT
    label = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else time.strftime("%Y-%m-%d %H:%M")
    if "--hindi" in sys.argv:  # en-prompt, hi-prompt, hi or both: how Hindi clips are decoded (core/stt.py HINDI)
        stt_mod.HINDI = sys.argv[sys.argv.index("--hindi") + 1]
        label += f" hindi={stt_mod.HINDI}"
    v = config()["voice"]
    stt = STT(v["stt_model"], v["stt_accurate_model"])
    stt.load_accurate()
    stt.likely = tuple(v["languages"])
    vocabulary = config()["dictation"]["dictionary"]
    rows = []
    for wav in sorted(FOLDER.glob("*.wav")):
        wanted = wav.with_suffix(".txt").read_text(encoding="utf-8").strip()
        clip = load(wav)
        t0 = time.perf_counter()
        heard = stt.transcribe(clip, v["language"], vocabulary)
        ms = (time.perf_counter() - t0) * 1000
        wer, cer = error_rates(heard, wanted)
        script = bool(DEVANAGARI_RE.search(heard))
        rows.append((wav.stem, wer, cer, script, ms))
        print(f"{wav.stem}  WER {wer:4.0%}  letters {cer:4.0%}  {ms:5.0f} ms  {'DEVANAGARI ' if script else ''}"
              f"heard {heard!r}  wanted {wanted!r}")
    if not rows:
        return print(f"No recordings in {FOLDER}: run 'python helpers/stt_bench.py record' first.")
    mean = lambda i: sum(r[i] for r in rows) / len(rows)  # noqa: E731
    hindi = [r for r, w in zip(rows, sorted(FOLDER.glob("*.wav"))) if re.search(
        r"\b(?:ka|ki|ke|ko|hai|hoon|karo|kar|mujhe|yaar|bhai|aaj|kal|mera|kya|tum|main|aur|pe|theek|ek|char)\b",
        w.with_suffix(".txt").read_text(encoding="utf-8"))]
    hmean = (sum(r[1] for r in hindi) / len(hindi)) if hindi else 0
    ms = sorted(r[4] for r in rows)
    print(f"\n{label}: WER {mean(1):.0%} (Hindi/Hinglish {hmean:.0%}, {len(hindi)} clips), letters {mean(2):.0%}, "
          f"wrong script {sum(r[3] for r in rows)}, median {ms[len(ms) // 2]:.0f} ms")
    with open(FOLDER / "scores.csv", "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([label, f"{mean(1):.3f}", f"{hmean:.3f}", f"{mean(2):.3f}", sum(r[3] for r in rows),
                                round(ms[len(ms) // 2])])


def folder(path, language):
    from core.stt import STT
    v = json.loads((ROOT / "config.default.json").read_text(encoding="utf-8"))["voice"]
    stt = STT(v["stt_model"], v["stt_accurate_model"])
    for wav in sorted(Path(path).glob("*.wav")):
        audio = load(wav)
        want = wav.with_suffix(".txt")
        print(f"{wav.name}: peak {np.abs(audio).max():.2f} | {stt.transcribe(audio, language)!r}"
              + (f" | wanted {want.read_text(encoding='utf-8').strip()!r}" if want.exists() else ""))


if __name__ == "__main__":
    if sys.argv[1:2] == ["record"]:
        record()
    elif sys.argv[1:2] == ["score"]:
        score()
    else:
        folder(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "auto")
