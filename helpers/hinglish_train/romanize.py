"""Step 2: every Hindi and Hinglish transcript in Roman letters, the way Nova should type it ("continue पर click करें"
-> "continue par click karein"), on this computer by rule (translit.py): no Claude calls, so no usage limit, and
spoken Hindi words are never swapped for English ones. English words the corpus spells in Devanagari (स्लाइड) come
back in English when the corpus also writes them in Latin letters. English transcripts are copied as they are, except
LibriSpeech's (all capitals), which punctuate.py gives back their casing.

    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/romanize.py

Reads manifest.jsonl, writes roman.jsonl {id, split, lang, text, seconds, source} afresh."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT  # noqa: E402
from translit import english, roman  # noqa: E402


def main():
    rows = [json.loads(line) for line in (OUT / "manifest.jsonl").open(encoding="utf-8")]
    vocabulary = english(r["text"] for r in rows if r["lang"] == "hi")
    kept = 0
    with (OUT / "roman.jsonl").open("w", encoding="utf-8") as out:
        for r in rows:
            if r["lang"] == "en" and r["text"].isupper():
                continue  # punctuate.py
            text = roman(r["text"], vocabulary) if r["lang"] == "hi" else r["text"]
            out.write(json.dumps({"id": r["id"], "split": r["split"], "lang": r["lang"], "text": text,
                                  "seconds": r["seconds"], "source": r["source"]}, ensure_ascii=False) + "\n")
            kept += 1
    print(f"{kept} transcripts written ({len(vocabulary)} English words known)")


if __name__ == "__main__":
    sys.exit(main())
