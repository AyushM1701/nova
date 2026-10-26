"""The reply card: a floating panel docked just above the bar, drawn like the bar (smooth corners, soft shadow).

It shows what Nova heard and the step it's on while it thinks (with a light sweeping along its top edge),
the answer while it talks (with a live waveform), and Allow / Deny when it needs your OK. It never takes
focus. Click it to open the Nova window, where the full reply and the history are.
"""
import math
import re
import time

from PIL import Image, ImageDraw, ImageFilter

from core import system
from core.bar import BOX, Layered, _font, dpi_scale

SS = 2  # drawn 2x, then downscaled: smooth corners and text
WIDTH, PAD, RADIUS, SHADOW = 440, 18, 16, 20  # logical px; SHADOW is the transparent margin the shadow uses
BG, EDGE = (13, 15, 26, 246), (255, 255, 255, 30)
TEXT, BODY, DIM, FAINT = (240, 242, 250), (212, 215, 232), (164, 168, 194), (124, 129, 156)
ACCENT, AMBER, RED, TRACK = (123, 109, 255), (255, 186, 60), (255, 122, 122), (38, 42, 66)
ICON = {"thinking": ACCENT, "speaking": TEXT, "approval": AMBER, "error": RED, "info": ACCENT, "reply": ACCENT}
HINT = {"speaking": "Esc to stop", "approval": "or say “allow” / “deny”"}
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


class Card(Layered):
    def __init__(self, root, on_allow, on_deny, on_open=None, hotkey="", position="bottom"):
        target = self._init_surface(root, level=25)
        self.logical = dpi_scale(root)  # screen pixels per design pixel (Windows display scaling)
        self.scale = self.logical * self.px  # image pixels per design pixel (x2 more on a Retina Mac)
        self.top = position == "top"
        self.on_allow, self.on_deny, self.on_open = on_allow, on_deny, on_open
        px = lambda size: int(size * self.scale * SS)
        self.f_title, self.f_body = _font(px(14.5), FONTS["semibold"]), _font(px(13.5), FONTS["regular"])
        self.f_small, self.f_mono = _font(px(12), FONTS["regular"]), _font(px(12), FONTS["mono"])
        self.f_button = _font(px(13), FONTS["semibold"])
        self.hotkey, self.visible, self.base, self.buttons = hotkey, False, None, []
        self._hide_job, self._tick_job, self.shown_at = None, None, 0.0
        target.bind("<Button-1>", self._click)
        target.bind("<Motion>", lambda e: target.config(cursor="hand2" if self._button_at(e) or self.on_open else ""))
        # Windows rejects every later paint (error 87) if a layered window is hidden before its first one
        self._present(Image.new("RGBA", (1, 1)), 0, 0)
        self.hide()

    def set_hotkey(self, hotkey):
        self.hotkey = hotkey

    # ---------- content ----------
    def show(self, title, body="", buttons=False, hide_after=None, kind=None, quote="", detail="", labels=None):
        self.kind = kind or ("approval" if buttons else "info")
        self.base = self._render(title, plain(body), buttons, quote, detail, labels)
        left, top, right, bottom = system.work_area()
        width, height, k = self.base.width / self.px, self.base.height / self.px, self.logical
        self.x = int((left + right - width) / 2)
        if self.top:  # just under the bar: hanging from the notch, or along the top of the screen
            notch_h = system.notch()[1]
            self.y = int((notch_h + 50) * k - SHADOW * k) if notch_h else int(top + 50 * k - SHADOW * k)
        else:  # dock above the bar (its window is BOX tall), letting the shadow margin overlap it
            self.y = int(bottom - (BOX[1] - 2 + 4) * k - height + SHADOW * k)
        if not self.visible:
            self.visible, self.shown_at = True, time.monotonic()
            self._frame()
            self._show()
        else:
            self._frame()
        if not self._tick_job:
            self._tick()
        self.hide_later(hide_after)

    def _render(self, title, body, buttons, quote, detail, labels=None):
        """The card at rest, at 1x: shadow, panel, text and buttons. Animated bits go on top per frame."""
        s = self.scale * SS
        inner = (WIDTH - 2 * PAD) * s
        blocks, y = [], PAD * s + 24 * s  # the title row is 24 px tall
        if quote:
            lines, _ = wrap(f"“{quote.strip()}”", self.f_body, inner, 2)
            blocks.append((lines, self.f_body, DIM, 20 * s))
        body_cut = False
        if body:
            lines, body_cut = wrap(body, self.f_body, inner, 7)
            blocks.append((lines, self.f_body, BODY, 20 * s))
        if detail:
            lines, _ = wrap(detail, self.f_mono, inner - 20 * s, 3 if buttons else 1)
            blocks.append((lines, self.f_mono, TEXT if buttons else FAINT, 18 * s))
        if body_cut:
            blocks.append((["Click to see the full reply in Nova"], self.f_small, ACCENT, 18 * s))
        heights = [len(lines) * lh + 6 * s for lines, _, _, lh in blocks]
        y += 6 * s if blocks else 0
        height = y + sum(heights) + (44 * s if buttons else 0) + PAD * s - (6 * s if blocks else 0)
        m = SHADOW * s
        W, H = int(WIDTH * s + 2 * m), int(height + 2 * m)

        shadow = Image.new("RGBA", (W, H))
        ImageDraw.Draw(shadow).rounded_rectangle((m, m + 6 * s, W - m, H - m + 6 * s), RADIUS * s, fill=(0, 0, 0, 120))
        img = shadow.filter(ImageFilter.GaussianBlur(12 * s))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((m, m, W - m, H - m), RADIUS * s, fill=BG, outline=EDGE, width=max(1, round(s)))
        x0 = m + PAD * s
        d.text((x0 + 26 * s, m + PAD * s + 12 * s), title, font=self.f_title, fill=TEXT, anchor="lm")
        hint = HINT.get(self.kind)
        if self.kind == "thinking":  # Esc doesn't stop a request at work (it may be meant for another app)
            hint = f"{self.hotkey} to stop" if self.hotkey else None
        if hint:
            d.text((W - m - PAD * s, m + PAD * s + 12 * s), hint, font=self.f_small, fill=FAINT, anchor="rm")
        y = m + y
        for (lines, font, color, lh), block_h in zip(blocks, heights):
            if font is self.f_mono and buttons:  # the command waiting for an OK sits in its own well
                d.rounded_rectangle((x0, y - 4 * s, W - m - PAD * s, y + block_h - 4 * s), 8 * s, fill=(30, 30, 37, 255))
            for i, line in enumerate(lines):
                d.text((x0 + (10 * s if font is self.f_mono and buttons else 0), y + i * lh), line, font=font, fill=color)
            y += block_h
        self.buttons = []
        if buttons:
            y += 4 * s
            bx = x0
            yes, no = labels or (f"Allow   {self.hotkey}" if self.hotkey else "Allow", "Deny   Esc")
            for label, color, action in ((yes, ACCENT, self.on_allow), (no, TRACK, self.on_deny)):
                bw = self.f_button.getlength(label) + 28 * s
                d.rounded_rectangle((bx, y, bx + bw, y + 34 * s), 17 * s, fill=color + (255,))
                d.text((bx + bw / 2, y + 17 * s), label, font=self.f_button, fill=TEXT, anchor="mm")
                self.buttons.append(((bx / SS, y / SS, (bx + bw) / SS, (y + 34 * s) / SS), action))
                bx += bw + 10 * s
        self.icon_at = ((x0 + 9 * s) / SS, (m + PAD * s + 12 * s) / SS)
        self.panel = (m / SS, m / SS, (W - m) / SS)
        return img.resize((W // SS, H // SS), Image.LANCZOS)

    # ---------- animation ----------
    def _frame(self):
        t = time.monotonic()
        img = self.base.copy()
        self._icon(img, t)
        if self.kind == "thinking":
            self._sweep(img, t)
        fade = min(1.0, (t - self.shown_at) / 0.16)
        rise = int((1 - fade) ** 2 * 8 * self.logical) * (-1 if self.top else 1)  # slides into place as it fades in
        self._present(img, self.x, self.y + rise, int(255 * (1 - (1 - fade) ** 3)))

    def _icon(self, img, t):
        """A 20 px status mark beside the title, drawn small at 4x for smooth edges."""
        size, k = int(20 * self.scale), 4
        sprite = Image.new("RGBA", (size * k, size * k))
        d = ImageDraw.Draw(sprite)
        c, color = size * k / 2, ICON.get(self.kind, ACCENT)
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
        if getattr(self, "_strip", None) is None:  # built once: a short line that fades in and out
            self._strip = Image.new("RGBA", (glow, max(2, int(2 * self.scale))))
            for i in range(glow):
                self._strip.paste(ACCENT + (int(230 * math.sin(math.pi * i / glow) ** 2),), (i, 0, i + 1, self._strip.height))
        img.alpha_composite(self._strip, (int(x), int(top)))

    def _tick(self):
        self._tick_job = None
        if not self.visible:
            return
        if self.kind in ("thinking", "speaking", "approval") or time.monotonic() - self.shown_at < 0.2:
            self._frame()
        self._tick_job = self.win.after(33, self._tick)

    # ---------- input and lifetime ----------
    def _button_at(self, event):
        pad = 6 * self.scale  # a little forgiving around each button's edge
        return next((action for (x0, y0, x1, y1), action in self.buttons
                     if x0 - pad <= event.x <= x1 + pad and y0 - pad <= event.y <= y1 + pad), None)

    def _click(self, event):
        action = self._button_at(event)
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
        self.visible = False
        self._hide()
