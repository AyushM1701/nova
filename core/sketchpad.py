"""The sketch pad: a paper note that appears on screen while Nova speaks, for questions with a short factual answer (the
AI's `:::sketch` block, read by core/sketch.py). Hand-drawn look: a handwriting font, wobbly circles, boxes and bars,
an optional photo, and follow-up questions as chips. Click a chip to ask it; click anywhere else (or press Esc) to clear.

It is drawn in by a pen. Shapes (circles, boxes, bars, arrows, chip outlines) really are drawn stroke by stroke along
their paths; text and fills are wiped in behind the pen tip, because a font can't be traced stroke by stroke.
Every step is built ahead of time (`build`), off the screen thread; the window only shows the frames."""
import math
import random
import zlib

from PIL import Image, ImageDraw, ImageFilter

from core import system
from core.bar import Layered, _font, dpi_scale
from core.draw import _cut, _length, _rounded_box

SS = 2  # drawn 2x, then downscaled: smooth edges
WIDTH, PAD, HEADER, SHADOW, PILL = 440, 22, 26, 18, 34  # design pixels: the paper, its margin, title bar, shadow, Clear pill
PAPER, EDGE, BAR_BG = (249, 247, 240), (200, 196, 184), (233, 231, 223)
INK, GREY, BLUE, MARK, PEN = (32, 34, 44), (118, 120, 132), (74, 144, 255), (255, 228, 110), (30, 52, 120)
HAND = ("Inkfree.ttf", "segoepr.ttf", "/System/Library/Fonts/Noteworthy.ttc",
        "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf", "segoeui.ttf", "/System/Library/Fonts/Helvetica.ttc")
FRAME_MS = 45
TOTAL_FRAMES = 28 if system.IS_MAC else 56  # about 3 s on this PC in all (frame time plus the time to show each one)
MAX_FRAMES = 10  # per line
HOLD_S = 25  # how long it stays once Nova has finished speaking
_fonts = {}


def _hand(px):
    if px not in _fonts:
        _fonts[px] = _font(px, HAND)
    return _fonts[px]


class _Ctx:
    """What every line needs to draw itself, at one moment of its drawing. A line is a function that makes its calls to
    the pen operations below in a fixed order; each call gets a slice of the line's time (`slot`), so the same
    function drawn at t = 0.3 or 1.0 shows the line that far along. The wobble is the same at every t because
    `build` rewinds the random hand before each frame."""

    def __init__(self, scale, seed):
        self.scale, self.u = scale, scale * SS
        self.w = round(WIDTH * scale)  # final width of every line's image
        self.rnd, self.cache = random.Random(seed), {}
        self.img = self.d = None
        self.planning, self.weights, self.t, self.i, self.starts, self.lens, self.chips = True, [], 1.0, 0, [], [], []

    def font(self, size):
        return _hand(int(size * self.u))

    def layer(self, height):
        self.img = Image.new("RGBA", (self.w * SS, round(height * self.scale) * SS))
        self.d = ImageDraw.Draw(self.img)

    # timing
    def plan(self):
        self.planning, self.weights, self.i, self.chips = True, [], 0, []

    def finish_plan(self):
        total = sum(self.weights) or 1
        self.lens = [w / total for w in self.weights]
        self.starts = [sum(self.lens[:i]) for i in range(len(self.lens))]
        self.planning = False

    def frame(self, t):
        self.t, self.i = t, 0

    def slot(self, weight):
        """How far along this call is: 0 to 1."""
        i, self.i = self.i, self.i + 1
        if self.planning:
            self.weights.append(weight)
            return 1.0
        if self.t >= 1.0:
            return 1.0
        return min(1.0, max(0.0, (self.t - self.starts[i]) / self.lens[i]))

    # pen operations
    def tip(self, x, y):
        r = 3.4 * self.u
        self.d.ellipse((x - r, y - r, x + r, y + r), fill=PEN)

    def line(self, pts, color, width=2.2, amp=None):
        """A polyline, drawn along its length; `amp`: wobble it like a hand (design px)."""
        if amp is not None:
            pts = _jitter(self, pts, amp, 12 * self.u)  # always drawn in full first, so the random hand moves the same
        f = self.slot(1 + _length(pts) / self.u / 90)
        if f <= 0:
            return
        part = pts if f >= 1 else _cut(pts, f)
        self.d.line(part, fill=color, width=round(width * self.u), joint="curve")
        if f < 1:
            self.tip(*part[-1])

    def text(self, xy, text, font, fill, anchor, bold=False):
        f = self.slot(0.3 + 0.12 * len(text))
        if f <= 0:
            return

        def draw(d):
            for dx in ((0, 0.7 * self.u) if bold else (0,)):  # the same stroke twice, a hair apart: a marker, not a pencil
                d.text((xy[0] + dx, xy[1]), text, font=font, fill=fill, anchor=anchor)
        if f >= 1:
            return draw(self.d)
        x0, y0, x1, y1 = self.d.textbbox(xy, text, font=font, anchor=anchor)
        self._wipe(draw, x0, x1, f, (y0 + y1) / 2)

    def shape(self, draw, x0, x1, weight=0.8):
        """A fill or panel, wiped in from the left across x0..x1."""
        f = self.slot(weight)
        if f >= 1:
            draw(self.d)
        elif f > 0:
            self._wipe(draw, x0, x1, f, None)

    def pop(self, draw, weight=0.3):
        """A small thing that appears at once."""
        if self.slot(weight) > 0:
            draw(self.d)

    def picture(self, im, xy):
        """A photo, wiped in from the top."""
        f = self.slot(1.6)
        if f > 0:
            self.img.paste(im.crop((0, 0, im.width, max(1, int(im.height * min(f, 1))))), (int(xy[0]), int(xy[1])))

    def _wipe(self, draw, x0, x1, f, tip_y):
        tmp = Image.new("RGBA", self.img.size)
        draw(ImageDraw.Draw(tmp))
        cut = int(x0 + (x1 - x0) * f)
        self.img.alpha_composite(tmp.crop((0, 0, max(1, cut), tmp.height)), (0, 0))
        if tip_y is not None:
            self.tip(cut, tip_y)


def _jitter(ctx, pts, amp, step):
    """A polyline redrawn the way a hand would: points every `step`, each off by up to `amp` (design px)."""
    out, carry = [pts[0]], 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dist = math.hypot(x1 - x0, y1 - y0)
        pos = step - carry
        while pos < dist:
            out.append((x0 + (x1 - x0) * pos / dist, y0 + (y1 - y0) * pos / dist))
            pos += step
        carry = dist - (pos - step)
    out.append(pts[-1])
    a = amp * ctx.u
    return [(x + ctx.rnd.uniform(-a, a), y + ctx.rnd.uniform(-a, a)) for x, y in out]


def _circle(ctx, cx, cy, r, color, width=2.2):
    """A hand-drawn circle: it doesn't quite close, and drifts a little in size."""
    ctx.line([(cx + (r + 0.6 * ctx.u * math.sin(a * 2)) * math.cos(a), cy + (r + 0.6 * ctx.u * math.sin(a * 2)) * math.sin(a))
              for a in (6.28 * i / 40 + 0.4 for i in range(46))], color, width)


def _box(ctx, x, y, w, h, color, width=2.2, amp=0.9):
    ctx.line(_rounded_box(x, y, w, h, min(8 * ctx.u, w / 3, h / 3)), color, width, amp)


def _wrap(font, text, width, lines):
    out, line = [], ""
    for word in text.split():
        if line and font.getlength(f"{line} {word}") > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    out.append(line)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][:max(1, len(out[-1]) - 1)].rstrip() + "…"
    return out


def _fit(font, text, width):
    """`text` cut with an ellipsis until it fits `width` pixels."""
    while font.getlength(text) > width and len(text) > 1:
        text = text[:-2].rstrip() + "…"
    return text


# ---------- the lines of a note: each makes its pen calls in a fixed order and returns its height in design px ----------
def _title(ctx, text):
    u, size = ctx.u, 30
    while size > 20 and ctx.font(size).getlength(text) > (WIDTH - 2 * PAD) * u:
        size -= 2
    font, h = ctx.font(size), 44
    ctx.layer(h)
    tw = min(font.getlength(text), (WIDTH - 2 * PAD) * u)
    box = (PAD * u - 4 * u, 25 * u, PAD * u + tw + 6 * u, 38 * u)
    ctx.shape(lambda d: d.rounded_rectangle(box, 6 * u, fill=MARK + (150,)), box[0], box[2])  # a highlighter stroke
    ctx.text((PAD * u, 4 * u), text, font, INK, "la", bold=True)
    return h


def _sub(ctx, text):
    ctx.layer(28)
    ctx.text((PAD * ctx.u, 2 * ctx.u), text, ctx.font(17), GREY, "la")
    return 28


def _row(ctx, number, label, detail):
    u, h = ctx.u, 40
    ctx.layer(h)
    if number:
        _circle(ctx, (PAD + 12) * u, 20 * u, 12 * u, BLUE)
        ctx.text(((PAD + 12) * u, 20 * u), number, ctx.font(16), BLUE, "mm")
        x = PAD + 36
    else:
        dot = ((PAD + 3) * u, 17 * u, (PAD + 9) * u, 23 * u)
        ctx.pop(lambda d: d.ellipse(dot, fill=BLUE))
        x = PAD + 20
    font = ctx.font(22)
    room = (WIDTH - PAD) * u - x * u
    text = _fit(font, label, room * (0.5 if detail else 1))
    ctx.text((x * u, 20 * u), text, font, INK, "lm")
    if detail:
        dx = max(x * u + font.getlength(text) + 14 * u, WIDTH * 0.44 * u)
        ctx.text((dx, 20 * u), _fit(ctx.font(17), detail, (WIDTH - PAD) * u - dx), ctx.font(17), GREY, "lm")
    return h


def _item(ctx, text):
    u = ctx.u
    lines = _wrap(ctx.font(20), text, (WIDTH - 2 * PAD - 22) * u, 2)
    h = len(lines) * 26 + 8
    ctx.layer(h)
    dot = ((PAD + 2) * u, 12 * u, (PAD + 8) * u, 18 * u)
    ctx.pop(lambda d: d.ellipse(dot, fill=BLUE))
    for i, line in enumerate(lines):
        ctx.text(((PAD + 22) * u, (15 + 26 * i) * u), line, ctx.font(20), INK, "lm")
    return h


def _bar(ctx, label, value, biggest):
    u, h = ctx.u, 36
    ctx.layer(h)
    font = ctx.font(20)
    text = _fit(font, label, 130 * u)
    ctx.text((PAD * u, 18 * u), text, font, INK, "lm")
    x0 = PAD * u + max(font.getlength(text) + 12 * u, 90 * u)
    room = (WIDTH - PAD - 46) * u - x0
    length = max(8 * u, room * value / biggest) if biggest else 8 * u
    ctx.shape(lambda d: d.rounded_rectangle((x0, 8 * u, x0 + length, 28 * u), 8 * u, fill=BLUE + (200,)), x0, x0 + length)
    ctx.line(_rounded_box(x0, 8 * u, length, 20 * u, 8 * u), (40, 96, 200), 1.6, 0.5)
    ctx.text((x0 + length + 8 * u, 18 * u), f"{value:g}", ctx.font(17), GREY, "lm")
    return h


def _flow(ctx, nodes):
    u = ctx.u
    font = ctx.font(19)
    widths = [font.getlength(n) + 24 * u for n in nodes]
    gap, inner = 34 * u, (WIDTH - 2 * PAD) * u
    horizontal = sum(widths) + gap * (len(nodes) - 1) <= inner
    h = 54 if horizontal else len(nodes) * 36 + (len(nodes) - 1) * 26 + 10
    ctx.layer(h)
    x, y = PAD * u + (inner - sum(widths) - gap * (len(nodes) - 1)) / 2, 10 * u
    for i, (node, w) in enumerate(zip(nodes, widths)):
        if not horizontal:
            x = (WIDTH * u - w) / 2
        _box(ctx, x, y, w, 34 * u, INK, 2)
        ctx.text((x + w / 2, y + 17 * u), node, font, INK, "mm")
        if i + 1 < len(nodes):  # an arrow to the next
            if horizontal:
                a, b = (x + w + 5 * u, y + 17 * u), (x + w + gap - 5 * u, y + 17 * u)
                head = [(b[0], b[1]), (b[0] - 9 * u, b[1] - 6 * u), (b[0] - 9 * u, b[1] + 6 * u)]
            else:
                a, b = (WIDTH * u / 2, y + 38 * u), (WIDTH * u / 2, y + 58 * u)
                head = [(b[0], b[1]), (b[0] - 6 * u, b[1] - 9 * u), (b[0] + 6 * u, b[1] - 9 * u)]
            ctx.line([a, b], BLUE, 2.4, 0.5)
            ctx.pop(lambda d, head=head: d.polygon(head, fill=BLUE))
        x += w + gap
        y += 0 if horizontal else 62 * u
    return h


def _note(ctx, text):
    u = ctx.u
    font = ctx.font(20)
    lines = _wrap(font, text, (WIDTH - 2 * PAD - 8) * u, 3)
    h = len(lines) * 28 + 12
    ctx.layer(h)
    for i, line in enumerate(lines):
        y = (6 + 28 * i) * u
        box = (PAD * u - 4 * u, y + 5 * u, PAD * u + font.getlength(line) + 8 * u, y + 27 * u)
        ctx.shape(lambda d, box=box: d.rounded_rectangle(box, 5 * u, fill=MARK + (150,)), box[0], box[2])
        ctx.text((PAD * u, y + 16 * u), line, font, INK, "lm")
    return h


def _src(ctx, names):
    u = ctx.u
    font = ctx.font(15)
    chips, x, y = [], (PAD + 62) * u, 4 * u
    for name in names:
        w = font.getlength(name) + 18 * u
        if x + w > (WIDTH - PAD) * u and x > (PAD + 62) * u:
            x, y = PAD * u, y + 30 * u
        chips.append((name, x, y, w))
        x += w + 8 * u
    h = round(y / u) + 34
    ctx.layer(h)
    ctx.text((PAD * u, 17 * u), "Sources", font, GREY, "lm")
    for name, cx, cy, w in chips:
        _box(ctx, cx, cy + 4 * u, w, 24 * u, GREY, 1.4)
        ctx.text((cx + w / 2, cy + 16 * u), name, font, GREY, "mm")
    return h


def _photo(ctx, image, caption):
    """A snapshot taped to the note: pen-drawn frame, the picture wiped in from the top, a handwritten caption."""
    u = ctx.u
    box_w, box_h, pad = min(300, WIDTH - 2 * PAD - 20), 140, 10
    k = min(box_w / image.width, box_h / image.height)
    iw, ih = image.width * k, image.height * k
    fw = max(iw + 2 * pad, 230)  # a narrow photo still gets room for its caption
    lines = _wrap(ctx.font(18), caption, (fw - 20) * u, 2) if caption else []
    cap = 10 + 24 * len(lines)
    fh = ih + pad + cap
    ctx.layer(fh + 18)
    key = ("photo", id(image))
    if key not in ctx.cache:
        ctx.cache[key] = image.resize((max(1, round(iw * u)), max(1, round(ih * u))), Image.LANCZOS)
    x0, y0 = (WIDTH - fw) / 2 * u, 10 * u
    x1, y1 = x0 + fw * u, y0 + fh * u
    ctx.pop(lambda d: d.rectangle((x0, y0, x1, y1), fill=(255, 255, 255, 255)))
    ctx.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], (176, 172, 160), 1.6, 0.6)
    ctx.picture(ctx.cache[key], ((x0 + x1) / 2 - iw * u / 2, y0 + pad * u))
    for i, line in enumerate(lines):
        ctx.text(((x0 + x1) / 2, y0 + (pad + ih + 6 + 12 + 24 * i) * u), line, ctx.font(18), INK, "mm")
    mid = (x0 + x1) / 2
    ctx.pop(lambda d: d.rectangle((mid - 28 * u, y0 - 7 * u, mid + 28 * u, y0 + 8 * u), fill=BLUE + (110,)))  # tape
    return fh + 18


def _chip_fits(ctx, text):
    """A chip shows its whole question or isn't drawn: what is drawn is exactly what a click would ask."""
    return ctx.font(17).getlength(text) + 24 * ctx.u <= (WIDTH - 2 * PAD) * ctx.u


def _chips(ctx, asks):
    """Follow-up questions as chips. Their rectangles go in ctx.chips (final pixels, relative to this line)."""
    u = ctx.u
    font = ctx.font(17)
    placed, x, y, left = [], (PAD + 62) * u, 2 * u, (PAD + 62) * u
    for text in asks:
        w = font.getlength(text) + 24 * u
        if x + w > (WIDTH - PAD) * u and x > left:
            x, left, y = PAD * u, PAD * u, y + 38 * u
        placed.append((text, x, y, w))
        x += w + 8 * u
    h = round(y / u) + 42
    ctx.layer(h)
    ctx.text((PAD * u, 20 * u), "Ask next", ctx.font(15), GREY, "lm")
    for text, cx, cy, w in placed:
        box = (cx, cy + 2 * u, cx + w, cy + 34 * u)
        if ctx.planning:
            ctx.chips.append((text, box[0] / SS, box[1] / SS, box[2] / SS, box[3] / SS))
        ctx.pop(lambda d, box=box: d.rounded_rectangle(box, 14 * u, fill=(226, 237, 255, 255)))
        ctx.line(_rounded_box(box[0], box[1], w, 32 * u, 14 * u), BLUE, 1.8, 0.7)
        ctx.text((cx + w / 2, cy + 18 * u), text, font, (36, 78, 168), "mm")
    return h


def build(sketch, scale, total_frames=TOTAL_FRAMES):
    """Everything to show a sketch, made ahead of time (so it can be made off the screen thread): the empty note as one
    RGBA image at 1x, each line as the frames of its drawing, and the chips' rectangles. `scale`: image pixels per
    design pixel. A photo, if there is one, is `sketch["photo"] = (a PIL image, a caption)`."""
    ctx = _Ctx(scale, zlib.crc32(sketch["title"].encode()))
    bars = [data[1] for kind, data in sketch["elements"] if kind == "bar"]
    lines = [lambda: _title(ctx, sketch["title"])]
    if sketch["sub"]:
        lines.append(lambda: _sub(ctx, sketch["sub"]))
    if sketch.get("photo"):
        lines.append(lambda: _photo(ctx, *sketch["photo"]))
    for kind, data in sketch["elements"]:
        makers = {"row": lambda data: _row(ctx, *data), "item": lambda data: _item(ctx, data),
                  "note": lambda data: _note(ctx, data), "flow": lambda data: _flow(ctx, data),
                  "bar": lambda data: _bar(ctx, data[0], data[1], max(bars, default=0))}
        lines.append(lambda make=makers[kind], data=data: make(data))  # bound now: it is called later, once per frame
    if sketch["src"]:
        lines.append(lambda: _src(ctx, sketch["src"]))
    asks = [q for q in sketch.get("asks", ()) if _chip_fits(ctx, q)]
    if asks:
        lines.append(lambda: _chips(ctx, asks))
    n = max(2, min(MAX_FRAMES, total_frames // len(lines)))
    made, chips = [], []
    for fn in lines:
        start = ctx.rnd.getstate()
        ctx.plan()
        h = fn()
        ctx.finish_plan()
        end, rects = ctx.rnd.getstate(), ctx.chips
        frames = []
        for k in range(1, n + 1):
            ctx.rnd.setstate(start)
            ctx.frame(k / n)
            fn()
            frames.append(ctx.img.resize((ctx.img.width // SS, ctx.img.height // SS), Image.LANCZOS))
        ctx.rnd.setstate(end)
        made.append((frames, h, rects))
    body = sum(h for _, h, _ in made)
    card_h = HEADER + 10 + body + 14
    m = SHADOW * scale
    W, H = round(WIDTH * scale + 2 * m), round((card_h + PILL) * scale + 2 * m)
    # the paper: shadow, sheet, title bar, and the Clear pill above it
    shadow = Image.new("RGBA", (W, H))
    ImageDraw.Draw(shadow).rounded_rectangle((m, m + PILL * scale + 5 * scale, W - m, H - m + 5 * scale), 10 * scale,
                                             fill=(0, 0, 0, 90))
    base = shadow.filter(ImageFilter.GaussianBlur(9 * scale))
    d = ImageDraw.Draw(base)
    top = m + PILL * scale
    d.rounded_rectangle((m, top, W - m, H - m), 10 * scale, fill=PAPER, outline=EDGE, width=max(1, round(scale)))
    d.rounded_rectangle((m, top, W - m, top + HEADER * scale), 10 * scale, fill=BAR_BG, outline=EDGE, width=max(1, round(scale)),
                        corners=(True, True, False, False))
    small = _font(int(13 * scale), HAND[-2:-1] + HAND[-1:])
    d.text((W / 2, top + HEADER * scale / 2), "Nova", font=small, fill=GREY, anchor="mm")
    pill = (W / 2 - 38 * scale, m + 2 * scale, W / 2 + 38 * scale, m + 28 * scale)
    d.rounded_rectangle(pill, 13 * scale, fill=(255, 255, 255, 235), outline=EDGE, width=max(1, round(scale)))
    d.text((W / 2, m + 15 * scale), "×  Clear", font=small, fill=INK, anchor="mm")
    elements, y = [], top + (HEADER + 10) * scale
    for frames, h, rects in made:
        elements.append({"frames": frames, "x": round(m), "y": round(y)})
        chips += [(text, round(m) + x0, round(y) + y0, round(m) + x1, round(y) + y1) for text, x0, y0, x1, y1 in rects]
        y += h * scale
    return {"base": base, "elements": elements, "chips": chips, "sketch": sketch}


class SketchPad(Layered):
    """The window: shows a built sketch, drawing each line in; a click on a chip asks its question, any other click
    clears it."""

    def __init__(self, root, on_chip=None):
        self.root = root
        target = self._init_surface(root, level=25)
        self.scale = dpi_scale(root) * self.px
        self.on_chip = on_chip
        self.current, self._jobs, self._hide_job, self.held = None, [], None, None
        target.bind("<Button-1>", self._click)
        target.bind("<Motion>", lambda e: target.config(cursor="hand2" if self._chip_at(e) else ""))
        self._present(Image.new("RGBA", (1, 1)), 0, 0)  # Windows rejects later paints if hidden before the first
        self._hide()

    def prepare(self, sketch):
        return build(sketch, self.scale)

    def _chip_at(self, event):
        for text, x0, y0, x1, y1 in (self.current or {}).get("chips", ()):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                return text

    def _click(self, event):
        text = self._chip_at(event)
        self.hide()
        if text and self.on_chip:
            self.on_chip(text)

    def show(self, built):
        self.hide()
        self.current = built
        base = built["base"]
        left, top, right, bottom = system.work_area()
        x = int(left + 0.06 * (right - left))
        y = max(top + 8, min(int(top + 0.12 * (bottom - top)), bottom - base.height / self.px - 8))  # tall notes stay on screen
        page = base.copy()
        self._show()
        self._present(page, x, y)
        steps = [(frame, el["x"], el["y"], k == len(el["frames"]) - 1) for el in built["elements"]
                 for k, frame in enumerate(el["frames"])]

        def step(i):
            frame, fx, fy, last = steps[i]
            shown = page if last else page.copy()  # a line's last frame stays; the ones before it are only for a moment
            shown.alpha_composite(frame, (fx, fy))
            self._present(shown, x, y)
            if i + 1 < len(steps):
                self._jobs = [self.win.after(FRAME_MS, step, i + 1)]
            else:
                self._jobs = []
                if self.held and self.held[0] is built["sketch"]:  # Nova finished speaking before the drawing did
                    self.hold(built["sketch"], self.held[1])
        step(0)

    def hold(self, sketch, seconds=HOLD_S):
        """Clear the note for `sketch` `seconds` after its drawing is done (or now, if it is), unless something newer has
        replaced it by then."""
        self.held = (sketch, seconds)
        built = self.current
        if built and built["sketch"] is sketch and not self._jobs and self._hide_job is None:
            self._hide_job = self.win.after(int(seconds * 1000), lambda: self.hide() if self.current is built else None)

    def hide(self):
        for job in self._jobs + ([self._hide_job] if self._hide_job else []):
            self.win.after_cancel(job)
        self._jobs, self._hide_job, self.current, self.held = [], None, None, None
        self._hide()
