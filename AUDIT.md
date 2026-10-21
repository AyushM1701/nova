# Nova audit — 2026-10-21

Scope: every tracked and untracked source file (nova.py, core/*, guard/*, helpers/*, browser/extension/*, setup/uninstall scripts, tests.py, README, config). About 8,000 lines, all read. `python tests.py` passes on Windows before and after the fixes (now 98 command checks and 12 file checks).

## 1. Fixed in this pass

| # | Where | Bug | Effect before the fix |
|---|---|---|---|
| 1 | `tests.py` | The backup-brain check ran `Get-Date`, a PowerShell command, which fails under bash | **Mac setup always stopped at "self-checks failed"** |
| 2 | `core/system.py`, `nova.py` | Nova.app starts with a bare PATH (`/usr/bin:/bin`) | Mac: Claude Code / Codex / npm in Homebrew, nvm or `~/.local/bin` not found, so "No AI connected" |
| 3 | `core/system.py` | Mac "lock my computer" ran `pmset displaysleepnow` | Only turned the screen off; now presses Ctrl+Cmd+Q (Lock Screen) |
| 4 | `nova.py` `assist()` | `self.brain.browser_name` with no CLI installed | Crash on every request when only the Gemini backup brain was set up |
| 5 | `nova.py` `interrupted()` | Sent the "heard" event twice | Your interrupting sentence showed twice in Chat and History |
| 6 | `nova.py` | After Nova asked "Want me to run the tests?", answering "okay" / "alright" matched the goodbye list | Conversation ended instead of saying yes |
| 7 | `core/brain.py` Codex `clean()` | Reused the last output file | A failed Codex cleanup could paste the **previous** dictation |
| 8 | `core/brain.py` `cancel()` | `os.killpg` on a process that just ended | Mac: Esc right as a reply finished raised an error |
| 9 | `helpers/browser_mcp.py` | Only caught `OSError`; read stdin in the ANSI code page | MCP server crashed on a wrong key / hang-up; Hindi or other non-ASCII text in browser typing garbled or crashed |
| 10 | `nova.py` `browser_tool` | Unknown default browser id raised outside the error handler | The AI's browser call hung up with no answer |
| 11 | `nova.py` `quit()` | Left the browser socket file behind | Stale socket files in the Mac temp folder |
| 12 | `core/app.py` reset | "Reset settings" forgot which browsers had the extension | Extension stayed installed but Nova no longer used it |
| 13 | `helpers/setup_window.py` | Mac setup never wrote `data/setup.log` (README promises it) and restarted Nova before the old copy had exited | No log to share; after an update Nova could silently not start |
| 14 | `core/app.html` | Canvas `roundRect` doesn't exist in macOS 12's WebKit | Mac 12: every pill animation in the window stopped drawing |
| 15 | `core/app.html`, `core/app.py` | "Open Privacy settings" opened four System Settings panes at once | Only the last (Screen Recording) stayed visible; now one button per permission |
| 16 | `core/app.html` | Home suggested "What's on my calendar today?" | Nova has no calendar access; replaced with the weather example |

## 2. Security

Fixed:

- **Credential files the AI could read freely**: `~/.aws/credentials`, `.git-credentials`, `.netrc`, `.npmrc`, `.pypirc`, Docker/kube configs, `gh` tokens, Claude Code's and Codex's own login files, `.gnupg`, and Nova's own `browser-token` / `events.key` are now blocked like browser passwords already were. Before, a prompt injection could read them and send them out with WebFetch (which isn't guarded).
- **AppleScript bypass (Mac)**: `osascript -e 'tell application "Finder" to delete every item of home'` and Mail/Messages `send` were allowed without asking. Now confirm.
- **Run-on-commit**: writing inside a project's `.git` (for example `.git/hooks/pre-commit`, which the allowed `git commit` would then run) and inside `.codex` now asks.
- **Script launch**: `Start-Process x.py` / `.pyw .jar .reg .cpl .wsf .vbe .jse` now ask, like `.ps1`/`.bat` already did.
- **Key files on Mac** (`events.key`, `browser-token`, `mcp.json`, `fallback.key`) are written readable by you only (0600).
- **Browser extension**: card-number and one-time-code fields' values are no longer included when the AI reads a page (passwords already weren't). Version bumped to 1.0.1 so installed copies refresh.

Not fixed (design decisions for you):

- **Running tests runs code the AI wrote.** Edits inside projects are allowed and `npm run …` / `pytest` are allowed, so a prompt injection can write a script and run it without a prompt. Closing this means asking before `npm run`/`pytest` after an edit; that costs convenience.
- **WebFetch / browser navigation can carry data out in a URL.** Neither asks. Consider confirming WebFetch to hosts the user didn't name.
- **`ANTHROPIC*` / `CLAUDE*` environment variables are removed** at startup. Anyone who signs Claude Code in with `ANTHROPIC_API_KEY` will see "not signed in".
- **Windows file permissions**: on a `D:\` folder other local accounts can usually read `data\`. Fine for a single-user PC.
- `requirements.txt` has no version pins, so a future library release can break a fresh install. Consider a lock file.

## 3. macOS readiness

Now fixed: setup self-checks (#1), CLI discovery (#2), lock screen (#3), setup log and restart (#13), window on macOS 12 (#14), permission buttons (#15).

Can't be verified from Windows. Test these on a real Mac:

- That macOS asks for permissions as "Nova" and not "Python": Nova.app's executable is a bash script that runs the venv Python, which usually works but can vary with the Python build.
- pynput hotkeys need Input Monitoring **and** Accessibility. Without them the shortcut silently does nothing.
- The bar and card re-encode a PNG every frame while animating, which costs some CPU on Macs.
- Nova.app isn't code-signed, so every update can make macOS ask for permissions again.

## 4. GitHub / one-click install

- **Blocker: most of the app isn't committed.** `core/app.py`, `core/app.html`, `core/config.py`, `core/browser.py`, `core/intents.py`, `core/fallback.py`, `core/loopback.py`, `core/region.py`, `browser/`, `helpers/*.py` and `PRODUCT.md` are untracked. A clone of GitHub today crashes at `from core.config import …`. Commit and push everything.
- Added **`setup.command`**: double-click in Finder to install. Commit it executable: `git add --chmod=+x setup.command`.
- README now has a **step-by-step install that needs no git** (Download ZIP → `setup.cmd` / `setup.command`), including the SmartScreen and Gatekeeper prompts, a "First run" section and a first thing to try.
- Suggested: a GitHub Actions workflow that runs `python tests.py` on `windows-latest` and `macos-latest`. That would have caught #1.

## 5. Buttons checked

Every control in `core/app.html` is wired to a handler that exists in `core/app.py` or Nova: navigation, mode, pause, status tiles, try-phrases, chat send/stop/mic/new, history filter/search/clear/copy, dictionary add/remove, replacements, memory add/forget/clear, every settings switch, select, slider and number box, shortcut recorder, mic test, voice play/download, engines install/sign-in/choose, backup key check/get/remove, nicknames, routines, browsers on/off/default/restart/finish setup, open config/logs/notes, run setup, reset, and the onboarding back/next. The same goes for the tray menu, the bar (click / right-click), the card (Allow / Deny / open), and the browser panel (send / mic / Allow / Deny).

Removed: the onboarding **Skip** button, which was always hidden.

## 6. Stale / unused code

- Removed: `system.round_corners()` (never called), an unused variable in `nova.interrupted()`, and the dead Skip button.
- `Api.open("folder")` has no button. Harmless.
- pyflakes is otherwise clean. Its other warnings are intentional re-exports (`core/clipboard.py`) and an availability probe (`core/loopback.py`).

## 7. UI/UX improvements worth doing

1. The Nova window loads settings once. If you say "add X to my dictionary" while it's open, then edit the dictionary in the window, the window's older list overwrites your spoken word. Have Nova push a `config` event when `config.json` changes.
2. History rows open only by mouse click; make them buttons so the keyboard can open them too. Settings tabs have no arrow-key navigation.
3. Timers can't be listed or cancelled, and they're lost when Nova quits.
4. When the region picker is left alone, the screen stays dimmed until you click.
5. Sign-in polling fails silently if `engines()` errors; show "Couldn't check, try again".
6. The backup brain doesn't stop between steps when you press Esc. Commands already started still run.

## 8. Features worth adding

- Cancel or list timers ("cancel my timer"), and reminders at a time ("remind me at 5 to call mom").
- An update check: show "A new version is available" in the window, since there's no auto-update.
- A push-to-talk mode: hold the shortcut to talk, release to send.
- Multi-monitor support for screenshots and the region picker (currently main screen only).
- Export history.
- CI on Windows and Mac (see §4).
