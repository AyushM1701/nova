"""Does the fix-up turn misheard Hinglish commands back into what was said? Real Hinglish voice-assistant commands
(Kaggle's Hinglish-TOP, human-written test set) are read aloud by Kokoro's Indian voices, heard by Nova's Whisper,
then fixed by the polish model (cleanup.fix_heard). Prints word error rates before and after the fix.

    .venv/Scripts/python helpers/hinglish_train/polish_test.py [--n 100] [--model data/hinglish-train/ct2]

The polish runs only with a model on this computer (Settings, Dictation, Local AI, e.g. Ollama's qwen2.5:3b); without
one it measures the hearing alone. Synthetic voices: a rough guide, not a replacement for your own recordings."""
import csv
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "helpers"))
from core import cleanup, stt as stt_mod, tts  # noqa: E402
from core.local_llm import LocalLLM  # noqa: E402
from stt_bench import config, error_rates  # noqa: E402

TSV = ROOT / "data" / "hinglish-train" / "kaggle" / "Human Annotated Data" / "test.tsv"
VOICES = ("hf_alpha", "hf_beta", "hm_omega", "hm_psi")


def commands(n):
    with TSV.open(encoding="utf-8") as f:
        rows = [r["cs_query"].strip() for r in csv.DictReader(f, delimiter="\t") if r.get("cs_query")]
    random.Random(0).shuffle(rows)
    return rows[:n]


def speak(model, text, voice):
    out = model.generate(text, sid=tts.KOKORO_VOICES.index(voice), speed=1.0)
    audio = np.array(out.samples, dtype=np.float32)
    return np.interp(np.linspace(0, len(audio), int(len(audio) * 16000 / out.sample_rate), endpoint=False),
                     np.arange(len(audio)), audio).astype(np.float32)


def main():
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 100
    trained = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else ""
    cfg = config()
    v, d = cfg["voice"], cfg["dictation"]
    from faster_whisper import WhisperModel
    s = stt_mod.STT.__new__(stt_mod.STT)
    s.fast = WhisperModel(trained or v["stt_accurate_model"], device="cuda", compute_type="float16")
    s.accurate, s.small, s.device, s.likely = None, None, "GPU", tuple(v["languages"])
    stt_mod.HINDI = "hi" if trained else stt_mod.HINDI
    polish = LocalLLM(d["local_url"], d["local_model"]) if d["cleanup_engine"] == "local" else None
    if polish and polish.clean("Reply OK.", "ping", d["local_model"], timeout=20) is None:
        print(f"The local model ({d['local_model']} at {d['local_url']}) didn't answer: measuring hearing only.")
        polish = None
    voice_model = tts.load("kokoro")
    heard_w = fixed_w = 0.0
    fix_ms, rows = 0.0, []
    for i, said in enumerate(commands(n)):
        heard = s.transcribe(speak(voice_model, said, VOICES[i % len(VOICES)]), "auto")
        t0 = time.perf_counter()
        fixed = cleanup.fix_heard(heard, d["dictionary"], polish, d) if polish else heard
        fix_ms += (time.perf_counter() - t0) * 1000
        hw, fw = error_rates(heard, said)[0], error_rates(fixed, said)[0]
        heard_w, fixed_w = heard_w + hw, fixed_w + fw
        rows.append({"said": said, "heard": heard, "fixed": fixed, "heard_wer": round(hw, 3), "fixed_wer": round(fw, 3)})
    count = len(rows)
    print(f"{count} commands: heard WER {heard_w / count:.1%}"
          + (f", after the fix {fixed_w / count:.1%} ({fix_ms / count:.0f} ms a fix)" if polish else ""))
    report = ROOT / "data" / "hinglish-train" / f"polish-test{'-trained' if trained else ''}.jsonl"
    report.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    print(f"each command: {report}")


if __name__ == "__main__":
    main()
