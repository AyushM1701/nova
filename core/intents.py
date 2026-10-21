"""Everyday requests Nova handles itself, instantly and offline, without spending any AI quota:
volume, media keys, opening apps and websites, the time and date, timers and locking the screen.

parse() only understands the request; nova.py carries it out. Anything not recognised here goes to the AI.
"""
import re

# common sites people ask for by name; anything that looks like a domain ("github.com") works too
SITES = {"youtube": "https://www.youtube.com", "gmail": "https://mail.google.com", "google": "https://www.google.com",
         "github": "https://github.com", "whatsapp": "https://web.whatsapp.com", "chatgpt": "https://chatgpt.com",
         "claude": "https://claude.ai", "netflix": "https://www.netflix.com", "linkedin": "https://www.linkedin.com",
         "twitter": "https://x.com", "x": "https://x.com", "instagram": "https://www.instagram.com",
         "reddit": "https://www.reddit.com", "amazon": "https://www.amazon.in", "google drive": "https://drive.google.com",
         "google calendar": "https://calendar.google.com", "calendar": "https://calendar.google.com",
         "google maps": "https://maps.google.com", "maps": "https://maps.google.com", "outlook": "https://outlook.live.com",
         "stack overflow": "https://stackoverflow.com", "wikipedia": "https://www.wikipedia.org"}
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

    m = re.fullmatch(rf"(?:open|launch|start|bring up|pull up|go to)(?: up)? (?:the )?(.+?)(?: app| application| website| site)?{TAIL}", body)
    if m and len(m.group(1).split()) <= 4 and not re.search(r"\b(?:and|then|in|with|my|file|folder|project|tab|that|this)\b", m.group(1)):
        target = m.group(1).strip()
        if target in SITES:
            return "url", SITES[target]
        if re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:/\S*)?", target):
            return "url", "https://" + target
        return "app", target
    return None


def say_duration(seconds):
    if seconds % 3600 == 0:
        n, unit = seconds // 3600, "hour"
    elif seconds % 60 == 0:
        n, unit = seconds // 60, "minute"
    else:
        n, unit = seconds, "second"
    return f"{n} {unit}{'' if n == 1 else 's'}"
