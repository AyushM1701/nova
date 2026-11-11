"""Flow Bar: a small pill on screen, like Wispr Flow's.

Idle it is a quiet pill with standby dots; hovering it shows how to talk, it grows with a live waveform while
you speak, shows a travelling wave while Nova thinks, a voice waveform while it talks, and turns amber when it
needs your OK. Click it to talk, right-click it to open the Nova window.

It sits at the top centre, out of sight until the pointer rests at the top edge (or Nova is working); or at the
bottom centre (above the taskbar or Dock), always visible. On a MacBook with a notch it hangs just below the
notch, centred on it. Drawn with per-pixel alpha so the edges stay
smooth: a layered window on Windows, a native borderless window on macOS (sharp on Retina, never takes
focus, and clicks pass through its transparent parts).
"""
import collections
import functools
import ctypes
import io
import math
import threading
import time
import tkinter as tk
import types

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from core import glass, system, theme

if not system.IS_MAC:
    from ctypes import wintypes as w

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.UINT, ctypes.c_void_p, ctypes.c_void_p,
                                       w.DWORD]
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    user32.UpdateLayeredWindow.argtypes = [w.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, w.DWORD]

SS = 3  # draw 3x larger, then downscale: anti-aliased edges
BOX = (300, 56)  # window size in logical px; the pill (6 px in, CAPSULE tall) and its halo are drawn inside it
CAPSULE = 42  # the pill's height, logical px
MARGIN = 24  # logical px of transparent room around the glass, for its shadow and the accent's glow
# Nova's logo, as the tray icon and the window draw it: five bars in a 48-unit square that spell an N (x, y, height)
LOGO = ((8.3, 11, 26), (14.9, 11.5, 13), (21.5, 17.5, 13), (28.1, 23.5, 13), (34.7, 11, 26))
TALK = (0.42, 0.34, 0.5, 0.38, 0.46)  # seconds each bar takes to swing while Nova talks, as in the window
UNIT = 15 / 26  # logical px per logo unit at size 1: its tall bars are 15 px
MARK_W = (34.7 + 5 - 8.3) * UNIT  # the mark's width at size 1
# motion, from transitions.dev's tokens: how long, and which curve
QUICK, FAST, MEDIUM, SLOW, VERY_SLOW = 0.15, 0.25, 0.35, 0.4, 0.5  # seconds
FRAME_MS = 1000 / 60  # a frame, while anything moves
GRAB = (616, 444)  # logical px of screen grabbed behind the glass: the widest notice and the tallest card, plus a tenth
BLUR = 2  # logical px: the cross-blur of a swap, an entrance, an exit


def smooth_out(p):
    """cubic-bezier(0.22, 1, 0.36, 1), the curve things open, close and resize on (close enough: an ease-out quint)."""
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 5


def in_out(p):
    """ease-in-out: swaps and reveals."""
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)
MIST = (224, 231, 255)  # the light end of the waveform's gradient
GREY = (150, 152, 160)
WHITE, AMBER = (255, 255, 255), (255, 186, 60)


def _inside(point, rect):
    return rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]


class Reveal:
    """Hover-to-open at the top edge: hidden -> peek (a glow, after PEEK_S in the zone) -> open (the pill, after DWELL_S).
    An open pill stays while the pointer is in `keep`, and goes LEAVE_S after it leaves. Pure: the clock and the pointer
    are passed in."""
    PEEK_S, DWELL_S, LEAVE_S = 0.08, 0.3, 0.5

    def __init__(self, clock=time.monotonic):
        self.clock, self.stage, self.since, self.left = clock, "hidden", None, None

    def update(self, mouse, zone, keep, blocked):
        """`mouse` is (x, y) or None (locked desktop); `blocked` (a button down, no pointer, a full-screen app) stops a
        new reveal but never closes an open pill, so a click on it still lands."""
        now = self.clock()
        if mouse is None or (blocked and self.stage != "open"):
            self.stage, self.since, self.left = "hidden", None, None
        elif self.stage == "open":
            if _inside(mouse, keep):
                self.left = None
            else:
                self.left = now if self.left is None else self.left
                if now - self.left >= self.LEAVE_S:
                    self.stage, self.since, self.left = "hidden", None, None
        elif not _inside(mouse, zone):
            self.stage, self.since = "hidden", None
        else:
            self.since = now if self.since is None else self.since
            if now - self.since >= self.DWELL_S:
                self.stage, self.left = "open", None
            elif now - self.since >= self.PEEK_S:
                self.stage = "peek"
        return self.stage


def spring(x, v, target, dt, k=420.0, damping=1.0):
    """One step of a damped spring toward `target`, so motion depends on real elapsed time and not on the frame rate
    (damping 1, critical: it settles as fast as it can without going past; 0.8 would bounce). Steps of at most 1/120 s."""
    c, steps = 2 * damping * math.sqrt(k), max(1, math.ceil(dt * 120))
    h = dt / steps
    for _ in range(steps):
        v += (k * (target - x) - c * v) * h
        x += v * h
    return x, v


def visible(state, card, stage, reveal, top):
    """Whether the bar is on screen: while it is a card; always at the bottom (the edge belongs to the
    taskbar); while Nova works; otherwise only as the reveal mode allows."""
    if card or reveal == "always" or not top or state not in ("idle", "paused"):
        return True
    return reveal == "hover" and stage in ("peek", "open")


SEMIBOLD = ("seguisb.ttf", "segoeui.ttf", "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc")


def _font(px, names=("segoeui.ttf", "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc")):
    for name in names:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            pass
    return ImageFont.load_default(px)


@functools.lru_cache(maxsize=64)
def ui_font(px, weight=400, italic=False):
    """Segoe UI Variable at any weight (the design's 500 is a real 500 here); else the nearest static face."""
    if italic:
        return _font(px, ("segoeuii.ttf", "/System/Library/Fonts/SFNSItalic.ttf", "/System/Library/Fonts/SFNS.ttf"))
    try:
        f = ImageFont.truetype("SegUIVar.ttf", px)
        f.set_variation_by_axes([weight, 10.5])
        return f
    except (OSError, ValueError, AttributeError):  # Windows 10, or a Mac
        return _font(px, SEMIBOLD) if weight >= 550 else _font(px)


@functools.lru_cache(maxsize=16)
def mono_font(px):
    return _font(px, ("CascadiaMono.ttf", "consola.ttf", "/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc"))


def mark(img, x, cy, s, size=1.0, colors=None, state="idle", t=0.0, born=None, levels=None):
    """Nova's logo from `x`, centred on `cy` (image px; `s` image px per logical px), alive as in the window: its bars
    rise into place one after another when it appears (`born`), follow the microphone while listening (`levels`, five
    0..1), roll a wave through while thinking (the glow breathing), swing like a voice while talking, and wave slowly
    while waiting for an OK. A soft glow of its own colours sits behind it. Returns its width."""
    colors = colors or theme.marks()
    u = UNIT * size * s
    pad = round(5 * u)
    W, H = round(MARK_W * size * s) + 2 * pad, round(30 * u) + 2 * pad
    layer = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(layer)
    mid, still = H / 2, system.reduced_motion()
    glow = 0.8
    for i, ((bx, by, bh), c) in enumerate(zip(LOGO, colors)):
        sy, ty, a = 1.0, 0.0, 1.0
        if born is not None and not still:  # rising into place, 70 ms apart
            e = smooth_out((t - born - 0.07 * i) / 0.7)
            sy, a = 0.05 + 0.95 * e, e
        if state == "listening" and levels:
            sy *= 0.4 + 0.75 * levels[i]
            glow = 1.0
        elif state in ("thinking", "approval") and not still:
            period, lag = (1.3, 0.16) if state == "thinking" else (2.2, 0.2)
            f = 0.5 - 0.5 * math.cos(2 * math.pi * (t + i * lag) / period)
            ty, sy = -2.5 * f, sy * (1 - 0.28 * f)
            if state == "thinking":
                glow = 0.35 + 0.65 * (0.5 + 0.5 * math.cos(2 * math.pi * t / 1.3))
        elif state == "speaking" and not still:
            f = 0.5 - 0.5 * math.cos(math.pi * t / TALK[i])
            sy *= 1.12 - 0.62 * f
        hh, ccy = bh * sy * u, mid + (by + bh / 2 - 24 + ty) * u
        x0 = pad + (bx - 8.3) * u
        if a > 0.01:
            d.rounded_rectangle((x0, ccy - hh / 2, x0 + 5 * u, ccy + hh / 2), radius=2.5 * u, fill=c + (round(255 * a),))
    halo = layer.filter(ImageFilter.GaussianBlur(2.4 * u))
    halo.putalpha(halo.getchannel("A").point(lambda v: round(v * glow)))
    ax, ay = round(x - pad), round(cy - mid)
    for part in (halo, layer):  # cropped where it would hang over the image's edge
        img.alpha_composite(part, (max(0, ax), max(0, ay)), (max(0, -ax), max(0, -ay)))
    return MARK_W * size * s


def keycap(d, right, cy, s, text, font):
    """A crisp key ending at `right`: mono, white at 65% on white at 6%, a hairline edge lit along its top. Returns
    its left edge."""
    w, h = font.getlength(text) + 12 * s, 18 * s
    box = (right - w, cy - h / 2, right, cy + h / 2)
    d.rounded_rectangle(box, 5 * s, fill=(255, 255, 255, 15), outline=(255, 255, 255, 26), width=max(1, round(s)))
    d.line((box[0] + 5 * s, box[1] + s, box[2] - 5 * s, box[1] + s), fill=(255, 255, 255, 22), width=max(1, round(s)))
    d.text((right - w / 2, cy), text, font=font, fill=(255, 255, 255, 166), anchor="mm")
    return right - w


def stop_square(d, cx, cy, s, half, alpha=230):
    d.rounded_rectangle((cx - half, cy - half, cx + half, cy + half), radius=max(1, half * .4), fill=(255, 255, 255, alpha))


def mic(d, cx, cy, s, color):
    """A small microphone outline: what Nova heard."""
    wd = max(1, round(1.4 * s))
    d.rounded_rectangle((cx - 2.6 * s, cy - 6.5 * s, cx + 2.6 * s, cy + 1.5 * s), radius=2.6 * s, outline=color, width=wd)
    d.arc((cx - 5 * s, cy - 5 * s, cx + 5 * s, cy + 4 * s), 0, 180, fill=color, width=wd)
    d.line((cx, cy + 4 * s, cx, cy + 6.5 * s), fill=color, width=wd)


@functools.lru_cache(maxsize=16)
def _text_mask(text, font, ss):
    left, top, right, bottom = font.getbbox(text, anchor="lm")
    m = Image.new("L", (int(right - left) + 4, int(bottom - top) + 4))
    ImageDraw.Draw(m).text((2 - left, 2 - top), text, font=font, fill=255, anchor="lm")
    return m.reduce(ss), (left - 2) / ss, (top - 2) / ss


def shimmer(img, x, cy, text, font, ss, t, still=False):
    """`text` at (x, cy) (its left middle, image px) with a band of light sweeping across it every 2.2 s: white at 40%,
    95% in the band. `font` is ss times the image's scale."""
    m, ox, oy = _text_mask(text, font, ss)
    w, h = m.size
    if still:
        row = [204] * w
    else:
        c = (t / 2.2 % 1.0) * 3 * w - w  # the band comes in from a width before the text and leaves a width after
        row = [round(255 * (0.4 + 0.55 * in_out(1 - abs(i - c) / (0.5 * w)))) for i in range(w)]  # eased: no hard peak
    band = Image.new("L", (w, 1))
    band.putdata(row)
    layer = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    layer.putalpha(ImageChops.multiply(m, band.resize((w, h))))
    img.alpha_composite(layer, (round(x + ox), round(cy + oy)))


def wave(img, x, cy, heights, bw, gap, accent):
    """Bars from `x`, centred on `cy` (image px), each lit from light at the top to the accent at the bottom."""
    hmax = max(max(heights), bw)
    W, H = int(len(heights) * (bw + gap) - gap) + 2, int(hmax) + 2
    m = Image.new("L", (W * 3, H * 3))  # drawn 3x, for round ends
    d = ImageDraw.Draw(m)
    for i, hh in enumerate(heights):
        hh, bx = max(bw, hh), 1 + i * (bw + gap)
        d.rounded_rectangle((bx * 3, (H - hh) / 2 * 3, (bx + bw) * 3, (H + hh) / 2 * 3), radius=bw * 1.5, fill=255)
    layer = Image.composite(Image.new("RGB", (W, H), accent), Image.new("RGB", (W, H), MIST),
                            Image.linear_gradient("L").resize((W, H))).convert("RGBA")
    layer.putalpha(m.reduce(3))
    img.alpha_composite(layer, (round(x), round(cy - H / 2)))


@functools.lru_cache(maxsize=24)
def _halo(W, H, m, gw, gh, r, accent):
    """The glass's drop shadow and the accent's glow around it, blurred at a quarter size (the blur is the slow part)."""
    q, k = 4, m / MARGIN
    w, h = max(1, W // q), max(1, H // q)
    box = (m / q, m / q, (m + gw) / q, (m + gh) / q)
    glow = Image.new("RGBA", (w, h), accent + (0,))
    ImageDraw.Draw(glow).rounded_rectangle(box, r / q, fill=accent + (90,))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((box[0], box[1] + 8 * k / q, box[2], box[3] + 8 * k / q), r / q, fill=(0, 0, 0, 185))
    out = shadow.filter(ImageFilter.GaussianBlur(7 * k / q))
    out.alpha_composite(glow.filter(ImageFilter.GaussianBlur(9 * k / q)))
    out = out.resize((W, H), Image.BILINEAR)
    out.putalpha(out.getchannel("A").point(lambda a: a if a >= 10 else 0))  # the faintest edge lets clicks through
    return out


@functools.lru_cache(maxsize=4)
def _edge_glow(W, H, s, accent):
    """The glow along the screen's top edge while the pointer rests there: a line of the accent in its own soft light."""
    line = 32 * s
    soft = Image.new("RGBA", (W, H), accent + (0,))
    ImageDraw.Draw(soft).rounded_rectangle((W / 2 - line - 4 * s, -6 * s, W / 2 + line + 4 * s, 7 * s), radius=6 * s, fill=accent + (150,))
    img = soft.filter(ImageFilter.GaussianBlur(5 * s))
    ImageDraw.Draw(img).rounded_rectangle((W / 2 - line, 0, W / 2 + line, 3 * s), radius=1.5 * s, fill=accent + (255,))
    return img


def voice(t, i, level=None):
    """How tall bar `i` of Nova's voice is at time `t`, 0.2..1: as loud as the voice is now (`level`, 0..1, when the
    voice reports it), each bar a little different; without a level, a smooth swing (|sin| bounced off the bottom)."""
    swing = 0.5 - 0.5 * math.cos(t * 10 + i * 1.8)
    return 0.3 + 0.7 * swing if level is None else 0.2 + 0.8 * min(1.0, level * 1.4) * (0.55 + 0.45 * swing)


if not system.IS_MAC:
    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG), ("biPlanes", w.WORD),
                    ("biBitCount", w.WORD), ("biCompression", w.DWORD), ("biSizeImage", w.DWORD),
                    ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD),
                    ("biClrImportant", w.DWORD)]
else:
    import objc
    from AppKit import NSColor, NSData, NSImage, NSImageView, NSMakeRect, NSScreen, NSTrackingArea, NSWindow

    class _View(NSImageView):
        """Shows the rendered image and passes clicks and hover back to Python (macOS)."""

        def acceptsFirstMouse_(self, event):
            return True  # one click works even though Nova's window is never the active one

        # plain Python, not a method macOS calls: newer pyobjc refuses to load the class otherwise
        # ("'_send' expects 0 arguments"), which stopped Nova from starting on a Mac
        @objc.python_method
        def _send(self, kind, event):
            p = self.convertPoint_fromView_(event.locationInWindow(), None)
            self.owner._mac_event(kind, p.x, self.frame().size.height - p.y)

        def mouseDown_(self, event):
            self._send("<Button-1>", event)

        def rightMouseDown_(self, event):
            self._send("<Button-3>", event)

        def mouseEntered_(self, event):
            self._send("<Enter>", event)

        def mouseExited_(self, event):
            self._send("<Leave>", event)

        def mouseMoved_(self, event):
            self._send("<Motion>", event)


def dpi_scale(root):
    # Tk on macOS works in points (72 per inch); Windows reports real DPI once the process is DPI-aware
    return 1.0 if system.IS_MAC else root.winfo_fpixels("1i") / 96


class _Event:
    def __init__(self, x, y):
        self.x, self.y = x, y


class _Target:
    """Stands in for a Tk widget on macOS, where the drawing is a native window: bind() and config()."""

    def __init__(self):
        self.handlers = {}

    def bind(self, kind, fn):
        self.handlers[kind] = fn

    def config(self, **_):
        pass  # the pointer shape is the system's on macOS


class Layered:
    """A borderless, always-on-top window showing an RGBA image with per-pixel alpha. Windows: a layered
    window (transparent pixels let clicks through). macOS: a native borderless NSWindow at the screen's real
    pixel density, which never takes focus. `self.px` is device pixels per logical pixel for the image."""

    def _init_surface(self, root, level=3):
        win = self.win = tk.Toplevel(root)  # on macOS only a timer host: it is never shown
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        self.hwnd, self._size, self.px, self.ns = None, None, 1, None
        if system.IS_MAC:
            win.withdraw()
            try:
                return self._init_mac(level)
            except Exception:  # pyobjc problem: fall back to a plain Tk window (blurry on Retina, but works)
                self.ns = None
                return self._init_tk_fallback()
        self.hwnd = system.no_activate(win, layered=True)
        system.OWN_WINDOWS.append(self.hwnd)
        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        return win

    def _init_mac(self, level):
        self.px = int(NSScreen.screens()[0].backingScaleFactor() or 2)
        ns = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(0, 0, 10, 10), 0, 2, False)
        ns.setOpaque_(False)
        ns.setBackgroundColor_(NSColor.clearColor())
        ns.setHasShadow_(False)  # the image draws its own
        ns.setLevel_(level)  # 3 floats over apps; 25 (status) also covers the menu bar, for the notch
        ns.setCollectionBehavior_(1 | 16 | 64 | 256)  # all Spaces, stationary, not in Cmd+Tab, over full screen
        ns.setIgnoresMouseEvents_(False)
        ns.setAcceptsMouseMovedEvents_(True)
        view = _View.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        view.owner = self
        view.addTrackingArea_(NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            NSMakeRect(0, 0, 10, 10), 0x01 | 0x02 | 0x80 | 0x200, view, None))  # enter/exit, moved, always, in rect
        ns.setContentView_(view)
        self.ns, self.view, self.target = ns, view, _Target()
        system.OWN_WINDOWS.append(ns)
        return self.target

    def _init_tk_fallback(self):
        from PIL import ImageTk
        self._tk_image = ImageTk.PhotoImage
        self.win.deiconify()
        self.win.attributes("-transparent", True)
        self.win.config(bg="systemTransparent")
        self.label = tk.Label(self.win, bg="systemTransparent", borderwidth=0, highlightthickness=0)
        self.label.pack()
        return self.label

    def _mac_event(self, kind, x, y):
        fn = self.target.handlers.get(kind)
        if fn:  # in image pixels, like a click on Windows
            fn(_Event(x * self.px, y * self.px))

    def _present(self, img, x, y, alpha=255):
        """Show `img` at (x, y), in screen coordinates with the origin top-left, logical pixels."""
        if system.IS_MAC:
            w_pt, h_pt = img.width / self.px, img.height / self.px
            if self.ns is None:
                self.win.geometry(f"{img.width}x{img.height}+{x}+{y}")
                self.photo = self._tk_image(img)  # keep a reference or Tk drops the image
                self.label.config(image=self.photo)
                return
            buf = io.BytesIO()
            img.save(buf, "PNG")
            image = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue())))
            image.setSize_((w_pt, h_pt))  # Retina: the extra pixels make it sharp, not bigger
            full = NSScreen.screens()[0].frame().size.height  # AppKit counts y from the bottom of the main screen
            self.ns.setFrame_display_(NSMakeRect(x, full - y - h_pt, w_pt, h_pt), True)
            self.view.setFrame_(NSMakeRect(0, 0, w_pt, h_pt))
            for area in self.view.trackingAreas():
                self.view.removeTrackingArea_(area)
            self.view.addTrackingArea_(NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                NSMakeRect(0, 0, w_pt, h_pt), 0x01 | 0x02 | 0x80 | 0x200, self.view, None))
            self.view.setImage_(image)
            self.ns.setAlphaValue_(alpha / 255)
            return
        if self._size != img.size:  # a new bitmap only when the size changes
            header = BITMAPINFOHEADER(40, img.width, -img.height, 1, 32, 0, 0, 0, 0, 0, 0)  # top-down 32-bit
            self.bits = ctypes.c_void_p()
            dib = gdi32.CreateDIBSection(self.screen_dc, ctypes.byref(header), 0, ctypes.byref(self.bits), None, 0)
            if not dib:  # too big for Windows: writing to the missing bitmap would end Nova
                raise MemoryError(f"Windows can't make a {img.width} x {img.height} picture")
            old = gdi32.SelectObject(self.mem_dc, dib)
            if self._size:
                gdi32.DeleteObject(old)
            self._size = img.size
        bgra = img.tobytes("raw", "BGRa")  # Windows wants premultiplied BGRA; 8 times faster than numpy
        ctypes.memmove(self.bits, bgra, len(bgra))
        user32.UpdateLayeredWindow(self.hwnd, self.screen_dc, ctypes.byref(w.POINT(x, y)),
                                   ctypes.byref(w.SIZE(*img.size)), self.mem_dc, ctypes.byref(w.POINT(0, 0)),
                                   0, ctypes.byref(BLENDFUNCTION(0, 0, alpha, 1)), 2)  # AC_SRC_ALPHA, ULW_ALPHA

    def _move(self, x, y):
        """Move the window without redrawing it: much cheaper than _present for something that follows the mouse."""
        if self.ns is not None:
            full = NSScreen.screens()[0].frame().size.height  # AppKit counts y from the bottom of the main screen
            self.ns.setFrameOrigin_((x, full - y - self.ns.frame().size.height))
        elif system.IS_MAC:
            self.win.geometry(f"+{x}+{y}")
        else:
            user32.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(w.POINT(x, y)), None, None, None, 0, None, 0)

    def _click_through(self, on=True):
        """Clicks go to the app underneath, even on the window's own pixels (or, with on=False, back to the window)."""
        if self.ns is not None:
            self.ns.setIgnoresMouseEvents_(on)
        elif self.hwnd:  # WS_EX_TRANSPARENT
            style = user32.GetWindowLongW(self.hwnd, -20)
            user32.SetWindowLongW(self.hwnd, -20, style | 0x20 if on else style & ~0x20)

    def _show(self):
        if self.ns is not None:
            self.ns.orderFrontRegardless()  # shown without activating Nova: the app you're in keeps focus
        else:
            system.show(self.win, self.hwnd)

    def _hide(self):
        if self.ns is not None:
            self.ns.orderOut_(None)
        else:
            system.hide(self.win, self.hwnd)


class Bar(Layered):
    # class defaults so a Bar built without __init__ (the tests do) behaves as before: always on screen
    reveal, stage, card, suppressed, _vis, _thru, _dt = "always", "hidden", None, False, None, False, 1 / 60
    vw, vh, _last = 0.0, 0.0, None  # the glass's size velocities, and when it was last stepped
    _born, _leave, _swap, _key, _last_img, _shake, _hover_at, _gated = None, None, None, None, None, None, 0.0, True  # motion
    badge, recording, _sec = "", None, 0  # beside "Listening" ("Dictation · Gmail"); when a meeting recording began; the second last drawn
    timer = None  # when the next voice timer rings (time.time()): the resting pill counts it down
    said, _heard_at = None, 0.0  # how loud Nova's voice is now, eased (None: no level is coming, the bars swing by themselves)
    frames = collections.deque(maxlen=600)  # (seconds since the last frame, seconds it took to draw): for tuning the motion
    back, _pane, _at, _glass = None, None, None, None  # the blurred screen behind (image, x, y); the glass at the size
    # it is growing to (its key, the image); where the content and the glass were drawn in the window

    def __init__(self, root, on_click, on_menu=None, position="bottom", reveal="always"):
        self.scale = dpi_scale(root)
        self.hovering = False
        self.f_label = ui_font(int(12 * self.scale * SS), 500)
        self.area, self.top = None, position == "top"
        self.reveal = "always" if system.IS_MAC else reveal  # hover-reveal is Windows for now
        self.reveals = Reveal()
        self.notch = system.notch()  # (width, height) of a MacBook's notch, or (0, 0)
        target = self._init_surface(root, level=25)  # macOS: above full-screen apps and the menu bar
        self._place()
        self.on_click, self.on_menu = on_click, on_menu
        target.bind("<Button-1>", self._clicked)
        if on_menu:
            target.bind("<Button-3>", lambda _: on_menu())
            target.bind("<Button-2>", lambda _: on_menu())  # right button on macOS Tk
        target.bind("<Enter>", lambda _: self._hover(True))
        target.bind("<Leave>", lambda _: self._hover(False))

        self.state, self.levels = "idle", collections.deque([0.0] * 15, maxlen=15)
        self.shown = [0.0] * 15  # the drawn bar heights, eased toward the live levels
        self.w, self.h = self._target()
        self.dirty = True
        self._job = None
        self._grab()
        self._tick()  # the first paint comes before any hiding: Windows rejects later paints otherwise (error 87)
        self._apply()
        self._watch_screen()
        self._watch_hover()

    @property
    def island(self):
        """Hanging from a MacBook notch (top position on a notched screen)."""
        return self.top and self.notch[1] > 0

    def set_position(self, position):
        if (position == "top") != self.top:
            self.top, self.dirty = position == "top", True
            self._place()
            self._apply()

    def set_reveal(self, reveal):
        self.reveal = "always" if system.IS_MAC else reveal
        self._apply()

    def attach(self, card):
        """A card (core/overlay.py) to grow into, or None to shrink back to the pill."""
        self.card, self.dirty = card, True
        self._apply()
        self._wake()

    @property
    def peeking(self):
        """The hairline glow at the top edge: the pointer is there, the pill isn't open yet."""
        return self.stage == "peek" and self.state in ("idle", "paused") and self.reveal == "hover" and self.top

    def _apply(self):
        """Show or hide the window as `visible` says, and let clicks through only while it is just the glow."""
        want = visible(self.state, self.card is not None, self.stage, self.reveal, self.top)
        if want != self._vis:
            was, self._vis = self._vis, want
            if want:
                self._grab()  # before the window appears: its glass is what is behind it
                self._show()
                if self._leave is None:  # (coming back mid-exit, it simply stays)
                    self._born = time.monotonic()  # it rises in: fade, a little drop, the blur clearing
                    self._key = self._last_img = self._swap = None
                self._leave = None
                self.dirty = True
                self._wake()
            elif was and hasattr(self, "win") and not system.reduced_motion():
                self._leave = time.monotonic()  # it fades up and out, quicker than it came; _tick hides it after
                self._wake()
            else:
                self._hide()
        through = want and self.peeking
        if through != self._thru:
            self._thru = through
            self._click_through(through)

    def _zone(self):
        """The hot zone: the top 2 px of the screen (of the work area, with a taskbar on top), 440 px wide at the middle."""
        half = 220 * self.scale
        return (self.cx - half, 0, self.cx + half, self.area[1] + 2)

    def _keep(self):
        """Where an open pill stays open: the zone down to a little below the pill."""
        left, _, right, _ = self._zone()
        return (left, 0, right, self.anchor + (self.h + 24) * self.scale)

    def _watch_hover(self):
        """The top-edge pointer check, 20 times a second, while the bar hides at the top. A hidden window gets no mouse
        events, so this reads the pointer position itself."""
        delay = 500
        try:
            if self.reveal == "hover" and self.top:
                delay = 50
                self._look()
        finally:  # whatever fails, the next look is still scheduled: a dead poll would hide the bar for good
            self.win.after(delay, self._watch_hover)

    def _look(self):
        try:
            pos = system.mouse_pos()
        except OSError:  # locked desktop
            pos = None
        blocked = self.suppressed or system.mouse_down() or not system.cursor_visible()
        stage = self.reveals.update(pos, self._zone(), self._keep(), blocked)
        if stage != self.stage:
            if (self.stage, stage) == ("peek", "open") and self.card is None:  # the glow condenses into the pill
                self.w, self.h, self.vw, self.vh, self._key = 64.0, 4.0, 0.0, 0.0, None
            self.stage, self.dirty = stage, True
            self._apply()
            self._wake()

    def _place(self):
        left, top, right, bottom = self.area = system.work_area()
        extra = self.notch[1] if self.island else 0
        self.W, self.H = int(BOX[0] * self.scale), int((BOX[1] + extra) * self.scale)
        if self.island:  # flush with the very top of the screen, centred on the notch
            full_left, full_right = system.screen_span()
            self.x, self.y = int((full_left + full_right - self.W) / 2), 0
        else:
            self.x = int((left + right - self.W) / 2)
            self.y = int(top) if self.top else int(bottom - self.H)
        # the glass hangs from its anchor: its top edge (at the top of the screen), else its bottom edge
        self.cx = self.x + self.W / 2
        self.anchor = ((self.notch[1] + 6) * self.scale if self.island else top + 6 * self.scale) if self.top \
            else bottom - 6 * self.scale
        if self.ns is None:
            self.win.geometry(f"{self.W}x{self.H}+{self.x}+{self.y}")

    def _watch_screen(self):
        if system.work_area() != self.area:  # taskbar moved, resolution or display changed
            self._place()
            self.dirty = True
        self.win.after(3000, self._watch_screen)

    def _hover(self, on):
        self.hovering, self.dirty, self._hover_at = on, True, time.monotonic()
        self._wake()

    def _grab(self):
        """The screen behind the glass, blurred, for its glass (Nova's own windows are left out of it). Everywhere the
        glass can reach, the tallest card included, so growing into a card never has to stop and look again."""
        if system.IS_MAC:
            self.back = None
            return
        half, tall = (GRAB[0] / 2 + 4) * self.scale, (GRAB[1] + 4) * self.scale
        x0, y0 = int(self.cx - half), int(self.anchor if self.top else self.anchor - tall)
        img = glass.backdrop((x0, y0, int(self.cx + half), int(y0 + tall)))
        self.back, self.dirty = ((img, x0, y0) if img is not None else None), True

    def _regrab(self):
        """The same while the bar is on screen and about to move, off the UI thread: the grab takes longer than a frame,
        and the first frame of a change is the one the eye catches. The glass takes the new backdrop when it's ready."""
        threading.Thread(target=self._grab, daemon=True).start()

    def _text_w(self, text):
        return self.f_label.getlength(text) / SS / self.scale

    LABELS = {"idle": "Nova", "paused": "Nova", "listening": "Listening", "thinking": "Thinking…",
              "speaking": "Speaking", "approval": "Needs your OK"}

    def _pill_width(self):
        """The pill's width for this state, logical px: the mark and a word, then what the state adds."""
        tw = lambda text: self.f_label.getlength(text) / SS / self.scale
        state = self.state
        w = 14 + MARK_W + 10 + tw(self.LABELS.get(state, "Nova"))
        if state in ("idle", "paused"):  # [● 12:34] | ✦ Ask   or   | Paused
            rec = (12 + 7 + 6 + tw(self._clock()) if self.recording else 0) + (12 + 9 + 6 + tw(self._left()) if self.timer else 0)
            return max(168, w + rec + 12 + 1 + 8 + (14 + 6 + tw("Ask") if state == "idle" else tw("Paused")) + 14)
        if state == "listening":
            note = self._f_badge().getlength(self.badge.upper()) / SS / self.scale + 12 if self.badge else 0
            return w + 16 + 48 + note + 12 + 24 + 9
        if state == "thinking":
            return w + 12 + 24 + 9
        if state == "speaking":
            return w + 14 + 19 + 8 + 24 + 9
        return w + 14

    def _f_badge(self):
        return mono_font(int(10.5 * self.scale * SS))

    def _clock(self):
        """How long the meeting has been recording: 4:07, or 1:04:07."""
        m, s = divmod(max(0, int(time.time() - self.recording)), 60)
        return f"{m // 60}:{m % 60:02}:{s:02}" if m >= 60 else f"{m}:{s:02}"

    def _left(self):
        """How long until the timer rings: 4:07."""
        m, s = divmod(max(0, math.ceil(self.timer - time.time())), 60)
        return f"{m // 60}:{m % 60:02}:{s:02}" if m >= 60 else f"{m}:{s:02}"

    def _target(self):
        return self.card.size if self.card is not None else (self._pill_width(), CAPSULE)

    def set(self, state):
        if state == "listening" and self.state != "listening":
            self.levels.extend([0.0] * self.levels.maxlen)
        changed, shown = state != self.state, self._vis
        self.state, self.dirty = state, True
        self._apply()  # a working state shows a hidden bar (with a fresh backdrop); going idle hides it again
        if changed and shown and self._vis:
            self._regrab()  # the screen may have changed since the glass was made
        self._wake()

    def _clicked(self, event):
        """On a card, what it says (its buttons, links, stop). On the pill, the mark opens the Nova window and the rest
        is the shortcut (talk, or stop)."""
        g = self._glass
        if g and not (g[0] <= event.x < g[2] and g[1] <= event.y < g[3]):
            return  # the shadow and glow around the glass aren't the bar
        if self.card is not None and self._at:
            return self.card.click(types.SimpleNamespace(x=event.x - self._at[0], y=event.y - self._at[1]))
        if self.on_menu and event.x / (self.scale * self.px) - MARGIN < 14 + MARK_W + 6:
            return self.on_menu()
        self.on_click()

    def _wake(self):
        """Something changed while the bar sat idle (checking only now and then): draw it at once."""
        try:
            self.win.after_cancel(self._job)
            self._job = self.win.after(0, self._tick)
        except Exception:  # not on the UI thread, or no window yet: the next slow check picks it up
            pass

    def level(self, value):
        self.levels.append(value)
        self._heard_at = time.monotonic()

    def _tick(self):
        tw, th = self._target()
        now = time.monotonic()
        gap = now - self._last if self._last else 1 / 60
        dt = self._dt = min(0.05, gap)  # a stale first step after a long rest stays small
        self._last = now
        if system.reduced_motion():
            self.w, self.h, self.vw, self.vh = tw, th, 0.0, 0.0
        else:
            self.w, self.vw = spring(self.w, self.vw, tw, dt)
            self.h, self.vh = spring(self.h, self.vh, th, dt)
        if self.state == "speaking" and now - self._heard_at < 0.3:  # Nova's voice is reporting how loud it is: follow it
            self.said = (self.said or 0.0) + (self.levels[-1] - (self.said or 0.0)) * (1 - math.exp(-dt * 22))
        else:
            self.said = None
        if (self.recording or self.timer) and int(time.time()) != self._sec:  # the recording's clock and the timer tick, at rest too
            self._sec, self.dirty = int(time.time()), True
        moving = abs(tw - self.w) > 0.2 or abs(th - self.h) > 0.2 or abs(self.vw) > 0.5 or abs(self.vh) > 0.5
        moving = moving or self._in_motion(now)
        active = self.dirty or moving or self.state not in ("idle", "paused") or bool(self.card and self.card.live)
        if self._leave is not None and now - self._leave >= FAST:  # the exit has played: now it goes
            self._leave = None
            self._hide()
        if self._vis is False and self._leave is None:  # nothing on screen: nothing to draw until _apply shows it again
            active, self._last = False, None
        if active:
            self._draw()
            self.dirty = False
            self.frames.append((gap, time.monotonic() - now))
        # a bar at rest looks again 4 times a second: it is on screen all day. Alive, it draws 60 times a second: the
        # wait is what is left of a frame after drawing (Windows' timer fires every 15.6 ms, so asking for 33 gave 47)
        spent = (time.monotonic() - now) * 1000
        # shortcut: a Mac encodes a PNG per frame (see _present), so there only a moving glass gets 60; a layer-backed
        # view fed raw pixels would lift that
        frame = FRAME_MS if moving or not system.IS_MAC else 33
        self._job = self.win.after(max(1, int(frame - spent) - 1) if active else 250, self._tick)

    def _in_motion(self, now):
        """An entrance, an exit, a swap, a shake or a hover still playing."""
        return any(at is not None and now - at < span for at, span in (
            (self._born, 0.8), (self._leave, FAST), (self._swap and self._swap[2], QUICK + 0.1), (self._shake, 0.45),
            (self._hover_at, QUICK)))

    def _motion(self, out, x, y, t):
        """The window's own entrance and exit (transitions.dev's toast): in, it fades up from a little above (or below,
        at the bottom), a touch smaller and blurred, over SLOW; out, the same in reverse and quicker (FAST).
        Returns (image, x, y, alpha)."""
        if system.reduced_motion():
            return out, x, y, 255
        if self._leave is not None:
            p = 1 - smooth_out((t - self._leave) / FAST)
        elif self._born is not None:
            p = smooth_out((t - self._born) / SLOW)
        else:
            p = 1.0
        if self._shake is not None:  # an error: a short shake, 80 ms a step (8, 8, 6, 6 px)
            q = (t - self._shake) / 0.08
            steps = (0, -8, 8, -6, 6, 0)
            if q < len(steps) - 1:
                i = int(q)
                x += round((steps[i] + (steps[i + 1] - steps[i]) * (q - i)) * self.scale)
        if p >= 1:
            return out, x, y, 255
        k = self.scale * self.px
        if p < 0.999:
            out = out.filter(ImageFilter.GaussianBlur(BLUR * k * (1 - p)))
            sc = 0.96 + 0.04 * p
            w, h = out.size
            out = out.resize((max(1, round(w * sc)), max(1, round(h * sc))), Image.BILINEAR)
            x += round((w - out.width) / 2 / self.px)
            y += round((h - out.height) / self.px) if not self.top else 0
        y += round((1 - p) * 8 * self.scale * (-1 if self.top else 1))
        return out, x, y, round(255 * p)

    def _draw(self):
        self._glass = None  # set again by _draw_glass; the peek glow takes any click
        s = self.scale * SS
        W, H = self.W * SS, self.H * SS
        if self.peeking:  # just a glow along the screen's top edge, so the pill isn't there until you dwell
            img = _edge_glow(W, H, s, theme.T["accent"])
            glow, x, y, alpha = self._motion(img.resize((self.W * self.px, self.H * self.px), Image.LANCZOS), self.x, self.y,
                                             time.monotonic())
            self._present(glow, x, y, alpha)
            return
        self._draw_glass()

    def _draw_glass(self):
        """One shape of frosted glass: the pill, or the card it grows into. Its size follows a spring toward the
        target; the content comes in once the glass has nearly reached it. The window is the glass plus MARGIN all
        round (for the shadow and the accent's glow), hanging from the anchor."""
        T, state, t = theme.T, self.state, time.monotonic()
        k, card = self.scale * self.px, self.card  # image px per logical px
        tw, th = self._target()
        w, h = max(8.0, self.w), max(8.0, self.h)
        gw, gh, m = round(w * k), round(h * k), round(MARGIN * k)
        W, H = gw + 2 * m, gh + 2 * m
        accent = AMBER if state == "approval" and card is None else T["accent"]
        paused = state == "paused" and card is None
        x = round(self.cx - W / self.px / 2)
        y = round(self.anchor - m / self.px) if self.top else round(self.anchor - (gh + m) / self.px)
        # the glass is made once, at the size it is growing (or shrinking) to, and fitted to each size on the way: its
        # corners stay as drawn, its straight parts stretch. A glass smaller than its own corners (coming out of the
        # glow at the screen's edge) is made as it is
        small = gh < round(min(th, 2 * 21) * k) - 2
        sw, sh = (gw, gh) if small else (round(tw * k), round(th * k))
        r = round(min(sh / 2, 21 * k))
        key = (sw, sh, r, T["tint"], accent, paused, id(self.back))
        if not self._pane or self._pane[0] != key:
            back = None
            if self.back:  # the part of the grabbed screen this glass covers (Windows, where px is 1)
                img, bx, by = self.back
                sx = round(self.cx - sw / self.px / 2) - bx
                sy = round(self.anchor if self.top else self.anchor - sh / self.px) - by
                if sx >= 0 and sy >= 0 and sx + sw <= img.width and sy + sh <= img.height:
                    back = img.crop((sx, sy, sx + sw, sy + sh))
            shell = _halo(sw + 2 * m, sh + 2 * m, m, sw, sh, r, accent).copy()
            shell.alpha_composite(glass.pane(sw, sh, r, T["tint"], accent, back, 150 if paused else glass.OPACITY), (m, m))
            self._pane = key, shell
        out = glass.fit(self._pane[1], W, H, m + r)
        out = out.copy() if out is self._pane[1] else out
        self._glass = (m, m, m + gw, m + gh)
        # how close the glass is to its size, growing or shrinking: the new content comes in near the end
        near = min(min(w, tw) / max(w, tw), min(h, th) / max(h, th)) if tw and th else 1.0
        still = system.reduced_motion()
        key = id(card.base) if card is not None else ("pill", state)
        if key != self._key:  # new content: the old one leaves upward through a blur while the new one rises in
            # pill <-> card: the new content waits for the glass to (nearly) reach its size; card -> card doesn't
            self._gated = self._key is None or isinstance(self._key, tuple) != isinstance(key, tuple)
            if self._last_img is not None and not still and not (card is not None and card.quiet):
                self._swap = (self._last_img, self._last_at, t)
            self._key = key
            if card is not None and card.kind == "error" and not still:
                self._shake = t
        layer = Image.new("RGBA", (gw, gh))
        if self._swap and t - self._swap[2] < QUICK:  # transitions.dev's text states swap: up, blurred, faded
            old, (ox, oy), t0 = self._swap
            q = in_out((t - t0) / QUICK)
            ghost = old.filter(ImageFilter.GaussianBlur(BLUR * k * q)) if q > 0.05 else old
            ghost.putalpha(ghost.getchannel("A").point(lambda v: round(v * (1 - q))))
            self._paste(layer, ghost, ox, oy - round(4 * k * q))
        fade = 1.0 if still or not self._gated else max(0.0, min(1.0, (near - 0.82) / 0.16))
        self._at = None
        swap_in = 1.0 if not self._swap or still else in_out((t - self._swap[2] - 0.05) / QUICK)
        alpha = min(fade, swap_in)
        if alpha > 0:
            content = card.frame(t) if card is not None else self._pill(tw, t)
            ox = (gw - content.width) // 2
            oy = 0 if self.top else gh - content.height
            self._last_img, self._last_at = content, (ox, oy)
            shown = content
            if alpha < 1:  # rising in from 4 px below, its blur clearing
                shown = content.filter(ImageFilter.GaussianBlur(BLUR * k * (1 - alpha)))
                shown.putalpha(shown.getchannel("A").point(lambda v: round(v * alpha)))
            self._paste(layer, shown, ox, oy + round(4 * k * (1 - alpha)))
            self._at = (m + ox, m + oy)
        layer.putalpha(ImageChops.multiply(layer.getchannel("A"), glass.fit(glass.mask(sw, sh, r), gw, gh, r)))  # inside the glass
        out.alpha_composite(layer, (m, m))
        out, x, y, a = self._motion(out, x, y, t)
        self._present(out, x, y, a)

    @staticmethod
    def _paste(layer, img, ox, oy):
        """`img` onto `layer` with its top-left at (ox, oy), cropped where it hangs over."""
        layer.alpha_composite(img, (max(0, ox), max(0, oy)), (max(0, -ox), max(0, -oy)))

    def _pill(self, tw, t):
        """The pill's content at its full width, in image px: the mark and a word, then what the state adds."""
        T, state = theme.T, self.state
        s = self.scale * SS
        img = Image.new("RGBA", (round(tw * s), round(CAPSULE * s)))
        d = ImageDraw.Draw(img)
        cy, x, right = CAPSULE / 2 * s, 14 * s, tw * s
        colors = [AMBER] * 5 if state == "approval" else [GREY] * 5 if state == "paused" else None
        for i, lv in enumerate(list(self.levels)[-8:]):  # the microphone, eased so it doesn't jitter
            aim = min(1.0, lv * 1.5)
            self.shown[i] += (aim - self.shown[i]) * (1 - math.exp(-self._dt * (40 if aim > self.shown[i] else 9)))  # up fast, down slow
        bands = [max(self.shown[j], self.shown[j + 1]) for j in (0, 2, 3, 5, 6)]
        x += mark(img, x, cy, s, 1, colors, state, t, self._born, bands) + 10 * s
        label = self.LABELS.get(state, "Nova")
        still = system.reduced_motion()
        if state == "thinking":
            shimmer(img, x, cy, label, self.f_label, 1, t, still)
        else:
            lit = in_out((t - self._hover_at) / QUICK)  # hovering lifts "Nova" from 50% to 80% white, over 150 ms
            lit = lit if self.hovering else 1 - lit
            alpha = 255 if state == "approval" else 204 if state in ("listening", "speaking") else round(128 + 76 * lit)
            d.text((x, cy), label, font=self.f_label, fill=(AMBER if state == "approval" else WHITE) + (alpha,), anchor="lm")
        x += self.f_label.getlength(label)
        if state in ("idle", "paused") and self.recording:  # a meeting is being recorded: a red dot and how long
            d.ellipse((x + 12 * s, cy - 3.5 * s, x + 19 * s, cy + 3.5 * s), fill=(229, 72, 77, 255))
            d.text((x + 25 * s, cy), self._clock(), font=self.f_label, fill=WHITE + (204,), anchor="lm")
            x += (7 + 6 + 12) * s + self.f_label.getlength(self._clock())
        if state in ("idle", "paused") and self.timer:  # a timer is running: a small dial and what is left
            ring = (x + 12 * s, cy - 4.5 * s, x + 21 * s, cy + 4.5 * s)
            d.ellipse(ring, outline=T["light"] + (255,), width=max(1, round(1.4 * s)))
            d.line((x + 16.5 * s, cy, x + 16.5 * s, cy - 3 * s), fill=T["light"] + (255,), width=max(1, round(1.4 * s)))
            d.text((x + 27 * s, cy), self._left(), font=self.f_label, fill=WHITE + (204,), anchor="lm")
        if state in ("idle", "paused"):  # a hairline, then ✦ Ask (or Paused) at the right
            word = "Ask" if state == "idle" else "Paused"
            group = self.f_label.getlength(word) + ((14 + 6) * s if state == "idle" else 0)
            left = right - 14 * s - group
            d.line((left - 9 * s, cy - 8 * s, left - 9 * s, cy + 8 * s), fill=WHITE + (26,), width=max(1, round(s / SS)))
            if state == "idle":
                self._sparkle(d, left + 7 * s, cy, 7 * s, T["accent"])
                left += 20 * s
            d.text((left, cy), word, font=self.f_label, fill=WHITE + (217 if state == "idle" else 128,), anchor="lm")
        elif state == "listening":  # eight bars, following the microphone
            floor = (0.35, 0.6, 0.45, 0.7, 0.4, 0.6, 0.5, 0.3)  # a resting shape, so silence still reads as listening
            heights = [(4 + 16 * max(f * 0.35, v)) * s for f, v in zip(floor, self.shown[:8])]
            wave(img, x + 16 * s, cy, heights, 2.5 * s, 4 * s, T["accent"])
            if self.badge:  # which mode is listening, and whose tone: quiet mono caps
                d.text((x + (16 + 48 + 12) * s, cy), self.badge.upper(), font=self._f_badge(), fill=WHITE + (128,), anchor="lm")
        elif state == "speaking":  # four bars, like a voice
            heights = [(0.5 if still else voice(t, i, self.said)) * 12 * s for i in range(4)]
            wave(img, x + 14 * s, cy, heights, 2.5 * s, 3 * s, T["accent"])
        if state in ("listening", "thinking", "speaking"):  # stop, with no frame around it
            stop_square(d, right - 21 * s, cy, s, 5 * s)
        return img.reduce(SS) if self.px == 1 else img.resize((round(tw * self.scale * self.px), round(CAPSULE * self.scale * self.px)), Image.LANCZOS)

    @staticmethod
    def _sparkle(d, cx, cy, r, color):
        """A four-pointed star, with a small one beside it: the mark of asking."""
        def star(x, y, r):
            n = r * .26
            d.polygon([(x, y - r), (x + n, y - n), (x + r, y), (x + n, y + n), (x, y + r), (x - n, y + n), (x - r, y),
                       (x - n, y - n)], fill=color + (255,))
        star(cx - r * .2, cy + r * .1, r * .85)
        star(cx + r * .75, cy - r * .7, r * .38)
