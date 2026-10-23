"""Spoken replies, fully offline. Nothing is sent anywhere, and speech stops as soon as `stop` is set.

Three neural voices, all run by sherpa-onnx on the CPU and streamed sentence by sentence, so Nova starts talking
before the whole reply is made:
- Piper (en_US lessac, 64 MB): the default. Setup installs it. Whisper heard every word of it in a check.
- Kitten (nano, 25 MB): the lightest and fastest, 8 voices. Setup installs it too.
- Kokoro (330 MB): the most natural. Downloaded only when picked; until then Nova keeps talking with Piper.
If none is downloaded or one fails, Nova falls back to the operating system's voice (Windows SAPI, macOS `say`).

`python -m core.tts download [kokoro|piper|kitten]` fetches one into data/tts (core/models.py).
"""
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from core.system import IS_MAC, NO_WINDOW

ENGINES = ("piper", "kitten", "kokoro")  # the neural voices, as named in core/models.py and voice.tts_engine
# speaker IDs in the model's voices.bin, in order (stable per the model's README)
KOKORO_VOICES = ("af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky "
                 "am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa bf_alice bf_emma "
                 "bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis ef_dora em_alex ff_siwis hf_alpha hf_beta "
                 "hm_omega hm_psi if_sara im_nicola jf_alpha jf_gongitsune jf_nezumi jf_tebukuro jm_kumo pf_dora "
                 "pm_alex pm_santa zf_xiaobei zf_xiaoni zf_xiaoxiao zf_xiaoyi zm_yunjian zm_yunxi zm_yunxia "
                 "zm_yunyang em_santa").split()
# the voices that read English (and Roman Hinglish) well; the others are for their own languages
ENGLISH = [v for v in KOKORO_VOICES if v[0] in "ab" and v != "am_santa"]
KITTEN_VOICES = ("expr-voice-2-m expr-voice-2-f expr-voice-3-m expr-voice-3-f expr-voice-4-m expr-voice-4-f "
                 "expr-voice-5-m expr-voice-5-f").split()  # its voices.bin, in order

# stdin is UTF-8: without the first statement PowerShell reads it in the console code page and
# reads curly quotes, accents or the rupee sign aloud as garbage
SAPI = ("[Console]::InputEncoding = [Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "if ($env:NOVA_VOICE) { try { $s.SelectVoice($env:NOVA_VOICE) } catch {} }; "
        "$s.Speak([Console]::In.ReadToEnd())")

_models, _load_lock, _speak_lock = {}, threading.Lock(), threading.Lock()


def installed(engine):
    from core import models
    return models.installed(engine)


def keep_kokoro(marker, saved_voice, kokoro_installed):
    """Piper became the default voice: whoever already had Kokoro (the old default) and never chose a voice keeps
    hearing it. True means switch them to Kokoro. Decided once (the marker file): choosing Piper later saves nothing,
    since it's the default, so asking again would keep switching them back. `saved_voice`: the "voice" section of
    the user's own settings (config.json, not the defaults)."""
    if marker.exists():
        return False
    marker.touch()
    return "tts_engine" not in saved_voice and kokoro_installed


def capable(engine):
    """Can this computer run the voice well? Kokoro needs about 400 MB of memory on top of Nova's speech models and a
    few CPU cores to speak faster than it talks (4x real time on 16 threads here). Piper and Kitten run anywhere.
    shortcut: a rule of thumb (8 GB, 4 threads), not a measurement; time a sentence if people report a slow Kokoro."""
    from core import system
    return engine != "kokoro" or (system.memory_gb() >= 8 and (os.cpu_count() or 1) >= 4)


def preview(engine, voice):
    """The voice saying Nova's test line, recorded once (voice_previews/, about 25 KB each), as a data: URL the Nova
    window plays at once: no model to download or load just to hear it. None if there's no clip for it."""
    import base64
    clip = Path(__file__).resolve().parents[1] / "voice_previews" / f"{engine}-{voice or 'lessac'}.mp3"
    if engine not in ENGINES or not re.fullmatch(r"[\w-]+", voice or "lessac") or not clip.exists():
        return None
    return "data:audio/mpeg;base64," + base64.b64encode(clip.read_bytes()).decode()


def pick(v):
    """The neural voice to speak with for the voice settings `v`: the chosen one if it's downloaded, else Piper,
    else Kitten (so picking Kokoro never silences Nova while it downloads). None: the system voice."""
    if v.get("tts_engine") == "system":
        return None
    return next((e for e in (v.get("tts_engine"), "piper", "kitten") if e in ENGINES and installed(e)), None)


def speaker(engine, v):
    """The speaker number inside the engine's model for the voice settings `v`."""
    if engine == "kokoro":
        voice = v.get("kokoro_voice")
        return KOKORO_VOICES.index(voice if voice in KOKORO_VOICES else "af_heart")
    if engine == "kitten":
        voice = v.get("kitten_voice")
        return KITTEN_VOICES.index(voice if voice in KITTEN_VOICES else "expr-voice-2-f")
    return 0  # Piper's lessac model has one speaker


def load(engine):
    """Load one voice model once (Kokoro: about 1.5 s and 400 MB of memory). Safe to call from any thread."""
    with _load_lock:
        if engine not in _models:
            import sherpa_onnx
            from core import models
            d = models.path(engine)
            if engine == "kokoro":
                voice = {"kokoro": sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(d / "model.onnx"), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"),
                    data_dir=str(d / "espeak-ng-data"), dict_dir=str(d / "dict"),
                    lexicon=f"{d / 'lexicon-us-en.txt'},{d / 'lexicon-zh.txt'}")}
            elif engine == "kitten":
                voice = {"kitten": sherpa_onnx.OfflineTtsKittenModelConfig(
                    model=str(d / "model.fp16.onnx"), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"),
                    data_dir=str(d / "espeak-ng-data"))}
            else:
                voice = {"vits": sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(next(d.glob("*.onnx"))), tokens=str(d / "tokens.txt"),
                    data_dir=str(d / "espeak-ng-data"))}
            threads = max(1, min(8, (os.cpu_count() or 4) // 2))  # past 8 threads it gets no faster
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(num_threads=threads, provider="cpu", **voice),
                max_num_sentences=1)  # one sentence per chunk: the first one plays while the rest is made
            # one voice in memory at a time: all three held about 690 MB (Kokoro most), kept until Nova restarted.
            # A voice still talking keeps its own reference, so dropping the others here is safe.
            _models.clear()
            _models[engine] = sherpa_onnx.OfflineTts(config)
    return _models[engine]


def _speak_neural(text, engine, sid, speed, stop):
    import numpy as np
    import sounddevice as sd
    model = load(engine)
    chunks = queue.Queue()

    def on_audio(samples, _progress):
        chunks.put(np.array(samples, dtype=np.float32))
        return 0 if stop.is_set() else 1  # 0 tells sherpa-onnx to stop generating

    def generate():
        try:
            model.generate(text, sid=sid, speed=speed, callback=on_audio)
        finally:
            chunks.put(None)

    with _speak_lock:  # one voice at a time; a model isn't meant to run twice at once
        threading.Thread(target=generate, daemon=True).start()
        block = model.sample_rate // 10  # write 100 ms at a time so `stop` cuts in quickly
        with sd.OutputStream(samplerate=model.sample_rate, channels=1, dtype="float32") as out:
            while not stop.is_set():
                try:
                    chunk = chunks.get(timeout=0.1)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                for i in range(0, len(chunk), block):
                    if stop.is_set():
                        break
                    out.write(chunk[i:i + block])


def _speak_system(text, voice, stop):
    if IS_MAC:
        args, env = ["say"] + (["-v", voice] if voice else []), None
    else:  # the voice name goes through the environment, never into the command line
        args, env = ["powershell", "-NoProfile", "-Command", SAPI], dict(os.environ, NOVA_VOICE=voice or "")
    p = subprocess.Popen(args, stdin=subprocess.PIPE, text=True, encoding="utf-8", env=env, creationflags=NO_WINDOW)
    p.stdin.write(text)
    p.stdin.close()
    while p.poll() is None:
        if stop.is_set():
            p.kill()
        time.sleep(0.1)


def speak(text, v, stop):
    """Say `text` with the voice settings `v` (config["voice"])."""
    if not text.strip():
        return
    engine = pick(v)
    if engine:
        try:
            return _speak_neural(text, engine, speaker(engine, v), float(v.get("tts_speed") or 1.0), stop)
        except Exception as e:  # no sherpa-onnx, broken model or no speakers: still answer out loud
            print(f"The {engine} voice failed, using the system voice: {e!r}", file=sys.stderr)
    _speak_system(text, v.get("tts_voice"), stop)


def voices():
    """System voice names."""
    if IS_MAC:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        return [line.split("  ")[0].strip() for line in out.splitlines() if line.strip()]
    cmd = ("Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer)"
           ".GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    return [v.strip() for v in out.splitlines() if v.strip()]


def download(engine="kokoro"):
    """Fetch and unpack one voice model into data/tts, printing progress. Skips work already done."""
    from core import models
    models.download(engine, lambda line: print(line, flush=True))


if __name__ == "__main__" and sys.argv[1:2] == ["download"]:
    download(*sys.argv[2:3])
