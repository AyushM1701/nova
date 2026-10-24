"""Settings → Advanced → Save diagnostics: a zip to attach to a GitHub issue, made on this computer and sent nowhere.

What you said, Nova's replies, the commands it ran, your dictionary and your folders stay out: only which events
happened, errors, and settings with personal lists replaced by their length. Your home folder becomes "~".
"""
import json
import platform
import sys
import time
import zipfile
from pathlib import Path

from core.config import CONFIG, LOGS, WORKSPACE, user_config

# log fields that say what happened, never what was said or run
FIELDS = {"t", "event", "error", "mode", "source", "via", "brain", "stt_device", "tool", "tier", "decision", "ok",
          "allowed", "timed_out", "browser", "engine", "status", "duration", "verdict"}
PERSONAL = {"dictionary", "replacements", "aliases", "folders", "exclude", "routines", "actions", "custom_stt_url",
            "whisper_cpp_server", "whisper_cpp_model", "folder", "tts_voice"}
DAYS = 7


def scrub(value, home=str(Path.home())):
    if isinstance(value, dict):
        return {k: f"[{len(v)} set]" if k in PERSONAL and isinstance(v, (dict, list)) else
                "[set]" if k in PERSONAL and v else scrub(v, home) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, home) for v in value]
    if isinstance(value, str):
        for h in {home, home.replace("\\", "/")}:
            value = value.replace(h, "~")
        return value[:300]
    return value


def lines(logs=LOGS, days=DAYS):
    """The last `days` of the log, each entry cut down to FIELDS."""
    out, cutoff = [], time.time() - days * 86400
    for f in sorted(logs.glob("nova-*.jsonl")):
        if f.stat().st_mtime < cutoff:
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                out.append(json.dumps(scrub({k: v for k, v in entry.items() if k in FIELDS}), ensure_ascii=False))
    return out


def save(folder=WORKSPACE, version=""):
    """Write the zip into `folder` and return its path."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / time.strftime("nova-diagnostics-%Y%m%d-%H%M%S.zip")
    try:
        settings = user_config() if CONFIG.exists() else {}
    except ValueError:
        settings = {"error": "config.json isn't valid JSON"}
    about = (f"Nova {version}\n{platform.platform()} ({platform.machine()})\nPython {sys.version.split()[0]}\n\n"
             "What you said, Nova's replies, commands and your personal lists are not in this file.\n")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("about.txt", about)
        z.writestr("settings.json", json.dumps(scrub(settings), indent=2, ensure_ascii=False))
        z.writestr("log.jsonl", "\n".join(lines()) + "\n")
    return path
