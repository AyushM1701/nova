"""Save and restore the whole clipboard (text, images, copied files, rich text) around a dictation paste."""
import sys

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

else:
    from core._clipboard_win import restore, set_text, snapshot  # noqa: F401
