#!/bin/bash
# Nova setup for macOS. Run from the folder you cloned:   ./setup.sh
# Finds (or installs) Python, then a setup window shows the rest; Nova's own screens handle the AI, shortcut and permissions.
# Safe to run again: it updates everything in place.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }
ask() { read -r -p "$1 [Y/n] " a; [[ ! "$a" =~ ^([nN]|no)$ ]]; }
has() { command -v "$1" >/dev/null 2>&1; }

find_python() {
  # Python 3.11-3.13 with Tk (the speech libraries don't ship wheels for newer versions yet)
  for p in python3.13 python3.12 python3.11 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 python3; do
    # /usr/bin/python3 without the developer tools is a stub that pops an "install tools?" dialog (and is 3.9 anyway)
    [ "$(command -v "$p")" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1 && continue
    if has "$p" && "$p" -c 'import sys, tkinter; assert (3, 11) <= sys.version_info[:2] <= (3, 13)' 2>/dev/null; then
      command -v "$p"; return
    fi
  done
}

echo "Nova setup: everything is installed inside $ROOT (plus the speech models in your user cache)."

step "Python"
BASE="$(find_python || true)"
if [ -z "$BASE" ]; then
  if has brew && ask "Python 3.12 with Tk isn't installed. Install it with Homebrew?"; then
    brew install python@3.12 python-tk@3.12
    BASE="$(find_python || true)"
  fi
  [ -n "$BASE" ] || { echo "Install Python 3.12 from https://www.python.org/downloads/macos/ and run setup again."; exit 1; }
fi
echo "Using $BASE. Setup continues in the Nova setup window."
"$BASE" "$ROOT/helpers/setup_window.py"
