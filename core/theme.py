"""The one colour of Nova's bar and card: Settings -> Colour & cursor (companion.color), worked out the way the window's
`themeTokens` (core/app.html) does it, so the bar, the card and the window are always the same colour. The glass itself
is neutral obsidian whatever the pick; the colour is the accent (fills, the sparkle, waveforms, a soft glow) and the
five bars of Nova's mark. `T` holds the current tokens as RGB tuples; apply() swaps them."""
import colorsys

VIOLET, INK = (123, 109, 255), (11, 13, 26)
GLASS = (12, 13, 18)  # the HUD's obsidian, for every pick
# Nova's own: neutral glass with the violet as its one voice. Fills are Signal Violet (#6d5ff7), not the brand #7b6dff,
# so white lettering on them reaches 4.5:1.
NOVA = {"accent": (109, 95, 247), "ink": (255, 255, 255), "light": (190, 182, 255), "tint": GLASS, "raised": (40, 41, 48),
        "text": (244, 244, 246), "body": (222, 223, 228), "muted": (172, 174, 182), "faint": (156, 158, 166)}
T = dict(NOVA)  # what the bar and card draw with right now
# Nova's own five bars: the logo's gradient (violet, blue, cyan, pink) taken at each bar, as the tray icon has it
RAMP = ((0.0, (123, 109, 255)), (0.31, (90, 140, 255)), (0.62, (63, 214, 230)), (1.0, (224, 71, 154)))


def _ramp(t):
    (t0, c0), (t1, c1) = next(pair for pair in zip(RAMP, RAMP[1:]) if t <= pair[1][0])
    return tuple(round(c0[i] + (c1[i] - c0[i]) * (t - t0) / (t1 - t0)) for i in range(3))


MARK = [_ramp((x + 2.5 - 8) / 32) for x in (8.3, 14.9, 21.5, 28.1, 34.7)]
PICK = [None]  # the picked (r, g, b), or None for Nova's own


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
    k = 0  # the surfaces stay neutral: the colour is the accent, not the glass
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
            "tint": GLASS, "raised": _hls(hue, .36 * k, .15), "text": _hls(hue, k, .95),
            "body": _hls(hue, .6 * k, .86), "muted": _hls(hue, .33 * k, .72), "faint": _hls(hue, .28 * k, .65)}


def apply(color):
    T.clear()
    T.update(tokens(color))
    PICK[0] = color or None


def marks():
    """The colours of the mark's five bars: Nova's own, or shades of the picked colour (as the cursor's mark does)."""
    if not PICK[0]:
        return list(MARK)
    return [tuple(min(255, round(c + (255 - c) * lift)) for c in PICK[0]) for lift in (0.0, 0.1, 0.2, 0.1, 0.0)]
