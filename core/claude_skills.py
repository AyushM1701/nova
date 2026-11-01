"""The skills and slash commands installed for Claude Code on this computer (~/.claude/skills, ~/.claude/commands and the
installed plugins), so the Skills page can list them as buttons. Nova starts Claude Code with only the project's settings
(core/brain.py), so Claude does not see these by name there: pressing one sends the AI the skill's own text, the way a
Nova skill (core/skills.py) is sent, and the guard still asks before anything risky."""
import json
import re
from pathlib import Path

ROOT = Path.home() / ".claude"
MAX_CHARS = 60000
FRONT = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def _parse(text):
    """(fields, body): the simple `key: value` lines of a front-matter block (a folded `>` or `|` value is joined)."""
    m = FRONT.match(text)
    if not m:
        return {}, text
    fields, key = {}, None
    for line in m.group(1).splitlines():
        if re.match(r"^[\w-]+:", line):
            key, _, value = line.partition(":")
            value = value.strip()
            fields[key.strip()] = "" if value in (">", "|", ">-", "|-") else value.strip("\"'")
        elif key and line.startswith((" ", "\t")):
            fields[key] = f"{fields[key]} {line.strip()}".strip()
    return fields, text[m.end():]


def _add(out, source, folder, path, fallback, label):
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return
    fields, _ = _parse(text)
    if fields.get("user-invocable", "").lower() == "false":  # meant for Claude to pick, not for a button
        return
    name = fields.get("name") or fallback
    out.append({"id": f"{source}:{path.relative_to(folder).as_posix()}", "name": f"{label}:{name}" if label else name,
                "description": re.sub(r"\s+", " ", fields.get("description", "")).strip()[:220], "source": label or "you",
                "path": str(path)})


def _tree(out, folder, label, source):
    if not folder.is_dir():
        return
    for p in sorted(folder.glob("skills/*/SKILL.md")):
        _add(out, source, folder, p, p.parent.name, label)
    for p in sorted(folder.glob("commands/*.md")):
        _add(out, source, folder, p, p.stem, label)


def all_skills():
    """Every skill and command, yours first, then each plugin's. A file that can't be read is left out."""
    out = []
    _tree(out, ROOT, "", "user")
    try:
        plugins = json.loads((ROOT / "plugins" / "installed_plugins.json").read_text(encoding="utf-8")).get("plugins", {})
    except (OSError, ValueError):
        plugins = {}
    for key, installs in plugins.items():
        for install in installs[:1] if isinstance(installs, list) else []:
            try:
                _tree(out, Path(install["installPath"]), key.split("@")[0], f"plugin-{key}")
            except (KeyError, TypeError, OSError):
                continue
    seen = set()  # the same plugin can be installed twice; one button each
    return [s for s in out if not (s["name"] in seen or seen.add(s["name"]))]


def load(skill_id):
    """(name, instructions, folder) of the skill with this id from the list above, or None. The id is looked up, never
    used as a path: what the window sends can't point anywhere else."""
    for s in all_skills():
        if s["id"] == skill_id:
            path = Path(s["path"])
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                return None
            return s["name"], _parse(text)[1].strip()[:MAX_CHARS], str(path.parent)
    return None
