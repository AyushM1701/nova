"""Usage stats for the Home page: words dictated, speaking speed and minutes saved over typing. Kept in
data/stats.json on this computer; only dictations spoken into Nova's microphone count."""
import datetime
import json

from core.config import DATA, write_atomic

STATS = DATA / "stats.json"
TYPING_WPM = 40  # an average typist
KEEP_DAYS = 30


def _load(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):  # none yet, or a broken file: start fresh
        return {}


def record(words, seconds, path=STATS, today=None):
    if seconds <= 0 or words <= 0:  # typed on the phone, not spoken: no speed to measure
        return
    today = today or datetime.date.today()
    data = _load(path)
    days = {d: n for d, n in data.get("days", {}).items()
            if d >= (today - datetime.timedelta(days=KEEP_DAYS)).isoformat()}
    days[today.isoformat()] = days.get(today.isoformat(), 0) + words
    data.update(words=data.get("words", 0) + words, seconds=data.get("seconds", 0) + seconds,
                dictations=data.get("dictations", 0) + 1, days=days)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(data))


def summary(path=STATS, today=None):
    today = today or datetime.date.today()
    data = _load(path)
    words, seconds = data.get("words", 0), data.get("seconds", 0)
    week = (today - datetime.timedelta(days=6)).isoformat()
    return {"words": words, "dictations": data.get("dictations", 0),
            "wpm": round(words / (seconds / 60)) if seconds else 0,
            "minutes_saved": round(max(0, words / TYPING_WPM - seconds / 60), 1),
            "week_words": sum(n for d, n in data.get("days", {}).items() if d >= week)}
