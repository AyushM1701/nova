"""Save and restore the whole clipboard (text, images, copied files, rich text) around a dictation paste,
and remember recently copied text so "paste what I copied earlier" works. That history lives only in memory
(never on disk) and skips anything that looks like a password, key or token."""
import collections
import re
import sys
import time

if sys.platform == "darwin":
    from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString

    def snapshot():
        """Every item on the pasteboard as {type: data}."""
        items = NSPasteboard.generalPasteboard().pasteboardItems() or []
        return [{str(k): item.dataForType_(k) for k in item.types()} for item in items]

    def restore(items):
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        rebuilt = []
        for item in items:
            new = NSPasteboardItem.alloc().init()
            for kind, data in item.items():
                if data is not None:  # promised data the source app never provided
                    new.setData_forType_(data, kind)
            rebuilt.append(new)
        if rebuilt:
            pb.writeObjects_(rebuilt)

    def set_text(text):
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, NSPasteboardTypeString)

    def get_text():
        text = NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)
        return str(text) if text is not None else None

    def change_count():
        return NSPasteboard.generalPasteboard().changeCount()

else:
    from core._clipboard_win import change_count, get_text, restore, set_text, snapshot  # noqa: F401

SECRET_RE = re.compile(
    r"password|passwd|passcode|\bpin\b|secret|token|api[_ -]?key|bearer\s|-----BEGIN|\b(?:sk|pk|rk)[-_][\w-]{16,}"
    r"|\bgh[pousr]_\w{20,}|\bAKIA[0-9A-Z]{16}\b|\bxox[bpas]-|\beyJ[\w-]{10,}\.[\w-]{10,}"
    r"|^(?!https?://|[a-z]:\\|/|~/)\S{24,}$", re.I)  # one long unbroken string is likely a key; URLs and paths aren't


class History:
    """The last few things copied as text, newest last. Secrets and Nova's own markers are never kept."""

    def __init__(self, size=20):
        self.items = collections.deque(maxlen=size)

    def add(self, text, now=None):
        text = (text or "").strip()
        if not text or len(text) > 4000 or text.startswith("nova-") or SECRET_RE.search(text):
            return
        for item in [i for i in self.items if i[1] == text]:
            self.items.remove(item)  # copied again: move it to the top
        self.items.append((now or time.time(), text))

    def describe(self, now=None):
        """Numbered, newest first, with how long ago: for the AI's context."""
        now = now or time.time()
        ago = lambda t: f"{int((now - t) // 60)} min ago" if now - t >= 60 else "just now"
        return "\n".join(f"{n}. ({ago(t)}) {text[:600]}" for n, (t, text) in enumerate(reversed(self.items), 1))
