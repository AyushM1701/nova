"""One-shot spoken reminders: "remind me to call the bank at 4 pm", then "snooze 10 minutes". Kept in data/reminders.json so
a restart doesn't lose them; Nova's 30-second loop (watch_schedules) says the ones that are due."""
import datetime as dt
import json
import re
import threading
import time

from core import when
from core.config import DATA, write_atomic

FILE = DATA / "reminders.json"  # [{"at": epoch seconds, "text": "call the bank"}]
REMIND_RE = re.compile(r"^\W*(?:please )?remind me (?:to |about |that )?(.+?)[.!]?$", re.I)
SNOOZE_RE = re.compile(r"^\W*snooze(?: (?:it|that|this|the reminder))?(?: for)?"
                       r"(?: ((?:\d+(?:\.\d+)?|[a-z-]+(?: [a-z]+)?) (?:minutes?|mins?|hours?|hrs?)))?[.!]?$", re.I)
CLEAR_RE = re.compile(r"^\W*(?:cancel|clear|delete|forget) (?:all )?(?:my |the )?reminders?[.!]?$", re.I)
_LOCK = threading.Lock()
STALE_S = 3600  # a reminder this late is said as missed, not as if it were on time


def parse(text, now):
    """(epoch seconds, what) for "remind me to X at 4 pm" / "remind me in 20 minutes to X", or None. A time that has
    passed today is asked for again by the caller, not guessed."""
    m = REMIND_RE.match(text.strip())
    if not m:
        return None
    found = when.find(m[1], now)
    if not found:
        return None
    at, (start, end) = found
    what = f"{m[1][:start]} {m[1][end:]}"
    what = re.sub(r"\s+", " ", re.sub(r"^\s*(?:to|that|about)\s+|\s+(?:to|at|on|in|by|for)\s*$|^\s*(?:to|at|on|in)\s+", " ", what)).strip(" ,.")
    return (at.timestamp(), what) if what else None


def snooze(text):
    """Minutes for "snooze 10 minutes" / "snooze", or None when it isn't a snooze."""
    m = SNOOZE_RE.match(text.strip())
    return when.minutes(m[1] or "") if m else None


def load():
    try:
        items = json.loads(FILE.read_text(encoding="utf-8"))
        return [i for i in items if isinstance(i, dict) and isinstance(i.get("at"), (int, float)) and str(i.get("text", ""))]
    except (OSError, ValueError):
        return []


def save(items):
    with _LOCK:
        write_atomic(FILE, json.dumps(items))


def add(at, text):
    with _LOCK:  # a new reminder (a worker thread) and one just said (the UI thread) must not overwrite each other
        write_atomic(FILE, json.dumps(sorted([*load(), {"at": at, "text": text[:200]}], key=lambda i: i["at"])))


def first_due(now=None):
    """The first reminder that is due, still in the file (remove it once it has been said), or None."""
    now = time.time() if now is None else now
    items = load()
    return items[0] if items and items[0]["at"] <= now else None


def remove(item):
    """Take a said reminder out of the file. Said first, removed after: a crash in between says it again, not never."""
    with _LOCK:
        items = load()
        if item in items:
            items.remove(item)
            write_atomic(FILE, json.dumps(items))


def late(item, now=None):
    return (time.time() if now is None else now) - item["at"] > STALE_S


def describe(at, now):
    """"at 4:00 PM", "tomorrow at 9:00 AM" or "on Thursday at 3:30 PM" for the card and the spoken answer."""
    then = dt.datetime.fromtimestamp(at)
    clock = then.strftime("%I:%M %p").lstrip("0")
    days = (then.date() - now.date()).days
    return f"at {clock}" if days < 1 else f"tomorrow at {clock}" if days < 2 else f"on {then.strftime('%A')} at {clock}"


def handle(text, now, last, note):
    """Do a reminder command ("remind me to X at 4 pm", "snooze 10 minutes", "clear my reminders") and say what
    happened through `note(title, text)`. `last`: the reminder Nova said most recently. False when it isn't one."""
    if CLEAR_RE.match(text):
        save([])
        note("Reminders cleared", "Okay, I cleared your reminders.")
        return True
    minutes = snooze(text)
    if minutes is not None:
        if not last:
            note("Nothing to snooze", "I haven't reminded you of anything lately.")
        else:
            add(time.time() + minutes * 60, last["text"])
            note("Snoozed", f"Okay, I'll remind you again in {minutes} minutes.")
        return True
    found = parse(text, now)
    if not found:
        return False
    at, what = found
    if at <= time.time():
        note("That time has passed", "That time has already passed. Say it again with a later time.")
    else:
        add(at, what)
        note("Reminder set", f"Okay, I'll remind you to {what} {describe(at, now)}.")
    return True
