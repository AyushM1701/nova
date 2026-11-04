"""The reply card: a pane of frosted glass in the theme's colour, drawn like the bar (smooth corners, soft shadow). It
hangs just under the pill, which stays on screen above it.

It shows what Nova heard (in an accent bubble at the top right) and the step it's on while it thinks (with a light
sweeping along its top edge), the answer itself in large type while it talks (with a live waveform) and after, Allow /
Deny when it needs your OK, and, under a finished reply, glass chips to ask more or open it in Nova. It never takes
focus. Click it to open the Nova window, where the full
reply and the history are.
"""
import functools
import math
import re
import time

from PIL import Image, ImageDraw, ImageFilter

from core import glass, icon, system, theme
from core.bar import BOX, CAPSULE, Bar, Layered, _font, dpi_scale

SS = 2  # drawn 2x, then downscaled: smooth corners and text
WIDTH, PAD, RADIUS, SHADOW = 440, 18, 20, 20  # logical px; SHADOW is the transparent margin the shadow uses
AMBER, RED = (255, 186, 60), (255, 122, 122)
BACK_H = 400  # logical px of screen grabbed behind a card as it appears: room for the tallest reply
FONTS = {"regular": ("segoeui.ttf", "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"),
         "semibold": ("seguisb.ttf", "segoeui.ttf", "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"),
         "mono": ("consola.ttf", "/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf")}


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


@functools.lru_cache(maxsize=8)
def _shadow(W, H, m, s):
    """The blurred drop shadow of a card of this size: the blur is the slow part, and cards of one size repeat."""
    shadow = Image.new("RGBA", (W, H))
    ImageDraw.Draw(shadow).rounded_rectangle((m, m + 6 * s, W - m, H - m + 6 * s), RADIUS * s, fill=(0, 0, 0, 120))
    return shadow.filter(ImageFilter.GaussianBlur(12 * s)).resize((W // SS, H // SS), Image.LANCZOS)


@functools.lru_cache(maxsize=4)
def _logo(size):
    """Nova's icon (core/icon.py) at `size` px: drawn once, pasted on every frame."""
    return icon.draw(size, tile=False)  # the bars alone, as in the pill above the card


class Card(Layered):
    bar, back, chips, _strip = None, None, (), None  # the pill it hangs under, the blurred screen behind it, the links under a reply, the sweep's light

    def __init__(self, root, on_allow, on_deny, on_open=None, hotkey="", position="bottom", on_ask=None):
        target = self._init_surface(root, level=25)
        self.logical = dpi_scale(root)  # screen pixels per design pixel (Windows display scaling)
        self.scale = self.logical * self.px  # image pixels per design pixel (x2 more on a Retina Mac)
        self.top = position == "top"
        self.on_allow, self.on_deny, self.on_open, self.on_ask = on_allow, on_deny, on_open, on_ask
        self._fonts()
        self.hotkey, self.visible, self.base, self.buttons = hotkey, False, None, []
        self._hide_job, self._tick_job, self.shown_at = None, None, 0.0
        target.bind("<Button-1>", self._click)
        target.bind("<Motion>", lambda e: target.config(cursor="hand2" if self._hit(e) or self.on_open else ""))
        # Windows rejects every later paint (error 87) if a layered window is hidden before its first one
        self._present(Image.new("RGBA", (1, 1)), 0, 0)
        self.hide()

    def _fonts(self):
        px = lambda size: int(size * self.scale * SS)
        self.f_title, self.f_body = _font(px(14.5), FONTS["semibold"]), _font(px(13.5), FONTS["regular"])
        self.f_lead = _font(px(16.5), FONTS["regular"])  # the answer itself: the biggest thing on the card
        self.f_small, self.f_mono = _font(px(12), FONTS["regular"]), _font(px(12), FONTS["mono"])
        self.f_button, self.f_chip = _font(px(13), FONTS["semibold"]), _font(px(12.5), FONTS["regular"])

    def set_hotkey(self, hotkey):
        self.hotkey = hotkey

    def bottom(self):
        """The screen y of the panel's bottom edge while a card hangs at the top of the screen, else 0 (nothing to avoid)."""
        if not (self.top and self.visible and self.base):
            return 0
        return int(self.y + self.base.height / self.px - SHADOW * self.logical)

    # ---------- content ----------
    def show(self, title, body="", buttons=False, hide_after=None, kind=None, quote="", detail="", labels=None):
        self.kind = kind or ("approval" if buttons else "info")
        self._render(title, plain(body), buttons, quote, detail, labels)
        left, top, right, bottom = system.work_area()
        width, height, k = self._text.width / self.px, self._text.height / self.px, self.logical
        self.x = int((left + right - width) / 2)
        if self.top:  # under the notch, or just under the pill, which stays on screen above it
            notch_h = system.notch()[1]
            self.y = int(((notch_h + 50) * k if notch_h else top + (6 + CAPSULE + 8) * k) - SHADOW * k)
        else:  # dock above the bar (its window is BOX tall), letting the shadow margin overlap it
            self.y = int(bottom - (BOX[1] - 2 + 4) * k - height + SHADOW * k)
        fresh = not self.visible
        if fresh:
            self.visible, self.shown_at = True, time.monotonic()
            m = round(self.panel[0])  # the glass takes its backdrop from where the panel will be, before it is there
            self.back = None if (not self.top or system.IS_MAC) else glass.backdrop(
                (self.x + m, self.y + m, self.x + self.panel[2], self.y + m + BACK_H * k))
        self.base = self._compose()
        self._frame()
        if fresh:
            self._show()
            if self.bar is not None:
                self.bar.cover(True)  # the pill stays up (orb and Ask) while the card hangs under it
        if not self._tick_job:
            self._tick()
        self.hide_later(hide_after)

    def _render(self, title, body, buttons, quote, detail, labels=None):
        """The card at rest as two layers, at 1x: its shadow, and its text and buttons. The glass goes between them
        (_compose); the animated bits go on top per frame. A spoken answer leads with the answer, large, under the
        question it answers; other cards lead with their title."""
        T, s, kind = theme.T, self.scale * SS, self.kind
        answer = kind in ("speaking", "reply")
        inner = (WIDTH - 2 * PAD) * s
        m = SHADOW * s
        x0, right = m + PAD * s, m + (WIDTH - PAD) * s
        heading = "" if answer and title == "Nova" else title  # "Nova" over Nova's own answer says nothing
        title_font = self.f_chip if answer else self.f_title
        head_w = 26 * s + (title_font.getlength(heading) if heading else 0)

        # the question, as a bubble at the top right like a message you sent: on the title row when it fits
        bubble, bubble_row = None, False
        if quote:
            room = inner - head_w - 16 * s
            bubble_row = room >= 150 * s
            width = (room if bubble_row else inner * 0.8) - 24 * s
            bubble = wrap(quote.strip(), self.f_chip, width, 1 if bubble_row or answer else 2)[0]
        caps, hint = self._hint_parts()
        hint_row = bool(caps or hint) and not bubble_row  # else the hint goes under the card's content

        blocks = []  # (kind, lines, font, colour, line height)
        if bubble and not bubble_row:
            blocks.append(("bubble", bubble, self.f_chip, T["ink"], 18 * s))
        body_cut = False
        if body:
            font, lh, n = (self.f_lead, 24 * s, 6) if answer else (self.f_body, 20 * s, 7)
            lines, body_cut = wrap(body, font, inner, n)
            blocks.append(("text", lines, font, T["text"] if answer else T["body"], lh))
        if detail:
            lines, _ = wrap(detail, self.f_mono, inner - 20 * s, 3 if buttons else 1)
            blocks.append(("mono", lines, self.f_mono, T["text"] if buttons else T["faint"], 18 * s))
        links = [(label, icon, action) for label, icon, action in (("Ask more", "spark", self.on_ask), ("Open in Nova", "arrow", self.on_open))
                 if action] if kind == "reply" else []
        if body_cut and not links:
            blocks.append(("text", ["Click to see the full reply in Nova"], self.f_small, T["light"], 18 * s))
        heights = [len(lines) * lh + (6 * s if b == "bubble" else 8 * s if b == "mono" and buttons else 0)
                   for b, lines, _, _, lh in blocks]
        gap = 10 * s
        footer = 44 * s if buttons else 42 * s if links else 30 * s if (caps or hint) and not hint_row else 0
        height = PAD * s + 24 * s + sum(h + gap for h in heights) + footer + PAD * s
        W, H = int(WIDTH * s + 2 * m), int(height + 2 * m)

        img = Image.new("RGBA", (W, H))  # text and buttons only: the shadow and the glass are other layers
        d = ImageDraw.Draw(img)
        cy = m + PAD * s + 12 * s
        if heading:
            d.text((x0 + 26 * s, cy), heading, font=title_font, fill=(T["muted"] if answer else T["text"]) + (255,), anchor="lm")
        if bubble_row:
            self._bubble(d, right, cy - 12 * s, bubble, s)
        elif hint_row:
            self._hint(d, right, cy, s, caps, hint)
        y = m + PAD * s + 24 * s
        for (b, lines, font, color, lh), block_h in zip(blocks, heights):
            y += gap
            if b == "bubble":
                self._bubble(d, right, y, lines, s)
            else:
                ix = x0
                if b == "mono" and buttons:  # the command waiting for an OK sits in its own well
                    d.rounded_rectangle((x0, y, right, y + block_h), 10 * s, fill=(0, 0, 0, 90),
                                        outline=(255, 255, 255, 28), width=max(1, round(s)))
                    ix += 10 * s
                top = y + (4 * s if b == "mono" and buttons else 0)
                for i, line in enumerate(lines):
                    d.text((ix, top + i * lh), line, font=font, fill=color + (255,))
            y += block_h
        self.buttons, self.chips = [], []
        if buttons:
            y += 10 * s
            bx = x0
            yes, no = labels or (f"Allow   {self.hotkey}" if self.hotkey else "Allow", "Deny   Esc")
            for n, (label, action) in enumerate(((yes, self.on_allow), (no, self.on_deny))):
                bw = self.f_button.getlength(label) + 30 * s
                box = (bx, y, bx + bw, y + 34 * s)
                if n:
                    self._chip_well(d, box, s)
                else:
                    d.rounded_rectangle(box, 17 * s, fill=T["accent"] + (255,), outline=(255, 255, 255, 55), width=max(1, round(s)))
                d.text((bx + bw / 2, y + 17 * s), label, font=self.f_button, fill=(T["text"] if n else T["ink"]) + (255,), anchor="mm")
                self.buttons.append((tuple(v / SS for v in box), action))
                bx += bw + 10 * s
        elif links:  # "Ask more", "Open in Nova": glass chips under the answer
            y += 12 * s
            cx = x0
            for label, icon, action in links:
                cw = 33 * s + self.f_chip.getlength(label) + 14 * s
                box = (cx, y, cx + cw, y + 30 * s)
                self._chip_well(d, box, s)
                ic, mid = cx + 19 * s, y + 15 * s
                if icon == "spark":
                    Bar._sparkle(d, ic, mid, 7 * s, T["light"])
                else:
                    wd = max(1, round(1.7 * s))
                    d.line((ic - 4.5 * s, mid + 4.5 * s, ic + 4.5 * s, mid - 4.5 * s), fill=T["light"] + (255,), width=wd)
                    d.line((ic - 1.5 * s, mid - 4.5 * s, ic + 4.5 * s, mid - 4.5 * s, ic + 4.5 * s, mid + 1.5 * s), fill=T["light"] + (255,), width=wd)
                d.text((cx + 33 * s, mid), label, font=self.f_chip, fill=T["text"] + (255,), anchor="lm")
                self.chips.append((tuple(v / SS for v in box), action))
                cx += cw + 8 * s
        elif footer:  # what stops Nova, under the answer
            self._hint(d, right, y + 6 * s + 15 * s, s, caps, hint)
        self.icon_at = ((x0 + 9 * s) / SS, cy / SS)
        self.panel = (m / SS, m / SS, (W - m) / SS)
        self._strip = None  # the sweep's light is in the theme's colour
        self._shadow_img = _shadow(W, H, m, s)
        self._text = img.resize((W // SS, H // SS), Image.LANCZOS)

    def _bubble(self, d, right, y, lines, s):
        """What Nova heard, right-aligned in the accent, like a message you sent."""
        T, font, lh = theme.T, self.f_chip, 18 * s
        width = max(font.getlength(line) for line in lines) + 24 * s
        y1 = y + len(lines) * lh + 6 * s
        d.rounded_rectangle((right - width, y, right, y1), min(12 * s, (y1 - y) / 2), fill=T["accent"] + (255,))
        for i, line in enumerate(lines):
            d.text((right - width + 12 * s, y + 3 * s + lh / 2 + i * lh), line, font=font, fill=T["ink"] + (255,), anchor="lm")

    @staticmethod
    def _chip_well(d, box, s):
        """A lighter pocket of the glass: Deny, and the links under an answer."""
        light = theme.T["light"]
        d.rounded_rectangle(box, (box[3] - box[1]) / 2, fill=light + (30,), outline=light + (76,), width=max(1, round(s)))

    def _hint_parts(self):
        """What stops Nova: (keys, words)."""
        if self.kind == "speaking":
            return ["Esc"], "to stop"
        if self.kind == "thinking" and self.hotkey:  # Esc doesn't stop a request at work (it may be meant for another app)
            return [c for c in self.hotkey.split("+") if c], "to stop"
        if self.kind == "approval":
            return [], "or say “allow” / “deny”"
        return [], ""

    def _hint(self, d, right, cy, s, caps, text):
        """Keys as little keycaps, then what they do, ending at `right`."""
        T = theme.T
        if text:
            d.text((right, cy), text, font=self.f_small, fill=T["muted"] + (255,), anchor="rm")
            right -= self.f_small.getlength(text) + 8 * s
        for cap in reversed(caps):
            w = max(20 * s, self.f_small.getlength(cap) + 12 * s)
            d.rounded_rectangle((right - w, cy - 10 * s, right, cy + 10 * s), 6 * s, fill=T["light"] + (26,),
                                outline=T["light"] + (76,), width=max(1, round(s)))
            d.text((right - w / 2, cy), cap, font=self.f_small, fill=T["muted"] + (255,), anchor="mm")
            right -= w + 4 * s

    def _compose(self):
        """Shadow, then the glass (with the screen behind it, if it was grabbed), then the text."""
        T, (W, H), m = theme.T, self._text.size, round(self.panel[0])
        pw, ph = W - 2 * m, H - 2 * m
        back = self.back.crop((0, 0, pw, ph)) if self.back and self.back.width >= pw and self.back.height >= ph else None
        out = self._shadow_img.copy()
        out.alpha_composite(glass.pane(pw, ph, round(RADIUS * self.scale), T["tint"], T["accent"], back), (m, m))
        out.alpha_composite(self._text)
        return out

    # ---------- animation ----------
    def _frame(self):
        t = time.monotonic()
        img = self.base.copy()
        self._icon(img, t)
        if self.kind == "thinking":
            self._sweep(img, t)
        fade = 1.0 if system.reduced_motion() else min(1.0, (t - self.shown_at) / 0.18)
        rise = int((1 - fade) ** 3 * 10 * self.logical) * (-1 if self.top else 1)  # drops into place as it fades in
        self._present(img, self.x, self.y + rise, int(255 * (1 - (1 - fade) ** 3)))

    def _icon(self, img, t):
        """A 20 px status mark beside the title, drawn small at 4x for smooth edges."""
        size, k = int(20 * self.scale), 4
        sprite = Image.new("RGBA", (size * k, size * k))
        d = ImageDraw.Draw(sprite)
        T = theme.T
        c, color = size * k / 2, {"thinking": T["light"], "speaking": T["text"], "approval": AMBER, "error": RED}.get(self.kind, T["accent"])
        if self.kind == "thinking":
            for i in range(3):
                a = 0.5 + 0.5 * math.sin(t * 6 - i * 0.9)
                r, x = (1.6 + 1.1 * a) * self.scale * k, c + (i - 1) * 6 * self.scale * k
                d.ellipse((x - r, c - r, x + r, c + r), fill=color + (int(110 + 145 * a),))
        elif self.kind == "speaking":
            bw = 2.2 * self.scale * k
            for i in range(4):
                hh = (0.3 + 0.7 * abs(math.sin(t * 5 + i * 0.9))) * 14 * self.scale * k
                x = c + (i - 1.5) * 4.4 * self.scale * k
                d.rounded_rectangle((x - bw / 2, c - hh / 2, x + bw / 2, c + hh / 2), bw / 2, fill=color + (255,))
        elif self.kind in ("approval", "error"):  # amber and red say something: they stay dots
            r = 4.5 * self.scale * k
            d.ellipse((c - r, c - r, c + r, c + r), fill=color + (255,))
        else:  # Nova's own mark, as in the tray
            mark = _logo(size)
            img.alpha_composite(mark, (int(self.icon_at[0] - size / 2), int(self.icon_at[1] - size / 2)))
            return
        sprite = sprite.resize((size, size), Image.LANCZOS)
        img.alpha_composite(sprite, (int(self.icon_at[0] - size / 2), int(self.icon_at[1] - size / 2)))

    def _sweep(self, img, t):
        """While thinking, a soft violet light travels along the card's top edge."""
        left, top, right = self.panel
        span, glow = right - left - 2 * RADIUS * self.scale, int(90 * self.scale)
        x = left + RADIUS * self.scale + (t * 0.55 % 1.0) * span - glow / 2
        if self._strip is None:  # built once: a short line that fades in and out
            self._strip = Image.new("RGBA", (glow, max(2, int(2 * self.scale))))
            for i in range(glow):
                self._strip.paste(theme.T["accent"] + (int(230 * math.sin(math.pi * i / glow) ** 2),), (i, 0, i + 1, self._strip.height))
        img.alpha_composite(self._strip, (int(x), int(top)))

    def _tick(self):
        self._tick_job = None
        if not self.visible:
            return
        entering = time.monotonic() - self.shown_at < 0.2
        if entering or self.kind in ("thinking", "speaking", "approval"):
            self._frame()
        self._tick_job = self.win.after(16 if entering else 33, self._tick)

    # ---------- input and lifetime ----------
    def _hit(self, event):
        """The button or link under the pointer: its action, or None."""
        pad = 6 * self.scale  # a little forgiving around each one's edge
        return next((action for (x0, y0, x1, y1), action in (*self.buttons, *self.chips)
                     if x0 - pad <= event.x <= x1 + pad and y0 - pad <= event.y <= y1 + pad), None)

    def _click(self, event):
        action = self._hit(event)
        if action:
            return action()
        if self.buttons:  # a click beside Allow / Deny is a near miss, not "open the window"
            return
        if self.on_open:
            self.hide()
            self.on_open()

    def hide_later(self, seconds):
        if self._hide_job:
            self.win.after_cancel(self._hide_job)
            self._hide_job = None
        if seconds:
            self._hide_job = self.win.after(int(seconds * 1000), self.hide)

    def hide(self):
        if self.visible and self.bar is not None:
            self.bar.cover(False)
        self.visible, self.back = False, None
        self._hide()
