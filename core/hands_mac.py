"""Desktop "hands" on macOS: the Accessibility API (AXUIElement) behind the same three tools as core/hands.py.

AXPress and setting AXValue act on the control itself, so the mouse never moves and no app comes to the front. Keystrokes
(which would need CGEvent posting to a background app) are not used. Needs the Accessibility permission, which Nova
already asks for. Only `_ax` and `_apps` touch macOS, so tests can swap in a fake tree.
"""
import collections
import os
import subprocess
import time

from core.hands import BROWSER_BUNDLES, DECIDES, MAX_VISITED

ROLES = {"AXButton": "button", "AXTextField": "edit", "AXTextArea": "edit", "AXSecureTextField": "edit", "AXComboBox": "combobox",
         "AXCheckBox": "checkbox", "AXRadioButton": "radio", "AXPopUpButton": "button", "AXMenuButton": "button",
         "AXMenuItem": "menu item", "AXMenuBarItem": "menu item", "AXLink": "link", "AXRow": "item", "AXCell": "item"}
MAX_ITEMS, MAX_DEPTH = 150, 25
_last = {"app": "", "items": []}  # (role, name) of the controls the last `see` numbered


def _ax():
    import ApplicationServices
    return ApplicationServices


def _apps():
    """[(pid, localized name, bundle id)] of the apps with a window on the Dock, front app first."""
    from AppKit import NSWorkspace
    workspace = NSWorkspace.sharedWorkspace()
    front = workspace.frontmostApplication()
    first = front.processIdentifier() if front else -1  # None when nothing is in front
    apps = sorted((a for a in workspace.runningApplications() if a.activationPolicy() == 0),
                  key=lambda a: a.processIdentifier() != first)
    return [(a.processIdentifier(), str(a.localizedName() or ""), str(a.bundleIdentifier() or "")) for a in apps]


def _parent(pid):
    try:
        return int(subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def _is_nova(pid, bundle=""):
    """Nova, or anything it started (the companion window is a child process whose Settings change the safety mode)."""
    if bundle == "com.nova.assistant":
        return True
    for _ in range(10):
        if pid == os.getpid():
            return True
        pid = _parent(pid)
        if pid <= 1:
            return False
    return False


def _get(element, attribute):
    error, value = _ax().AXUIElementCopyAttributeValue(element, attribute, None)
    return value if error == 0 else None


def window_id(app):
    """The app `app` ("" = the front one) means right now, to notice a change while the user decides."""
    wanted = app.lower().strip()
    return wanted or (_apps() or [(None,)])[0][0]


def _application(app):
    """The AXUIElement of an app by its spoken name (empty: the front app). Never Nova itself, never a browser."""
    wanted = app.lower().strip()
    for pid, name, bundle in _apps():
        if wanted and wanted not in name.lower() and wanted not in bundle.lower():
            continue  # the name first: finding Nova's ancestry costs a `ps` per step, and only the match needs it
        if not _is_nova(pid, bundle):
            if bundle.startswith(BROWSER_BUNDLES):
                raise PermissionError("That is a browser: use the browser tools (read, click) for web pages.")
            element = _ax().AXUIElementCreateApplication(pid)
            _ax().AXUIElementSetAttributeValue(element, "AXManualAccessibility", True)  # Chromium and Electron build their tree
            return element, name
        if not wanted:  # the front app is Nova's own window: not whichever app happens to be listed next
            break
    raise RuntimeError(f"No open app for {app!r}. Open it first (Nova's own windows are off limits).")


def _window(element):
    window = _get(element, "AXFocusedWindow") or _get(element, "AXMainWindow") or next(iter(_get(element, "AXWindows") or []), None)
    if window is None:
        raise RuntimeError("That app has no open window.")
    return window


def _name(control):
    for attribute in ("AXTitle", "AXDescription", "AXPlaceholderValue", "AXHelp"):
        value = _get(control, attribute)
        if value:
            return str(value)[:80]
    return ""


def _secret(control):
    return _get(control, "AXSubrole") == "AXSecureTextField" or _get(control, "AXRole") == "AXSecureTextField"


def _collect(app):
    element, name = _application(app)
    window = _window(element)
    items, queue, visited = [], collections.deque([(window, 0)]), 0
    while queue and len(items) < MAX_ITEMS and visited < MAX_VISITED:  # breadth first: the window's own controls first
        visited += 1
        control, depth = queue.popleft()
        role = _get(control, "AXRole")
        if role in ROLES and (_name(control) or ROLES[role] == "edit"):
            items.append(control)
        if depth < MAX_DEPTH:
            queue.extend((child, depth + 1) for child in _get(control, "AXChildren") or [])
    return name, items


def _describe(control):
    return (str(_get(control, "AXRole")), _name(control))


def _line(i, control):
    kind = ROLES[_get(control, "AXRole")]
    value = ""
    if kind in ("edit", "combobox") and not _secret(control):
        text = _get(control, "AXValue")
        value = f' = "{str(text)[:60]}"' if text else ""
    return f'[{i}] {kind} "{_name(control)}"{value}'


def look(app):
    title, items = _collect(app)
    _last.update(app=app, items=[_describe(c) for c in items])
    return title + "\n" + ("\n".join(_line(i, c) for i, c in enumerate(items, 1)) if items else "(no controls found)")


def _target(app, ref):
    if not _last["items"] or _last["app"] != app:
        look(app)
    _, items = _collect(app)
    if str(ref).isdigit():
        i = int(ref) - 1
        if 0 <= i < len(items) and i < len(_last["items"]) and _describe(items[i]) == tuple(_last["items"][i]):
            return items[i]
        raise RuntimeError(f"[{ref}] changed or is gone. Use hands_see for fresh numbers.")
    words = str(ref).lower()
    for match in (lambda n: n == words, lambda n: n.startswith(words), lambda n: words in n):
        for control in items:
            if match(_name(control).lower()):
                return control
    raise RuntimeError(f"No control {ref!r}. Use hands_see to get fresh numbers.")


def describe(app, ref):
    control = _target(app, ref)
    return {"name": _name(control), "type": "password" if _secret(control) else "", "isSubmit": bool(DECIDES.search(_name(control))),
            "field": str(_get(control, "AXIdentifier") or ""), "host": app or "the front app"}


def click(app, ref):
    control = _target(app, ref)
    if _ax().AXUIElementPerformAction(control, "AXPress") != 0:
        raise RuntimeError(f"{_name(control)!r} can't be pressed without moving the mouse.")
    time.sleep(0.6)
    return f"clicked [{ref}]\n" + look(app)


def type_text(app, ref, text):
    control = _target(app, ref)
    if _secret(control):
        raise PermissionError("That is a password field; the user types those.")
    if _ax().AXUIElementSetAttributeValue(control, "AXValue", text) != 0:
        raise RuntimeError(f"{_name(control)!r} isn't a field Nova can fill without the keyboard.")
    return f"typed into [{ref}]"


def run(tool, args):
    app = args.get("app", "")
    if tool == "hands_see":
        return look(app)
    if tool == "hands_click":
        return click(app, args["target"])
    if tool == "hands_type":
        return type_text(app, args["target"], str(args["text"]))
    raise RuntimeError(f"Unknown tool {tool}")
