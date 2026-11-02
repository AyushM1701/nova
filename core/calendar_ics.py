"""Your calendar, read-only, from its secret iCal (ICS) address: Google Calendar (Settings → your calendar →
"Secret address in iCal format") or Outlook (Settings → Calendar → Shared calendars → Publish → ICS link).
Nova names a meeting recording after the event happening now and reminds you when one starts. It can also write one
event as an .ics file ("put a review on Thursday at 3 pm") for your calendar app to open: no account, no access.

The address works like a password to your calendar, so it's kept in data/calendar.key, which the safety guard
won't let the AI read. Nova fetches it at most every 10 minutes.
"""
import datetime as dt
import re
import threading
import time
import urllib.request
import uuid

from core import vault, when
from core.config import DATA

KEY_FILE = DATA / "calendar.key"
REFRESH_S = 600
_cache, _lock = {"url": None, "at": 0.0, "cal": None}, threading.Lock()


def url():
    return vault.read(KEY_FILE)  # the OS's credential store; a file from before is moved there


def fetch(address):
    import icalendar
    address = address.replace("webcal://", "https://", 1)
    if not address.startswith("https://"):
        raise ValueError("That isn't a calendar address. It should start with https:// or webcal://.")
    req = urllib.request.Request(address, headers={"User-Agent": "Nova"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return icalendar.Calendar.from_ical(r.read())


def calendar():
    """The parsed calendar, refreshed every REFRESH_S. None if no address is set."""
    address = url()
    if not address:
        return None
    with _lock:
        if _cache["url"] != address or time.time() - _cache["at"] > REFRESH_S:
            try:
                _cache.update(url=address, at=time.time(), cal=fetch(address))
            except Exception:
                if _cache["url"] != address or _cache["cal"] is None:
                    raise
                _cache["at"] = time.time()  # offline: the copy from before still reminds; try again in REFRESH_S
        return _cache["cal"]


def cached():
    """The calendar as last fetched, without going to the network (None if there's none yet)."""
    return _cache["cal"] if _cache["url"] == url() else None


def local(value):
    """An event time as a local naive datetime (all-day dates become midnight)."""
    if not isinstance(value, dt.datetime):
        return dt.datetime.combine(value, dt.time())
    return value.astimezone().replace(tzinfo=None) if value.tzinfo else value


def events(start, end, cal=None):
    """[{title, start, end}] between two local datetimes, recurring events expanded, all-day events left out."""
    import recurring_ical_events
    cal = cal or calendar()
    if cal is None:
        return []
    out = []
    for e in recurring_ical_events.of(cal).between(start, end):
        begin = e.get("DTSTART").dt
        if not isinstance(begin, dt.datetime):
            continue  # all-day: a holiday or a reminder, not a meeting
        finish = e.get("DTEND").dt if e.get("DTEND") else begin + dt.timedelta(hours=1)
        out.append({"title": str(e.get("SUMMARY") or "Meeting"), "start": local(begin), "end": local(finish)})
    return sorted(out, key=lambda e: e["start"])


def now_event(now=None, cal=None):
    """The meeting happening now (or starting within 5 minutes), or None."""
    now = now or dt.datetime.now()
    found = [e for e in events(now - dt.timedelta(hours=4), now + dt.timedelta(minutes=5), cal)
             if e["start"] - dt.timedelta(minutes=5) <= now < e["end"]]
    return min(found, key=lambda e: abs((e["start"] - now).total_seconds()), default=None)


# ---------- writing: one event as an .ics file the user's own calendar app opens (no account, no access) ----------
EVENT_RE = re.compile(r"^\W*(?:please )?(put|add|schedule|book|block(?: off)?|create|set up|make)\s+"
                      r"(?:an? |the |my |some )?(.+?)[.!]?$", re.I)
CALENDAR_TAIL = re.compile(r"\s+(?:on|to|in|onto) (?:my )?(?:calendar|schedule)\b", re.I)
LENGTH = re.compile(rf"\s+for ((?:{when.NUMBER}) (?:minute|min|hour|hr)s?)\b", re.I)
DAY_WORD = re.compile(r"\b(?:today|tonight|tomorrow|" + "|".join(when.DAYS) + r")\b", re.I)
SURE = re.compile(r"\b(?:[ap]\.?m\.?|noon|midnight)\b|" + DAY_WORD.pattern, re.I)
PLAIN_VERBS = ("add", "create", "make", "set up")  # also what a developer says about a cron job or a build


def parse_event(text, now):
    """(title, start, minutes) for "put a review on Thursday at 3 pm for an hour", or None. Needs a day or an am/pm, so
    "add a margin at 4 px" is not an event. Shortcut: 30 minutes when no length is said."""
    m = EVENT_RE.match(text.strip())
    if not m:
        return None
    rest = CALENDAR_TAIL.sub("", m[2])
    if m[1].lower() in PLAIN_VERBS and rest == m[2] and not DAY_WORD.search(rest):
        return None  # "add a cron job that runs at 3 am": no day and no "calendar", so it is for the AI
    length = LENGTH.search(rest)
    minutes = when.minutes(length[1]) if length else 30
    rest = LENGTH.sub("", rest)
    found = when.find(rest, now)
    if not found or not SURE.search(rest[found[1][0]:found[1][1]]):
        return None
    start, (a, b) = found
    title = re.sub(r"\s+", " ", f"{rest[:a]} {rest[b:]}")
    title = re.sub(r"^\s*(?:on|at|for|to)\s+|\s+(?:on|at|for|by|to|in)\s*$", "", title).strip(" ,.")
    return (title, start, minutes) if title and len(title) <= 60 else None  # a long "title" is a command, not an event


def make_ics(title, start, minutes=30):
    """The text of an .ics file with one event. Times are local ("floating"): the calendar app shows them as said."""
    esc = lambda s: re.sub(r"[\x00-\x1f]", " ", s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")  # noqa: E731
    stamp = lambda t: t.strftime("%Y%m%dT%H%M%S")  # noqa: E731
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Nova//EN", "BEGIN:VEVENT",
                        f"UID:{uuid.uuid4()}@nova", f"DTSTAMP:{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                        f"DTSTART:{stamp(start)}", f"DTEND:{stamp(start + dt.timedelta(minutes=minutes))}",
                        f"SUMMARY:{esc(title)[:200]}", "END:VEVENT", "END:VCALENDAR", ""])
