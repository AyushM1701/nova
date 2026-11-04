"""The reply card: a pane of frosted glass in the theme's colour, drawn like the bar (smooth corners, soft shadow).

It shows what Nova heard (in an accent bubble) and the step it's on while it thinks (with a light sweeping along its
top edge), the answer while it talks (with a live waveform), Allow / Deny when it needs your OK, and, under a finished
reply, a way to ask more or open it in Nova. It never takes focus. Click it to open the Nova window, where the full
reply and the history are.
"""
import functools
import math
import re
import time

from PIL import Image, ImageDraw, ImageFilter

from core import glass, system, theme
from core.bar import BOX, Bar, Layered, _font, dpi_scale, spring

SS = 2  # drawn 2x, then downscaled: smooth corners and text
WIDTH, PAD, RADIUS, SHADOW = 440, 18, 20, 20  # logical px; SHADOW is the transparent margin the shadow uses
AMBER, RED, INK = (255, 186, 60), (255, 122, 122), (11, 13, 26)
BACK_H = 340  # logical px of screen grabbed behind a card as it appears: room for the tallest reply
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


class Card(Layered):
    # At the top of the screen (Windows) the card sits where the pill is and grows out of it, like the Dynamic Island:
    # `over` says so, `cw`/`ch` are the panel's size right now (device px), `seed` the pill it grows from and shrinks
    # back to, `full` its size at rest. Class defaults keep a Card made without __init__ a plain one.
    bar, over, closing, anim, cw, ch, vw, vh, _last = None, False, False, False, 0.0, 0.0, 0.0, 0.0, None
    seed, full = (0.0, 0.0), (0.0, 0.0)
    back, chips, _strip = None, (), None  # the blurred screen behind the card, the links under a reply, the sweep's light

    def __init__(self, root, on_allow, on_deny, on_open=None, hotkey="", position="bottom", on_ask=None):
        target = self._init_surface(root, level=25)
        self.logical = dpi_scale(root)  # screen pixels per design pixel (Windows display scaling)
        self.scale = self.logical * self.px  # image pixels per design pixel (x2 more on a Retina Mac)
        self.top = position == "top"
        self.on_allow, self.on_deny, self.on_open, self.on_ask = on_allow, on_deny, on_open, on_ask
        px = lambda size: int(size * self.scale * SS)
        self.f_title, self.f_body = _font(px(14.5), FONTS["semibold"]), _font(px(13.5), FONTS["regular"])
        self.f_small, self.f_mono = _font(px(12), FONTS["regular"]), _font(px(12), FONTS["mono"])
        self.f_button = _font(px(13), FONTS["semibold"])
        self.hotkey, self.visible, self.base, self.buttons = hotkey, False, None, []
        self._hide_job, self._tick_job, self.shown_at = None, None, 0.0
        target.bind("<Button-1>", self._click)
        target.bind("<Motion>", lambda e: target.config(cursor="hand2" if self._hit(e) or self.on_open else ""))
        # Windows rejects every later paint (error 87) if a layered window is hidden before its first one
        self._present(Image.new("RGBA", (1, 1)), 0, 0)
        self.hide()

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
        self.over = self.top and self.bar is not None and not system.IS_MAC
        if self.top:  # under the notch; or flush with the pill, which the card grows out of; or just under the bar
            notch_h = system.notch()[1]
            self.y = (int((notch_h + 50) * k - SHADOW * k) if notch_h
                      else int(top + (6 if self.over else 50) * k - SHADOW * k))
        else:  # dock above the bar (its window is BOX tall), letting the shadow margin overlap it
            self.y = int(bottom - (BOX[1] - 2 + 4) * k - height + SHADOW * k)
        fresh = not self.visible
        if fresh:
            self.visible, self.shown_at, self.closing = True, time.monotonic(), False
            m = round(self.panel[0])  # the glass takes its backdrop from where the panel will be, before it is there
            self.back = None if (not self.top or system.IS_MAC) else glass.backdrop(
                (self.x + m, self.y + m, self.x + self.panel[2], self.y + m + BACK_H * k))
        self.closing = False  # shown again while shrinking: it grows back from where it is
        self.base = self._compose()
        self.full = (self.panel[2] - self.panel[0], self.base.height - 2 * self.panel[0])
        if self.over:
            sw, sh = self.bar.pill_size()[:2]
            self.seed = (min(sw, self.full[0]), min(sh, self.full[1]))
        if not self.over or system.reduced_motion():
            self.cw, self.ch, self.anim = self.full[0], self.full[1], False
        elif fresh:
            self.cw, self.ch, self.vw, self.vh, self.anim = *self.seed, 0.0, 0.0, True
        else:  # new content while it is up: grows if it is bigger, snaps if smaller
            self.cw, self.ch, self.anim = min(self.cw, self.full[0]), min(self.ch, self.full[1]), True
        self._frame()
        if fresh:
            self._show()
            if self.over:
                self.bar.cover(True)  # after the card is up, so there is no frame with neither
        if not self._tick_job:
            self._tick()
        self.hide_later(hide_after)

    def _render(self, title, body, buttons, quote, detail, labels=None):
        """The card at rest as two layers, at 1x: its shadow, and its text and buttons. The glass goes between them
        (_compose); the animated bits go on top per frame."""
        T, s = theme.T, self.scale * SS
        inner = (WIDTH - 2 * PAD) * s
        blocks, y = [], PAD * s + 24 * s  # the title row is 24 px tall
        if quote:  # what Nova heard, as a bubble at the right, like a message you sent
            lines, _ = wrap(f"“{quote.strip()}”", self.f_body, inner * 0.8 - 24 * s, 2)
            blocks.append(("bubble", lines, self.f_body, T["ink"], 20 * s))
        body_cut = False
        if body:
            lines, body_cut = wrap(body, self.f_body, inner, 7)
            blocks.append(("text", lines, self.f_body, T["body"], 20 * s))
        if detail:
            lines, _ = wrap(detail, self.f_mono, inner - 20 * s, 3 if buttons else 1)
            blocks.append(("mono", lines, self.f_mono, T["text"] if buttons else T["faint"], 18 * s))
        links = [(label, icon, action) for label, icon, action in (("Ask more", "spark", self.on_ask), ("Open in Nova", "arrow", self.on_open))
                 if action] if self.kind == "reply" else []
        if body_cut and not links:
            blocks.append(("text", ["Click to see the full reply in Nova"], self.f_small, T["light"], 18 * s))
        heights = [len(lines) * lh + (14 * s if kind == "bubble" else 0) + 6 * s for kind, lines, _, _, lh in blocks]
        y += 6 * s if blocks else 0
        height = (y + sum(heights) + (44 * s if buttons else 0) + (34 * s if links else 0) + PAD * s
                  - (6 * s if blocks else 0))
        m = SHADOW * s
        W, H = int(WIDTH * s + 2 * m), int(height + 2 * m)

        img = Image.new("RGBA", (W, H))  # text and buttons only: the shadow and the glass are other layers
        d = ImageDraw.Draw(img)
        x0, right = m + PAD * s, W - m - PAD * s
        d.text((x0 + 26 * s, m + PAD * s + 12 * s), title, font=self.f_title, fill=T["text"] + (255,), anchor="lm")
        self._hint(d, right, m + PAD * s + 12 * s, s)
        y = m + y
        for (kind, lines, font, color, lh), block_h in zip(blocks, heights):
            if kind == "bubble":
                width = max(font.getlength(line) for line in lines) + 24 * s
                bx1, by1 = right, y + len(lines) * lh + 14 * s - 6 * s
                d.rounded_rectangle((bx1 - width, y, bx1, by1), min(14 * s, (by1 - y) / 2), fill=T["accent"] + (255,))
                for i, line in enumerate(lines):
                    d.text((bx1 - width + 12 * s, y + 7 * s + i * lh), line, font=font, fill=color + (255,))
            else:
                if kind == "mono" and buttons:  # the command waiting for an OK sits in its own well
                    d.rounded_rectangle((x0, y - 4 * s, right, y + block_h - 4 * s), 10 * s, fill=(0, 0, 0, 90),
                                        outline=(255, 255, 255, 28), width=max(1, round(s)))
                for i, line in enumerate(lines):
                    d.text((x0 + (10 * s if kind == "mono" and buttons else 0), y + i * lh), line, font=font, fill=color + (255,))
            y += block_h
        self.buttons, self.chips = [], []
        if buttons:
            y += 4 * s
            bx = x0
            yes, no = labels or (f"Allow   {self.hotkey}" if self.hotkey else "Allow", "Deny   Esc")
            for label, fill, ink, action in ((yes, T["accent"], T["ink"], self.on_allow), (no, T["raised"], T["text"], self.on_deny)):
                bw = self.f_button.getlength(label) + 28 * s
                d.rounded_rectangle((bx, y, bx + bw, y + 34 * s), 17 * s, fill=fill + (255,), outline=(255, 255, 255, 55),
                                    width=max(1, round(s)))
                d.text((bx + bw / 2, y + 17 * s), label, font=self.f_button, fill=ink + (255,), anchor="mm")
                self.buttons.append(((bx / SS, y / SS, (bx + bw) / SS, (y + 34 * s) / SS), action))
                bx += bw + 10 * s
        if links:  # "Ask more · Open in Nova": quiet links under the reply
            cx, cy = x0, y + 2 * s + 12 * s
            for n, (label, icon, action) in enumerate(links):
                if n:
                    d.ellipse((cx + 8 * s, cy - 1.5 * s, cx + 11 * s, cy + 1.5 * s), fill=T["faint"] + (255,))
                    cx += 19 * s
                if icon == "spark":
                    Bar._sparkle(d, cx + 7 * s, cy, 7 * s, T["light"])
                else:
                    d.line((cx + 2 * s, cy + 5 * s, cx + 12 * s, cy - 5 * s), fill=T["light"] + (255,), width=max(1, round(1.8 * s)))
                    d.line((cx + 5 * s, cy - 5 * s, cx + 12 * s, cy - 5 * s, cx + 12 * s, cy + 2 * s), fill=T["light"] + (255,),
                           width=max(1, round(1.8 * s)))
                d.text((cx + 20 * s, cy), label, font=self.f_small, fill=T["muted"] + (255,), anchor="lm")
                x1 = cx + 20 * s + self.f_small.getlength(label)
                self.chips.append(((cx / SS, (cy - 14 * s) / SS, x1 / SS, (cy + 14 * s) / SS), action))
                cx = x1
        self.icon_at = ((x0 + 9 * s) / SS, (m + PAD * s + 12 * s) / SS)
        self.panel = (m / SS, m / SS, (W - m) / SS)
        self._strip = None  # the sweep's light is in the theme's colour
        self._shadow_img = _shadow(W, H, m, s)
        self._text = img.resize((W // SS, H // SS), Image.LANCZOS)

    def _hint(self, d, right, cy, s):
        """What stops Nova, at the right of the title row: keys as little keycaps, then what they do."""
        T, kind = theme.T, self.kind
        caps, text = [], ""
        if kind == "speaking":
            caps, text = ["Esc"], "to stop"
        elif kind == "thinking" and self.hotkey:  # Esc doesn't stop a request at work (it may be meant for another app)
            caps, text = [c for c in self.hotkey.split("+") if c], "to stop"
        elif kind == "approval":
            text = "or say “allow” / “deny”"
        if text:
            d.text((right, cy), text, font=self.f_small, fill=T["faint"] + (255,), anchor="rm")
            right -= self.f_small.getlength(text) + 8 * s
        for cap in reversed(caps):
            w = max(20 * s, self.f_small.getlength(cap) + 12 * s)
            d.rounded_rectangle((right - w, cy - 10 * s, right, cy + 10 * s), 6 * s, fill=(255, 255, 255, 22),
                                outline=(255, 255, 255, 60), width=max(1, round(s)))
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
        if self.over:  # the spring does the entrance: no fade
            x = self.x
            if self.closing or abs(self.cw - self.full[0]) > 0.5 or abs(self.ch - self.full[1]) > 0.5:
                img, x = self._shape(img)
            return self._present(img, x, self.y)
        fade = min(1.0, (t - self.shown_at) / 0.16)
        rise = int((1 - fade) ** 2 * 8 * self.logical) * (-1 if self.top else 1)  # slides into place as it fades in
        self._present(img, self.x, self.y + rise, int(255 * (1 - (1 - fade) ** 3)))

    def _shape(self, img):
        """The card at its current size, mid-grow: the middle of the finished card cut to a rounded shape (its corners
        go from the pill's to the card's). Cheap: no text is drawn again. Returns the image and its screen x."""
        m = int(round(self.panel[0]))  # the shadow's margin: not drawn while it moves
        fw, fh = img.width - 2 * m, img.height - 2 * m
        cw, ch = min(max(2, round(self.cw)), fw), min(max(2, round(self.ch)), fh)
        left = m + (fw - cw) // 2
        crop = img.crop((left, m, left + cw, m + ch))
        grown = min(1.0, max(0.0, (ch - self.seed[1]) / max(1.0, self.full[1] - self.seed[1])))
        radius = min(ch / 2, cw / 2, self.seed[1] / 2 * (1 - grown) + RADIUS * self.scale * grown)
        mask = Image.new("L", (cw * 2, ch * 2), 0)  # drawn at 2x for smooth edges, then halved
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw * 2 - 1, ch * 2 - 1), radius * 2, fill=255)
        out = Image.new("RGBA", (cw + 2 * m, ch + 2 * m))
        out.paste(crop, (m, m), mask.reduce(2))
        return out, self.x + (img.width - out.width) // 2

    def _step(self):
        """Move the grow/shrink spring one frame. True while a frame is still needed (including the one that settles)."""
        if not self.over:
            return False
        now = time.monotonic()
        dt = min(0.05, now - self._last) if self._last else 1 / 60
        tw, th = self.seed if self.closing else self.full
        if system.reduced_motion():
            self.cw, self.ch, self.vw, self.vh = tw, th, 0.0, 0.0
        else:
            self.cw, self.vw = spring(self.cw, self.vw, tw, dt)
            self.ch, self.vh = spring(self.ch, self.vh, th, dt)
        # close enough to snap (a pixel and a half, slower than 30 px/s): the spring's last sub-pixel creep takes as long again
        settled = abs(self.cw - tw) < 1.5 and abs(self.ch - th) < 1.5 and abs(self.vw) < 30 and abs(self.vh) < 30
        if settled:
            self.cw, self.ch, self.vw, self.vh = tw, th, 0.0, 0.0
        was, self.anim, self._last = self.anim, not settled, None if settled else now
        if settled and self.closing:
            self._finish()
            return False
        return was or self.anim

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
        else:
            r = 4.5 * self.scale * k
            d.ellipse((c - r, c - r, c + r, c + r), fill=color + (255,))
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
        moving = self._step()
        if not self.visible:  # it has shrunk back into the pill
            return
        if moving or self.kind in ("thinking", "speaking", "approval") or time.monotonic() - self.shown_at < 0.2:
            self._frame()
        self._tick_job = self.win.after(16 if moving else 33, self._tick)

    # ---------- input and lifetime ----------
    def _hit(self, event):
        """The button or link under the pointer: its action, or None."""
        if self.over and self.anim:  # still moving: a click now would land beside them
            return None
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

    def hide(self, instant=False):
        """Shrink back into the pill, then go. `instant`: at once (the mic is opening and needs the pill)."""
        if self.visible and self.over and not instant:
            if not self.closing:
                self.closing, self.anim = True, True
                self.hide_later(None)
                if not self._tick_job:
                    self._tick()
            return
        self.visible = self.closing = self.anim = False
        self._last, self.back = None, None
        if self.over:
            self.bar.cover(False)
        self._hide()

    def _finish(self):  # the spring has settled on the pill
        self.hide(instant=True)
