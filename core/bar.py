"""Flow Bar: a small pill on screen, like Wispr Flow's.

Idle it is a quiet pill with standby dots; hovering it shows how to talk, it grows with a live waveform while
you speak, shows a travelling wave while Nova thinks, a voice waveform while it talks, and turns amber when it
needs your OK. Click it to talk, right-click it to open the Nova window.

It sits at the top centre, out of sight until the pointer rests at the top edge (or Nova is working); or at the
bottom centre (above the taskbar or Dock), always visible. On a MacBook with a notch it hangs from the notch and
grows out of it, like the Dynamic Island. Drawn with per-pixel alpha so the edges stay
smooth: a layered window on Windows, a native borderless window on macOS (sharp on Retina, never takes
focus, and clicks pass through its transparent parts).
"""
import collections
import functools
import ctypes
import io
import math
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont

from core import glass, icon, system, theme

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
SIZES = {"idle": (64, 14), "paused": (64, 14), "listening": (156, 36), "thinking": (92, 30),
         "speaking": (124, 30), "approval": (92, 30), "hover": (0, 30)}  # the notch island's; the capsule works its own out
CAPSULE = 42  # the capsule's height, logical px: an orb, the action button and (while working) a stop button inside it
ORB, PAD, GAP = 32, 5, 6  # the orb and buttons are ORB across, PAD from the edge, GAP apart
WHITE, AMBER, DIM, INK = (255, 255, 255), (255, 186, 60), (190, 193, 214), (11, 13, 26)
LIGHT = {False: (169, 161, 255), True: AMBER}  # the thinking dots: light violet, or amber when Nova needs you


@functools.lru_cache(maxsize=4)
def _logo(size):
    """The bars of Nova's icon at `size` px (drawing pixels), drawn once."""
    return icon.draw(size, tile=False)


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


def spring(x, v, target, dt, k=420.0, damping=0.8):
    """One step of a damped spring toward `target`, so motion depends on real elapsed time and not on the frame rate
    (damping 1 settles without overshoot; 0.8 gives a slight Dynamic-Island bounce). Steps of at most 1/120 s."""
    c, steps = 2 * damping * math.sqrt(k), max(1, math.ceil(dt * 120))
    h = dt / steps
    for _ in range(steps):
        v += (k * (target - x) - c * v) * h
        x += v * h
    return x, v


def visible(state, card, stage, reveal, top):
    """Whether the bar is on screen: while a card hangs under it; always at the bottom (the edge belongs to the
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
    reveal, stage, covered, suppressed, _vis, _thru = "always", "hidden", False, False, None, False
    vw, vh, _last = 0.0, 0.0, None  # the pill's size velocities, and when it was last stepped
    back, _pane = None, None  # the blurred screen behind the bar, for its glass; and the last pane made

    def __init__(self, root, on_click, on_menu=None, hint="", position="bottom", reveal="always"):
        self.scale = dpi_scale(root)
        self.hint, self.font, self.hovering = hint, _font(int(12 * self.scale * SS)), False
        self.f_label = _font(int(12.5 * self.scale * SS), SEMIBOLD)
        self.area, self.top = None, position == "top"
        self.reveal = "always" if system.IS_MAC else reveal  # the notch island stays; hover-reveal is Windows for now
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

    def cover(self, on):
        """A card hangs under the pill: the pill stays on screen, open (orb and Ask), until the card goes."""
        self.covered = on
        self._apply()

    def pill_size(self):
        """The pill the card grows from and shrinks back to, in screen pixels: (width, height, top y, centre x)."""
        w, h = self._target()
        return w * self.scale, h * self.scale, self.y + 6 * self.scale, self.x + self.W / 2

    @property
    def peeking(self):
        """The hairline glow at the top edge: the pointer is there, the pill isn't open yet."""
        return self.stage == "peek" and self.state in ("idle", "paused") and self.reveal == "hover" and self.top

    def _apply(self):
        """Show or hide the window as `visible` says, and let clicks through only while it is just the glow."""
        want = visible(self.state, self.covered, self.stage, self.reveal, self.top)
        if want != self._vis:
            self._vis = want
            if want:
                self._grab()  # before the window appears: its glass is what is behind it
            self._show() if want else self._hide()
            if want:
                self.dirty = True
                self._wake()
        through = want and self.peeking
        if through != self._thru:
            self._thru = through
            self._click_through(through)

    def _zone(self):
        """The hot zone: the top 2 px of the screen (of the work area, with a taskbar on top), 440 px wide at the middle."""
        half = 220 * self.scale
        return (self.x + self.W / 2 - half, 0, self.x + self.W / 2 + half, self.area[1] + 2)

    def _keep(self):
        """Where an open pill stays open: the zone down to a little below the pill."""
        left, _, right, _ = self._zone()
        return (left, 0, right, self.y + (6 + self.h) * self.scale + 24 * self.scale)

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
        if self.ns is None:
            self.win.geometry(f"{self.W}x{self.H}+{self.x}+{self.y}")

    def _watch_screen(self):
        if system.work_area() != self.area:  # taskbar moved, resolution or display changed
            self._place()
            self.dirty = True
        self.win.after(3000, self._watch_screen)

    def _hover(self, on):
        self.hovering, self.dirty = on, True
        self._wake()

    def _expanded(self):
        """The idle pill opens into the capsule while the pointer is on it, or when it has just opened at the top edge."""
        return self.state == "idle" and (self.hovering or self.covered or self.stage == "open" and self.reveal == "hover")

    def _hint_on(self):
        return self._expanded() and bool(self.hint)

    def _grab(self):
        """The screen behind the bar, blurred, for its glass (Nova's own windows are left out of it)."""
        self.back = None if self.island or system.IS_MAC else glass.backdrop((self.x, self.y, self.x + self.W, self.y + self.H))

    def _text_w(self, text):
        return self.f_label.getlength(text) / SS / self.scale

    def _parts(self):
        """What the capsule holds in this state: {"label", "btn" (the action button's width), "stop"}; None for the quiet
        standby pill. Click the orb for the Nova window, the rest to talk (or, while Nova works, to stop it)."""
        state = self.state
        if state == "idle":
            return {"label": "Ask", "btn": 15 + GAP + self._text_w("Ask") + 32, "stop": False} if self._expanded() else None
        if state in ("listening", "speaking"):
            return {"label": "", "btn": 96, "stop": True}
        if state == "thinking":
            return {"label": "Thinking", "btn": 20 + GAP + self._text_w("Thinking") + 32, "stop": True}
        if state == "approval":
            return {"label": "Needs OK", "btn": self._text_w("Needs OK") + 32, "stop": False}
        return None  # paused

    def _target(self):
        if not self.island:
            parts = self._parts()
            if not parts:
                return SIZES["idle"]
            return PAD + ORB + GAP + parts["btn"] + (GAP + ORB if parts["stop"] else 0) + PAD, CAPSULE
        if self._hint_on():
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
        changed = state != self.state
        self.state, self.dirty = state, True
        self._apply()  # a working state shows a hidden bar; going idle hides it again
        if changed and self._vis:
            self._grab()  # the screen may have changed since the glass was made
        self._wake()

    def _clicked(self, event):
        """The orb opens the Nova window; the rest of the capsule is the shortcut (talk, or stop)."""
        left = (BOX[0] - self.w) / 2
        if self.on_menu and self._parts() and event.x / (self.scale * self.px) < left + PAD + ORB + GAP / 2:
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

    def _tick(self):
        tw, th = self._target()
        now = time.monotonic()
        dt = min(0.05, now - self._last) if self._last else 1 / 60  # a stale first step after a long rest stays small
        self._last = now
        if system.reduced_motion():
            self.w, self.h, self.vw, self.vh = tw, th, 0.0, 0.0
        else:
            self.w, self.vw = spring(self.w, self.vw, tw, dt)
            self.h, self.vh = spring(self.h, self.vh, th, dt)
        moving = abs(tw - self.w) > 0.2 or abs(th - self.h) > 0.2 or abs(self.vw) > 0.5 or abs(self.vh) > 0.5
        active = self.dirty or moving or self.state not in ("idle", "paused")
        if self._vis is False:  # nothing on screen: nothing to draw until _apply shows it again
            active, self._last = False, None
        if active:
            self._draw()
            self.dirty = False
        # a bar at rest looks again 4 times a second, not 30: it is on screen all day; moving, it follows the display
        self._job = self.win.after(16 if moving and active else 33 if active else 250, self._tick)

    def _draw(self):
        s = self.scale * SS
        W, H = self.W * SS, self.H * SS
        img = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(img)
        if self.peeking:  # just a glow along the screen's top edge, so the pill isn't there until you dwell
            line = 32 * s
            for i, spread in enumerate((6, 4, 2)):
                g = spread * s
                d.rounded_rectangle((W / 2 - line - g, -g, W / 2 + line + g, 3 * s + g), radius=(3 * s + 2 * g) / 2,
                                    fill=theme.T["accent"] + (30 + 25 * i,))
            d.rounded_rectangle((W / 2 - line, 0, W / 2 + line, 3 * s), radius=1.5 * s, fill=theme.T["accent"] + (255,))
            self._present(img.resize((self.W * self.px, self.H * self.px), Image.LANCZOS), self.x, self.y)
            return
        if not self.island:
            return self._draw_capsule(img, d)
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
        tint = AMBER if state == "approval" else theme.T["accent"]
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
        if idle and self._hint_on() and pw >= 0.92 * target_w * s:
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

        # an exact box filter is several times faster than LANCZOS, and as smooth for a whole-number reduction
        self._present(img.reduce(SS) if self.px == 1 else img.resize((self.W * self.px, self.H * self.px), Image.LANCZOS),
                      self.x, self.y)

    def _draw_capsule(self, img, d):
        """The glass capsule: an orb, the action button in the accent colour, and a stop button while Nova works. The
        glass is made at screen resolution and the drawing (at 3x, for smooth edges) goes on top."""
        T, state, t = theme.T, self.state, time.monotonic()
        s, k = self.scale * SS, self.scale * self.px  # drawing px, and screen px, per logical px
        W, H = self.W * SS, self.H * SS
        pw, ph = self.w * s, self.h * s
        x0 = (W - pw) / 2
        y0 = 6 * s if self.top else H - 6 * s - ph
        y1, cy = y0 + ph, y0 + ph / 2
        accent = AMBER if state == "approval" else T["accent"]
        glow = {"listening": 0.55, "thinking": 0.35 + 0.25 * math.sin(t * 2.4), "approval": 0.45 + 0.3 * math.sin(t * 3)}
        if state in glow:  # a soft halo: mic is live, Nova is working, or it needs you
            for i, spread in enumerate((5, 3.2, 1.6)):
                g = spread * s
                d.rounded_rectangle((x0 - g, y0 - g, x0 + pw + g, y1 + g), radius=ph / 2 + g,
                                    outline=accent + (int(glow[state] * (40 + 35 * i)),), width=max(1, round(1.4 * s)))
        parts, target_w = self._parts(), self._target()[0]
        if pw < 0.85 * target_w * s:
            pass  # still opening: the glass alone
        elif not parts:  # standby: five faint dots, so the pill reads as Nova and not an empty field
            for i in range(5):
                r, x = 1.1 * s, W / 2 + (i - 2) * 6.5 * s
                d.ellipse((x - r, cy - r, x + r, cy + r), fill=WHITE + (70 if state == "paused" else 115,))
        else:
            self._orb(img, d, x0 + (PAD + ORB / 2) * s, cy, ORB / 2 * s, s, state != "idle")
            b0 = x0 + (PAD + ORB + GAP) * s
            b1 = b0 + parts["btn"] * s
            box = (b0, cy - ORB / 2 * s, b1, cy + ORB / 2 * s)
            if state in ("listening", "approval"):  # the accent says "live mic"; amber says "needs you"
                ink = INK if state == "approval" else T["ink"]
                d.rounded_rectangle(box, radius=ORB / 2 * s, fill=accent + (255,), outline=WHITE + (70,), width=max(1, round(s)))
            else:  # a lighter well of the same glass, like a key on it
                ink = T["text"]
                self._well(d, box, s)
            mid = (b0 + b1) / 2
            if state == "idle":
                label_w = self._text_w(parts["label"]) * s
                left = mid - (15 * s + GAP * s + label_w) / 2
                self._sparkle(d, left + 7.5 * s, cy, 7.5 * s, T["light"])
                d.text((left + (13 + GAP) * s, cy), parts["label"], font=self.f_label, fill=ink + (255,), anchor="lm")
            elif state == "thinking":
                label_w = self._text_w(parts["label"]) * s
                left = mid - (20 * s + GAP * s + label_w) / 2
                for i in range(3):
                    phase = t * 5.2 - i * 0.75
                    r, x = 1.9 * s, left + (3 + i * 7) * s
                    lift = max(0.0, math.sin(phase)) * 2.4 * s
                    alpha = int(255 * (0.55 + 0.45 * max(0.0, math.sin(phase))))
                    d.ellipse((x - r, cy - r - lift, x + r, cy + r - lift), fill=T["light"] + (alpha,))
                d.text((left + (20 + GAP) * s, cy), parts["label"], font=self.f_label, fill=ink + (255,), anchor="lm")
            elif state == "approval":
                d.text((mid, cy), parts["label"], font=self.f_label, fill=ink + (255,), anchor="mm")
            elif state == "listening":  # the voice level, tallest in the middle, smoothed so it doesn't jitter
                n, inner = len(self.levels), (ORB - 10) * s
                for i, lv in enumerate(self.levels):
                    aim = min(1.0, lv * 1.5) * (0.45 + 0.55 * math.sin(math.pi * (i + 0.5) / n))
                    self.shown[i] += (aim - self.shown[i]) * (0.6 if aim > self.shown[i] else 0.22)
                self._bars(d, mid, cy, s, [v * inner for v in self.shown], 2.4 * s, ink)
            elif state == "speaking":  # two layered waves, like a voice rather than a metronome
                inner = (ORB - 10) * s
                heights = [(0.25 + 0.75 * abs(0.6 * math.sin(t * 4.2 + i * 0.55) + 0.4 * math.sin(t * 7.1 + i * 1.3)))
                           * (0.5 + 0.5 * math.sin(math.pi * (i + 0.5) / 9)) * inner for i in range(9)]
                self._bars(d, mid, cy, s, heights, 2.4 * s, ink)
            if parts["stop"]:
                sx = b1 + (GAP + ORB / 2) * s
                self._well(d, (sx - ORB / 2 * s, cy - ORB / 2 * s, sx + ORB / 2 * s, cy + ORB / 2 * s), s)
                q = 4.6 * s
                d.rounded_rectangle((sx - q, cy - q, sx + q, cy + q), radius=1.6 * s, fill=WHITE + (240,))
        content = img.reduce(SS) if self.px == 1 else img.resize((self.W * self.px, self.H * self.px), Image.LANCZOS)
        out = Image.new("RGBA", content.size)
        gw, gh = round(self.w * k), round(self.h * k)
        gx = round((content.width - gw) / 2)
        gy = round(6 * k) if self.top else round(content.height - 6 * k - gh)
        # the pane changes only with its size, colour or backdrop: not with each frame of a waveform
        key = (gw, gh, gx, gy, T["tint"], accent, state == "paused", id(self.back))
        if not self._pane or self._pane[0] != key:
            back = self.back.crop((gx, gy, gx + gw, gy + gh)) if self.back and self.back.size == content.size else None
            self._pane = key, glass.pane(gw, gh, gh // 2, T["tint"], accent, back, 150 if state == "paused" else glass.OPACITY)
        out.alpha_composite(self._pane[1], (gx, gy))
        out.alpha_composite(content)
        self._present(out, self.x, self.y)

    @staticmethod
    def _well(d, box, s):
        """A lighter pocket of the glass (round ends): the orb, the action button and the stop button sit in one."""
        light = theme.T["light"]  # tinted by the theme's light, so the wells belong to the glass rather than sit grey on it
        d.rounded_rectangle(box, radius=(box[3] - box[1]) / 2, fill=light + (34,), outline=light + (80,), width=max(1, round(s)))

    @staticmethod
    def _orb(img, d, cx, cy, r, s, lit=False):
        """Nova's logo (the tray icon's bars, without its tile) in a glass well; a soft accent glow behind it while Nova
        works. Click it for the Nova window."""
        Bar._well(d, (cx - r, cy - r, cx + r, cy + r), s)
        if lit:
            for f, a in ((.82, 40), (.6, 70)):
                d.ellipse((cx - r * f, cy - r * f, cx + r * f, cy + r * f), fill=theme.T["accent"] + (a,))
        size = round(r * 1.55)  # the bars fill about two thirds of the well
        img.alpha_composite(_logo(size), (round(cx - size / 2), round(cy - size / 2)))

    @staticmethod
    def _sparkle(d, cx, cy, r, color):
        """A four-pointed star, with a small one beside it: the mark of asking."""
        def star(x, y, r):
            n = r * .26
            d.polygon([(x, y - r), (x + n, y - n), (x + r, y), (x + n, y + n), (x, y + r), (x - n, y + n), (x - r, y),
                       (x - n, y - n)], fill=color + (255,))
        star(cx - r * .2, cy + r * .1, r * .85)
        star(cx + r * .75, cy - r * .7, r * .38)

    @staticmethod
    def _bars(d, cx, cy, s, heights, bw, color=WHITE):
        gap = 3.2 * s if bw < 3 * s else 4 * s
        x = cx - (len(heights) * (bw + gap) - gap) / 2
        for hh in heights:
            hh = max(bw, hh)
            d.rounded_rectangle((x, cy - hh / 2, x + bw, cy + hh / 2), radius=bw / 2, fill=color + (240,))
            x += bw + gap
