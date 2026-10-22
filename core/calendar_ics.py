"""Your calendar, read-only, from its secret iCal (ICS) address: Google Calendar (Settings → your calendar →
"Secret address in iCal format") or Outlook (Settings → Calendar → Shared calendars → Publish → ICS link).
Nova names a meeting recording after the event happening now and reminds you when one starts.

The address works like a password to your calendar, so it's kept in data/calendar.key, which the safety guard
won't let the AI read. Nova fetches it at most every 10 minutes.
"""
import datetime as dt
import threading
import time
import urllib.request

from core.config import DATA

KEY_FILE = DATA / "calendar.key"
REFRESH_S = 600
_cache, _lock = {"url": None, "at": 0.0, "cal": None}, threading.Lock()


def url():
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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
            _cache.update(url=address, at=time.time(), cal=fetch(address))
        return _cache["cal"]


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
