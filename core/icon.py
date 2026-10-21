"""Nova's icon, drawn in code so the tray, the shortcuts and the Mac app all match.

The mark: five sound bars that spell an "N" (two tall stems, three short bars stepping down between them), coloured
violet -> cyan -> pink with a soft glow, on a near-black tile. core/app.html, core/phone.html and the extension's
panel.html draw the same bars as SVG (BARS, on the same 48-unit grid) and animate them.

`python -m core.icon out.ico|out.icns|out.png` writes an icon file (used by setup).
"""
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

INK = ((8, (123, 109, 255)), (18, (90, 140, 255)), (28, (63, 214, 230)), (40, (224, 71, 154)))  # by x, left to right
TILE = ((19, 21, 40), (8, 10, 18))  # top, bottom
BARS = ((8.3, 11, 26), (14.9, 11.5, 13), (21.5, 17.5, 13), (28.1, 23.5, 13), (34.7, 11, 26))  # (x, top, height)
WIDTH = 5


def _mix(x, stops):
    if x <= stops[0][0]:
        return stops[0][1]
    for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
        if x <= x1:
            k = (x - x0) / (x1 - x0)
            return tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))
    return stops[-1][1]


def draw(size=64):
    S = size * 4  # drawn at 4x, then downscaled: smooth corners at 16 px
    u = S / 48

    tile_mask = Image.new("L", (S, S))
    ImageDraw.Draw(tile_mask).rounded_rectangle((0, 0, S - 1, S - 1), 11 * u, fill=255)
    tile = Image.new("RGB", (1, 2))
    tile.putdata(TILE)
    img = Image.new("RGBA", (S, S))
    img.paste(tile.resize((S, S), Image.BILINEAR), mask=tile_mask)

    bars = Image.new("L", (S, S))
    d = ImageDraw.Draw(bars)
    for x, top, h in BARS:
        d.rounded_rectangle((x * u, top * u, (x + WIDTH) * u, (top + h) * u), WIDTH * u / 2, fill=255)
    row = Image.new("RGB", (S, 1))
    row.putdata([_mix(x / u, INK) for x in range(S)])
    color = row.resize((S, S)).split()

    glow = bars.filter(ImageFilter.GaussianBlur(3 * u)).point(lambda v: v * .8)
    img.alpha_composite(Image.merge("RGBA", (*color, ImageChops.multiply(glow, tile_mask))))
    img.alpha_composite(Image.merge("RGBA", (*color, bars)))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    draw(256 if not sys.argv[1].endswith(".png") else 512).save(sys.argv[1])
