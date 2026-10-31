"""Desktop "hands" for the AI (Windows): list an app's controls, press them and fill fields through UI Automation.

Nothing here moves the mouse or takes focus, so the user keeps working while Nova does something in another app.
The accessibility tree of Chromium and Electron apps (Spotify, Discord, VS Code) only exists while Windows'
screen-reader flag is set (winctl.screen_reader raises it, and drops it again half a minute after the last call).
"""
import contextlib
import re
import time

from core import winctl
from core.system import IS_MAC

KINDS = {"ButtonControl": "button", "SplitButtonControl": "button", "EditControl": "edit", "CheckBoxControl": "checkbox",
         "RadioButtonControl": "radio", "ComboBoxControl": "combobox", "MenuItemControl": "menu item",
         "TabItemControl": "tab", "ListItemControl": "item", "HyperlinkControl": "link", "TreeItemControl": "item",
         "DataItemControl": "item"}
MAX_ITEMS, MAX_DEPTH, MAX_VISITED = 150, 30, 3000  # visited: a big Electron app has far more nodes
_last = {"app": "", "items": []}  # (type, name) of the controls the last `see` numbered


@contextlib.contextmanager
def _session():
    import uiautomation as auto
    with winctl.screen_reader(), auto.UIAutomationInitializerInThread():
        yield auto


# browsers are driven by the browser tools (Nova's side panel and Allow buttons live in their windows)
BROWSER_BUNDLES = ("com.google.Chrome", "com.brave.Browser", "com.apple.Safari", "org.mozilla.firefox", "com.operasoftware.",
                   "com.vivaldi.", "company.thebrowser.", "com.microsoft.edgemac")  # macOS: by bundle id
BROWSERS = {"chrome", "brave", "opera", "msedge", "vivaldi", "firefox", "arc", "iexplore"}
# buttons of a desktop app's own confirm dialogs: pressing them is a decision, so the user is asked
DECIDES = re.compile(r"^(?:yes|ok|allow|approve|continue|accept|proceed|don.?t save|discard|erase|reset|uninstall|format|empty|overwrite|replace|move to trash|force quit)\b", re.I)


def _window(auto, app):
    hwnd = winctl.find(app or "this")
    if not hwnd:
        raise RuntimeError(f"No open window for {app!r}. Open the app first (Nova's own windows are off limits).")
    if winctl.process_of(hwnd) in BROWSERS:
        raise PermissionError("That is a browser: use the browser tools (read, click) for web pages.")
    return auto.ControlFromHandle(hwnd)


def _secret(control):
    return bool(getattr(control, "IsPassword", False))


def _line(i, control):
    kind = KINDS[control.ControlTypeName]
    value = ""
    if kind in ("edit", "combobox") and not _secret(control):
        pattern = control.GetValuePattern()
        text = pattern.Value if pattern else ""
        value = f' = "{text[:60]}"' if text else ""
    return f'[{i}] {kind} "{control.Name[:80]}"{value}'


def _collect(auto, app):
    """Interactive controls of the app's window, in reading order (fresh each call: elements don't outlive a thread)."""
    window = _window(auto, app)
    items, stack, visited = [], [(window, 0)], 0
    while stack and len(items) < MAX_ITEMS and visited < MAX_VISITED:
        visited += 1
        control, depth = stack.pop()
        try:
            kids = control.GetChildren() if depth < MAX_DEPTH else []
            kind = control.ControlTypeName
            if kind in KINDS and (control.Name or kind == "EditControl") and not control.IsOffscreen:
                items.append(control)
        except Exception:  # the tree changed under the walk
            continue
        stack.extend((k, depth + 1) for k in reversed(kids))
    return window, items


def see(auto, app=""):
    """Numbered interactive controls of the app's window. The numbers stay valid until the window changes."""
    window, items = _collect(auto, app)
    _last.update(app=app, items=[(c.ControlTypeName, c.Name) for c in items])
    head = window.Name + "\n"
    return head + "\n".join(_line(i, c) for i, c in enumerate(items, 1)) if items else head + "(no controls found)"


def _target(auto, app, ref):
    """The control a [number] or a label stands for, found again now and checked against what `see` numbered."""
    if not _last["items"] or _last["app"] != app:
        see(auto, app)
    _, items = _collect(auto, app)
    if str(ref).isdigit():
        i = int(ref) - 1
        if 0 <= i < min(len(items), len(_last["items"])) and (items[i].ControlTypeName, items[i].Name) == _last["items"][i]:
            return items[i]
        raise RuntimeError(f"[{ref}] changed or is gone. Use hands_see for fresh numbers.")
    words = str(ref).lower()
    for match in (lambda n: n == words, lambda n: n.startswith(words), lambda n: words in n):  # the closest name wins
        for control in items:
            if match(control.Name.lower()):
                return control
    raise RuntimeError(f"No control {ref!r}. Use hands_see to get fresh numbers.")


def window_id(app):
    """Which window `app` ("" = the one in front) means right now: compared before and after the user decides."""
    try:
        if IS_MAC:
            from core import hands_mac
            return hands_mac.window_id(app)
        return winctl.find(app or "this")
    except Exception:
        return None


def describe(app, ref):
    """What Nova's safety rules need to know about a control, in the shape core/browser.classify expects."""
    if IS_MAC:
        from core import hands_mac
        return hands_mac.describe(app, ref)
    with _session() as auto:
        control = _target(auto, app, ref)
        return {"name": control.Name, "type": "password" if _secret(control) else "", "isSubmit": bool(DECIDES.search(control.Name)),
                "field": control.AutomationId, "host": _window(auto, app).Name}


def click(app, ref):
    with _session() as auto:
        control = _target(auto, app, ref)
        for getter, act in (("GetInvokePattern", "Invoke"), ("GetTogglePattern", "Toggle"),
                            ("GetSelectionItemPattern", "Select"), ("GetExpandCollapsePattern", "Expand"),
                            ("GetLegacyIAccessiblePattern", "DoDefaultAction")):
            pattern = getattr(control, getter)()
            if pattern:
                getattr(pattern, act)()
                break
        else:
            raise RuntimeError(f"{control.Name!r} can't be pressed without moving the mouse.")
        time.sleep(0.6)
        return f"clicked [{ref}]\n" + see(auto, app)


def type_text(app, ref, text):
    with _session() as auto:
        control = _target(auto, app, ref)
        if _secret(control):
            raise PermissionError("That is a password field; the user types those.")
        pattern = control.GetValuePattern()
        if not pattern or pattern.IsReadOnly:
            raise RuntimeError(f"{control.Name!r} isn't a field Nova can fill without the keyboard.")
        pattern.SetValue(text)
        return f"typed into [{ref}]"


def look(app):
    with _session() as auto:
        return see(auto, app)


def run(tool, args):
    """Execute one hands_* tool (already checked by the safety rules). Returns text for the AI."""
    if IS_MAC:
        from core import hands_mac
        return hands_mac.run(tool, args)
    app = args.get("app", "")
    if tool == "hands_see":
        return look(app)
    if tool == "hands_click":
        return click(app, args["target"])
    if tool == "hands_type":
        return type_text(app, args["target"], str(args["text"]))
    raise RuntimeError(f"Unknown tool {tool}")
