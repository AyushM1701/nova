"""Play or queue something in the Spotify desktop app, with no AI: open its search page, then press buttons there.

Spotify is a Chromium window and only builds its accessibility tree while Windows' screen-reader flag is set, so the
flag is raised for the few seconds this takes. Buttons are pressed through UI Automation, so the mouse never moves.
"""
import contextlib
import os
import time
import urllib.parse

from core import winctl
from core.system import IS_MAC

MARKER = "Genres & Moods"  # the last filter chip above the results; the first bare "Play" after it is the top result
IDLE = ("spotify", "spotify premium", "spotify free")  # its window title when nothing plays; else "Artist - Song"


def _find(window, want):
    """The Play button to press, or None while the page is still loading. want='top': first result ('playing': or its
    Pause, once it plays); 'player': the bar."""
    seen = want == "player"
    stack = [window]
    while stack:  # depth-first, in document order
        control = stack.pop()
        children = control.GetChildren()
        stack.extend(reversed(children))
        name = control.Name
        if not seen:
            seen = name == MARKER
        elif control.ControlTypeName == "ButtonControl" and (name == "Play" or want != "top" and name == "Pause"):
            return control  # in the player bar "Pause" means it is already playing
    return None


@contextlib.contextmanager
def _spotify(uri):
    """Opens `uri` in Spotify with its accessibility tree switched on; yields a function that returns its window."""
    import uiautomation as auto
    os.startfile(uri)
    with winctl.screen_reader(), auto.UIAutomationInitializerInThread():
        def window():  # by process: the title is the song while one plays; None while the window isn't up yet
            hwnd = winctl.find_process("spotify")
            return auto.ControlFromHandle(hwnd) if hwnd else None
        yield window


def _press(control, *patterns):
    """Press a control without the mouse, with the first pattern it supports. False if it supports none."""
    for getter, act in patterns or (("GetInvokePattern", "Invoke"), ("GetLegacyIAccessiblePattern", "DoDefaultAction")):
        pattern = getattr(control, getter)()
        if pattern:
            getattr(pattern, act)()
            return True
    return False


def _showing(window, query):
    """True once the search box holds `query`: before that the window still shows the previous search's results."""
    box = window().ComboBoxControl(Name="What do you want to play?", searchDepth=30)
    pattern = box.Exists(0) and box.GetValuePattern()
    typed = pattern.Value.replace("+", " ").lower().strip() if pattern else ""
    return typed == query.lower().strip()


def _until(find, timeout):
    end = time.time() + timeout
    while time.time() < end:
        try:
            found = find()
        except Exception:  # the page rebuilt itself under the search (a COMError): look again
            found = None
        if found:
            return found
        time.sleep(0.4)
    return None


def started(before, after):
    """Did pressing Play start something? The title went from `before` to `after`: it now names a track, a new one."""
    return after.lower().strip() not in IDLE and after != before


def play(query, timeout=20):
    """True once something started playing. With no query, resumes whatever Spotify has queued."""
    if IS_MAC:
        return False
    with _spotify("spotify:search:" + urllib.parse.quote(query) if query else "spotify:") as window:
        def top(want):
            w = window()
            if query and not _showing(window, query):
                return None
            return w and _find(w, want if query else "player")
        for want in ("top", "playing"):  # the second look takes a top result that has started meanwhile as done
            button = _until(lambda: top(want), timeout)
            if not button:
                return False
            if button.Name == "Pause":
                return True  # already playing
            time.sleep(0.4)  # results settle just after they appear
            before = window().Name
            if not _press(button):
                return False
            # the search box shows the new words a moment before the results below it change: a press that early hits
            # the last search's card (pausing what plays). Then the page has settled, and the second press is the right one.
            if _until(lambda: started(before, window().Name), 4):
                return True
        return False


def queue(query, timeout=20):
    """True once the best matching song was added to the queue (the top result may be a playlist, so Songs is chosen first)."""
    if IS_MAC or not query:
        return False
    with _spotify("spotify:search:" + urllib.parse.quote(query)) as window:
        songs = _until(lambda: _showing(window, query) and
                       (lambda c: c if c.Exists(0) else None)(window().HyperlinkControl(Name="Songs", searchDepth=30)), timeout)
        if not songs:
            return False
        if not _press(songs):
            return False
        time.sleep(1.5)  # the list swaps from "All" to songs only
        more = _until(lambda: (lambda c: c if c.Exists(0) else None)(window().ButtonControl(SubName="More options for", searchDepth=30)), 8)
        if not more:
            return False
        if not _press(more, ("GetExpandCollapsePattern", "Expand"), ("GetLegacyIAccessiblePattern", "DoDefaultAction")):
            return False
        item = _until(lambda: (lambda c: c if c.Exists(0) else None)(window().MenuItemControl(Name="Add to queue", searchDepth=40)), 5)
        if not item:
            return False
        return _press(item)
