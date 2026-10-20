"""Nova's icon, drawn in code so the tray, the shortcuts and the Mac app all match.

`python -m core.icon out.ico|out.icns` writes an icon file (used by setup).
"""
import sys

from PIL import Image, ImageDraw


def draw(size=64):
    img = Image.new("RGBA", (size, size))
    d = ImageDraw.Draw(img)
    d.ellipse((size * 0.06, size * 0.06, size * 0.94, size * 0.94), fill="#7c5cff")
    d.ellipse((size * 0.375, size * 0.375, size * 0.625, size * 0.625), fill="white")
    return img


if __name__ == "__main__":
    draw(256).save(sys.argv[1])
