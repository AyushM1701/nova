"""On-device models Nova downloads: the natural voice (Kokoro), the Parakeet and Orukeet speech engines and the
speaker-label (diarization) models. All run through sherpa-onnx on the CPU; nothing is sent anywhere.

Run `python -m core.models download <name>` to fetch one with progress lines (the Nova window does this).
"""
import os
import sys
import tarfile
import threading
import urllib.request
from pathlib import Path

from core.config import DATA

MODELS = DATA / "models"
SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
# name: (label, url, where it lives once unpacked (a folder, or the .onnx file itself), size shown to people)
DOWNLOADS = {
    "kokoro": ("Natural voice", f"{SHERPA}/tts-models/kokoro-multi-lang-v1_0.tar.bz2",
               DATA / "tts" / "kokoro-multi-lang-v1_0", "330 MB"),
    "kws": ("\"Hey Nova\" detector", f"{SHERPA}/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2",
            MODELS / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01", "18 MB"),
    "parakeet": ("Parakeet", f"{SHERPA}/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2",
                 MODELS / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8", "490 MB"),
    "orukeet": ("Orukeet", "https://huggingface.co/oruk/orukeet/resolve/55a984d46f68323301837194ce647c702f55facc/"
                "onnx/sherpa-onnx-orukeet-v0.1.0-int8.tar.bz2", MODELS / "sherpa-onnx-orukeet-v0.1.0-int8", "490 MB"),
    "segmentation": ("Speaker segmentation", f"{SHERPA}/speaker-segmentation-models/"
                     "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2", MODELS / "sherpa-onnx-pyannote-segmentation-3-0",
                     "7 MB"),
    "embedding": ("Speaker voices", f"{SHERPA}/speaker-recongition-models/"
                  "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx",
                  MODELS / "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx", "28 MB"),
}
# Parakeet v3 and its Orukeet fine-tune understand these 25 languages; Hindi isn't one of them
LANGUAGES = set("bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro sk sl es sv ru uk".split())


def path(name):
    return DOWNLOADS[name][2]


def installed(name):
    p = path(name)
    return p.is_file() if p.suffix == ".onnx" else (p / "tokens.txt").exists() or (p / "model.onnx").exists()


def download(name, say=print):
    """Fetch and unpack one model into data/models, reporting progress. Skips work already done."""
    label, url, where, _ = DOWNLOADS[name]
    if installed(name):
        return say(f"{label} is already downloaded.")
    where.parent.mkdir(parents=True, exist_ok=True)
    part = where.parent / f"{name}.part"
    with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
        total, done, shown = int(r.headers.get("Content-Length") or 0), 0, -1
        while block := r.read(1 << 20):
            f.write(block)
            done += len(block)
            if done >> 23 != shown:  # every 8 MB
                shown = done >> 23
                say(f"{label}: {done >> 20} of {total >> 20} MB")
    if url.endswith(".onnx"):
        part.replace(path(name))
    else:
        say("Unpacking…")
        with tarfile.open(part, "r:bz2") as tar:
            try:
                tar.extractall(where.parent, filter="data")  # refuses absolute paths, "..", and links out of it
            except TypeError:  # Python 3.11 before 3.11.4 has no filter argument: check the names ourselves
                if any(n.startswith(("/", "\\")) or ".." in Path(n).parts for n in tar.getnames()):
                    raise ValueError("unexpected paths in the model download")
                tar.extractall(where.parent)
        part.unlink()
    say(f"{label} ready.")


class Transducer:
    """Parakeet or Orukeet. Same interface as whisper_cpp.Server: transcribe(audio, language, prompt) -> text.
    The prompt (Whisper's vocabulary hint) has no equivalent here and is ignored."""

    def __init__(self, name):
        if not installed(name):
            raise RuntimeError(f"{DOWNLOADS[name][0]} isn't downloaded yet. Download it in Nova's settings, Voice.")
        self.name, self.recognizer, self.lock = name, None, threading.Lock()

    def load(self):
        with self.lock:
            if self.recognizer is None:
                import sherpa_onnx
                d = path(self.name)
                self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
                    joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"), model_type="nemo_transducer",
                    num_threads=max(1, min(8, (os.cpu_count() or 4) // 2)))
        return self.recognizer

    def transcribe(self, audio, language, prompt):
        recognizer = self.load()
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, audio)
        recognizer.decode_stream(stream)
        return " ".join(stream.result.text.split())


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "download":
    download(sys.argv[2], lambda line: print(line, flush=True))
