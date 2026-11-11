---
name: Nova
description: An always-dark obsidian command deck for a voice layer, and one morphing glass HUD: Nova's state, Claude's real numbers and your skills around one soft point-cloud orb.
colors:
  ground: "#0a0a0c"
  dock: "#0c0c10"
  panel: "#111218"
  raised: "#1a1b22"
  sunk: "#07070a"
  hairline: "rgba(255, 255, 255, .07)"
  hairline-strong: "rgba(255, 255, 255, .13)"
  specular: "inset 0 1px 0 rgba(255, 255, 255, .06)"
  hud-glass: "rgba(12, 13, 18, .82)"
  text: "#f3f4f6"
  muted: "#a1a3ad"
  faint: "#8b8d97"
  accent: "#6d5ff7"
  accent-hover: "#5e4ff0"
  accent-text: "#b9b1ff"
  accent-soft: "rgba(123, 109, 255, .16)"
  amber: "#ffba3c"
  ok: "#3ecf8e"
  danger: "#ff7a7a"
  on-accent: "#ffffff"
  recording: "#e5484d"
  brand-violet: "#7b6dff"
  brand-blue: "#5a8cff"
  brand-cyan: "#3fd6e6"
  brand-pink: "#e0479a"
  scene-ink: "#d4d7e8"
  scene-muted: "#a4a8c2"
  scene-ok: "#2f9e63"
  shadow-ink: "rgba(0, 0, 0, .3)"
typography:
  body:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", -apple-system, BlinkMacSystemFont, \"SF Pro Text\", system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  greeting:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", -apple-system, system-ui, sans-serif"
    fontSize: "19px"
    lineHeight: 1.25
  page-title:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", -apple-system, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-.02em"
  numeral:
    fontFamily: "ui-monospace, \"Cascadia Mono\", \"SF Mono\", Consolas, Menlo, monospace"
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-.02em"
  value:
    fontFamily: "ui-monospace, \"Cascadia Mono\", \"SF Mono\", Consolas, Menlo, monospace"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.35
  ui-small:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", -apple-system, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  detail:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", -apple-system, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.45
  display:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", -apple-system, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 650
    lineHeight: 1.2
  code:
    fontFamily: "\"Cascadia Code\", \"SF Mono\", Consolas, ui-monospace, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "ui-monospace, \"Cascadia Mono\", \"SF Mono\", Consolas, Menlo, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: ".08em"
rounded:
  kbd: "5px"
  xs: "6px"
  sm: "8px"
  control: "9px"
  md: "10px"
  lg: "12px"
  xl: "14px"
  xxl: "24px"
  pill: "999px"
spacing:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "14px"
  xl: "16px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "9px"
    height: "34px"
    padding: "0 14px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-default:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "9px"
    height: "34px"
    padding: "0 14px"
  hud-panel:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.lg}"
    padding: "12px 14px"
  command-button:
    backgroundColor: "{colors.sunk}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "7px 9px"
  request-box:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: "7px 8px 7px 14px"
  dock-tab-active:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "7px 11px"
---

# Design System: Nova

## Overview

**Creative North Star: "The Command Deck"**

The Nova window is a deck, not a menu. Nova's state, Claude's real numbers, your skills and your next request sit around one living orb instead of a sidebar and a page of cards. It is always dark, whatever the system theme: neutral obsidian (#0a0a0c), hairlines of white at 7%, one accent. Mono carries data and labels; navigation and controls stay standard. It assumes you know how to use it: no instruction paragraphs on the deck, one-sentence descriptions in Settings.

Density is high but calm. Panels are quiet glass: a 1px white-7% hairline, 14px corners and a specular top edge (`--lit`, an inset white-6% line), so depth reads as light from above rather than as boxes. Captions are mono caps with no rule after them; whitespace separates sections.

The colour picked in Settings → Colour & cursor is the accent only: fills, focus, violet text, the orb, the bar's sparkle, waveform and glow, and the five bars of the mark. Surfaces stay neutral for every pick (`themeTokens` in `core/app.html` and `core/theme.py` keep `k = 0`). Every pick keeps the contrast targets below (checked in `tests.py`): lettering on the accent at 4.5:1 or better (near-black when white can't reach it, as on yellow), accent text 7:1 on the panels. Read "violet" in this file as "the chosen colour".

On Windows the dock is the title bar (drag it to move, double-click to maximize); the edges resize it natively, and it snaps to the screen's edges. The window draws its own –, □ and × in the dock's top-right corner (core/winframe.py) and answers them as Windows' own, so hovering □ brings up the snap layouts. The Mac keeps its traffic lights.

**The HUD is one shape of frosted glass** at the top centre of the screen (or the bottom, above the taskbar): obsidian (12, 13, 18 at 82%) over the blurred, saturated screen behind it, a white-9% hairline with a brighter top line, a soft accent wash high on the left, a faint accent glow around it. The pill (168×42 at rest) holds Nova's mark, a word and what the state adds: ✦ Ask; the live voice as eight light-to-accent bars; a frameless stop square. When Nova thinks, speaks or has something to say, the pill grows into a card (440 wide) in the same window on a spring, and shrinks back after: never a second box under the pill, never the same status twice. The card leads with what matters: the question, quiet (white 50%, one line) above a hairline, then the step Nova is on with light sweeping across it, or the answer in crisp white; short notices ("Nova is ready", "Cancelled") stay one line, the pill's height. Amber is Needs your OK only; Allow is the HUD's one solid fill.

**Motion (the HUD).** Every change the HUD makes moves, on transitions.dev's motion scale (core/bar.py: QUICK 150 ms, FAST 250, SLOW 400, VERY_SLOW 500; the smooth-out curve for opening and resizing, ease-in-out for swaps; a 2 px cross-blur). It arrives like a toast (up from a few px above, a touch smaller, fading in out of a blur, 400 ms) and leaves the same way, quicker (250 ms). The pill grows into the card on a spring, and the card's content waits until the glass has nearly reached its size. New words swap in place: the old ones leave upward through a blur as the new ones rise in. The step Nova is on shimmers. An answer's lines rise in 60 ms apart. An error shakes (8, 8, 6, 6 px). Nova's logo is the real mark, alive: its bars rise into place when it appears, follow the microphone, roll a wave while thinking and swing like a voice while talking. Reduced motion turns all of it into plain cuts.

**Key Characteristics:**
- Always dark, neutral obsidian; three stacked `:root` token blocks in app.html, the third wins.
- Mono for labels, numbers and the CORE / LINK / JOBS strip; system sans for prose.
- Hairlines of white at 7% and a specular top edge for depth; the accent is a glow, never a tint.
- One signature: the point-cloud orb, reactive to state.
- Amber means waiting on you; green means ok; red is for failure and destruction only.

## Colors

An obsidian ground with a single violet voice, amber reserved for "needs you".

### Primary
- **Signal Violet** (#6d5ff7): fills for primary buttons, the on-switch, selected-engine border, composer focus border. Hover #5e4ff0.
- **Lilac Ink** (#b9b1ff): violet as text and mark: gauge fill, active-tab icon, orb-adjacent progress, skill icons, typing dots.
- **Violet Haze** (rgba(123, 109, 255, .16)): hover and selected wash on tabs, skill rows, library rows, user messages.

### Secondary
- **Waiting Amber** (#ffba3c): approvals and warnings only: the approval strip border and heading, tab badge dot, plan warning line.

### Neutral
- **Obsidian Ground** (#0a0a0c): window base; the stage fades from the panel colour at the centre, with an accent glow at 10% behind the orb.
- **Dock** (#0c0c10): the top dock, which is also the title bar.
- **Panel** (#111218): HUD panels, drawn at 65% over the ground.
- **Raised** (#1a1b22): hover for neutral buttons and tabs.
- **Sunk** (#07070a): inset wells: search field, segmented control track.
- **Hairline** (white 7%) and **Strong Hairline** (white 13%): panel borders and dividers.
- **Text** (#f3f4f6), **Muted** (#a1a3ad) secondary text and mono labels, **Faint** (#8b8d97) placeholders and timestamps.
- **Go Green** (#3ecf8e) ok dots; **Alert Coral** (#ff7a7a) danger text.

### Named Rules
**The Waiting Rule.** Amber appears only when the system is waiting on the person. If everything is fine, there is no amber on screen.
**The One Voice Rule.** Violet is the only accent; status colors never decorate.

## Typography

**Display Font:** none; the window has no display face. Headings are the system sans.
**Body Font:** Segoe UI Variable Text / Segoe UI / SF Pro Text / system-ui.
**Label/Mono Font:** `ui-monospace` stack (Cascadia Mono, SF Mono, Consolas, Menlo), exposed as `--mono`.

**Character:** Plain system sans for everything you read, a technical mono voice for everything you scan. The pairing is the HUD.

### Hierarchy
- **Numeral** (mono 600, 34px, 1.1): the single large 5-hour-window figure in Claude vitals, tabular numbers.
- **Page title** (sans 650, 26px, 1.2, -.02em): inner pages; onboarding steps go to 30px.
- **Greeting** (sans, 19px, 1.25): the Home greeting above the orb.
- **Value** (mono 600, 15px): vitals values, one line, ellipsised.
- **Body** (sans, 14px, 1.5): default; panel rows 12-13px, command buttons 12.5px.
- **Label** (mono 400, 11px, +.08em, uppercase): section captions (no rule after them), vitals keys, deck status, the closed "What Nova can do" summary. Nova skill rows are mono 500 12px, +.06em, uppercase; Claude skills are one-line sans rows, ellipsised.

### Named Rules
**The 11px Floor Rule.** No Home text is smaller than 11px; mono caps labels sit exactly at 11px, never below. (The walkthrough mock scene scales down to 9.5px as an illustration, which is not part of the deck.)
**The Mono Is Data Rule.** Mono carries labels, numbers and status; sentences stay in the sans.

## Layout

The shell is a grid of a dock row and a scrolling main. Home is a three-column deck: `minmax(240px, 300px) | minmax(0, 1fr) | minmax(240px, 300px)`, 14px gaps, 14px 16px padding. Left: Claude vitals (plan line, the 5-hour hero and gauge, Today and 7 days side by side, a sparkline; where the numbers come from sits behind an ⓘ by the caption), System status and the walkthrough row, Recent (3). Middle: greeting and the CORE / LINK / JOBS strip, the orb filling the stage, the running-job card, the reply or approval strip, the request box ("Ask Nova anything…" with the talk keys as keycaps). Right: Nova skills, Claude skills (search, six one-line rows, "All N"), Library, a closed "What Nova can do". The page never overflows; a column scrolls only in a short window, its scrollbar hidden until you're on it. Panel rhythm is 12px between panels, 12-14px internal padding.

Responsive: under 1000px the orb comes first and the panels sit under it, two across (`repeat(auto-fit, minmax(250px, 1fr))`). The dock sheds text in steps (leaving room for the window buttons): under 1720px the live-state detail, Mode labels and Pause label go to icons; under 1600px only the active tab keeps its label; under 1000px all tabs are icons and the brand and state text hide. Minimum window 820x580.

Inner pages (Chat, History, Meetings, Dictionary, Skills, Memory, Settings) keep the dock and palette inside a centered column of max 940px with 40px padding.

## Elevation & Depth

Light from above. Panels and the stage carry a specular top edge (`--lit`: `inset 0 1px 0 rgba(255,255,255,.06)`) over a white-7% hairline; tone steps (sunk, ground, panel, raised) do the rest. `--shadow` is kept for popovers (the ⓘ note) and the active segment of the Mode switch. Focus is a 2px accent-text outline.

### Named Rules
**The Lit Edge Rule.** Panels are separated by white-7% hairlines, tone and a lit top edge, not by heavy shadows or tinted borders.

## Shapes

Softly rounded rectangles. Corners are 14px on panels and the central stage, 10px on the strip and segmented control, 8-9px on buttons, fields and rows, 7px on tab/skill rows, 999px on chips. Status dots and the round send button are circles. Gauges are 4px tracks with a rounded fill. Boxed panels are intentional (see Overview).

## Components

### Buttons
- **Shape:** 9px radius, 34px tall (28px small, 42px large).
- **Primary:** Signal Violet (#6d5ff7) fill, white text, 0 14px padding; hover #5e4ff0.
- **Default:** Panel fill, strong hairline border; hover Raised. **Ghost:** transparent, Muted text. **Danger:** coral text, solid coral when armed.
- **Pressed:** 1px downward nudge; disabled at 50% opacity.

### Claude skills rows
One column of one-line rows, 12.5px sans 500, ellipsised (the full name and description in the tooltip), no frame at rest; hover is the accent wash and a hairline. Above: a search field; beneath: an "All N" link.

### Panels
`hud-panel`: Panel at 65%, white-7% hairline, the lit top edge, 14px radius, 12px 14px padding. Each opens with a mono caption (no rule). Vitals rows: mono key, mono value, one mono detail line.

The Claude vitals panel has three states besides its numbers. **Limit reached**: Claude Code wrote that it hit a limit, so the hero reads "Limit reached" in the numeral's mono at 22px (a word, so a step under the 30px figure, one line even in the 820px window) with a full gauge, its caption says which ("5-hour window" or "Weekly limit") and the line under it says when it resets (days and hours for a weekly one). **Signed out**: the plan line turns amber ("Claude Code is signed out.") with a small Sign in button, since it waits on you. **Reading / couldn't refresh**: "Reading…" until the first scan, and an amber foot naming the time of the numbers shown. The System panel's Brain row says "signed out" (amber dot, as it waits on you) or "Codex (Claude Code isn't set up)" (amber) when Nova runs the other AI; it agrees with Settings → AI.

The Library ends with **Nova Pro** ("Vote on what comes next"), which opens the poll on GitHub in the browser.

### Dock and navigation
Brand, live-state pill (mini canvas plus mono state and detail), centered tabs, Mode switch, Pause, then (Windows) – □ × after a hairline. Empty dock drags the window. Tabs are 8px-radius, Muted text, Raised on hover; the active tab takes the violet wash, Text white and a Lilac icon. A small amber dot badges a tab that needs you.

### Request box
Translucent ground fill, 12px radius, strong hairline, borderless textarea (max 120px). Focus-within turns the border violet and shows the focus ring.

### Reply and approval strip
Sits above the request box, 10px radius, strong hairline on near-black. Approval mode: amber border, 9% amber tint, amber heading, actions in a wrapping row. Working state shows three blinking dots (static at reduced motion).

### The Orb (signature)
A 600-point cloud joined to its 3 nearest neighbours by faint threads (a soft cloud, not a wireframe), drawn on canvas in violet (hue 248) over a soft glow, sized to about 36% of the stage's short side. State drives it: listening tightens (spread .88) and follows the microphone; thinking spreads loose (1.18) and spins fastest; speaking is brightest and pulses with the level; approval and paused are still and dim; "working" maps to thinking. Calm states redraw at 20 fps (idle) or 10 fps (approval, paused, gone); the loop stops when Home is hidden. Reduced motion freezes twinkle and keeps only a slow small swell while speaking. The orb has no chrome around it.

### First-run setup
Two columns inside the full-window overlay (max 1180px): what to do on the left (title 30px, lede, rows and controls), and on the right the stage. The stage holds Nova's bar (the `pill()` canvas, 196px wide), the orb (the same singleton, moved onto the setup while it's open and handed back to Home on close) and a mono readout of what's set up (Mic, AI, browser, email, apps, Obsidian), green dots when done. The stage stays in view while a long step scrolls. The orb acts out the step: it plays Nova's four states on the welcome, follows the microphone level on the mic step, and answers (speaking, 1.8s) when a step becomes ready. Tour steps put their live scene in the stage instead. Progress is five named chapters (Hello, Try it, Your AI, Your apps, Ready) in mono caps with a tick per step, not a row of dashes. A setup step's main button says "Set up later", unhighlighted, until something is set up, then Continue. Under 960px the stage sits above the step, the orb at 19vh and without the bar.

The walkthrough clips (`docs/video/build.py`, DECK) use the same world at 1920×1080: navy ground with a violet field behind a dark desktop, the bar as indigo glass at the desktop's top centre that drops in after a glow at the top edge, the heard bubble in Signal Violet, and the reply or approval card growing out of the bar.

## Do's and Don'ts

### Do:
- **Do** use the tokens (`--bg`, `--surface`, `--sunk`, `--line`, `--accent`, `--accent-text`); raw hex only where the stage gradient needs it.
- **Do** set labels, numbers and statuses in `--mono`, 11px minimum, uppercase with .08em tracking for captions.
- **Do** keep keycaps compact: mono 11px, 5px radius, white 6% on a white-10% edge.
- **Do** use Lilac Ink (#b9b1ff) for violet text and Signal Violet (#6d5ff7) only for fills.
- **Do** keep the app dark in every system theme, and honor reduced motion.
- **Do** keep panels as quiet glass (hairline, lit top, 14px radius) with the page never scrolling.
- **Do** keep the HUD one shape: grow the pill into the card; keep the heard text quiet (white 50%), text in the HUD at 50% white or brighter.

### Don't:
- **Don't** use amber for anything but waiting on the user.
- **Don't** set sentences or long prose in mono.
- **Don't** add a second accent hue or a gradient fill on controls, or tint surfaces with the accent.
- **Don't** put a rule after a caption, a box inside a box, or a well around the HUD's mark, words or stop.
- **Don't** put text under 11px on the deck.
- **Don't** start a theme by copying the first two `:root` blocks into new window UI; the phone page and browser panel still use them, tests.py compares only those two.
- **Don't** put chrome (frame, ring, glow box) around the orb; the stage's soft accent glow is the only light behind it.

**Exemption: the onboarding scene.** The walkthrough's `.scene` is a scaled illustration of the product (em-based radii, fluid type, its own small palette above). It is not part of the system's scale.
