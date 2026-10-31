"""Nova's README video, GIF, banner and first-run walkthrough clips, made from HTML with HyperFrames.

    python docs/video/build.py narrate     # the narration, spoken by Nova's own local Kokoro voice (data/tts)
    python docs/video/build.py hero        # docs/media/nova-hero.mp4 (1080p, with narration) and nova-demo.gif
    python docs/video/build.py clips       # the seven walkthrough clips (docs/media/walkthrough/*.mp4, 720p)
    python docs/video/build.py banner      # docs/banner.png

Run it with Nova's own Python (it needs sherpa-onnx for the voice) from the repo root. It also needs Node, FFmpeg and
Chrome (HyperFrames drives Chrome). Everything on screen is a made-up mock, so no real desktop, name or file appears.
Edit the words below (LINES) and the scene functions, then run the commands again. Nothing here ships with Nova.
"""
import json
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "docs" / "video" / ".build"  # scratch: audio, the HyperFrames projects, raw renders (git-ignored)
MEDIA = ROOT / "docs" / "media"
VOICE = "af_nova"

# ---------- what the narrator says, scene by scene ----------
LINES = {
    "intro": "This is Nova. Talk to your computer, and it does the work. Free, open source, and listening on your own machine.",
    "ask": "Say Hey Nova and ask for anything. Open Spotify. Fix a bug in your project. Or ask what's wrong on your screen. "
           "Nova uses the Claude or ChatGPT plan you already have, and answers out loud.",
    "dictate": "Hold Control and just talk. Nova types clean text into any app. The ums disappear, corrections like no wait "
               "are applied, and Hindi comes out in English letters.",
    "rewrite": "Select any text and say, make this more formal. Nova rewrites it right where it sits.",
    "screen": "Nova sees what you see. Ask where a setting is, and it draws arrows and boxes on your real screen, one step at a time.",
    "meeting": "Record meetings without a bot. Nova hears your microphone and your computer's audio, transcribes on your machine, "
               "and writes the minutes.",
    "safe": "Nova asks before it runs risky commands. Every command goes through a local guard. Deleting, installing or pushing waits for "
            "your okay, and wiping a disk is always blocked.",
    "more": "Use it from your phone. Let it drive your browser. And if it types the wrong thing, just say, undo that.",
    "install": "Setup takes a few minutes. On Windows, download the zip, extract it, and double-click setup dot c m d. "
               "On a Mac, paste one line into Terminal. Nova installs everything it needs.",
    "end": "Nova. Free, open source, and yours. Say Hey Nova to start.",
    # the first-run walkthrough: each clip is followed by a "your turn" step in the app (core/app.html, WALK)
    "w_welcome": "Welcome to Nova. This two-minute tour shows each thing it does, and then lets you try it.",
    "w_talk": "Press your shortcut or say Hey Nova, then ask a question. Try, what time is it?",
    "w_dictate": "Click in any text box. Hold the dictation key until you hear the chime, say a sentence, ums and all, then let go.",
    "w_rewrite": "Select some text, hold the key, and say, make this more formal. Nova rewrites it in place.",
    "w_screen": "Ask about your screen. What's on my screen? Or, where's the settings button?",
    "w_safe": "Risky commands wait for your okay. The card shows the exact command. Allow it, or say no. No answer means no.",
    "w_finish": "You're ready. Nova lives in your tray. Say Hey Nova whenever you need it.",
}

CSS = """
:root{--ground:#f4f4f6;--ink:#1d1d1f;--mute:#6e6e73;--a:#7b6dff;--b:#5a8cff;--c:#3fd6e6;--d:#e0479a}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1920px;height:1080px;overflow:hidden;background:var(--ground);font-family:Inter,sans-serif;color:var(--ink)}
#root{position:relative;width:1920px;height:1080px;overflow:hidden;
 background:radial-gradient(1200px 700px at 20% 15%,#fff 0%,rgba(255,255,255,0) 70%),radial-gradient(900px 600px at 95% 95%,#ebe9f7 0%,rgba(235,233,247,0) 70%),var(--ground)}
.scene{position:absolute;left:0;top:0;width:1920px;height:1080px}
.inner{position:absolute;left:0;top:0;width:1920px;height:1080px}
.head{position:absolute;left:130px;top:330px;width:720px}
h2{font-size:112px;line-height:.98;font-weight:900;letter-spacing:-.045em}
.sub{font-size:36px;color:var(--mute);margin-top:30px;line-height:1.32;letter-spacing:-.012em;font-weight:400}
.w{display:inline-block}
.screen{position:absolute;left:900px;top:140px;width:900px;height:800px;border-radius:34px;overflow:hidden;
 background:linear-gradient(135deg,#d9d6f5 0%,#cfe0f7 45%,#f3d3e6 100%);box-shadow:0 50px 90px -30px rgba(40,30,90,.35),0 0 0 1px rgba(0,0,0,.06)}
.win{position:absolute;background:#fff;border-radius:18px;box-shadow:0 24px 50px -16px rgba(30,20,70,.35),0 0 0 1px rgba(0,0,0,.07);overflow:hidden}
.win.dark{background:#1c1d28;color:#e6e6f0}
.bar{height:46px;display:flex;align-items:center;gap:9px;padding:0 18px;font-size:19px;font-weight:700;color:#6a6a76;border-bottom:1px solid rgba(0,0,0,.06)}
.dark .bar{border-color:rgba(255,255,255,.07);color:#9a9ab0}
.dot{width:13px;height:13px;border-radius:50%;background:#e2e2e8}
.mono{font-family:'JetBrains Mono',monospace}
.code{padding:22px 26px;font-size:24px;line-height:1.7;color:#c9c9dc}
.code .k{color:#8fa4ff}.code .s{color:#8fe3b0}.code .p{color:#e0a3ff}
.hl{background:rgba(63,214,100,.18);border-radius:6px}
.ch{opacity:0}
.pill{position:absolute;left:50%;margin-left:-190px;bottom:36px;width:380px;height:78px;border-radius:40px;background:#14151f;color:#fff;
 display:flex;align-items:center;gap:16px;padding:0 28px;font-size:25px;font-weight:700;box-shadow:0 20px 40px -12px rgba(20,10,60,.55)}
.eq{display:flex;gap:5px;align-items:center;height:34px}
.eq i{display:block;width:7px;border-radius:4px;background:linear-gradient(#7b6dff,#e0479a);height:14px}
.card{position:absolute;left:50%;margin-left:-320px;width:640px;border-radius:24px;background:#14151f;color:#ecedf6;padding:28px 32px;
 box-shadow:0 30px 60px -18px rgba(20,10,60,.6);font-size:26px;line-height:1.4}
.card .who{font-size:19px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#8b8da6;margin-bottom:10px}
.card .q{font-weight:700;color:#fff}
.card .st{margin-top:14px;color:#9fa2c0;font-size:23px}
.card .ok{margin-top:16px;color:#aef0c4}
.btns{display:flex;gap:16px;margin-top:22px}
.btn{padding:14px 34px;border-radius:14px;font-weight:700;font-size:25px}
.allow{background:linear-gradient(90deg,#7b6dff,#5a8cff);color:#fff}.deny{background:#2a2c3b;color:#d5d7ea}
kbd{display:inline-block;background:#fff;border-radius:18px;padding:20px 30px;font:500 34px Inter,sans-serif;color:#3a3a40;
 box-shadow:0 10px 24px -8px rgba(0,0,0,.22),0 0 0 1px rgba(0,0,0,.05)}
.keys{display:flex;gap:18px}
.mark{display:block}
.line{height:14px;border-radius:7px;background:#e8e8ee;margin:18px 0}
.mail{padding:22px 30px;font-size:30px;line-height:1.55}
.mail .f{color:#85858f;font-size:24px;border-bottom:1px solid #eee;padding:10px 0}
.mail .f b{color:#1d1d1f;font-weight:700}
.sel{background:#cfd8ff;border-radius:6px}
.pop{position:absolute;background:#14151f;color:#fff;border-radius:16px;padding:16px 26px;font-size:25px;font-weight:700;box-shadow:0 20px 40px -12px rgba(20,10,60,.55)}
.pop s{color:#7d7f98;font-weight:400}
.menu{position:absolute;background:#fff;border-radius:12px;box-shadow:0 18px 40px -10px rgba(0,0,0,.3),0 0 0 1px rgba(0,0,0,.08);padding:8px;box-sizing:border-box;height:304px}
.menu div{font-size:25px;border-radius:8px}
.ring{position:absolute;border:5px solid #e0479a;border-radius:14px;box-shadow:0 0 0 8px rgba(224,71,154,.18)}
.chip{position:absolute;background:#e0479a;color:#fff;border-radius:999px;font-weight:900;font-size:22px;width:38px;height:38px;display:flex;align-items:center;justify-content:center}
.tag{position:absolute;display:flex;align-items:center;gap:10px;height:48px;background:#14151f;color:#fff;border-radius:24px;padding:0 20px 0 9px;font-size:22px;font-weight:700;white-space:nowrap}
.tag .n{display:flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;background:#e0479a;font-size:18px;font-weight:900}
.av{width:120px;height:120px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:900;color:#fff}
.tr{padding:18px 22px;font-size:22px;line-height:1.45;color:#3a3a46}
.tr b{color:#7b6dff}
.step{display:flex;gap:16px;font-size:30px;margin:18px 0;line-height:1.35;align-items:flex-start}
.step i{flex:none;font-style:normal;width:46px;height:46px;border-radius:50%;background:var(--ink);color:#fff;font-weight:900;font-size:24px;display:flex;align-items:center;justify-content:center}
.term{padding:22px 26px;font-size:26px;line-height:1.6;color:#d6d8ea}
.term .pr{color:#7b6dff}.term .cm{color:#f1a1a1}
.tile{position:absolute;background:#fff;border-radius:26px;box-shadow:0 24px 50px -16px rgba(30,20,70,.3),0 0 0 1px rgba(0,0,0,.06);padding:26px 28px}
.tile h3{font-size:30px;font-weight:900;letter-spacing:-.03em;margin-bottom:8px}
.tile p{font-size:23px;color:var(--mute);line-height:1.35}
.big{position:absolute;left:0;width:1920px;text-align:center}
.big .t{font-size:210px;font-weight:900;letter-spacing:-.055em;line-height:1}
.big .s{font-size:46px;color:var(--mute);margin-top:12px;letter-spacing:-.015em}
"""

BARS = [(8.3, 11, 26), (14.9, 11.5, 13), (21.5, 17.5, 13), (28.1, 23.5, 13), (34.7, 11, 26)]


def logo(size):
    rects = "".join(f'<rect x="{x}" y="{y}" width="5" height="{h}" rx="2.5" fill="url(#g{size})"/>' for x, y, h in BARS)
    return (f'<svg class="mark" width="{size}" height="{size}" viewBox="0 0 48 48"><defs><linearGradient id="t{size}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="#131528"/><stop offset="1" stop-color="#080a12"/></linearGradient>'
            f'<linearGradient id="g{size}" gradientUnits="userSpaceOnUse" x1="8" y1="24" x2="40" y2="24"><stop offset="0" stop-color="#7b6dff"/>'
            f'<stop offset=".31" stop-color="#5a8cff"/><stop offset=".62" stop-color="#3fd6e6"/><stop offset="1" stop-color="#e0479a"/></linearGradient></defs>'
            f'<rect width="48" height="48" rx="11" fill="url(#t{size})"/>{rects}</svg>')


def words(text):
    return "".join(" ".join(f'<span class="w">{w}</span>' for w in line.split()) + "<br>" for line in text.split("|")).removesuffix("<br>")


def chars(text):
    return "".join(f'<span class="ch">{"&nbsp;" if c == " " else c}</span>' for c in text)


def eq():
    return '<div class="eq">' + "".join(f'<i style="height:{h}px"></i>' for h in (12, 24, 16, 30, 14, 22, 10)) + "</div>"


# ---------- scenes: (html, js) from the scene's id, start S and length D; js times are absolute ----------
def head(i, title, sub, S):
    return (f'<div class="head" id="{i}h"><h2>{words(title)}</h2><p class="sub">{sub}</p></div>',
            [f'tl.from("#{i}h .w",{{y:70,opacity:0,duration:.75,ease:"power3.out",stagger:.09}},{S + .15:.2f});',
             f'tl.from("#{i}h .sub",{{y:30,opacity:0,duration:.7,ease:"power3.out"}},{S + .6:.2f});'])


def screen_in(i, S):
    return [f'tl.from("#{i}s",{{y:60,opacity:0,scale:.97,duration:.9,ease:"power3.out"}},{S + .1:.2f});']


def typing(sel, t, n, per=.045):
    return f'tl.to("{sel} .ch",{{opacity:1,duration:.01,stagger:{per}}},{t:.2f});'


def scene_wrap(i, S, D, body, js, track=0):
    out = f'tl.to("#{i} .inner",{{opacity:0,duration:.45,ease:"power2.in"}},{S + D - .5:.2f});'
    html = f'<section id="{i}" class="clip scene" data-start="{S:.2f}" data-duration="{D:.2f}" data-track-index="{track}"><div class="inner">{body}</div></section>'
    return html, js + [out]


def s_intro(i, S, D, welcome=False):
    keys = '<div class="keys" id="%sk"><kbd>Hey Nova</kbd><kbd>Hold Ctrl</kbd><kbd>Ctrl&nbsp;×3</kbd></div>' % i
    sub = "Your guided tour." if welcome else "Talk to your computer. It does the work."
    body = (f'<div style="position:absolute;left:0;width:1920px;top:210px;text-align:center"><div id="{i}l" style="display:inline-block">{logo(190)}</div></div>'
            f'<div class="big" style="top:430px" id="{i}b"><div class="t">{"Welcome" if welcome else "Nova"}</div><div class="s">{sub}</div></div>'
            f'<div style="position:absolute;left:0;width:1920px;top:780px;display:flex;justify-content:center">{keys}</div>')
    js = [f'tl.from("#{i}l",{{scale:.6,opacity:0,duration:.9,ease:"back.out(1.6)"}},{S + .1:.2f});',
          f'tl.from("#{i}b .t",{{y:50,opacity:0,duration:.8,ease:"power3.out"}},{S + .4:.2f});',
          f'tl.from("#{i}b .s",{{y:30,opacity:0,duration:.7,ease:"power3.out"}},{S + .9:.2f});',
          f'tl.from("#{i}k kbd",{{y:40,opacity:0,duration:.6,ease:"power3.out",stagger:.14}},{S + 1.4:.2f});']
    return scene_wrap(i, S, D, body, js)


def s_ask(i, S, D, ask="In my portfolio project, fix the navbar on mobile.", steps=("Reading Navbar.jsx", "Editing 2 files"),
          reply="Done. The menu now collapses on phones.", title="Ask it|anything.|Out loud.", sub="Open apps, fix code, answer questions about your screen."):
    h, hj = head(i, title, sub, S)
    code = ('<div class="code mono"><div><span class="k">const</span> Navbar = () =&gt; (</div><div>&nbsp;&nbsp;&lt;<span class="p">nav</span> className=<span class="s">"navbar"</span>&gt;</div>'
            '<div>&nbsp;&nbsp;&nbsp;&nbsp;&lt;<span class="p">Logo</span> /&gt;</div><div id="%shl">&nbsp;&nbsp;&nbsp;&nbsp;&lt;<span class="p">Links</span> items={pages} /&gt;</div>'
            '<div>&nbsp;&nbsp;&nbsp;&nbsp;&lt;<span class="p">ThemeToggle</span> /&gt;</div><div>&nbsp;&nbsp;&lt;/<span class="p">nav</span>&gt;</div><div>)</div></div>') % i
    body = (h + f'<div class="screen" id="{i}s"><div class="win dark" style="left:50px;top:70px;width:800px;height:470px"><div class="bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span>'
            f'&nbsp;&nbsp;portfolio — editor</div>{code}</div>'
            f'<div class="card" id="{i}c" style="bottom:140px"><div class="who">You</div><div class="q" id="{i}q">{chars(ask)}</div>'
            f'<div class="st" id="{i}a">{steps[0]}…</div><div class="st" id="{i}b" style="margin-top:6px">{steps[1]}…</div><div class="ok" id="{i}r">{reply}</div></div>'
            f'<div class="pill" id="{i}p">{eq()}<span id="{i}pt">Listening…</span></div></div>')
    js = hj + screen_in(i, S) + [
        f'tl.from("#{i}p",{{y:80,opacity:0,duration:.6,ease:"power3.out"}},{S + 1.0:.2f});',
        f'tl.fromTo("#{i}p .eq i",{{scaleY:.4}},{{scaleY:1.6,duration:.35,stagger:.06,repeat:5,yoyo:true,ease:"sine.inOut"}},{S + 1.2:.2f});',
        f'tl.from("#{i}c",{{y:60,opacity:0,duration:.6,ease:"power3.out"}},{S + 1.9:.2f});',
        f'tl.set("#{i}a,#{i}b,#{i}r",{{opacity:0}},0);',
        typing(f"#{i}q", S + 2.1, len(ask), .05),
        f'tl.to("#{i}a",{{opacity:1,duration:.4}},{S + D * .55:.2f});',
        f'tl.to("#{i}b",{{opacity:1,duration:.4}},{S + D * .66:.2f});',
        f'tl.to("#{i}r",{{opacity:1,duration:.5}},{S + D * .78:.2f});',
        f'tl.to("#{i}hl",{{backgroundColor:"rgba(63,214,100,.22)",duration:.5}},{S + D * .8:.2f});']
    return scene_wrap(i, S, D, body, js)


def s_dictate(i, S, D, held="um so meet at 6, no wait, 7 near the metro", clean="So meet at 7 near the metro.",
              title="Dictate into|any app.", sub="Hold the key, talk, let go. Clean text, wherever your cursor is."):
    h, hj = head(i, title, sub, S)
    body = (h + f'<div class="screen" id="{i}s"><div class="win" style="left:50px;top:80px;width:800px;height:560px"><div class="bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span>&nbsp;&nbsp;New message</div>'
            f'<div class="mail"><div class="f"><b>To</b>&nbsp;&nbsp;Sam</div><div class="f"><b>Subject</b>&nbsp;&nbsp;Tonight</div><div style="margin-top:22px">Hey Sam,<br><span id="{i}t">{chars(clean)}</span></div></div></div>'
            f'<div class="pop" id="{i}p" style="left:110px;top:690px;font-size:27px"><span style="color:#8b8da6">You say</span>&nbsp;&nbsp;<span id="{i}say">{held}</span></div></div>')
    js = hj + screen_in(i, S) + [
        f'tl.from("#{i}p",{{y:40,opacity:0,duration:.6,ease:"power3.out"}},{S + 1.4:.2f});',
        typing(f"#{i}t", S + D * .5, len(clean), .06)]
    return scene_wrap(i, S, D, body, js)


def s_rewrite(i, S, D, title="Rewrite what|you select.", sub="Select text, say what you want. It changes in place."):
    h, hj = head(i, title, sub, S)
    body = (h + f'<div class="screen" id="{i}s"><div class="win" style="left:50px;top:80px;width:800px;height:520px"><div class="bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span>&nbsp;&nbsp;Notes</div>'
            f'<div class="mail" style="padding-top:40px"><div style="position:relative;height:96px"><span id="{i}old" class="sel" style="position:absolute;left:0;top:0">hey can u send the report asap</span><span id="{i}new" style="position:absolute;left:0;top:0;opacity:0">Could you please send the report as soon as possible?</span></div>'
            f'<div class="line" style="margin-top:130px;width:70%"></div><div class="line" style="width:55%"></div></div></div>'
            f'<div class="pop" id="{i}p" style="left:210px;top:650px"><span style="color:#8b8da6">You say</span>&nbsp;&nbsp;“make this more formal”</div></div>')
    js = hj + screen_in(i, S) + [
        f'tl.from("#{i}p",{{y:40,opacity:0,duration:.6,ease:"power3.out"}},{S + D * .3:.2f});',
        f'tl.to("#{i}old",{{opacity:0,duration:.35}},{S + D * .6:.2f});',
        f'tl.to("#{i}new",{{opacity:1,duration:.6}},{S + D * .66:.2f});']
    return scene_wrap(i, S, D, body, js)


def s_screen(i, S, D, title="Sees your screen.|Shows you where.", sub="It draws on your real screen, one step at a time.",
             ask="Where do I export as PDF?"):
    """Every size below is fixed, so each ring is computed from the box it circles (screen coordinates, window at 50,70):
    menu bar row y 116-176 with items 84 px wide from x 74; the menu hangs under File at x 74 with 56 px rows from y 190."""
    h, hj = head(i, title, sub, S)
    items = "".join(f'<span style="display:inline-block;width:{w}px;text-align:center;{"" if n == 0 else "color:#767680;"}">{t}</span>'
                    for n, (t, w) in enumerate((("File", 84), ("Edit", 84), ("View", 84), ("Insert", 100))))
    rows = "".join(f'<div style="height:56px;line-height:56px;padding:0 18px;{"background:#efeaff;" if t == "Export as PDF" else ""}" id="{i}{"e" if t == "Export as PDF" else "x" + str(n)}">{t}</div>'
                   for n, t in enumerate(("New", "Open…", "Save", "Export as PDF", "Print…")))
    body = (h + f'<div class="screen" id="{i}s"><div class="win" style="left:50px;top:70px;width:800px;height:560px"><div class="bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span>&nbsp;&nbsp;Q3 report</div>'
            f'<div style="height:60px;line-height:60px;padding-left:24px;font-size:24px;font-weight:700;border-bottom:1px solid #eee;white-space:nowrap">{items}</div>'
            f'<div class="line" style="width:64%;margin-left:30px;margin-top:330px"></div><div class="line" style="width:48%;margin-left:30px"></div></div>'
            f'<div class="menu" id="{i}m" style="left:74px;top:182px;width:300px">{rows}</div>'
            f'<div class="ring" id="{i}r1" style="left:72px;top:122px;width:88px;height:48px"></div>'
            f'<div class="tag" id="{i}t1" style="left:452px;top:123px"><b class="n">1</b>Click File</div>'
            f'<div class="ring" id="{i}r2" style="left:78px;top:355px;width:292px;height:62px"></div>'
            f'<div class="tag" id="{i}t2" style="left:392px;top:362px"><b class="n">2</b>Export as PDF</div>'
            f'<div class="pop" id="{i}p" style="left:170px;top:690px"><span style="color:#8b8da6">You ask</span>&nbsp;&nbsp;{ask}</div></div>')
    js = hj + screen_in(i, S) + [
        f'tl.set("#{i}m,#{i}r1,#{i}t1,#{i}r2,#{i}t2",{{opacity:0}},0);',
        f'tl.from("#{i}p",{{y:40,opacity:0,duration:.6,ease:"power3.out"}},{S + 1.2:.2f});',
        f'tl.to("#{i}r1,#{i}t1",{{opacity:1,duration:.5,stagger:.12}},{S + D * .35:.2f});',
        f'tl.to("#{i}m",{{opacity:1,duration:.4}},{S + D * .55:.2f});',
        f'tl.to("#{i}r2,#{i}t2",{{opacity:1,duration:.5,stagger:.12}},{S + D * .68:.2f});']
    return scene_wrap(i, S, D, body, js)


def s_meeting(i, S, D):
    h, hj = head(i, "Meeting notes.|No bot.", "Recorded and transcribed on your computer.", S)
    avs = "".join(f'<div class="av" style="background:{c};position:absolute;left:{x}px;top:{y}px">{n}</div>' for n, c, x, y in
                  (("AM", "#5a8cff", 90, 100), ("RK", "#e0479a", 270, 100), ("JS", "#2fb37a", 90, 260), ("PL", "#e8a03a", 270, 260)))
    body = (h + f'<div class="screen" id="{i}s"><div class="win" style="left:40px;top:70px;width:820px;height:560px"><div class="bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span>&nbsp;&nbsp;Team sync</div>'
            f'{avs}<div style="position:absolute;left:470px;top:56px;width:340px;height:480px;border-left:1px solid #eee" class="tr"><div style="font-weight:900;color:#1d1d1f;font-size:23px">● Nova is taking notes</div>'
            f'<div style="color:#85858f;font-size:19px;margin-bottom:16px">On this computer · no bot joined</div><div id="{i}l1"><b>Riya</b> Can we ship the navbar fix today?</div><div id="{i}l2" style="margin-top:12px"><b>You</b> Yes, it\'s green. I\'ll merge after lunch.</div></div></div>'
            f'<div class="card" id="{i}c" style="bottom:70px;width:700px;margin-left:-350px"><div class="who">Minutes</div><div class="q">Decision: ship the navbar fix today.</div><div class="st">Action: merge after lunch (you)</div></div></div>')
    js = hj + screen_in(i, S) + [
        f'tl.set("#{i}l1,#{i}l2,#{i}c",{{opacity:0}},0);',
        f'tl.to("#{i}l1",{{opacity:1,duration:.5}},{S + D * .3:.2f});',
        f'tl.to("#{i}l2",{{opacity:1,duration:.5}},{S + D * .45:.2f});',
        f'tl.to("#{i}c",{{opacity:1,y:-10,duration:.6}},{S + D * .72:.2f});']
    return scene_wrap(i, S, D, body, js)


def s_safe(i, S, D, title="Asks before|risky commands.", sub="Every command goes through a local guard first.", short=False):
    h, hj = head(i, title, sub, S)
    body = (h + f'<div class="screen" id="{i}s"><div class="win dark" style="left:50px;top:70px;width:800px;height:380px"><div class="bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span>&nbsp;&nbsp;Terminal</div>'
            f'<div class="term mono"><div><span class="pr">my-site $</span> ls</div><div>dist&nbsp;&nbsp;src&nbsp;&nbsp;package.json</div><div id="{i}cmd"><span class="pr">my-site $</span> <span class="cm">rm -rf dist</span></div></div></div>'
            f'<div class="card" id="{i}c" style="bottom:80px;width:700px;margin-left:-350px"><div class="who">Nova needs your OK</div><div class="q mono" style="font-size:28px">rm -rf dist</div>'
            f'<div class="st">Deletes the dist folder in my-site (14 files)</div><div class="btns"><div class="btn allow" id="{i}al">Allow</div><div class="btn deny">Deny</div></div></div></div>')
    js = hj + screen_in(i, S) + [
        f'tl.from("#{i}c",{{y:70,opacity:0,scale:.96,duration:.7,ease:"back.out(1.4)"}},{S + D * .35:.2f});',
        f'tl.to("#{i}al",{{scale:1.07,duration:.35,yoyo:true,repeat:1}},{S + D * .75:.2f});']
    return scene_wrap(i, S, D, body, js)


def s_more(i, S, D):
    tiles = ("<h3>From your phone</h3><p>Scan a code. Type, dictate, or tap Allow from the couch.</p>",
             "<h3>Your browser</h3><p>It searches, reads and fills pages in the browser you already use.</p>",
             "<h3>Undo that</h3><p>Typed the wrong thing? Say it, and it's gone.</p>")
    h, hj = head(i, "And more.", "Phone. Browser. Undo.", S)
    pos = ((900, 150, 440), (900, 450, 440), (900, 750, 440))
    body = h + "".join(f'<div class="tile" id="{i}t{n}" style="left:{x}px;top:{y}px;width:900px;height:260px;padding-top:40px">{t}</div>' for n, ((x, y, _), t) in enumerate(zip(pos, tiles)))
    js = hj + [f'tl.from("#{i}t{n}",{{x:90,opacity:0,duration:.7,ease:"power3.out"}},{S + D * (.25 + .17 * n):.2f});' for n in range(3)]
    return scene_wrap(i, S, D, body, js)


def s_install(i, S, D):
    h, hj = head(i, "Installs in|minutes.", "No git, no terminal on Windows.", S)
    body = (h + f'<div class="screen" id="{i}s"><div class="tile" style="left:40px;top:60px;width:820px;height:330px"><h3>Windows</h3>'
            f'<div class="step"><i>1</i><span>Download <b>nova-main.zip</b> from the latest release</span></div><div class="step"><i>2</i><span>Extract it to a folder you will keep</span></div>'
            f'<div class="step"><i>3</i><span>Double-click <b>setup.cmd</b></span></div></div>'
            f'<div class="win dark" style="left:40px;top:430px;width:820px;height:320px" id="{i}m"><div class="bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span>&nbsp;&nbsp;Mac · Terminal</div>'
            f'<div class="term mono" style="font-size:20px;line-height:1.5"><span class="pr">$</span> cd ~ &amp;&amp; curl -fsSL github.com/AyushM1701/nova/releases/latest/download/nova-main.tar.gz | tar xz &amp;&amp; cd nova-main &amp;&amp; bash setup.sh</div></div></div>')
    js = hj + screen_in(i, S) + [f'tl.from("#{i}m",{{y:60,opacity:0,duration:.7,ease:"power3.out"}},{S + D * .55:.2f});']
    return scene_wrap(i, S, D, body, js)


def s_end(i, S, D, finish=False):
    keys = '<div class="keys" id="%sk"><kbd>Hey Nova</kbd><kbd>Hold Ctrl</kbd><kbd>Ctrl&nbsp;×3</kbd></div>' % i
    title, sub = ("You're ready.", "Nova lives in your tray. Say “Hey Nova” anytime.") if finish else ("Nova", "Free. Open source. Runs on your computer.")
    body = (f'<div style="position:absolute;left:0;width:1920px;top:210px;text-align:center"><div id="{i}l" style="display:inline-block">{logo(170)}</div></div>'
            f'<div class="big" style="top:420px" id="{i}b"><div class="t">{title}</div><div class="s">{sub}</div></div>'
            f'<div style="position:absolute;left:0;width:1920px;top:790px;display:flex;justify-content:center">{keys}</div>')
    js = [f'tl.from("#{i}l",{{scale:.6,opacity:0,duration:.9,ease:"back.out(1.6)"}},{S + .1:.2f});',
          f'tl.from("#{i}b .t",{{y:50,opacity:0,duration:.8,ease:"power3.out"}},{S + .4:.2f});',
          f'tl.from("#{i}b .s",{{y:30,opacity:0,duration:.7,ease:"power3.out"}},{S + .9:.2f});',
          f'tl.from("#{i}k kbd",{{y:40,opacity:0,duration:.6,ease:"power3.out",stagger:.14}},{S + 1.4:.2f});']
    return scene_wrap(i, S, D, body, js)


HERO = [("intro", s_intro, {}), ("ask", s_ask, {}), ("dictate", s_dictate, {}), ("rewrite", s_rewrite, {}), ("screen", s_screen, {}),
        ("meeting", s_meeting, {}), ("safe", s_safe, {}), ("more", s_more, {}), ("install", s_install, {}), ("end", s_end, {})]
CLIPS = [("00-welcome", "w_welcome", s_intro, {"welcome": True}),
         ("01-talk", "w_talk", s_ask, {"ask": "What time is it?", "steps": ("Checking the clock", "Writing the answer"), "reply": "It's 7:42 PM.",
                                       "title": "Talk to Nova.", "sub": "Say “Hey Nova”, or press your shortcut."}),
         ("02-dictate", "w_dictate", s_dictate, {"title": "Dictate into|any app.", "sub": "Hold the key until you hear the chime."}),
         ("03-rewrite", "w_rewrite", s_rewrite, {"title": "Rewrite what|you selected.", "sub": "Say how you want it changed."}),
         ("04-screen", "w_screen", s_screen, {"title": "Ask about|your screen.", "sub": "Nova looks at the window you're in."}),
         ("05-safety", "w_safe", s_safe, {"title": "Risky commands|wait for you.", "sub": "No answer in 30 seconds means no."}),
         ("06-finish", "w_finish", s_end, {"finish": True})]


# ---------- plumbing ----------
def run(cmd, **kw):
    print("$", " ".join(str(c) for c in cmd)[:200], flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def narrate():
    sys.path.insert(0, str(ROOT))
    from core import tts
    model, sid = tts.load("kokoro"), tts.speaker("kokoro", {"kokoro_voice": VOICE})
    (WORK / "audio").mkdir(parents=True, exist_ok=True)
    for name, text in LINES.items():
        out = WORK / "audio" / f"{name}.wav"
        g = model.generate(text, sid=sid, speed=1.0)
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(g.sample_rate)
            w.writeframes((__import__("numpy").clip(g.samples, -1, 1) * 32767).astype("<i2").tobytes())
        print(f"{name}: {len(g.samples) / g.sample_rate:.1f}s")


def seconds(name):
    with wave.open(str(WORK / "audio" / f"{name}.wav")) as w:
        return w.getnframes() / w.getframerate()


def project(name, scenes):
    """scenes: [(scene_id, narration_key, builder, kwargs, min_seconds)] -> a HyperFrames project; returns its folder."""
    folder = WORK / name
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "assets").mkdir(parents=True)
    html, js, audio, t, starts = [], [], [], 0.0, {}
    for n, (sid, key, build, kw, floor) in enumerate(scenes):
        d = max(floor, seconds(key) + 1.5)
        starts[sid] = t
        h, j = build(sid, t, d, **kw)
        html.append(h)
        js += j
        shutil.copy(WORK / "audio" / f"{key}.wav", folder / "assets" / f"{key}.wav")
        audio.append(f'<audio id="a{n}" class="clip" src="assets/{key}.wav" data-start="{t + .5:.2f}" data-duration="{seconds(key):.2f}" data-track-index="{10 + n}"></audio>')
        t += d
    page = (f'<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=1920, height=1080">'
            f'<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script><style>{CSS}</style></head><body>'
            f'<div id="root" data-composition-id="main" data-start="0" data-duration="{t:.2f}" data-width="1920" data-height="1080">{"".join(html)}{"".join(audio)}</div>'
            f'<script>window.__timelines=window.__timelines||{{}};const tl=gsap.timeline({{paused:true}});{"".join(js)}window.__timelines["main"]=tl;tl.seek(0);</script></body></html>')
    (folder / "index.html").write_text(page, encoding="utf-8")
    (folder / "hyperframes.json").write_text(json.dumps({"$schema": "https://hyperframes.heygen.com/schema/hyperframes.json", "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"}}), encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps({"id": name, "name": name}), encoding="utf-8")
    (folder / "starts.json").write_text(json.dumps(starts), encoding="utf-8")
    print(f"{name}: {t:.1f}s, {len(scenes)} scenes")
    return folder


def render(folder, out):
    run(["npx", "-y", "hyperframes", "check", "--json"], cwd=folder, shell=sys.platform == "win32")
    run(["npx", "-y", "hyperframes", "render", "-o", out, "-q", "looks", "--quiet"], cwd=folder, shell=sys.platform == "win32")


def encode(src, dst, width=None, crf=23, audio="96k"):
    vf = ["-vf", f"scale={width}:-2"] if width else []
    run(["ffmpeg", "-v", "error", "-y", "-i", src, *vf, "-c:v", "libx264", "-preset", "slow", "-crf", crf, "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-c:a", "aac", "-b:a", audio, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", dst])


def hero():
    folder = project("hero", [(sid, sid, fn, kw, 5.5) for sid, fn, kw in HERO])
    render(folder, WORK / "hero-raw.mp4")
    MEDIA.mkdir(parents=True, exist_ok=True)
    encode(WORK / "hero-raw.mp4", MEDIA / "nova-hero.mp4", crf=24)
    gif()


def gif():
    """About 18 s of the best moments, 12 fps, 900 px wide, one shared palette."""
    src, dst = MEDIA / "nova-hero.mp4", MEDIA / "nova-demo.gif"
    starts = json.loads((WORK / "hero" / "starts.json").read_text())
    parts = [("ask", 7.0, 5.0), ("dictate", 5.0, 3.5), ("screen", 3.0, 5.0), ("safe", 4.0, 4.6)]
    sel = "+".join(f"between(t,{starts[n] + a},{starts[n] + a + b})" for n, a, b in parts)
    vf = f"select='{sel}',setpts=N/FRAME_RATE/TB,fps=12,scale=900:-1:flags=lanczos"
    run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", f"{vf},split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4", "-loop", "0", dst])


def snap():
    """Build the hero project and take stills of every scene, to look at before the long render."""
    folder = project("hero", [(sid, sid, fn, kw, 5.5) for sid, fn, kw in HERO])
    starts = json.loads((folder / "starts.json").read_text())
    times = ",".join(f"{starts[s] + off:.1f}" for s in starts for off in (3.5,))
    run(["npx", "-y", "hyperframes", "snapshot", "--at", times], cwd=folder, shell=sys.platform == "win32")


def clips():
    out = MEDIA / "walkthrough"
    out.mkdir(parents=True, exist_ok=True)
    for name, key, fn, kw in CLIPS:
        if sys.argv[2:] and name not in sys.argv[2:]:  # python build.py clips 03-rewrite 04-screen: just those
            continue
        folder = project(f"clip-{name}", [(name.split("-")[1], key, fn, kw, 5.0)])
        render(folder, WORK / f"{name}-raw.mp4")
        encode(WORK / f"{name}-raw.mp4", out / f"{name}.mp4", width=1280, crf=31, audio="40k")


def banner():
    shutil.rmtree(WORK / "banner", ignore_errors=True)
    folder = WORK / "banner"
    folder.mkdir(parents=True)
    keys = "<kbd>Hey Nova</kbd><kbd>Hold Ctrl</kbd><kbd>Ctrl&nbsp;×3</kbd>"
    page = (f'<!doctype html><html><head><meta charset="UTF-8"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;900&display=swap">'
            f'<style>{CSS}html,body{{width:2000px;height:667px}}#root{{width:2000px;height:667px}}'
            f'kbd{{font-size:28px;padding:16px 26px}}</style></head><body><div id="root">'
            f'<div style="position:absolute;left:330px;top:150px">{logo(300)}</div>'
            f'<div style="position:absolute;left:760px;top:110px"><div style="font-size:250px;font-weight:900;letter-spacing:-.06em;line-height:1">Nova</div>'
            f'<div style="font-size:56px;color:#6e6e73;letter-spacing:-.025em;margin-top:6px">Talk to your computer. It does the work.</div>'
            f'<div class="keys" style="margin-top:44px">{keys}</div></div></div></body></html>')
    (folder / "banner.html").write_text(page, encoding="utf-8")
    shot = WORK / "banner.png"
    chrome = next(p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") if Path(p).exists())
    run([chrome, "--headless=new", "--hide-scrollbars", f"--screenshot={shot}", "--window-size=2000,667", "--force-device-scale-factor=1",
         "--virtual-time-budget=3000", (folder / "banner.html").as_uri()])
    shutil.copy(shot, ROOT / "docs" / "banner.png")


if __name__ == "__main__":
    {"narrate": narrate, "snap": snap, "hero": hero, "clips": clips, "banner": banner, "gif": gif}[sys.argv[1]]()
