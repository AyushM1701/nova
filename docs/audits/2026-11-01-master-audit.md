# Nova app: master audit

Date: 2026-11-01. This merges two audits of the same build: **Impeccable v4.8.0** (engine 0.1.18: its scored audit, its rendered and static detector) and **ui-ux-pro-max** (repo commit `3a13158`, its 10-category rule list, read-only searches). Opus reviewed how to merge them (see "How this was built"). Nothing was fixed while writing it. **Status: the P1, all five P2s and the P3 list were fixed in follow-up passes the same day; see sections 9 and 10.** Sections 1 to 8 are the audit as first written.

**One severity standard for every finding:** WCAG 2.2 AA, applied to the surface it fits. The Nova window is pointer-first with a 820x580 minimum, so the bar for targets is 24x24 CSS px (SC 2.5.8). The 44 px touch rule applies to the phone page only. Everything else (type size, motion, scale drift) is a quality heuristic and capped at P3 unless a WCAG criterion is failed.

## 1. Scope and state

**The run all numbers come from:** one re-measurement of the current, uncommitted build, on this PC (Windows 11, WebView2), in the real window driven through its debug port, plus the static detector. Earlier numbers in the two separate audits were taken before four later changes (pill contrast fix, companion off by default, DESIGN.md written, Settings label edits) and are not used.

| What | Covered |
|---|---|
| Window pages | Home, Chat, History, Meetings, Dictionary, Skills, Memory, Settings (13 tabs: general, shortcuts, cursor, voice, microphone, dictation, meetings, ai, routines, browsers, phone, privacy, advanced) |
| Widths | 1333, 820 (the minimum), 410 and 320 CSS px (reflow) |
| Checks | rendered detector (7 pages + 3 Settings tabs), 39 keyboard stops on Home, control names, target sizes, headings, landmarks, live regions, reflow, text sizes, label presence, target gaps, static detector on all four web files |
| Phone page (`core/phone.html`) | **Rendered once at 375 px, with no connection**, so only its idle state; plus static scan |
| Browser panel (`browser/extension/panel.html`) | Rendered once, idle state; plus static scan |

**Not audited. Read this before relying on the score:**
- **The Tk bar, reply card and pointer marker.** They are not web surfaces; neither tool covers them.
- **macOS** (WKWebView; the `:has()` rule used on Home needs Safari 15.4 or later).
- **Any screen reader**, and **Windows high-contrast / forced-colors mode**.
- **The phone page when connected** (the chat thread, approvals) and **the browser panel when connected**.
- **Keyboard behaviour of the onboarding overlay and the walkthrough.**
- The window is always dark now, so there is no light OS theme to audit.

## 2. Score (Impeccable's five dimensions; ui-ux-pro-max has no scoring, its findings are mapped in)

| # | Dimension | Score | Key finding |
|---|---|---|---|
| 1 | Accessibility | **2** | Every custom focus ring is 2.1:1 against the panel (needs 3:1, SC 1.4.11, AA) |
| 2 | Performance | 3 | Orb costs about 16% of a core idle on Home; History draws every row |
| 3 | Theming | 3 | Tokens used 351 times against about 40 hard-coded colours; DESIGN.md out of step with the build |
| 4 | Responsive | 3 | Settings does not reflow at 320 or 410 px; the other 7 pages do |
| 5 | Implementation integrity | 3 | No AI-slop tells found; small isolated polish items |
| | **Total** | **14 / 20** | **Good: address the weak dimension (accessibility)** |

The first audit scored 15. The drop is a changed ruling, not a regression: the focus-ring contrast finding was first noted as an AAA item and is a P1 under AA (see D2).

## 3. Findings (each counted once, with all its locations)

Found by: **I** = Impeccable, **U** = ui-ux-pro-max, **both**.

| ID | P | Finding | Standard | Evidence | Found | Fix | Command |
|---|---|---|---|---|---|---|---|
| M-01 | **P1** | Keyboard focus ring is too faint on every control | WCAG 1.4.11 Non-text Contrast (AA): author-drawn focus indicators need 3:1 against the adjacent background | `:focus-visible` box-shadow `0 0 0 3px rgba(123,109,255,.5)`; over the panel (`#0f1226`) that is **2.12:1**. The lighter violet `#b9b1ff` would be 9.5:1. All 39 Home stops show a ring, it is just under 3:1 | U (as AAA) / I (passed: visible only) | Use an opaque `--accent-text` ring in `--focus` | `polish` |
| M-02 | P2 | Settings page does not reflow at 320 or 410 px | WCAG 1.4.10 Reflow (AA) | `#setTabs` is 445 px wide at a 320 px viewport (right edge 445), so `main` scrolls sideways; the narrow-layout rule makes the tab strip scroll but its grid track is `1fr` and grows to the strip's width. Other 7 pages: no overflow at 320, 410 or 820 | U | `grid-template-columns: minmax(0, 1fr)` in the narrow `.set-grid` rule | `adapt` |
| M-03 | P2 | Data-entry fields with a placeholder and no visible label | WCAG 3.3.2 Labels or Instructions (A). They do have `aria-label`, so 4.1.2 is met | `wordInput` (Dictionary), `memInput` (Memory), `fbKey` and two more inputs in Settings → AI | U | Visible labels or helper text above the fields | `clarify` |
| M-04 | P2 | Claude's live numbers have no "as of" time and no failure state | ui-ux-pro-max live-telemetry pattern; not a WCAG criterion | Deck refreshes every 5 s; `loadDeck` swallows errors (`catch (e) { }`), so a failed read leaves old numbers looking current | U | Show "updated 12:41" and a quiet "couldn't read Claude's files" state | `harden` |
| M-05 | P2 | History lines are far too long | Heuristic (65 to 75 ch); both tools | About 128 characters per line on 48 rows of History, 110 on Chat replies (detector `line-length`, pages: History, Chat) | both | `max-width: 70ch` on `.feed .body .t` and reply text | `layout` |
| M-06 | P2 | Design system out of step with the build | Impeccable design-system drift; ui-ux-pro-max `font-scale`, `spacing-scale`, `consistency` | **32 static findings in `core/app.html`**: **about 7 are DESIGN.md gaps** (it was written from Home and lacks the 12, 12.5 and 13 px sizes and the 7 and 9 px radii the Home deck uses, `Cascadia Code`, and the `#3fd6e6` brand-gradient colour); **about 25 are legacy CSS** (chat 6, onboarding scene 9, controls 5, old home 2, shared 3, Settings 1; the split is by CSS section, so one or two could go either way). The onboarding scene is an illustration and can be exempt. App-wide: 18 font sizes, 17 radii, 16 gap values | both | Document the missing scale in DESIGN.md first; then fold the legacy radii and sizes onto the scale | `document`, then `polish` |
| M-07 | P3 | Errors appear only as a toast | WCAG 3.3.1 is met: the toast is `role="status"` (announced). Placement is the issue | 30 `fail()` call sites, e.g. a refused notes folder | U | Put the message beside the field where there is one | `clarify` |
| M-08 | P3 | Small mono labels | Heuristic only; WCAG has no minimum size | 21 elements on Home are under 12 px (all 11 px caps labels and detail lines); none under 11 px. Detector `tiny-text` flags 2 at 11 and 11.5 px | both | Raise detail lines to 12 px | `typeset` |
| M-09 | P3 | Chat and Meetings badges are colour-only dots | WCAG 1.4.1 (supplementary signal only) | `#chatBadge`, `#recBadge` have no text; the approval itself is announced (`role="alert"` on the Home strip and the chat card) | U | Add an `aria-label` | `harden` |
| M-10 | P3 | Dock tabs only show names when wide | Heuristic | At the default 1080 px window only the active tab shows its name; others have a tooltip title; tabs are 2 px apart | U | Show names to 1000 px, or widen gaps | `adapt` |
| M-11 | P3 | A few targets under 24 px | WCAG 2.5.8 (spacing exception covers isolated switches) | Switches 38x22 on 11 Settings tabs; Dictionary remove buttons 22x22; an input 180x16 px on Settings → Dictation (and earlier Voice), probably a slider, not confirmed; inline links exempt | both | 24 px minimum hit area | `adapt` |
| M-12 | P3 | Motion hygiene | Impeccable `bounce-easing`; ui-ux-pro-max `duration-timing`, `transform-performance` | One overshoot curve `cubic-bezier(.3,1.5,.5,1)` reported on every page (one rule, 10 pages); 24 transitions over 8 durations and 4 easings; one `transition: all`; one width animation (the job bar, linear, constant-rate, acceptable) | both | One duration and easing token set | `animate` |
| M-13 | P3 | Orphan words | Impeccable `straggler` | Last line holds one short word on Chat, Settings → AI, General, Voice | I | `text-wrap: pretty` | `typeset` |
| M-14 | P3 | Card inside card | Impeccable `nested-cards` | Settings → AI engine cards inside rows | I | Flatten one level | `layout` |
| M-15 | P3 | History draws every row | ui-ux-pro-max `virtualize-lists` | 199 controls on History after 30 days of use | U | Window the list, or cap and page it | `optimize` |
| M-16 | P3 | Phone page: no `h1` in its idle state; no `touch-action` | Heuristic | Rendered at 375 px: 7 controls all 44 px or more, all named, no sideways overflow, zoomable, reduced motion handled; its status text is 13 px | I (static) / rendered here | Add a heading; set `touch-action: manipulation` | `harden` |

**Totals: 1 P1, 5 P2, 10 P3.** No P0.

## 4. Where the two audits disagreed, and the ruling

| # | Disagreement | Ruling and reason |
|---|---|---|
| D1 | ui-ux-pro-max: 44 px targets are critical. Impeccable: 24 px (WCAG 2.5.8) | **24 px for the window** (pointer-first). 44 px applies to the phone page, which passes. Applying a touch rule to the window would fill the report with noise |
| D2 | ui-ux-pro-max cited Focus Appearance (AAA) for the ring. Impeccable passed any visible ring | **P1.** The W3C Understanding page for 1.4.11 says a focus indicator the author draws must have 3:1 against the adjacent background; only the browser's own unmodified indicator is exempt. Nova draws its own. Opus asked for this to be checked against the primary source, and it was |
| D3 | Impeccable's detector flags body text under 11 px (2 hits); ui-ux-pro-max says under 12 px (21 hits) | **P3.** WCAG sets no minimum text size. Heuristic only |
| D4 | Impeccable counts DESIGN.md drift; ui-ux-pro-max ignores DESIGN.md but flags scale sprawl | Both are right about different halves. Split into M-06's two parts, because the fix differs (edit the document, or edit the CSS) |
| D5 | ui-ux-pro-max `scroll-behavior`: avoid nested scroll regions. Impeccable did not flag them | **Intentional.** Home's two side columns and the chat thread scroll on their own by design in a dashboard |
| D6 | ui-ux-pro-max treats placeholder-only inputs as one finding | **Split.** Data-entry fields are P2 (M-03). Search boxes and the two composers (`homePrompt`, `prompt`, `deckClaudeSearch`, `claudeSearch`, `histSearch`, `mtSearch`, `mtQuestion`) follow the common search-box pattern with an `aria-label`: P3, not listed separately |

## 5. Retracted, and fixed during the audit

- **Retracted:** "10 buttons without names on Home" was a measuring error. They sit in a closed `<details>`, where `innerText` is empty; `textContent` shows all 16 named.
- **Retracted:** "one Home tab stop with no focus ring" appeared in one run and did not repeat in a second 45-stop run (0 without a ring). Not counted.
- **Fixed earlier in the session:** selected pills (white on `#b9b1ff`, 1.9:1) and the pale "on" switch track. Now `--accent` with white at **4.54:1**. This was a regression caused by an earlier global colour swap.
- **Not a finding:** the cursor companion (separate decision: off by default).

## 6. Recommendations rejected from ui-ux-pro-max

- **Its design-system output.** For "voice assistant status dashboard dark" it returned a landing-page pattern and the Glassmorphism style. Nova is a desktop window, not a landing page, and the skill's own `blur-purpose` rule says blur is for dismissing a background, not decoration. Not adopted.
- **Native-mobile rules:** Dynamic Type, safe areas, haptics, bottom-nav limit of 5, 16 px base on mobile, lazy-loaded images (Nova has none). Not applicable to a desktop window. The top dock of eight tabs is fine for desktop.
- **44 px everywhere:** see D1.

## 7. What works

- Contrast on text: muted 8.1:1, faint 6.0:1, white on accent 4.54:1.
- Home keyboard stops showed a ring (but see section 9: the first check counted any box-shadow as a ring, and the selected Mode button's own shadow was hiding it); no keyboard traps seen; zero controls without a name; one `h1` per page, no skipped heading levels; `main`, `nav` and `header` landmarks.
- Live regions for toast, replies and approvals; reduced-motion rules (7 in the window, 2 on the phone page, 1 in the panel).
- No emoji icons; one icon family; one shadow token; z-index scale of 1, 20, 40; pinch-zoom allowed.
- No horizontal overflow at 820 px on any page; 7 of 8 pages reflow at 320 and 410.
- The orb stops drawing when Home is hidden or the window minimised; the sparkline and gauge have text equivalents.
- The rendered detector found no AI-slop patterns in the window.

## 8. How this was built

1. Both audits were run separately (Impeccable's detector plus measurements; ui-ux-pro-max's rule list applied by measurement in the real window).
2. Opus was asked how to merge them. It asked for: one fresh re-measurement instead of two snapshots of different builds; each issue counted once, not once per page; one severity standard; the focus-ring ruling checked against the W3C text; reflow tested at 320 px, not just 410; the placeholder and small-text findings split by what the standard actually requires; drift split into "document is behind" and "CSS is off"; the phone page rendered or listed as not audited. All of that was done.
3. Fixed nothing: this is a document.

**Suggested order of fixes:** M-01 (P1, one line), M-02 (one line), then M-03 to M-06, then the P3 list as one `polish` pass. Re-run both audits afterwards.

## 9. After the fix pass (same day, same method)

Every number below is from a fresh run on the fixed build: the real window over its debug port, the rendered and static detector, and a reflow check at 320 and 410 px on all 8 pages and all 13 Settings tabs.

| ID | Status | What was done | Measured after |
|---|---|---|---|
| M-01 | **Fixed** | The focus ring is now a 2 px **outline** in the light violet (`--accent-text`) instead of a half-strength box-shadow; the window's `--focus` token is the same opaque colour | 9.5:1 against the panel (was 2.1:1). **Found while fixing:** the old ring was also being covered on controls with their own shadow (the selected Mode button), and the first audit's check counted any box-shadow as a ring, so "39 of 39 show a ring" was too generous. With the strict check (a visible outline or the ring colour), 37 of 38 stops pass; the Home request box shows its ring on the box around it (`:focus-within`), not on the textarea, which is the pattern the Chat box uses too |
| M-02 | **Fixed** | Settings' narrow layout uses `minmax(0, 1fr)`; each setting's controls drop under its words and wrap; pills, add-forms and tags wrap; long help text breaks | No sideways overflow at 320 or 410 px on any of the 8 pages, and none on any of the 13 Settings tabs (before: `#setTabs` 445 px wide, then Voice, AI and Privacy as the layout was fixed in steps) |
| M-03 | **Fixed** | Visible labels on the Dictionary and Memory add-forms and the Meetings question box. Settings fields already sit under their row heading and keep their `aria-label`, so they were not changed | Labels present; the search boxes and the two composers stay as they are (P3, listed in D6) |
| M-04 | **Fixed** | The deck prints "Updated 3:09 pm" and, when a read fails, says "Couldn't refresh just now. These numbers are from 3:09 pm" in amber and keeps the old numbers. The Python side records the last good time and the error | Tested with a read that raises: the old numbers stay, the error shows, and the next good read clears it |
| M-05 | **Fixed** | History and chat text is limited to `62ch` (about 75 characters) | Detector `line-length`: gone on History and Chat (was about 128 and 110 characters; an intermediate `72ch` still measured about 87) |
| M-06 | **Fixed, with one exemption** | DESIGN.md now documents the 12, 13 and 30 px sizes, the code face, the 6 and 24 px radii, and the on-accent, recording, brand-gradient and illustration colours. Legacy CSS was moved onto the scale: radii 3, 4, 7, 9, 11, 18 and 22 px and sizes 18, 20, 22 and 28 px | Static findings in `core/app.html`: **32 down to 5**. The 5 left: the onboarding scene's em-based radii and fluid type (a scaled illustration of the product, exempt), and one font-stack parse quirk in the detector (the stack is documented). The phone page (13) and the browser panel (5) keep their older palette by decision and were not touched |

Also: the earlier 14/20 stands as the score at the time of the audit. A re-score needs the P3 list addressed; with the P1 gone and no P2 open, accessibility would be 3, giving about 16/20. Not re-scored formally.

**Still not audited:** the Tk bar, reply card and pointer marker; macOS; screen readers; Windows high-contrast mode (the new outline ring should show there, since outlines are kept in forced-colors, but this was not checked); the phone page and browser panel when connected. The P3 list (M-07 to M-16) is untouched.

## 10. The P3 pass (same day, same method)

Re-measured on the fixed build: the real window over its debug port, the rendered and static detector, and the reflow check at 320 and 410 px.

| ID | Status | What was done | Measured after |
|---|---|---|---|
| M-07 | **Fixed for fields** | An error from a field now sits under that field (`role="alert"`, the field marked invalid, cleared when the user types): the Google key, the speech key, the calendar address, and a refused notes folder (said in amber in the folder row) | Tried on the Google key: message under the box, `role=alert`, `aria-invalid`, gone on typing. The other `fail()` toasts are for buttons and installs, not fields, and stay toasts (they are announced) |
| M-08 | **Fixed** | Detail lines (vitals sub-lines, gauge note, sparkline axis, job card) are 12 px | 21 elements under 12 px on Home became 15, all of them 11 px **uppercase tracked labels**, kept on purpose (DESIGN.md's 11 px floor) |
| M-09 | **Fixed** | `role="img"` with names on both badges ("Nova needs your OK", "Recording") | Present |
| M-10 | **Partly fixed** | Tabs are 8 px apart between 900 and 1180 px, where they are icon-only | Below 900 px they go back to 2 px (8 px broke the 320 px reflow; caught and reverted in this pass). Names at the default 1080 px window are still only on the active tab; the tooltips and the screen-reader names stay. Not changed |
| M-11 | **Fixed** | Switches 42x24, Dictionary remove buttons 24x24, sliders 24 px tall | Only 3 inline links remain under 24 px, which WCAG 2.5.8 exempts |
| M-12 | **Fixed** | One easing (the fast-out curve) instead of four, no overshoot, three durations (.15, .25 and .45 s) instead of eight, the one `transition: all` made specific, the job bar moves by transform not width | Rendered detector `bounce-easing`: gone |
| M-13 | **Fixed** | `text-wrap: pretty` on paragraphs and list items | Detector `straggler`: gone |
| M-14 | **Fixed** | The Brain row in Settings → AI is a heading with its two engine cards, not a card around them | Detector `nested-cards`: gone |
| M-15 | **Fixed** | History draws 50 rows at a time with "Show 50 more (133 left)" | Tried: 50 rows, then 100 after one press; a new search or filter starts again at 50 |
| M-16 | **Fixed (static state only)** | The phone page has a hidden `h1` ("Nova") and `touch-action: manipulation` on its controls | In the file; its connected states were not rendered |

**Result.** The rendered detector now reports **no findings** on any page (it had `tiny-text`, `bounce-easing` on 10 pages, `straggler`, `line-length` and `nested-cards`). Static findings: `core/app.html` 5 (four are the exempt onboarding scene, one is a font-stack parsing quirk), `phone.html` 13 and the browser panel 5 (older palette, by decision). No overflow at 320 or 410 px on any page.

**Honest re-score: 17/20, Good (top of the band):** accessibility 3, performance 3, theming 3, responsive 4, implementation integrity 4. Not 18 or more because screen readers, Windows high-contrast mode, macOS, the Tk bar and the connected phone page are still not audited, and the orb still costs about 16% of a core idle on Home.

**One regression caught by the re-measurement:** the 8 px tab gap pushed the dock past the viewport at 320 px (page-level sideways scroll on every page). Fixed by keeping the gap at 2 px below 900 px.
