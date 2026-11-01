"""What the AI's command-line tool said each request used, one line per request in data/usage.jsonl, for the Home deck.
jobs.finish() adds a line when a request has usage. The numbers are the tool's own (see brain.tally): tokens as reported
and the price those tokens would have on the API, not what a plan charges, and not how much of a plan's limit is left."""
import datetime
import json
import time

from core.config import DATA, log

PATH = DATA / "usage.jsonl"
KEEP_S = 90 * 86400
FIELDS = ("input", "cached", "output", "cost_usd")


def add(usage, kind="request", engine="", now=None):
    if not isinstance(usage, dict) or not usage:
        return
    line = {"t": now or time.time(), "kind": kind, "engine": engine, **{k: usage.get(k, 0) for k in FIELDS}}
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError as e:  # a full disk must not stop the request
        log("error", error=f"couldn't record usage: {e!r}")


def _total(lines):
    out = {"runs": len(lines), "input": 0, "cached": 0, "output": 0, "cost_usd": 0.0}
    for e in lines:
        for k in FIELDS:
            out[k] += e[k]
    out["cost_usd"] = round(out["cost_usd"], 4)
    return out


def summary(now=None):
    """Totals for today (since midnight), the last 5 hours and the last 7 days, and the 7 days one by one (oldest first)."""
    now = now or time.time()
    lines, keep = [], []
    try:
        for raw in PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(raw)
                if isinstance(e, dict) and all(isinstance(e.get(k), (int, float)) for k in ("t", *FIELDS)):
                    lines.append(e)
                    keep.append(raw)
            except ValueError:
                continue
    except OSError:
        pass
    if any(e["t"] < now - KEEP_S for e in lines):  # tidy: nothing older than 90 days is kept
        try:
            PATH.write_text("".join(raw + "\n" for raw, e in zip(keep, lines) if e["t"] >= now - KEEP_S), encoding="utf-8")
        except OSError:
            pass
    today, days = datetime.date.fromtimestamp(now), []
    for back in range(6, -1, -1):
        day = today - datetime.timedelta(days=back)
        start, end = time.mktime(day.timetuple()), time.mktime((day + datetime.timedelta(days=1)).timetuple())
        days.append({"date": day.isoformat(), **_total([e for e in lines if start <= e["t"] < end])})
    return {"today": days[-1], "five_hours": _total([e for e in lines if e["t"] >= now - 5 * 3600]),
            "week": _total([e for e in lines if e["t"] >= now - 7 * 86400]), "days": days}
