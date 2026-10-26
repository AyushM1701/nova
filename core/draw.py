"""Drawing on the screen: the pointer's bigger sibling. Besides one "POINT: x,y label", the AI can mark up its
screenshot with a few "DRAW:" lines (a box round a setting, an arrow to a button, numbered steps) and Nova draws
them on the real screen, one shape at a time, where clicks pass through. Idea from Clicky: a tiny shape language
instead of one tool call per shape.

    DRAW: circle x y r ["label"]          DRAW: box x y w h ["label"]
    DRAW: arrow x1 y1 x2 y2 ["label"]     DRAW: line x1 y1 x2 y2 ["label"]
    DRAW: dot x y ["label"]               DRAW: num x y 1          DRAW: text x y "words"

Positions are pixels in the screenshot (0,0 its top-left). Any line may add a colour (blue red green orange purple
pink yellow gray), `fill` (a soft wash), `dashed` or `curve` (arrows and lines). Labels are 1-3 words."""
import math
import re

from PIL import Image, ImageDraw

from core.bar import Layered, _font, dpi_scale

SS = 3  # drawn 3x, then downscaled: smooth edges
MAX_SHAPES = 12
HOLD_S = 12  # how long a drawing stays
FRAMES, FRAME_MS, LEAD_MS = 6, 35, 170  # a shape is drawn in this many frames, this far apart (half as many when there are many shapes)
VIOLET, BG, TEXT = (123, 109, 255), (13, 15, 26, 236), (240, 242, 250)
COLORS = {"blue": (74, 144, 255), "red": (255, 84, 84), "green": (52, 199, 120), "orange": (255, 159, 64),
          "purple": (176, 104, 255), "pink": (255, 112, 190), "yellow": (255, 214, 64), "gray": (170, 175, 190)}
NEEDS = {"circle": 3, "box": 4, "arrow": 4, "line": 4, "dot": 2, "num": 3, "text": 2}
POSITIONS = {"circle": (0, 1), "box": (0, 1), "arrow": (0, 1, 2, 3), "line": (0, 1, 2, 3), "dot": (0, 1),
             "num": (0, 1), "text": (0, 1)}  # the other numbers are sizes (a radius, a width), not places
DRAW_RE = re.compile(r"\s*\**DRAW:\**\s*(.*)")  # capitals only: "Draw: hold Shift" in an answer is just text
TOKEN_RE = re.compile(r'"[^"]*"|“[^”]*”|\S+')


def parse(rest):
    """One DRAW line (after "DRAW:") as a shape in screenshot pixels, or None if it makes no sense."""
    tokens = []
    for t in TOKEN_RE.findall(rest.replace("**", "")):
        tokens += [t] if t[0] in "\"“" else t.replace(",", " ").split()  # "10,10" and "box 1, 2, 3, 4", as POINT writes x,y
    kind = tokens[0].lower().strip(":") if tokens else ""
    if kind not in NEEDS:
        return None
    nums, shape = [], {"kind": kind, "label": "", "color": "", "fill": False, "dashed": False, "curve": False}
    for t in tokens[1:]:
        if t[0] in "\"“":
            shape["label"] = t.strip("\"“”").strip()[:40]
        elif re.fullmatch(r"-?\d+(?:\.\d+)?", t) and len(nums) < NEEDS[kind]:
            nums.append(float(t))
        elif t.lower().strip(",.") in COLORS:
            shape["color"] = t.lower().strip(",.")
        elif t.lower() in ("fill", "dashed", "curve"):
            shape[t.lower()] = True
    if len(nums) < NEEDS[kind] or (kind == "text" and not shape["label"]):
        return None
    if kind == "num":
        shape["label"], nums = str(int(nums[2]))[:2], nums[:2]
    if any(n < 0 for n in nums) or (kind in ("circle", "box") and min(nums[2:]) < 1):
        return None
    shape["p"] = nums
    return shape


def take(shown, shot):
    """(the reply without its DRAW: lines, the shapes on screen). `shot` is (left, top, k, width, height) like the
    pointer's: where the screenshot's top-left sits on screen, its pixels per screen pixel, and its size. Without a
    screenshot the lines are still removed (they must not be read out), but nothing is drawn."""
    kept, shapes = [], []
    for line in shown.splitlines():
        m = DRAW_RE.match(line)
        shape = m and parse(m[1])
        if shape:
            shapes.append(shape)
        elif not m:
            kept.append(line)
    shown = "\n".join(kept).strip()
    if not shot:
        return shown, []
    left, top, k, width, height = shot
    for shape in shapes:
        p = shape["p"]
        for i in range(len(p)):
            if i in POSITIONS[shape["kind"]]:  # an AI guess past the edge stays on the screenshot
                p[i] = round((left if i % 2 == 0 else top) + min(p[i], width if i % 2 == 0 else height) / k)
            else:
                p[i] = round(p[i] / k)
    return shown, shapes[:MAX_SHAPES]


# ---------- drawing ----------
def _dashes(pts, on, off):
    """A polyline cut into dashes `on` long with `off` gaps."""
    out, cur, drawing, left = [], [pts[0]], True, on
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dist, pos = math.hypot(x1 - x0, y1 - y0), 0
        while dist - pos > left:
            pos += left
            pt = (x0 + (x1 - x0) * pos / dist, y0 + (y1 - y0) * pos / dist)
            if drawing:
                cur.append(pt)
                out.append(cur)
                cur = []
            else:
                cur = [pt]
            drawing = not drawing
            left = on if drawing else off
        left -= dist - pos
        if drawing:
            cur.append((x1, y1))
    if drawing and len(cur) > 1:
        out.append(cur)
    return out


def _rounded_box(x, y, w, h, r):
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        pts += [(cx + r * math.cos(math.radians(a0 + 90 * i / 6)), cy + r * math.sin(math.radians(a0 + 90 * i / 6)))
                for i in range(7)]
    return pts + pts[:1]


def _curve(a, b, bow):
    """A quadratic curve from a to b, bowed to one side."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2 - dy * bow, (y0 + y1) / 2 + dx * bow
    return [((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1)
            for t in (i / 24 for i in range(25))]


def _pill(font, text, x, y, place, u):
    """The rectangle of a label pill anchored at (x, y)."""
    w, h = font.getlength(text) + 18 * u, 24 * u
    return {"above": (x - w / 2, y - h, x + w / 2, y), "right": (x, y - h / 2, x + w, y + h / 2),
            "center": (x - w / 2, y - h / 2, x + w / 2, y + h / 2), "above-left": (x, y - h, x + w, y)}.get(
        place, (x, y, x + w, y + h))


def _geometry(sh, g, u, font):
    """What to draw for one shape, in supersampled image pixels: strokes (polylines), fills, discs and label pills."""
    p = [v * g for v in sh["p"]]
    strokes, fills, discs, pill = [], [], [], None
    kind, label = sh["kind"], sh["label"]
    if kind == "circle":
        (x, y, r), n = p, 72
        ring = [(x + r * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
        strokes.append(ring)
        if sh["fill"]:
            fills.append(ring)
        pill = label and (label, x, y - r - 4 * u, "above")
    elif kind == "box":
        x, y, w, h = p
        ring = _rounded_box(x, y, w, h, min(8 * u, w / 3, h / 3))
        strokes.append(ring)
        if sh["fill"]:
            fills.append(ring)
        pill = label and (label, x, y - 4 * u, "above-left")
    elif kind in ("arrow", "line"):
        a, b = (p[0], p[1]), (p[2], p[3])
        path = _curve(a, b, 0.2) if sh["curve"] else [a, b]
        strokes.append(path)
        if kind == "arrow" and a != b:
            (x0, y0), (x1, y1) = path[-2] if len(path) > 2 else a, path[-1]
            ang, head = math.atan2(y1 - y0, x1 - x0), 15 * u
            fills.append([(x1, y1), (x1 - head * math.cos(ang - 0.45), y1 - head * math.sin(ang - 0.45)),
                          (x1 - head * math.cos(ang + 0.45), y1 - head * math.sin(ang + 0.45))])
        mid = path[len(path) // 2]
        pill = label and (label, mid[0], mid[1] - 10 * u, "above")
    elif kind == "dot":
        discs.append((p[0], p[1], 6 * u))
        pill = label and (label, p[0] + 12 * u, p[1], "right")
    elif kind == "num":
        discs.append((p[0], p[1], 13 * u))
    else:  # text
        pill = (label, p[0], p[1], "below-right")
    rect = pill and _pill(font, pill[0], pill[1], pill[2], pill[3], u)
    return strokes, fills, discs, rect and (pill[0], rect)


def bounds(sh, g, u, font):
    """(left, top, right, bottom) of a shape's drawing in the pixels `g` and `u` give (screen pixels for g = the pixel
    density): how much room it takes, before anything is drawn."""
    strokes, fills, discs, pill = _geometry(sh, g, u, font)
    xs = [x for s_ in strokes + fills for x, _ in s_] + [d[0] + e for d in discs for e in (-d[2], d[2])]
    ys = [y for s_ in strokes + fills for _, y in s_] + [d[1] + e for d in discs for e in (-d[2], d[2])]
    if pill:
        xs += [pill[1][0], pill[1][2]]
        ys += [pill[1][1], pill[1][3]]
    return min(xs), min(ys), max(xs), max(ys)


def _cut(pts, f):
    """The first fraction `f` of a polyline, by length."""
    goal, out = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])) * f, [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg >= goal:
            t = goal / seg if seg else 0
            return out + [(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)]
        goal -= seg
        out.append((x1, y1))
    return out


def render(sh, g, u, font, t=1.0, ss=SS):
    """One shape as (a small RGBA image, its left, its top, the pen tip) in final image pixels, drawn `t` of the way
    (0 to 1) by a pen: its strokes are traced along their paths, then the wash, the dots and the label appear. The
    image has the same size and place at every `t`. The tip is where the pen is (supersampled image pixels, the same
    space as the shape's geometry), or None once it is done. `g` turns screen pixels into supersampled image pixels,
    `u` design pixels (line widths, label sizes) into them, and `font` is sized for the same `ss` (how many times bigger
    than the final image it is drawn, for smooth edges: big shapes use less, to stay quick)."""
    color = COLORS.get(sh["color"], VIOLET)
    lw = 3 * u
    strokes, fills, discs, pill = _geometry(sh, g, u, font)
    xs = [x for s in strokes + fills for x, _ in s] + [d[0] + s for d in discs for s in (-d[2], d[2])]
    ys = [y for s in strokes + fills for _, y in s] + [d[1] + s for d in discs for s in (-d[2], d[2])]
    if pill:
        xs += [pill[1][0], pill[1][2]]
        ys += [pill[1][1], pill[1][3]]
    pad = 2 * lw
    left, top = math.floor((min(xs) - pad) / ss) * ss, math.floor((min(ys) - pad) / ss) * ss
    right, bottom = math.ceil((max(xs) + pad) / ss) * ss, math.ceil((max(ys) + pad) / ss) * ss
    img = Image.new("RGBA", (right - left, bottom - top))
    d = ImageDraw.Draw(img)
    at = lambda pts: [(x - left, y - top) for x, y in pts]  # noqa: E731
    done, tip = t >= 1.0, None
    inked = min(1.0, t / 0.75)  # the strokes take the first three quarters of the time, one after another
    if done or inked >= 1.0:
        for poly in fills:
            d.polygon(at(poly), fill=color + ((255,) if len(poly) == 3 else (60,)))
    total = sum(_length(pts) for pts in strokes) or 1
    spent = 0.0
    for pts in strokes:
        length = _length(pts)
        f = 1.0 if done else min(1.0, max(0.0, (inked * total - spent) / length)) if length else 1.0
        spent += length
        if f <= 0:
            continue
        part = pts if f >= 1 else _cut(pts, f)
        for seg in (_dashes(at(part), 10 * u, 7 * u) if sh["dashed"] else [at(part)]):
            if len(seg) >= 2:
                d.line(seg, fill=color, width=round(lw), joint="curve")
            for x, y in (seg[0], seg[-1]):  # round ends
                d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=color)
        if f < 1:
            tip = part[-1]
    if done or t >= 0.2:
        for x, y, r in discs:
            d.ellipse((x - left - r, y - top - r, x - left + r, y - top + r), fill=color, outline=(255, 255, 255), width=round(lw / 2))
            if sh["kind"] == "num":
                d.text((x - left, y - top), sh["label"], font=font, fill=(255, 255, 255), anchor="mm")
    if pill and (done or t >= 0.88):
        x0, y0, x1, y1 = pill[1]
        d.rounded_rectangle((x0 - left, y0 - top, x1 - left, y1 - top), radius=12 * u, fill=BG, outline=color, width=round(u))
        d.text(((x0 + x1) / 2 - left, (y0 + y1) / 2 - top), pill[0], font=font, fill=TEXT, anchor="mm")
    img = img.resize((img.width // ss, img.height // ss), Image.LANCZOS) if ss > 1 else img
    return img, left // ss, top // ss, tip


def _length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


class Canvas(Layered):
    """A click-through window that draws the AI's shapes over the screen with a pen, one after another, then goes away.
    The pen is Nova's companion pointer: it follows each stroke as it is drawn (`pen(x, y)` is told where)."""

    def __init__(self, root, pen=None):
        self.root = root
        self._init_surface(root, level=25)
        self.scale = dpi_scale(root) * self.px  # image pixels per design pixel
        self.font = _font(int(13 * self.scale * SS))
        self._font_cache = {SS: self.font}
        self._jobs = []
        self.pen = pen or (lambda x, y: None)
        self._click_through()
        self._present(Image.new("RGBA", (1, 1)), 0, 0)  # Windows rejects later paints if hidden before the first
        self._hide()

    def _fonts(self, ss):
        if ss not in self._font_cache:
            self._font_cache[ss] = _font(int(13 * self.scale * ss))
        return self._font_cache[ss]

    def prepare(self, shapes):
        """Every frame of every shape, made ahead of time (off the screen thread). The frames in between are drawn
        plainly (they're on screen for a moment); the finished shape is smooth, less so when it is huge (a box round a
        whole window), and a huge one has no in-between frames at all, so preparing stays quick and small.
        {"steps": [(image, x, y, pen tip in screen pixels or None, last frame of its shape, where the pen starts)], ...}"""
        n = FRAMES if len(shapes) <= 6 else FRAMES // 2
        made = []
        for sh in shapes:
            x0, y0, x1, y1 = bounds(sh, self.px, self.scale, self._fonts(1))
            area = (x1 - x0) * (y1 - y0)  # device pixels (what the plain frame costs), not screen points
            ss = SS if area < 400_000 else 2 if area < 2_500_000 else 1
            frames = []
            for k in range(1, (1 if area >= 2_500_000 else n) + 1):
                last = k == (1 if area >= 2_500_000 else n)
                f = ss if last else 1
                img, x, y, tip = render(sh, self.px * f, self.scale * f, self._fonts(f), 1.0 if last else k / n, f)
                frames.append((img, x, y, tip and (tip[0] / (self.px * f), tip[1] / (self.px * f))))
            start = next((tip for _, _, _, tip in frames if tip), None)  # where the pen first touches the screen
            made.append((frames, start))
        px = self.px
        every = [f for frames, _ in made for f in frames]
        left = math.floor(min(x for _, x, _, _ in every) / px) * px  # on a whole screen pixel
        top = math.floor(min(y for _, _, y, _ in every) / px) * px
        right = max(x + img.width for img, x, _, _ in every)
        bottom = max(y + img.height for img, _, y, _ in every)
        steps = [(img, x, y, tip, k == len(frames) - 1, start if k == 0 else None)
                 for frames, start in made for k, (img, x, y, tip) in enumerate(frames)]
        return {"steps": steps, "left": left, "top": top, "size": (right - left, bottom - top)}

    def show(self, built, hold_s=HOLD_S):
        """Draw a prepared set of shapes (or shapes straight from take(), prepared here) and clear them after `hold_s`."""
        self.hide()
        if not built:
            return
        if isinstance(built, list):
            built = self.prepare(built)
        px, left, top = self.px, built["left"], built["top"]
        page = Image.new("RGBA", built["size"])
        steps = built["steps"]
        self._show()

        led = [False]

        def step(i):
            img, x, y, tip, last, start = steps[i]
            if start and not led[0]:  # the pen gets to where the shape starts before any ink appears
                led[0] = True
                self.pen(*start)
                self._jobs = [self.win.after(LEAD_MS, step, i)]
                return
            led[0] = False
            shown = page if last else page.copy()  # a shape's last frame stays; the frames before it are for a moment
            shown.alpha_composite(img, (x - left, y - top))
            self._present(shown, left // px, top // px)
            if tip:
                self.pen(*tip)  # the pointer is the pen
            if i + 1 < len(steps):
                self._jobs = [self.win.after(FRAME_MS, step, i + 1)]
            else:
                self._jobs = [self.win.after(int(hold_s * 1000), self.hide)] if hold_s else []
        step(0)

    def hide(self):
        for job in self._jobs:
            self.win.after_cancel(job)
        self._jobs = []
        self._hide()
