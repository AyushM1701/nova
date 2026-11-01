# UI wiring audit: every control, every feature (2026-11-01)

Scope: the Nova window (`core/app.html`) with everything not yet on `main` merged into a local throwaway branch (the colour
theme, "learn how you like answers", "Your voice", macOS 27). The phone page, the browser panel and the Tk bar and card are
not covered. Question asked: is every feature wired in and shown, are there stale or dead buttons, does every button work, and does it look good.

## Verdict

No dead buttons. Every control I could reach does something, is named for a screen reader, and is not covered by anything.
One real layout regression (mine, from "Your voice"), fixed. The rest is polish and discoverability.

## How it was checked

| Check | Result |
|---|---|
| Static: duplicate ids, ids the script needs that don't exist, unhooked buttons, `api().x` calls with no `Api.x`, ops the page sends that Nova doesn't handle, unused functions and consts | none found (the 13 "unreferenced ids" are headings, containers and a `meetings()` handler my regex missed) |
| Real window, every page and every Settings tab (13), every visible control clicked once with the API stubbed so nothing real changes (reads go to the real API, writes are recorded and swallowed) | 467 controls: 0 dead, 0 unlabelled, 0 obscured. 19 "no visible change" were checked by hand: 12 are the option already selected (current tab, current radio, sliders), 7 are "Add row" buttons that append an empty input (no text changes) or forms submitted empty |
| Every option of every segmented control, and every speech-recognition engine, then the controls that choice reveals | all respond (Download, Check and save, Get a key, Remove key, Play, speed) |
| First-run tour, all 6 steps, every button | all respond |
| Horizontal overflow and clipped text on every page and tab at 820x580 (the smallest the window allows), 1080x740 and 1920x1000 | clean (after the fix below) |
| Impeccable rendered detector on the live window | no findings; static findings are the known DESIGN.md advisories |
| `tests.py` on the merged branch | passes |

Not covered: states that need real events (the approval strip, a running job, the meeting recorder) were exercised in the Home audit earlier this
session, not again here; macOS-only controls (permissions, notch bar); the walkthrough scene (it waits for real mouse and keyboard events, its only buttons are Close and Replay).

## Findings

### P2

1. **"Nova's voice" row squeezed at the narrowest window.** The fifth option ("Your voice") pushed the picker to 347 px and left the text a 118 px column: a 412 px tall row of one-word lines. Fixed on `voice-clone` (picker now sits under the text, row 207 px).

### P3

2. **Forms submitted empty say nothing.** Dictionary *Add*, Memory *Add*, Meetings *Ask*. A line such as "Type a word first" (or a disabled button until there is text) would do.
3. **Spacing on three pages.** Meetings: the "Ask your meetings" label touches the header text above it. Skills: *Open folder* sits on the header rule. Dictionary: the Replacements and Snippets column headers ("When it hears / Nova types") show over nothing when the lists are empty; show them with the first row, or add an example row.
4. **"Nova isn't running" banner has no button.** It tells people to start Nova but offers no way to; the window can't start Nova, so say where (Start menu / Applications) or drop the banner's dead end.
5. **Row actions appear only on hover or focus** (History *Copy*, Memory *Forget this*, Dictionary remove). Fine with a mouse, invisible on a first look. Showing them at low contrast would help.
6. **Small targets.** 125 of the buttons are under 32 px in one direction (chips and Home buttons 28 px, mode and Pause 28 px, remove crosses and *Check for updates* 24 px). All meet WCAG 2.2's 24 px minimum; none is generous.
7. **Red-ish colour picks blur "danger" and "primary".** With the pink, red or orange themes, *Forget everything* (danger) and *Add* (primary) are the same hue family. They still differ in fill versus outline and a trash icon.

### Features that aren't visible in the window

8. **Spoken or tray-only:** "undo that" / Undo last dictation (tray menu and voice only), "sketch the answer" (no setting, no mention; `overlay.sketch` is config-file only), Uninstall (scripts only, described in the README).
9. **Settings that exist only in `config.json`** (all documented in the README table, none in the window): `voice.stt_accurate_model`, `voice.deepgram_model`, `brain.max_turns`, `brain.max_background`, `brain.fallback_model`, `projects.exclude`, `skills.past_runs`, `browser.agent_window`, `triple_tap_mode`, `proactive.max_per_day`, `proactive.use_local_model`, `overlay.sketch`, `overlay.sketch_images`, `meetings.codex_model`. Reasonable as advanced settings; the two proactive ones are the likeliest to be wanted in the Suggestions row.

## Things that are right

Every `api()` call has a method, every op the page sends has a handler in `nova.py`, the Home "What Nova can do" list links to the right Settings tabs, the settings tabs and the deep links (`settings:cursor` and so on) agree, and the focus ring is visible on every control. The grey theme and the pink theme (the saved colour on this computer) both read well on every page.

## Method notes

The click-through ran in Nova's real window over the Chrome DevTools protocol with `pywebview.api` wrapped: read methods pass through, anything else
is recorded and answered with `true`. The first runs were wrong in two ways worth knowing about if it is repeated: a stub that returned `true` for
`memory(null)` (a read) made Home say "undefined things remembered", and the "Take the walkthrough" button leaves an overlay up that must be closed
before the next control is hit-tested.

## Status: all of the above fixed (branch `ui-polish`)

| # | Fix |
|---|---|
| 1 | Voice picker under its text (row 412 px to 207 px at 820 wide) |
| 2 | Empty Add / Ask say "Type a word or name first." and so on, and put the cursor back in the field |
| 3 | Meetings label has room; `#skillList` is clear of the header rule; the column labels over the Dictionary, Snippets, Routines, Tones, Apps and Nickname lists show only once a row exists |
| 4 | The "Nova isn't running" banner has a Start Nova button: it starts Nova, waits for it to answer, has it open its own window and closes the old one |
| 5 | Row actions show at half strength at rest, full on hover or focus |
| 6 | Click targets: small buttons 28 to 32 px, chips and segmented buttons 32 px, the 24 px cross on a dictionary word and the switches get a 32 px hit area; the 24 px minimum still holds |
| 7 | Red, pink and orange colour picks give a paler danger colour, and lettering on a danger fill is near-black (white was 2.4:1 on it even in the default theme) |
| 8 | "Undo last dictation" button in Settings, Dictation (and "undo that" in What Nova can do); "Sketch the answer" and "A photo on the note" in Settings, Colour & cursor |
| 9 | All 14 config-only settings now have a control: Whisper models (Voice), Deepgram model (Voice), tidy models (Dictation), Codex minutes model (Meetings), backup Gemini model, steps per request, background jobs, folders Nova skips and the suggestion limits (AI), past notes a skill reads (Routines), the AI's own browser window (Browsers), what "Hey Nova" and three taps start (Shortcuts), and the sketch pair |
