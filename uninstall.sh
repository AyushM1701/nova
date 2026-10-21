#!/bin/bash
# Remove Nova from macOS: stops it, removes Nova.app and start-at-login, and optionally its libraries and models.
# Your settings, logs and notes in this folder are left alone; delete the folder to remove those too.
ROOT="$(cd "$(dirname "$0")" && pwd)"
AGENT="$HOME/Library/LaunchAgents/com.nova.assistant.plist"
ask() { read -r -p "$1 [y/N] " a; [[ "$a" =~ ^([yY]|yes)$ ]]; }

pkill -f "$ROOT/nova.py" 2>/dev/null
pkill -f "$ROOT/.venv/bin/python.* -m core.app" 2>/dev/null  # the Nova window
launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null
rm -rf "$HOME/Applications/Nova.app" "$AGENT"
echo "Nova stopped; Nova.app and start-at-login removed."

if ask "Also delete Nova's Python libraries (.venv)?"; then rm -rf "$ROOT/.venv"; fi
CACHE="$HOME/.cache/huggingface/hub"
if [ -d "$CACHE/models--Systran--faster-whisper-small" ] && ask "Also delete the downloaded speech models (about 2 GB)?"; then
  rm -rf "$CACHE/models--Systran--faster-whisper-small" "$CACHE/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
fi
if [ -d "$ROOT/data/tts" ] && ask "Also delete Nova's natural voice (about 380 MB)?"; then rm -rf "$ROOT/data/tts"; fi
echo "Done. Claude Code / Codex were left installed; remove them separately if you want."
