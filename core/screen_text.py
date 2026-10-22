"""The text in the user's window, read through Windows UI Automation or macOS Accessibility, for requests like
"summarize this page" or "what does this email say?". It includes text scrolled out of view, which a screenshot
can't show, and is read only when a request is about the screen. Password fields are skipped; nothing is saved.
"""
import sys
import time

LIMIT = 20_000  # characters handed to the AI
BUDGET_S = 2.5  # a page with thousands of elements must not hold up the request


def _add(out, text, seen):
    text = " ".join((text or "").split())
    if len(text) > 1 and text.lower() not in seen and not any(text in big for big in out if len(big) > 400):
        seen.add(text.lower())
        out.append(text)


if sys.platform == "darwin":
    TEXT_ROLES = {"AXStaticText", "AXTextArea", "AXTextField", "AXHeading", "AXLink", "AXCell", "AXMenuButton",
                  "AXButton", "AXWebArea"}

    def window_text(app, limit=LIMIT, budget_s=BUDGET_S):
        """The frontmost window of `app` (an NSRunningApplication) as plain text, or ''."""
        from ApplicationServices import AXUIElementCopyAttributeValue, AXUIElementCreateApplication
        get = lambda el, attr: AXUIElementCopyAttributeValue(el, attr, None)[1]  # noqa: E731
        if app is None:
            return ""
        window = get(AXUIElementCreateApplication(app.processIdentifier()), "AXFocusedWindow")
        out, seen, queue, start = [], set(), [window] if window is not None else [], time.monotonic()
        while queue and time.monotonic() - start < budget_s and sum(map(len, out)) < limit:
            el = queue.pop(0)
            role = get(el, "AXRole")
            if role == "AXSecureTextField":
                continue
            if role in TEXT_ROLES:
                for attr in ("AXValue", "AXTitle", "AXDescription"):
                    value = get(el, attr)
                    if isinstance(value, str):
                        _add(out, value, seen)
                        break
            queue += list(get(el, "AXChildren") or [])
        return "\n".join(out)[:limit]
else:
    def window_text(hwnd, limit=LIMIT, budget_s=BUDGET_S):
        """The window `hwnd` as plain text, or ''. Documents (web pages, editors) are read whole."""
        import uiautomation as auto
        if not hwnd:
            return ""
        T = auto.ControlType
        named = {T.TextControl, T.HyperlinkControl, T.ListItemControl, T.HeaderItemControl, T.DataItemControl,
                 T.TreeItemControl, T.TabItemControl, T.TitleBarControl}
        with auto.UIAutomationInitializerInThread():
            root = auto.ControlFromHandle(hwnd)
            if root is None:
                return ""
            out, seen, start = [], set(), time.monotonic()
            for c, _ in auto.WalkControl(root, includeTop=False, maxDepth=60):
                if time.monotonic() - start > budget_s or sum(map(len, out)) > limit:
                    break
                try:
                    if c.IsPassword:
                        continue
                    kind = c.ControlType
                    if kind in (T.DocumentControl, T.EditControl):
                        text = c.GetPattern(auto.PatternId.TextPattern)
                        value = c.GetPattern(auto.PatternId.ValuePattern)
                        _add(out, text.DocumentRange.GetText(limit) if text else value.Value if value else "", seen)
                    elif kind in named:
                        _add(out, c.Name, seen)
                except Exception:  # an element that vanished while being read (a page still loading)
                    continue
            return "\n".join(out)[:limit]
