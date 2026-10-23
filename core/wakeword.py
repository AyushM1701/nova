"""A second "Hey Nova" detector for accents the keyword model misses: a small classifier trained on Indian-English
"Hey Nova"s (one speaker's recordings plus thousands of synthetic voices, helpers/train_wake.py) on top of
openWakeWord's speech features (Apache-2.0: a mel spectrogram, then a 96-number embedding every 80 ms). It listens
to the last 1.28 s of the microphone.

The classifier ships with Nova (models/hey_nova.npz); one trained on this computer with train_wake.py replaces it.
It only wakes Nova for the voice of whoever taught it theirs: Settings → General → "Teach Nova your Hey Nova"
records a few tries through Nova's own microphone and keeps a voiceprint in data/ (enroll). Until then it's off.
Nothing here leaves the computer.
"""
import time
import wave

import numpy as np

from core.config import DATA, ROOT
from core.models import MODELS

DIR = MODELS / "wakeword"  # the feature models, and a classifier trained on this computer
SHARED = ROOT / "models" / "hey_nova.npz"  # the classifier Nova ships
OWN = DIR / "hey_nova.npz"
VOICEPRINT = DIR / "voiceprint.npz"
RECORDINGS = DATA / "wakeword-recordings"  # the tries from enrolling, for training on this microphone later
FRAMES = 16  # embeddings the classifier sees: 1.28 s
HOP = 1280  # samples per embedding (80 ms at 16 kHz)
CONTEXT = 32000  # audio that yields FRAMES embeddings: 2 s (each embedding looks at 0.76 s)
TAIL = 12640  # audio that yields exactly one embedding (76 mel frames): each 80 ms step makes only the new one
WARMUP = -(-TAIL // HOP)  # steps until the first embedding is all real audio
# how alike a voice (its spoken part) must be to the voiceprint. Measured when this was built: 59% of the trainer's
# recordings over 0.85, 84% over 0.80; LibriSpeech speech the classifier mistook for "Hey Nova" topped out at 0.85,
# and 1.1 an hour of it was over 0.80
VOICE = 0.85
TRIES = 8  # "Hey Nova"s recorded when enrolling


def model():
    return OWN if OWN.exists() else SHARED


def installed():
    """The classifier and the models it needs are on this computer (the voiceprint may come later)."""
    from core import models
    return model().exists() and all(models.installed(n) for n in ("wake-mel", "wake-embedding", "embedding"))


def enrolled():
    return VOICEPRINT.exists()


class Features:
    """16 kHz float audio -> one 96-number embedding per 80 ms (openWakeWord's front end)."""

    def __init__(self):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = opts.inter_op_num_threads = 1  # small models: one thread is fastest
        self.mel = ort.InferenceSession(str(DIR / "melspectrogram.onnx"), opts, providers=["CPUExecutionProvider"])
        self.emb = ort.InferenceSession(str(DIR / "embedding_model.onnx"), opts, providers=["CPUExecutionProvider"])

    def __call__(self, audio):
        # the models were trained on 16-bit sample values, and on the mel scaled this way (openWakeWord's own code)
        mel = np.squeeze(self.mel.run(None, {"input": (audio * 32767).astype(np.float32)[None]})[0]) / 10 + 2
        starts = range(0, len(mel) - 75, 8)
        if not starts:
            return np.zeros((0, 96), np.float32)
        windows = np.stack([mel[s:s + 76] for s in starts])[..., None].astype(np.float32)
        return self.emb.run(None, {"input_1": windows})[0].reshape(-1, 96)


class Scorer:
    """How sure the classifier is that the last FRAMES embeddings are "Hey Nova" (0 to 1)."""

    def __init__(self, path=None):
        m = np.load(path or model())
        self.mean, self.std, self.w1, self.b1, self.w2, self.b2 = (m[k] for k in ("mean", "std", "w1", "b1", "w2", "b2"))
        self.threshold = float(m["threshold"])

    def __call__(self, frames):
        x = (frames.reshape(len(frames), -1) - self.mean) / self.std
        logit = (np.maximum(x @ self.w1 + self.b1, 0) @ self.w2 + self.b2)[:, 0]
        return 1 / (1 + np.exp(-np.clip(logit, -30, 30)))


def voice_model():
    """The CAM++ speaker model meetings use for speaker labels."""
    import sherpa_onnx
    from core import models
    return sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(models.path("embedding")), num_threads=1))


def spoken(audio, frame=320):
    """Only the 20 ms frames with speech in them (at least a tenth of the loudest one's level): the speaker model
    weighs every frame, so a second of quiet room around the phrase moved the user's own clips from 0.96 to 0.3."""
    frames = audio[:len(audio) // frame * frame].reshape(-1, frame)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    return frames[rms >= 0.1 * rms.max()].reshape(-1) if len(rms) else audio


def voice_of(model, audio):
    """A voice as 192 numbers, scaled to length 1: two voices' dot product is how alike they sound (up to 1).
    Measured on the spoken part only (see spoken)."""
    stream = model.create_stream()
    stream.accept_waveform(16000, spoken(audio))
    stream.input_finished()
    e = np.array(model.compute(stream), np.float32)
    return e / max(float(np.linalg.norm(e)), 1e-9)


class Voice:
    """Is this the enrolled user's voice? Compared with their voiceprint, read again whenever it changes (enrolling
    while Nova runs). No voiceprint yet: never."""

    def __init__(self):
        self.model, self.print, self.seen = voice_model(), None, None

    def similarity(self, audio):
        """How alike `audio`'s voice is to the voiceprint (up to 1), or None if there's no voiceprint."""
        try:
            stamp = VOICEPRINT.stat().st_mtime_ns
        except OSError:
            return None
        if stamp != self.seen:
            self.print, self.seen = np.load(VOICEPRINT)["voiceprint"], stamp
        return float(voice_of(self.model, audio) @ self.print)

    def matches(self, audio):
        alike = self.similarity(audio)
        return alike is not None and alike >= VOICE


SHADOW = DIR / "shadow"  # while this file exists the detector never wakes Nova: it keeps what would have
SHADOW_CLIPS = DATA / "wakeword-shadow"
SHADOW_KEEP = 300


def shadow():
    return SHADOW.exists()


def keep_shadow(clip, alike):
    """Save a clip the detector would have woken Nova for (shadow mode), keeping the newest SHADOW_KEEP. Its name."""
    SHADOW_CLIPS.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{'none' if alike is None else f'{alike:.2f}'}.wav"
    with wave.open(str(SHADOW_CLIPS / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(clip, -1, 1) * 32767).astype("<i2").tobytes())
    for old in sorted(SHADOW_CLIPS.glob("*.wav"))[:-SHADOW_KEEP]:
        old.unlink(missing_ok=True)
    return name


def utterances(audio, rate=16000):
    """The phrases in a recording: stretches of sound split at pauses of 0.35 s or more, 0.35 to 2.5 s long, with a
    little of the quiet around them."""
    frame = 320
    rms = np.sqrt(np.mean(audio[:len(audio) // frame * frame].reshape(-1, frame) ** 2, axis=1))
    if not len(rms):
        return []
    loud = rms > max(0.12 * rms.max(), 3 * np.percentile(rms, 10))
    out, start, quiet = [], None, 0
    for i, on in enumerate(np.append(loud, False)):
        if on:
            start, quiet = (i if start is None else start), 0
        elif start is not None:
            quiet += 1
            if quiet * frame / rate >= 0.35 or i == len(loud):
                a, b = max(0, (start - 8) * frame), min(len(audio), (i - quiet + 8) * frame)
                if 0.35 <= (b - a) / rate <= 2.5:
                    out.append(audio[a:b])
                start = None
    return out


def enroll(clips):
    """Make the voiceprint from the user's "Hey Nova" tries (16 kHz audio), and keep the tries for training on this
    microphone later. Returns how alike the tries were to each other: low means noise or several voices."""
    tries = [u for clip in clips for u in utterances(clip)[:1]]
    if len(tries) < 3:
        raise ValueError("Nova heard too few of them. Try again somewhere quieter, a little closer to the microphone.")
    voice = voice_model()
    prints = np.stack([voice_of(voice, t) for t in tries])
    v = prints.mean(0)
    # each try against the others' average (with itself in it, the score came out near 1 whatever was recorded)
    others = [np.delete(prints, i, 0).mean(0) for i in range(len(prints))]
    alike = float(np.median([p @ (o / np.linalg.norm(o)) for p, o in zip(prints, others)]))
    DIR.mkdir(parents=True, exist_ok=True)
    np.savez(VOICEPRINT, voiceprint=v / np.linalg.norm(v), tries=len(tries))
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for k, t in enumerate(tries):
        with wave.open(str(RECORDINGS / f"{stamp}-{k + 1}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((np.clip(t, -1, 1) * 32767).astype("<i2").tobytes())
    return {"tries": len(tries), "alike": round(alike, 2), "ok": alike >= VOICE}


class Personal:
    """The personal model's parts, loaded once and shared by every Listener."""

    def __init__(self):
        self.features, self.scorer, self.voice = Features(), Scorer(), Voice()


class Listener:
    """Feed it microphone blocks; it scores the latest 1.28 s every 80 ms. feed() returns the score when it's over
    the model's threshold, else None."""

    def __init__(self, personal):
        self.features, self.scorer = personal.features, personal.scorer
        self.audio, self.new = np.zeros(TAIL, np.float32), np.zeros(0, np.float32)
        self.frames, self.seen = np.zeros((FRAMES, 96), np.float32), 0

    def score(self, block):
        """The best score for the latest 1.28 s over the 80 ms steps this block completed (None if it completed
        none). Steps are cut exactly every 80 ms, as in training, whatever size the blocks are."""
        self.new, best = np.concatenate([self.new, block]), None
        while len(self.new) >= HOP:
            self.audio = np.concatenate([self.audio[HOP:], self.new[:HOP]])
            self.new = self.new[HOP:]
            self.frames = np.vstack([self.frames[1:], self.features(self.audio)])
            self.seen += 1
            # scored once every frame comes from real audio: the empty start is digital silence training never saw
            score = float(self.scorer(self.frames[None])[0]) if self.seen >= FRAMES + WARMUP else 0.0
            best = score if best is None else max(best, score)
        return best

    def feed(self, block):
        score = self.score(block)
        return score if score is not None and score >= self.scorer.threshold else None
