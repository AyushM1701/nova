"""'Hey Nova' wake word, fully on-device.

The first 2.5 s of each utterance is transcribed locally and checked for the wake phrase. Nothing leaves
the laptop and nothing is logged unless the phrase is heard. "Hey Nova, play some music" in one
breath works too: the audio after "Nova" becomes the request, transcribed by the full (Hindi-aware) pipeline.
"""
import collections
import difflib
import queue
import re

import numpy as np
import sounddevice as sd

from core.audio import BLOCK, RATE, is_speech

# Whisper's usual spellings of the phrase; "noah"/"nava" only count after a greeting
WAKE_RE = re.compile(r"^\W*(?:(?:hey|hej|hei|hi|hay|ay|a|eh|he|ok|okay|hello)[\s,]+"
                     r"(?:nova|novah|nover|noba|noah|nava|novo|nowa|no va)|anova|inova|nova)\b"
                     r"[\s,.!?]*(.*)$", re.I | re.S)
NAME_RE = re.compile(r"nov|noah|nava|noba|nowa|^\W*va\b", re.I)  # the word that ends the name ("no va" -> "va")
CHECK_S, MAX_S, MIN_S, END_SILENCE_MS = 2.5, 20.0, 0.4, 700


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
    """True if the user is ending the conversation rather than asking for something."""
    return bool(DONE_RE.fullmatch(re.sub(r"[^\w\s]", "", (text or "").lower()).strip()))


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


def listen(transcribe, on_wake, enabled, running=lambda: True):
    """Run until `running()` is False (own thread). on_wake(None) = start listening, on_wake(audio) = this
    audio is the request. `enabled()` is False while Nova is busy, so its own voice can't wake it.
    Returning closes the microphone, so turning the wake word off really stops listening."""
    blocks = queue.Queue()
    before = collections.deque(maxlen=10)  # 300 ms of audio before speech, so "hey" isn't clipped
    seg, floor, quiet = [], None, 0
    woke = None  # None: not checked yet, False: not a wake phrase, else (end of "Nova" in s, words after it)
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK,
                        callback=lambda data, *_: blocks.put(data[:, 0].copy())):
        while running():
            try:
                block = blocks.get(timeout=0.5)
            except queue.Empty:
                continue
            if not enabled():
                seg, quiet, woke = [], 0, None
                before.clear()
                continue
            rms = float(np.sqrt(np.mean(block ** 2)))
            floor = rms if floor is None else floor  # the first block seeds the room's noise level
            loud = is_speech(rms, floor)
            if not seg:
                if loud:
                    seg, quiet = list(before) + [block], 0
                else:
                    floor = 0.98 * floor + 0.02 * rms  # track the room's noise level
                    before.append(block)
                continue
            seg.append(block)
            quiet = 0 if loud else quiet + 30
            ended, seconds = quiet >= END_SILENCE_MS, len(seg) * BLOCK / RATE
            if woke is None and seconds >= MIN_S and (ended or seconds >= CHECK_S):
                words = transcribe(np.concatenate(seg))
                rest = match(" ".join(word for word, _ in words))
                woke = False if rest is None else (next((e for word, e in words if NAME_RE.search(word)), 0.0), rest)
            if woke is False:
                seg = seg[-1:]  # ordinary talk: just wait for the pause, don't keep the audio
            if ended or (woke and seconds >= MAX_S):
                if woke:
                    end, rest = woke
                    # more speech after "Nova" (heard, or still going past the check): that audio is the request.
                    # +0.12 s because Whisper's word end times run slightly early
                    on_wake(np.concatenate(seg)[int((end + 0.12) * RATE):] if rest or seconds > CHECK_S + 1 else None)
                seg, woke = [], None
                before.clear()
