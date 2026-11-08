"""Step 1 of training Whisper on Hinglish: download a slice of two public datasets and keep clean clips.

    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/prepare.py

Writes data/hinglish-train/clips/<id>.wav (16 kHz mono) and manifest.jsonl lines {id, split, text, seconds, source}.
The transcripts are still Devanagari mixed with English here; romanize.py turns them into Roman Hinglish.
ujs/hinglish states no license: a model trained on it is for this computer only, never shipped with Nova."""
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import soundfile as sf

OUT = Path(__file__).resolve().parents[2] / "data" / "hinglish-train"
BASE = "https://huggingface.co/api/datasets/{}/parquet/default/train/{}.parquet"
# (dataset, shard, split): shards spread through agarwalayushi's 816 (it is ordered by speaker) for more voices
# (most of agarwalayushi is lectures with few Hindi-English clips: shard 220 has none, 61 sits by 60, which has many)
SHARDS = [("ujs/hinglish", n, "train") for n in (0, 1, 2, 4, 7)] + [("ujs/hinglish", 9, "test")] + \
         [("agarwalayushi/hinglish", n, "train") for n in (60, 220, 380, 540, 700)] + [("agarwalayushi/hinglish", 61, "test")]
TEST_PER_SHARD = 250  # held-out clips from each test shard
DOUBLED = re.compile(r"([ऀ-ॿ]+)([A-Za-z]+)")  # "लूपloop": a word written twice, Hindi then English


def fetch(dataset, shard):
    path = OUT / "raw" / f"{dataset.replace('/', '_')}-{shard}.parquet"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {dataset} shard {shard}", flush=True)
        part = path.with_suffix(".part")
        with urllib.request.urlopen(BASE.format(dataset, shard), timeout=120) as r, open(part, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        part.rename(path)
    return path


def text_of(dataset, row):
    """The transcript, or None to skip the clip (agarwalayushi: only its Hindi-English mixed clips)."""
    if dataset == "ujs/hinglish":
        text = row["sentence"]
    else:
        m = re.match(r"\s*<([\w-]+)>\s*(.*)", row["text"] or "", re.S)
        if not m or m.group(1) != "hi-en":
            return None
        text = m.group(2)
    text = DOUBLED.sub(r"\2", " ".join((text or "").split()))
    return text if re.search(r"[ऀ-ॿ]", text) else None  # it must have Hindi in it


def audio_of(cell):
    data, rate = sf.read(io.BytesIO(cell["bytes"]), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if rate != 16000:
        data = np.interp(np.linspace(0, len(data), int(len(data) * 16000 / rate), endpoint=False),
                         np.arange(len(data)), data).astype(np.float32)
    return data


def main():
    (OUT / "clips").mkdir(parents=True, exist_ok=True)
    manifest = OUT / "manifest.jsonl"
    done = {json.loads(line)["id"] for line in manifest.open(encoding="utf-8")} if manifest.exists() else set()
    total = {"train": 0.0, "test": 0.0}
    with manifest.open("a", encoding="utf-8") as out:
        for dataset, shard, split in SHARDS:
            table = pq.read_table(fetch(dataset, shard))
            kept = 0
            for i, row in enumerate(table.to_pylist()):
                if split == "test" and kept >= TEST_PER_SHARD:
                    break
                cid = f"{dataset.split('/')[0]}-{shard}-{i}"
                text = text_of(dataset, row)
                if not text:
                    continue
                if cid in done:
                    kept += 1
                    continue
                try:
                    audio = audio_of(row["audio"])
                except Exception:  # an unreadable clip
                    continue
                seconds = len(audio) / 16000
                if not 1.0 <= seconds <= 28.0 or len(text) > 400:  # Whisper hears 30 s at most
                    continue
                sf.write(OUT / "clips" / f"{cid}.wav", audio, 16000, subtype="PCM_16")
                out.write(json.dumps({"id": cid, "split": split, "text": text, "seconds": round(seconds, 2),
                                      "source": dataset}, ensure_ascii=False) + "\n")
                kept += 1
                total[split] += seconds
            print(f"{dataset} {shard}: {kept} clips", flush=True)
    print(f"new audio: {total['train'] / 3600:.1f} h train, {total['test'] / 3600:.1f} h test")


if __name__ == "__main__":
    sys.exit(main())
