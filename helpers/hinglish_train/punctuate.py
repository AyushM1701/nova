"""Step 2b: LibriSpeech's transcripts are in capitals with no punctuation; trained on as they are, the model would
stop punctuating English. Stock Whisper (which punctuates) hears each clip; where it heard exactly the same words, its
text is used, cased and punctuated. Otherwise the transcript is kept in plain sentence case. On this computer, no
Claude calls. Runs in Nova's own environment (faster-whisper):

    .venv/Scripts/python helpers/hinglish_train/punctuate.py

Appends the LibriSpeech rows to roman.jsonl (romanize.py writes the others first)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "helpers"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT  # noqa: E402
from stt_bench import load  # noqa: E402
sys.path.insert(0, str(ROOT))
import core.stt  # noqa: E402,F401  registers the venv's CUDA DLL folders (cublas) on Windows


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("'", ""))


def main():
    from faster_whisper import WhisperModel
    model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
    rows = [r for r in map(json.loads, (OUT / "manifest.jsonl").open(encoding="utf-8"))
            if r["lang"] == "en" and r["text"].isupper()]
    done = {json.loads(line)["id"] for line in (OUT / "roman.jsonl").open(encoding="utf-8")}
    exact = 0
    with (OUT / "roman.jsonl").open("a", encoding="utf-8") as out:
        for n, r in enumerate(rows, 1):
            if r["id"] in done:
                continue
            segments, _ = model.transcribe(load(OUT / "clips" / f"{r['id']}.wav"), language="en", beam_size=1,
                                           condition_on_previous_text=False)
            heard = " ".join(s.text.strip() for s in segments).strip()
            if words(heard) == words(r["text"]):
                text, exact = heard, exact + 1
            else:
                text = r["text"].capitalize() + "."
            out.write(json.dumps({"id": r["id"], "split": r["split"], "lang": "en", "text": text,
                                  "seconds": r["seconds"], "source": r["source"]}, ensure_ascii=False) + "\n")
            if n % 500 == 0:
                print(f"{n}/{len(rows)}, {exact} punctuated by Whisper", flush=True)
    print(f"done: {exact} of {len(rows)} punctuated by Whisper, the rest in plain sentence case")


if __name__ == "__main__":
    main()
