"""One note per skill run, in notes/runs/<skill>/, and a copy of what the run made in notes/outputs/<skill>/. The next
run of the same skill reads the newest notes first, so it can do better: that is the loop. Plain markdown, so the
user can open a note in any editor and write what to change under "## Feedback"."""
import os
import shutil
import time
from pathlib import Path

from core.config import NOTES, log, write_atomic
from core.skills import NAME_RE

DIR = NOTES / "runs"
OUT = NOTES / "outputs"
KEEP = 30  # notes (and output copies) kept per skill; older ones are deleted
REPLY_MAX = 4000
MAX_FILE_BYTES = 10 << 20  # a bigger file stays in the job's own folder only
MAX_FILES = 30
SHOWN = {"reply": 1200, "run note": 1500, "feedback": 1500}  # characters of each part that go into the next prompt


def _check(name):
    if not NAME_RE.fullmatch(str(name)):  # a name becomes a folder: never a path
        raise ValueError(f"not a skill name: {name!r}")
    return name


def _inside(path, root):
    """The real place `path` is (links, Windows junctions and short names resolved) is under `root`. A link is not
    always a symlink: `mklink /J` makes a junction that is_symlink() calls an ordinary folder."""
    real, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(root)  # Windows paths ignore case
    return real == root or real.startswith(root + os.sep)


def _plain_file(path, root):
    """A regular file that really lives under `root` and isn't a second name for a file elsewhere (a hard link)."""
    try:
        return not path.is_symlink() and path.is_file() and path.stat().st_nlink <= 1 and _inside(path, root)
    except OSError:
        return False


def _copy_output(folder, dest):
    """The regular files in a job's output/, kept in notes/outputs/. Links of every kind are skipped: one pointing at a
    key file would otherwise put its contents where the AI, and any sync of the notes folder, can read them."""
    src = Path(folder) / "output"
    root, copied = os.path.realpath(src), 0
    for here, dirs, names in os.walk(src, followlinks=False):
        dirs[:] = [d for d in dirs if _inside(Path(here) / d, root)]
        for name in sorted(names):
            path = Path(here) / name
            try:
                if not _plain_file(path, root) or path.stat().st_size > MAX_FILE_BYTES:
                    continue
                target = dest / path.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            except OSError as e:  # a locked file or a too-long path: the rest is still worth keeping
                log("error", error=f"couldn't keep {path.name} from a skill run: {e!r}")
                continue
            copied += 1
            if copied >= MAX_FILES:
                return copied
    return copied


def _prune(parent):
    """Delete the oldest entries of `parent` past KEEP: names start with a date, so name order is time order."""
    entries = sorted(parent.iterdir(), key=lambda p: p.name) if parent.is_dir() else []
    for old in entries[:-KEEP] if len(entries) > KEEP else []:
        if old.is_dir():
            shutil.rmtree(old, ignore_errors=True)
        else:
            old.unlink(missing_ok=True)


def _quiet(text):
    """AI text for a note, with its own "## " headings lowered so it can't pass for the note's Run note / Feedback."""
    return ("#" + text if text.startswith("## ") else text).replace("\n## ", "\n### ")


def _usage(usage):
    """The front-matter line for what the CLI reported ("" if it reported nothing). The cost is the API price of the
    tokens, not what a subscription is charged."""
    if not isinstance(usage, dict) or not usage:
        return ""
    cost = f", ${usage['cost_usd']:.4f} API-equivalent" if usage.get("cost_usd") else ""
    return (f"usage: {usage.get('input', 0)} in ({usage.get('cached', 0)} cached), {usage.get('output', 0)} out{cost}"
            " (as reported by the CLI)\n")


def record(skill_name, rec, folder):
    """Write the note for a finished run of `skill_name` (from its job record) and keep a copy of what it made."""
    _check(skill_name)
    started = rec.get("started") or time.time()
    stamp = f"{time.strftime('%Y-%m-%d-%H%M%S', time.localtime(started))}-{str(rec['id'])[-4:]}"
    out = Path(folder) / "output"
    run_note = out / "run-note.md"
    try:
        learned = run_note.read_text(encoding="utf-8", errors="replace").strip()[:2000] \
            if _plain_file(run_note, os.path.realpath(out)) else ""
    except OSError:
        learned = ""
    seconds = int((rec.get("finished") or time.time()) - started)
    head = (f"---\njob: {rec['id']}\nstatus: {rec.get('status', '')}\nbrain: {rec.get('engine', '')}\n"
            f"started: {time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(started))}\nseconds: {seconds}\n"
            f"files: {', '.join(rec.get('files') or [])}\n{_usage(rec.get('usage'))}---\n").replace("\r", " ")
    note = DIR / skill_name / f"{stamp}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    reply = _quiet((rec.get("reply") or "")[:REPLY_MAX])
    write_atomic(note, f"{head}{reply}\n\n## Run note\n{_quiet(learned)}\n\n## Feedback\n")  # first: the copy may fail
    _copy_output(folder, OUT / skill_name / stamp)
    _prune(DIR / skill_name)
    _prune(OUT / skill_name)
    return note


def _fit(text):
    """(status, the note shortened for a prompt): the reply is cut, but the run note and the user's feedback stay."""
    status = ""
    if text.startswith("---\n"):
        head, _, text = text[4:].partition("\n---\n")
        status = next((line[7:].strip() for line in head.splitlines() if line.startswith("status:")), "")
    cut = text.rfind("\n## Feedback")  # the last one: the user's own words come last
    feedback = text[cut:] if cut >= 0 else ""
    before = text[:cut] if cut >= 0 else text
    mid = before.rfind("\n## Run note")
    learned = before[mid:] if mid >= 0 else ""
    reply = before[:mid] if mid >= 0 else before
    return status, (reply[:SHOWN["reply"]] + learned[:SHOWN["run note"]] + feedback[:SHOWN["feedback"]]).strip()


def latest(skill_name):
    """The newest note of a skill for the Skills page: {"path", "status", "started", "usage"}, or None if it never ran."""
    _check(skill_name)
    folder = DIR / skill_name
    for path in sorted(folder.glob("*.md"), reverse=True)[:1] if folder.is_dir() else []:
        try:
            head = path.read_text(encoding="utf-8-sig", errors="replace").split("\n---\n")[0]
        except OSError:
            return None
        field = lambda key: next((x[len(key) + 1:].strip() for x in head.splitlines() if x.startswith(key + ":")), "")  # noqa: E731
        return {"path": str(path), "status": field("status"), "started": field("started"), "usage": field("usage")}
    return None


def recent(skill_name, n):
    """The newest `n` notes of a skill, newest first, each shortened to fit a prompt. "" when there are none."""
    _check(skill_name)
    folder = DIR / skill_name
    notes = sorted(folder.glob("*.md"), reverse=True)[:max(0, n)] if folder.is_dir() else []
    out = []
    for path in notes:
        try:
            status, body = _fit(path.read_text(encoding="utf-8-sig", errors="replace"))
            out.append(f"### Run {path.stem}{f' ({status})' if status else ''}\n{body}")
        except OSError as e:
            log("error", error=f"couldn't read run note {path.name}: {e!r}")
    return "\n\n".join(out)
