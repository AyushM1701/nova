"""Spoken replies, fully offline. Nothing is sent anywhere, and speech stops as soon as `stop` is set.

The natural voice is Kokoro (Apache-2.0, 82M parameters) run by sherpa-onnx on the CPU: it is streamed
sentence by sentence, so Nova starts talking before the whole reply is synthesised. If its model isn't
downloaded or anything fails, Nova falls back to the operating system's voice (Windows SAPI, macOS `say`).

`python -m core.tts download` fetches the Kokoro model (about 330 MB) into data/tts (used by setup).
"""
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from core.system import IS_MAC, NO_WINDOW

KOKORO = Path(__file__).resolve().parents[1] / "data" / "tts" / "kokoro-multi-lang-v1_0"
KOKORO_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-multi-lang-v1_0.tar.bz2"
# speaker IDs in the model's voices.bin, in order (stable per the model's README)
KOKORO_VOICES = ("af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky "
                 "am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa bf_alice bf_emma "
                 "bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis ef_dora em_alex ff_siwis hf_alpha hf_beta "
                 "hm_omega hm_psi if_sara im_nicola jf_alpha jf_gongitsune jf_nezumi jf_tebukuro jm_kumo pf_dora "
                 "pm_alex pm_santa zf_xiaobei zf_xiaoni zf_xiaoxiao zf_xiaoyi zm_yunjian zm_yunxi zm_yunxia "
                 "zm_yunyang em_santa").split()
# the voices that read English (and Roman Hinglish) well; the others are for their own languages
ENGLISH = [v for v in KOKORO_VOICES if v[0] in "ab" and v != "am_santa"]

# stdin is UTF-8: without the first statement PowerShell reads it in the console code page and
# reads curly quotes, accents or the rupee sign aloud as garbage
SAPI = ("[Console]::InputEncoding = [Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "if ($env:NOVA_VOICE) { try { $s.SelectVoice($env:NOVA_VOICE) } catch {} }; "
        "$s.Speak([Console]::In.ReadToEnd())")

_kokoro, _load_lock, _speak_lock = None, threading.Lock(), threading.Lock()


def kokoro_installed():
    return (KOKORO / "model.onnx").exists()


def load_kokoro():
    """Load the model once (about 1.5 s, ~400 MB of memory). Safe to call from any thread."""
    global _kokoro
    with _load_lock:
        if _kokoro is None:
            import sherpa_onnx
            d = KOKORO
            model = sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(d / "model.onnx"), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"),
                data_dir=str(d / "espeak-ng-data"), dict_dir=str(d / "dict"),
                lexicon=f"{d / 'lexicon-us-en.txt'},{d / 'lexicon-zh.txt'}")
            threads = max(1, min(8, (os.cpu_count() or 4) // 2))  # past 8 threads it gets no faster
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(kokoro=model, num_threads=threads, provider="cpu"),
                max_num_sentences=1)  # one sentence per chunk: the first one plays while the rest is made
            _kokoro = sherpa_onnx.OfflineTts(config)
    return _kokoro


def _speak_kokoro(text, voice, speed, stop):
    import numpy as np
    import sounddevice as sd
    model = load_kokoro()
    sid = KOKORO_VOICES.index(voice) if voice in KOKORO_VOICES else KOKORO_VOICES.index("af_heart")
    chunks = queue.Queue()

    def on_audio(samples, _progress):
        chunks.put(np.array(samples, dtype=np.float32))
        return 0 if stop.is_set() else 1  # 0 tells sherpa-onnx to stop generating

    def generate():
        try:
            model.generate(text, sid=sid, speed=speed, callback=on_audio)
        finally:
            chunks.put(None)

    with _speak_lock:  # one voice at a time; the model isn't meant to run twice at once
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
    if v.get("tts_engine") == "kokoro" and kokoro_installed():
        try:
            return _speak_kokoro(text, v.get("kokoro_voice"), float(v.get("tts_speed") or 1.0), stop)
        except Exception as e:  # no sherpa-onnx, broken model or no speakers: still answer out loud
            print(f"Kokoro voice failed, using the system voice: {e!r}", file=sys.stderr)
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


def download():
    """Fetch and unpack the Kokoro model into data/tts, printing progress. Skips work already done."""
    import tarfile
    import urllib.request
    if kokoro_installed():
        return print("Natural voice already installed.")
    KOKORO.parent.mkdir(parents=True, exist_ok=True)
    part = KOKORO.parent / "kokoro.tar.bz2.part"
    with urllib.request.urlopen(KOKORO_URL, timeout=60) as r, open(part, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while block := r.read(1 << 20):
            f.write(block)
            done += len(block)
            print(f"{done >> 20} of {total >> 20} MB", flush=True)
    with tarfile.open(part, "r:bz2") as tar:
        names = tar.getnames()
        if any(n.startswith(("/", "\\")) or ".." in Path(n).parts for n in names):
            raise ValueError("unexpected paths in the voice download")
        try:
            tar.extractall(KOKORO.parent, filter="data")  # also refuses links that point out of the folder
        except TypeError:  # Python 3.11 before 3.11.4 has no filter argument; the names were checked above
            tar.extractall(KOKORO.parent)
    part.unlink()
    print("Natural voice ready.")


if __name__ == "__main__" and sys.argv[1:] == ["download"]:
    download()
