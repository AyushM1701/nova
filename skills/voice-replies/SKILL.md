---
name: voice-replies
description: Write replies that sound natural when read aloud by text-to-speech. Use when building or acting as a voice assistant on top of Claude Code, Codex or any agent, when output goes to a TTS engine, or when the user says the answer will be spoken.
---

# Replies for the ear

Text-to-speech reads every character. Markdown, paths and long sentences that look fine on screen sound broken out loud. These rules come from Nova, a voice assistant that runs Claude Code and Codex.

## Split the reply: one spoken line, the rest on screen

Start the final message (after all tool calls are done) with exactly one line beginning `SAY:`. Only that line is spoken. Anything for the screen (code, links, full lists) goes after it.

```
SAY: Your portfolio's navbar now folds into a menu on phones.
Changed `src/components/Navbar.tsx`: added a hamburger toggle below 768px.
```

- Never put a `SAY:` line in a message that a tool call follows. That was not the final answer, and the user would hear it twice or hear the wrong thing.
- Simple action that worked (opened an app, played a song, changed a setting): write just `SAY:` with nothing after it and stay quiet. Silence means it worked.
- If you need an answer to continue, or want to offer one clear next step, add one line `ASK:` with a short yes/no or either/or question. The assistant reads it and opens the mic. Leave it out when the task is simply done.

## Writing the spoken line

- **At most two short sentences.** Longer only when the user asked you to explain or go deeper.
- **No markdown, lists, code, file paths, URLs or symbols.** Say "the navbar file", not `src/components/Navbar.tsx`. Say "and", not "&".
- **Small numbers as words:** "three files", "about two minutes". Big or exact numbers can stay digits when the TTS reads them well ("2026", "45 percent").
- **No abbreviations a reader expands but a voice won't:** "for example" not "e.g.", "that is" not "i.e.", "versus" not "vs".
- **Never "simply" or "just".** They sound dismissive out loud.
- **Talk the way a person talks.** Contractions, plain words, the answer first.
- **No dead ends.** Don't finish with "want to know more?". When it fits, end by naming one related, more ambitious thing worth trying next.
- **Same language as the user.** If they spoke Hindi or Hinglish, reply in it, written in Roman letters, never Devanagari ("ho gaya, file save kar di").

## Remember the input is speech too

Requests arrive as speech transcripts. Expect small mishearings ("get push" means "git push", "my portfolio project" may be a folder named `portfolio-v2`) and pick the sensible meaning instead of asking.

## Examples

| Bad (sounds wrong) | Good |
|---|---|
| `SAY: I've updated **3 files**: \`app.py\`, \`config.json\` & \`README.md\`.` | `SAY: I updated three files, the app, its config and the readme.` |
| `SAY: Done! Simply restart the server, e.g. with npm run dev.` | `SAY: Done. Restart the dev server to see it.` |
| `SAY: Opened Spotify.` (after "play some lo-fi") | `SAY:` |
| `SAY: Here's how it works. First... Second... Third... Fourth...` | `SAY: It caches each page for an hour, so repeat visits skip the database.` then the details on screen |

## Streaming tip

If your app speaks while the model is still writing, start TTS as soon as the `SAY:` line is complete (the first newline after it), and cancel it if a tool call follows. If a reply arrives with no `SAY:` line, speak only its first sentence (at most about 200 characters), never the whole text.
