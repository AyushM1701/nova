"""The Nova window's page as it renders on Windows (Chromium, the engine of WebView2) and on a Mac (WebKit, the engine
of WKWebView), at the sizes each OS really uses: every page and Settings tab (scrolled through, since the window itself
never scrolls), the ⌘K / Ctrl+K palette, the first-run tour, and the states Home can be in (thinking, an approval,
Nova not running, a usage limit, Claude signed out, a long status). It fails on any error the page logs, on a page that
scrolls sideways, on text cut off at the side of its box and on a dock whose items overlap; it saves a picture of each.

    python -m pip install -r requirements-dev.txt && python -m playwright install webkit chromium
    python helpers/webkit_ui.py ui-deep-dive                 # both OSes, fixed sample data
    python helpers/webkit_ui.py out --profiles macos --live    # the Mac only, with this computer's own data

Not the OS itself: no real title bar or traffic lights, no ClearType, no SF Pro on Windows, no permissions. The macOS UI
workflow (.github/workflows/macos-ui-test.yml) runs the Mac profile on a real Mac beside pictures of the real window.

With --live the page reads the real window code (core/app.py), so the numbers are this computer's; calls that would
change something (save, install, sign in, open, record...) do nothing here. Without it every read is fixed sample data,
so two runs can be compared picture by picture."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402  (requirements-dev.txt)

from core import app, phone  # noqa: E402
from core.config import defaults  # noqa: E402

READS = {"hello", "history", "stats", "deck", "skills_list", "claude_skills", "meetings_list", "upcoming", "voices",
         "audio_devices", "browsers", "model_status", "notes_info", "safety_status", "fallback_status", "calendar_status",
         "stt_key_status", "clone_status", "obsidian_info", "schedule_usage", "voice_enrolled", "check_hotkey", "settings",
         "phone_info"}
NOW = time.time()
DAYS = [{"date": time.strftime("%Y-%m-%d", time.localtime(NOW - d * 86400)), "tokens": t, "messages": m}
        for d, t, m in ((6, 410_000, 40), (5, 1_200_000, 120), (4, 980_000, 88), (3, 2_400_000, 210), (2, 1_700_000, 150),
                        (1, 3_100_000, 260), (0, 1_450_000, 131))]
USAGE = {"block": {"tokens": 820_000, "resets": NOW + 3 * 3600 + 1200}, "peak": 3_600_000, "percent": 23,
         "today": DAYS[-1], "days": DAYS, "week": sum(d["tokens"] for d in DAYS), "scanned_days": 35, "limit": None}
CLAUDE = {"usage": USAGE, "auth": {"logged_in": True, "plan": "pro"}, "loading": False, "at": NOW, "error": ""}
SKILLS = [{"name": "morning-intel", "title": "Morning intel", "status": "done"},
          {"name": "ship-check", "title": "Ship check", "status": ""}]
HISTORY = [{"event": "reply", "t": NOW - 600, "heard": "What's on my screen?", "reply": "A pull request with two failing checks."},
           {"event": "dictation", "t": NOW - 3600, "text": "Meet at 7 near the metro."},
           {"event": "reply", "t": NOW - 7200, "heard": "In my portfolio project, fix the navbar on mobile",
            "reply": "Done. The menu now folds into a button under 640px and the links wrap instead of overflowing."}]
FIXED = {  # every read, when the run is on sample data (and the ones that would start a program or ask the OS, always)
    "engines": {"claude": {"installed": True, "signed_in": True}, "codex": {"installed": False, "signed_in": False}, "npm": True},
    "mac_permissions": {p: True for p in ("microphone", "input", "accessibility", "screen")},  # core/system.py: {name: allowed}
    "memory": ["I use pnpm", "My portfolio is in D:\\projects\\portfolio"],
    "check_update": {"latest": None, "current": None},
}
SAMPLE = {"deck": {"usage": None, "claude": CLAUDE, "running": [], "skills": SKILLS}, "history": HISTORY,
          "meetings_list": {"meetings": [], "folders": [], "actions": []}, "upcoming": [], "claude_skills": [], "skills_list": []}
STATE = {"event": "state", "phase": "idle", "brain": "Claude Code", "jobs": 0, "mode": "assistant"}
PROFILES = {
    # Windows 11: WebView2 is Chromium; 125% display scaling is the commonest laptop setting and rounds borders badly
    "windows": {"engine": "chromium", "platform": "Win32", "scale": {"1920x1080": 1, "1536x864": 1.25, "1080x740": 1.25, "820x580": 1},
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"},
    "macos": {"engine": "webkit", "platform": "MacIntel", "scale": {"1440x900": 2, "1280x800": 2, "1080x740": 2, "820x580": 2},
            "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"},
}
BRIDGE = """
Object.defineProperty(navigator, "platform", { get: () => %s });
window.pywebview = { api: new Proxy({}, { get: (_, name) => (...args) => window.novaCall(name, args) }) };
"""
CHECKS_JS = """() => {
  const out = [];
  if (document.documentElement.scrollWidth > innerWidth + 1) out.push("page " + document.documentElement.scrollWidth + "px wide");
  const name = el => el.id ? "#" + el.id : el.className && typeof el.className === "string" ? "." + el.className.split(" ")[0] : el.tagName;
  for (const el of document.querySelectorAll("body *")) {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (!r.width || cs.display === "none" || cs.visibility === "hidden" || el.closest("[hidden]") || el.closest("svg")) continue;
    if (["auto", "scroll"].includes(cs.overflowX) || cs.textOverflow === "ellipsis") continue;
    // a label folded away on purpose (a tab showing only its icon) or text for screen readers only isn't cut off
    if (el.clientWidth < 8 || el.classList.contains("sr-only") || cs.opacity === "0") continue;
    if (cs.overflowX === "hidden" && el.scrollWidth > el.clientWidth + 2 && el.children.length === 0 && el.textContent.trim())
      out.push("cut off " + name(el) + ": " + el.textContent.trim().slice(0, 40));
    if (r.right > innerWidth + 1 && cs.position !== "fixed") out.push("past the right edge: " + name(el));
  }
  // the dock: its parts must not overlap each other (the brand, the live pill, the tabs, Mode and Pause)
  const dock = document.querySelector(".dock");
  if (dock) {
    const parts = [...dock.children].filter(c => c.getBoundingClientRect().width && getComputedStyle(c).display !== "none");
    for (let i = 1; i < parts.length; i++) {
      const a = parts[i - 1].getBoundingClientRect(), b = parts[i].getBoundingClientRect();
      if (a.right > b.left + 1 && a.top < b.bottom && b.top < a.bottom) out.push("dock overlap: " + name(parts[i - 1]) + " / " + name(parts[i]));
    }
  }
  // Windows: the window draws –, □, × (3 × 46px, core/winframe.py) over the dock's right end, which must stay free
  if (dock && document.documentElement.classList.contains("framed")) {
    const right = Math.max(...[...dock.querySelectorAll("button, a, .live, .seg")].filter(e => e.getClientRects().length).map(e => e.getBoundingClientRect().right));
    if (right > innerWidth - 138) out.push("dock runs under the window buttons: ends at " + Math.round(right) + " of " + innerWidth);
  }
  // a missing value printed as text
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = walker.nextNode());)
    if (/^(null|undefined|NaN)$/.test(n.data.trim()) && n.parentElement && n.parentElement.getClientRects().length && !n.parentElement.closest("[hidden], pre, code"))
      out.push("prints " + n.data.trim() + " in " + name(n.parentElement));
  // text under the 11px floor (DESIGN.md), outside the walkthrough's scaled illustration
  for (const el of document.querySelectorAll("#home *")) {
    if (el.closest(".scene") || !el.childNodes.length || ![...el.childNodes].some(n => n.nodeType === 3 && n.data.trim())) continue;
    const cs = getComputedStyle(el); if (cs.display === "none" || el.closest("[hidden]") || el.classList.contains("sr-only")) continue;
    if (parseFloat(cs.fontSize) < 10.95) out.push("under 11px on Home: " + name(el) + " " + cs.fontSize);
  }
  return [...new Set(out)].slice(0, 25);
}"""
# the window never scrolls; its panes do: every one that can is scrolled to its end for a second picture
SCROLLERS_JS = """() => [...document.querySelectorAll("*")].filter(el => {
  const cs = getComputedStyle(el); return ["auto", "scroll"].includes(cs.overflowY) && el.scrollHeight > el.clientHeight + 40 && el.getClientRects().length && !el.closest("[hidden]");
}).map((el, i) => { el.dataset.shotScroll = i; return i; })"""


def bridge(api, platform, live):
    def call(source, name, args):
        if name in FIXED:
            return FIXED[name]
        if not live and name in SAMPLE:
            return SAMPLE[name]
        if name not in READS:
            return None
        if not live and name == "settings":  # sample data shows no one's own settings, dictionary or blocked sites
            return defaults()
        if not live and name == "phone_info":  # nor a phone pairing link
            return []
        result = getattr(api, name)(*args)
        if name == "hello":
            result.update(platform=platform, connected=True, page="home", error="")
            base = result["config"] if live else defaults()
            result["config"] = {**base, "onboarded": True, "walked": True, "setup_hidden": not live}
        return json.loads(json.dumps(result, default=str))
    return call


def states(page, deck):
    """Home in each state worth seeing: (name, what to do first)."""
    asking = {"event": "asking", "id": 7, "who": "Claude Code", "reason": "Deletes files", "summary": "Remove-Item -Recurse dist",
              "plain": "Delete the dist folder in your portfolio project", "timeout": 30, "until": NOW + 30, "source": "assistant"}
    limit = {**CLAUDE, "usage": {**USAGE, "limit": {"kind": "session", "resets": NOW + 2 * 3600 + 600}}}
    weekly = {**CLAUDE, "usage": {**USAGE, "limit": {"kind": "weekly", "resets": NOW + 2 * 86400 + 5 * 3600}}}
    out = {**CLAUDE, "auth": {"logged_in": False, "plan": ""}}
    job = [{"label": "Summarise this week's pull requests across all four repositories", "started": NOW - 95, "skill": ""}]
    long = "Done. " + "x" * 160 + "\n\n```\nnpm run build && npx playwright test --project=webkit --reporter=line --workers=4 --retries=2\n```"

    def set_deck(c=CLAUDE, running=()):
        deck["claude"], deck["running"] = c, list(running)
        page.evaluate("loadDeck()")
    return [
        ("thinking", lambda: page.evaluate("nova.recv({event:'bar', state:'thinking'}); nova.recv({event:'step', text:'Reading src/components/Navbar.tsx'})")),
        ("approval", lambda: page.evaluate(f"nova.recv({json.dumps(asking)})")),
        ("limit-session", lambda: set_deck(limit)),
        ("limit-weekly", lambda: set_deck(weekly)),
        ("signed-out", lambda: set_deck(out)),
        ("fallback-brain", lambda: page.evaluate("S.cfg.brain = {...(S.cfg.brain||{}), engine:'claude'}; nova.recv({...S.state, event:'state', phase:'idle', brain:'Codex'})")),
        ("job-running", lambda: set_deck(running=job)),
        ("deck-loading", lambda: set_deck({**CLAUDE, "usage": None, "loading": True})),
        ("deck-failed", lambda: set_deck({**CLAUDE, "error": "OSError"})),
        ("config-error", lambda: page.evaluate("$('#cfgError').hidden = false; $('#cfgError span').textContent = 'config.json has an error on line 12, so Nova is using its defaults.'; syncBanners()")),
        ("long-reply", lambda: page.evaluate(f"homeReply({json.dumps(long)})")),
        ("not-running", lambda: page.evaluate("nova.recv({event:'gone'})")),
    ]


def set_loading(page, deck):
    deck["claude"] = {**CLAUDE, "usage": None, "loading": True}
    page.evaluate("loadDeck(); go('skills'); go('home')")


def reset(page, deck):
    """Back to an idle Home between states, so one state's card doesn't show in the next picture."""
    deck.update(claude=CLAUDE, running=[])
    page.evaluate(f"stripSet(''); $('#cfgError').hidden = true; syncBanners(); S.cfg.brain = {{...(S.cfg.brain||{{}}), engine:'claude'}}; nova.recv({json.dumps(STATE)}); nova.recv({{event:'bar', state:'idle'}}); loadDeck()")


def run(out, profiles, sizes, live):
    problems, shots = [], []
    html = phone.page(app.HTML)
    with sync_playwright() as pw:
        for prof in profiles:
            p = PROFILES[prof]
            launcher = getattr(pw, p["engine"])
            # headless Chromium hides scrollbars by default; the real window (WebView2) shows them
            browser = launcher.launch(ignore_default_args=["--hide-scrollbars"]) if p["engine"] == "chromium" else launcher.launch()
            for size, scale in p["scale"].items():
                if sizes and size not in sizes:
                    continue
                w, h = map(int, size.split("x"))
                folder = out / prof
                folder.mkdir(parents=True, exist_ok=True)
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale, user_agent=p["ua"], locale="en-US")
                ctx.add_init_script(BRIDGE % json.dumps(p["platform"]))
                deck = json.loads(json.dumps(SAMPLE["deck"]))
                sample = {**SAMPLE, "deck": deck}
                call = bridge(app.Api(), "mac" if prof == "macos" else "win", live)
                ctx.expose_binding("novaCall", lambda s, n, a, call=call, sample=sample: sample[n] if not live and n in sample else call(s, n, a))
                page = ctx.new_page()
                errors = []
                page.on("console", lambda m, errors=errors: m.type == "error" and errors.append(m.text))
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                page.set_content(html)
                page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
                page.wait_for_function("typeof S !== 'undefined' && !!S.platform", timeout=15000)
                page.evaluate(f"nova.recv({json.dumps(STATE)})")
                page.wait_for_timeout(1500)
                tag = f"{size}@{scale}x"

                def shot(name, tag=tag, page=page, folder=folder, scroll=False):
                    page.wait_for_timeout(600)
                    path = folder / f"{tag}-{name}.png"
                    page.screenshot(path=str(path))
                    shots.append(f"{prof}/{path.name}")
                    for problem in page.evaluate(CHECKS_JS):
                        problems.append(f"{prof} {tag} {name}: {problem}")
                    if scroll and page.evaluate(SCROLLERS_JS):  # and the bottom of what scrolls
                        page.evaluate("document.querySelectorAll('[data-shot-scroll]').forEach(el => el.scrollTop = el.scrollHeight)")
                        page.wait_for_timeout(300)
                        page.screenshot(path=str(folder / f"{tag}-{name}-end.png"))
                        shots.append(f"{prof}/{tag}-{name}-end.png")
                        page.evaluate("document.querySelectorAll('[data-shot-scroll]').forEach(el => { el.scrollTop = 0; delete el.dataset.shotScroll; })")

                if prof == "windows":  # the app's own 10px scrollbars: if headless hid them, the scrollbar checks see nothing
                    gutter = page.evaluate("(() => { const d = document.createElement('div'); d.style.cssText = 'width:100px;height:50px;overflow:scroll;position:absolute;top:-999px'; document.body.append(d); const g = d.offsetWidth - d.clientWidth; d.remove(); return g; })()")
                    if gutter != 10:
                        problems.append(f"{prof} {tag}: scrollbar is {gutter}px, not the window's 10px")
                linked = page.evaluate("[...new Set([...document.querySelectorAll('[data-go]')].map(e => e.dataset.go))]")
                for target in dict.fromkeys(["home", "chat", "skills", *linked]):
                    pg, _, tab = target.partition(":")
                    page.evaluate(f"go({json.dumps(pg)}, {json.dumps(tab or None)})")
                    shot(target.replace(":", "-"), scroll=True)
                page.evaluate("go('home')")
                for name, do in states(page, deck):
                    reset(page, deck)
                    do()
                    shot(f"home-{name}")
                reset(page, deck)
                # a chat thread with a long unbroken string and a code block, and History with nothing in it
                page.evaluate("go('chat'); userMsg('Fix the build'); novaMsg('Run this:\\n\\n```\\n' + 'npx '.repeat(40) + '\\n```\\n\\n' + 'y'.repeat(200))")
                shot("chat-long")
                page.evaluate("S.history = []; go('history')")
                shot("history-empty")
                page.evaluate("go('home')")
                # reduced motion (PRODUCT.md): with the OS asking for it, nothing should loop on screen
                page.emulate_media(reduced_motion="reduce")
                for name, do in (("thinking", lambda: page.evaluate("homeWorking('Working'); nova.recv({event:'bar', state:'thinking'})")),
                                 ("loading", lambda: set_loading(page, deck))):
                    reset(page, deck)
                    do()
                    page.wait_for_timeout(500)
                    loops = page.evaluate("""document.getAnimations().filter(a => a.playState === 'running' && a.effect && a.effect.getTiming().iterations === Infinity
                        && a.effect.target && a.effect.target.getClientRects().length
                        // a fade in place is allowed (core/app.html: the busy dots "breathe" instead of moving)
                        && a.effect.getKeyframes().some(k => Object.keys(k).some(p => !["opacity", "offset", "easing", "composite", "computedOffset"].includes(p)))).map(a => (a.animationName || a.constructor.name) + ' on ' + (a.effect.target.id || a.effect.target.className))""")
                    for loop in dict.fromkeys(loops):
                        problems.append(f"{prof} {tag}: reduced motion, {name}: still loops: {loop}")
                page.emulate_media(reduced_motion="no-preference")
                reset(page, deck)
                page.keyboard.press("Meta+k" if prof == "macos" else "Control+k")
                if page.is_hidden("#pal"):
                    problems.append(f"{prof} {tag}: the shortcut didn't open the command palette")
                shot("palette")
                page.keyboard.press("Escape")
                page.evaluate("openOnboarding()")
                shot("onboarding")
                problems += [f"{prof} {tag}: console error: {e}" for e in dict.fromkeys(errors)]
                ctx.close()
            browser.close()
    return problems, shots


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", type=Path, nargs="?", default=ROOT / "ui-deep-dive")
    ap.add_argument("--profiles", default="windows,macos")
    ap.add_argument("--sizes", default="", help="only these, e.g. 1440x900,820x580")
    ap.add_argument("--live", action="store_true", help="this computer's own data instead of the fixed sample")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ⌘ in a Windows console
    args.out.mkdir(parents=True, exist_ok=True)
    problems, shots = run(args.out, args.profiles.split(","), set(filter(None, args.sizes.split(","))), args.live)
    report = "\n".join(problems) or "No problems found."
    (args.out / "report.txt").write_text(f"{len(shots)} pictures\n{report}\n", encoding="utf-8")
    print(f"{len(shots)} pictures in {args.out}\n{report}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
