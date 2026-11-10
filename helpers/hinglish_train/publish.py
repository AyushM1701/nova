"""Step 5: publish the trained model on Hugging Face, where every Nova downloads it (core/stt.py
load_accurate). Run it yourself, after logging in once with your own token:

    data/hinglish-train/.venv/Scripts/hf.exe auth login
    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/publish.py [--repo AyushM1701/nova-whisper-hinglish]
    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/publish.py --card-only   (write the card, upload nothing)
    ... publish.py --dir v2   (a later run: $HINGLISH_DIR/v2/ct2, scored in scores.json as "v2")

Writes the model card (README.md) into $HINGLISH_DIR/ct2 from sources.json and scores.json, then uploads the folder.
Only for a model trained on the licensed mix (prepare.py): CC BY 4.0 sources, plus MUCS (CC BY-SA 4.0), whose
share-alike term makes the model CC BY-SA 4.0. A source under any other license stops it."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT  # noqa: E402

REPO = "AyushM1701/nova-whisper-hinglish"


def card(repo, key="trained"):
    sources = json.loads((OUT / "sources.json").read_text(encoding="utf-8"))
    scores = json.loads((OUT / "scores.json").read_text(encoding="utf-8")) if (OUT / "scores.json").exists() else {}
    licenses = {s["license"] for s in sources}
    if not licenses <= {"CC BY 4.0", "CC BY-SA 4.0"}:  # another license changes what the model may be released as
        raise SystemExit(f"Sources have other licenses ({licenses}): check before publishing.")
    sa = "CC BY-SA 4.0" in licenses
    license_name, license_id = ("CC BY-SA 4.0", "cc-by-sa-4.0") if sa else ("CC BY 4.0", "cc-by-4.0")
    of = {s["corpus"]: s["license"] for s in sources}
    hours = {}
    for s in sources:
        if s["split"] == "train":
            hours[(s["corpus"], s["url"], s["lang"])] = hours.get((s["corpus"], s["url"], s["lang"]), 0) + s["hours"]
    rows = "\n".join(f"| {c} | {'Hindi / Hinglish' if lang == 'hi' else 'English'} | {h:.1f} h | {of[c]} | {u} |"
                     for (c, u, lang), h in sorted(hours.items()))
    # only stock turbo and this model, under names a reader knows (scores.json may hold other models too)
    shown = {"today: turbo + Hinglish prompt": "Whisper large-v3-turbo", key: "This model"}
    scores = {shown[m]: v for m, v in scores.items() if m in shown}
    corpora = sorted({c for m in scores.values() for c in m})

    def cell(m, c, k):
        return f"{scores[m][c][k]:.1%}" if k in scores[m].get(c, {}) else "-"
    table = "\n".join(f"| {c} | " + " | ".join(f"{cell(m, c, 'wer')} / {cell(m, c, 'twer')}" for m in scores) + " |"
                      for c in corpora)
    header = "| Test set | " + " | ".join(scores) + " |\n|---|" + "---|" * len(scores)
    made = OUT / ("" if key == "trained" else key) / "training.json"  # v1 predates it: the decoder only, no splicing
    how = json.loads(made.read_text(encoding="utf-8")) if made.exists() else {}
    trained = "a LoRA on the decoder" + (f" and the encoder's last {how['encoder_layers']} layers"
                                         if how.get("encoder_layers") else "") + ", merged"
    spliced = (f" A further {how['splice']:.0%} of clips were made by joining a Hindi clip and an English one, so the model"
               " hears language switch inside a sentence (code-mix splicing).") if how.get("splice") else ""
    return f"""---
license: {license_id}
base_model: openai/whisper-large-v3-turbo
language: [en, hi]
tags: [whisper, ctranslate2, faster-whisper, hinglish, code-switching, speech-recognition]
---
# Nova Whisper Hinglish

Whisper large-v3-turbo, fine-tuned ({trained}) so that **one model** hears English, Hindi and
Hinglish, and **writes Hindi in Roman letters** ("kal meeting cancel kar do"), the way people type it. Made for
[Nova](https://github.com/AyushM1701/nova), which downloads it automatically; any faster-whisper program can use it.

```python
from faster_whisper import WhisperModel
model = WhisperModel("{repo}", device="cuda", compute_type="float16")
segments, _ = model.transcribe("speech.wav", language="hi")   # Hindi / Hinglish, in Roman letters
segments, _ = model.transcribe("speech.wav", language="en")   # English
```
Detect the language first (`model.detect_language`, between `en` and `hi`) and decode with it, as Nova does.

## Training data
| Corpus | Language | Hours | License | Source |
|---|---|---|---|---|
{rows}

Clips from the [agarwalayushi/hinglish](https://huggingface.co/datasets/agarwalayushi/hinglish) aggregate are only those
of its corpora licensed CC BY 4.0 (by clip source). Hindi transcripts were written in Roman letters by rule (spoken
words kept, never translated); LibriSpeech's capitals were cased and punctuated where stock Whisper heard exactly the
same words.{spliced}

## Word error rate on held-out clips
Word error rate / Roman word error rate (any Devanagari in a model's output converted to Roman letters first, by the
same rules as the references, so a model is charged for its words, not its script). Lower is better.

{header}
{table}

## License
{license_name}, crediting the corpora above{" (MUCS 2021 is CC BY-SA 4.0: shared alike)" if sa else ""}; the base
model, Whisper, is MIT (OpenAI).
"""


def main():
    repo = sys.argv[sys.argv.index("--repo") + 1] if "--repo" in sys.argv else REPO
    run = sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv else ""  # a later run, e.g. v2 (train.py --name)
    folder = OUT / run / "ct2"
    (folder / "README.md").write_text(card(repo, run or "trained"), encoding="utf-8")
    print(f"model card: {folder / 'README.md'}")
    if "--card-only" in sys.argv:
        return
    from huggingface_hub import create_repo, upload_folder
    create_repo(repo, repo_type="model", exist_ok=True)
    upload_folder(repo_id=repo, folder_path=str(folder), repo_type="model",
                  commit_message="Nova Whisper Hinglish: English, Hindi and Hinglish in one model")
    print(f"published: https://huggingface.co/{repo}")


if __name__ == "__main__":
    main()
