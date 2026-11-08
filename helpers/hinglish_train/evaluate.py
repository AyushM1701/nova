"""Step 4: is the trained model better than what Nova uses now? Word and letter error rates on the held-out test clips,
for each test corpus (Hinglish lectures, read Hindi, Indian English, LibriSpeech English).

    .venv/Scripts/python helpers/hinglish_train/evaluate.py [--limit 250]

Runs in Nova's own environment (faster-whisper), on Nova's own decoding (core/stt.py): today's large-v3-turbo with its
Hinglish prompt, against the trained model ($HINGLISH_DIR/ct2) decoding Hindi as "hi", the way it was trained. The
language is detected per clip, as in Nova. The ship rule (the plan): Hinglish clearly better, English no worse."""
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


RESULTS = {}  # {model: {corpus: {wer, letters, ms}}}, saved to scores.json for the model card (publish.py)


def score(name, model, hindi, groups):
    stt_mod.HINDI = hindi
    s = stt_mod.STT.__new__(stt_mod.STT)
    s.fast, s.accurate, s.small, s.device, s.likely = model, None, None, "GPU", ("en", "hi")
    for corpus, test in groups.items():
        wer = cer = ms = 0.0
        for r in test:
            audio = load(OUT / "clips" / f"{r['id']}.wav")
            t0 = time.perf_counter()
            heard = s.transcribe(audio, "auto")
            ms += (time.perf_counter() - t0) * 1000
            w, c = error_rates(heard, r["text"])
            wer, cer = wer + w, cer + c
        n = len(test)
        RESULTS.setdefault(name, {})[corpus] = {"wer": round(wer / n, 4), "letters": round(cer / n, 4), "ms": round(ms / n),
                                                "clips": n}
        print(f"{name:30} {corpus[:34]:34} WER {wer / n:5.1%}  letters {cer / n:5.1%}  {ms / n:5.0f} ms", flush=True)


def main():
    from faster_whisper import WhisperModel
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 250
    groups = collections.defaultdict(list)
    for r in map(json.loads, (OUT / "roman.jsonl").open(encoding="utf-8")):
        if r["split"] == "test" and len(groups[r.get("source") or "test"]) < limit:
            groups[r.get("source") or "test"].append(r)
    for corpus, test in groups.items():
        print(f"{corpus}: {len(test)} clips, {sum(r['seconds'] for r in test) / 60:.0f} min")
    today = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
    score("today: turbo + Hinglish prompt", today, "en-prompt", groups)
    del today
    score("trained", WhisperModel(str(OUT / "ct2"), device="cuda", compute_type="float16"), "hi", groups)
    (OUT / "scores.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
