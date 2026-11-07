"""The card: what Nova heard, what it's doing and what it says, drawn inside the bar's own window. When a card comes up
the pill grows into it (one shape of frosted glass that morphs), and shrinks back to the pill when it goes.

Thinking: the question (quiet, on one line) over the step Nova is on, with light sweeping across it. Speaking and after:
the answer in crisp white, the question above it. Needs your OK: Allow / Deny. Short notices ("Nova is ready",
"Cancelled") are one line, the height of the pill. It never takes focus; click it to open the Nova window, where the
full reply and the history are.
"""
import math
import re
import time

from PIL import Image, ImageDraw

from core import system, theme
from PIL import ImageFilter

from core.bar import (AMBER, BLUR, CAPSULE, MARK_W, VERY_SLOW, Bar, dpi_scale, in_out, keycap, mark, mic, mono_font,
                      shimmer, stop_square, ui_font, wave)

SS = 2  # drawn 2x, then downscaled: smooth corners and text
WIDTH, PX, PY = 440, 18, 14  # logical px: the card's width, and its padding across and down
TOAST_MAX = 560  # the widest a one-line notice grows
RED = (255, 122, 122)
LIVE = ("thinking", "speaking", "approval")  # kinds that move, so the bar keeps drawing them
W95, W85, W80, W70, W50, W40, W20, W06 = 242, 217, 204, 179, 128, 102, 51, 15  # white's alpha at 95%, 85%...


def plain(text):
    """Replies are markdown; the card shows them as plain prose."""
    text = re.sub(r"```[\w-]*\n?|`|\*\*|^#+\s*", "", text, flags=re.M)
    return re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.M)


def wrap(text, font, width, max_lines):
    """(lines, truncated): word-wrapped to `width`, long words broken, the last line ellipsized if cut."""
    lines = []
    for para in filter(str.strip, text.splitlines()):
        line = ""
        for word in para.split():
            candidate = f"{line} {word}" if line else word
            if font.getlength(candidate) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            while font.getlength(word) > width:  # a path or URL longer than the card
                cut = max(1, int(len(word) * width / font.getlength(word)) - 1)
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    cut = len(lines) > max_lines
    lines = lines[:max_lines]
    if cut:
        last = lines[-1]
        while last and font.getlength(last + "…") > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines, cut


def fit(text, font, width):
    """`text` on one line, ellipsized to `width` (drawing px)."""
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


class Card:
    """The card's content and what a click on it does. The bar (core/bar.py) draws it, in its own window, inside the
    glass it grows into. `size` is the card's size in logical px; `frame()` its content for this moment, in image px."""
    quiet = False
    bar, visible, kind, telemetry, base, _body, _said, shown_at, _reveal_at, _reveal_end, _rows = None, False, "info", "", None, None, None, 0.0, 0.0, 0.0, ()
    size, buttons, chips, stop_box, _live = (WIDTH, CAPSULE), (), (), None, ()

    def __init__(self, root, on_allow, on_deny, on_open=None, hotkey="", position="bottom", on_ask=None):
        self.root = root
        self.scale = dpi_scale(root)  # image px per logical px; the bar's (x2 on a Retina Mac) once it is set
        self.on_allow, self.on_deny, self.on_open, self.on_ask = on_allow, on_deny, on_open, on_ask
        self.hotkey, self._hide_job = hotkey, None
        self._fonts()

    def _fonts(self):
        px = lambda size: int(size * self.scale * SS)
        self.f_label, self.f_title, self.f_step = ui_font(px(12), 500), ui_font(px(13), 600), ui_font(px(13), 500)
        self.f_body, self.f_quote, self.f_small = ui_font(px(13.5)), ui_font(px(12), italic=True), ui_font(px(11))
        self.f_mono, self.f_kbd = mono_font(px(11)), mono_font(px(11))
        self.f_button, self.f_link = ui_font(px(12.5), 600), ui_font(px(12), 500)

    def set_hotkey(self, hotkey):
        self.hotkey = hotkey

    @property
    def live(self):
        """Moving: a working kind, its mark still rising, or its answer still being revealed."""
        t = time.monotonic()
        return self.kind in LIVE or t - self.shown_at < 0.8 or (self._body is not None and t < self._reveal_end)

    def bottom(self):
        """The screen y of the card's bottom edge while it is up at the top of the screen, else 0 (nothing to avoid)."""
        bar = self.bar
        if not (self.visible and bar is not None and bar.top):
            return 0
        return int(bar.anchor + self.size[1] * bar.scale)

    # ---------- content ----------
    def show(self, title, body="", buttons=False, hide_after=None, kind=None, quote="", detail="", labels=None,
             toast=False, keys=""):
        """`toast`: one line, `body` beside the title and `keys` as a keycap. Title-only notices are toasts too."""
        if self.bar is not None and self.bar.scale * self.bar.px != self.scale:
            self.scale = self.bar.scale * self.bar.px
            self._fonts()
        kind = kind or ("approval" if buttons else "info")
        now = time.monotonic()
        said = plain(body) if kind in ("speaking", "reply") else None
        self.quiet = said is not None and said == self._said  # the same answer, spoken then done: no swap, no reveal
        if not self.visible or (kind != self.kind and not self.quiet):  # a card arriving, not an update: its mark rises in
            self.shown_at = now
        self.kind = kind
        if said != self._said:  # new words: they rise in line by line
            self._said, self._reveal_at = said, now
        self._render(title, plain(body), buttons, quote, detail, labels, toast, keys)
        self.visible = True
        if self.bar is not None:
            self.bar.attach(self)
        self.hide_later(hide_after)

    def _render(self, title, body, buttons, quote, detail, labels=None, toast=False, keys=""):
        """The card at rest, at 1x: text, marks and buttons on transparent (the bar puts the glass under it). What
        moves (the sweep of light, the voice wave) is drawn per frame, from `_live`."""
        self.buttons, self.chips, self.stop_box, self._live, self._body = [], [], None, [], None
        if toast or not (body or detail or buttons or self.kind in LIVE):
            return self._toast(title, body or (f"“{quote.strip()}”" if quote else ""), keys)
        if self.kind == "thinking":
            return self._thinking(title, quote, detail)
        if self.kind in ("speaking", "reply"):
            return self._answer(title, body, quote)
        return self._notice(title, body, buttons, detail, labels)

    def _canvas(self, width, height):
        s = self.scale * SS
        img = Image.new("RGBA", (round(width * s), round(height * s)))
        return img, ImageDraw.Draw(img), s

    def _done(self, img, width, height):
        self.size = (width, height)
        self.base = img.reduce(SS)

    def _mark(self, x, cy, size, colors=None):
        """Nova's logo here, drawn live each frame (core/bar.py mark): returns its width."""
        self._live.append(("mark", x / SS, cy / SS, size, colors))
        return MARK_W * size * self.scale * SS

    def _toast(self, title, sub, keys):
        """One line, as tall as the pill: the mark, the title, a quiet detail beside it and, maybe, a key."""
        s = self.scale * SS
        sep = "  ·  "
        kw = (self.f_kbd.getlength(keys) / s + 12 + 14) if keys else 0
        fixed = PX + MARK_W * .9 + 10 + self.f_label.getlength(title) / s + kw + PX
        if sub:
            sub = fit(sub, self.f_label, (TOAST_MAX - fixed) * s - self.f_label.getlength(sep))
        width = max(168, round(fixed + (self.f_label.getlength(sep + sub) / s if sub else 0)))
        img, d, s = self._canvas(width, CAPSULE)
        cy, x = CAPSULE / 2 * s, PX * s
        error = self.kind == "error"
        x += self._mark(x, cy, .9, [RED] * 5 if error else None) + 10 * s
        d.text((x, cy), title, font=self.f_label, fill=(255, 255, 255, W95), anchor="lm")
        x += self.f_label.getlength(title)
        if sub:
            d.text((x, cy), sep, font=self.f_label, fill=(255, 255, 255, W20), anchor="lm")
            x += self.f_label.getlength(sep)
            d.text((x, cy), sub, font=self.f_label, fill=(255, 255, 255, W50), anchor="lm")
        if keys:
            keycap(d, (width - PX) * s, cy, s, keys, self.f_kbd)
        self.kind = "error" if error else "toast"
        self._done(img, width, CAPSULE)

    def _thinking(self, title, quote, detail):
        """The question, quiet, over what Nova is doing: that line has light sweeping across it."""
        row1 = bool(quote)
        height = PY + (20 + 10 + 1 + 10 if row1 else 0) + 22 + PY
        img, d, s = self._canvas(WIDTH, height)
        right, y = (WIDTH - PX) * s, PY * s
        if row1:
            cy = y + 10 * s
            mic(d, (PX + 7) * s, cy, s, (255, 255, 255, W40))
            d.text(((PX + 22) * s, cy), fit(f"“{quote.strip()}”", self.f_quote, right - (PX + 22 + 30) * s),
                   font=self.f_quote, fill=(255, 255, 255, W50), anchor="lm")
            self._stop(d, right - 10 * s, cy, s)
            y += 30 * s
            d.line((PX * s, y, right, y), fill=(255, 255, 255, W06), width=max(1, round(s)))
            y += 11 * s
        cy = y + 11 * s
        x = PX * s + self._mark(PX * s, cy, .9) + 10 * s
        left = right
        if not row1:  # no question row for the stop button: it ends this one
            self._stop(d, right - 10 * s, cy, s)
            left -= 30 * s
        caps = "+".join(c for c in self.hotkey.split("+") if c)
        if caps:  # Esc doesn't stop a request at work (it may be meant for another app): the shortcut does
            d.text((left, cy), "to stop", font=self.f_small, fill=(255, 255, 255, W50), anchor="rm")
            left = keycap(d, left - self.f_small.getlength("to stop") - 6 * s, cy, s, caps, self.f_kbd) - 12 * s
        step = detail or (title if title.endswith(("…", "...")) else f"{title}…")
        self._live.append(("shimmer", x / SS, cy / SS, fit(step, self.f_step, left - x)))
        self._done(img, WIDTH, height)

    def _answer(self, title, body, quote):
        """Nova's answer in crisp white, the question quiet above it, the voice wave while it talks."""
        speaking = self.kind == "speaking"
        lead = f"“{quote.strip()}”" if quote else ("" if title == "Nova" else title)
        lines, cut = wrap(body, self.f_body, (WIDTH - 2 * PX) * self.scale * SS, 6) if body else ([], False)
        links = [(label, icon, action) for label, icon, action in (("Ask more", "spark", self.on_ask),
                 ("Open in Nova", "arrow", self.on_open)) if action] if self.kind == "reply" else []
        more, foot, lh = cut and not links, bool(self.telemetry or speaking), 21.6
        height = round(PY + 20 + 10 + 1 + 8 + len(lines) * lh + (18 if more else 0) + (34 if links else 0)
                       + (26 if foot else 0) + PY)
        img, d, s = self._canvas(WIDTH, height)
        right, y = (WIDTH - PX) * s, PY * s
        cy = y + 10 * s
        x = PX * s + self._mark(PX * s, cy, .75) + 8 * s
        end = right
        if speaking:
            self._stop(d, right - 10 * s, cy, s)
            self._live.append(("wave", (right - 28 * s - 19 * s) / SS, cy / SS))
            end -= 56 * s
        if lead:
            d.text((x, cy), fit(lead, self.f_label, end - x), font=self.f_label, fill=(255, 255, 255, W50), anchor="lm")
        y += 30 * s
        d.line((PX * s, y, right, y), fill=(255, 255, 255, W06), width=max(1, round(s)))
        y += 9 * s
        body, rows = Image.new("RGBA", img.size), []
        bd = ImageDraw.Draw(body)
        for line in lines:  # on a layer of their own: they rise in one after another (frame)
            bd.text((PX * s, y + lh * s / 2), line, font=self.f_body, fill=(255, 255, 255, W95), anchor="lm")
            rows.append((round(y / SS), round((y + lh * s) / SS)))
            y += lh * s
        if more:
            d.text((PX * s, y + 9 * s), "Click to see the full reply in Nova", font=self.f_small,
                   fill=theme.T["light"] + (255,), anchor="lm")
            y += 18 * s
        if rows:
            self._body, self._rows = body.reduce(SS), rows
            self._reveal_end = self._reveal_at + 0.1 + 0.06 * len(rows) + VERY_SLOW
        if links:  # "Ask more", "Open in Nova": quiet text buttons under the answer
            y += 8 * s
            cx = PX * s
            for label, icon, action in links:
                cw = 32 * s + self.f_link.getlength(label)
                box = (cx, y, cx + cw, y + 26 * s)
                d.rounded_rectangle(box, 13 * s, fill=(255, 255, 255, 12), outline=(255, 255, 255, 22), width=max(1, round(s)))
                ic, mid = cx + 14 * s, y + 13 * s
                if icon == "spark":
                    Bar._sparkle(d, ic, mid, 6 * s, theme.T["accent"])
                else:
                    wd, c = max(1, round(1.5 * s)), (255, 255, 255, W70)
                    d.line((ic - 3.5 * s, mid + 3.5 * s, ic + 3.5 * s, mid - 3.5 * s), fill=c, width=wd)
                    d.line((ic - 1 * s, mid - 3.5 * s, ic + 3.5 * s, mid - 3.5 * s, ic + 3.5 * s, mid + 1 * s), fill=c, width=wd)
                d.text((cx + 25 * s, mid), label, font=self.f_link, fill=(255, 255, 255, W80), anchor="lm")
                self.chips.append((tuple(v / SS for v in box), action))
                cx += cw + 8 * s
            y += 26 * s
        if foot:  # what Nova runs on, and how to stop it talking
            fy = y + 17 * s
            if self.telemetry:
                d.text((PX * s, fy), self.telemetry.upper(), font=self.f_mono, fill=(255, 255, 255, W50), anchor="lm")
            if speaking:
                d.text((right, fy), "to stop", font=self.f_small, fill=(255, 255, 255, W50), anchor="rm")
                keycap(d, right - self.f_small.getlength("to stop") - 6 * s, fy, s, "Esc", self.f_kbd)
        self._done(img, WIDTH, height)

    def _notice(self, title, body, buttons, detail, labels):
        """A titled card: approvals (amber, with Allow / Deny), errors (a red dot) and everything else (the mark)."""
        approval, error = self.kind == "approval", self.kind == "error"
        inner = (WIDTH - 2 * PX) * self.scale * SS
        lines, cut = wrap(body, self.f_body, inner, 7) if body else ([], False)
        dlines = wrap(detail, self.f_mono, inner - 20 * self.scale * SS, 3 if buttons else 1)[0] if detail else []
        more, lh, mh = cut and not buttons, 20, 17
        rule = bool(lines or dlines or buttons)
        height = (PY + 20 + (20 if rule else 0) + len(lines) * lh
                  + (((10 if lines else 0) + len(dlines) * mh + (12 if buttons else 0)) if dlines else 0)
                  + (18 if more else 0) + (46 if buttons else 0) + PY)
        img, d, s = self._canvas(WIDTH, height)
        right, y = (WIDTH - PX) * s, PY * s
        cy = y + 10 * s
        if approval or error:  # amber and red say something: they stay dots
            r = 4 * s
            d.ellipse((PX * s + 2 * s, cy - r, PX * s + 2 * s + 2 * r, cy + r), fill=(AMBER if approval else RED) + (255,))
            x = (PX + 18) * s
        else:
            x = PX * s + self._mark(PX * s, cy, .9) + 10 * s
        hint = "or say “allow” / “deny”" if approval else ""
        room = right - x
        if hint:
            d.text((right, cy), hint, font=self.f_small, fill=(255, 255, 255, W50), anchor="rm")
            room -= self.f_small.getlength(hint) + 12 * s
        d.text((x, cy), fit(title, self.f_title, room), font=self.f_title,
               fill=AMBER + (255,) if approval else (255, 255, 255, W95), anchor="lm")
        y += 20 * s
        if rule:
            y += 10 * s
            d.line((PX * s, y, right, y), fill=(255, 255, 255, W06), width=max(1, round(s)))
            y += 10 * s
        for line in lines:
            d.text((PX * s, y + lh * s / 2), line, font=self.f_body, fill=(255, 255, 255, W85), anchor="lm")
            y += lh * s
        if dlines:
            y += (10 if lines else 0) * s
            ix = PX * s
            if buttons:  # the command waiting for an OK sits in its own quiet well
                d.rounded_rectangle((PX * s, y, right, y + (len(dlines) * mh + 12) * s), 8 * s, fill=(0, 0, 0, 70),
                                    outline=(255, 255, 255, 18), width=max(1, round(s)))
                ix += 10 * s
                y += 6 * s
            for line in dlines:
                d.text((ix, y + mh * s / 2), line, font=self.f_mono, fill=(255, 255, 255, W80 if buttons else W50), anchor="lm")
                y += mh * s
            y += (6 if buttons else 0) * s
        if more:
            d.text((PX * s, y + 9 * s), "Click to see the full reply in Nova", font=self.f_small,
                   fill=theme.T["light"] + (255,), anchor="lm")
            y += 18 * s
        if buttons:
            y += 14 * s
            bx = PX * s
            yes, no = labels or (f"Allow   {self.hotkey}" if self.hotkey else "Allow", "Deny   Esc")
            for n, (label, action) in enumerate(((yes, self.on_allow), (no, self.on_deny))):
                bw = self.f_button.getlength(label) + 28 * s
                box = (bx, y, bx + bw, y + 32 * s)
                if n:
                    d.rounded_rectangle(box, 16 * s, fill=(255, 255, 255, W06), outline=(255, 255, 255, 26), width=max(1, round(s)))
                else:  # the one solid fill left in the HUD
                    d.rounded_rectangle(box, 16 * s, fill=theme.T["accent"] + (255,))
                d.text((bx + bw / 2, y + 16 * s), label, font=self.f_button,
                       fill=(255, 255, 255, W85) if n else theme.T["ink"] + (255,), anchor="mm")
                self.buttons.append((tuple(v / SS for v in box), action))
                bx += bw + 8 * s
        self._done(img, WIDTH, height)

    def _stop(self, d, cx, cy, s):
        """A stop square with no frame around it; a click on (or near) it stops Nova."""
        stop_square(d, cx, cy, s, 4 * s, 115)  # quiet in a card: white at 45%
        r = 13 * s
        self.stop_box = ((cx - r) / SS, (cy - r) / SS, (cx + r) / SS, (cy + r) / SS)

    # ---------- each frame ----------
    def frame(self, t=None):
        """The content for this moment: the card at rest, with what moves drawn on it."""
        t = time.monotonic() if t is None else t
        still = system.reduced_motion()
        img, k = self.base.copy(), self.scale
        if self._body is not None:
            self._reveal(img, t, still)
        state = {"thinking": "thinking", "speaking": "speaking"}.get(self.kind, "idle")
        for item in self._live:
            if item[0] == "mark":
                mark(img, item[1], item[2], k, item[3], item[4], state, t, self.shown_at)
            elif item[0] == "shimmer":
                shimmer(img, item[1], item[2], item[3], self.f_step, SS, t, still)
            else:  # the voice, as four bars
                heights = [(0.5 if still else 0.3 + 0.7 * abs(math.sin(t * 5 + i * 0.9))) * 12 * k for i in range(4)]
                wave(img, item[1], item[2], heights, 2.5 * k, 3 * k, theme.T["accent"])
        return img

    def _reveal(self, img, t, still):
        """The answer's lines rise in, 60 ms apart, each from 6 px below through a soft blur (transitions.dev's texts
        reveal and streaming text): then they simply stay."""
        if still or t >= self._reveal_end:
            img.alpha_composite(self._body)
            return
        k = self.scale
        for i, (y0, y1) in enumerate(self._rows):
            p = in_out((t - self._reveal_at - 0.1 - 0.06 * i) / VERY_SLOW)
            if p <= 0:
                continue
            row = self._body.crop((0, y0, self._body.width, y1))
            if p < 1:
                row = row.filter(ImageFilter.GaussianBlur(BLUR * k * (1 - p)))
                row.putalpha(row.getchannel("A").point(lambda v: round(v * p)))
            img.alpha_composite(row, (0, min(img.height - row.height, y0 + round(6 * k * (1 - p)))))

    # ---------- input and lifetime ----------
    def _hit(self, event):
        """The button or link under the pointer: its action, or None. `event.x/.y` in the content's pixels."""
        pad = 6 * self.scale  # a little forgiving around each one's edge
        return next((action for (x0, y0, x1, y1), action in (*self.buttons, *self.chips)
                     if x0 - pad <= event.x <= x1 + pad and y0 - pad <= event.y <= y1 + pad), None)

    def click(self, event):
        action = self._hit(event)
        if action:
            return action()
        box = self.stop_box
        if box and box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3] and self.bar is not None:
            return self.bar.on_click()  # while Nova works, the bar's click stops it
        if self.buttons:  # a click beside Allow / Deny is a near miss, not "open the window"
            return
        if self.on_open:
            self.hide()
            self.on_open()

    def hide_later(self, seconds):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if seconds:
            self._hide_job = self.root.after(int(seconds * 1000), self.hide)

    def hide(self):
        if self.visible and self.bar is not None:
            self.bar.attach(None)  # the glass shrinks back into the pill
        self.visible, self._said = False, None
