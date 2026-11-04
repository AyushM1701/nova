"""Frosted glass for the bar and the card: what is behind the window (grabbed once as it appears, blurred, then tinted
with the theme's dark), a soft light from above, a hint of the accent, a fine grain and a rim that is brighter on top.
Everything is drawn once per size on small images, so it costs about a millisecond a frame. On macOS (and if the grab
fails) it is the same glass without the backdrop."""
import functools

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageGrab

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
    small = shot.reduce(4).filter(ImageFilter.GaussianBlur(3))  # blurring a quarter-size copy is 16 times cheaper
    return small.resize(shot.size, Image.BILINEAR).convert("RGB")


@functools.lru_cache(maxsize=1)
def _grain():
    """Two sheets of fine noise, one lightening and one darkening, as RGBA."""
    noise = Image.effect_noise((GRAIN_W, GRAIN_H), 60)
    sheets = []
    for color, alpha in (((255, 255, 255), noise.point(lambda v: max(0, v - 128) // 8)),
                         ((0, 0, 0), noise.point(lambda v: max(0, 128 - v) // 8))):
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


def _vgrad(w, h, top, bottom):
    """An L image going from `top` to `bottom` down its height."""
    column = Image.linear_gradient("L").resize((1, h), Image.BILINEAR)  # 0 at the top, 255 at the bottom
    return column.point(lambda v: round(top + (bottom - top) * v / 255)).resize((w, h))


def pane(w, h, radius, tint, accent, back=None, opacity=OPACITY):
    """A w x h glass panel as RGBA with corner `radius`. `back`: the blurred backdrop cropped to this size, or None."""
    w, h = max(6, int(w)), max(6, int(h))
    radius = min(radius, w // 2, h // 2)
    base = Image.new("RGB", (w, h), tint)
    if back is not None and back.size == (w, h):
        # a quarter of the backdrop's colour comes through the tint, dimmed first: a white window behind the glass
        # would otherwise lift it until the text on it is hard to read
        base = Image.blend(back.point(lambda v: v * 0.55), base, 0.72)
    out = base.convert("RGBA")
    light = Image.new("RGBA", (w, h), (255, 255, 255, 0))  # light from above
    light.putalpha(_vgrad(w, h, 40, 0))
    out.alpha_composite(light)
    glow = Image.new("RGBA", (w, h), accent + (0,))  # a hint of the accent, low on the left
    spot = Image.radial_gradient("L").point(lambda v: max(0, 70 - v // 2) if v < 140 else 0)
    shape = Image.new("L", (w, h), 0)
    shape.paste(spot.resize((int(w * 0.9), int(h * 1.8)), Image.BILINEAR), (-int(w * 0.2), int(h * 0.1)))
    glow.putalpha(shape)
    out.alpha_composite(glow)
    for sheet in _grain():
        out.alpha_composite(sheet.crop((0, 0, min(w, GRAIN_W), min(h, GRAIN_H))))
    outer = mask(w, h, radius)
    inner = Image.new("L", (w, h), 0)
    inner.paste(mask(w - 2, h - 2, max(1, radius - 1)), (1, 1))
    rim = ImageChops.multiply(ImageChops.subtract(outer, inner), _vgrad(w, h, 190, 55))  # bright on top, faint below
    edge = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    edge.putalpha(rim)
    out.alpha_composite(edge)
    out.putalpha(ImageChops.multiply(outer, Image.new("L", (w, h), opacity)))
    return out
