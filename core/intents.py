"""Everyday requests Nova handles itself, instantly and offline, without spending any AI quota:
volume, media keys, opening apps and websites, the time and date, timers and locking the screen.

parse() only understands the request; nova.py carries it out. Anything not recognised here goes to the AI.
"""
import json
import os
import re
from urllib.parse import quote_plus

# common sites people ask for by name; anything that looks like a domain ("github.com") works too
SITES = {"youtube": "https://www.youtube.com", "gmail": "https://mail.google.com", "google": "https://www.google.com",
         "github": "https://github.com", "whatsapp": "https://web.whatsapp.com", "chatgpt": "https://chatgpt.com",
         "claude": "https://claude.ai", "netflix": "https://www.netflix.com", "linkedin": "https://www.linkedin.com",
         "twitter": "https://x.com", "x": "https://x.com", "instagram": "https://www.instagram.com",
         "reddit": "https://www.reddit.com", "amazon": "https://www.amazon.in", "google drive": "https://drive.google.com",
         "google calendar": "https://calendar.google.com", "calendar": "https://calendar.google.com",
         "google maps": "https://maps.google.com", "maps": "https://maps.google.com", "outlook": "https://outlook.live.com",
         "stack overflow": "https://stackoverflow.com", "wikipedia": "https://www.wikipedia.org"}
GENERIC_MUSIC = {"a song", "some music", "music", "something", "a track", "songs", "a song for me", "something good", "anything"}
POLITE = r"(?:(?:hey |ok |okay )?(?:nova )?(?:please |can you |could you |would you |will you )?(?:please )?)"
TAIL = r"(?: for me)?(?: please)?(?: now)?"
AMOUNT = r"(?: (?:a bit|a little|a little bit|slightly|a lot|way up|way down|more|some|by \d{1,3}(?: percent)?))?"
UNITS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600}
_ONES = "one two three four five six seven eight nine".split()
_TEENS = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
# one to ninety-nine in words ("twenty five": the hyphen was already turned into a space)
WORDS = {"a": 1, "an": 1, "half an": 0.5, **{w: n for n, w in enumerate(_ONES, 1)},
         **{w: n for n, w in enumerate(_TEENS, 10)},
         **{f"{t} {o}".strip(): 20 + 10 * i + j for i, t in enumerate(_TENS) for j, o in enumerate([""] + _ONES)}}


def _amount(text):
    """How many 2% volume steps: "a bit" is small, "a lot" is big, "by 20" is exact."""
    by = re.search(r"\bby (\d{1,3})(?: percent| %)?\b", text)
    if by:
        return max(1, int(by.group(1)) // 2)
    if re.search(r"\b(?:a bit|a little|slightly|little bit|thoda)\b", text):
        return 3
    if re.search(r"\b(?:a lot|way|much|max|maximum|bahut)\b", text):
        return 15
    return 6


def parse(text):
    """(action, value) for a request Nova can do itself, or None for the AI. `text` is a raw transcript."""
    t = re.sub(r"[^\w\s%.]", " ", text.lower()).replace("%", " percent")
    t = re.sub(r"\s+", " ", t).strip(" .")
    body = re.sub(rf"^{POLITE}", "", t)

    m = re.fullmatch(rf"(?:set |change |put |turn )?(?:the )?(?:volume|sound)(?: level)? (?:to |at )?(\d{{1,3}})(?: percent)?{TAIL}", body)
    if m:
        return "volume_set", max(0, min(100, int(m.group(1))))
    if re.fullmatch(rf"(?:(?:turn|crank|bump|pump) (?:it|the volume|the sound|the music) up|(?:increase|raise|boost) "
                    rf"(?:the )?(?:volume|sound)|volume up|louder|make it louder){AMOUNT}{TAIL}", body):
        return "volume_up", _amount(body)
    if re.fullmatch(rf"(?:turn (?:it|the volume|the sound|the music) down|(?:decrease|lower|reduce) (?:the )?(?:volume|sound)"
                    rf"|volume down|quieter|make it quieter|softer){AMOUNT}{TAIL}", body):
        return "volume_down", _amount(body)
    if re.fullmatch(rf"(?:un)?mute(?: the)?(?: volume| sound| audio| music| it)?{TAIL}", body):
        return "media", "mute"
    if re.fullmatch(rf"(?:pause|stop|resume|unpause|continue)(?: the| this)?(?: music| song| track| playback| video)?{TAIL}"
                    rf"|play(?: the)? music{TAIL}|play{TAIL}", body):
        return "media", "play_pause"
    if re.fullmatch(rf"(?:next|skip)(?: this| the)?(?: song| track| one)?{TAIL}|play (?:the )?next(?: song| track| one)?{TAIL}", body):
        return "media", "next"
    if re.fullmatch(rf"(?:previous|last|go back(?: to the)?)(?: song| track| one){TAIL}|previous{TAIL}|play (?:the )?previous(?: song| track)?{TAIL}", body):
        return "media", "previous"

    if re.fullmatch(rf"(?:what(?: s| is)?|tell me)(?: the)? (?:current )?time(?: is it)?(?: now| right now)?{TAIL}|what time is it(?: now)?|time kya hua", body):
        return "time", None
    if re.fullmatch(rf"(?:what(?: s| is)?|tell me)(?: the)? (?:today s |current )?(?:date|day)(?: today)?(?: is it)?{TAIL}|what day is it(?: today)?", body):
        return "date", None

    m = re.fullmatch(rf"(?:set|start|put on)(?: a| an)? (?:timer|alarm) (?:for |of )?([\w ]+?) (second|sec|minute|min|hour|hr)s?{TAIL}"
                     rf"|(?:set|start)(?: a| an)? ([\w ]+?) (second|sec|minute|min|hour|hr)s? timer{TAIL}", body)
    if m:
        amount, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        number = float(amount) if re.fullmatch(r"\d+(?:\.\d+)?", amount) else WORDS.get(amount.strip())
        if number:
            return "timer", int(number * UNITS[unit])

    if re.fullmatch(rf"lock(?: my| the)? (?:computer|pc|laptop|screen|mac|system){TAIL}", body):
        return "lock", None

    m = re.fullmatch(rf"(?:open spotify and )?play (.+?) (?:on|in|from|using|with) spotify{TAIL}|(?:open )?spotify (?:and )?play (.+?){TAIL}"
                     rf"|open spotify and play (.+?){TAIL}", body)
    if m:
        what = re.sub(r"^(?:the song|a song called|song|the track|track)\b ?", "", next(g for g in m.groups() if g)).strip()
        return "spotify", "" if what in GENERIC_MUSIC else what

    # bare "play <song>": music means Spotify; anything about a video, a page or "this" is left to the AI
    m = re.fullmatch(rf"play (.+?){TAIL}", body)
    if m and not re.search(r"\b(?:youtube|video|videos|movie|netflix|tab|this|that|it|again|next|previous|pause|game|and|then)\b", m.group(1)):
        what = re.sub(r"^(?:the song|a song called|song|the track|track)\b ?", "", m.group(1)).strip()
        return "spotify", "" if what in GENERIC_MUSIC else what

    m = re.fullmatch(rf"(?:add|put) (.+?) (?:to|in|on) (?:my |the )?(?:spotify )?queue{TAIL}|queue(?: up)? (.+?)(?: next)?(?: on spotify)?{TAIL}", body)
    if m:
        what = re.sub(r"^(?:the song|song|the track|track)\b ?", "", m.group(1) or m.group(2)).strip()
        if what and not re.search(r"\b(?:this|that|it)\b", what):
            return "queue", what

    m = re.fullmatch(rf"(?:search|google|look up)(?: for)? (.+?)(?: on (youtube|google))?{TAIL}", body)
    if m and not re.search(r"\b(?:this|that|it|here|my|and|then)\b", m.group(1)):
        if m.group(2) == "youtube":
            return "url", "https://www.youtube.com/results?search_query=" + quote_plus(m.group(1))
        return "url", "https://www.google.com/search?q=" + quote_plus(m.group(1))

    m = re.fullmatch(rf"(?:close|quit|exit) (?:the )?(.+?)(?: app| window)?{TAIL}", body)
    if m and len(m.group(1).split()) <= 3 and not re.search(r"\b(?:and|then|tab|file|project)\b", m.group(1)):
        return "close", m.group(1)

    m = re.fullmatch(rf"(?:snap|move|put|dock|send) (?:the )?(.+?) (?:to |on |at )?(?:the )?(left|right|center|middle|full ?screen)"
                     rf"(?: half| side| of (?:the|my) screen| screen)?{TAIL}", body)
    if m and len(m.group(1).split()) <= 3 and not re.search(r"\b(?:and|then|my|files?|folders?)\b", m.group(1)):
        return "place", (m.group(1), {"middle": "center", "fullscreen": "full", "full screen": "full"}.get(m.group(2), m.group(2)))
    m = re.fullmatch(rf"maximi[sz]e (?:the )?(.+?)(?: window)?{TAIL}", body)
    if m and len(m.group(1).split()) <= 3:
        return "place", (m.group(1), "full")

    m = re.fullmatch(r"(?:when|if) i say [\"']?(.+?)[\"']?\s*(?:,|:| then | do )\s*(?:do |run |please )?(.+)", text.lower().strip(" ."))
    if m and (len(m.group(1).split()) < 2 or len(m.group(1).replace(" ", "")) < 4):
        return "learn_refused", m.group(1)  # "yes" or "ok" as a shortcut would answer every question Nova asks
    if m:  # needs the comma or "then": the normalised body has no punctuation left to tell the phrase from the command
        inner = parse(m.group(2))
        if inner and inner[0] not in ("learn", "learn_ai"):
            return "learn", (m.group(1), inner)
        if not inner and len(m.group(2).split()) >= 2:
            return "learn_ai", (m.group(1), m.group(2))  # not an instant command: the AI does it once, Nova records how

    m = re.fullmatch(rf"(?:open|launch|start|bring up|pull up|go to)(?: up)? (?:the )?(.+?)(?: app| application| website| site)?{TAIL}", body)
    if m and len(m.group(1).split()) <= 4 and not re.search(r"\b(?:and|then|in|with|my|file|folder|project|tab|that|this)\b", m.group(1)):
        target = m.group(1).strip()
        if target in SITES:
            return "url", SITES[target]
        if re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:/\S*)?", target):
            return "url", "https://" + target
        return "app", target
    return None


def is_junk(text):
    """A transcript that can't be a request, so it isn't worth an AI call: no words, spelled-out letters ("V.S.O.N."), or
    the same phrase of two or more words said over and over (a stuck microphone or a video playing nearby)."""
    t = re.sub(r"[^\w\s]", " ", text.lower())
    words = t.split()
    if not any(c.isalpha() for c in t):
        return True
    if len(words) >= 2 and all(len(w) == 1 for w in words):
        return True
    return bool(re.fullmatch(r"(\w+(?: \w+)+)(?: \1)+", " ".join(words)))


def _key(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _save(path, saved):
    """Whole file or nothing: a power cut mid-write leaves the old shortcuts, not half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    os.replace(temp, path)


def learn(path, said, intent):
    """Remember that `said` means `intent` (an instant command), in the JSON file `path`."""
    saved = recall_all(path)
    saved[_key(said)] = list(intent)
    _save(path, saved)


def forget(path, said):
    saved = recall_all(path)
    if saved.pop(_key(said), None) is not None:
        _save(path, saved)


def recall_all(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):  # unreadable: keep it as .bak, so the next save doesn't replace it with one entry
        try:
            os.replace(path, path.with_suffix(".bak"))
        except OSError:
            pass
        return {}


def recall(path, text):
    """The instant command a saved phrase stands for, or None. Whole phrase only, so a shortcut never fires mid-sentence."""
    hit = recall_all(path).get(_key(re.sub(rf"^{POLITE}", "", _key(text))))
    return tuple(hit) if hit else None


def say_duration(seconds):
    if seconds % 3600 == 0:
        n, unit = seconds // 3600, "hour"
    elif seconds % 60 == 0:
        n, unit = seconds // 60, "minute"
    else:
        n, unit = seconds, "second"
    return f"{n} {unit}{'' if n == 1 else 's'}"
