"""The dictionary learns from your corrections. After Nova pastes a dictation, it reads the text field it pasted
into a few times over the next minute (Windows UI Automation, macOS Accessibility). When you fix a misheard word
there ("Cooper Netties" -> "Kubernetes"), the corrected word joins your dictionary so Whisper expects it next time.

The field's text is only compared in memory and never saved or logged; password fields are never read. Only the
learned word is kept. Turn it off in Settings, Dictation.
"""
import re
import sys
import time
from difflib import SequenceMatcher

WORD_RE = re.compile(r"[\w'’+#.-]*\w[\w'’+#-]*")
CHECKS_S = (4, 15, 35, 60)  # after the paste: when to look at the field again


def similar(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _match(pasted, field):
    """(pasted words, field words, matcher), or None when the pasted text isn't (mostly) in the field."""
    a, spans = WORD_RE.findall(pasted), [x.span() for x in WORD_RE.finditer(field or "")]
    b = [field[i:j] for i, j in spans]
    if len(a) < 2 or not b:
        return None
    m = SequenceMatcher(None, [w.lower() for w in a], [w.lower() for w in b], autojunk=False)
    return (a, b, m, spans) if sum(block.size for block in m.get_matching_blocks()) >= max(2, len(a) // 2) else None


def corrections(pasted, field):
    """Words the user changed inside the pasted text, as they spelled them. A change is a fix (not a rewrite)
    when it replaces one or two words with one or two similar-sounding-looking ones, between words that stayed."""
    match = _match(pasted, field)
    if not match:
        return []
    a, b, m, spans = match
    found = []
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        if tag == "equal":  # same word, new capitals: "grpc" -> "gRPC", "openai" -> "OpenAI" (not "the" -> "The")
            for old, j in zip(a[i1:i2], range(j1, j2)):
                new = b[j]
                mid_sentence = j > 0 and not re.search(r"[.!?:\n]", field[spans[j - 1][1]:spans[j][0]])
                if new != old and len(new) >= 3 and (any(ch.isupper() for ch in new[1:]) or mid_sentence
                                                     and new == old.capitalize()):
                    found.append(new)
            continue
        if tag != "replace" or i2 - i1 > 2 or j2 - j1 > 2 or (i1 == 0 and i2 == len(a)):
            continue
        old, new = " ".join(a[i1:i2]), " ".join(b[j1:j2]).strip(".-'’")
        if len(new) >= 3 and not new.isdigit() and new.lower() != old.lower() and similar(old, new) >= 0.5:
            found.append(new)
    return found


if sys.platform == "darwin":
    def focused_text():
        """(element, text) of the focused text field, or (None, None)."""
        from ApplicationServices import (AXUIElementCopyAttributeValue, AXUIElementCreateSystemWide,
                                         kAXFocusedUIElementAttribute, kAXRoleAttribute, kAXValueAttribute)
        err, el = AXUIElementCopyAttributeValue(AXUIElementCreateSystemWide(), kAXFocusedUIElementAttribute, None)
        if err or el is None:
            return None, None
        err, role = AXUIElementCopyAttributeValue(el, kAXRoleAttribute, None)
        if role == "AXSecureTextField":
            return None, None
        err, value = AXUIElementCopyAttributeValue(el, kAXValueAttribute, None)
        return (el, str(value)) if not err and isinstance(value, str) else (None, None)
else:
    def focused_text():
        """(element id, text) of the focused text field, or (None, None)."""
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            c = auto.GetFocusedControl()
            if c is None or c.IsPassword:
                return None, None
            ident = (c.ProcessId, tuple(c.GetRuntimeId() or ()))
            value = c.GetPattern(auto.PatternId.ValuePattern)
            if value is not None and value.Value:
                return ident, value.Value
            text = c.GetPattern(auto.PatternId.TextPattern)
            if text is not None:
                return ident, text.DocumentRange.GetText(20000)
            return None, None


def watch(pasted, known, on_learn, read=focused_text, sleep=time.sleep):
    """Run after a paste (in its own thread): follow the field the text went into, and call on_learn(words) with
    the words the user corrected there. Stops early once focus moves to another field."""
    sleep(1.5)  # let the paste land
    try:
        ident, last = read()
    except Exception:  # an app that doesn't answer Accessibility / UI Automation: nothing to learn from
        return
    if ident is None or not _match(pasted, last):  # not a text field Nova can read, or the paste went elsewhere
        return
    waited = 1.5
    for at in CHECKS_S:
        sleep(at - waited)
        waited = at
        try:
            now, text = read()
        except Exception:
            break
        if now != ident:
            break
        last = text
    known = {w.lower() for w in known}
    words = [w for w in dict.fromkeys(corrections(pasted, last)) if w.lower() not in known]
    if words:
        on_learn(words)
