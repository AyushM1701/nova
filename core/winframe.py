"""Nova's window on Windows: a real, resizable window whose title bar is Nova's own dock.

The frame stays (so Windows resizes it at the edges, snaps it to them and Win+Arrow works), but the caption is taken
away (WM_NCCALCSIZE), and the page fills the window. At the top right a hole is cut in the page, where minimize,
maximize and close are drawn here and answered as Windows' own buttons (WM_NCHITTEST): hovering maximize brings up
the snap layouts. Windows Terminal draws its title bar the same way."""
import ctypes
from ctypes import wintypes as w

u, gdi = ctypes.windll.user32, ctypes.windll.gdi32
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
u.CallWindowProcW.argtypes = [ctypes.c_void_p, w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u.CallWindowProcW.restype = LRESULT
u.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_void_p]
u.SetWindowLongPtrW.restype = ctypes.c_void_p
u.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u.DefWindowProcW.restype = LRESULT
gdi.CreateFontW.restype = ctypes.c_void_p
gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi.SelectObject.restype = ctypes.c_void_p
gdi.DeleteObject.argtypes = [ctypes.c_void_p]
gdi.CreateSolidBrush.restype = ctypes.c_void_p
gdi.CreateRectRgn.restype = ctypes.c_void_p
gdi.CombineRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
u.SetWindowRgn.argtypes = [w.HWND, ctypes.c_void_p, w.BOOL]
u.GetDC.restype = ctypes.c_void_p
u.GetDC.argtypes = [w.HWND]
u.ReleaseDC.argtypes = [w.HWND, ctypes.c_void_p]
u.FillRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.RECT), ctypes.c_void_p]
gdi.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
gdi.SetTextColor.argtypes = [ctypes.c_void_p, w.COLORREF]
u.DrawTextW.argtypes = [ctypes.c_void_p, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT), w.UINT]

HTCLIENT, HTCAPTION, HTMIN, HTMAX, HTCLOSE = 1, 2, 8, 9, 20
BUTTONS = (HTMIN, HTMAX, HTCLOSE)  # left to right
BUTTON_W = 46  # logical px, as Windows 11 draws them
GLYPH = {HTMIN: "", HTMAX: "", HTCLOSE: ""}
RESTORE = ""
GROUND, LINE = (12, 12, 16), (27, 27, 31)  # the dock (--side) and its hairline, white 7% over it
INK, INK_HOT, HOT, CLOSE_HOT, DOWN = (161, 163, 173), (243, 244, 246), (28, 29, 35), (196, 43, 28), (36, 37, 44)


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("dwFlags", w.DWORD), ("hwndTrack", w.HWND), ("dwHoverTime", w.DWORD)]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", w.RECT * 3), ("lppos", ctypes.c_void_p)]


def rgb(c):
    return c[0] | c[1] << 8 | c[2] << 16


class Frame:
    """Installed on a pywebview window once it is shown (on its own thread): `attach(window)`."""

    def __init__(self, window):
        self.window = window
        self.hwnd = int(window.native.Handle.ToInt64())
        self.web = int(window.native.browser.webview.Handle.ToInt64())  # the page's own window, inside ours
        self.bar_h = 50  # logical px: the dock's height, until the page says (set_bar)
        self.hot = self.down = None
        self.tracking, self.zoomed, self.normal = False, False, None
        self.proc = WNDPROC(self._proc)  # kept, or Python frees the callback Windows still calls
        self.old = u.SetWindowLongPtrW(self.hwnd, -4, ctypes.cast(self.proc, ctypes.c_void_p))  # GWLP_WNDPROC
        u.SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, 0x0027)  # SWP_FRAMECHANGED: the caption goes now
        self._cut()

    # ---------- geometry ----------
    def k(self):
        return u.GetDpiForWindow(self.hwnd) / 96 or 1

    def buttons(self):
        """{HT code: RECT} in client coordinates."""
        r = w.RECT()
        u.GetClientRect(self.hwnd, ctypes.byref(r))
        k = self.k()
        bw, bh = round(BUTTON_W * k), round(self.bar_h * k)
        out = {}
        for i, ht in enumerate(reversed(BUTTONS)):
            right = r.right - i * bw
            out[ht] = w.RECT(right - bw, 0, right, bh)
        return out

    def set_bar(self, height):
        """The dock's height in logical px, as the page measured it: the buttons are as tall."""
        self.bar_h = max(28, min(80, float(height)))
        self._cut()
        u.InvalidateRect(self.hwnd, None, False)

    def _cut(self):
        """The page leaves the buttons' corner to the window, which draws and answers them."""
        r = w.RECT()
        u.GetClientRect(self.web, ctypes.byref(r))
        b = self.buttons()
        left = b[HTMIN].left
        whole = gdi.CreateRectRgn(0, 0, r.right, r.bottom)
        hole = gdi.CreateRectRgn(left, 0, r.right, b[HTCLOSE].bottom)
        gdi.CombineRgn(whole, whole, hole, 4)  # RGN_DIFF
        gdi.DeleteObject(hole)
        u.SetWindowRgn(self.web, whole, True)  # Windows owns the region now

    # ---------- drawing ----------
    def paint(self):
        dc = u.GetDC(self.hwnd)
        if not dc:
            return
        k = self.k()
        zoomed = u.IsZoomed(self.hwnd)
        font = gdi.CreateFontW(-round(10 * k), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe Fluent Icons")
        if not font:
            font = gdi.CreateFontW(-round(10 * k), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe MDL2 Assets")
        old_font = gdi.SelectObject(dc, font)
        gdi.SetBkMode(dc, 1)  # TRANSPARENT
        for ht, r in self.buttons().items():
            hot = ht == self.hot
            fill = (CLOSE_HOT if ht == HTCLOSE else DOWN if self.down == ht else HOT) if hot else GROUND
            brush = gdi.CreateSolidBrush(rgb(fill))
            u.FillRect(dc, ctypes.byref(r), brush)
            gdi.DeleteObject(brush)
            line = w.RECT(r.left, r.bottom - max(1, round(k)), r.right, r.bottom)  # the dock's hairline runs on under them
            brush = gdi.CreateSolidBrush(rgb(LINE))
            u.FillRect(dc, ctypes.byref(line), brush)
            gdi.DeleteObject(brush)
            gdi.SetTextColor(dc, rgb((255, 255, 255) if hot and ht == HTCLOSE else INK_HOT if hot else INK))
            glyph = RESTORE if ht == HTMAX and zoomed else GLYPH[ht]
            u.DrawTextW(dc, glyph, 1, ctypes.byref(w.RECT(r.left, r.top, r.right, r.bottom - 1)), 0x25)  # center|vcenter|singleline
        gdi.SelectObject(dc, old_font)
        gdi.DeleteObject(font)
        u.ReleaseDC(self.hwnd, dc)

    def _set_hot(self, ht):
        if ht != self.hot:
            self.hot = ht
            self.paint()

    # ---------- what Windows asks ----------
    def _hit(self, lp):
        x, y = ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short((lp >> 16) & 0xFFFF).value
        pt = w.POINT(x, y)
        u.ScreenToClient(self.hwnd, ctypes.byref(pt))
        b = self.buttons()
        if b[HTMIN].left <= pt.x and pt.y < b[HTCLOSE].bottom and pt.y < 5 * self.k():  # the resize edge above them
            return 14 if pt.x >= b[HTCLOSE].right - 8 * self.k() else 12  # HTTOPRIGHT, HTTOP
        for ht, r in b.items():
            if r.left <= pt.x < r.right and r.top <= pt.y < r.bottom:
                return ht
        return None

    def _proc(self, hwnd, msg, wp, lp):
        try:
            if msg == 0x0083 and wp:  # WM_NCCALCSIZE: keep the frame's sides and bottom, drop the caption
                params = ctypes.cast(lp, ctypes.POINTER(NCCALCSIZE_PARAMS)).contents
                top = params.rgrc[0].top
                u.CallWindowProcW(self.old, hwnd, msg, wp, lp)
                params.rgrc[0].top = top
                if u.IsZoomed(hwnd):  # a maximized window reaches past the screen by its frame: keep the dock on it
                    dpi = u.GetDpiForWindow(hwnd)
                    params.rgrc[0].top += u.GetSystemMetricsForDpi(33, dpi) + u.GetSystemMetricsForDpi(92, dpi)
                return 0
            if msg == 0x0084:  # WM_NCHITTEST
                ht = self._hit(lp)
                if ht:
                    return ht
            elif msg == 0x00A0:  # WM_NCMOUSEMOVE
                if wp in BUTTONS:
                    if not self.tracking or wp != self.hot:  # a fresh hover for each button: maximize's brings the layouts
                        self.tracking = True
                        tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), 0x12, hwnd, 0)  # leave, non-client (hover is Windows' own)
                        u.TrackMouseEvent(ctypes.byref(tme))
                    self._set_hot(wp)
                    out = u.DefWindowProcW(hwnd, msg, wp, lp)  # Windows itself: over maximize, the snap layouts
                    self.paint()
                    return out
                self._set_hot(None)
            elif msg == 0x02A0 and wp in BUTTONS:  # WM_NCMOUSEHOVER
                return u.DefWindowProcW(hwnd, msg, wp, lp)
            elif msg == 0x02A2:  # WM_NCMOUSELEAVE (also when a press captures the mouse: that press still counts)
                self.tracking = False
                if not self.down:
                    self._set_hot(None)
            elif msg == 0x00A1 and wp in BUTTONS:  # WM_NCLBUTTONDOWN on a button: ours, not the classic one
                self.down = wp
                u.SetCapture(hwnd)  # its release comes here as WM_LBUTTONUP, wherever the pointer is then
                self.paint()
                return 0
            elif msg == 0x0202 and self.down:  # WM_LBUTTONUP after pressing a button: a click if still on it
                pressed, self.down = self.down, None
                u.ReleaseCapture()
                pt = w.POINT()
                u.GetCursorPos(ctypes.byref(pt))
                over = self._hit(pt.x & 0xFFFF | (pt.y & 0xFFFF) << 16)
                self._set_hot(over)
                if over == pressed:
                    command = {HTMIN: 0xF020, HTCLOSE: 0xF060}.get(over) or (0xF120 if u.IsZoomed(hwnd) else 0xF030)
                    u.PostMessageW(hwnd, 0x0112, command, 0)  # WM_SYSCOMMAND: minimize, close, restore or maximize
                return 0
            elif msg == 0x0215 and self.down:  # WM_CAPTURECHANGED: the press was taken away
                self.down = None
                self.paint()
            elif msg in (0x00A3, 0x00A4) and wp in BUTTONS:  # double-click, right-click on a button: nothing
                return 0
            elif msg == 0x8001 and self.normal:  # WM_APP: the size from before maximizing, back
                u.SetWindowPos(hwnd, 0, 0, 0, *self.normal, 0x0016)  # size only (a drag puts it under the pointer)
                return 0
            elif msg == 0x0112 and wp & 0xFFF0 == 0xF030 and not u.IsZoomed(hwnd):  # SC_MAXIMIZE: remember the size
                r = w.RECT()
                u.GetWindowRect(hwnd, ctypes.byref(r))
                self.normal = (r.right - r.left, r.bottom - r.top)
            out = u.CallWindowProcW(self.old, hwnd, msg, wp, lp)
            if msg == 0x0005:  # WM_SIZE: coming back from maximized, WinForms would add the caption we took away
                if wp == 2:
                    self.zoomed = True
                elif wp == 0 and self.zoomed:
                    self.zoomed = False
                    if self.normal:
                        u.PostMessageW(hwnd, 0x8001, 0, 0)  # after WinForms has set its own size
            if msg in (0x0005, 0x000F, 0x02E0, 0x00A0):  # WM_SIZE, WM_PAINT, WM_DPICHANGED: the corner follows the window
                if msg != 0x000F:
                    self._cut()
                self.paint()
            return out
        except Exception:  # a fault here must never take the window's messages down with it
            return u.DefWindowProcW(hwnd, msg, wp, lp)


def attach(window):
    """Give the shown window Nova's title bar. Must run on the window's thread."""
    return Frame(window)
