"""The personal "Hey Nova" model: a small classifier trained on this computer (helpers/train_wake.py) from the
user's own recordings plus thousands of synthetic voices, on top of openWakeWord's speech features (Apache-2.0:
a mel spectrogram, then a 96-number embedding every 80 ms). It listens to the last 1.28 s of the microphone.
Nothing here leaves the computer; the model file lives in data/models/wakeword next to the feature models.
"""
import numpy as np

from core.models import MODELS

DIR = MODELS / "wakeword"
MODEL = DIR / "hey_nova.npz"
FRAMES = 16  # embeddings the classifier sees: 1.28 s
HOP = 1280  # samples per embedding (80 ms at 16 kHz)
CONTEXT = 32000  # audio that yields FRAMES embeddings: 2 s (each embedding looks at 0.76 s)
TAIL = 12640  # audio that yields exactly one embedding (76 mel frames): each 80 ms step makes only the new one
WARMUP = -(-TAIL // HOP)  # steps until the first embedding is all real audio


def installed():
    from core import models
    return MODEL.exists() and (DIR / "melspectrogram.onnx").exists() and (DIR / "embedding_model.onnx").exists() \
        and models.installed("embedding")


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

    def __init__(self, path=MODEL):
        m = np.load(path)
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
    """Is this the voice the model was trained on? Compared with the average of the user's recordings. Other
    people's speech the model mistook for "Hey Nova" was never this close in the training check; the user's own
    recordings were."""

    def __init__(self, path=MODEL):
        m = np.load(path)
        self.print, self.threshold, self.model = m["voiceprint"], float(m["voice_threshold"]), voice_model()

    def matches(self, audio):
        return float(voice_of(self.model, audio) @ self.print) >= self.threshold


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
