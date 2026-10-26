"""Sketch notes: for a question with a short factual answer ("who won today's grand prix?", "how does a heat pump
work?"), the AI can explain out loud AND hand Nova a small drawing of it, which Nova sketches on screen while it
speaks (core/sketchpad.py). The drawing is a block in the reply:

    :::sketch Antonelli wins at Suzuka
    sub Japanese Grand Prix, 29 March
    img wiki Kimi Antonelli | Kimi Antonelli
    row 1 | Antonelli | Mercedes
    row 2 | Piastri | +13.7 s
    bar Antonelli | 100
    flow Heat > Fluid > Pump
    item a plain bullet
    note the one thing to remember
    src Formula 1, ESPN
    ask How do safety cars help?
    :::

This file only reads and removes the block (no drawing, no windows), so the brain can import it."""
import re

MAX_ELEMENTS = 8  # rows, bars, items, flows and notes together
MAX_ASKS = 3  # follow-up questions, drawn as chips the user can click
START_RE = re.compile(r"^\s*:::\s*sketch\b(.*)$", re.I)
END_RE = re.compile(r"^\s*:::\s*$")
FENCE_RE = re.compile(r"^\s*```\w*\s*$")  # a model sometimes wraps the block in a code fence
FLOW_SPLIT = re.compile(r"\s*(?:->|→|>)\s*")


def _clip(text, n):
    return " ".join(str(text).split())[:n].strip()


def _element(line):
    """One line of the block as (kind, data), or None. `row` is "n | label | detail" with the number and the
    detail optional."""
    word, _, rest = line.strip().partition(" ")
    kind, rest = word.lower(), rest.strip()
    if not rest:
        return None
    if kind == "row":
        parts = [_clip(p, 40) for p in rest.split("|")]
        number = parts.pop(0) if len(parts) > 1 and re.fullmatch(r"\d{1,2}", parts[0]) else ""
        return ("row", (number, parts[0], parts[1] if len(parts) > 1 else "")) if parts[0] else None
    if kind == "bar":
        label, _, value = rest.partition("|")
        m = re.search(r"-?\d+(?:\.\d+)?", value)
        return ("bar", (_clip(label, 30), float(m[0]))) if m and _clip(label, 30) and float(m[0]) >= 0 else None
    if kind == "flow":
        nodes = [_clip(n, 18) for n in FLOW_SPLIT.split(rest) if _clip(n, 18)]
        return ("flow", nodes[:4]) if len(nodes) >= 2 else None
    if kind == "img":  # one picture: the lead photo of a Wikipedia page, named by its title. Never a link: one the AI
        spec, _, caption = rest.partition("|")  # copied from a web page could make Nova contact someone else's server
        spec = spec.strip()
        if spec.lower().startswith("wiki ") and _clip(spec[5:], 100):
            return ("img", ("wiki:" + _clip(spec[5:], 100), _clip(caption, 40)))
        return None
    if kind == "ask":
        return ("ask", _clip(rest, 60)) if rest.rstrip().endswith("?") else None
    if kind in ("item", "note", "sub"):
        return (kind, _clip(rest, 120 if kind == "note" else 80))
    if kind == "src":
        return ("src", [_clip(s, 24) for s in rest.split(",") if _clip(s, 24)][:4])
    return None


def take(text):
    """(the reply without its sketch block, the sketch as {"title", "sub", "elements", "src"} or None). The block ends
    at its closing ::: line, or at the end of the reply if the model forgot it; a code fence around it goes too."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if START_RE.match(l)), None)
    if start is None:
        return text, None
    end = next((i for i in range(start + 1, len(lines)) if END_RE.match(lines[i])), len(lines))
    first, last = start, min(end + 1, len(lines))
    if first > 0 and FENCE_RE.match(lines[first - 1]):
        first -= 1
        if last < len(lines) and FENCE_RE.match(lines[last]):
            last += 1
    after = []  # ask lines the model put just after the closing ::: instead of inside the block
    while True:
        at = last
        while at < len(lines) and not lines[at].strip():
            at += 1
        if at < len(lines) and re.match(r"^\s*ask\s+\S.*\?\s*$", lines[at], re.I):
            after.append(lines[at])
            last = at + 1
        else:
            break
    sketch = {"title": _clip(START_RE.match(lines[start])[1], 60) or "Nova", "sub": "", "elements": [], "src": [], "image": None, "asks": []}
    for line in lines[start + 1:end] + after:
        el = _element(line)
        if not el:
            continue
        if el[0] == "sub":
            sketch["sub"] = el[1]
        elif el[0] == "src":
            sketch["src"] = el[1]
        elif el[0] == "img":
            sketch["image"] = sketch["image"] or el[1]
        elif el[0] == "ask":
            sketch["asks"] = (sketch["asks"] + [el[1]])[:MAX_ASKS]
        elif len(sketch["elements"]) < MAX_ELEMENTS:
            sketch["elements"].append(el)
    numbers = [data[0] for kind, data in sketch["elements"] if kind == "row" and data[0]]
    if numbers and [int(n) for n in numbers] != sorted({int(n) for n in numbers}):  # "1, 1, 1": not a ranking, plain rows
        sketch["elements"] = [("row", ("", *data[1:])) if kind == "row" else (kind, data) for kind, data in sketch["elements"]]
    rest = "\n".join(lines[:first] + lines[last:]).strip()
    return rest, (sketch if sketch["elements"] or sketch["image"] else None)


def strip(text):
    """The reply without any sketch block, for the spoken-line fallback and for requests that can't show one."""
    return take(text)[0]


def as_text(sketch):
    """The sketch as plain lines, for the history in the Nova window (which can't show the drawing)."""
    out = [sketch["title"] + (f" ({sketch['sub']})" if sketch["sub"] else "")]
    for kind, data in sketch["elements"]:
        if kind == "row":
            out.append(" ".join(x for x in (f"{data[0]}." if data[0] else "-", data[1], f"({data[2]})" if data[2] else "") if x))
        elif kind == "bar":
            out.append(f"- {data[0]}: {data[1]:g}")
        elif kind == "flow":
            out.append(" → ".join(data))
        else:
            out.append(f"- {data}")
    return "\n".join(out)
