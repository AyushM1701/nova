---
name: nova-hinglish-stt
description: Set up offline speech-to-text that understands English, Hindi and Hinglish and writes Hindi in Roman letters ("kal meeting cancel kar do", not Devanagari), using the Nova Whisper Hinglish model with faster-whisper. Use when the user wants voice input, dictation or transcription for Hindi, Hinglish or Indian English.
---

# Nova Whisper Hinglish speech-to-text

Nova Whisper Hinglish (`AyushM1701/nova-whisper-hinglish` on Hugging Face) is a fine-tune of Whisper large-v3-turbo, converted to CTranslate2 for faster-whisper. It writes Hindi the way people type it, in Roman letters, and keeps English as English. Same speed as stock turbo. License: CC BY-SA 4.0.

Word error rate on held-out clips (lower is better): Hinglish 45.7% vs 77.9% for stock turbo (scored after converting stock turbo's Devanagari to Roman letters); Indian English 9.7% vs 10.3%; LibriSpeech 2.4% vs 2.7%.

## 1. Check the machine

- Python 3.9 or newer: `python --version`.
- About 2 GB free disk for the model.
- NVIDIA GPU? Run `nvidia-smi`. If it prints a GPU, use the GPU path below. Otherwise (and on every Mac) use the CPU path.

Ask the user before installing anything.

## 2. Install

Use a virtual environment so nothing touches the system Python:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install faster-whisper "av<16"
```

Keep the `av<16` pin: faster-whisper 1.2.1 cannot read audio files with av 16 or newer (`TypeError: open() got an unexpected keyword argument 'metadata_errors'`).

GPU on Windows or Linux also needs the CUDA 12 libraries:

```bash
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
```

On Windows, faster-whisper does not find those DLLs by itself. Add each `site-packages/nvidia/*/bin` folder before importing it:

```python
import glob, os, sys
if os.name == "nt":
    for d in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin")):
        os.add_dll_directory(d)
        os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
```

## 3. Transcribe

The first run downloads the model (1.6 GB) into the Hugging Face cache. Tell the user it will take a few minutes.

```python
from faster_whisper import WhisperModel

# GPU: device="cuda", compute_type="float16"   CPU: device="cpu", compute_type="int8"
model = WhisperModel("AyushM1701/nova-whisper-hinglish", device="cuda", compute_type="float16")

VAD = {"threshold": 0.35, "speech_pad_ms": 300, "min_silence_duration_ms": 500}
segments, info = model.transcribe(
    "speech.wav",
    language="hi",                 # "hi" = Hindi/Hinglish in Roman letters, "en" = English
    vad_filter=True, vad_parameters=VAD,
    beam_size=1, condition_on_previous_text=False,
)
print(" ".join(s.text.strip() for s in segments))
```

Key points:

- **Always pass `language`.** `hi` mode was trained to write Roman letters; `en` mode is unchanged English. Leaving it to auto-detect can pick an unrelated language on short clips.
- **Mixed speakers:** detect the language first, but only choose between the languages the user actually speaks:

  ```python
  from faster_whisper import decode_audio
  audio = decode_audio("speech.wav")                   # 16 kHz float32, also accepted by transcribe()
  _, _, ranked = model.detect_language(audio)          # [(code, prob), ...]; needs faster-whisper 1.1+
  lang = max((p, c) for c, p in ranked if c in ("en", "hi"))[1]
  ```

  Decode each clip in its own language so the user can switch from one sentence to the next.
- `condition_on_previous_text=False` stops one bad segment from repeating through the rest.
- The VAD settings above trim silence without clipping soft word endings.

## 4. CPU tip

On a CPU the 1.6 GB model takes a second or more per clip. A faster setup: transcribe with stock `small` (`WhisperModel("small", device="cpu", compute_type="int8")`, `language="en"`), and only re-run a clip through Nova Whisper Hinglish when language detection says Hindi.

## 5. Verify

Record or find a short clip, run step 3, and show the user the text. A Hinglish sentence should come back in Roman letters, for example "kal meeting cancel kar do". If you see Devanagari, `language="hi"` was not passed or the stock Whisper model was loaded instead.

## Troubleshooting

- `Could not load library cudnn...` or `cublas64_12.dll not found`: the CUDA packages are missing or the DLL folders were not added (step 2). Or fall back to CPU.
- `open() got an unexpected keyword argument 'metadata_errors'`: run `pip install "av<16"`.
- `pip` times out on the large CUDA packages: retry with `pip install --timeout 120 ...`.
- Out of GPU memory: use `compute_type="int8_float16"`.
- Download stalls: set `HF_HUB_ENABLE_HF_TRANSFER=0` and retry; behind a proxy, set `HTTPS_PROXY`.
- Microphone input: record 16 kHz mono with `sounddevice` and pass the float32 numpy array straight to `transcribe()`.

Source and training pipeline: https://github.com/AyushM1701/nova (folder `helpers/hinglish_train`).
