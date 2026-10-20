# Nova

A voice assistant for Windows and macOS. Say **"Hey Nova"**, press a shortcut or click the small bar at the bottom of your screen, then talk. Nova runs your request through **Claude Code** or **OpenAI Codex**, whichever you connect, and answers out loud. It also does Wispr Flow-style **dictation**: speak, and clean text is typed into whatever app you're in.

- **Assistant mode:** "Open Spotify and play something chill", "in my portfolio project, fix the navbar on mobile", "copy my resume to the clipboard", "what's the weather in Goa?"
- **Dictation mode:** filler words ("um", "uh") are removed, self-corrections are applied ("meet at 6, no wait, 7" becomes "meet at 7"), and Hindi or Hinglish is written in English letters.
- **Lives in the tray:** on Windows its icon is in the hidden icons area (the ^ next to the clock); on a Mac it's in the menu bar. It starts when you log in.

## Install

You need about 3 GB of free space. Setup installs everything else it needs and asks before installing anything system-wide.

**Windows 10/11**

```bash
git clone https://github.com/AyushM1701/nova.git
```

Then double-click `setup.cmd` in the `nova` folder.

**macOS 12+ (Apple Silicon or Intel)**

```bash
git clone https://github.com/AyushM1701/nova.git && cd nova && ./setup.sh
```

Setup:

1. Finds or installs Python 3.11–3.13.
2. Creates Nova's own Python environment inside the folder.
3. Downloads the speech models (about 2 GB, once), plus GPU support if you have an NVIDIA card.
4. Asks whether to use **Claude Code** or **Codex**. If the chosen CLI isn't installed it installs it, then opens its login (your Claude or ChatGPT/OpenAI account).
5. Adds Nova to the Start menu or `~/Applications`, and to start-at-login if you agree.
6. Runs Nova's self-checks and starts it.

**On a Mac**, allow "Nova" under System Settings → Privacy & Security → **Microphone**, **Accessibility** and **Input Monitoring**, then quit Nova from the menu bar and open it again.

Run setup again at any time to update after a `git pull` or to switch AI. Uninstall with `uninstall.cmd` (Windows) or `./uninstall.sh` (Mac).

## Using it

| Do this | What happens |
|---|---|
| Say "Hey Nova", press **Ctrl+Alt+Space** (Mac: **Cmd+Shift+Space**), or click the bar | Nova listens. Press again to stop early, or press while it's working to cancel. |
| "Hey Nova, play some music" in one breath | Runs straight away |
| Esc | Cancel; when Nova is asking for permission, Esc denies |
| "switch to dictation" / "switch to assistant" | Change mode |
| "new conversation" | Forget the follow-up context |
| "add Kubernetes to my dictionary" | Teaches the speech recognizer a word |
| "pause", "next song", "volume 40", "mute" | Handled instantly on your computer; the AI isn't called |

**The bar** at the bottom-centre shows what Nova is doing:

- a waveform while it listens
- dots while it thinks
- a ripple while it talks
- amber when it needs your OK

The tray / menu bar icon has: mode, **Brain** (switch between Claude Code and Codex), pause, logs, settings and quit.

## What stays on your computer

- **Speech recognition** (Whisper, via faster-whisper) and the **"Hey Nova" wake word** run entirely on your machine. Audio is never uploaded, and nothing you say is kept unless it starts with "Hey Nova" or you pressed the shortcut.
- **Spoken replies** use your operating system's built-in voices (Windows SAPI, macOS `say`).
- **Settings, logs, notes and history** live in the Nova folder (`config.json`, `logs/`, `workspace/notes/`). There is no Nova server, account or analytics.
- **Text only goes out to your chosen AI:** your request and, for long or tricky dictations, the dictated text go to Claude Code or Codex, because that's where the AI runs. Nova turns off Claude Code's telemetry and error reporting, and turns off the speech-model downloader's telemetry and online checks after setup.

## Safety

Every command, file edit and file read that Claude Code or Codex makes passes through Nova's guard (`guard/guard.py`) first:

- **Allowed:** reading files, opening apps and websites, media, edits inside your Claude Code / Codex projects, `git status/diff/commit`, running tests.
- **Asks you first:** deleting or moving files, `git push`, installing software, closing apps, shutting down, `sudo`, system settings, uploads, writing outside your projects, and anything it doesn't recognise. You see the exact command; press the shortcut to allow or Esc to deny. No answer in 30 s means no.
- **Never:** wiping disks or system folders, disabling the firewall/Defender/SIP, changing user accounts, reading saved passwords, keychains or SSH keys, or `curl … | sh`.

If the guard fails, Nova isn't running, or the CLI skips the guard, the action is denied, or Nova warns you. Codex additionally runs in its `workspace-write` sandbox. The rules are tested by `tests.py`.

## Settings

Edit them from the tray menu → **Edit settings**. Your `config.json` only needs the values you change; everything else comes from `config.default.json`.

| Setting | Default | Meaning |
|---|---|---|
| `hotkey` | Ctrl+Alt+Space / Cmd+Shift+Space | e.g. `"ctrl+shift+n"` (restart Nova after changing) |
| `wake_word` | `true` | Listen for "Hey Nova" |
| `voice.tts_voice` | system default | A voice name, e.g. `"Microsoft Zira Desktop"` or `"Rishi"` (Mac) |
| `voice.language` | `auto` | Or `"en"`, `"hi"`… |
| `brain.engine` | set by setup | `"claude"` or `"codex"` |
| `brain.claude_model` / `brain.codex_model` | CLI default | Model for assistant requests |
| `brain.codex_sandbox` | `workspace-write` | Use `danger-full-access` if Codex's sandbox blocks opening apps (the guard still applies) |
| `dictation.editing` | `light` | `verbatim`, `light` or `medium` |
| `dictation.dictionary` / `replacements` | | Words to spell right, e.g. `{"wisper": "Wispr"}` |
| `projects.aliases` | | Spoken nicknames, e.g. `{"my site": "portfolio"}` |

## Speed

- **Windows with an NVIDIA GPU:** speech takes about 0.3 s.
- **CPU (and every Mac):** English takes 1–3 s with the `small` model; Hindi is re-transcribed with the larger model, which takes several seconds.
- **The AI step:** a request to the AI takes 5–30 s, depending on the task.

## Troubleshooting

- **No icon?** On Windows, click the ^ next to the clock. Nova may already be running; only one copy can run at a time.
- **The shortcut does nothing (Mac):** allow Nova under Input Monitoring and Accessibility, then restart it.
- **"No AI connected":** run setup again and pick Claude Code or Codex. Check the login with `claude auth status` / `codex login status`.
- **Logs:** tray menu → Open log folder. Every request, reply and guard decision is in `logs/nova-YYYY-MM-DD.jsonl`.

## Project layout

```
nova.py               app: tray, shortcut, bar, voice commands, wiring
core/system.py        everything that differs between Windows and macOS
core/audio.py         microphone capture with silence detection
core/stt.py           speech to text (faster-whisper, GPU when available)
core/wake.py          "Hey Nova" wake word
core/cleanup.py       dictation cleanup: fillers, self-corrections, Hinglish
core/brain.py         Claude Code and Codex adapters
core/bar.py           the bottom-centre bar
core/overlay.py       the card for replies and approvals
core/clipboard.py     keeps your clipboard intact around dictation
core/tts.py           spoken replies with system voices
guard/guard.py        safety hook for Claude Code and Codex
helpers/              clipboard copy helpers the AI can call
setup.* / uninstall.* installers
tests.py              self-checks (python tests.py)
```
