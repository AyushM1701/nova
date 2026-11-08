"""Step 1 of training Nova's speech model: download a slice of licensed speech in English, Hindi and Hinglish.

    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/prepare.py

Only sources whose licenses allow a model trained on them to be shipped with Nova, all CC BY 4.0:
- agarwalayushi/hinglish (an aggregate), only the clips from its CC BY 4.0 corpora, picked by name: NPTEL lectures
  (Hindi and Hinglish), Kathbath (read Hindi), IndicTTS (studio Hindi), Mann Ki Baat (Indian English). Its other
  corpora ("See source": ujs, Orpheus and single-voice TTS sets, unnamed YouTube clips) are left out.
- LibriSpeech train-clean-100 and test-clean (English).
Writes $HINGLISH_DIR (default data/hinglish-ship)/clips/<id>.wav (16 kHz mono), manifest.jsonl lines
{id, split, lang, text, seconds, source} and sources.json (what the model card credits). Resumable."""
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT  # noqa: E402

API = "https://huggingface.co/api/datasets/{}/parquet/{}/{}.parquet"
AGG, LIBRI = "agarwalayushi/hinglish", "openslr/librispeech_asr"
# the aggregate's clips name their corpus; these are its CC BY 4.0 ones (its card's source table)
LICENSED = {"nptel_hin_": "NPTEL Hindi lectures (ai4bharat/Spoken-Tutorial)", "kathbath_hin_": "Kathbath (ai4bharat)",
            "indictts_hin_": "IndicTTS Hindi (SPRINGLab)", "mann_ki_baat_": "Mann Ki Baat (ai4bharat)"}
# (dataset, path, shard, split): the aggregate is ordered by corpus, so shards are picked across each one's range
SHARDS = ([(AGG, "default/train", n, "train") for n in range(300, 771, 15)]       # NPTEL: 32 shards (it ends near 779)
          + [(AGG, "default/train", n, "train") for n in (150, 175, 200)]          # Kathbath
          + [(AGG, "default/train", n, "train") for n in (250, 265)]               # IndicTTS
          + [(AGG, "default/train", n, "train") for n in (800, 803, 806, 809)]     # Mann Ki Baat, English
          + [(LIBRI, "all/train.clean.100", n, "train") for n in (0, 5, 10)]
          + [(AGG, "default/train", 775, "test"), (AGG, "default/train", 225, "test"), (AGG, "default/train", 812, "test"),
             (LIBRI, "all/test.clean", 0, "test")])
TEST_PER_SHARD = 250  # held-out clips from each test shard
DOUBLED = re.compile(r"([ऀ-ॿ]+)([A-Za-z]+)")  # "लूपloop": a word written twice, Hindi then English
CARDS = {AGG: ("https://huggingface.co/datasets/agarwalayushi/hinglish", "CC BY 4.0"),
         LIBRI: ("https://www.openslr.org/12", "CC BY 4.0")}


def fetch(dataset, path, shard):
    file = OUT / "raw" / f"{dataset.replace('/', '_')}-{path.replace('/', '_')}-{shard}.parquet"
    if not file.exists():
        file.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {dataset} {path} shard {shard}", flush=True)
        part = file.with_suffix(".part")
        with urllib.request.urlopen(API.format(dataset, path, shard), timeout=120) as r, open(part, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        part.rename(file)
    return file


def clip_of(dataset, row):
    """(lang, text, corpus) for a clip to keep, or None to leave it out."""
    if dataset == LIBRI:
        return "en", " ".join(row["text"].split()), "LibriSpeech"
    corpus = next((name for prefix, name in LICENSED.items() if (row.get("source") or "").startswith(prefix)), None)
    m = re.match(r"\s*<([\w-]+)>\s*(.*)", row.get("text") or "", re.S)
    if not corpus or not m:
        return None
    text = DOUBLED.sub(r"\2", " ".join(m.group(2).split()))
    if m.group(1) in ("hi", "hi-en"):
        return ("hi", text, corpus) if re.search(r"[ऀ-ॿ]", text) else None
    if m.group(1) in ("en", "en-in"):
        return "en", text, corpus
    return None


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
    rows = [json.loads(line) for line in manifest.open(encoding="utf-8")] if manifest.exists() else []
    done = {r["id"] for r in rows}
    with manifest.open("a", encoding="utf-8") as out:
        for dataset, path, shard, split in SHARDS:
            table = pq.read_table(fetch(dataset, path, shard))
            kept = 0
            for i, row in enumerate(table.to_pylist()):
                if split == "test" and kept >= TEST_PER_SHARD:
                    break
                clip = clip_of(dataset, row)
                if not clip:
                    continue
                lang, text, corpus = clip
                cid = f"{'libri' if dataset == LIBRI else 'agg'}-{path.split('/')[-1]}-{shard}-{i}"
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
                entry = {"id": cid, "split": split, "lang": lang, "text": text, "seconds": round(seconds, 2),
                         "source": corpus, "dataset": dataset}
                out.write(json.dumps(entry, ensure_ascii=False) + "\n")
                rows.append(entry)
                kept += 1
            out.flush()
            print(f"{dataset} {path} {shard}: {kept} clips", flush=True)
    hours = {}
    for r in rows:
        key = (r["dataset"], r["source"], r["split"], r["lang"])
        hours[key] = hours.get(key, 0.0) + r["seconds"] / 3600
    sources = [{"dataset": d, "corpus": c, "split": s, "lang": lang, "hours": round(h, 1), "url": CARDS[d][0],
                "license": CARDS[d][1]} for (d, c, s, lang), h in sorted(hours.items())]
    (OUT / "sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    for s in sources:
        print(f"{s['split']:5} {s['lang']}  {s['hours']:6.1f} h  {s['corpus']}")


if __name__ == "__main__":
    sys.exit(main())
