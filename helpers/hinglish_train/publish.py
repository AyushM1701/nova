"""Step 5: publish the trained model on Hugging Face, where every Nova downloads it (core/stt.py load_hindi /
load_accurate). Run it yourself, after logging in once with your own token:

    data/hinglish-train/.venv/Scripts/hf.exe auth login
    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/publish.py [--repo AyushM1701/nova-whisper-hinglish]
    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/publish.py --card-only   (write the card, upload nothing)

Writes the model card (README.md) into $HINGLISH_DIR/ct2 from sources.json and scores.json, then uploads the folder.
Only for a model trained on the licensed mix (prepare.py): CC BY 4.0 sources, plus MUCS (CC BY-SA 4.0), whose
share-alike term makes the model CC BY-SA 4.0. A source under any other license stops it."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT  # noqa: E402

REPO = "AyushM1701/nova-whisper-hinglish"


def card(repo):
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
    corpora = sorted({c for m in scores.values() for c in m})
    table = "\n".join(f"| {c} | " + " | ".join(f"{scores[m][c]['wer']:.1%}" if c in scores[m] else "-" for m in scores) + " |"
                      for c in corpora)
    header = "| Test set | " + " | ".join(scores) + " |\n|---|" + "---|" * len(scores)
    return f"""---
license: {license_id}
base_model: openai/whisper-large-v3-turbo
language: [en, hi]
tags: [whisper, ctranslate2, faster-whisper, hinglish, code-switching, speech-recognition]
---
# Nova Whisper Hinglish

Whisper large-v3-turbo, fine-tuned (a LoRA on the decoder, merged) so that **one model** hears English, Hindi and
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
same words.

## Word error rate on held-out clips
{header}
{table}

## License
{license_name}, crediting the corpora above{" (MUCS 2021 is CC BY-SA 4.0: shared alike)" if sa else ""}; the base
model, Whisper, is MIT (OpenAI).
"""


def main():
    repo = sys.argv[sys.argv.index("--repo") + 1] if "--repo" in sys.argv else REPO
    (OUT / "ct2" / "README.md").write_text(card(repo), encoding="utf-8")
    print(f"model card: {OUT / 'ct2' / 'README.md'}")
    if "--card-only" in sys.argv:
        return
    from huggingface_hub import create_repo, upload_folder
    create_repo(repo, repo_type="model", exist_ok=True)
    upload_folder(repo_id=repo, folder_path=str(OUT / "ct2"), repo_type="model",
                  commit_message="Nova Whisper Hinglish: English, Hindi and Hinglish in one model")
    print(f"published: https://huggingface.co/{repo}")


if __name__ == "__main__":
    main()
