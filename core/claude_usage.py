"""What Claude Code really used on this computer, read from its own session files (~/.claude/projects/**/*.jsonl): every
assistant message there carries the tokens it used, whether it came from Nova, a terminal or the desktop app. Used by the
Home deck. Read-only and local; nothing is sent anywhere.

Tokens here are the fresh ones: input + cache writes + output. Cache reads are far more numerous and nearly free, so
they are left out. The 5-hour window is worked out the way the `ccusage` tool does (a block starts at the hour of its first
message and lasts 5 hours), and "peak" is the busiest block in the scanned history: Claude does not publish a plan's limit
to this computer, so the percentage is "of your own busiest 5 hours", not of a plan limit."""
import datetime
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = Path.home() / ".claude" / "projects"
SCAN_DAYS = 35
BLOCK_S = 5 * 3600
_lock = threading.Lock()
_files = {}   # path -> [size, offset] already read
_events = {}  # message key -> [time, fresh tokens]
_limit = {}   # the newest "You've hit your … limit" Claude Code wrote: {"at", "kind", "resets"}
_state = {"summary": None, "scanned": 0.0, "running": False, "auth": None, "auth_at": 0.0, "at": 0.0, "error": ""}


LIMIT_LINE = re.compile(r"hit your (?:(.+?) )?limit\W*(?:resets (?:(\w{3}) (\d{1,2}), )?(\d{1,2})(?::(\d\d))?\s*([ap]m)"
                        r"(?: \(([^)]+)\))?)?", re.I)


def _text(m):
    content = m.get("content")
    if isinstance(content, str):
        return content
    return " ".join(c.get("text", "") for c in content or [] if isinstance(c, dict))


def limit_of(text, at):
    """{"at", "kind", "resets"} from Claude Code's limit message; resets is None when it gives no time."""
    found = LIMIT_LINE.search(text or "")
    if not found:
        return None
    kind, mon, day, hour, minute, ampm, zone = found.groups()
    resets = None
    if hour:
        try:
            tz = ZoneInfo(zone) if zone else None
        except Exception:  # no time zone database (Windows without tzdata): this computer's own zone
            tz = None
        base = datetime.datetime.fromtimestamp(at, tz)
        h = int(hour) % 12 + (12 if ampm.lower() == "pm" else 0)
        when = base.replace(hour=h, minute=int(minute or 0), second=0, microsecond=0)
        if mon:
            try:
                when = when.replace(month=datetime.datetime.strptime(mon, "%b").month, day=int(day))
            except ValueError:
                pass
        if when.timestamp() <= at:  # "resets 2:30am" said at 11 pm means tomorrow (a date that passed: next year)
            when = when.replace(year=when.year + 1) if mon else when + datetime.timedelta(days=1)
        resets = when.timestamp()
    return {"at": at, "kind": (kind or "usage").lower(), "resets": resets}


def _num(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def _read(path, entry):
    """New complete lines of one session file since the last time; the usage of each assistant message in them."""
    size = path.stat().st_size
    if size < entry[1]:  # rewritten: start again
        entry[1] = 0
    if size == entry[1]:
        return
    with path.open("rb") as f:
        f.seek(entry[1])
        data = f.read()
    end = data.rfind(b"\n") + 1  # a line still being written is read next time
    entry[0], entry[1] = size, entry[1] + end
    for raw in data[:end].splitlines():
        if b'"usage"' not in raw or b'"assistant"' not in raw:
            continue
        try:
            e = json.loads(raw)
            u, m = e["message"]["usage"], e["message"]
            t = datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).timestamp()
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if e.get("error") == "rate_limit":  # "You've hit your session limit · resets 10:40pm (Asia/Kolkata)"
            found = limit_of(_text(m), t)
            if found and (not _limit or t >= _limit["at"]):
                _limit.clear(), _limit.update(found)
            continue
        if not isinstance(u, dict):
            continue
        fresh = _num(u.get("input_tokens")) + _num(u.get("cache_creation_input_tokens")) + _num(u.get("output_tokens"))
        key = f"{m.get('id') or raw[:80]}|{e.get('requestId', '')}"
        old = _events.get(key)
        if not old or fresh > old[1]:  # a message is written several times while it streams: the last has the most
            _events[key] = [t, fresh]


def scan(now=None):
    now = now or time.time()
    try:
        paths = [p for p in HOME.rglob("*.jsonl") if p.stat().st_mtime >= now - SCAN_DAYS * 86400]
    except OSError:
        paths = []
    for p in paths:
        try:
            _read(p, _files.setdefault(str(p), [0, 0]))
        except OSError:
            continue


def blocks(events):
    """The 5-hour blocks of [(time, tokens)], oldest first, as the ccusage tool draws them."""
    out, last = [], 0.0
    for t, tokens in sorted(events):
        if not out or t >= out[-1]["end"] or t - last >= BLOCK_S:
            start = t - t % 3600
            out.append({"start": start, "end": start + BLOCK_S, "tokens": 0})
        out[-1]["tokens"] += tokens
        last = t
    return out


def active_limit(limit, events, now):
    """The limit Claude is at now: until its reset time, or, with none given, until Claude answers again (5 hours at most)."""
    if not limit:
        return None
    if limit["resets"]:
        return limit if now < limit["resets"] else None
    later = any(t > limit["at"] and k for t, k in events)
    return None if later or now - limit["at"] > BLOCK_S else limit


def summarise(events, now, limit=None):
    events = list(events)
    limit = active_limit(limit, events, now)
    bl = blocks(events)
    current = bl[-1] if bl and now < bl[-1]["end"] else None
    peak = max((b["tokens"] for b in bl), default=0)
    today = datetime.date.fromtimestamp(now)
    days = []
    for back in range(6, -1, -1):
        d = today - datetime.timedelta(days=back)
        lo, hi = time.mktime(d.timetuple()), time.mktime((d + datetime.timedelta(days=1)).timetuple())
        days.append({"date": d.isoformat(), "tokens": sum(k for t, k in events if lo <= t < hi), "messages": sum(lo <= t < hi for t, _ in events)})
    return {"block": {"tokens": current["tokens"], "resets": current["end"]} if current else None, "peak": peak,
            "percent": round(100 * current["tokens"] / peak) if current and peak else 0, "today": days[-1], "days": days,
            "week": sum(d["tokens"] for d in days), "scanned_days": SCAN_DAYS,
            "limit": {"kind": limit["kind"], "resets": limit["resets"]} if limit else None}


def auth():
    """`claude auth status`: {"logged_in", "plan"} or None if it can't be asked."""
    from core.brain import find_cli
    exe = find_cli("claude")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=20, encoding="utf-8",
                             errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        info = json.loads(out)
        return {"logged_in": bool(info.get("loggedIn")), "plan": str(info.get("subscriptionType") or "")}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _refresh():
    try:
        now = time.time()
        with _lock:
            scan(now)
            _state["summary"] = summarise(_events.values(), now, dict(_limit))
            _state["at"], _state["error"] = now, ""
        # signed out (or unknown): asked again every 15 s, so signing back in shows within moments; signed in: each minute
        signed_in = (_state["auth"] or {}).get("logged_in")
        if now - _state["auth_at"] > (60 if signed_in else 15):
            _state["auth_at"] = now
            _state["auth"] = auth() or _state["auth"]  # a status check that timed out keeps the last answer
    except Exception as e:  # keep the numbers from the last good read, and let the window say it could not refresh
        _state["error"] = type(e).__name__
    finally:
        _state["scanned"], _state["running"] = time.time(), False


def current(max_age=3.0):
    """The latest numbers at once (None until the first scan is done), starting a fresh scan in the background if the
    last one is older than `max_age` seconds. The first scan reads a month of history and can take a few seconds."""
    if not _state["running"] and time.time() - _state["scanned"] > max_age:
        _state["running"] = True
        threading.Thread(target=_refresh, daemon=True).start()
    return {"usage": _state["summary"], "auth": _state["auth"], "loading": _state["summary"] is None, "at": _state["at"], "error": _state["error"]}
