# Nova

A voice assistant for Windows and macOS. Say **"Hey Nova"**, press a shortcut or click the small bar at the bottom of your screen, then talk. Nova runs your request through **Claude Code** or **OpenAI Codex**, whichever you connect, and answers out loud. It also does Wispr Flow-style **dictation**: speak, and clean text is typed into whatever app you're in.

- **Assistant mode:** "Open Spotify and play something chill", "in my portfolio project, fix the navbar on mobile", "copy my resume to the clipboard", "what's the weather in Goa?"
- **Dictation mode:** filler words ("um", "uh") are removed, self-corrections are applied ("meet at 6, no wait, 7" becomes "meet at 7"), and Hindi or Hinglish is written in English letters.
- **Command mode:** select text in any app, press the shortcut and say "make this more formal", "translate it to Hindi" or "fix the grammar". The selection is rewritten in place.
- **Knows what you're looking at:** "what's this error on my screen?" gives the AI a screenshot to look at, and every spoken request tells it which app you're in. You can turn this off.
- **Conversational:** talk over Nova to interrupt it and redirect it; when it asks you something ("Want me to run the tests?") it listens for your answer without "Hey Nova".
- **Remembers:** tell it "remember I use pnpm" and it keeps that in `workspace/notes/memory.md` for every later request; see and delete entries on the window's Memory page. It also remembers your last 20 copies (in memory only, skipping passwords and keys), so "paste the link I copied earlier" works.
- **Point at things:** "turn this card into a Tailwind component" dims the screen so you can drag a box around what you mean; other questions about your screen send just the window you're in. Highlight code and ask "where else is this function called?" and Nova passes the selection along.
- **Routines:** "start my day" gives a short spoken rundown (each project's branch and uncommitted changes, open tasks in your notes, follow-ups from memory). Add your own in Settings → Routines, e.g. "deep code mode" = "pause music, open VS Code in portfolio, run npm run dev".
- **Keeps an eye on long jobs:** run `python <nova folder>/helpers/watch.py npm run build` and keep working; Nova says when it's done, or explains why it failed and offers to fix it. Turn on Settings → AI → "Tell me when Claude Code finishes" to hear when a Claude Code task you started in a terminal is done.
- **Listens to your computer (Windows):** say "listen to my computer" (or use the tray menu) during a video, lecture or call, then ask "what did they just say?" or "grab the command they mentioned". The transcript covers the last 15 minutes, stays in memory and is never saved; "stop listening" ends it.
- **Uses your real browser (Windows):** Opera GX, Brave, Vivaldi or Opera, inside your own profile with your logins, through a small Nova extension that only talks to Nova on this computer. "Open my GitHub notifications and summarise them", "fill this form with my address", "in Brave, find the cheapest flight to Goa". Nova asks before anything that submits, buys, posts or sends, and never types passwords, card numbers or one-time codes. Turn it on in Settings → Browsers (or the tray menu → Browsers…); a Nova panel in the browser shows the same live conversation, with Allow / Deny.
- **Never stuck at a limit:** when Claude Code or Codex reaches its usage limit, Nova can switch to a free Google Gemini key (Settings → AI → Backup brain) until it resets. Its commands go through the same safety guard. On Google's free tier your requests may be used to improve Google's products, so it's off until you add a key.
- **The Nova window:** click the tray icon (in the hidden icons area, the ^ next to the clock; in the menu bar on a Mac). It has a chat for typed requests, your history, your dictionary and every setting. You can also ask Nova to change itself: "use Ctrl+Shift+N as my shortcut".

## Install

You need about 3 GB of free space and an internet connection for the first setup. Setup installs everything else it needs and asks before installing anything system-wide. You don't need git or a terminal.

### Step-by-step (no git needed)

**Windows 10/11**

1. On the [GitHub page](https://github.com/AyushM1701/nova), click the green **Code** button, then **Download ZIP**.
2. Right-click the downloaded `nova-main.zip` → **Extract All…** and pick a folder you'll keep, for example `Documents\nova`. Nova runs from this folder, so don't delete it afterwards.
3. Open the folder and double-click **`setup.cmd`**. If Windows shows "Windows protected your PC" or a security warning, click **More info → Run anyway** (or **Run**).
4. A Nova setup window shows each step. The first run downloads about 2.5 GB and takes 5–15 minutes. If Python 3.11–3.13 isn't installed, setup offers to install it for you.
5. When it says "Nova is installed", Nova opens its first-run screens (microphone, AI, shortcut). See [First run](#first-run) below.

**macOS 12+ (Apple Silicon or Intel)**

1. Open **Terminal** (press Cmd+Space, type "Terminal", press Enter).
2. Paste this line and press Enter. It downloads Nova into a `nova-main` folder in your home folder and starts setup:

   ```bash
   cd ~ && curl -fsSL https://github.com/AyushM1701/nova/archive/refs/heads/main.tar.gz | tar xz && cd nova-main && bash setup.sh
   ```

3. If Python 3.11–3.13 with Tk isn't installed, setup offers to install it with Homebrew, or tells you to get it from [python.org](https://www.python.org/downloads/macos/) and run the same line again.
4. A Nova setup window shows the rest of the progress, then opens Nova from `~/Applications/Nova.app`. Nova runs from `~/nova-main`, so keep that folder.

Prefer a ZIP? Click **Code → Download ZIP**, unpack it, and double-click **`setup.command`**. Because it was downloaded, macOS blocks it the first time ("Apple could not verify…"): click **Done**, open **System Settings → Privacy & Security**, scroll down to *"setup.command" was blocked*, click **Open Anyway**, enter your password and click **Open**. (On macOS 14 and earlier, right-click → **Open** does the same.)

If you use git, `git clone https://github.com/AyushM1701/nova.git`, then run `setup.cmd` (Windows) or `./setup.sh` (Mac) in the folder; `git pull` and running setup again updates Nova.

Setup:

1. Finds or installs Python 3.11–3.13 (it asks before installing anything).
2. Creates Nova's own Python environment inside the folder and installs its libraries.
3. Downloads the speech models (about 2 GB, once), plus GPU support if you have an NVIDIA card.
4. Adds Nova to the Start menu or `~/Applications`, runs Nova's self-checks and starts it.

### First run

Nova then shows its own first-run screens:

1. **Microphone:** a live level meter shows that Nova hears you.
2. **Brain:** pick **Claude Code** or **Codex**. If it isn't installed, one click installs it (and Node.js if needed); **Sign in** opens its login (your Claude or ChatGPT account). Skip it and dictation still works.
3. **Shortcut:** keep Ctrl+Alt+Space or press a new one, and turn "Hey Nova" on or off.
4. **Start at login**, and a first try.

**On a Mac**, the last screen has one button per permission (Microphone, Accessibility, Input Monitoring, Screen Recording); each opens that page of System Settings → Privacy & Security. Turn on "Nova" in each, then quit Nova from the menu bar and open it again.

**Try it:** press the shortcut (or say "Hey Nova") and say "what time is it?". Then try "open YouTube", and, with an AI connected, "what's the weather in Goa?".

To update, download the new ZIP into the same folder (or `git pull`) and run setup again; it restarts Nova on the new code. On a Mac installed with the Terminal line, run the same line again: it replaces the files in `~/nova-main` and keeps your settings, history and downloaded models. To see the first-run screens again, use Settings → Advanced → Run setup. Uninstall with `uninstall.cmd` (Windows) or `./uninstall.sh` (Mac).

## Using it

| Do this | What happens |
|---|---|
| Say "Hey Nova", press **Ctrl+Alt+Space** (Mac: **Cmd+Shift+Space**), or click the bar | Nova listens. Press again to stop early, or press while it's working to cancel. |
| "Hey Nova, play some music" in one breath | Runs straight away |
| Esc | Cancel; when Nova is asking for permission, Esc denies |
| "switch to dictation" / "switch to assistant" | Change mode |
| "new conversation" | Forget the follow-up context |
| "add Kubernetes to my dictionary" | Teaches the speech recognizer a word |
| "turn it up a bit", "volume 40", "skip this song", "open VS Code", "open YouTube", "what time is it?", "set a timer for 5 minutes", "lock my computer" | Done instantly on your computer: no AI call, no quota used |
| Select text, then "make this shorter" (dictation mode) | Rewrites the selection in place |
| Click the tray icon, or right-click the bar | Opens the Nova window |

**The bar** at the bottom-centre shows what Nova is doing:

- a waveform while it listens
- dots while it thinks
- a ripple while it talks
- amber when it needs your OK

Hover over it to see the shortcut. Settings → General → **Where the bar sits** moves it to the top of the screen; on a MacBook with a notch it then hangs from the notch and grows out of it while Nova listens, thinks and talks, like the Dynamic Island. Clicking the tray / menu bar icon opens the Nova window; its menu has mode, **Brain** (switch between Claude Code and Codex), pause, settings and quit.

## What stays on your computer

- **Speech recognition** (Whisper, via faster-whisper) and the **"Hey Nova" wake word** run entirely on your machine. Audio is never uploaded, and nothing you say is kept unless it starts with "Hey Nova" or you pressed the shortcut.
- **Spoken replies** use a natural neural voice (Kokoro, run by sherpa-onnx) on your own computer, or your operating system's built-in voices (Windows SAPI, macOS `say`) if you prefer them or the voice isn't downloaded.
- **Settings, logs, notes and history** live in the Nova folder (`config.json`, `logs/`, `workspace/notes/`). History is kept for 30 days and can be cleared on the History page. There is no Nova server, account or analytics.
- **Text only goes out to your chosen AI:** your request and, for long or tricky dictations, the dictated text go to Claude Code or Codex, because that's where the AI runs. With "Share what you're looking at" on (Settings → Privacy & safety), a spoken request also says which app or window you're in, and a request about your screen comes with a screenshot (saved as `workspace/screen.png`). Nova turns off Claude Code's telemetry and error reporting, and turns off the speech-model downloader's telemetry and online checks after setup.

## Safety

**In the browser**, Nova checks the real element on the page (not what the AI says it is): reading, navigating, scrolling and ordinary clicks are allowed; clicks that submit, buy, post, send or delete, pressing Enter in a form, downloads and page scripts ask you first; typing into password, card or one-time-code fields is blocked. Page text is treated as data, never as instructions.

**On the computer**:

Every command, file edit and file read that Claude Code or Codex makes passes through Nova's guard (`guard/guard.py`) first:

- **Allowed:** reading files, opening apps and websites, media, edits inside your Claude Code / Codex projects, `git status/diff/commit`, running tests.
- **Asks you first:** deleting or moving files, `git push`, installing software, closing apps, shutting down, `sudo`, system settings, uploads, starting a program with hidden arguments (`Start-Process git -ArgumentList push`), writing outside your projects, changing Nova's own settings, and anything it doesn't recognise. You see the exact command on the card and in the Nova window's chat; press the shortcut or **Allow** to allow, Esc or **Deny** to deny. No answer in 30 s means no.
- **Never:** wiping disks or system folders, disabling the firewall/Defender/SIP, changing user accounts, reading saved passwords, keychains or SSH keys, or `curl … | sh`.

If the guard fails, Nova isn't running, or the CLI skips the guard, the action is denied, or Nova warns you. Codex additionally runs in its `workspace-write` sandbox. The rules are tested by `tests.py`.

## Settings

Change them in the Nova window → **Settings** (they apply within a second, no restart), by asking Nova ("keep the reply card up for 10 seconds"), or by editing `config.json`. `config.json` only holds the values you changed; everything else comes from `config.default.json`, so new settings from an update reach you automatically.

| Setting | Default | Meaning |
|---|---|---|
| `hotkey` | Ctrl+Alt+Space / Cmd+Shift+Space | e.g. `"ctrl+shift+n"` |
| `wake_word` | `true` | Listen for "Hey Nova" |
| `overlay.position` | `bottom` | `"top"` puts the bar at the top of the screen (from the notch on a MacBook) |
| `voice.tts_engine` | `kokoro` | `"kokoro"` (natural voice) or `"system"` |
| `voice.kokoro_voice` / `voice.tts_speed` | `af_heart` / `1.0` | Natural voice, e.g. `"bm_george"` (British man); speed 0.75 to 1.4 |
| `voice.tts_voice` | system default | System voice name, e.g. `"Microsoft Zira Desktop"` or `"Rishi"` (Mac) |
| `voice.language` | `auto` | Or `"en"`, `"hi"`… |
| `brain.engine` | set by setup | `"claude"` or `"codex"` |
| `brain.claude_model` / `brain.codex_model` | CLI default | Model for assistant requests |
| `brain.codex_sandbox` | `workspace-write` | Use `danger-full-access` if Codex's sandbox blocks opening apps (the guard still applies) |
| `dictation.editing` | `light` | `verbatim`, `light` or `medium` |
| `dictation.dictionary` / `replacements` | | Words to spell right, e.g. `{"wisper": "Wispr"}` |
| `projects.aliases` | | Spoken nicknames, e.g. `{"my site": "portfolio"}` |
| `projects.folders` | `[]` | Folders where Nova creates and edits files without asking, e.g. `["D:\\projects"]` (Settings → AI). Folders holding your Claude Code / Codex projects count automatically. A drive, your user folder, Documents, system folders and Nova's own folder are refused |
| `voice.barge_in` | `true` | Talk while Nova answers to interrupt it |
| `brain.auto_model` | `true` | Quick actions use Haiku; "use opus to…" picks the model for one request |
| `brain.clipboard_history` | `true` | Remember your last 20 copies, in memory only |
| `browser.default` / `browser.enabled` | `opera-gx` / none | Which browsers Nova is set up in; say "in Brave" for one request, "add Vivaldi" / "stop using Brave" to change |
| `routines` | `{}` | Spoken routines, e.g. `{"deep code mode": "pause music, open VS Code in portfolio"}` |
| `brain.fallback_model` | `gemini-flash-latest` | The backup brain's Gemini model (the key itself lives in `data/fallback.key`) |
| `brain.screen_context` | `true` | Tell the AI which app you're in, and send a screenshot when you ask about your screen |

## Speed

- **Windows with an NVIDIA GPU:** speech takes about 0.3 s.
- **CPU (and every Mac):** English takes 1–3 s with the `small` model; Hindi is re-transcribed with the larger model, which takes several seconds.
- **The AI step:** a request to the AI takes 5–30 s, depending on the task.

## Troubleshooting

- **No icon?** On Windows, click the ^ next to the clock. Nova may already be running; only one copy can run at a time.
- **The shortcut does nothing (Mac):** allow Nova under Input Monitoring and Accessibility, then restart it.
- **"No AI connected":** open the Nova window → Settings → AI, and install or sign in to Claude Code or Codex there.
- **Setup stopped:** the setup window says why; the full output is in `data/setup.log`.
- **Logs:** Nova window → Settings → Advanced → Logs. Every request, reply and guard decision is in `logs/nova-YYYY-MM-DD.jsonl`.

## Project layout

```
nova.py               app: tray, shortcut, bar, voice commands, wiring, the window's control channel
core/app.py, app.html the Nova window (pywebview): first-run setup, chat, history, dictionary, settings
core/config.py        settings (defaults plus your changes) and the activity log
core/system.py        everything that differs between Windows and macOS
core/audio.py         microphone capture with silence detection
core/stt.py           speech to text (faster-whisper, GPU when available)
core/wake.py          "Hey Nova" wake word
core/cleanup.py       dictation cleanup: fillers, self-corrections, Hinglish
core/brain.py         Claude Code and Codex adapters
core/bar.py           the bottom-centre bar
core/overlay.py       the card for replies and approvals
core/clipboard.py     keeps your clipboard intact around dictation
core/tts.py           spoken replies: the natural Kokoro voice, or system voices
guard/guard.py        safety hook for Claude Code and Codex
core/browser.py       the browser bridge, its safety rules and the extension installer
browser/extension/    the Nova extension (Chromium, unpacked; never published to a store)
helpers/              clipboard helpers, the browser MCP server, the command watcher and Claude Code hook
setup.* / uninstall.* installers (setup.command: double-click setup for Finder)
tests.py              self-checks (python tests.py)
```

## License

MIT. See [LICENSE](LICENSE).
