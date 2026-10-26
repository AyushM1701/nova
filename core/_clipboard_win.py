"""Windows clipboard snapshot/restore via the Win32 API (GDI-handle formats are re-created by Windows)."""
import ctypes
import time
from ctypes import wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.OpenClipboard.argtypes = [w.HWND]
user32.EnumClipboardFormats.argtypes = [w.UINT]
user32.EnumClipboardFormats.restype = w.UINT
user32.GetClipboardData.argtypes = [w.UINT]
user32.GetClipboardData.restype = w.HANDLE
user32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
user32.SetClipboardData.restype = w.HANDLE
kernel32.GlobalLock.argtypes = [w.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [w.HGLOBAL]
kernel32.GlobalSize.argtypes = [w.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = w.HGLOBAL
kernel32.GlobalFree.argtypes = [w.HGLOBAL]

user32.RegisterClipboardFormatW.argtypes = [w.LPCWSTR]
user32.RegisterClipboardFormatW.restype = w.UINT
user32.IsClipboardFormatAvailable.argtypes = [w.UINT]
user32.IsClipboardFormatAvailable.restype = w.BOOL

CF_UNICODETEXT = 13
# GDI-handle formats can't be copied as bytes; Windows re-creates them from CF_DIB / CF_UNICODETEXT
GDI_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}


def sensitive():
    """True when the app that copied asked not to be recorded (password managers do), so nothing reads it."""
    return bool(user32.IsClipboardFormatAvailable(user32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")))


def _open():
    for _ in range(25):  # another app may hold the clipboard for a moment
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def _set(fmt, data):
    h = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    if not user32.SetClipboardData(fmt, h):
        kernel32.GlobalFree(h)  # on success the clipboard owns h


def snapshot():
    """Every format currently on the clipboard as (format, bytes)."""
    if not _open():
        return []
    items, fmt = [], 0
    try:
        while fmt := user32.EnumClipboardFormats(fmt):
            if fmt in GDI_FORMATS:
                continue
            h = user32.GetClipboardData(fmt)
            p = kernel32.GlobalLock(h) if h else None
            if not p:  # not memory-backed (e.g. OLE stream): skip it
                continue
            try:
                items.append((fmt, ctypes.string_at(p, kernel32.GlobalSize(h))))
            finally:
                kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()
    return items


def restore(items):
    if not _open():
        return
    try:
        user32.EmptyClipboard()
        for fmt, data in items:
            _set(fmt, data)
    finally:
        user32.CloseClipboard()


def change_count():
    """Goes up every time anything is copied, without opening the clipboard."""
    return user32.GetClipboardSequenceNumber()


def get_text():
    """The clipboard's text, or None if it holds no text."""
    if not _open():
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        p = kernel32.GlobalLock(h) if h else None
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def set_text(text):
    restore([(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))])
