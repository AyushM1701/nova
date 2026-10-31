"""Suggestion cards and follow-up chips: what happens when something is copied (core/proactive.py decides), and when a chip
on a sketch note is tapped. A mixin of the Nova class (nova.py); it uses the Nova window's state (self.cfg, self.card...)."""
import time

from core import clipboard, proactive, system
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
            if not cand or not self.limiter.allow(cand["kind"], text, p["max_per_day"] if llm else min(p["max_per_day"], 2)):
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

    def answer_suggestion(self, ok):
        cand, self.suggestion = self.suggestion, None
        self.card.hide()
        if not ok:
            return self.limiter.dismissed(cand["kind"])
        self.limiter.accepted(cand["kind"])
        if self.phase == "idle" and not self.paused:
            self.target, self.voice = system.foreground(), True
            log("heard", mode="assistant", text=f"[suggestion: {cand['kind']}]", source="suggestion")
            self.spawn(lambda: self.assist(cand["ask"], plain=True, tools=cand["kind"] == "link"), "busy")  # only a link needs a fetch
