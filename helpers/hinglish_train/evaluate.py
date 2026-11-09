"""Step 4: is the trained model better than what Nova uses now? Word and letter error rates on the held-out test clips,
for each test corpus (Hinglish lectures, Indian English, LibriSpeech English).

    .venv/Scripts/python helpers/hinglish_train/evaluate.py [--limit 250] [--model NAME=PATH:MODE ...]

Runs in Nova's own environment (faster-whisper), on Nova's own decoding (core/stt.py). Without --model: today's
large-v3-turbo with its Hinglish prompt against the trained model ($HINGLISH_DIR/ct2). MODE says how a model decodes:
  en-prompt  Nova's stock-Whisper way (en/hi detected, Hindi decoded as English with the Hinglish prompt)
  hi         a model trained here (en/hi detected, Hindi decoded as "hi", the way it was trained)
  en         always "en", no detection (Oriserve's Whisper-Hindi2Hinglish, as its card decodes)
"Roman WER" first converts any Devanagari the model wrote to Roman letters by the same rules the test transcripts went
through (translit.py), as MUCS's own transliterated WER does: a model isn't charged for its script, only its words.
The ship rule (the plan): Hinglish clearly better, English no worse."""
import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "helpers"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT  # noqa: E402
from core import stt as stt_mod  # noqa: E402
from stt_bench import error_rates, load  # noqa: E402
from translit import english, roman  # noqa: E402

TURBO = "today: turbo + Hinglish prompt"  # scores.json key; publish.py shows it as "Whisper large-v3-turbo"
TRAINED = "trained"
RESULTS = {}  # {model: {corpus: {wer, twer, letters, ms, clips}}}, saved to scores.json for the model card (publish.py)


def score(name, model, mode, groups, vocabulary):
    stt_mod.HINDI = "en-prompt" if mode == "en-prompt" else "hi"
    s = stt_mod.STT.__new__(stt_mod.STT)
    s.fast, s.accurate, s.small, s.device, s.likely = model, None, None, "GPU", ("en", "hi")
    for corpus, test in groups.items():
        wer = twer = cer = ms = 0.0
        for r in test:
            audio = load(OUT / "clips" / f"{r['id']}.wav")
            t0 = time.perf_counter()
            heard = s.transcribe(audio, "en" if mode == "en" else "auto")
            ms += (time.perf_counter() - t0) * 1000
            w, c = error_rates(heard, r["text"])
            wer, cer, twer = wer + w, cer + c, twer + error_rates(roman(heard, vocabulary), r["text"])[0]
        n = len(test)
        RESULTS.setdefault(name, {})[corpus] = {"wer": round(wer / n, 4), "twer": round(twer / n, 4),
                                                "letters": round(cer / n, 4), "ms": round(ms / n), "clips": n}
        print(f"{name[:30]:30} {corpus[:34]:34} WER {wer / n:5.1%}  Roman WER {twer / n:5.1%}  letters {cer / n:5.1%}  "
              f"{ms / n:5.0f} ms", flush=True)


def models(argv):
    """[(name, path, mode)] from --model NAME=PATH:MODE (PATH may hold a drive letter's colon)."""
    given = [argv[i + 1] for i, a in enumerate(argv) if a == "--model"]
    if not given:
        return [(TURBO, "large-v3-turbo", "en-prompt"), (TRAINED, str(OUT / "ct2"), "hi")]
    out = []
    for g in given:
        name, rest = g.split("=", 1)
        path, mode = rest.rsplit(":", 1)
        assert mode in ("en-prompt", "hi", "en"), f"unknown mode {mode!r} in {g!r}"
        out.append((name, path, mode))
    return out


def main():
    from faster_whisper import WhisperModel
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 250
    groups = collections.defaultdict(list)
    for r in map(json.loads, (OUT / "roman.jsonl").open(encoding="utf-8")):
        if r["split"] == "test" and len(groups[r.get("source") or "test"]) < limit:
            groups[r.get("source") or "test"].append(r)
    for corpus, test in groups.items():
        print(f"{corpus}: {len(test)} clips, {sum(r['seconds'] for r in test) / 60:.0f} min")
    # the English words the corpus spells in Devanagari, as romanize.py found them for the test transcripts
    vocabulary = english(r["text"] for r in map(json.loads, (OUT / "manifest.jsonl").open(encoding="utf-8"))
                         if r["lang"] == "hi")
    for name, path, mode in models(sys.argv):
        model = WhisperModel(path, device="cuda", compute_type="float16")
        score(name, model, mode, groups, vocabulary)
        del model  # one model on the GPU at a time
    (OUT / "scores.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
