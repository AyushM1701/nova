"""Step 4: is the trained model better than what Nova uses now? Word and letter error rates on the held-out test clips.

    .venv/Scripts/python helpers/hinglish_train/evaluate.py [--limit 300]

Runs in Nova's own environment (faster-whisper), on Nova's own decoding (core/stt.py): today's large-v3-turbo with its
Hinglish prompt, against the trained model (data/hinglish-train/ct2) decoding Hindi as "hi", the way it was trained.
Close Nova first, so both fit on the GPU."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "helpers"))
from core import stt as stt_mod  # noqa: E402
from stt_bench import error_rates, load  # noqa: E402

OUT = ROOT / "data" / "hinglish-train"


def score(name, model, hindi, test):
    stt_mod.HINDI = hindi
    s = stt_mod.STT.__new__(stt_mod.STT)
    s.fast, s.accurate, s.small, s.device, s.likely = model, None, None, "GPU", ("en", "hi")
    wer = cer = ms = 0.0
    for r in test:
        audio = load(OUT / "clips" / f"{r['id']}.wav")
        t0 = time.perf_counter()
        heard = s.transcribe(audio, "auto")
        ms += (time.perf_counter() - t0) * 1000
        w, c = error_rates(heard, r["text"])
        wer, cer = wer + w, cer + c
    n = len(test)
    print(f"{name:34} WER {wer / n:5.1%}  letters {cer / n:5.1%}  {ms / n:5.0f} ms a clip", flush=True)


def main():
    from faster_whisper import WhisperModel
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 300
    test = [r for r in map(json.loads, (OUT / "roman.jsonl").open(encoding="utf-8")) if r["split"] == "test"][:limit]
    print(f"{len(test)} held-out clips, {sum(r['seconds'] for r in test) / 60:.0f} min")
    today = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
    for hindi in ("en-prompt", "hi-prompt"):
        score(f"today: turbo, {hindi}", today, hindi, test)
    del today
    score("trained: turbo + Hinglish LoRA", WhisperModel(str(OUT / "ct2"), device="cuda", compute_type="float16"),
          "hi", test)


if __name__ == "__main__":
    main()
