---
name: Nova
description: An always-dark command deck for a voice layer: Nova's state, Claude's real numbers and your skills around one living point-cloud orb.
colors:
  ground: "#080a15"
  dock: "#0a0c19"
  panel: "#0f1226"
  raised: "#151833"
  sunk: "#060812"
  hairline: "rgba(143, 149, 230, .16)"
  hairline-strong: "rgba(143, 149, 230, .30)"
  text: "#e8eaff"
  muted: "#a3a9d2"
  faint: "#8a90bd"
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
    letterSpacing: ".18em"
rounded:
  xs: "6px"
  sm: "8px"
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

The Nova window is a deck, not a menu. Nova's state, Claude's real numbers, your skills and your next request sit around one living orb instead of a sidebar and a page of cards. It is always dark, whatever the system theme: deep navy ground, violet-tinted hairlines, one violet accent. The look is lent by a user-pinned reference (V.A.U.L.T. / Jarvis screens, "agentic OS"): it supplies mono for data and labels, the palette, the density and one signature (the orb). Navigation and controls stay standard.

Density is high but calm. Data is mono, anything you read is the system sans. Panels are boxed on purpose (1px hairline, 12px corners); the reference's frameless look was considered and not adopted, because boxes keep each vital scannable at a glance and in a 820x580 window.

Nova's brand violet is #7b6dff (tray icon, bar, reply card, orb). In this window the working accent is #6d5ff7 for fills and #b9b1ff for violet text and marks, so white button text and small violet text both stay legible on the navy ground.

**Key Characteristics:**
- Always dark; three stacked `:root` token blocks in app.html, the third wins.
- Mono for labels, numbers and the CORE / LINK / JOBS strip; system sans for prose.
- Tonal layering and 1px violet hairlines for depth; one soft shadow on the central stage only.
- One signature: the point-cloud orb, reactive to state.
- Amber means waiting on you; green means ok; red is for failure and destruction only.

## Colors

A navy ground with a single violet voice, amber reserved for "needs you".

### Primary
- **Signal Violet** (#6d5ff7): fills for primary buttons, the on-switch, selected-engine border, composer focus border. Hover #5e4ff0.
- **Lilac Ink** (#b9b1ff): violet as text and mark: gauge fill, active-tab icon, orb-adjacent progress, skill icons, typing dots.
- **Violet Haze** (rgba(123, 109, 255, .16)): hover and selected wash on tabs, skill rows, library rows, user messages.

### Secondary
- **Waiting Amber** (#ffba3c): approvals and warnings only: the approval strip border and heading, tab badge dot, plan warning line.

### Neutral
- **Deep Navy Ground** (#080a15): window and central stage base; the stage fades from #171a38 at the centre.
- **Dock Navy** (#0a0c19): the top dock.
- **Panel Navy** (#0f1226): HUD panels, drawn at 85% (details at 70%) over the ground.
- **Raised Navy** (#151833): hover for neutral buttons and tabs.
- **Sunk Navy** (#060812): inset wells: command buttons, search field, segmented control track.
- **Hairline** (rgba(143, 149, 230, .16)) and **Strong Hairline** (.30): panel borders and the rule after each caption.
- **Cloud White** (#e8eaff) text, **Mist** (#a3a9d2) secondary text and mono labels, **Dusk** (#8a90bd) placeholders and timestamps.
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
- **Label** (mono 400, 11px, +.18em, uppercase): section captions with a trailing rule, vitals keys (+.14em), deck status (+.16em), the closed "What Nova can do" summary. Skill rows are mono 500 12px, +.06em, uppercase.

### Named Rules
**The 11px Floor Rule.** No Home text is smaller than 11px; mono caps labels sit exactly at 11px, never below. (The walkthrough mock scene scales down to 9.5px as an illustration, which is not part of the deck.)
**The Mono Is Data Rule.** Mono carries labels, numbers and status; sentences stay in the sans.

## Layout

The shell is a grid of a dock row and a scrolling main. Home is a three-column deck: `minmax(240px, 300px) | minmax(0, 1fr) | minmax(240px, 300px)`, 14px gaps, 14px 16px padding. Left: Claude vitals, System status, Recent. Middle: greeting and the CORE / LINK / JOBS strip, the orb filling the stage, the running-job card (176px wide, bottom-right of the stage), the reply or approval strip, the request box. Right: Nova skills, Claude skills (search, a two-column deck of 8 command buttons, "All N"), Library, a closed "What Nova can do". Columns scroll inside; the page never overflows. Panel rhythm is 12px between panels, 12-14px internal padding.

Responsive: under 1000px the orb comes first and the panels sit under it, two across (`repeat(auto-fit, minmax(250px, 1fr))`). The dock sheds text in steps: under 1560px the live-state detail, Mode labels and Pause label go to icons; under 1180px only the active tab keeps its label; under 900px all tabs are icons and the brand and state text hide. Minimum window 820x580.

Inner pages (Chat, History, Meetings, Dictionary, Skills, Memory, Settings) keep the dock and palette inside a centered column of max 940px with 40px padding.

## Elevation & Depth

Tonal layering plus hairlines. Surfaces are flat at rest: depth comes from navy steps (sunk, ground, panel, raised) and translucent panels over the stage. A soft shadow (`0 1px 2px rgba(0,0,0,.5), 0 12px 32px rgba(0,0,0,.4)`) exists as `--shadow` and is used on the central stage and the active segment of the Mode switch. Focus is a 3px violet ring (`0 0 0 3px rgba(123,109,255,.5)`).

### Named Rules
**The Hairline Depth Rule.** Panels are separated by 1px violet-tinted lines and tone, not by shadows. The central stage is the one lifted object.

## Shapes

Softly rounded rectangles. Corners are 12px on panels, 14px on the central stage, 10px on the strip and segmented control, 8-9px on buttons, fields and rows, 7px on tab/skill rows, 999px on chips. Status dots and the round send button are circles. Gauges are 4px tracks with a rounded fill. Boxed panels are intentional (see Overview).

## Components

### Buttons
- **Shape:** 9px radius, 34px tall (28px small, 42px large).
- **Primary:** Signal Violet (#6d5ff7) fill, white text, 0 14px padding; hover #5e4ff0.
- **Default:** Panel Navy fill, strong hairline border; hover Raised Navy. **Ghost:** transparent, Mist text. **Danger:** coral text, solid coral when armed.
- **Pressed:** 1px downward nudge; disabled at 50% opacity.

### Command buttons (Claude skills deck)
Sunk Navy wells, 8px radius, 1px hairline, 12.5px sans 500 text clamped to two lines, in a two-column grid with 6px gaps. Hover is the violet wash with a strong hairline. Beneath: a search field and an "All N" link.

### Panels
`hud-panel`: 85% Panel Navy, 1px hairline, 12px radius, 12px 14px padding. Each opens with a mono caption and a trailing strong-hairline rule. Vitals rows end in a hairline divider: mono key, mono value, one mono detail line.

### Dock and navigation
Brand, live-state pill (mini canvas plus mono state and detail), centered tabs, Mode switch, Pause. Tabs are 8px-radius, Mist text, Raised Navy on hover; the active tab takes the violet wash, Cloud White text and a Lilac icon. A small amber dot badges a tab that needs you.

### Request box
Translucent ground fill, 12px radius, strong hairline, borderless textarea (max 120px). Focus-within turns the border violet and shows the focus ring.

### Reply and approval strip
Sits above the request box, 10px radius, strong hairline on near-black. Approval mode: amber border, 9% amber tint, amber heading, actions in a wrapping row. Working state shows three blinking dots (static at reduced motion).

### The Orb (signature)
A 600-point cloud joined to its 3 nearest neighbours, drawn on canvas in violet (hue 248), sized to about 36% of the stage's short side. State drives it: listening tightens (spread .88) and follows the microphone; thinking spreads loose (1.18) and spins fastest; speaking is brightest and pulses with the level; approval and paused are still and dim; "working" maps to thinking. Calm states redraw at 20 fps (idle) or 10 fps (approval, paused, gone); the loop stops when Home is hidden. Reduced motion freezes twinkle and keeps only a slow small swell while speaking. The orb has no chrome around it.

## Do's and Don'ts

### Do:
- **Do** use the tokens (`--bg`, `--surface`, `--sunk`, `--line`, `--accent`, `--accent-text`); raw hex only where the stage gradient needs it.
- **Do** set labels, numbers and statuses in `--mono`, 11px minimum, uppercase with wide tracking for captions.
- **Do** end a section caption with the strong hairline rule.
- **Do** use Lilac Ink (#b9b1ff) for violet text and Signal Violet (#6d5ff7) only for fills.
- **Do** keep the app dark in every system theme, and honor reduced motion.
- **Do** keep panels boxed (1px hairline, 12px radius) with the page never scrolling.

### Don't:
- **Don't** use amber for anything but waiting on the user.
- **Don't** set sentences or long prose in mono.
- **Don't** add a second accent hue or a gradient fill on controls.
- **Don't** put text under 11px on the deck.
- **Don't** start a theme by copying the first two `:root` blocks into new window UI; the phone page and browser panel still use them, tests.py compares only those two.
- **Don't** put chrome (frame, ring, glow box) around the orb.

**Exemption: the onboarding scene.** The walkthrough's `.scene` is a scaled illustration of the product (em-based radii, fluid type, its own small palette above). It is not part of the system's scale.
