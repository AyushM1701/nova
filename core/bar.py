"""Flow Bar: a small pill on screen, like Wispr Flow's.

Idle it is a quiet pill with standby dots; hovering it shows how to talk, it grows with a live waveform while
you speak, shows a travelling wave while Nova thinks, a voice waveform while it talks, and turns amber when it
needs your OK. Click it to talk, right-click it to open the Nova window.

It sits at the bottom centre (above the taskbar or Dock), or at the top: on a MacBook with a notch it hangs
from the notch and grows out of it, like the Dynamic Island. Drawn with per-pixel alpha so the edges stay
smooth: a layered window on Windows, a native borderless window on macOS (sharp on Retina, never takes
focus, and clicks pass through its transparent parts).
"""
import collections
import ctypes
import io
import math
import time
import tkinter as tk

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core import system

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
BOX = (300, 48)  # window size in logical px (bottom position); the pill is drawn inside it
SIZES = {"idle": (64, 14), "paused": (64, 14), "listening": (156, 36), "thinking": (92, 30),
         "speaking": (124, 30), "approval": (92, 30), "hover": (0, 30)}  # hover width fits its text
WHITE, AMBER, DIM, VIOLET = (255, 255, 255), (255, 186, 60), (190, 193, 214), (123, 109, 255)
LIGHT = {False: (169, 161, 255), True: AMBER}  # the thinking dots: light violet, or amber when Nova needs you


def _font(px, names=("segoeui.ttf", "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc")):
    for name in names:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            pass
    return ImageFont.load_default(px)


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
        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        return win

    def _init_mac(self, level):
        self.px = int(NSScreen.mainScreen().backingScaleFactor() or 2)
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
            old = gdi32.SelectObject(self.mem_dc, dib)
            if self._size:
                gdi32.DeleteObject(old)
            self._size = img.size
        px = np.asarray(img, dtype=np.uint16)
        rgb = px[..., :3] * px[..., 3:4] // 255  # Windows wants premultiplied BGRA
        bgra = np.dstack((rgb[..., 2], rgb[..., 1], rgb[..., 0], px[..., 3])).astype(np.uint8)
        ctypes.memmove(self.bits, bgra.tobytes(), bgra.nbytes)
        user32.UpdateLayeredWindow(self.hwnd, self.screen_dc, ctypes.byref(w.POINT(x, y)),
                                   ctypes.byref(w.SIZE(*img.size)), self.mem_dc, ctypes.byref(w.POINT(0, 0)),
                                   0, ctypes.byref(BLENDFUNCTION(0, 0, alpha, 1)), 2)  # AC_SRC_ALPHA, ULW_ALPHA

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
    def __init__(self, root, on_click, on_menu=None, hint="", position="bottom"):
        self.scale = dpi_scale(root)
        self.hint, self.font, self.hovering = hint, _font(int(12 * self.scale * SS)), False
        self.area, self.top = None, position == "top"
        self.notch = system.notch()  # (width, height) of a MacBook's notch, or (0, 0)
        target = self._init_surface(root, level=25)  # macOS: above full-screen apps and the menu bar
        self._place()
        target.bind("<Button-1>", lambda _: on_click())
        if on_menu:
            target.bind("<Button-3>", lambda _: on_menu())
            target.bind("<Button-2>", lambda _: on_menu())  # right button on macOS Tk
        target.bind("<Enter>", lambda _: self._hover(True))
        target.bind("<Leave>", lambda _: self._hover(False))

        self.state, self.levels = "idle", collections.deque([0.0] * 15, maxlen=15)
        self.shown = [0.0] * 15  # the drawn bar heights, eased toward the live levels
        self.w, self.h = self._target()
        self.dirty = True
        self._show()
        self._tick()
        self._watch_screen()

    @property
    def island(self):
        """Hanging from a MacBook notch (top position on a notched screen)."""
        return self.top and self.notch[1] > 0

    def set_position(self, position):
        if (position == "top") != self.top:
            self.top, self.dirty = position == "top", True
            self._place()

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
        if self.ns is None:
            self.win.geometry(f"{self.W}x{self.H}+{self.x}+{self.y}")

    def _watch_screen(self):
        if system.work_area() != self.area:  # taskbar moved, resolution or display changed
            self._place()
            self.dirty = True
        self.win.after(3000, self._watch_screen)

    def _hover(self, on):
        self.hovering, self.dirty = on, True

    def _target(self):
        if self.state == "idle" and self.hovering and self.hint:
            text_w = self.font.getlength(self.hint) / SS / self.scale
            w, h = min(BOX[0] - 12, text_w + 28), SIZES["hover"][1]
        else:
            w, h = SIZES[self.state]
        if self.island:  # grows out of the notch: at least as wide, content below it
            nw, nh = self.notch
            return (nw, nh) if self.state in ("idle", "paused") and not self.hovering else (max(nw, w + 24), nh + h + 6)
        return w, h

    def set(self, state):
        if state == "listening" and self.state != "listening":
            self.levels.extend([0.0] * self.levels.maxlen)
        self.state, self.dirty = state, True

    def level(self, value):
        self.levels.append(value)

    def _tick(self):
        tw, th = self._target()
        self.w += (tw - self.w) * 0.3
        self.h += (th - self.h) * 0.3
        moving = abs(tw - self.w) > 0.2 or abs(th - self.h) > 0.2
        if self.dirty or moving or self.state not in ("idle", "paused"):
            self._draw()
            self.dirty = False
        self.win.after(33, self._tick)

    def _draw(self):
        s = self.scale * SS
        W, H = self.W * SS, self.H * SS
        img = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(img)
        pw, ph = self.w * s, self.h * s
        x0 = (W - pw) / 2
        if self.island:
            y0 = 0
        elif self.top:
            y0 = 6 * s
        else:
            y0 = H - 6 * s - ph
        y1 = y0 + ph
        corners = (False, False, True, True) if self.island else None  # flat top where it meets the notch
        state, t = self.state, time.monotonic()
        idle = state in ("idle", "paused")
        tint = AMBER if state == "approval" else VIOLET
        glow = {"listening": 0.55, "thinking": 0.35 + 0.25 * math.sin(t * 2.4), "approval": 0.45 + 0.3 * math.sin(t * 3)}
        if state in glow:  # a soft halo: mic is live, Nova is working, or it needs you
            for i, spread in enumerate((5, 3.2, 1.6)):
                g = spread * s
                d.rounded_rectangle((x0 - g, y0 - (0 if self.island else g), x0 + pw + g, y1 + g), radius=ph / 2 + g,
                                    corners=corners, outline=tint + (int(glow[state] * (40 + 35 * i)),),
                                    width=max(1, round(1.4 * s)))
        if self.island:  # pure black, so it reads as part of the notch
            d.rounded_rectangle((x0, y0, x0 + pw, y1), radius=min(ph / 2, 14 * s), corners=corners, fill=(0, 0, 0, 255))
        else:
            d.rounded_rectangle((x0, y0, x0 + pw, y1), radius=ph / 2,
                                fill=(13, 15, 26, 150 if state == "paused" else 238),
                                outline=(tint if state in ("approval", "thinking") else WHITE)
                                + ((90 if state == "paused" else 120 if idle else 215),),
                                width=max(1, round(1.4 * s)))
        top_of_content = y0 + (self.notch[1] * s if self.island else 0)
        cx, cy = W / 2, (top_of_content + y1) / 2
        inner = min(ph, y1 - top_of_content) - 12 * s
        target_w = self._target()[0]
        if idle and self.hovering and self.hint and pw >= 0.92 * target_w * s:
            d.text((cx, cy), self.hint, font=self.font, fill=DIM + (255,), anchor="mm")
        elif idle and (pw < 0.92 * target_w * s or self.island):
            pass  # still changing size; in the notch, standby is simply the notch itself
        elif idle:  # standby: five faint dots, so the pill reads as Nova and not an empty field
            for i in range(5):
                r, x = 1.1 * s, cx + (i - 2) * 6.5 * s
                d.ellipse((x - r, cy - r, x + r, cy + r), fill=WHITE + (70 if state == "paused" else 105,))
        elif pw < 0.85 * target_w * s:
            pass
        elif state == "listening":  # the voice level, tallest in the middle, smoothed so it doesn't jitter
            n = len(self.levels)
            for i, lv in enumerate(self.levels):
                aim = min(1.0, lv * 1.5) * (0.45 + 0.55 * math.sin(math.pi * (i + 0.5) / n))
                self.shown[i] += (aim - self.shown[i]) * (0.6 if aim > self.shown[i] else 0.22)
            self._bars(d, cx, cy, s, [v * inner for v in self.shown], 3 * s)
        elif state == "speaking":  # two layered waves, like a voice rather than a metronome
            heights = [(0.25 + 0.75 * abs(0.6 * math.sin(t * 4.2 + i * 0.55) + 0.4 * math.sin(t * 7.1 + i * 1.3)))
                       * (0.5 + 0.5 * math.sin(math.pi * (i + 0.5) / 9)) * inner for i in range(9)]
            self._bars(d, cx, cy, s, heights, 3 * s)
        else:  # thinking / approval: three dots in a travelling wave
            for i in range(3):
                phase = t * 5.2 - i * 0.75
                lift, a = max(0.0, math.sin(phase)) * 3.2 * s, 0.55 + 0.45 * max(0.0, math.sin(phase))
                r, x = 2.4 * s, cx + (i - 1) * 9 * s
                d.ellipse((x - r, cy - r - lift, x + r, cy + r - lift), fill=LIGHT[state == "approval"] + (int(255 * a),))

        self._present(img.resize((self.W * self.px, self.H * self.px), Image.LANCZOS), self.x, self.y)

    @staticmethod
    def _bars(d, cx, cy, s, heights, bw):
        gap = 4 * s
        x = cx - (len(heights) * (bw + gap) - gap) / 2
        for hh in heights:
            hh = max(bw, hh)
            d.rounded_rectangle((x, cy - hh / 2, x + bw, cy + hh / 2), radius=bw / 2, fill=WHITE + (240,))
            x += bw + gap
