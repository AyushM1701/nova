"""The one colour of Nova's bar and card: Settings -> Colour & cursor (companion.color), worked out the way the window's
`themeTokens` (core/app.html) does it, so the bar, the card and the window are always the same colour. "nova" (or no
colour) keeps Nova's own violet on navy. `T` holds the current tokens as RGB tuples; apply() swaps them."""
import colorsys

VIOLET, INK = (123, 109, 255), (11, 13, 26)
# Nova's own: indigo glass with the violet as its one voice. Fills are Signal Violet (#6d5ff7), not the brand #7b6dff,
# so white lettering on them reaches 4.5:1; the text tints come from the violet, not from grey.
NOVA = {"accent": (109, 95, 247), "ink": (255, 255, 255), "light": (190, 182, 255), "tint": (17, 14, 42), "raised": (44, 38, 86),
        "text": (244, 242, 255), "body": (222, 219, 246), "muted": (184, 179, 226), "faint": (158, 152, 208)}
T = dict(NOVA)  # what the bar and card draw with right now


def _hls(h, s, light):
    r, g, b = colorsys.hls_to_rgb(h / 360, light, s)
    return round(r * 255), round(g * 255), round(b * 255)


def _lum(c):
    r, g, b = [v / 255 for v in c]
    r, g, b = [v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4 for v in (r, g, b)]
    return .2126 * r + .7152 * g + .0722 * b


def ratio(a, b):
    x, y = _lum(a), _lum(b)
    return (max(x, y) + .05) / (min(x, y) + .05)


def tokens(color):
    """The colours for a picked (r, g, b), or Nova's own for None. Same rules as the window: a grey or white pick gives
    neutral surfaces, lettering on the accent keeps 4.5:1 (near-black when white can't reach it, as on yellow)."""
    if not color:
        return dict(NOVA)
    r, g, b = [v / 255 for v in color]
    mx, mn = max(r, g, b), min(r, g, b)
    light, d = (mx + mn) / 2, mx - mn
    sat = d / (1 - abs(2 * light - 1)) if d else 0
    hue = (round(60 * (((g - b) / d + 6) % 6 if mx == r else (b - r) / d + 2 if mx == g else (r - g) / d + 4)) if d else 0)
    k = min(1.0, sat / .5)  # how much of the colour goes into the dark surfaces
    surface = _hls(hue, .36 * k, .096)
    fs, f0 = (max(.5, sat * .9) if sat else 0), min(.62, max(.45, light))
    fl, on_white = f0, light < .8
    while on_white and ratio(_hls(hue, fs, fl), (255, 255, 255)) < 4.6:
        fl -= .01
        if fl < .36:
            on_white, fl = False, f0
    dark = _hls(231, .5, .04)
    while not on_white and ratio(_hls(hue, fs, fl), dark) < 4.6 and fl < .9:
        fl += .01
    ts, tl = (max(.4, sat) if sat else 0), .78
    while ratio(_hls(hue, ts, tl), surface) < 7 and tl < .95:
        tl += .01
    return {"accent": _hls(hue, fs, fl), "ink": (255, 255, 255) if on_white else INK, "light": _hls(hue, ts, tl),
            "tint": _hls(hue, .36 * k, .06), "raised": _hls(hue, .36 * k, .15), "text": _hls(hue, k, .95),
            "body": _hls(hue, .6 * k, .86), "muted": _hls(hue, .33 * k, .72), "faint": _hls(hue, .28 * k, .65)}


def apply(color):
    T.clear()
    T.update(tokens(color))
