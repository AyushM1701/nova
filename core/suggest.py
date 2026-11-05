"""Suggestion cards and follow-up chips: what happens when something is copied (core/proactive.py decides), and when a chip
on a sketch note is tapped. A mixin of the Nova class (nova.py); it uses the Nova window's state (self.cfg, self.card...)."""
import datetime
import re
import threading
import time

from core import clipboard, corrections, daily, proactive, system
from core.background import free
from core.config import log
from core.local_llm import LocalLLM
from core.questions import chip_question

PROACTIVE_DELAY_S = 4  # after a copy, before a suggestion: long enough to paste it first


class SuggestMixin:
    def chip_clicked(self, text):
        """A follow-up chip on the sketch note (the UI thread): ask it as if it had been spoken. While Nova is still
        talking, its speech stops and the question starts as soon as that request is over."""
        if self.paused or self.pending or not chip_question(text):
            return
        log("heard", mode="assistant", text=text, source="chip")
        if self.phase == "idle":
            return self.start_chip(text)
        self.next_job = lambda: self.start_chip(text)
        if self.phase == "listening" and self.in_followup and not self.holding:
            self.cancel.set()  # the follow-up listen after the answer ends now (not abort(): nothing was cancelled)
            self.stop_rec.set()
        else:
            self.stop_tts.set()

    def start_chip(self, text):
        if not free(self):
            return
        self.target, self.voice = system.foreground(), True
        self.spawn(lambda: self.command(text, typed=True) or self.assist(text), "busy")


    # ---------- proactive suggestions (core/proactive.py): a card offers to help with what was just copied ----------
    def proactive_ok(self):
        return (self.cfg["proactive"]["enabled"] and self.brain and self.cfg["brain"]["clipboard_history"] and not self.paused
                and self.phase == "idle" and not self.pending and not self.recorder and not system.gaming())

    def proactive_check(self, count, text):
        """Something was copied. After a few seconds (long enough to paste it), maybe offer to help with it. Runs off the
        screen thread: a model on this computer votes YES or NO, and nothing reaches the AI unless the user presses Do it."""
        time.sleep(PROACTIVE_DELAY_S)
        try:
            if clipboard.change_count() != count or clipboard.sensitive() or not self.proactive_ok():
                return
            cand = proactive.candidate(text, self.brain.name)
            p, d = self.cfg["proactive"], self.cfg["dictation"]
            llm = (LocalLLM(d["local_url"], d["local_model"])  # only when the user chose a local model (the shipped model
                   if p["use_local_model"] and d["cleanup_engine"] == "local" and d["local_model"] else None)  # name isn't a promise
            if not cand or cand["kind"] not in p["kinds"] or not self.limiter.allow(cand["kind"], text, p["max_per_day"] if llm else min(p["max_per_day"], 2)):
                return
            if llm:  # rules alone would be more eager: with a model, no answer means no card
                yes = proactive.vote(llm, d["local_model"], cand, system.window_title(system.foreground()), text)
                log("proactive", kind=cand["kind"], vote=yes)
                if not yes:
                    return
            self.ui(lambda: self.suggest(cand, text))
        except Exception as e:
            log("error", error=f"proactive: {e!r}")

    def suggest(self, cand, text):
        if not self.proactive_ok():
            return
        self.limiter.shown(cand["kind"], text)
        self.suggestion = cand
        log("proactive", kind=cand["kind"], shown=True)
        self.card.show(cand["title"], cand["body"], buttons=True, kind="suggest", labels=("Do it", "Not now"), hide_after=30)

    def suggesting(self):
        """A suggestion card is on screen right now (not replaced by another card, not timed out)."""
        return bool(self.suggestion and getattr(self.card, "kind", "") == "suggest" and getattr(self.card, "visible", False))

    # ---------- habits (core/corrections.py): "shorter", "just do it" said again and again becomes a line in the memory ----------
    def noticed(self, text):
        """A request is about to run. If it corrects the answer just given, count it; the third time, on another day, offer to
        remember it, once Nova is idle again (shortcut: an offer that finds Nova busy for two minutes is dropped, and asked again in a week)."""
        self.offer_briefing(re.fullmatch(daily.BRIEFING_RE, re.sub(r"[^\w\s]", "", text.lower()).strip()))
        if not self.cfg["habits"]["enabled"] or time.time() - self.replied_at > corrections.FOLLOW_UP_S:
            return
        try:
            offer = self.habits.see(text)
        except Exception as e:
            return log("error", error=f"habits: {e!r}")
        if offer:
            threading.Thread(target=self.when_idle, args=(lambda: self.show_habit(offer),), daemon=True).start()

    def when_idle(self, show):
        for _ in range(120):
            if self.phase == "idle" and not self.pending and not getattr(self.card, "visible", False):  # the reply read
                break
            time.sleep(1)
        else:
            return
        self.ui(show)

    def show_habit(self, offer):
        if self.paused or self.suggesting() or self.phase != "idle":
            return
        self.suggestion = {"kind": "habit", "habit": offer["kind"]}
        self.card.show(offer["title"], offer["body"], buttons=True, kind="suggest", labels=("Remember", "Not now"), hide_after=45)

    # ---------- the morning rundown (core/daily.py): the first request of a morning, Nova offers "start my day" once ----------
    def offer_briefing(self, asked):
        """An assistant request is about to run (noticed). `asked`: it is the rundown itself, which counts as today's offer."""
        today = datetime.date.today().isoformat()
        if asked and not self.briefed.s.get("used"):  # at any hour: "what can you do?" stops suggesting it
            self.briefed.s["used"] = True
            self.briefed.accepted("briefing")
        if not daily.morning(datetime.datetime.now()) or not self.brain or not self.briefed.allow("briefing", today, 1):
            return
        self.briefed.shown("briefing", today)  # shortcut: an offer that finds Nova busy for two minutes is gone for the day
        if not asked:
            threading.Thread(target=self.when_idle, args=(self.show_briefing,), daemon=True).start()

    def show_briefing(self):
        if self.paused or self.suggesting() or self.phase != "idle" or self.recorder or system.gaming():
            return
        self.suggestion = {"kind": "briefing"}
        self.card.show("Good morning", "Want your day in 20 seconds? Your projects, reminders and calendar.", buttons=True,
                       kind="suggest", labels=("Brief me", "Not now"), hide_after=45)

    def answer_suggestion(self, ok):
        cand, self.suggestion = self.suggestion, None
        self.card.hide()
        if cand["kind"] == "briefing":
            if not ok:
                return self.briefed.dismissed("briefing")
            self.briefed.s["used"] = True
            self.briefed.accepted("briefing")
            if self.phase == "idle" and not self.paused:
                self.target, self.voice = system.foreground(), True
                log("heard", mode="assistant", text="[suggestion: briefing]", source="suggestion")
                self.spawn(lambda: self.command("start my day", typed=True), "busy")
            return
        if cand.get("habit"):
            self.habits.answered(cand["habit"], ok)
            return self.card.show("Remembered", "Nova will answer that way from now on. You can change it in Memory.", hide_after=8) if ok else None
        if not ok:
            return self.limiter.dismissed(cand["kind"])
        self.limiter.accepted(cand["kind"])
        if self.phase == "idle" and not self.paused:
            self.target, self.voice = system.foreground(), True
            log("heard", mode="assistant", text=f"[suggestion: {cand['kind']}]", source="suggestion")
            self.spawn(lambda: self.assist(cand["ask"], plain=True, tools=cand["kind"] == "link"), "busy")  # only a link needs a fetch
