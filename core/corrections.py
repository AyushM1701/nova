"""Nova learns how you like to be answered from the times you correct it. A short follow-up right after an answer ("shorter",
"just do it", "more detail") is counted; when the same one has come up three times on at least two different days, Nova offers
once to remember it, and only your Remember writes a line to the long-term memory (notes/memory.md), with the why, so the
brain carries it into new requests.

What is kept is a count, the days and the last few words of the correction (data/habits.json); the answer itself is never
read or kept here. Turn it off in Settings, Privacy & safety.
"""
import json
import re
import time

from core.config import DATA, NOTES, log, write_atomic

STATE = DATA / "habits.json"
FOLLOW_UP_S = 600  # a correction is about the answer you just got: ten minutes at most
MAX_WORDS = 12  # a longer message is a new request, not a correction
TIMES, DAYS = 3, 2  # how often, over how many different days, before Nova offers
ASKED_AGAIN_S = 7 * 86400  # an offer nobody answered comes back after this
DECLINED_AGAIN_S = 30 * 86400  # after Not now

# kind: (what you say, the memory line, what Nova says it noticed)
KINDS = {
    "shorter": (r"\b(shorter|too long|too wordy|be brief|keep it (short|brief)|get to the point|more concise|just the answer|less words)\b",
                "Keep answers short, one or two sentences, and give detail only when asked: the user has asked for shorter answers again and again.",
                "you've asked for shorter answers"),
    "longer": (r"\b(more detail|more details|go deeper|elaborate|explain (more|further)|too short|say more)\b",
               "Give the reasoning and the detail, not just the result: the user has asked for more depth again and again.",
               "you've asked for more detail"),
    "just_do_it": (r"\b(just do it|stop asking|don'?t ask( me)?|no need to ask|quit asking)\b",
                   "When a request is clear enough, make a sensible choice, do it and say what you chose, instead of asking first: the user keeps telling Nova to stop asking.",
                   "you've told Nova to stop asking and just do it"),
    "plainer": (r"\b(too formal|less formal|more casual|more natural|sounds? robotic|too stiff|plain(er)? (words|english))\b",
                "Use plain, natural wording like a person talking, with no corporate or stiff phrasing: the user keeps asking for a more natural tone.",
                "you've asked for a more natural tone"),
}
RULES = {kind: re.compile(rule[0], re.I) for kind, rule in KINDS.items()}
DAY = "%Y-%m-%d"


def kind_of(text):
    """Which correction this request is ("shorter", "longer", "just_do_it", "plainer"), or None."""
    text = str(text).strip(" .!?,\n")
    if not text or len(text.split()) > MAX_WORDS:
        return None
    return next((kind for kind, rx in RULES.items() if rx.search(text)), None)


def remember(line):
    """Add `line` to the long-term memory unless it is already there. True if it was added."""
    path = NOTES / "memory.md"
    try:
        have = path.read_text(encoding="utf-8")
    except OSError:
        have = ""
    if line.lower() in have.lower():
        return False
    NOTES.mkdir(parents=True, exist_ok=True)
    write_atomic(path, have.rstrip("\n") + ("\n" if have.strip() else "") + line + "\n")
    return True


class Habits:
    def __init__(self, path=STATE):
        self.path = path
        try:
            self.s = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.s = {}
        if not isinstance(self.s, dict):
            self.s = {}

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path, json.dumps(self.s))
        except OSError as e:
            log("error", error=f"couldn't save what Nova noticed: {e!r}")

    def see(self, text, now=None):
        """A request just came in. If it is a correction that has now come up often enough, the offer to make:
        {"kind", "line", "body", "title"}; else None."""
        kind = kind_of(text)
        if not kind:
            return None
        now = now or time.time()
        k = self.s.setdefault(kind, {})
        if k.get("saved"):
            return None
        k["n"] = int(k.get("n", 0)) + 1
        k["days"] = sorted({*k.get("days", []), time.strftime(DAY, time.localtime(now))})[-30:]
        k["quote"] = str(text).strip()[:60]
        offer = None
        if k["n"] >= TIMES and len(k["days"]) >= DAYS and now >= k.get("until", 0):
            k["until"] = now + ASKED_AGAIN_S  # unanswered: not again for a week
            _, line, said = KINDS[kind]
            offer = {"kind": kind, "line": line, "title": "Remember this?",
                     "body": f"{said.capitalize()} {k['n']} times (last: “{k['quote']}”). Remember it so Nova answers that way from now on?"}
        self._save()
        return offer

    def answered(self, kind, yes, now=None):
        """The user's reply to an offer: Remember writes the line to memory and stops asking; Not now starts over in a month."""
        now = now or time.time()
        k = self.s.setdefault(kind, {})
        if yes:
            added = remember(KINDS[kind][1])
            k.update(saved=True, n=0, days=[])
            log("habit", kind=kind, saved=True, added=added)
        else:
            k.update(n=0, days=[], until=now + DECLINED_AGAIN_S)
            log("habit", kind=kind, saved=False)
        self._save()
