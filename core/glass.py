"""Frosted glass for the bar and the card: what is behind the window (grabbed once as it appears, blurred, then tinted
with the theme's dark), a soft light from above, a hint of the accent, a fine grain and a rim that is brighter on top.
Everything is drawn once per size on small images, so it costs about a millisecond a frame. On macOS (and if the grab
fails) it is the same glass without the backdrop."""
import functools

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageGrab

from core import system

GRAIN_W, GRAIN_H = 1600, 900  # the grain is made once, as one big sheet, and cropped
OPACITY = 232  # the glass is almost, not quite, solid: what is live behind it still shows a little


def backdrop(box):
    """The screen behind `box` (left, top, right, bottom), blurred, as an RGB image; None if it can't be grabbed."""
    if system.IS_MAC or box[2] <= box[0] or box[3] <= box[1]:
        return None
    try:
        system._own_windows_hidden(True)  # Nova's own windows, the bar and card included, are not part of the backdrop
        try:
            shot = ImageGrab.grab(bbox=tuple(int(v) for v in box), all_screens=True)
        finally:
            system._own_windows_hidden(False)
    except Exception:  # no desktop to grab (locked, remote session): plain glass
        return None
    small = ImageEnhance.Color(shot.reduce(4).convert("RGB")).enhance(1.4).filter(ImageFilter.GaussianBlur(6))  # blurring a quarter-size copy is 16 times cheaper
    return small.resize(shot.size, Image.BILINEAR).convert("RGB")


@functools.lru_cache(maxsize=1)
def _grain():
    """Two sheets of fine noise, one lightening and one darkening, as RGBA."""
    noise = Image.effect_noise((GRAIN_W, GRAIN_H), 60)
    sheets = []
    for color, alpha in (((255, 255, 255), noise.point(lambda v: max(0, v - 128) // 24)),
                         ((0, 0, 0), noise.point(lambda v: max(0, 128 - v) // 24))):
        sheet = Image.new("RGBA", noise.size, color + (0,))
        sheet.putalpha(alpha)
        sheets.append(sheet)
    return sheets


@functools.lru_cache(maxsize=96)
def mask(w, h, radius):
    """A rounded rectangle, anti-aliased (drawn 3 times larger, then reduced)."""
    big = Image.new("L", (w * 3, h * 3), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * 3 - 1, h * 3 - 1), radius * 3, fill=255)
    return big.reduce(3)


def fit(img, w, h, corner):
    """`img` at w x h with its corners kept as drawn and only the straight parts stretched (nine slices). The bar's
    glass is built once at the size it is growing to and fitted to every size on the way: building it afresh for each
    frame of the spring cost more than a frame."""
    W, H = img.size
    if (W, H) == (w, h):
        return img
    c = min(corner, (min(W, w) - 1) // 2, (min(H, h) - 1) // 2)
    if c < corner - 2:  # smaller than its own corners (the glow it grows out of): no slices to keep
        return img.resize((max(1, w), max(1, h)), Image.BILINEAR)
    out = Image.new(img.mode, (w, h))
    spans = lambda S, s: ((0, c, 0, c), (c, S - c, c, s - c), (S - c, S, s - c, s))  # noqa: E731  source, then where it goes
    for sx0, sx1, dx0, dx1 in spans(W, w):
        for sy0, sy1, dy0, dy1 in spans(H, h):
            if dx1 > dx0 and dy1 > dy0:
                part = img.crop((sx0, sy0, sx1, sy1))
                size = (dx1 - dx0, dy1 - dy0)
                out.paste(part if part.size == size else part.resize(size, Image.BILINEAR), (dx0, dy0))
    return out


def _vgrad(w, h, top, bottom):
    """An L image going from `top` to `bottom` down its height."""
    column = Image.linear_gradient("L").resize((1, h), Image.BILINEAR)  # 0 at the top, 255 at the bottom
    return column.point(lambda v: round(top + (bottom - top) * v / 255)).resize((w, h))


def pane(w, h, radius, tint, accent, back=None, opacity=OPACITY):
    """A w x h glass panel as RGBA with corner `radius`. `back`: the blurred backdrop cropped to this size, or None.
    Obsidian over the blurred screen, a soft wash of the accent high on the left, a faint grain, a hairline edge and a
    brighter line just inside the top: lit from above."""
    w, h = max(6, int(w)), max(6, int(h))
    radius = min(radius, w // 2, h // 2)
    base = Image.new("RGB", (w, h), tint)
    if back is not None and back.size == (w, h):
        # some of the screen's colour comes through, dimmed first: a white window behind the glass would otherwise
        # lift it until the text on it is hard to read
        base = Image.blend(back.point(lambda v: v * 0.55), base, 0.82)
    out = base.convert("RGBA")
    out.alpha_composite(glow_spot(w, h, accent))
    for sheet in _grain():
        out.alpha_composite(sheet.crop((0, 0, min(w, GRAIN_W), min(h, GRAIN_H))))
    outer = mask(w, h, radius)
    inner = Image.new("L", (w, h), 0)
    inner.paste(mask(w - 2, h - 2, max(1, radius - 1)), (1, 1))
    ring = ImageChops.subtract(outer, inner)
    edge = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    edge.putalpha(ring.point(lambda v: v * 23 // 255))  # the hairline: white at 9%
    out.alpha_composite(edge)
    top = Image.new("L", (w, h), 0)  # the top-lit line: white at 15%, one pixel inside the top edge
    top.paste(ImageChops.subtract(inner, _shift(inner, 1)), (0, 0))
    lit = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    lit.putalpha(ImageChops.multiply(top, _vgrad(w, h, 38, 0)))
    out.alpha_composite(lit)
    out.putalpha(ImageChops.multiply(outer, Image.new("L", (w, h), opacity)))
    return out


def _shift(img, dy):
    out = Image.new("L", img.size, 0)
    out.paste(img, (0, dy))
    return out


@functools.lru_cache(maxsize=32)
def _spot(size):
    return Image.radial_gradient("L").resize((size, size), Image.BILINEAR)  # 0 at the centre, 255 at the rim


def glow_spot(w, h, accent, strength=0.13):
    """The accent as a soft circle of light, 220 px across, centred 15% in and 20% down."""
    size = max(8, min(440, int(w * 0.9)))
    out = Image.new("RGBA", (w, h), accent + (0,))
    a = _spot(size).point(lambda v: round(255 * strength * max(0.0, 1 - v / 191) ** 1.6))
    alpha = Image.new("L", (w, h), 0)
    alpha.paste(a, (int(w * 0.15 - size / 2), int(h * 0.2 - size / 2)))
    out.putalpha(alpha)
    return out
