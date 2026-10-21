"""Paths, settings and the activity log, shared by Nova and its app window.

config.json holds only what the user changed; everything else comes from config.default.json,
so new settings from an update appear automatically.
"""
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG, DEFAULTS = ROOT / "config.json", ROOT / "config.default.json"
LOGS, DATA, WORKSPACE = ROOT / "logs", ROOT / "data", ROOT / "workspace"
NOTES = WORKSPACE / "notes"
LOG_HOOKS = []  # Nova forwards every log entry to its open app window
KEEP_LOG_DAYS = 30


def write_private(path, text):
    """Write a key or token file only this user can read (macOS; shortcut: Windows relies on the folder's ACL)."""
    path.write_text(text, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def log(event, **fields):
    entry = {"t": time.time(), "event": event, **fields}
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / time.strftime("nova-%Y-%m-%d.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    for hook in LOG_HOOKS:
        hook(entry)


def read_history(kinds, limit=600):
    """The newest log entries of these kinds, newest first."""
    items = []
    for f in sorted(LOGS.glob("nova-*.jsonl"), reverse=True):
        for line in reversed(f.read_text(encoding="utf-8", errors="replace").splitlines()):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("event") in kinds:
                items.append(entry)
                if len(items) >= limit:
                    return items
    return items


def prune_logs():
    cutoff = time.time() - KEEP_LOG_DAYS * 86400
    for f in LOGS.glob("nova-*.jsonl"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def merged(base, override):
    out = dict(base)
    for k, v in override.items():
        out[k] = merged(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def overrides(cfg, base):
    """Only the values that differ from the defaults."""
    out = {}
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            sub = overrides(v, base[k])
            if sub:
                out[k] = sub
        elif k not in base or base[k] != v:
            out[k] = v
    return out


def defaults():
    return json.loads(DEFAULTS.read_text(encoding="utf-8"))


def user_config():
    """The user's own overrides; raises ValueError if config.json isn't valid JSON."""
    return json.loads(CONFIG.read_text(encoding="utf-8-sig")) if CONFIG.exists() else {}


def load_config():
    """(settings, error). A broken config.json falls back to the defaults instead of stopping Nova."""
    try:
        return merged(defaults(), user_config()), None
    except ValueError as e:
        return defaults(), f"config.json has a mistake ({e}); using the default settings until it is fixed."


def save_config(cfg):
    try:
        user_config()
    except ValueError:  # keep the hand-edited file the user may still want
        CONFIG.replace(CONFIG.with_suffix(".broken.json"))
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(overrides(cfg, defaults()), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG)  # atomic: Nova's settings watcher never reads half a file
