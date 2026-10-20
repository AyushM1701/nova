#!/bin/bash
# Nova setup for macOS. Run from the folder you cloned:   ./setup.sh
# Safe to run again: it updates everything in place.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
APP="$HOME/Applications/Nova.app"
AGENT="$HOME/Library/LaunchAgents/com.nova.assistant.plist"

step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }
ask() { read -r -p "$1 [Y/n] " a; [[ ! "$a" =~ ^([nN]|no)$ ]]; }
has() { command -v "$1" >/dev/null 2>&1; }

find_python() {
  # Python 3.11-3.13 with Tk (the speech libraries don't ship wheels for newer versions yet)
  for p in python3.13 python3.12 python3.11 python3 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
    if has "$p" && "$p" -c 'import sys, tkinter; assert (3, 11) <= sys.version_info[:2] <= (3, 13)' 2>/dev/null; then
      command -v "$p"; return
    fi
  done
}

echo "Nova setup: everything is installed inside $ROOT (plus the speech models in your user cache)."

step "1/6  Python"
BASE="$(find_python || true)"
if [ -z "$BASE" ]; then
  if has brew && ask "Python 3.12 with Tk isn't installed. Install it with Homebrew?"; then
    brew install python@3.12 python-tk@3.12
    BASE="$(find_python || true)"
  fi
  [ -n "$BASE" ] || { echo "Install Python 3.12 from https://www.python.org/downloads/macos/ and run setup again."; exit 1; }
fi
echo "Using $BASE"

step "2/6  Nova's own Python environment and libraries"
[ -x "$PY" ] || "$BASE" -m venv "$VENV"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$ROOT/requirements.txt"
chmod +x "$ROOT/helpers/clipboard.sh"

step "3/6  Speech models (downloaded once, then used offline)"
"$PY" -c "from faster_whisper.utils import download_model as d; d('small'); d('large-v3-turbo'); print('Models ready.')"
mkdir -p "$ROOT/data" && touch "$ROOT/data/models-ready"

step "4/6  Connect an AI: Claude Code or Codex"
echo "  1) Claude Code (Anthropic)   installed: $(has claude && echo yes || echo no)"
echo "  2) Codex (OpenAI)            installed: $(has codex && echo yes || echo no)"
read -r -p "Which one should Nova use? [1/2] " choice
ENGINE=claude; [ "$choice" = "2" ] && ENGINE=codex
if ! has "$ENGINE"; then
  if ! has npm && has brew && ask "$ENGINE needs Node.js. Install it with Homebrew?"; then brew install node; fi
  if has npm; then
    PACKAGE="@anthropic-ai/claude-code"; [ "$ENGINE" = codex ] && PACKAGE="@openai/codex"
    if ask "Install the $ENGINE CLI ($PACKAGE) with npm?"; then npm install -g "$PACKAGE"; fi
  else
    echo "Install Node.js from https://nodejs.org to add $ENGINE later."
  fi
fi
if has "$ENGINE"; then
  if [ "$ENGINE" = claude ]; then
    claude auth status >/dev/null 2>&1 || { echo "Log in to Claude:"; claude auth login; }
  else
    codex login status >/dev/null 2>&1 || { echo "Log in to Codex:"; codex login; }
  fi
else
  printf '\033[33mSkipped: Nova will still do dictation; run setup again to connect an AI.\033[0m\n'
fi
"$PY" - "$ROOT/config.json" "$ENGINE" <<'EOF'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]); c = json.loads(p.read_text()) if p.exists() else {}
c.setdefault("brain", {})["engine"] = sys.argv[2]
p.write_text(json.dumps(c, indent=2))
EOF

step "5/6  Nova.app and start at login"
# A tiny app bundle, so macOS asks for microphone / keyboard permissions for "Nova"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/MacOS/Nova" <<EOF
#!/bin/bash
cd "$ROOT" && exec "$PY" "$ROOT/nova.py"
EOF
chmod +x "$APP/Contents/MacOS/Nova"
(cd "$ROOT" && "$PY" -m core.icon "$APP/Contents/Resources/Nova.icns")
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Nova</string>
  <key>CFBundleIdentifier</key><string>com.nova.assistant</string>
  <key>CFBundleExecutable</key><string>Nova</string>
  <key>CFBundleIconFile</key><string>Nova</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Nova listens for "Hey Nova" and your requests. Audio never leaves this Mac.</string>
  <key>NSAppleEventsUsageDescription</key><string>Nova controls apps when you ask it to.</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
if ask "Start Nova automatically when you log in?"; then
  mkdir -p "$(dirname "$AGENT")"
  cat > "$AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.nova.assistant</string>
  <key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-a</string><string>$APP</string></array>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF
  launchctl bootstrap "gui/$(id -u)" "$AGENT" 2>/dev/null || true
else
  rm -f "$AGENT"
fi

step "6/6  Permissions and first start"
(cd "$ROOT" && "$PY" tests.py)
cat <<EOF

macOS will ask for permissions the first time. Allow "Nova" in System Settings > Privacy & Security:
  - Microphone          (to hear you)
  - Accessibility       (to type dictation and press media keys)
  - Input Monitoring    (for the Cmd+Shift+Space shortcut)
Opening those settings now. After you allow them, quit Nova from its menu bar icon and open it again.
EOF
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" || true
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent" || true
open -a "$APP"
printf '\n\033[32mNova is running: its icon is in the menu bar. Say "Hey Nova", press Cmd+Shift+Space,\nor click the small bar at the bottom of the screen. Uninstall any time with ./uninstall.sh\033[0m\n'
