"""The companion: a small glowing blue marker that stays beside your mouse pointer, and is Nova's hand on the screen.
It shows what Nova is doing (listening, thinking, speaking, waiting for your OK, agents at work), flies to the thing on
screen the AI is talking about ("where's the export button?") and shows its name, is the pen when the AI draws on the
screen, then flies back to the mouse. Idea from Clicky: the AI gets a screenshot labelled with its pixel size and adds a
"POINT: x,y label" line in those pixels; Nova maps it back to the screen. Clicks pass through it, it is never in Nova's
own screenshots, and it dims when the mouse is still.

One animation loop (`tick`) owns the window. follow, fly, pen and hide only set a mode and a target."""
import math
import re
import time

from PIL import Image, ImageDraw, ImageFilter

from core import system
from core.bar import Layered, _font, dpi_scale

SS = 3  # drawn 3x, then downscaled: smooth edges
BLUE, AMBER, GREY = (51, 128, 255), (255, 186, 60), (150, 155, 175)  # the marker: Nova's colour, approval, paused
EDGE, BG, TEXT = (255, 255, 255), (13, 15, 26, 236), (240, 242, 250)
OFFSET = (14, 16)  # design px: where the marker's tip sits from the mouse pointer's tip, so it never covers it
MARGIN = 14  # design px of glow room around the marker
FADE_AFTER_S, FADE_ALPHA = 6.0, 120  # a still mouse and nothing happening: it dims to this
ANIM = {"listening": (12, 1.0), "thinking": (12, 1.2), "speaking": (10, 0.8)}  # frames, seconds per loop
EASE, EASE_PEN, EASE_HOME = 0.4, 0.6, 0.22  # how much of the gap to its goal it closes each frame
HOLD_S = 5  # how long it stays on the target
DONE_RE = re.compile(r"^\W*DONE\W*$", re.I)  # a walkthrough's last step
POINT_RE = re.compile(r"\s*\**POINT:\**\s*(\d+)\s*,\s*(\d+)\s*(.*)", re.I)


def take(shown, shot):
    """(the reply without its POINT: lines, (x, y, label) on screen or None). `shot` is (left, top, k, width,
    height): where the screenshot's top-left sits on screen, its pixels per screen pixel, and its size."""
    lines = shown.splitlines()
    points = [line for line in lines if re.match(r"\s*\**POINT:", line, re.I)]
    shown = "\n".join(line for line in lines if line not in points).strip()
    m = points and POINT_RE.match(points[-1])  # "POINT: none" doesn't match: nothing to point at
    if not (m and shot):
        return shown, None
    left, top, k, width, height = shot
    x, y = min(int(m[1]), width), min(int(m[2]), height)  # an AI guess past the edge stays on the screenshot
    return shown, (round(left + x / k), round(top + y / k), m[3].strip(" :-*`\"")[:40])


def last_step(reply):
    """(the reply without its DONE line, whether it had one): DONE ends a walkthrough."""
    lines = reply.splitlines()
    kept = [line for line in lines if not DONE_RE.match(line)]
    return "\n".join(kept).strip(), len(kept) < len(lines)


class Pointer(Layered):
    """The companion window (see the module docstring)."""

    def __init__(self, root, color=BLUE, enabled=True):
        self.root = root
        self._init_surface(root, level=25)
        self.setup(dpi_scale(root), color, enabled)
        self._click_through()
        self._present(Image.new("RGBA", (1, 1)), 0, 0)  # Windows rejects every later paint if hidden before its first
        self._hide()

    def setup(self, logical, color=BLUE, enabled=True, mouse=None, clock=time.monotonic, cursor_visible=None):
        """Everything but the window: also what the tests build a companion from, with a fake mouse and clock."""
        self.logical = logical  # screen pixels per design pixel
        self.scale = logical * self.px  # image pixels per design pixel
        self.font = _font(int(13 * self.scale * SS))
        self.color, self.enabled, self.suppressed = tuple(color), enabled, False
        self.mouse, self.clock = mouse or system.mouse_pos, clock
        self.cursor_visible = cursor_visible or system.cursor_visible  # False: the system hid the pointer (a full-screen video)
        self.state, self.badge, self.mode = "idle", 0, "follow"  # mode: follow, fly, hold, pen, home, gone
        self.pos, self.flight, self.label, self.hold_s, self.hold_until = None, [], "", HOLD_S, None
        self.pen_goal, self.pen_at = None, 0.0
        self.last_mouse, self.moved_at, self.cache = None, clock(), {}
        self.shown_key, self.shown_at, self.visible, self._after = None, None, False, None

    # ---------- what the rest of Nova tells it ----------
    def set_state(self, state):
        """idle, paused, listening, thinking, speaking or approval: the bar's states."""
        if state in ("idle", "paused", "listening", "thinking", "speaking", "approval"):
            self.state = state

    def set_badge(self, count):
        self.badge = count  # agents at work, shown as a number on the marker

    def set_enabled(self, on):
        self.enabled = bool(on)
        if not on and self.mode == "follow":
            self.mode = "gone"
        elif on and self.mode == "gone":
            self.mode = "follow"

    def set_suppressed(self, on):
        self.suppressed = bool(on)  # a game is in front: no companion

    def set_color(self, color):
        self.color, self.cache = tuple(color), {}

    def start(self):
        """Begin the animation loop."""
        if self._after:
            self.win.after_cancel(self._after)
        self._after = self.win.after(16, self.tick)

    def fly(self, x, y, label="", hold_s=HOLD_S):
        """Fly from where it is to (x, y) on screen along an arc, show the label there, then go home after `hold_s`
        seconds (None: stay until hide(), for a walkthrough step)."""
        start = self.pos or self.mouse()
        distance = math.dist(start, (x, y))
        steps = max(12, min(45, int(distance / 40)))  # ~0.2-0.75 s: short hops are quick
        lift = min(distance * 0.2, 80 * self.logical)
        control = ((start[0] + x) / 2, (start[1] + y) / 2 - lift)  # above the midpoint: an arc, not a line
        self.flight = []
        for i in range(1, steps + 1):
            t = 1 - (1 - i / steps) ** 3  # ease out: it slows as it lands
            self.flight.append(((1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control[0] + t * t * x,
                                (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control[1] + t * t * y))
        self.mode, self.label, self.hold_s = "fly", label, hold_s
        self.pos = self.pos or tuple(start)

    def pen(self, x, y):
        """The AI is drawing and this is where the pen is now (told every frame): it follows, and goes home when told
        no more."""
        self.mode, self.pen_goal, self.pen_at, self.label = "pen", (x, y), self.clock(), ""
        self.pos = self.pos or (x, y)

    def hide(self):
        """Done pointing (a walkthrough step ended): back to the mouse, or away if there is no companion."""
        self.flight = []
        self.mode = "home" if self.enabled and self.pos else "gone"

    # ---------- the loop ----------
    def goal(self):
        mx, my = self.mouse()
        if (mx, my) != self.last_mouse:
            self.last_mouse, self.moved_at = (mx, my), self.clock()
        return mx + OFFSET[0] * self.logical, my + OFFSET[1] * self.logical

    def tick(self):
        """One frame: move toward the goal of the current mode, and draw (move or repaint) at most once."""
        self._after = None
        now = self.clock()
        try:
            gx, gy = self.goal()
        except OSError:  # no pointer position (a locked desktop)
            return self._next(0.25)
        resting = not (self.enabled and not self.suppressed and self.cursor_visible())
        if self.mode == "gone" or (self.mode in ("follow", "home") and resting):
            if self.visible:
                self._hide()
                self.visible, self.shown_key = False, None
            if self.enabled:
                self.mode = "follow"
            return self._next(0.3)
        if self.pos is None:
            self.pos = (gx, gy)
        px, py = self.pos
        busy = True
        if self.mode == "follow":
            px, py = px + (gx - px) * EASE, py + (gy - py) * EASE
            busy = math.dist((px, py), (gx, gy)) > 0.5 or now - self.moved_at < 0.5
        elif self.mode == "fly":
            if self.flight:
                px, py = self.flight.pop(0)
            if not self.flight:
                self.mode = "hold"
                self.hold_until = None if self.hold_s is None else now + self.hold_s
        elif self.mode == "hold":
            if self.hold_until is not None and now >= self.hold_until:
                self.mode, self.label = ("home" if self.enabled else "gone"), ""
        elif self.mode == "pen":
            px, py = px + (self.pen_goal[0] - px) * EASE_PEN, py + (self.pen_goal[1] - py) * EASE_PEN
            if now - self.pen_at > 0.5:  # nobody has moved the pen for a moment: the drawing is done
                self.mode = "home" if self.enabled else "gone"
        elif self.mode == "home":
            px, py = px + (gx - px) * EASE_HOME, py + (gy - py) * EASE_HOME
            if math.dist((px, py), (gx, gy)) < 3:
                self.mode = "follow"
        self.pos = (px, py)
        self._draw(now)
        animated = self.state in ANIM or self.mode != "follow"
        return self._next(0.016 if busy or animated else 0.12)

    def _next(self, seconds):
        self._after = self.win.after(max(1, int(seconds * 1000)), self.tick)

    def _alpha(self, now):
        quiet = self.mode == "follow" and self.state in ("idle", "paused") and not self.badge
        return FADE_ALPHA if quiet and now - self.moved_at > FADE_AFTER_S else 255

    def _draw(self, now):
        n, period = ANIM.get(self.state, (1, 1.0))
        frame = int(now / period * n) % n if n > 1 else 0
        label = self.label if self.mode in ("fly", "hold") else ""
        key = (self.state, frame, label, self.badge, self._alpha(now), self.color)
        anchor = round(MARGIN * self.logical)  # the marker's tip, in screen pixels from the window's corner
        x, y = round(self.pos[0]) - anchor, round(self.pos[1]) - anchor
        if key != self.shown_key:
            if key not in self.cache:
                if len(self.cache) > 60:
                    self.cache.clear()
                self.cache[key] = self.glyph(self.state, frame, label, self.badge)
            if not self.visible:
                self._show()
                self.visible = True
            self._present(self.cache[key], x, y, key[4])
            self.shown_key, self.shown_at = key, (x, y)
        elif (x, y) != self.shown_at:
            self._move(x, y)
            self.shown_at = (x, y)

    # ---------- drawing the marker ----------
    def glyph(self, state, frame, label="", badge=0):
        """The marker as an image, its tip MARGIN design pixels in from the corner. States add a glow, rings, an orbit
        or a badge."""
        s = self.scale * SS
        color = AMBER if state == "approval" else GREY if state == "paused" else self.color
        pill = (self.font.getlength(label) + 22 * s) if label else 0
        width, height = int((MARGIN * 2 + 24) * s + (pill + 6 * s if label else 0)), int((MARGIN * 2 + 24) * s)
        ox = oy = MARGIN * s
        tri = [(ox, oy), (ox + 18 * s, oy + 8 * s), (ox + 8 * s, oy + 18 * s)]
        mid = (ox + 9 * s, oy + 9 * s)
        n, _ = ANIM.get(state, (1, 1.0))
        wave = 0.5 - 0.5 * math.cos(6.283 * frame / n) if n > 1 else 0.0
        glow = Image.new("RGBA", (width, height))
        ImageDraw.Draw(glow).polygon(tri, fill=color + ((int(120 + 100 * wave) if state == "speaking" else 105),))
        img = glow.filter(ImageFilter.GaussianBlur(4.5 * s))
        d = ImageDraw.Draw(img)
        if state == "listening":  # rings spreading out
            for k in range(2):
                t = (frame / n + k / 2) % 1
                r = (7 + 17 * t) * s
                d.ellipse((mid[0] - r, mid[1] - r, mid[0] + r, mid[1] + r), outline=color + (int(190 * (1 - t)),),
                          width=int(1.8 * s))
        d.polygon(tri, fill=color + (255,), outline=EDGE + (215,), width=max(1, int(1.3 * s)))
        d.line(tri + [tri[0]], fill=color + (255,), width=int(3 * s), joint="curve")  # rounded corners
        if state == "thinking":  # three dots circling
            for k in range(3):
                a = 6.283 * (frame / n + k / 3)
                x, y = mid[0] + 17 * s * math.cos(a), mid[1] + 17 * s * math.sin(a)
                d.ellipse((x - 2.3 * s, y - 2.3 * s, x + 2.3 * s, y + 2.3 * s), fill=EDGE + (230,))
        if badge:  # agents at work
            bx, by, r = ox + 24 * s, oy - 2 * s, 7 * s
            d.ellipse((bx - r, by - r, bx + r, by + r), fill=AMBER + (255,), outline=EDGE + (230,), width=max(1, int(s)))
            d.text((bx, by), str(min(badge, 9)), font=_font(int(10 * self.scale * SS)), fill=(30, 25, 10), anchor="mm")
        if label:
            d.rounded_rectangle((ox + 22 * s, oy + 12 * s, width - MARGIN * s + 2 * s, oy + 34 * s), radius=11 * s, fill=BG)
            d.text((ox + 33 * s, oy + 23 * s), label, font=self.font, fill=TEXT, anchor="lm")
        return img.resize((max(1, img.width // SS), max(1, img.height // SS)), Image.LANCZOS)


def rgb(text, default=BLUE):
    """"#3380FF" as (51, 128, 255); `default` for anything that isn't a hex colour."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(text).strip())
    return tuple(int(m[1][i:i + 2], 16) for i in (0, 2, 4)) if m else default
