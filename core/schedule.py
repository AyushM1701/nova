"""Scheduled routines: "every weekday at 9, run start my day". Nova checks every 30 seconds and runs what's due
once a day; a computer that wakes up within the hour still runs it, once."""
import datetime
import re

from core.config import DATA

LAST = DATA / "schedules-last.json"  # key -> the date it last ran, so a restart doesn't run it twice
WINDOW_MIN = 60
DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAYS = {"day": list(range(7)), "weekday": list(range(5)), "weekend": [5, 6],
        **{name: [i] for i, name in enumerate(DAY_NAMES)}}
SCHEDULE_RE = re.compile(r"^\W*every (" + "|".join(DAYS) + r")s? at (\d{1,2})(?::(\d{2}))? ?([ap])?\.?m?\.?,? "
                         r"run (.+?)[.!]?$", re.I)  # "run" is required: "every Monday at 9 I have…" is a request


def parse(text):
    """{"days", "at", "run"} for a spoken schedule, or None."""
    m = SCHEDULE_RE.match(text.strip())
    if not m:
        return None
    hour, minute, half = int(m[2]), int(m[3] or 0), (m[4] or "").lower()
    if half == "p" and hour < 12:
        hour += 12
    elif half == "a" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59 or not m[5].strip():
        return None
    return {"days": DAYS[m[1].lower()], "at": f"{hour:02d}:{minute:02d}", "run": m[5].strip()}


def key(s):
    return f"{s['run']}|{s['at']}|{''.join(map(str, s['days']))}"


def due(schedules, now, last):
    """The schedules to run now: today is one of their days, their time passed less than WINDOW_MIN minutes ago,
    and they haven't run today."""
    out = []
    for s in schedules:
        try:
            hour, minute = map(int, s["at"].split(":"))
            start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if "days" not in s or "run" not in s:
                continue
        except (ValueError, KeyError, TypeError, AttributeError):  # hand-edited into something else: skip just this one
            continue
        late = (now - start).total_seconds()
        if now.weekday() in s["days"] and 0 <= late < WINDOW_MIN * 60 and last.get(key(s)) != now.date().isoformat():
            out.append(s)
    return out


def describe(s):
    """"every weekday at 09:00" for a card or the Settings list."""
    days = next((name for name, d in DAYS.items() if d == s["days"]), ", ".join(DAY_NAMES[i] for i in s["days"]))
    return f"every {days} at {s['at']}"
