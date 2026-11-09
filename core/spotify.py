"""Play or queue something in the Spotify desktop app, with no AI: open its search page, then press buttons there.

Spotify is a Chromium window and only builds its accessibility tree while Windows' screen-reader flag is set, so the
flag is raised for the few seconds this takes. Buttons are pressed through UI Automation, so the mouse never moves.
"""
import contextlib
import os
import re
import time
import urllib.parse

from core import winctl
from core.system import IS_MAC

MARKER = "Genres & Moods"  # the last filter chip above the results; the first bare "Play" after it is the top result
IDLE = ("spotify", "spotify premium", "spotify free")  # its window title when nothing plays; else "Artist - Song"


def _walk(window):
    """Every control below `window`, depth-first, in document order."""
    stack = [window]
    while stack:
        control = stack.pop()
        stack.extend(reversed(control.GetChildren()))
        yield control


def _cards(window, most=6):
    """The first search results below the filter chips: (its Play button, the names of its links: title, then artists).
    The top result's links come before its bare "Play"; a song row's button ("Play goosebumps") comes before its links."""
    cards, links, seen = [], [], False
    for control in _walk(window):
        name = control.Name
        if not seen:
            seen = name == MARKER
            continue
        kind = control.ControlTypeName
        if kind == "HyperlinkControl":
            (cards[-1][1] if cards else links).append(name)
        elif kind == "ButtonControl" and re.match(r"(Play|Pause)( |$)", name):
            if len(cards) == most:
                break
            cards.append((control, [] if cards else links))
    return cards


def _words(text):
    return set(re.findall(r"\w+", text.lower()))


def best(query, cards):
    """Which result to play (`cards`: each one's link names, title first): the one whose title and artists cover most of
    what was asked, less the words its title adds ("Remix", "Live"). A tie goes to the earlier, Spotify's top result first:
    "travis scott goosebumps" tops with "Goosebumps - Remix", the song row below it is "goosebumps"."""
    want = _words(query)
    def score(links):
        return len(want & _words(" ".join(links))) - len(_words(links[0] if links else "") - want)
    return max(range(len(cards)), key=lambda i: (score(cards[i]), -i))


def covered(query, links):
    """How much of what was asked a result's title and artists cover, 0..1. A near-spelling counts ("diwari" for
    "Diwaari"): Hindi heard in Roman letters is spelled many ways."""
    from difflib import SequenceMatcher
    want, have = _words(query), _words(" ".join(links))
    return sum(any(w == h or SequenceMatcher(None, w, h).ratio() >= 0.75 for h in have) for w in want) / max(1, len(want))


def _find(window, want, query=""):
    """The Play button to press, None while the page is still loading, or "weak" when even the best result covers
    less than half of what was asked (Spotify's search missed: the AI tries other spellings). want='top': the best
    result ('playing': or its Pause, once it plays); 'player': the bar."""
    if want == "player":
        for control in _walk(window):
            if control.ControlTypeName == "ButtonControl" and control.Name in ("Play", "Pause"):
                return control  # in the player bar "Pause" means it is already playing
        return None
    cards = _cards(window)
    if not cards:
        return None
    pick = best(query, [links for _, links in cards])
    button, links = cards[pick]
    if covered(query, links) < 0.5:  # "4 deevaareez ek bandha kaam ka" topped by "4 Diwari": only "4" in common
        return "weak"
    return None if want == "top" and button.Name.startswith("Pause") else button


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
            return w and _find(w, want if query else "player", query)
        for want in ("top", "playing"):  # the second look takes a top result that has started meanwhile as done
            button = _until(lambda: top(want), timeout)
            if not button or button == "weak":
                return False  # nova.py then hands the request to the AI
            if button.Name.startswith("Pause"):
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
