# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Desktop app in Python. The companion window is pywebview rendering one local HTML file (`core/app.html`, no network, no build step); the always-on bar and reply card stay Tkinter. Chosen by the user.

## Users

Developers on Windows and macOS who already use Claude Code or Codex, speak English or Hinglish, and want voice control and dictation while they work. Also non-technical people: setup, onboarding and settings must work for someone who has never opened a terminal or heard of npm.

## Product Purpose

Nova is a voice layer for the computer. Say "Hey Nova", press a shortcut or click the bar, then talk. Assistant mode hands the request to Claude Code or Codex and answers out loud; dictation mode types clean text (fillers removed, self-corrections applied, Hinglish in Roman letters) into whatever app has focus. Success: the user talks instead of typing and never has to touch a config file or a console.

## Positioning

Nova uses the AI subscription the user already has (Claude Code or Codex CLI) instead of its own cloud, keeps speech recognition and the wake word fully on-device, and gates every command the AI runs through a local safety guard that asks before anything risky.

## Operating Context

- Lives in the Windows tray (hidden icons area) or the macOS menu bar; starts at login.
- A small pill bar sits bottom-centre of the screen; a reply/approval card appears bottom-right.
- The companion window opens from the tray icon: chat, history, dictionary, settings, first-run onboarding.
- Used mid-task, in other apps: Nova must never steal focus while dictating.

## Capabilities and Constraints

- Offline STT (faster-whisper, GPU when available), offline OS voices for replies.
- Brains: Claude Code (`claude -p`) or Codex (`codex exec`); the user can switch.
- Guard tiers: allow / confirm (asks the user) / block.
- Settings live in `config.json` (only overrides) on top of `config.default.json`.
- No Nova server, account or analytics.

## Brand Commitments

- Name: Nova. Accent violet `#7b6dff` (tray icon, bar, card). Voice: plain, short, friendly, no jargon.

## Evidence on Hand

No testimonials, user counts or benchmarks beyond the speed notes in README.md. Do not invent any.

## Product Principles

1. Talk, don't type: every flow should be finishable without a keyboard-heavy detour.
2. Never surprise: risky actions are shown verbatim and need an explicit OK.
3. Local first: say clearly what leaves the computer and when.
4. Zero terminal: non-technical users never need a console or a JSON file.

## Accessibility & Inclusion

Keyboard-operable window, visible focus, readable contrast in light and dark, reduced-motion respected.
