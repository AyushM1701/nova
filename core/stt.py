"""Offline speech-to-text with faster-whisper, biased toward the personal dictionary (Wispr's StaticVocabulary).

NVIDIA GPU (Windows): the accurate model handles everything in well under a second.
CPU (and every Mac): the fast model handles English; when it hears another language (Hindi, Hinglish) the
accurate model re-transcribes, because `small` drops and garbles Hindi words.

Setup downloads only the fast model (about 480 MB), so dictation works minutes sooner; the accurate one (1.6 GB)
downloads in the background the first time Nova runs (load_accurate), and the GPU switches to it then.
"""
import glob
import os
import sys
import threading

import numpy as np

# CUDA DLLs come from the nvidia-* pip packages inside the venv (installed by setup on NVIDIA PCs)
if os.name == "nt":
    for _d in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin")):
        os.add_dll_directory(_d)
        os.environ["PATH"] = _d + os.pathsep + os.environ["PATH"]

from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.utils import download_model  # noqa: E402
from faster_whisper.vad import VadOptions  # noqa: E402

from core.cleanup import drop_outro, fix_vocabulary, is_prompt_echo  # noqa: E402

_doubt = threading.local()  # per thread: what the last transcribe() doubted, and the language it heard


# softer speech passes (default threshold 0.5), 300 ms of padding keeps the first and last words whole, and a pause
# of half a second (not the default two) is cut out, breath and room hiss with it
VAD = {"threshold": 0.35, "speech_pad_ms": 300, "min_silence_duration_ms": 500}
# Whisper copies its prompt's style: a line of Roman Hinglish makes it write Hindi words in Roman letters
HINGLISH = "Haan, theek hai. Kal milte hain, aur woh file bhej dena."
ALIKE = {"ur": "hi"}  # Whisper often names spoken Hindi Urdu: it is the same speech, and the user speaks Hindi
HINDI = "en-prompt"  # how a Hindi or mixed clip is decoded; helpers/stt_bench.py compares them on the user's voice


def prompt_for(vocabulary, hindi=False):
    """What Whisper reads before the speech: the user's names in a punctuated sentence, and Hinglish for Hindi clips."""
    names = ("Names: " + ", ".join(vocabulary) + ".") if vocabulary else ""
    return " ".join(part for part in (HINGLISH if hindi else "", names) if part) or None


def _cached(name):
    """The downloaded copy's folder, or None. Hugging Face marks a version as the current one before its files arrive,
    and calls a folder downloaded without looking inside: a download cut short (Nova closed during it) leaves one
    without model.bin, which would fail to load on the GPU and drop Nova to the CPU."""
    try:
        path = download_model(str(name), local_files_only=True)
    except Exception:  # not in the cache yet
        return None
    return None if os.path.isdir(path) and not os.path.isfile(os.path.join(path, "model.bin")) else path


def downloaded(name):
    # a model folder on this computer (one trained with helpers/hinglish_train), or a complete download
    return os.path.isdir(str(name)) or _cached(name) is not None


def _local(name):
    """The copy already downloaded, so starting Nova never waits on the network (given a name, faster-whisper asks
    Hugging Face first, and would download a whole new release then). STT.refresh fetches new releases."""
    return str(name) if os.path.isdir(str(name)) else _cached(name) or str(name)


def _prune(keep):
    """Delete the other downloaded versions of the model at `keep` (a snapshot folder): each release leaves the
    previous one, 1.6 GB, in Hugging Face's cache. Failing, they stay."""
    try:
        from huggingface_hub import scan_cache_dir
        cache = scan_cache_dir()
        repo = os.path.normcase(os.path.dirname(os.path.dirname(os.path.normpath(keep))))
        old = [r.commit_hash for found in cache.repos if os.path.normcase(str(found.repo_path)) == repo
               for r in found.revisions if r.commit_hash != os.path.basename(os.path.normpath(keep))]
        if old:
            cache.delete_revisions(*old).execute()
    except Exception:  # a file in use, or the cache layout changed: nothing lost but disk space
        pass


def _model(name, gpu):
    """A WhisperModel on the GPU or CPU. `nova_roman` marks one trained on Hinglish (helpers/hinglish_train: its name says
    "hinglish"): its "hi" mode writes Hindi in Roman letters by itself, so it needs no Hinglish prompt."""
    model = WhisperModel(_local(name), device="cuda" if gpu else "cpu", compute_type="float16" if gpu else "int8")
    model.nova_roman = "hinglish" in str(name).lower()
    return model


def unsure(segment):
    """Whisper's own signs that a segment isn't speech it understood: it hears silence (and guesses anyway), or it loops on
    one phrase (a compression ratio over 2.4) the way it does on a stuck microphone or a video playing nearby."""
    silent = getattr(segment, "no_speech_prob", 0) > 0.6 and getattr(segment, "avg_logprob", 0) < -1.0
    return silent or getattr(segment, "compression_ratio", 0) > 2.4  # the test doubles in tests.py have neither field


class STT:
    likely = ("en", "hi")  # the languages the user speaks (voice.languages); a detection outside them is a guess
    @property
    def shaky(self):
        """The last transcribe() on this thread contained a segment Whisper itself wasn't sure was speech. Per thread:
        the computer-audio and meeting transcriptions run alongside, and must not flag a command they didn't hear."""
        return getattr(_doubt, "shaky", False)

    @shaky.setter
    def shaky(self, value):
        _doubt.shaky = value

    def __init__(self, fast_name, accurate_name):
        self.fast_name, self.accurate_name, self.accurate, self.small = fast_name, accurate_name, None, None
        try:
            if sys.platform == "darwin":  # no NVIDIA GPU on a Mac: go straight to the CPU (int8 is fast on Apple chips)
                raise RuntimeError("no CUDA on macOS")
            # the accurate model once it's downloaded; until then the fast one, still on the GPU, which is then
            # also the one that translates (no second copy of it)
            have = downloaded(accurate_name)
            self.fast = _model(accurate_name if have else fast_name, gpu=True)
            self.small = None if have else self.fast
            self.fast.transcribe(np.zeros(16000, dtype=np.float32))  # fails here if cuDNN/cuBLAS can't load
            self.device = "GPU"
        except Exception:
            self.small = None
            self.fast = _model(fast_name, gpu=False)
            self.device = "CPU"

    def load_accurate(self):
        """Download the accurate model if setup didn't (slow: run it in the background), then use it."""
        if not self.accurate_name:
            return
        had = downloaded(self.accurate_name)
        if not had:
            download_model(self.accurate_name)
            if self.device == "GPU":  # the fast model stood in until now; it stays as self.small, for translation
                self.fast = _model(self.accurate_name, gpu=True)
        if self.device == "CPU":
            self.accurate = _model(self.accurate_name, gpu=False)
        if had:  # after it's in use: a new release downloads meanwhile, for the next start
            self.refreshed = self.refresh()

    refreshed = False  # load_accurate downloaded a new release of the model, used from the next start

    def refresh(self):
        """A new release of the accurate model (Nova Whisper Hinglish v2, say), downloaded in the background: only the
        files that changed. True when there was one; offline, nothing happens."""
        if os.path.isdir(str(self.accurate_name)):
            return False
        before = _local(self.accurate_name)
        if os.path.isdir(before):
            _prune(before)
        try:
            return download_model(str(self.accurate_name)) != before
        except Exception:  # offline, or Hugging Face is down: the copy on disk stays
            return False

    def translator(self):
        """Whisper's turbo models were trained without translation (they write the language spoken), so translating
        uses the small model: the CPU's own fast one, or loaded once beside turbo on a GPU. An everyday model that is
        itself a turbo can't translate either: small is loaded for it."""
        if "turbo" in str(getattr(self, "fast_name", "")).lower():
            if getattr(self, "_translate", None) is None:
                self._translate = _model("small", gpu=self.device == "GPU")
            return self._translate
        if self.device == "CPU":
            return self.fast
        if self.small is None:
            self.small = WhisperModel(_local(self.fast_name), device="cuda", compute_type="float16")
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

    @property
    def heard(self):
        """(language, how sure) of the last transcribe() on this thread: ("hi", 0.9), or ("", 0) when not detected."""
        return getattr(_doubt, "heard", ("", 0.0))

    @heard.setter
    def heard(self, value):
        _doubt.heard = value

    def pick(self, model, audio):
        """The language spoken, chosen among the user's own (`likely`): (code, its share of their probability).
        Whisper picks from 99 on a second or two of speech and guesses wrong (a short "okay" as Telugu)."""
        # unlike transcribe(), detect_language() takes the voice filter's settings only as VadOptions
        _, _, ranked = model.detect_language(audio, vad_filter=True, vad_parameters=VadOptions(**VAD))
        mine = {}
        for code, p in ranked:
            code = ALIKE.get(code, code)
            if code in self.likely:
                mine[code] = mine.get(code, 0.0) + p
        if not mine:
            return self.likely[0], 0.0
        best = max(mine, key=mine.get)
        return best, mine[best] / (sum(mine.values()) or 1)

    def transcribe(self, audio, language="auto", vocabulary=(), server=None, task="transcribe", hindi=None):
        """What was said. `server` (whisper.cpp, Parakeet, a cloud service) decodes instead of faster-whisper when
        given; `hindi` (Sarvam) decodes only clips heard as Hindi. task="translate" writes English whatever language was
        spoken (Whisper's own translation)."""
        prompt = prompt_for(vocabulary)
        lang = None if language == "auto" else language
        peak = float(np.percentile(np.abs(audio), 99.5)) if audio is not None and len(audio) else 0.0  # not the max: one click
        if 0.01 < peak < 0.3:  # a quiet microphone (peaks near 0.05 are in the logs): Whisper hears far worse the softer it is
            audio = audio * min(0.7 / peak, 10.0)
        self.shaky, self.heard = False, ("", 0.0)  # a server (whisper.cpp, a cloud service) decodes without them

        def run(model, language, prompt, vad=True):
            """(text, average log-probability): how sure Whisper was of its words."""
            # greedy decoding keeps English words in Latin letters inside Hinglish speech
            segments, _ = model.transcribe(audio, language=language, task=task, initial_prompt=prompt, vad_filter=vad,
                                           vad_parameters=VAD if vad else None,
                                           beam_size=1, condition_on_previous_text=False)
            segments = list(segments)
            self.shaky = any(unsure(s) for s in segments)
            sure = sum(getattr(s, "avg_logprob", 0.0) for s in segments) / max(1, len(segments))
            return " ".join(s.text.strip() for s in segments).strip(), sure

        if server:
            return drop_outro(server.transcribe(audio, lang, prompt))
        first = self.translator() if task == "translate" else self.fast
        if lang is None and task == "transcribe" and self.likely:
            lang, sure = self.pick(first, audio)
            self.heard = (lang, round(sure, 2))
        if hindi is not None and task == "transcribe" and lang == "hi":  # failing, it raises: Nova falls back to Whisper
            return fix_vocabulary(drop_outro(hindi.transcribe(audio, "hi", None)), vocabulary)
        other = task == "transcribe" and lang not in (None, "en")
        # the small model is weak at other languages: the accurate one takes them (CPU only, once it's loaded),
        # except to translate, which it can't do
        model = self.accurate if other and self.accurate else first
        if other and lang == "hi" and getattr(model, "nova_roman", False):  # trained on Hinglish: writes Roman letters by itself
            used = "hi"
            text = run(model, "hi", prompt)[0]
        elif other and lang == "hi":  # Hindi or Hinglish, written in Roman letters (HINDI says how)
            styled = prompt_for(vocabulary, hindi=True)
            tries = {"en-prompt": [("en", styled)], "hi-prompt": [("hi", styled)], "hi": [("hi", prompt)],
                     "both": [("en", styled), ("hi", styled)]}[HINDI]
            (text, _), used, prompt = max(((run(model, code, p), code, p) for code, p in tries), key=lambda r: r[0][1])
        else:
            used = lang
            text = run(model, lang, prompt)[0]
        if is_prompt_echo(text, prompt):  # the voice filter cut the speech: decode everything once more
            text = run(model, used, prompt, vad=False)[0] or text
        return fix_vocabulary(drop_outro(text), vocabulary)
