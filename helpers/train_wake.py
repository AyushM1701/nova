"""Train Nova's personal "Hey Nova" model on this computer, from your own recordings plus thousands of synthetic ones.

    python helpers/train_wake.py "C:/Users/me/Documents/Sound Recordings"

Each recording is one or more "Hey Nova"s (a file with several is split at the pauses). The model learns them
alongside "Hey Nova" from every voice Nova has (Kokoro, Kitten, Piper and Piper's 904-speaker LibriTTS voice), each
with noise, room echo, other speeds and loudness, against look-alikes ("you know what", "a nova", "bossa nova"),
ordinary sentences and real recorded speech (LibriSpeech's dev-clean set). It reports how often it would wake on
recordings it never saw, and how often it would wake by mistake per hour of speech, then writes
data/models/wakeword/hey_nova.npz (Nova then uses it instead of the one it ships) and a voiceprint from the same
recordings. To ship it with Nova, copy the .npz to models/hey_nova.npz: it holds the classifier only, no voice.
Recordings, generated audio and the voiceprint never leave this computer.
"""
import re
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import meetings, models, tts, wakeword  # noqa: E402
from core.config import DATA  # noqa: E402
from core.loopback import to16k  # noqa: E402

RATE, CTX = 16000, wakeword.CONTEXT
WORK = DATA / "wakeword-train"  # generated audio and features, so a second run starts at the training
PHRASES = ["Hey Nova", "Hey, Nova!", "Hey Nova.", "Hey Nova?"]
LOOKALIKES = ["You know what?", "And over.", "A nova.", "Anova", "Hey, no problem.", "Hey, no way!", "Bossa nova",
              "Casanova", "Supernova", "Nova Scotia", "Hey Novak", "Hey Nora", "Hey Mona", "Hey Noah", "Hey lover",
              "Hey Siri", "Okay Google", "Hey Google", "I know what", "Hey, you know", "And now", "Hey now",
              "No, wait", "Innova", "Hey, over here", "Hey Rover", "Hey, no worries", "Hey, nobody", "Hey Nolan",
              "Hey, never mind", "Hey there", "Nova", "Hey", "Ho, nova", "Honda", "Hey, Lola", "Hey, Donna",
              "Have a nice day", "You know", "Innovation", "Hey, I know", "Hey, no more"]
LIBRITTS = ("LibriTTS voices", "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
            "vits-piper-en_US-libritts_r-medium.tar.bz2", DATA / "tts" / "vits-piper-en_US-libritts_r-medium", "75 MB")
LIBRISPEECH = "https://www.openslr.org/resources/12/dev-clean.tar.gz"  # 5.4 hours of read English, CC BY 4.0
VOICE = wakeword.VOICE
rng = np.random.default_rng(7)


# ---------- your recordings ----------
def personal(folder):
    clips = []
    for f in sorted(Path(folder).iterdir()):
        if f.suffix.lower() in (".m4a", ".wav", ".mp3", ".ogg", ".flac", ".aac", ".webm"):
            audio = meetings.decode(f)
            clips += [(f.name, u) for u in wakeword.utterances(audio) or [audio[-int(2.5 * RATE):]]]
    return clips


# ---------- synthetic speech ----------
def voice(engine):
    if engine == "libritts":
        import sherpa_onnx
        d = LIBRITTS[2]
        config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(next(d.glob("*.onnx"))), tokens=str(d / "tokens.txt"),
                                                       data_dir=str(d / "espeak-ng-data")), num_threads=4))
        return sherpa_onnx.OfflineTts(config), 904
    return tts.load(engine), {"kokoro": len(tts.KOKORO_VOICES), "kitten": len(tts.KITTEN_VOICES), "piper": 1}[engine]


def speak(model, text, sid, speed):
    a = model.generate(text, sid=sid, speed=speed)
    return to16k(np.array(a.samples, np.float32), a.sample_rate)


def synthesize(texts, per_text, name):
    """Each text in `per_text` random voices across every engine, cached in WORK/<name>.npy."""
    cache = WORK / f"{name}.npy"
    if cache.exists():
        return list(np.load(cache, allow_pickle=True))
    out = []
    for engine in ("kokoro", "kitten", "piper", "libritts"):
        model, speakers = voice(engine)
        share = {"kokoro": 0.35, "kitten": 0.1, "piper": 0.05, "libritts": 0.5}[engine]
        for text in texts:
            for _ in range(max(1, round(per_text * share))):
                out.append(speak(model, text, int(rng.integers(speakers)), float(rng.uniform(0.75, 1.3))))
        print(f"  {name}: {engine} done ({len(out)} clips)", flush=True)
    np.save(cache, np.array(out, dtype=object), allow_pickle=True)
    return out


def readme_sentences():
    text = re.sub(r"[`*#|\[\]()<>_]", " ", (ROOT / "README.md").read_text(encoding="utf-8"))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text) if 20 <= len(s.strip()) <= 160][:400]


def librispeech():
    """Real recorded speech, as long stretches: half the speakers for training, the other half only for counting
    false wakes."""
    cache = WORK / "librispeech.npy"
    if cache.exists():
        return list(np.load(cache, allow_pickle=True))
    archive = WORK / "dev-clean.tar.gz"
    if not archive.exists():
        print("  downloading LibriSpeech dev-clean (337 MB)…", flush=True)
        urllib.request.urlretrieve(LIBRISPEECH, archive)
    speakers = {}
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(WORK / "librispeech", filter="data")
    for flac in sorted((WORK / "librispeech").rglob("*.flac")):
        speakers.setdefault(flac.parts[-3], []).append(meetings.decode(flac))
    out = [np.concatenate(parts) for _, parts in sorted(speakers.items())]
    np.save(cache, np.array(out, dtype=object), allow_pickle=True)
    return out


# ---------- turning audio into training windows ----------
def noise(n, level):
    white = rng.normal(0, 1, n)
    if rng.random() < 0.5:  # pink-ish: more low rumble, like fans and traffic
        white = np.cumsum(white) - np.convolve(np.cumsum(white), np.ones(64) / 64, "same")
    return (white / (np.std(white) + 1e-9) * level).astype(np.float32)


def augment(clip, far=False):
    clip = clip / max(float(np.abs(clip).max()), 1e-4) * 0.5
    if rng.random() < 0.5:  # faster or slower
        f = rng.uniform(0.88, 1.12)
        clip = np.interp(np.arange(0, len(clip) - 1, f), np.arange(len(clip)), clip).astype(np.float32)
    if far or rng.random() < 0.4:  # room echo
        n = int(RATE * rng.uniform(0.08, 0.5))
        ir = rng.normal(0, 1, n) * np.exp(-np.linspace(0, rng.uniform(3, 9), n))
        ir[0] = 1 / rng.uniform(0.3, 1.0)  # how much of the voice comes straight, not off the walls
        clip = np.convolve(clip, ir)[:len(clip)].astype(np.float32)
        clip = clip / max(float(np.abs(clip).max()), 1e-4) * 0.5
    gain = 10 ** (rng.uniform(-30, -12) if far else rng.uniform(-20, 3)) / 20
    return clip * gain, float(np.sqrt(np.mean(clip ** 2))) * gain / 10 ** (rng.uniform(3, 30) / 20)


def placed(clip, augmented=True, far=False):
    """2 s of audio with the phrase ending 0-0.3 s before the end, as the model sees it when the user stops."""
    clip, level = augment(clip, far) if augmented else (clip, 3e-4)
    tail = int(rng.uniform(0, 0.3) * RATE)
    clip = clip[-(CTX - tail):]
    audio = noise(CTX, level)
    audio[CTX - tail - len(clip):CTX - tail] += clip
    return audio


def windows(feats, step):
    idx = np.arange(0, len(feats) - wakeword.FRAMES + 1, step)
    return np.stack([feats[i:i + wakeword.FRAMES] for i in idx]) if len(idx) else np.zeros((0, wakeword.FRAMES, 96))


def train(pos, neg, epochs=40, hidden=64):
    """A one-hidden-layer network (numpy, Adam). Returns the weights Scorer reads."""
    x = np.concatenate([pos, neg]).reshape(len(pos) + len(neg), -1).astype(np.float32)
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))]).astype(np.float32)
    mean, std = x.mean(0), x.std(0) + 1e-3
    x = (x - mean) / std
    w = {"w1": rng.normal(0, np.sqrt(2 / x.shape[1]), (x.shape[1], hidden)).astype(np.float32),
         "b1": np.zeros(hidden, np.float32), "w2": rng.normal(0, 0.1, (hidden, 1)).astype(np.float32),
         "b2": np.zeros(1, np.float32)}
    m, v = {k: np.zeros_like(p) for k, p in w.items()}, {k: np.zeros_like(p) for k, p in w.items()}
    weight = np.where(y == 1, len(neg) / len(pos), 1.0).astype(np.float32)  # both classes count the same
    step = 0
    for _ in range(epochs):
        for batch in np.array_split(rng.permutation(len(x)), max(1, len(x) // 256)):
            xb, yb, wb = x[batch], y[batch], weight[batch]
            h = np.maximum(xb @ w["w1"] + w["b1"], 0)
            p = 1 / (1 + np.exp(-np.clip((h @ w["w2"] + w["b2"])[:, 0], -30, 30)))
            d = ((p - yb) * wb / len(batch))[:, None]
            dh = (d @ w["w2"].T) * (h > 0)
            grads = {"w2": h.T @ d, "b2": d.sum(0), "w1": xb.T @ dh, "b1": dh.sum(0)}
            step += 1
            for k in w:
                g = grads[k] + 1e-4 * w[k]
                m[k] = 0.9 * m[k] + 0.1 * g
                v[k] = 0.999 * v[k] + 0.001 * g * g
                w[k] -= 1e-3 * (m[k] / (1 - 0.9 ** step)) / (np.sqrt(v[k] / (1 - 0.999 ** step)) + 1e-8)
    return {"mean": mean, "std": std, **w}


class Weights:
    def __init__(self, w, threshold=0.5):
        self.mean, self.std, self.w1, self.b1, self.w2, self.b2 = (w[k] for k in ("mean", "std", "w1", "b1", "w2", "b2"))
        self.threshold = threshold

    __call__ = wakeword.Scorer.__call__


def main(folder):
    WORK.mkdir(parents=True, exist_ok=True)
    features = wakeword.Features()
    feats = lambda audio: features(audio.astype(np.float32))  # noqa: E731
    t0 = time.time()
    mine = personal(folder)
    print(f"your recordings: {len(mine)} \"Hey Nova\"s", flush=True)
    if not all(models.installed(n) for n in ("kokoro", "embedding")) or not (LIBRITTS[2] / "tokens.txt").exists():
        for name in ("kokoro", "embedding", "libritts"):
            if name == "libritts":
                models.DOWNLOADS["libritts"] = LIBRITTS
            models.download(name)
    print("making synthetic speech…", flush=True)
    synth_pos = synthesize(PHRASES, 700, "positive")
    synth_like = synthesize(LOOKALIKES, 60, "lookalike")
    sentences = synthesize(readme_sentences(), 2, "sentences")
    real = librispeech()
    train_real, test_real = real[::2], real[1::2]
    print(f"{len(synth_pos)} synthetic \"Hey Nova\", {len(synth_like)} look-alikes, {len(sentences)} sentences, "
          f"{sum(map(len, real)) / RATE / 3600:.1f} h of real speech ({time.time() - t0:.0f} s)", flush=True)

    print("features…", flush=True)
    pos_synth = np.stack([feats(placed(c)) for c in synth_pos for _ in range(2)])
    neg_like = np.stack([feats(placed(c)) for c in synth_like for _ in range(2)])
    neg_sent = np.concatenate([windows(feats(np.concatenate([noise(RATE, 3e-4), s * 0.3])), 3) for s in sentences])
    neg_real = np.concatenate([windows(feats(s), 4) for s in train_real])
    neg_quiet = np.stack([feats(noise(CTX, 10 ** rng.uniform(-4.5, -1.5))) for _ in range(800)])
    negatives = np.concatenate([neg_like, neg_sent, neg_real, neg_quiet])
    print(f"  {len(pos_synth)} synthetic positives, {len(negatives)} negatives ({time.time() - t0:.0f} s)", flush=True)
    test_feats = [feats(s) for s in test_real]
    test_hours = sum(map(len, test_real)) / RATE / 3600
    like_test = [feats(placed(c)) for c in synthesize(LOOKALIKES, 12, "lookalike-test")]

    def mine_windows(clips, n):
        return np.stack([feats(placed(c, far=k % 4 == 3)) for c in clips for k in range(n)]) if clips else \
            np.zeros((0, wakeword.FRAMES, 96))

    # ---------- how well it works on recordings it never saw: 4 folds of your recordings ----------
    speaker = wakeword.voice_model()
    voices = {id(c): wakeword.voice_of(speaker, c) for _, c in mine}
    names = sorted({n for n, _ in mine})
    folds = [names[i::4] for i in range(4)]
    held = []  # (best score, how alike the voice is to the voiceprint of the other folds) per held-out "Hey Nova"
    for k, fold in enumerate(folds):
        rest = [c for n, c in mine if n not in fold]
        w = Weights(train(np.concatenate([pos_synth, mine_windows(rest, 40)]), negatives))
        voiceprint = voiceprint_of([voices[id(c)] for c in rest])
        for name, clip in mine:
            if name in fold:
                lead = noise(max(RATE, CTX - len(clip)), 3e-4)  # at least the 2 s the model looks at
                score = float(w(windows(feats(np.concatenate([lead, clip, noise(RATE // 2, 3e-4)])), 1)).max())
                held.append((score, float(voices[id(clip)] @ voiceprint)))
        print(f"  fold {k + 1} of 4 done ({time.time() - t0:.0f} s)", flush=True)
        if k == 0:  # false wakes are counted on this fold's model (trained without a quarter of your recordings)
            real_scores = [w(windows(f, 1)) for f in test_feats]
            like_scores = np.array([float(w(f[None])[0]) for f in like_test])
            fold_print = voiceprint
    held = np.array(held)
    print(f"\nwakes Nova when the model's score is over the threshold and the voice is yours (alike >= {VOICE})")
    print("threshold  your held-out \"Hey Nova\" woken   false wakes per hour of others' speech   look-alikes")
    print("                                           model alone    with the voice check")
    best = None
    for t in (0.5, 0.7, 0.8, 0.9, 0.95, 0.98):
        found = [(n, i) for n, s in enumerate(real_scores) for i in wake_points(s, t)]
        alike = [float(wakeword.voice_of(speaker, test_real[n][max(0, end - 2 * RATE):end]) @ fold_print)
                 for n, i in found for end in [(i + wakeword.FRAMES - 1) * wakeword.HOP + wakeword.TAIL]]
        false, gated = len(found) / test_hours, sum(a >= VOICE for a in alike) / test_hours
        caught = np.mean((held[:, 0] >= t) & (held[:, 1] >= VOICE))
        print(f"  {t:4.2f}            {caught:6.0%}                    {false:6.2f}         {gated:6.2f}"
              f"            {np.mean(like_scores >= t):4.0%}")
        if best is None and gated <= 0.5 and np.mean(like_scores >= t) <= 0.05:
            best = t
    best = best or 0.98
    print(f"\nchosen threshold {best}: the lowest with at most 0.5 false wakes an hour after the voice check, and at "
          f"most 5% of look-alikes (said by other voices; yours, saying something else, can't be measured here)")

    # ---------- the model Nova uses: trained on all your recordings ----------
    w = train(np.concatenate([pos_synth, mine_windows([c for _, c in mine], 40)]), negatives)
    wakeword.DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(wakeword.OWN, threshold=best, **{k: v.astype(np.float32) for k, v in w.items()})
    np.savez(wakeword.VOICEPRINT, voiceprint=voiceprint_of(list(voices.values())), tries=len(mine))
    print(f"wrote {wakeword.OWN} and your voiceprint ({time.time() - t0:.0f} s in all)")


def voiceprint_of(embeddings):
    v = np.mean(embeddings, axis=0)
    return v / np.linalg.norm(v)


def wake_points(scores, threshold, refractory=25):
    """The windows where it would wake: crossing the threshold, at most once per 2 s like a real wake."""
    out, last = [], -refractory
    for i in np.flatnonzero(scores >= threshold):
        if i - last >= refractory:
            out.append(i)
            last = i
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        sys.exit(__doc__)
    main(sys.argv[1])
