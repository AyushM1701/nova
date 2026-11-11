# Launch posts

Ready to paste. Every claim here is in the README; add no user counts, testimonials or benchmarks. Post the poll first, so the link in the README and on Home has something to show.

Repo: https://github.com/AyushM1701/nova
Video: https://github.com/AyushM1701/nova#readme (the 90-second clip at the top)

## The poll (GitHub → Discussions → New discussion → Polls, then pin it)

**Title:** Which paid extra would you want on top of Nova?

**Body:**
Nova is free and MIT, and everything in it today stays free. I'm deciding what to build next, and whether any of it is worth paying for. Prices are guesses. Vote for the one you'd pay for, and comment if it's something else.

**Options:**
- Phone from anywhere, nothing to install (no Tailscale): $5/month
- Hand over from Claude to Codex when one hits its limit: $49 once
- Several projects at once by voice: $49 once
- Meeting notes synced across my devices: $5/month
- I wouldn't pay for any of these

## Show HN

**Title:** Show HN: Nova – open-source voice dictation and assistant that runs speech on your computer

**Text:**
Nova is a voice layer for Windows and macOS. Hold Left Ctrl and talk: clean text lands in whatever app has your cursor. Fillers go, "no wait" corrections are applied, and Hindi or Hinglish comes out in English letters. Dictation needs no AI subscription; speech recognition (faster-whisper) and the "Hey Nova" wake word run on your machine.

Say "Hey Nova" for the assistant. It hands the request to Claude Code or Codex, so it uses the plan you already have rather than a cloud of its own. Every command, file edit and file read the AI makes goes through a local guard first: deleting, installing, `git push` and sending data ask you; wiping disks and reading saved passwords are always blocked.

Also in there: meeting transcripts without a bot joining, a phone page for approving requests away from the desk, and a Hinglish Whisper fine-tune I trained for it (CC BY-SA 4.0, on Hugging Face).

MIT, no account, no server, no analytics. Python, with a pywebview window.

I'd like to hear where the guard is too strict or too loose, and how dictation does on your accent.

https://github.com/AyushM1701/nova

## r/ClaudeAI

**Title:** I built a free voice layer for Claude Code: "Hey Nova", then talk, with a guard that asks before risky commands

**Text:**
Nova sits in the tray and sends what you say to Claude Code (`claude -p`) or Codex, using the plan you already have. "In my portfolio project, fix the navbar on mobile" runs in that project, shows each step, and answers out loud.

What I cared about most is safety. Every command, edit and read passes a local guard first. Deleting or moving files, installing, `git push` and sending data show the exact command on a card and wait for Allow. Wiping disks, turning off the firewall and reading saved passwords or SSH keys are blocked in every mode. There are Auto, Manual, Accept edits, Plan and Bypass modes.

Other things it does with Claude Code: a Home page with your real usage read from Claude Code's own session files, your installed Claude skills as buttons, background jobs ("in the background, …"), and Allow / Deny from your phone.

It also does dictation that needs no AI at all (hold Left Ctrl, talk), including Hindi and Hinglish.

Free, MIT, no account. Windows and macOS.

https://github.com/AyushM1701/nova

## r/LocalLLaMA

**Title:** Open-source dictation that stays on your machine: faster-whisper, a local wake word, and Ollama for cleanup

**Text:**
Nova is a voice app for Windows and macOS where the speech side is fully local. Recognition is faster-whisper (GPU when you have one; Parakeet or whisper.cpp if you prefer), the "Hey Nova" wake word is on-device, and spoken replies use Piper, Kitten or Kokoro through sherpa-onnx.

Dictation works with no cloud and no subscription: point it at Ollama, llama.cpp or LM Studio and long dictations are tidied by a model on your computer (fillers out, self-corrections applied). The default suggestion is a small model such as `qwen2.5:3b`.

I also fine-tuned Whisper large-v3-turbo on English, Hindi and Hinglish together so code-switched speech comes out in Roman letters. The model is on Hugging Face under CC BY-SA 4.0 and the training scripts are in the repo (`helpers/hinglish_train`).

The assistant half does use a cloud model (Claude Code or Codex, your own plan), behind a local guard. Dictation, meetings and the wake word don't.

MIT, no account, no telemetry.

https://github.com/AyushM1701/nova
Model: https://huggingface.co/AyushM1701/nova-whisper-hinglish

## Product Hunt

**Name:** Nova

**Tagline:** Talk to your computer. It does the work.

**Description:**
Say "Hey Nova" or hold Ctrl and talk. Nova types clean text into any app, answers questions about your screen, works in your code projects through Claude Code or Codex, and records meetings without a bot. Speech stays on your computer. Free and open source, no account.

**First comment:**
Hi, I'm Ayush. I built Nova because I wanted to talk instead of type, in English and Hinglish, without sending my voice to a server.

Dictation needs no AI subscription. For the assistant, Nova uses the Claude or ChatGPT plan you already have, and asks before anything risky: you see the exact command and press Allow.

Setup is a double-click on Windows and one pasted line on a Mac. I'd love to know what you try first and where it gets in your way.

## Indian developer communities (r/developersIndia, X, LinkedIn, Discord and WhatsApp groups)

**Title:** Hinglish mein bolo, English letters mein type ho jaata hai: a free, open-source dictation app

**Text:**
I made Nova, a free voice app for Windows and Mac. Hold Left Ctrl and speak the way we actually talk, "kal meeting 6 baje, no wait, 7 baje rakhte hain", and it types clean text in Roman letters into whatever app is open. No AI subscription needed for dictation.

Speech recognition runs on your own computer. I trained a Whisper model on English, Hindi and Hinglish together for this, and it's open on Hugging Face.

If you use Claude Code or Codex, "Hey Nova" also runs requests through them and asks before anything risky.

MIT licensed, no account, no server. I'd really like feedback on how well it hears your Hinglish.

https://github.com/AyushM1701/nova
