"""Flow Bar: a small pill at the bottom-centre of the screen, like Wispr Flow's.

Idle it is a quiet outlined pill; it grows with a live waveform while you speak, pulses while Nova
thinks, ripples while it talks and turns amber when it needs your OK. Drawn with per-pixel alpha
(a layered window on Windows, a transparent window on macOS) so the rounded edges stay smooth.
"""
import collections
import ctypes
import math
import time
import tkinter as tk

import numpy as np
from PIL import Image, ImageDraw

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
    user32.UpdateLayeredWindow.argtypes = [w.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, w.DWORD]

SS = 3  # draw 3x larger, then downscale: anti-aliased edges
BOX = (180, 48)  # window size in logical px; the pill is drawn inside it, anchored to the bottom
SIZES = {"idle": (64, 14), "paused": (64, 14), "listening": (156, 36), "thinking": (92, 30),
         "speaking": (124, 30), "approval": (92, 30)}
WHITE, AMBER = (255, 255, 255), (255, 186, 60)


if not system.IS_MAC:
    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG), ("biPlanes", w.WORD),
                    ("biBitCount", w.WORD), ("biCompression", w.DWORD), ("biSizeImage", w.DWORD),
                    ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD),
                    ("biClrImportant", w.DWORD)]


class Bar:
    def __init__(self, root, on_click):
        # Tk on macOS works in points (72 per inch); Windows reports real DPI once the process is DPI-aware
        self.scale = 1.0 if system.IS_MAC else root.winfo_fpixels("1i") / 96
        self.W, self.H = int(BOX[0] * self.scale), int(BOX[1] * self.scale)
        left, _, right, bottom = system.work_area()
        self.x, self.y = int((left + right - self.W) / 2), int(bottom - self.H)

        win = self.win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"{self.W}x{self.H}+{self.x}+{self.y}")
        if system.IS_MAC:  # transparent Tk window showing the rendered pill
            from PIL import ImageTk
            self._tk_image = ImageTk.PhotoImage
            win.attributes("-transparent", True)
            win.config(bg="systemTransparent")
            self.label = tk.Label(win, bg="systemTransparent", borderwidth=0, highlightthickness=0)
            self.label.pack()
            self.label.bind("<Button-1>", lambda _: on_click())
        else:  # per-pixel-alpha layered window; fully transparent pixels let clicks through
            win.bind("<Button-1>", lambda _: on_click())
            self._init_layered()

        self.state, self.levels = "idle", collections.deque([0.0] * 15, maxlen=15)
        self.w, self.h = SIZES["idle"]
        self.dirty = True
        self._tick()

    def _init_layered(self):
        self.hwnd = system.no_activate(self.win, layered=True)
        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        header = BITMAPINFOHEADER(40, self.W, -self.H, 1, 32, 0, 0, 0, 0, 0, 0)  # top-down 32-bit
        self.bits = ctypes.c_void_p()
        dib = gdi32.CreateDIBSection(self.screen_dc, ctypes.byref(header), 0, ctypes.byref(self.bits), None, 0)
        gdi32.SelectObject(self.mem_dc, dib)

    def _present(self, img):
        if system.IS_MAC:
            self.photo = self._tk_image(img)  # keep a reference or Tk drops the image
            self.label.config(image=self.photo)
            return
        px = np.asarray(img, dtype=np.uint16)
        rgb = px[..., :3] * px[..., 3:4] // 255  # Windows wants premultiplied BGRA
        bgra = np.dstack((rgb[..., 2], rgb[..., 1], rgb[..., 0], px[..., 3])).astype(np.uint8)
        ctypes.memmove(self.bits, bgra.tobytes(), bgra.nbytes)
        user32.UpdateLayeredWindow(self.hwnd, self.screen_dc, ctypes.byref(w.POINT(self.x, self.y)),
                                   ctypes.byref(w.SIZE(self.W, self.H)), self.mem_dc, ctypes.byref(w.POINT(0, 0)),
                                   0, ctypes.byref(BLENDFUNCTION(0, 0, 255, 1)), 2)  # AC_SRC_ALPHA, ULW_ALPHA

    def set(self, state):
        if state == "listening" and self.state != "listening":
            self.levels.extend([0.0] * self.levels.maxlen)
        self.state, self.dirty = state, True

    def level(self, value):
        self.levels.append(value)

    def _tick(self):
        tw, th = SIZES[self.state]
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
        x0, y1 = (W - pw) / 2, H - 6 * s
        y0 = y1 - ph
        state, t = self.state, time.monotonic()
        idle = state in ("idle", "paused")
        edge = AMBER if state == "approval" else WHITE
        d.rounded_rectangle((x0, y0, x0 + pw, y1), radius=ph / 2,
                            fill=(16, 16, 20, 150 if state == "paused" else 235),
                            outline=edge + ((120 if state == "paused" else 175 if idle else 225),),
                            width=max(1, round(1.5 * s)))
        cx, cy, inner = W / 2, (y0 + y1) / 2, ph - 12 * s
        if idle or pw < 0.85 * SIZES[state][0] * s:
            pass  # still growing: draw the content once there is room
        elif state == "listening":
            self._bars(d, cx, cy, s, [min(1.0, lv * 1.6) * inner for lv in self.levels], 3 * s)
        elif state == "speaking":
            heights = [(0.2 + 0.8 * abs(math.sin(t * 5 + i * 0.7))) * inner * 0.8 for i in range(11)]
            self._bars(d, cx, cy, s, heights, 3 * s)
        else:  # thinking / approval: three pulsing dots
            for i in range(3):
                a = 0.5 + 0.5 * math.sin(t * 6 - i * 0.9)
                r, x = (2.0 + 1.3 * a) * s, cx + (i - 1) * 10 * s
                d.ellipse((x - r, cy - r, x + r, cy + r), fill=edge + (int(110 + 145 * a),))

        self._present(img.resize((self.W, self.H), Image.LANCZOS))

    @staticmethod
    def _bars(d, cx, cy, s, heights, bw):
        gap = 4 * s
        x = cx - (len(heights) * (bw + gap) - gap) / 2
        for hh in heights:
            hh = max(bw, hh)
            d.rounded_rectangle((x, cy - hh / 2, x + bw, cy + hh / 2), radius=bw / 2, fill=WHITE + (240,))
            x += bw + gap
