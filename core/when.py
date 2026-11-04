"""A time said out loud: "at 4 pm", "in 20 minutes", "tomorrow at 9", "Thursday at 3:30 pm". For reminders and calendar
events. Shortcut: English only. With no am/pm, a clock time alone is the next one that comes round (at 4 is 4 pm if it
is 1 pm now), and with a day 1 to 6 means pm ("Thursday at 3") and 7 to 11 means am, "tonight at 8" being pm; upgrade
by asking the user when it is ambiguous."""
import datetime as dt
import re

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "twenty five": 25, "twenty-five": 25, "thirty": 30, "forty five": 45, "forty-five": 45, "half an": 0.5, "half a": 0.5}
NUMBER = r"\d+(?:\.\d+)?|" + "|".join(sorted(map(re.escape, NUMBERS), key=len, reverse=True))
UNITS = {"minute": 1, "min": 1, "hour": 60, "hr": 60, "day": 1440}
IN_RE = re.compile(rf"\bin ({NUMBER}) (minute|min|hour|hr|day)s?\b", re.I)
DAY = r"today|tonight|tomorrow|(?:next |this )?(?:" + "|".join(DAYS) + r")"
CLOCK = r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s?([ap])\.?m\.?|at\s+(\d{1,2})(?::(\d{2}))?\b|noon|midnight"
AT_RE = re.compile(rf"\b(?:({DAY})\s+)?(?:{CLOCK})(?!\w)", re.I)


def number(word):
    word = word.lower()
    return NUMBERS[word] if word in NUMBERS else float(word)


def minutes(text, default=10):
    """"10 minutes", "an hour", "half an hour" → minutes; `default` when there's no length."""
    m = re.search(rf"\b({NUMBER}) (minute|min|hour|hr)s?\b", text, re.I)
    return int(number(m[1]) * UNITS[m[2].lower()]) if m else default


def _day(word, now):
    """The date a day word means."""
    word = word.lower().strip()
    if word in ("today", "tonight"):
        return now.date()
    if word == "tomorrow":
        return now.date() + dt.timedelta(days=1)
    ahead = (DAYS.index(word.split()[-1]) - now.weekday()) % 7
    if ahead == 0 and word.startswith("next"):
        ahead = 7
    return now.date() + dt.timedelta(days=ahead)


def find(text, now):
    """(when, (start, end)): the first time in `text` and where it sits in it, or None. A day with no clock time isn't
    a time. `when` can be in the past (today at a time that has gone): the caller says so."""
    m = IN_RE.search(text)
    if m:
        return now + dt.timedelta(minutes=number(m[1]) * UNITS[m[2].lower()]), m.span()
    for m in AT_RE.finditer(text):
        day, hour, minute, half, hour2, minute2 = m.groups()
        word = m[0].lower()
        fixed = "noon" in word or "midnight" in word
        if "noon" in word:
            h, mi = 12, 0
        elif "midnight" in word:
            h, mi = 0, 0
        elif hour:
            h, mi = int(hour), int(minute or 0)
        else:
            h, mi = int(hour2), int(minute2 or 0)
        half = (half or "").lower()
        if h > 23 or mi > 59 or (half and not 1 <= h <= 12):
            continue
        if half == "p" and h < 12:
            h += 12
        elif half == "a" and h == 12:
            h = 0
        if not half and not fixed and h <= 12 and day:
            if "tonight" in day.lower() or 1 <= h <= 6:
                h = h % 12 + 12
        date = _day(day, now) if day else now.date()
        if day and "tonight" in day.lower() and h == 12 and not half and not fixed:
            h, date = 0, date + dt.timedelta(days=1)  # "tonight at 12" is midnight, the night's end
        if not half and not fixed and h <= 12 and not day:
            # no am/pm and no day: the next time the clock shows this
            options = sorted(dt.datetime.combine(date + dt.timedelta(days=d), dt.time(hh % 24, mi))
                             for d in (0, 1) for hh in {h, h + 12})
            return next(o for o in options if o > now), m.span()
        pick = dt.datetime.combine(date, dt.time(h, mi))
        if pick <= now and not day:
            pick += dt.timedelta(days=1)
        return pick, m.span()
    return None
