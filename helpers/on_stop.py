"""Claude Code "Stop" hook: tells Nova when Claude finishes a task you started in a terminal, so you hear about it
while working elsewhere. Settings → AI → "Tell me when Claude Code finishes" installs it in
~/.claude/settings.json. Nova's own requests don't trigger it (they don't load your user settings).
Stdlib only, and it never blocks or changes what Claude does."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notify import send  # noqa: E402


def last_reply(transcript):
    """The text of Claude's final message in a Claude Code transcript (JSON lines)."""
    try:
        with open(transcript, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") == "assistant":
            parts = (entry.get("message") or {}).get("content") or []
            text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
            if text.strip():
                return text.strip()[:1500]
    return ""


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
    except ValueError:
        return
    if data.get("stop_hook_active"):  # Claude is continuing because of another Stop hook: wait for the real end
        return
    send({"event": "claude_done", "cwd": data.get("cwd") or os.getcwd(),
          "text": last_reply(data.get("transcript_path") or "")})


if __name__ == "__main__":
    main()
