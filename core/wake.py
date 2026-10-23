"""'Hey Nova' wake word, fully on-device, in two stages like "Hey Siri" (see Detector):
1. a small keyword model (sherpa-onnx, 3 MB) listens to every 30 ms of the microphone, soft or loud, for the phrase;
2. only when it fires, Whisper checks that clip, so other talk can't wake Nova.
Measured on 360 synthesized "Hey Nova" scenes (normal, soft and quiet voices; quiet room, fan, TV) it caught 225 at
High (the default) and 212 at Normal, against 156 for the older loudness-gate-then-Whisper way, with no false wake in
720 sound-alike scenes or 23 minutes of talk naming "Nova" about 100 times. Running the older way alongside added
only 6 catches at High, for twice the processing, so it was removed.

Nothing leaves the laptop and nothing is logged unless the phrase is heard. "Hey Nova, play some music" in one
breath works too: the audio after "Nova" becomes the request, transcribed by the full (Hindi-aware) pipeline.
"""
import collections
import difflib
import queue
import re
import time

import numpy as np
import sounddevice as sd

from core import wakeword
from core.audio import BLOCK, MIN_SPEECH, RATE
from core.config import log

# Whisper's usual spellings of the phrase; "noah"/"nava" only count after a greeting
WAKE_RE = re.compile(r"^\W*(?:(?:hey|hej|hei|hi|hay|ay|a|eh|he|ok|okay|hello)[\s,]+"
                     r"(?:nova|novah|nover|noba|noah|nava|novo|nowa|no va)|anova|inova|nova)\b"
                     r"[\s,.!?]*(.*)$", re.I | re.S)
NAME_RE = re.compile(r"nov|noah|nava|noba|nowa|^\W*va\b", re.I)  # the word that ends the name ("no va" -> "va")
END_SILENCE_MS = 700  # this much quiet after the phrase: the user has stopped talking
STALLED_S = 3  # a live microphone sends a block every 30 ms, even in silence


def match(text):
    """None if `text` isn't a wake phrase, else the request that followed it ('' if none)."""
    m = WAKE_RE.match(text or "")
    return m.group(1).strip() if m else None


# "yeah that's it", "ok thanks", "no, that's all", "nothing else, bye": the user is done talking to Nova
DONE_RE = re.compile(
    r"(?:(?:yeah|yes|yep|yup|ok|okay|alright|all right|cool|great|perfect|awesome|nice|good|no|nope|nah|"
    r"thanks|thank you|nova)\s+)*"
    r"(?:thats (?:it|all|enough|fine|great|perfect)|that will be all|thatll be all|thanks?(?: you)?(?: so much| a lot)?|"
    r"thank you(?: so much)?|nothing(?: else)?|no thanks|all good|im good|were done|im done|done|bye|goodbye|"
    r"see you|never ?mind|no|nope|nah|ok|okay|alright|cool|great|perfect|got it)"
    r"(?:\s+(?:nova|thanks|thank you|bye|for now))*")


def is_done(text):
    """True if the user is ending the conversation rather than asking for something. Also when Whisper wraps the
    goodbye in stray audio: "Aish. That's it." or "That's it. <a line from a video>. That's it."."""
    said = [s for s in (re.sub(r"[^\w\s]", "", s).strip() for s in re.split(r"[.!?]", (text or "").lower())) if s]
    if not said or not DONE_RE.fullmatch(said[-1]):
        return False
    return len(said) == 1 or said[0] == said[-1] or all(len(s.split()) == 1 for s in said[:-1]) \
        or bool(DONE_RE.fullmatch(" ".join(said)))


# "hello", "allo", "a low": how Whisper sometimes writes an accented "allow" (only ever matched during an approval)
ALLOW_RE = re.compile(r"(?:(?:yes|yeah|yep|yup|ok|okay|sure|haan|ha|han|ji)\s+)*(?:allow(?: it)?|allowed|approve(?: it)?|"
                      r"hello|hallo|allo|alo|a low|aloud|"
                      r"yes|yeah|yep|yup|go ahead|do it|go for it|sure|okay|ok|haan|ha|han|haan ji|kar do)(?:\s+(?:nova|please))*")
DENY_RE = re.compile(r"(?:(?:no|nope|nah|nahi|na|stop|wait|cancel)\s+)*(?:deny(?: it)?|denied|no|nope|nah|dont|do not|stop|cancel|"
                     r"dont do it|dont allow(?: it)?|nahi|na|mat karo|rehne do)(?:\s+(?:nova|please|thanks|thank you))*")


def approval(text):
    """True for a clear spoken "allow", False for a clear "deny", None for anything else (keep waiting)."""
    said = re.sub(r"[^\w\s]", "", (text or "").lower()).strip()
    said = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", said)  # "allow, allow" / "hello? hello?" said twice
    if DENY_RE.fullmatch(said):
        return False
    if ALLOW_RE.fullmatch(said):
        return True
    return None


INTERRUPTIONS = {"stop", "wait", "no", "nova", "cancel", "hold", "enough", "okay", "ok", "quiet", "pause", "hang",
                 "sorry", "excuse", "shut", "hey", "never", "listen", "actually", "sec", "second"}
# what Whisper writes for a cough, a door or a fan: never a reason to stop talking
NOISE_PHRASES = {"thank you", "thanks", "you", "bye", "bye bye", "thank you for watching", "thanks for watching",
                 "thank you very much", "okay bye", "so", "uh", "um", "hmm", "mm", "oh"}
FOLLOWS = 0.6  # sound this much in step (unrelated voices measured up to 0.45; speakers into the mic, over 0.9) with the computer's own audio came out of its speakers


def interrupts(heard, spoken, played="", follows=0.0):
    """Did the user really talk over Nova? `heard` is what the mic picked up, `spoken` what Nova was saying,
    `played` what the computer played meanwhile (Nova's voice, a video, a call), `follows` how closely the mic's
    loudness followed the computer's (loopback.follows). Only a person's own words stop Nova: not noise, not an
    echo, not a video. Short leftovers ("That's it.") need a stop word ("stop", "wait", "Nova…")."""
    words = re.findall(r"[a-z0-9']+", heard.lower())
    if not words or " ".join(words) in NOISE_PHRASES:
        return False
    if is_echo(heard, spoken) or (played.strip() and is_echo(heard, played)) or follows >= FOLLOWS:
        return False
    return len(words) >= 3 or any(w in INTERRUPTIONS for w in words)


def is_echo(heard, spoken):
    """True if the mic only heard Nova's own voice through the speakers: what it heard runs in the same order
    as what Nova was saying. A user who talks over Nova says different words, or the same ones out of order."""
    words = re.findall(r"[a-z0-9']+", heard.lower())
    said = re.findall(r"[a-z0-9']+", spoken.lower())
    if not words:
        return True  # nothing intelligible: noise, not a person
    if len(words) <= 2:
        return not any(w in INTERRUPTIONS for w in words) and all(w in said for w in words)
    same = sum(b.size for b in difflib.SequenceMatcher(None, words, said, autojunk=False).get_matching_blocks())
    return same >= 0.7 * len(words)


# ---------- two stages, like "Hey Siri": a tiny keyword model, then Whisper to check ----------
# the wake phrases in the keyword model's word pieces (its bpe.model): "HEY NOVA" -> ▁HE Y ▁NO V A
PHRASES = {"HEY_NOVA": "▁HE Y ▁NO V A", "HI_NOVA": "▁HI ▁NO V A", "OK_NOVA": "▁O K ▁NO V A",
           "OKAY_NOVA": "▁OKAY ▁NO V A", "HELLO_NOVA": "▁HE LL O ▁NO V A"}
# Settings → General → "Hey Nova" sensitivity: how easily the keyword model fires (boost, threshold), and whether
# how close Whisper's letters must be to the phrase when it didn't spell it exactly (see sounds_like)
SENSITIVITY = {"low": (1.5, 0.25, 0.9), "normal": (2.0, 0.1, 0.8), "high": (3.0, 0.05, 0.72)}
SPELLED = ("heynova", "hinova", "oknova", "okaynova", "hellonova")  # the phrases as letters, for sounds_like
PRE_S = 2.0  # audio kept before the keyword model fires: the phrase is in it
CONFIRM_S = 1.5  # after the model fires, Whisper checks by then at the latest
STEP, STAGGER = 5120, 3  # samples per model step (about 0.3 s), and how many copies run a fraction of one apart
AGC_S, AGC_PEAK, MAX_GAIN = 3.0, 0.3, 30.0  # gain from the loudest sound of the last 3 s, at most +30 dB
_spotters = {}


def spotter(boost, threshold):
    """The keyword model (about 3 MB, data/models), loaded once per setting."""
    import sherpa_onnx
    from core import models
    if (boost, threshold) not in _spotters:
        d = models.path("kws")
        keywords = d / "nova-keywords.txt"
        keywords.write_text("\n".join(f"{tokens} @{name}" for name, tokens in PHRASES.items()) + "\n", encoding="utf-8")
        files = {part: str(d / f"{part}-epoch-12-avg-2-chunk-16-left-64.int8.onnx") for part in ("encoder", "decoder",
                                                                                                "joiner")}
        _spotters[(boost, threshold)] = sherpa_onnx.KeywordSpotter(
            tokens=str(d / "tokens.txt"), keywords_file=str(keywords), num_threads=1, keywords_score=boost,
            keywords_threshold=threshold, **files)
    return _spotters[(boost, threshold)]


class Detector:
    """Feed it the microphone 30 ms at a time. The keyword model listens to every block, however soft (there is no
    loudness gate to get past); when it hears "Hey Nova", the clip is raised to a normal level and Whisper checks it,
    so other talk can't wake Nova. feed() returns None, or ("wake", the request's audio after the name, or None)."""

    def __init__(self, transcribe, sensitivity="high", copies=STAGGER, gain=True, personal=None):
        boost, threshold, self.similar = SENSITIVITY.get(sensitivity, SENSITIVITY["high"])
        self.transcribe, self.spotter, self.copies, self.gain = transcribe, spotter(boost, threshold), copies, gain
        self.personal = personal  # the model trained on the user's own "Hey Nova" (core/wakeword.py), if there is one
        self.recent = collections.deque(maxlen=int(PRE_S * RATE / BLOCK))
        self.peaks = collections.deque(maxlen=int(AGC_S * RATE / BLOCK))
        self.seg, self.quiet, self.floor = None, 0, None
        self.new_streams()

    def new_streams(self):
        """The model works in steps of about 0.3 s, and a phrase that straddles a step badly is easy to miss: copies
        started a fraction of a step apart (measured: 21 of 40 caught with one, 32 with two, 35 with three) never all miss it."""
        self.streams = []
        for k in range(self.copies):
            stream = self.spotter.create_stream()
            stream.accept_waveform(RATE, np.zeros(int(STEP * k / self.copies), np.float32))
            self.streams.append(stream)
        self.listener, self.mine, self.keyword = (wakeword.Listener(self.personal) if self.personal else None), False, False

    def feed(self, block):
        rms = float(np.sqrt(np.mean(block ** 2)))
        if self.floor is None or rms < 2 * self.floor:  # the room's noise level, for telling when talking ends
            self.floor = rms if self.floor is None else 0.98 * self.floor + 0.02 * rms
        if self.seg is None:
            self.recent.append(block)
            self.peaks.append(float(np.abs(block).max()))
            # a soft or distant voice is raised toward a normal level, like a phone's mic before its wake word
            # (a muted mic sends exact zeros: never divide by them)
            loud = block * min(MAX_GAIN, max(1.0, AGC_PEAK / max(max(self.peaks), 1e-6))) if self.gain else block
            heard = False
            for stream in self.streams:
                stream.accept_waveform(RATE, loud)
                while self.spotter.is_ready(stream):
                    self.spotter.decode_stream(stream)
                    heard = heard or bool(self.spotter.get_result(stream))
            # the personal model hears the microphone as it is: it was trained on soft, loud and distant voices
            mine = self.listener is not None and self.listener.feed(block) is not None
            if heard or mine:  # stage 1: keep listening until the user pauses, so "Hey Nova, play music" is one clip
                self.seg, self.quiet, self.mine, self.keyword = list(self.recent), 0, mine, heard
                self.mark = self.sure = len(self.seg)  # where a model fired
            return None
        self.seg.append(block)
        # the personal model fires on the phrase's start and stays sure until it has all of it: follow it to there
        if self.listener is not None and self.listener.feed(block) is not None:
            self.mine, self.sure = True, len(self.seg)
        self.quiet = 0 if rms > max(MIN_SPEECH, 2 * self.floor) else self.quiet + 30
        paused = self.quiet >= END_SILENCE_MS
        # check once the user pauses, or soon anyway: with a TV or people talking the pause may never come
        if not paused and (len(self.seg) - self.mark) * BLOCK / RATE < CONFIRM_S:
            return None
        clip, self.seg = np.concatenate(self.seg), None
        self.recent.clear()
        mine, keyword = self.mine, self.keyword
        self.new_streams()  # what was heard while checking isn't part of the next phrase
        hit = self.check(clip, mine, keyword)
        if hit is None:
            return None
        after, rest = hit
        # still talking ("Hey Nova, what's the…"): Nova records the rest, from this audio and this room's noise level
        return ("wake", after, self.floor) if not paused else ("wake", after if rest else None, None)

    def check(self, clip, mine, keyword):
        """Stage 2. Each stage 1 has its own check: the personal model wakes only for the user's voice, and Whisper
        (whose spelling check lets "Hey, no problem" or "ANOVA" through) only checks what the keyword model flagged."""
        hit = mine and self.yours(clip)
        if hit:  # which model woke Nova, for judging the personal one (Nova logs the wake itself)
            log("wake_check", by="personal model")
            return hit
        return self.confirm(clip) if keyword else None

    def yours(self, clip):
        """Stage 2 when the personal model fired: the user's own voice, up to the last moment the model was sure, is
        enough. Whisper isn't asked to hear the words (it writes many accents' "Hey Nova" as "you know what"), only
        what came after. (the audio after the name, what Whisper heard after it), or None if it isn't their voice."""
        end = self.sure * BLOCK
        if not self.personal.voice.matches(clip[:end]):
            return None
        after = clip[end:]
        rest = " ".join(w for w, _ in self.transcribe(after)) if len(after) > RATE // 4 else ""
        return after, rest.strip(" .,!?")

    def confirm(self, clip):
        """Stage 2: Whisper hears the clip, raised to a normal level so a soft voice isn't taken for silence.
        (the audio after the name, what Whisper heard after it), or None if it isn't the phrase."""
        words = self.transcribe(clip * min(20.0, 0.3 / max(1e-4, float(np.abs(clip).max()))))
        name = None
        for i in range(len(words)):  # the phrase may follow a few words of other talk in the clip...
            # ...but there "Nova" alone ("bossa nova") isn't the phrase: it needs its "hey"
            if (not i or not NAME_RE.search(words[i][0])) and match(" ".join(w for w, _ in words[i:])) is not None:
                name = next((j for j in range(i, len(words)) if NAME_RE.search(words[j][0])), i)
                break
        if name is None:  # Whisper's own spelling of it: "Hinova", "HINE OVER", "Henova", "High Nova"
            name = sounds_like(words, self.similar)
        if name is None:
            return None
        # +0.12 s because Whisper's word end times run slightly early
        return clip[int((words[name][1] + 0.12) * RATE):], " ".join(w for w, _ in words[name + 1:]).strip(" .,!?")


def sounds_like(words, at_least):
    """The index of the word that ends a stretch of letters this close to a wake phrase (0..1), or None.
    Letters only, so Whisper's word breaks don't matter ("hine over" vs "hinova": 0.83)."""
    letters, owner = "", []
    for k, (w, _) in enumerate(words):
        clean = re.sub(r"[^a-z]", "", w.lower())
        letters += clean
        owner += [k] * len(clean)
    best, end = 0.0, None
    for phrase in SPELLED:
        for size in range(len(phrase) - 1, len(phrase) + 3):
            for start in range(max(1, len(letters) - size + 1)):
                score = difflib.SequenceMatcher(None, letters[start:start + size], phrase).ratio()
                if score > best and letters[start:start + size]:
                    best, end = score, owner[min(start + size, len(letters)) - 1]
    return end if best >= at_least else None


def listen(transcribe, on_wake, enabled, running=lambda: True, sensitivity=lambda: "high"):
    """Run until `running()` is False (own thread). on_wake(None) = start listening, on_wake(audio) = this
    audio is the request. `enabled()` is False while Nova is busy, so its own voice can't wake it.
    Returning closes the microphone, so turning the wake word off really stops listening.
    Needs the keyword model (models.download("kws")); Nova fetches it before calling this."""
    personal = None
    if wakeword.installed():  # trained on this computer with helpers/train_wake.py
        try:
            personal = wakeword.Personal()
        except Exception as e:  # an older or broken model file: the keyword model still listens
            log("error", error=f"the personal \"Hey Nova\" model didn't load: {e!r}")
    while running():
        _listen(transcribe, on_wake, enabled, running, sensitivity, personal)


def _listen(transcribe, on_wake, enabled, running, sensitivity, personal=None):
    """One microphone stream. Returns when it stops sending sound (a device that went away or changed, the Mac
    waking from sleep), so listen() opens a fresh one instead of waiting on it forever."""
    blocks, detector, level, heard_at = queue.Queue(), None, None, time.monotonic()
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK,
                        callback=lambda data, *_: blocks.put(data[:, 0].copy())):
        while running():
            try:
                block = blocks.get(timeout=0.5)
            except queue.Empty:
                if time.monotonic() - heard_at > STALLED_S:
                    return
                continue
            heard_at = time.monotonic()
            if not enabled():
                detector = None  # Nova is busy: start afresh afterwards, so its own voice can't count
                continue
            if detector is None or sensitivity() != level:
                level = sensitivity()
                detector = Detector(transcribe, level, personal=personal)
            hit = detector.feed(block)
            if hit:
                on_wake(hit[1], hit[2])

