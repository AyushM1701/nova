# Competitor Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the OpenWhispr and HeyClicky features Nova lacks (snippets, usage stats, SRT export, crash-safe dictation, pointing walkthroughs, scheduled routines, tone per app, local AI cleanup, a notes MCP server, meeting detection), all running on the user's computer and free.

**Architecture:** Each feature is a small pure function or module in `core/` (unit-tested in `tests.py`), plus wiring in `nova.py`, a setting in `config.default.json`, a control in `core/app.html` / `core/app.py`, and a line in `README.md`. No task depends on another, so they can land in any order, one commit each.

**Tech Stack:** Python 3.11–3.13, stdlib, plus the dependencies already in `requirements.txt` (numpy, pynput on macOS, pyobjc). Tkinter bar and card, pywebview window.

**Spec:** The user's feature list in this session (items 1–11, from the OpenWhispr/HeyClicky analysis). There is no separate spec file: this section is the spec.

1. Snippets: say a trigger phrase and a block of text is typed.
2. Usage stats: words dictated, words per minute, time saved.
3. Transcript export as SRT, TXT or Markdown.
4. Crash-safe dictation: keep the audio until the paste succeeds.
5. Captions while Nova talks.
6. Pointing walkthroughs: arrows on screen, next step after the user clicks.
7. Scheduled routines: "every weekday at 9, run start my day".
8. Tone per app.
9. Local AI cleanup (Ollama or llama.cpp).
10. Local MCP server for notes, memory and dictionary.
11. Meeting detection: "take notes?" when a meeting app uses the mic.

**Already covered, no task:**
- **5 Captions:** `Nova.say` already shows the whole reply on the card while Nova speaks (`kind="speaking"`). Revisit only if users ask for word-by-word captions.
- **3 Markdown and TXT:** `meetings.export_note` already writes the Markdown note, and `meetings.transcript_text` is the TXT. Only SRT and the export buttons are new (Task 3).

## Global Constraints

- No new pip dependency. Use stdlib (`urllib`, `winreg`, `wave`, `json`, `http.server` in tests) and what `requirements.txt` already has.
- Nothing leaves the computer that doesn't today. No Nova server, account or analytics. The local LLM in Task 9 goes only to the URL the user sets.
- Every new setting has its default in `config.default.json`. `config.json` keeps only the user's overrides (`core/config.py`).
- Each feature works on Windows and macOS, or says plainly in its UI copy and README line that it is Windows-only (Task 11 on macOS).
- Tests are plain `assert`s added to `tests.py` before its final `print("OK: all self-checks passed")` line. Run: `python tests.py`. Pass = last line `OK: all self-checks passed`.
- UI copy follows PRODUCT.md: plain, short, friendly, no jargon. Accent `#7b6dff`. Never invent numbers or testimonials.
- Commits carry no "Co-Authored-By: Claude" trailer.
- Each task adds one bullet to README "Everything it does" and its settings to the README Settings table.

## Review Focus

1. **Paths from an MCP client** (`read_note("../../config.json")`, absolute paths, symlinks): refused. Only files under `workspace/notes` are readable. The test is in Task 10.
2. **A scheduled routine while Nova is busy or paused:** it waits and runs once when Nova is free within its 60-minute window, never twice, and never after a restart that already ran it today. The test is in Task 7.
3. **A local LLM that is down, slow or "thinking":** dictation still pastes, cleaned by the local rules, within the timeout. `<think>…</think>` is stripped. The test is in Task 9.
4. **A recovered dictation from a crash:** it goes to the clipboard and History and is never typed into whatever app happens to be in front at startup. A corrupt rescue file is deleted, not retried forever. The test is in Task 4.
5. **Nova's own microphone** (wake word, `python.exe`/`pythonw.exe`) is never reported as a meeting app, and a browser counts only when its title is a meeting. The test is in Task 11.

---

### Task 1: Snippets

**Files:**
- Modify: `core/cleanup.py` (new function after `apply_replacements`)
- Modify: `nova.py` `Nova.dictate` (top of the method, before the `is_edit` check)
- Modify: `config.default.json` (`dictation.snippets: {}`)
- Modify: `core/app.html` (Dictionary page: a "Snippets" pairs editor under replacements)
- Test: `tests.py`

**Interfaces:**
- Produces: `cleanup.snippet_for(raw: str, snippets: dict[str, str]) -> str | None`

- [ ] **Step 1: Write the failing test**

```python
from core.cleanup import snippet_for  # noqa: E402
SNIPS = {"my address": "221B Baker Street, London", "sign off": "Thanks,\nAyush", "": "never"}
assert snippet_for("My address.", SNIPS) == "221B Baker Street, London"
assert snippet_for("insert my address", SNIPS) == "221B Baker Street, London"
assert snippet_for("Type sign off!", SNIPS) == "Thanks,\nAyush"
assert snippet_for("send it to my address", SNIPS) is None   # whole utterance only
assert snippet_for("", SNIPS) is None                        # an empty trigger never matches
assert snippet_for("my address", {}) is None
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python tests.py`
Expected: `ImportError: cannot import name 'snippet_for'`

- [ ] **Step 3: Implement `snippet_for` in `core/cleanup.py`**

Normalize the utterance and each trigger the way `Nova.command` does (`re.sub(r"[^\w\s]", "", s.lower()).strip()`). Match the whole utterance, optionally prefixed by `insert|paste|type`. Skip empty triggers. Return the expansion verbatim.

- [ ] **Step 4: Wire it into `Nova.dictate`**

Add `expansion = cleanup.snippet_for(raw, d["snippets"])` as the first lines. When it matches: `log("snippet", raw=raw)`, `self.paste(expansion)`, return. There's no cleanup, translation or auto-learn for snippets. Add `"snippets": {}` under `dictation` in `config.default.json`. In `core/app.html`, beside `addRepl`, add `addSnip = pairsEditor($("#snips"), "dictation.snippets", "my address", "221B Baker Street, London")` with a `#snips` container and the heading "Snippets: say the phrase, Nova types the text".
  `// shortcut: the pairs editor is single-line, so multi-line snippets need config.json; upgrade to a textarea if users ask`

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python tests.py`
Expected: `OK: all self-checks passed`

- [ ] **Step 6: Update the README and commit**

Add to README: a bullet "**Snippets:** say "my address" and Nova types the whole thing. Add them on the Dictionary page." and the `dictation.snippets` settings row.

```bash
git add core/cleanup.py nova.py config.default.json core/app.html README.md tests.py
git commit -m "Snippets: say a phrase, Nova types the saved text"
```

---

### Task 2: Usage stats

**Files:**
- Create: `core/stats.py`
- Modify: `nova.py` (`voice_job` sets `self.spoken_s`; `dictate` records; `dictate_from_phone` sets `self.spoken_s = 0`)
- Modify: `core/app.py` (new js_api method `stats`)
- Modify: `core/app.html` (Home page: one stats line)
- Test: `tests.py`

**Interfaces:**
- Produces:
  - `stats.STATS = DATA / "stats.json"`
  - `stats.TYPING_WPM = 40`
  - `stats.record(words: int, seconds: float, path: Path = STATS, today: datetime.date | None = None) -> None`
  - `stats.summary(path: Path = STATS, today: datetime.date | None = None) -> dict` with keys `words, dictations, wpm, minutes_saved, week_words`
  - `App.stats(self) -> dict` (returns `stats.summary()`)

- [ ] **Step 1: Write the failing test**

```python
import datetime  # noqa: E402
from core import stats  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    p, day = Path(tmp) / "stats.json", datetime.date(2026, 10, 24)
    assert stats.summary(p, day) == {"words": 0, "dictations": 0, "wpm": 0, "minutes_saved": 0, "week_words": 0}
    stats.record(120, 60, p, day)
    stats.record(5, 0, p, day)                           # not spoken into Nova's mic (phone): not counted
    stats.record(40, 30, p, day - datetime.timedelta(days=9))
    s = stats.summary(p, day)
    assert (s["words"], s["dictations"], s["wpm"]) == (160, 2, 107), s     # 160 words in 1.5 min
    assert s["minutes_saved"] == 2.5, s                  # 160/40 typing minutes - 1.5 spoken minutes
    assert s["week_words"] == 120, s                     # the last 7 days only
    p.write_text("{not json", encoding="utf-8")
    assert stats.summary(p, day)["words"] == 0           # a broken file starts fresh, never crashes
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python tests.py`
Expected: `ImportError: cannot import name 'stats'`

- [ ] **Step 3: Implement `core/stats.py`**

The file holds `{"words", "seconds", "dictations", "days": {"YYYY-MM-DD": words}}`. Prune `days` older than 30 days on write, and write via `config.write_private`. `record` ignores `seconds <= 0`. `wpm = round(words / (seconds / 60))`, or 0 when there are no seconds. `minutes_saved = round(max(0, words / TYPING_WPM - seconds / 60), 1)`.

- [ ] **Step 4: Wire it in**

- In `voice_job`, right after the clip is final (before `transcribe`), set `self.spoken_s = len(clip) / audio.RATE`.
- In `dictate`, after `self.paste(text)`, call `stats.record(len(text.split()), self.spoken_s)`.
- Set `self.spoken_s = 0` in `__init__` and in `dictate_from_phone`.
- Add `App.stats` in `core/app.py`.
- On the Home page in `core/app.html`, add a line filled from `api().stats()`: "{words} words dictated · {wpm} wpm · {minutes_saved} min saved". Hide it while `dictations == 0`.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python tests.py`
Expected: `OK: all self-checks passed`

- [ ] **Step 6: Update the README and commit**

Add to README: a bullet "**See your progress:** the Home page counts words dictated, your speaking speed and the minutes you saved over typing (kept on your computer)."

```bash
git add core/stats.py nova.py core/app.py core/app.html README.md tests.py
git commit -m "Home page shows words dictated, speaking speed and time saved"
```

---

### Task 3: SRT and TXT export for meetings and audio files

**Files:**
- Modify: `core/meetings.py` (new `srt` beside `transcript_text`)
- Modify: `core/app.py` (new js_api `export_meeting`)
- Modify: `core/app.html` (Meetings page: "Export" menu with SRT / TXT / Markdown)
- Test: `tests.py`

**Interfaces:**
- Produces:
  - `meetings.srt(m: dict) -> str`
  - `App.export_meeting(self, mid: str, kind: str) -> str | None`, where `kind` is `"srt" | "txt" | "md"`. It returns the saved path, or None when the user cancels.

- [ ] **Step 1: Write the failing test**

```python
from core.meetings import srt  # noqa: E402
M = {"transcript": [{"start": 0, "end": 2.5, "text": "Hi all.", "speaker": "Ayush"},
                    {"start": 3661.2, "end": 3663, "text": "Bye."}]}
assert srt(M) == ("1\n00:00:00,000 --> 00:00:02,500\nAyush: Hi all.\n\n"
                  "2\n01:01:01,200 --> 01:01:03,000\nSpeaker: Bye.\n")
assert srt({"transcript": []}) == ""
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python tests.py`
Expected: `ImportError: cannot import name 'srt'`

- [ ] **Step 3: Implement `srt`, then `export_meeting`**

Speaker fallback is `"Speaker"`, as in `transcript_text`. `export_meeting` uses pywebview's `create_file_dialog(webview.SAVE_DIALOG, save_filename=f"{title}.{kind}")`, the same way `pick_audio`/`pick_folder` open their dialogs. It writes `srt(m)`, `transcript_text(m)` or `markdown(m)` as UTF-8. In `core/app.html`, add the Export menu on an open meeting.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python tests.py`
Expected: `OK: all self-checks passed`

- [ ] **Step 5: Update the README and commit**

Add to README: extend the meetings bullet with "export as subtitles (SRT), text or Markdown".

```bash
git add core/meetings.py core/app.py core/app.html README.md tests.py
git commit -m "Export meeting and audio-file transcripts as SRT, TXT or Markdown"
```

---

### Task 4: Crash-safe dictation

**Files:**
- Create: `core/rescue.py`
- Modify: `nova.py` (`voice_job`: keep the clip before transcribing a dictation and clear it after `dictate`; `load_stt`: recover once the model is loaded)
- Test: `tests.py`

**Interfaces:**
- Produces:
  - `rescue.RESCUE = DATA / "last-dictation.wav"`
  - `rescue.keep(clip: np.ndarray, path: Path = RESCUE) -> None` (float32 at 16 kHz in, written as 16-bit mono WAV)
  - `rescue.pending(path: Path = RESCUE) -> np.ndarray | None` (float32; a corrupt file is deleted and returns None)
  - `rescue.clear(path: Path = RESCUE) -> None`

- [ ] **Step 1: Write the failing test**

```python
import numpy as np  # noqa: E402
from core import rescue  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "last.wav"
    assert rescue.pending(p) is None
    clip = np.sin(np.linspace(0, 100, 16000)).astype(np.float32) * 0.5
    rescue.keep(clip, p)
    back = rescue.pending(p)
    assert back is not None and len(back) == 16000 and np.abs(back - clip).max() < 1e-3
    rescue.clear(p)
    assert rescue.pending(p) is None and not p.exists()
    p.write_bytes(b"garbage")
    assert rescue.pending(p) is None and not p.exists()   # corrupt: removed, not retried every start
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python tests.py`
Expected: `ImportError: cannot import name 'rescue'`

- [ ] **Step 3: Implement `core/rescue.py`**

Use the `wave` module with the same 16-bit write as `meetings.Recorder` (`(clip * 32767).astype("<i2")`), and `meetings.read_wav`-style reading.

- [ ] **Step 4: Wire it in**

- In `voice_job`, when `mode == "dictation"`, call `rescue.keep(clip)` just before `self.transcribe(...)`.
- Call `rescue.clear()` after the dictation branch finishes, on cancel, and when `text` is empty.
- At the end of `load_stt`, once the model works: if `rescue.pending()` returns audio, transcribe it with `self.transcribe(clip)` and run `cleanup.clean(raw, self.cfg["dictation"], None)` (local rules only; the AI may not be up yet).
- Then `clipboard.set_text(text)`, `log("dictation", raw=raw, text=text, how="recovered")` (so History shows it), the card "Your last dictation is on the clipboard" / "Nova closed before typing it. Press Ctrl+V (Cmd+V on a Mac) to paste it.", and finally `rescue.clear()`.
- Never call `self.paste` here: the app in front at startup isn't where the user was dictating.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python tests.py`
Expected: `OK: all self-checks passed`

- [ ] **Step 6: Check it by hand**

Start a dictation, kill Nova (Task Manager / `kill`) while it says "thinking", then start Nova again. The card appears, Ctrl+V pastes the words, and History lists them.

- [ ] **Step 7: Update the README and commit**

Add to the README "What stays on your computer" section: "Each dictation's audio is kept in `data/last-dictation.wav` until it's typed, so a crash never loses it."

```bash
git add core/rescue.py nova.py README.md tests.py
git commit -m "Never lose a dictation: recover it to the clipboard after a crash"
```

---

### Task 5: Pointing walkthroughs

**Files:**
- Modify: `core/pointer.py` (`fly` gains `hold_s`; new `last_step` parser)
- Modify: `core/system.py` (new `mouse_down`)
- Modify: `nova.py` (`WALK_RE`, `WALK_PROMPT`, new `Nova.walk`; `assist` hands walkthrough requests to it)
- Test: `tests.py`

**Interfaces:**
- Consumes: `pointer.take(shown, shot)`, `system.screenshot(path, box)`, `system.window_rect(target)`, `brain.run(prompt, projects, aliases, on_step, image=, tools=False)`
- Produces:
  - `Pointer.fly(self, x: int, y: int, label: str = "", hold_s: float | None = HOLD_S)`, where `None` means stay until `hide()`
  - `pointer.last_step(reply: str) -> tuple[str, bool]`: the reply without its `DONE` line, and whether it had one
  - `system.mouse_down() -> bool`: the left button is down now
  - `Nova.walk(self, goal: str) -> None`
  - `nova.MAX_STEPS = 15`, `nova.CLICK_WAIT_S = 60`

- [ ] **Step 1: Write the failing tests**

```python
from core.pointer import last_step  # noqa: E402
assert last_step("SAY: Click File.\nPOINT: 10,20 File") == ("SAY: Click File.\nPOINT: 10,20 File", False)
assert last_step("SAY: That's it, you're done.\nDONE") == ("SAY: That's it, you're done.", True)
assert last_step("**DONE**") == ("", True)
assert nova_mod.WALK_RE.search("walk me through exporting a PDF")
assert nova_mod.WALK_RE.search("show me how to turn on dark mode")
assert not nova_mod.WALK_RE.search("show me the weather")
```

Then add a loop test with fakes, following the stub style near `tests.py:530`:
- A fake brain's `run` returns, in turn, `"SAY: Click File.\nPOINT: 10,20 File"` and `"SAY: Done.\nDONE"`.
- Patch `nova_mod.system.mouse_down` to `lambda: True`, `system.screenshot` to return `("shot.png", (0, 0, 1, 100, 100))`, and use a recording fake pointer.
- Call `Nova.walk("export a PDF")` on a stub.
- Assert that `run` was called twice, that the second prompt contains `"step 2"` and `"export a PDF"`, and that `pointer.fly` was called once with `(10, 20, "File")` and `hold_s=None`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python tests.py`
Expected: `ImportError: cannot import name 'last_step'`

- [ ] **Step 3: Implement `last_step`, `hold_s` and `mouse_down`**

- `last_step` strips lines matching `^\W*DONE\W*$` (case-insensitive) and reports whether any matched.
- In `fly`, `hold_s=None` skips the `after(HOLD_S * 1000, self.hide)`.
- `mouse_down` on Windows: `bool(user32.GetAsyncKeyState(0x01) & 0x8000)`.
- `mouse_down` on macOS: `Quartz.CGEventSourceButtonState(Quartz.kCGEventSourceStateCombinedSessionState, Quartz.kCGMouseButtonLeft)` (Quartz comes with pyobjc-framework-ApplicationServices).

- [ ] **Step 4: Implement `Nova.walk` and route to it**

- `WALK_RE = re.compile(r"\b(?:walk me through|step by step|show me how (?:to|do i)|guide me (?:through|to)|teach me how)\b", re.I)`.
- In `assist`, when `self.voice and self.cfg["brain"]["screen_context"] and WALK_RE.search(text)`, return `self.walk(text)`.
- `walk` loops `step` from 1 to `MAX_STEPS`:
  1. Screenshot `system.window_rect(system.foreground())` to `WORKSPACE / "screen.png"`.
  2. `brain.run(WALK_PROMPT.format(goal=goal, step=step, done="; ".join(said), width=…, height=…), {}, {}, self.on_step, image=…, tools=False)`.
  3. `last_step`, then `take_point`.
  4. If there's a spot, call `pointer.fly(*spot, hold_s=None)`.
  5. Say the step (`self.say`).
  6. If DONE, `pointer.hide()` and stop.
  7. Otherwise poll `system.mouse_down()` every 30 ms for up to `CLICK_WAIT_S`.
  8. On a click, `pointer.hide()`, sleep 0.8 s so the app can redraw, and append the step to `said`.
  9. On timeout or `self.cancel`, hide the pointer and say "Okay, stopping the walkthrough."
- `WALK_PROMPT` copy:
  > "The user wants to: {goal}. You are guiding them one step at a time on the attached screenshot ({width}x{height} pixels) of their window. Steps already done: {done}. This is step {step}. Reply with \"SAY: \" and one short instruction for the next single click, and \"POINT: x,y label\" for where to click. If the goal is reached, reply with \"SAY: \" and a one-line wrap-up, then a line \"DONE\"."
- `# shortcut: any left click advances (not only a click on the target), like Clicky; check the click position if steps skip ahead`

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python tests.py`
Expected: `OK: all self-checks passed`

- [ ] **Step 6: Check it by hand**

Say "Hey Nova, walk me through turning on dark mode" in Windows Settings (or macOS System Settings). The arrow lands on each control, each click moves to the next step, and Esc stops it.

- [ ] **Step 7: Update the README and commit**

Add to README: a bullet "**Walks you through it:** "walk me through exporting this as a PDF" and Nova's arrow shows each click, moving on after you click."

```bash
git add core/pointer.py core/system.py nova.py README.md tests.py
git commit -m "Walkthroughs: Nova points at each step and moves on when you click"
```

---

### Task 6: Scheduled routines

**Files:**
- Create: `core/schedule.py`
- Modify: `nova.py` (`command` recognizes a new schedule; new `watch_schedules` thread started in `run`)
- Modify: `config.default.json` (`"schedules": []`)
- Modify: `core/app.html` (Settings → Routines: the schedules list with Delete)
- Test: `tests.py`

**Interfaces:**
- Produces:
  - `schedule.parse(text: str) -> dict | None`, returning `{"days": list[int], "at": "HH:MM", "run": str}` with Monday = 0
  - `schedule.due(schedules: list[dict], now: datetime.datetime, last: dict[str, str]) -> list[dict]`
  - `schedule.key(s: dict) -> str` = `f"{s['run']}|{s['at']}"`
  - `schedule.LAST = DATA / "schedules-last.json"` (maps key to the `YYYY-MM-DD` it last ran)
  - `schedule.WINDOW_MIN = 60`

- [ ] **Step 1: Write the failing test**

```python
from core import schedule  # noqa: E402
assert schedule.parse("every weekday at 9, run start my day") == {"days": [0, 1, 2, 3, 4], "at": "09:00",
                                                                  "run": "start my day"}
assert schedule.parse("Every day at 6:30 pm start deep code mode.") == {"days": [0, 1, 2, 3, 4, 5, 6],
                                                                        "at": "18:30", "run": "start deep code mode"}
assert schedule.parse("every monday at 9am run standup notes")["days"] == [0]
assert schedule.parse("every weekend at 10 run plan the week")["days"] == [5, 6]
assert schedule.parse("what's the weather") is None
assert schedule.parse("every weekday at 25, run x") is None
S = {"days": [0, 1, 2, 3, 4], "at": "09:00", "run": "start my day"}
mon = datetime.datetime(2026, 10, 26, 9, 0, 30)
assert schedule.due([S], mon, {}) == [S]
assert schedule.due([S], mon, {"start my day|09:00": "2026-10-26"}) == []      # already ran today (even before a restart)
assert schedule.due([S], mon.replace(hour=9, minute=59), {}) == [S]           # woke up late: still runs, once
assert schedule.due([S], mon.replace(hour=10, minute=1), {}) == []            # past the 60-minute window
assert schedule.due([S], datetime.datetime(2026, 10, 24, 9, 0), {}) == []     # Saturday
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python tests.py`
Expected: `ImportError: cannot import name 'schedule'`

- [ ] **Step 3: Implement `core/schedule.py`**

The grammar is `every (day|weekday|weekend|monday…sunday) at H[:MM] [am|pm][,] [run ]<what>`. Hours above 23 or minutes above 59 return None. A leading "run " is dropped; any other verb stays, so `Nova.command` still recognizes "start deep code mode".

- [ ] **Step 4: Wire it in**

- In `Nova.command`, in the assistant branch before the routines loop: if `schedule.parse(text)` returns `s`, then `self.save_setting("schedules", self.cfg["schedules"] + [s])` and note "Scheduled" / f"Okay. Every {days in words} at {at}, I'll {run}."
- `watch_schedules` runs every 30 s. It loads `LAST` (if it's broken, treat it as `{}`) and goes through `due(self.cfg["schedules"], datetime.datetime.now(), last)`.
- For each due schedule, it runs only when `self.phase == "idle" and not self.pending and not self.paused`. Otherwise it waits for the next pass, still inside the window.
- To run one: set `last[key] = today`, write `LAST`, set `self.voice = True`, then `self.spawn(lambda: self.command(s["run"], typed=True) or self.assist(s["run"]), "busy")`.
- Start the thread in `run()`'s thread list.
- In Settings → Routines, list each schedule as "{days} at {at}: {run}" with a Delete button that saves `schedules` without it.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python tests.py`
Expected: `OK: all self-checks passed`

- [ ] **Step 6: Update the README and commit**

Add to README: extend the Routines bullet with "Schedule them by voice: "every weekday at 9, run start my day"." Add the `schedules` settings row.

```bash
git add core/schedule.py nova.py config.default.json core/app.html README.md tests.py
git commit -m "Scheduled routines: \"every weekday at 9, run start my day\""
```

---

### Task 7: Tone per app

**Files:**
- Modify: `core/cleanup.py` (`tone_for`; a `{tone}` line in `LLM_PROMPT`; `clean` gains `tone`)
- Modify: `nova.py` `Nova.dictate` (passes the tone for `self.target`)
- Modify: `config.default.json` (`dictation.tones: {}`)
- Modify: `core/app.html` (Settings → Dictation: "Tone per app" pairs editor)
- Test: `tests.py`

**Interfaces:**
- Produces:
  - `cleanup.tone_for(title: str, tones: dict[str, str]) -> str` (`""` when no app matches)
  - `cleanup.clean(raw: str, d: dict, brain=None, tone: str = "") -> tuple[str, str]`

- [ ] **Step 1: Write the failing test**

```python
from core.cleanup import tone_for, clean as clean_dictation  # noqa: E402
TONES = {"gmail": "clear and professional", "WhatsApp": "casual and friendly", "": "never"}
assert tone_for("Inbox (3) - you@gmail.com - Gmail - Opera", TONES) == "clear and professional"
assert tone_for("WHATSAPP", TONES) == "casual and friendly"
assert tone_for("Visual Studio Code", TONES) == ""
class ToneBrain:
    name = "Claude Code"
    def clean(self, system_prompt, text, model):
        self.prompt = system_prompt
        return "Hey, see you at 7!"
D = {"editing": "light", "llm_min_words": 30, "dictionary": [], "replacements": {}, "claude_model": "haiku"}
tb = ToneBrain()
assert clean_dictation("hey see you at 7", D, tb, tone="casual and friendly") == ("Hey, see you at 7!", "Claude Code")
assert "Tone: casual and friendly" in tb.prompt                       # short text still goes to the AI when a tone is set
assert clean_dictation("hey see you at 7", D, None, tone="casual")[1] == "local"  # no AI: tone is skipped, never an error
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python tests.py`
Expected: `ImportError: cannot import name 'tone_for'`

- [ ] **Step 3: Implement**

- `tone_for` does a case-insensitive substring match of each non-empty key in the title. The first match wins.
- Add the line `{tone}` to `LLM_PROMPT`, formatted as `f"Tone: {tone}. Adjust wording to it, keep the meaning."` or `""` when there's no tone.
- `clean` takes the LLM path when `brain and (tone or needs_llm(...))`.
- In `dictate`, call `cleanup.clean(raw, d, self.brain, cleanup.tone_for(system.window_title(self.target), d["tones"]))`.
- Add `"tones": {}` under `dictation`, and a pairs editor `"dictation.tones", "Gmail", "clear and professional"` headed "Tone per app (the app or window name, and how you want to sound)".

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python tests.py`
Expected: `OK: all self-checks passed`

- [ ] **Step 5: Update the README and commit**

Add to README: a bullet "**Sounds right in every app:** set a tone per app (casual in WhatsApp, professional in Gmail) in Settings → Dictation." Add the `dictation.tones` settings row.

```bash
git add core/cleanup.py nova.py config.default.json core/app.html README.md tests.py
git commit -m "Tone per app for dictation"
```

---

### Task 8: Local AI cleanup (Ollama, llama.cpp, LM Studio)

**Files:**
- Create: `core/local_llm.py`
- Modify: `core/cleanup.py` `model_for` (handles the local cleaner)
- Modify: `nova.py` (new `Nova.cleaner` property; `dictate` and `translate` use it instead of `self.brain`)
- Modify: `core/app.py` (new js_api `local_llm_test`)
- Modify: `config.default.json` (`dictation.cleanup_engine`, `dictation.local_url`, `dictation.local_model`)
- Modify: `core/app.html` (Settings → Dictation: "Clean up long dictations with" choice, URL, model, Test button)
- Test: `tests.py`

**Interfaces:**
- Produces:
  - `class LocalLLM` with `name = "Local AI"`
  - `LocalLLM.__init__(self, url: str, model: str)`
  - `LocalLLM.clean(self, system_prompt: str, text: str, model: str, timeout: float = 20) -> str | None`. It POSTs `{url}/chat/completions` (OpenAI format), strips `<think>…</think>`, and returns None on any error.
  - `Nova.cleaner -> LocalLLM | Brain | None`
  - `App.local_llm_test(self, url: str, model: str) -> str`: `"ok"` or a plain-English error
  - `config.default.json`: `"cleanup_engine": "ai"` (`"ai"` | `"local"`), `"local_url": "http://localhost:11434/v1"`, `"local_model": "llama3.2:3b"`

- [ ] **Step 1: Write the failing test**

Reuse the `http.server` pattern from `SpeechServer` (`tests.py:1406`).

```python
from core.local_llm import LocalLLM  # noqa: E402
seen = {}
class ChatServer(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        seen["path"], seen["body"] = self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        out = json.dumps({"choices": [{"message": {"content": "<think>hmm</think>\nSee you at 7."}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(out)
    def log_message(self, *_): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), ChatServer)
threading.Thread(target=srv.handle_request, daemon=True).start()
llm = LocalLLM(f"http://127.0.0.1:{srv.server_port}/v1", "llama3.2:3b")
assert llm.clean("SYSTEM", "<dictation>see you at 7</dictation>", "llama3.2:3b") == "See you at 7."
assert seen["path"] == "/v1/chat/completions" and seen["body"]["model"] == "llama3.2:3b"
assert seen["body"]["messages"][0] == {"role": "system", "content": "SYSTEM"}
assert LocalLLM("http://127.0.0.1:9/v1", "x").clean("S", "t", "x", timeout=2) is None   # nothing listening: None
from core.cleanup import model_for  # noqa: E402
assert model_for(llm, {"local_model": "llama3.2:3b", "claude_model": "haiku", "codex_model": ""}) == "llama3.2:3b"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python tests.py`
Expected: `ModuleNotFoundError: No module named 'core.local_llm'`

- [ ] **Step 3: Implement `core/local_llm.py` and update `model_for`**

Use `urllib.request` with `temperature: 0` and `stream: false`. Catch `Exception` and return None (dictation falls back to the local rules). `model_for` returns `d["local_model"]` when `brain.name == "Local AI"`.

- [ ] **Step 4: Wire it in**

- `Nova.cleaner` returns `LocalLLM(d["local_url"], d["local_model"])` when `d["cleanup_engine"] == "local"`, else `self.brain`.
- In `dictate` (edit mode, `cleanup.clean`) and `translate`, use `self.cleaner` where they use `self.brain` today, and say "Translating dictation needs an AI: connect Claude Code or Codex, or a local model" when it's None.
- `App.local_llm_test` calls `clean("Reply with the word ok.", "ok", model, 10)` and maps failures to "Nova couldn't reach {url}. Is Ollama running?".
- In Settings → Dictation, add a radio "Claude Code / Codex" | "A model on this computer (Ollama, llama.cpp, LM Studio)", plus URL, model and **Test**, with a link "Get Ollama" to https://ollama.com/download.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python tests.py`
Expected: `OK: all self-checks passed`

- [ ] **Step 6: Update the README and commit**

- Add to README: a bullet "**Fully offline dictation:** point Nova at Ollama or llama.cpp in Settings → Dictation, and long dictations are tidied on your computer with no subscription."
- Add the three settings rows.
- In "What stays on your computer", add that a local model keeps dictated text on the machine.

```bash
git add core/local_llm.py core/cleanup.py nova.py core/app.py config.default.json core/app.html README.md tests.py
git commit -m "Clean up dictation with a local model (Ollama, llama.cpp, LM Studio)"
```

---

### Task 9: Nova notes MCP server

**Files:**
- Create: `helpers/nova_mcp.py` (stdlib only, the same stdio JSON-RPC loop as `helpers/browser_mcp.py`)
- Modify: `core/app.py` (new js_api `mcp_install`)
- Modify: `core/app.html` (Settings → AI: "Let Claude Code / Codex read your Nova notes" buttons)
- Test: `tests.py`

**Interfaces:**
- Produces:
  - `nova_mcp.NOTES: Path` (defaults to `core.config.NOTES`; tests patch it)
  - `nova_mcp.handle(req: dict) -> dict` (same contract as `browser_mcp.handle`)
  - Tools:
    - `search_notes(query: str)` returns up to 20 `path: line` hits, case-insensitive, over `NOTES/**/*.md`
    - `read_note(path: str)` reads a path relative to `NOTES`
    - `read_memory()` reads `NOTES / "memory.md"`
    - `list_dictionary()` returns `dictation.dictionary` from `load_config()`
    - `add_dictionary_word(word: str)` writes it via `core.config.update_config`, which Nova's `watch_config` reloads
  - `App.mcp_install(self, cli: str) -> str`, where `cli` is `"claude"` or `"codex"`. It returns "ok" or the CLI's error.

- [ ] **Step 1: Write the failing test**

```python
import helpers.nova_mcp as nmcp  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    nmcp.NOTES = Path(tmp) / "notes"
    (nmcp.NOTES / "meetings").mkdir(parents=True)
    (nmcp.NOTES / "memory.md").write_text("- I use pnpm\n", encoding="utf-8")
    (nmcp.NOTES / "meetings" / "standup.md").write_text("# Standup\nShip the navbar fix\n", encoding="utf-8")
    (Path(tmp) / "secret.txt").write_text("key", encoding="utf-8")
    call = lambda name, **a: nmcp.handle({"method": "tools/call", "params": {"name": name, "arguments": a}})  # noqa: E731
    names = {t["name"] for t in nmcp.handle({"method": "tools/list"})["tools"]}
    assert names == {"search_notes", "read_note", "read_memory", "list_dictionary", "add_dictionary_word"}
    assert "meetings/standup.md" in call("search_notes", query="NAVBAR")["content"][0]["text"].replace("\\", "/")
    assert "pnpm" in call("read_memory")["content"][0]["text"]
    for bad in ("../secret.txt", str(Path(tmp) / "secret.txt"), "meetings/../../secret.txt"):
        assert call("read_note", path=bad).get("isError"), bad            # nothing outside notes/
```

Patch `nmcp.update_config` with a recorder, then assert that `add_dictionary_word` with `word="Kubernetes"` writes `{"dictation.dictionary": [..., "Kubernetes"]}`, and that a word already in the list (case-insensitively) isn't added twice.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python tests.py`
Expected: `ModuleNotFoundError: No module named 'helpers.nova_mcp'`

- [ ] **Step 3: Implement `helpers/nova_mcp.py`**

- Copy `browser_mcp`'s `main()` (UTF-8 stdin/stdout) and its `initialize`/`ping` handling. Use the server name `nova-notes`.
- Path check: `(NOTES / path).resolve()` must be relative to `NOTES.resolve()`; otherwise `isError` "Only notes in Nova's notes folder can be read."
- Errors are returned as `{"content": [{"type": "text", "text": msg}], "isError": True}`.
- Import only `core.config` (no tkinter, no audio).

- [ ] **Step 4: Implement `App.mcp_install` and the buttons**

- Run `[find_cli(cli), "mcp", "add", "--scope", "user", "nova", "--", sys.executable, str(ROOT / "helpers" / "nova_mcp.py")]` for claude, or `[find_cli("codex"), "mcp", "add", "nova", "--", …]` for codex, with a 30 s timeout.
- An "already exists" result counts as ok.
- The buttons show "Connected" after ok.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python tests.py`
Expected: `OK: all self-checks passed`

- [ ] **Step 6: Check it by hand**

Click the Claude button, then in a new terminal run `claude mcp list` and confirm `nova` is listed and connected. Ask Claude Code "search my Nova notes for standup".

- [ ] **Step 7: Update the README and commit**

Add to README: a bullet "**Your notes in Claude Code:** one click in Settings → AI lets Claude Code or Codex search your Nova notes, meetings and memory, on your computer." Add `helpers/nova_mcp.py` to the project layout.

```bash
git add helpers/nova_mcp.py core/app.py core/app.html README.md tests.py
git commit -m "Notes MCP server: Claude Code and Codex can read your Nova notes"
```

---

### Task 10: Meeting detection (Windows)

**Files:**
- Modify: `core/system.py` (new `mic_users`)
- Modify: `core/meetings.py` (new `in_use`, `meeting_app`, `MEETING_APPS`)
- Modify: `nova.py` (new `watch_meetings` thread; shares a "last offered" time with `watch_calendar`)
- Modify: `config.default.json` (`meetings.detect: true`)
- Modify: `core/app.html` (Settings → Meetings: "Offer to take notes when a meeting app uses the microphone (Windows)")
- Test: `tests.py`

**Interfaces:**
- Produces:
  - `meetings.in_use(entries: dict[str, tuple[int, int]]) -> list[str]`: maps registry subkey name to `(LastUsedTimeStart, LastUsedTimeStop)`, and returns the exe/package names in use now (start != 0 and stop == 0)
  - `meetings.meeting_app(users: list[str], title: str) -> str | None`: a friendly app name, or None
  - `system.mic_users() -> list[str]`: on Windows, `in_use` over `HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone` and its `NonPackaged` subkey read with `winreg`; `[]` on macOS
  - `Nova.offered: float` (time of the last meeting prompt, from either watcher)

- [ ] **Step 1: Write the failing test**

```python
from core.meetings import in_use, meeting_app  # noqa: E402
assert in_use({"C:#Program Files#Zoom#bin#Zoom.exe": (133, 0), "C:#Python#python.exe": (133, 0),
               "MSTeams_8wekyb3d8bbwe": (133, 0), "C:#old#Discord.exe": (133, 140), "never": (0, 0)}) \
    == ["Zoom.exe", "python.exe", "MSTeams_8wekyb3d8bbwe"]
assert meeting_app(["Zoom.exe"], "") == "Zoom"
assert meeting_app(["MSTeams_8wekyb3d8bbwe"], "") == "Teams"
assert meeting_app(["python.exe", "pythonw.exe"], "") is None            # Nova's own wake word
assert meeting_app(["chrome.exe"], "Meet - abc-defg-hij - Google Chrome") == "Google Meet"
assert meeting_app(["msedge.exe"], "YouTube - Microsoft Edge") is None   # a browser counts only in a meeting tab
assert meeting_app([], "Meet - x") is None
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python tests.py`
Expected: `ImportError: cannot import name 'in_use'`

- [ ] **Step 3: Implement**

- `in_use` keeps the part after the last `#` and preserves the input order.
- `MEETING_APPS` maps lowercase substrings to names: `zoom` → Zoom, `teams` → Teams, `webex` → Webex, `slack` → Slack, `discord` → Discord, `facetime` → FaceTime.
- For browsers (`chrome`, `msedge`, `brave`, `opera`, `vivaldi`, `firefox`), only the title counts: `Meet -` / `Google Meet` → "Google Meet", `Zoom` → Zoom, `Teams` → Teams.
- `python`/`pythonw` are always skipped.
- `system.mic_users` reads both registry levels. Any `OSError` returns `[]`.
- `# shortcut: macOS has no per-app mic API without extra entitlements; the calendar reminder covers Macs`

- [ ] **Step 4: Wire it in**

- `watch_meetings` runs every 10 s when `self.cfg["meetings"]["detect"]` is on and Nova isn't recording.
- It computes `app = meetings.meeting_app(system.mic_users(), system.window_title(system.foreground()))`.
- It prompts once per app session (reset when `app` becomes None) and not within 5 minutes of `self.offered`.
- The prompt is `self.card.show(f"{app} is using your microphone", "Say “record this meeting” to take notes. No bot joins.", hide_after=30)`, after which it sets `self.offered = time.time()`.
- `watch_calendar` also sets `self.offered` and skips its card if it's under 5 minutes old.
- Add `"detect": true` under `meetings`.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python tests.py`
Expected: `OK: all self-checks passed`

- [ ] **Step 6: Check it by hand (Windows)**

Join a Zoom or Google Meet test call. The card appears once within about 10 s. Leave and rejoin later, and it appears again.

- [ ] **Step 7: Update the README and commit**

Add to README: a bullet "**Notices your meetings (Windows):** when Zoom, Teams or Meet starts using your mic, Nova offers to take notes." Add the `meetings.detect` settings row.

```bash
git add core/system.py core/meetings.py nova.py config.default.json core/app.html README.md tests.py
git commit -m "Offer to take notes when a meeting app starts using the microphone (Windows)"
```

---

## Suggested order

Tasks 1–4 are each an afternoon. Do them first: they ship visible wins for the next release, and Task 2's numbers can go in the README honestly. Tasks 5, 8 and 9 are the strongest new selling points: walkthroughs match HeyClicky's headline feature, local AI cleanup makes dictation entirely free, and the MCP server is a paid OpenWhispr feature. Tasks 6, 7 and 10 are polish.
