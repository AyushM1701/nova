"""Offline speech-to-text with faster-whisper, biased toward the personal dictionary (Wispr's StaticVocabulary).

NVIDIA GPU (Windows): the accurate model handles everything in well under a second.
CPU (and every Mac): the fast model handles English; when it hears another language (Hindi, Hinglish) the
accurate model re-transcribes, because `small` drops and garbles Hindi words.
"""
import glob
import os
import sys

import numpy as np

# CUDA DLLs come from the nvidia-* pip packages inside the venv (installed by setup on NVIDIA PCs)
if os.name == "nt":
    for _d in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin")):
        os.add_dll_directory(_d)
        os.environ["PATH"] = _d + os.pathsep + os.environ["PATH"]

from faster_whisper import WhisperModel  # noqa: E402


# softer speech passes (default threshold 0.5), and 300 ms of padding keeps the first and last words whole
VAD = {"threshold": 0.35, "speech_pad_ms": 300}


class STT:
    def __init__(self, fast_name, accurate_name):
        self.accurate_name, self.accurate = accurate_name, None
        try:
            if sys.platform == "darwin":  # no NVIDIA GPU on a Mac: go straight to the CPU (int8 is fast on Apple chips)
                raise RuntimeError("no CUDA on macOS")
            self.fast = WhisperModel(accurate_name, device="cuda", compute_type="float16")
            self.fast.transcribe(np.zeros(16000, dtype=np.float32))  # fails here if cuDNN/cuBLAS can't load
            self.device = "GPU"
        except Exception:
            self.fast = WhisperModel(fast_name, device="cpu", compute_type="int8")
            self.device = "CPU"

    def load_accurate(self):
        if self.device == "CPU" and self.accurate_name:
            self.accurate = WhisperModel(self.accurate_name, device="cpu", compute_type="int8")

    def quick(self, audio):
        """One fast English pass to spot "Hey Nova": [(word, end_seconds)]. No prompt: Whisper can echo one on noise."""
        segments, _ = self.fast.transcribe(audio, language="en", vad_filter=True, vad_parameters=VAD, beam_size=1,
                                           condition_on_previous_text=False, word_timestamps=True)
        return [(w.word.strip(), w.end) for s in segments for w in s.words]

    def answer(self, audio, expect):
        """A one- or two-word reply to a question ("allow" / "deny"): English, primed with what to expect.
        Without it, an accented "allow" often comes out as "Hello"."""
        segments, _ = self.fast.transcribe(audio, language="en", initial_prompt=expect, vad_filter=True,
                                           vad_parameters=VAD, beam_size=1, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()

    def transcribe(self, audio, language="auto", vocabulary=()):
        prompt = ("Vocabulary: " + ", ".join(vocabulary) + ".") if vocabulary else None
        lang = None if language == "auto" else language

        def run(model):
            # greedy decoding keeps English words in Latin letters inside Hinglish speech
            segments, info = model.transcribe(audio, language=lang, initial_prompt=prompt, vad_filter=True,
                                              vad_parameters=VAD,
                                              beam_size=1, condition_on_previous_text=False)
            return " ".join(s.text.strip() for s in segments).strip(), info.language

        text, detected = run(self.fast)
        if detected != "en" and self.accurate:  # CPU only; while it is still loading, keep the fast result
            text, _ = run(self.accurate)
        return text
