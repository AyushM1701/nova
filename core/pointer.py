"""The pointer: a small violet arrow that flies along an arc to the thing on screen the AI is talking about
("where's the export button?") and shows its name. Idea from Clicky: the AI gets a screenshot labelled with its
pixel size and adds a "POINT: x,y label" line in those pixels; Nova maps it back to the screen. Clicks pass
through it."""
import math
import re

from PIL import Image, ImageDraw

from core import system
from core.bar import Layered, _font, dpi_scale

SS = 3  # drawn 3x, then downscaled: smooth edges
ARROW, EDGE, BG, TEXT = (123, 109, 255), (255, 255, 255), (13, 15, 26, 236), (240, 242, 250)
HOLD_S = 5  # how long it stays on the target
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


class Pointer(Layered):
    def __init__(self, root):
        self.root = root
        self._init_surface(root, level=25)
        self.scale = dpi_scale(root) * self.px  # image pixels per design pixel
        self.font = _font(int(13 * self.scale * SS))
        self.pos, self._job = (0, 0), None
        if self.ns is not None:
            self.ns.setIgnoresMouseEvents_(True)
        elif self.hwnd:  # WS_EX_TRANSPARENT: clicks go to the app underneath, even on the arrow itself
            user32 = system.user32
            user32.SetWindowLongW(self.hwnd, -20, user32.GetWindowLongW(self.hwnd, -20) | 0x20)
        # Windows rejects every later paint if a layered window is hidden before its first one
        self._present(Image.new("RGBA", (1, 1)), 0, 0)
        self._hide()

    def draw(self, label=""):
        """The arrow with its tip at the top-left corner, and the label in a pill beside it."""
        s = self.scale * SS
        width = 22 * s + (self.font.getlength(label) + 22 * s if label else 0)
        img = Image.new("RGBA", (int(width) + SS, int(34 * s)))
        d = ImageDraw.Draw(img)
        d.polygon([(2 * s, 2 * s), (20 * s, 10 * s), (10 * s, 20 * s)], fill=ARROW, outline=EDGE, width=int(1.5 * s))
        if label:
            d.rounded_rectangle((22 * s, 12 * s, width, 34 * s), radius=11 * s, fill=BG)
            d.text((33 * s, 23 * s), label, font=self.font, fill=TEXT, anchor="lm")
        return img.resize((max(1, img.width // SS), max(1, img.height // SS)), Image.LANCZOS)

    def fly(self, x, y, label=""):
        """Fly from the mouse pointer to (x, y) on screen along an arc, show the label there, then go away."""
        if self._job:
            self.win.after_cancel(self._job)
        start = self.root.winfo_pointerxy()
        tip = round(2 * self.scale / self.px)  # the arrow's tip sits a little inside its image
        distance = math.dist(start, (x, y))
        steps = max(12, min(45, int(distance / 40)))  # ~0.2-0.75 s: short hops are quick
        lift = min(distance * 0.2, 80 * self.scale / self.px)
        control = ((start[0] + x) / 2, (start[1] + y) / 2 - lift)  # above the midpoint: an arc, not a line
        arrow = self.draw()
        self._show()

        def frame(i):
            t = i / steps
            t = 1 - (1 - t) ** 3  # ease out: it slows as it lands
            px = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control[0] + t * t * x
            py = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control[1] + t * t * y
            if i < steps:
                self._present(arrow, round(px) - tip, round(py) - tip)
                self._job = self.win.after(16, frame, i + 1)
            else:
                self._present(self.draw(label), x - tip, y - tip)
                self._job = self.win.after(HOLD_S * 1000, self.hide)
        frame(0)

    def hide(self):
        self._job = None
        self._hide()
