"""What kind of request a sentence is: a question about the screen (one quick answer with no tools), a question a sketch
note could answer, a follow-up chip's question (which becomes a request when tapped, so never a task)."""
import re

# a question about the screen, not a task: one answer with no tools, which is much faster (Claude only)
QUESTION_RE = re.compile(r"^\W*(?:what|what'?s|whats|where|which|who|why|how|is|are|does|can you see|explain|describe|"
                         r"summari[sz]e|read|translate|tell me|show me where)\b", re.I)
HOW_TO_RE = re.compile(r"^\W*(?:how (?:do|can|should|would) i|where)\b", re.I)  # asks how, not to do it
ACT_RE = re.compile(r"\b(?:open|close|click|type|write|fix|change|edit|delete|remove|install|run|send|reply|create|make|"
                    r"save|copy|paste|move|rename|add|update|set|turn|play|search|download|book|buy|order|submit|post|"
                    r"email|schedule|go to|remember|note|commit|push|deploy|build|refactor|rewrite|apply|share|upload|"
                    r"print|undo)\b", re.I)


# "can you tell me who won", "do you know who won", "so who won": the same question with a lead-in
SKETCH_LEAD_RE = re.compile(r"^\W*(?:(?:so|and|okay|ok|well|um|uh),?\s+|(?:can|could|would) you (?:please )?(?:tell|explain to|show) me\s+|"
                            r"do you know\s+|i (?:want|need) to know\s+)+", re.I)


CHIP_RE = re.compile(r"^\W*(?:when|what|where|which|who|whom|whose|why|how|is|are|was|were|does|do|did|can|could|will|"
                     r"would|should|has|have|want)\b", re.I)


def chip_question(text):
    """A follow-up chip's text, which becomes a request when tapped: a question, and not a task (a chip can't ask
    Nova to delete or send something)."""
    return (bool(CHIP_RE.match(text)) and text.rstrip().endswith("?") and not ACT_RE.search(text)
            and not re.match(r"^\W*(?:when|if) i say\b", text, re.I))  # a tap must not teach a shortcut


def sketch_question(text):
    """A spoken question a sketch note could answer. Its own test, not QUESTION_RE: that one also picks the no-tools
    quick path for screen questions."""
    return screen_question(SKETCH_LEAD_RE.sub("", text, count=1)) or screen_question(text)


def screen_question(text):
    """A question to answer from the screenshot alone ("where's the export button?"), not a task ("fix this")."""
    return bool(QUESTION_RE.match(text)) and bool(HOW_TO_RE.match(text) or not ACT_RE.search(text))
