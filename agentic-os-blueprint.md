# Agentic OS Blueprint

Built from two sources, compared and merged:

- **[video]** Chase AI, "The Agentic OS Setup That Will 10x Claude Code" (31:18). Transcript plus 87 scene-change frames.
- **[carousel]** An 8-image carousel by Chase AI, "The Claude Agentic OS that's making everyone go nuts". The slides are numbered 01/09 to 08/09, so **slide 9 was not provided** and is not covered here.
- **[inferred]** My own reading or design. Nothing in the sources states it directly.

Names such as Jev, GPT-6 Astra, Luna and Opus 5.5 are used exactly as the sources write them. I could not verify them, and I do not describe what Jev is beyond what slide 4 says.

---

## 1. What each source shows

### The 8 carousel slides

| # | Content |
|---|---------|
| 1 | Title slide with a "JARVIS /V2" dashboard. A Claude Code / Codex toggle sits at the top. The left panel shows weekly usage (32%) and three "directives". The right panel has quick-access skills (Plan Today, Inbox Brief, Deep Research, Content Cascade, "browse all skills 21"), a voice panel (Tap to talk), a schedule, and an "AI wire". Annotated: Obsidian memory, Jev model routing, fully local voice. |
| 2 | The stack in five rows: Opus 5.5 / GPT-6 Astra (the brain), Jev (the model router), Whisper + Kokoro (local voice mode), Obsidian (the memory), custom skill architecture (repeat work, written down). |
| 3 | The brain. One switch changes the model and both dashboards follow. Claude Code mode shows a blue network orb ("CLAUDE"). Codex mode shows a white galaxy ("ASTRA"). |
| 4 | The router. Jev sorts requests instead of writing answers. Tier 1: rules and saved data, no AI, instant. Tier 2: a small fast model (Haiku / Luna). Tier 3: real work, which opens a Claude Code or Codex terminal or runs a skill in the background. |
| 5 | Voice. `SYSTRAN/faster-whisper` (26.3K stars) is the ears. `thewh1teagle/kokoro-onnx` (2.8K stars) is the voice. UI text: "Speech stays local. Transcripts go to the selected provider." |
| 6 | Memory. Everything saves to an Obsidian vault, and a `CLAUDE.md` file gives Claude the map. Karpathy-style `raw/`, `wiki/`, `outputs/`. The dashboard shown is labelled **"demo data"**. |
| 7 | Skills, drawn as three columns. Research → "catch up on AI news" → `/morning-intel` → daily 6:30. Content → "repurpose my videos" → `/content-cascade` → when the video goes live. Community → "answer members" → `/qa-digest` → Fridays. Advice: ask Claude which repeat tasks from your last 30 days qualify. |
| 8 | All together. You → (Jarvis web app \| Obsidian plugin) → the bridge ("one brain for both apps") → Jev sorts it → Tier 1 / 2 / 3 → saves reports → the vault (shared memory). A two-way "reads + records" arrow links the bridge and the vault. |

### Comparison

| In both | Video only | Carousel only |
|---|---|---|
| Obsidian vault as memory | Four-level framing: skills + loop engineering, memory + state, interface, distribution | **Jev**, a router with three tiers |
| `CLAUDE.md` as the map of the vault | Three ways to find skills (manual, mine sessions, interview) | Claude Code / Codex **brain switch** that both dashboards follow |
| Karpathy `raw/` → `wiki/` → `outputs/` | **Loop engineering**: log runs so future runs improve | **The bridge** shared by both front ends |
| Skills as one-click buttons | `index.md` at every folder level | Skill triggers: cron (6:30), event (video goes live), weekly (Fridays) |
| Web app and Obsidian plugin as two front ends | Desktop routines for scheduling | "AI wire" panel |
| Local voice model | Distribution: GitHub for the web app, hands-on for the Obsidian plugin | Named voice repos (faster-whisper, kokoro-onnx) |
| Skills run in the background, headless | `claude -p` billing caveat | |
| Domain-organised skills (research, content, community) | Workflow audit before any build | |
| Dashboard with metrics, usage meter and skill buttons | His real vault has more folders than three: content, daily-notes, dashboard-runs, graph-imports, inbox, ops, projects, raw, system, wiki | |
| Directives panel (video: pulled from Google Calendar; carousel: top 3 for today) | | |

### Where the two sources disagree or one leaves a gap

- **Two versions of one build [inferred].**
  - The video frames show a dashboard called V.A.U.L.T., Opus 4.8, and a vault note dated 2026-06-24.
  - The carousel shows "JARVIS /V2", a Claude Code / Codex toggle, Opus 5.5, and a clock reading Fri Oct 30.
  - Most likely the carousel describes a later version. Treat the carousel's router and brain switch as additions and the video's loop engineering as the foundation.
- **"Completely local" voice [video] vs slide 5 [carousel].** Only speech-to-text and text-to-speech run locally. The transcribed text still goes to whichever model provider is selected. Do not describe the whole system as private.
- **Usage meter tracks different things.** The video describes a Claude "5 hour window" counter; slide 1 shows weekly usage (32%). Same widget, different quota.
- **The carousel contradicts itself on voice.** Slide 1 labels it "Fully local voice"; slide 5 says transcripts go to the selected provider.
- **Skill discovery window.** The video says to mine your last 5-20 sessions. Slide 7 says the last 30 days. Both work. Use the longer window if you have the history.
- **Slide 6 figures are demo data.** The 18.4K subscribers and 126.3K views are placeholders. The video's 137K subscribers and 11.4M views are Chase's real numbers. Do not mix them.
- **The carousel has no loop engineering.** The only trace is the "reads + records" arrow on slide 8. The video's `dashboard-runs` folder fills that gap.
- **Headless runs are draft-only [video, hedged].** In the 25:36 frame the Inbox Brief note appears to say that drafts are not sent and that sending is reserved for interactive sessions. I read that off a small frame, so confirm the wording before depending on it. The blueprint adopts the rule either way.

---

## 2. Principles

1. **Skills and memory carry about 90% of the value [video].** Build levels 1 and 2 before any dashboard. They work in a plain terminal.
2. **Codify before you automate.** Do the task by hand, confirm it works, then turn it into a skill, then schedule it [video].
3. **Give Claude a map.** Every folder has an `index.md`, and the vault root has a `CLAUDE.md` [`CLAUDE.md`: video, carousel; per-folder `index.md`: video only]. This is cheaper and faster than letting it search.
4. **Route by cost [carousel].** Do not send a request to a big model if rules or a small model can answer it.
5. **One brain, many front doors [carousel].** Every interface talks to the same bridge and shares the same vault.
6. **Every run leaves a record [video, inferred].** Loops cannot improve without logs of past runs.
7. **Headless means draft-only [inferred, supported by the video].** A background run can write notes and drafts. Sending email, posting or spending money needs a human in an interactive session.
8. **Say what stays local.** Audio stays on the machine. Text goes to the model provider [carousel].

---

## 3. Architecture

```
                                YOU
                 (voice, text, button click, schedule)
                  |                              |
        +---------v----------+        +----------v---------+
        |  Web app (Jarvis / |        |  Obsidian plugin   |   LEVEL 3: interface
        |  V.A.U.L.T.)       |        |  (Command Center)  |   [video, carousel]
        +---------+----------+        +----------+---------+
                  \                              /
                   +-------------+--------------+
                                 |
                       +---------v----------+
                       |     THE BRIDGE     |   one brain for both apps
                       |  (local service)   |   [carousel; internals inferred]
                       +----+----------+----+
                            |          |
                 voice      |          |  reads + records
              +-------------+          |
              |                        |
   +----------v-----------+            |
   | STT: faster-whisper  |            |
   | TTS: kokoro-onnx     |            |   local [carousel]
   +----------+-----------+            |
              |                        |
   +----------v-----------+            |
   |   JEV  (router)      |            |   [carousel]
   +--+--------+--------+-+            |
      |        |        |              |
  Tier 1    Tier 2    Tier 3           |
  rules +   small     real work        |
  saved     fast      = Claude Code    |
  data,     model     or Codex,        |
  no AI     (Haiku /  interactive      |
            Luna)     terminal, or     |
                      headless skill   |
                      (claude -p)      |
      |        |        |              |
      +--------+--------+--------------+
                        |  saves reports
                 +------v-------------------------+
                 |  THE VAULT (Obsidian)          |   LEVEL 2: memory + state
                 |  CLAUDE.md, index.md per level |   [video, carousel]
                 |  raw/ wiki/ outputs/ runs/ ... |
                 +------^-------------------------+
                        |
                 +------+-------------------------+
                 |  SKILLS + AUTOMATIONS          |   LEVEL 1: backbone
                 |  skills, routines, loops       |   [video, carousel]
                 +--------------------------------+

   LEVEL 4: distribution. Web app via GitHub; Obsidian plugin set up by hand. [video]
```

---

## 4. Component specifications

### 4.1 Skills and automations (level 1) [video, carousel]

**Workflow audit.** List what you do each day and week by domain (research, content, community, agency, sales, finance, productivity). Find repeat tasks three ways:

1. Do it by hand first, then tell Claude "turn what we just did into a skill".
2. Ask Claude to read your last 10-20 sessions [video] or last 30 days [carousel] and produce a table: repeated task, expected output, proposed skill.
3. Have Claude interview you from a stream-of-consciousness description of your week, flagging blind spots.

**Skill template (one folder per skill, `SKILL.md` inside).**

| Field | Content |
|---|---|
| Name | `/morning-intel` style, verb-or-noun, lower-case |
| Domain | research, content, community, and so on |
| Trigger | manual button, cron time, or event |
| Inputs | where it reads from (vault paths, APIs) |
| Steps | numbered, the way you would brief an assistant |
| Output | exact shape and where it is saved in the vault |
| Safety | read-only, draft-only or needs-human |
| Log | what it appends to `runs/` |

**Example skills from the carousel [carousel].**

| Skill | Does | Trigger |
|---|---|---|
| `/morning-intel` | AI news from YouTube and GitHub → one brief | Daily 6:30 |
| `/content-cascade` | One video → three posts (YouTube and LinkedIn) | Event: video goes live |
| `/qa-digest` | Community questions → one post | Fridays |

**Skills visible in the video [video].** Plan Today, Plan Tomorrow, Morning Brief, Inbox Brief, Weekly Review, Vault Cleanup, Deep Research, Content Cascade, YT Pipeline, Pull Metrics, `/whats-new <tool>`.

**Scheduling.** Claude Desktop Routines (name, description, instructions "run this skill", schedule). They only run while the computer is awake [video]. For event triggers, the carousel gives no mechanism [inferred]; the bridge would need to watch for them.

**Loop engineering [video].** For any skill worth improving: write each run's output and a short result note to `runs/<skill>/`. On the next run, the skill reads the last few notes first and adjusts. Add this after a skill is stable, not before.

### 4.2 Memory and state (level 2) [video, carousel]

**Vault layout.** Start from the Karpathy shape, then extend it. The video's real vault is a good guide.

```
the-vault/
  CLAUDE.md          # conventions, folder map, navigation pattern
  index.md           # what each top-level folder is for
  raw/               # unstructured capture          (index.md)
  wiki/              # compiled, structured articles (index.md)
  outputs/           # deliverables: decks, briefs   (index.md)
  inbox/             # triage queue
  daily-notes/
  projects/
  ops/
  system/
  runs/              # per-skill run logs; feeds loop engineering   (video: dashboard-runs)
  graph-imports/
```

**`CLAUDE.md` must contain** (from the video): the vault structure, the navigation pattern ("to find X, go to Y first"), and conventions for naming and where outputs go.

**Rules.**
- An `index.md` at every level, even when a folder holds one file. It is the map that saves tokens as the vault grows [video].
- Every report and conversation saves to the vault [carousel].
- Obsidian is optional. A plain, coherent file structure is "99% of the way there"; a database works too [video].

### 4.3 Brain [carousel]

Two interchangeable brains: Opus 5.5 inside Claude Code, or GPT-6 Astra inside Codex. A single setting switches the brain, and both dashboards read it. Keep skills and the vault model-agnostic so the switch does not break anything [inferred]. The video also says the pattern works with Codex or a local model.

### 4.4 Router: Jev [carousel]

Jev sorts each request into a tier. It does not write the answer.

| Tier | Handles | Example | Cost |
|---|---|---|---|
| 1 | Rules and saved data, no AI | "What are my priorities?" | Free, instant |
| 2 | Small fast model (Haiku / Luna) | "Summarize today's AI news" | Cheap, fast |
| 3 | Real work: opens a Claude Code or Codex terminal, or runs a skill in the background | "Draft the launch outline" [inferred; from slide 1's directives, not slide 4] | Full model |

The carousel does not say how Jev classifies requests. A reasonable build [inferred]: rule match first (known intents map to Tier 1), then a small-model classifier for the rest, with Tier 3 as the default when unsure. Log every routing decision so misroutes can be reviewed.

### 4.5 Voice [carousel, video]

- Speech to text: `SYSTRAN/faster-whisper`.
- Text to speech: `thewh1teagle/kokoro-onnx`.
- Interaction: tap to talk, pause to send, Escape cancels, plus a typed "Ask or continue..." field.
- Both run locally and are free. In the video the voice reads out "Inbox brief is done... 32 threads triaged".
- Privacy: audio never leaves the machine; the transcript goes to the selected provider.

### 4.6 The bridge [carousel; internals inferred]

The only source statement is "one brain for both apps": the web app and the Obsidian plugin both call the same layer, which calls Jev and reads and records to the vault. A workable design:

- A local service on localhost, started with the OS.
- Exposes a small API: submit request, list skills, run skill, job status, read usage, get/set brain.
- Runs Tier 3 skills as headless jobs: `claude -p "/skill-name"`, or the Codex equivalent [video, 27:00]. No terminal window appears.
- Writes each job's result to `outputs/` and a log line to `runs/`.
- Holds the current brain setting and the usage numbers the dashboards show.

**Billing risk [video].** Anthropic floated billing `claude -p` against API credits rather than the subscription, then walked it back. As of the video it still drew on the Max plan. Check before building a design that depends on high headless volume.

### 4.7 Interfaces (level 3) [video, carousel]

Both front ends are thin. They show state and call the bridge.

**Web app (Jarvis / V.A.U.L.T.).**
- Header: brain toggle (Claude Code / Codex), status line (core, vault, terminals), clock.
- Left: system vitals (weekly usage meter), directives (top 3 for today), channel metrics.
- Centre: a visual core that reflects the active brain and speaking state.
- Right: quick-access skill buttons ("browse all skills"), voice panel, schedule, AI wire.

**Obsidian plugin (Command Center).**
- Tabs: Overview, Audience, Research. Token-burn bar, metric tiles, latest upload, skill buttons, activity feed.
- Click a button → job is queued → result lands in the vault and opens in Obsidian.

**How to build both** [video]: screenshot a design you like, give it to Claude Code with your skill list, the vault path and the metrics you want, and ask for a web app. Then ask it to port that web app into an Obsidian plugin.

### 4.8 Distribution (level 4) [video]

- The web app ships through GitHub or a zip. Easy to hand over.
- The Obsidian plugin needs hands-on setup per person.
- The point is to raise the floor for non-technical teammates and clients, so they click a button instead of running Claude Code.

---

## 5. Request lifecycle

1. You speak, type, click a button, or a schedule or event fires.
2. A front end sends it to the bridge. Voice goes through faster-whisper first.
3. The bridge asks Jev for a tier.
4. Tier 1 answers from rules and saved vault data. Tier 2 asks the small model. Tier 3 starts a Claude Code or Codex job, or a headless skill.
5. The result is saved to the vault (`outputs/` and `runs/`).
6. The bridge returns a summary to the front end. Kokoro reads it aloud if voice is on.
7. The next run of the same skill reads the recent `runs/` notes first. This is the loop.

---

## 6. Build order

| Phase | Build | Done when | Source |
|---|---|---|---|
| 0 | Pick the vault folder. Write `CLAUDE.md` and root `index.md`. Open Claude Code inside it. | Claude can answer "where do I keep X?" from the map alone. | video |
| 1 | Workflow audit. Produce the repeated-task table. | A ranked list of 10+ candidate skills. | video |
| 2 | Build the top 3-5 skills. Each runs by hand with a saved output. | Each skill produces its output twice with the same shape. | video, carousel |
| 3 | Schedule the stable ones with Desktop Routines. | One skill runs unattended and writes to `outputs/`. | video |
| 4 | Add `runs/` logging, then loop engineering to one skill. | The second run measurably uses notes from the first. | video |
| 5 | Build the bridge with headless job running. Add the draft-only rule. | A button-less API call runs a skill and returns the saved path. | carousel (inferred design) |
| 6 | Add Jev: rules tier first, then the small-model tier, then default to Tier 3. | Routing log shows sensible tiers on 20 real requests. | carousel |
| 7 | Build the web app, then the Obsidian plugin, both against the bridge. | Same skill button works from both. | video, carousel |
| 8 | Add the Claude / Codex brain switch. | Flipping it changes the model used and both UIs follow. | carousel |
| 9 | Add local voice. | Tap, speak, hear the reply; audio never leaves the machine. | carousel |
| 10 | Package for others (GitHub for the web app, a setup guide for the plugin). | A teammate runs it without touching a terminal. | video |

Phases 0-4 need no code beyond skills and are about 90% of the value [video]. Stop there if you want the cheapest useful version.

---

## 7. Risks and open questions

| Risk | Why it matters | Mitigation |
|---|---|---|
| Permission bypass | The video's terminal shows "bypass permissions on". A router that can open Tier 3 terminals multiplies that risk. | Run bridge jobs with the narrowest permissions each skill needs; keep bypass off for anything that touches email, money or posting. |
| Headless sends | A background run could send or post without anyone watching. | Draft-only rule in section 2; sending only from an interactive session. |
| `claude -p` billing | Could shift from subscription to API credits. | Monitor; keep headless volume modest; use Tier 1 and 2 where possible. |
| Router misroutes | A wrong Tier 1 answer is silent. | Default to Tier 3 when unsure; log routing; review weekly. |
| Transcripts leave the machine | Voice is only half local. | State it plainly in setup docs; allow a local-model option. |
| Unverified names and numbers | Jev, GPT-6 Astra, Luna, repo star counts, and the models and dates come only from the sources. | Re-check each before depending on it. |
| Event triggers | The sources show triggers but not the mechanism. | Decide per trigger (webhook, poll, manual) when building phase 5. |
| Missing slide 9 | The carousel's last slide was not provided. | Send it if it adds anything, such as a call to action or setup steps. |

## 8. Open questions for you

1. Is Jev a product you can install, or something Chase built privately? The sources do not say.
2. Do you want the full system, or only phases 0-4?
3. Claude Code only, or both brains from the start?
