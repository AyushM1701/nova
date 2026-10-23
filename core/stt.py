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

from core.cleanup import drop_outro, is_prompt_echo  # noqa: E402


# softer speech passes (default threshold 0.5), and 300 ms of padding keeps the first and last words whole
VAD = {"threshold": 0.35, "speech_pad_ms": 300}


class STT:
    def __init__(self, fast_name, accurate_name):
        self.fast_name, self.accurate_name, self.accurate, self.small = fast_name, accurate_name, None, None
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

    def translator(self):
        """Whisper's turbo models were trained without translation (they write the language spoken), so translating
        uses the small model: the CPU's own fast one, or loaded once beside turbo on a GPU."""
        if self.device == "CPU":
            return self.fast
        if self.small is None:
            self.small = WhisperModel(self.fast_name, device="cuda", compute_type="float16")
        return self.small

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

    def segments(self, audio, language="auto", vocabulary=(), on_progress=None):
        """A long recording (a meeting, an audio file) as [{start, end, text}] with times in seconds. Uses the
        accurate model when it's loaded; on_progress(fraction) as it goes."""
        prompt = ("Vocabulary: " + ", ".join(vocabulary) + ".") if vocabulary else None
        model = self.accurate or self.fast
        found, info = model.transcribe(audio, language=None if language == "auto" else language, initial_prompt=prompt,
                                       vad_filter=True, vad_parameters=VAD, beam_size=1,
                                       condition_on_previous_text=False)
        out, total, shown = [], max(1.0, len(audio) / 16000), -1
        for s in found:
            text = drop_outro(s.text.strip())
            if text:
                out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
            percent = int(min(1.0, s.end / total) * 100)
            if on_progress and percent != shown:  # once per percent, not once per segment (hundreds an hour)
                shown = percent
                on_progress(percent / 100)
        return out

    def transcribe(self, audio, language="auto", vocabulary=(), server=None, task="transcribe"):
        """What was said. `server` (whisper.cpp, Parakeet, a cloud service) decodes instead of faster-whisper when
        given. task="translate" writes English whatever language was spoken (Whisper's own translation)."""
        prompt = ("Vocabulary: " + ", ".join(vocabulary) + ".") if vocabulary else None
        lang = None if language == "auto" else language

        def run(model, vad=True):
            # greedy decoding keeps English words in Latin letters inside Hinglish speech
            segments, info = model.transcribe(audio, language=lang, task=task, initial_prompt=prompt, vad_filter=vad,
                                              vad_parameters=VAD if vad else None,
                                              beam_size=1, condition_on_previous_text=False)
            return " ".join(s.text.strip() for s in segments).strip(), info.language

        if server:
            return drop_outro(server.transcribe(audio, lang, prompt))
        first = self.translator() if task == "translate" else self.fast
        text, detected = run(first)
        # the small model is weak at other languages: the accurate one takes them (CPU only, once it's loaded),
        # except to translate, which it can't do
        model = self.accurate if task == "transcribe" and detected != "en" and self.accurate else first
        if model is not first:
            text, _ = run(model)
        if is_prompt_echo(text, prompt):  # the voice filter cut the speech: decode everything once more
            text = run(model, vad=False)[0] or text
        return drop_outro(text)
