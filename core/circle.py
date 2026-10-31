"""Circle something while you ask: hold the talk key, draw a loop round what you mean with the mouse, and say "what does
this error mean?" Nova follows the mouse while the key is down, finds the loop, and draws it on the screenshot the AI
gets, so it sees exactly what you marked. A live red trail on screen shows what Nova sees while you draw.

Detection is deliberately strict (a loop that closes, big enough, and long enough to be a loop and not a drift of the
hand), because an ordinary mouse movement while holding Ctrl must not turn into a marked screenshot."""
import collections
import math
import threading
import time

from PIL import Image, ImageDraw

from core import system
from core.bar import Layered

SAMPLE_S = 1 / 60
MAX_POINTS = 60 * 60 * 2  # two minutes of path: a key-up that never came must not let it grow for hours
MIN_DIAG = 48  # px: smaller than this is a hand wobble, not a circle
CLOSE = 0.35  # the ends of the loop meet within this fraction of its size
MIN_TURNS = 2.2  # path length as a multiple of the loop's size: a circle is about 3.1, a straight line 1
MAX_POINTS = 400
MARGIN = 0.12  # the circled area is reported this much bigger than the loop
TRAIL = (255, 84, 84)


def thin(points, step=4):
    """The mouse positions with every point closer than `step` px to the last kept one dropped, newest kept."""
    out = []
    for p in points:
        if not out or math.dist(out[-1], p) >= step:
            out.append(p)
    if points and out[-1] != points[-1]:
        out.append(points[-1])
    return out[-MAX_POINTS:]


def find_loop(points):
    """The newest loop in the mouse path as {"points": [...], "box": (left, top, right, bottom)} in the same pixels,
    or None. The box is the loop's own bounds, made a little bigger."""
    pts = thin(points)
    n = len(pts)
    if n < 10:
        return None
    run = [0.0]
    for a, b in zip(pts, pts[1:]):
        run.append(run[-1] + math.dist(a, b))
    best = None
    for j in range(n - 1, 8, -1):  # every loop; the most closed one wins (a loop with a tail of wandering is less closed)
        left = right = pts[j][0]
        top = bottom = pts[j][1]
        for i in range(j - 1, -1, -1):
            x, y = pts[i]
            left, right, top, bottom = min(left, x), max(right, x), min(top, y), max(bottom, y)
            diag = math.hypot(right - left, bottom - top)
            gap = math.dist(pts[i], pts[j]) / diag if diag else 1
            if diag >= MIN_DIAG and run[j] - run[i] >= MIN_TURNS * diag and gap <= CLOSE:
                score = (round(gap, 2), -j)  # a tie goes to the newest
                if best is None or score < best[0]:
                    best = (score, i, j, (left, top, right, bottom))
    if not best:
        return None
    _, i, j, (left, top, right, bottom) = best
    pad = MARGIN * max(right - left, bottom - top)
    return {"points": pts[i:j + 1], "box": (round(left - pad), round(top - pad), round(right + pad), round(bottom + pad))}


def to_image(point, shot):
    """A screen position in a screenshot's pixels. `shot` is (left, top, k, width, height): where the screenshot's top-left
    sits on screen, its pixels per screen pixel, and its size."""
    left, top, k, width, height = shot
    return (point[0] - left) * k, (point[1] - top) * k


def mark(path, shot, loop):
    """Draw the loop in red on the saved screenshot (the AI sees it there), and return the circled area in the
    screenshot's pixels (left, top, right, bottom), or None when it is outside the picture."""
    left, top, k, width, height = shot
    pts = [to_image(p, shot) for p in loop["points"]]
    x0, y0 = to_image(loop["box"][:2], shot)
    x1, y1 = to_image(loop["box"][2:], shot)
    box = (max(0, round(x0)), max(0, round(y0)), min(width, round(x1)), min(height, round(y1)))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    image = Image.open(path).convert("RGB")
    d = ImageDraw.Draw(image)
    w = max(3, round(width / 300))
    for color, extra in (((255, 255, 255), 2), (TRAIL, 0)):  # a white edge under the red, so it shows on a red page too
        d.line(pts, fill=color, width=w + extra, joint="curve")
    image.save(path)
    return box


class Trail:
    """The mouse positions from `start()` to `stop()`, sampled 60 times a second on a thread of its own."""

    def __init__(self, pos=system.mouse_pos):
        self.pos, self.points, self._run = pos, collections.deque(maxlen=MAX_POINTS), None

    def start(self):
        self.stop()
        self.points, run = collections.deque(maxlen=MAX_POINTS), threading.Event()
        self._run = run
        run.set()

        def sample():
            while run.is_set():
                try:
                    self.points.append(self.pos())
                except OSError:  # a locked desktop: no position for now
                    pass
                time.sleep(SAMPLE_S)
        threading.Thread(target=sample, daemon=True).start()

    def stop(self):
        """Stop sampling; returns the positions."""
        if self._run:
            self._run.clear()
            self._run = None
        return list(self.points)

    @property
    def running(self):
        return self._run is not None


class Ink(Layered):
    """The red trail on screen while the mouse draws it. Click-through, and never in Nova's own screenshots."""

    def __init__(self, root):
        self.root = root
        self._init_surface(root, level=25)
        self.scale = self.px
        self._click_through()
        self._present(Image.new("RGBA", (1, 1)), 0, 0)
        self._hide()

    def show(self, points):
        pts = thin(points)[-120:]
        if len(pts) < 2:
            return
        s = self.px
        pad = 8
        left, top = min(x for x, _ in pts) - pad, min(y for _, y in pts) - pad
        right, bottom = max(x for x, _ in pts) + pad, max(y for _, y in pts) + pad
        img = Image.new("RGBA", (int((right - left) * s), int((bottom - top) * s)))
        d = ImageDraw.Draw(img)
        line = [((x - left) * s, (y - top) * s) for x, y in pts]
        d.line(line, fill=TRAIL + (230,), width=max(3, round(4 * s)), joint="curve")
        self._show()
        self._present(img, int(left), int(top))

    def hide(self):
        self._hide()
