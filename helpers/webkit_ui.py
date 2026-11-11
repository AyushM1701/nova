"""The Nova window's page in WebKit (the engine of the Mac's WKWebView and Safari), told it runs on a Mac, on a Retina
screen, at two MacBook sizes, light and dark: every page and every Settings tab is opened, the command palette with ⌘K,
the first-run tour and the walkthrough. It fails on any error the page logs, on a page that scrolls sideways, and on
text cut off at the side of its box; it saves a full picture of each state.

    python -m pip install -r requirements-dev.txt && python -m playwright install webkit
    python helpers/webkit_ui.py macos-ui-snapshots

It runs anywhere (Windows too), so it is the quick look. It is not the Mac itself: no menu bar, no real WKWebView, no
permissions. .github/workflows/macos-ui-test.yml runs it on a real Mac as well, beside pictures of the real window.

The page talks to the real window code (core/app.py) for what it reads, so the numbers are this computer's; calls that
would change something (save, install, sign in, open, record...) do nothing here."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402  (requirements-dev.txt)

from core import app, phone  # noqa: E402

# what the page may really call: they only read. Anything else answers None, as a call that did nothing.
READS = {"hello", "history", "stats", "deck", "skills_list", "claude_skills", "meetings_list", "upcoming", "voices",
         "audio_devices", "browsers", "model_status", "notes_info", "safety_status", "fallback_status", "calendar_status",
         "stt_key_status", "clone_status", "obsidian_info", "schedule_usage", "voice_enrolled", "check_hotkey", "settings",
         "phone_info", "local_llm_test"}
FAKE = {  # reads that would start a program or ask macOS: a plausible answer instead
    "engines": {"claude": {"installed": True, "signed_in": True}, "codex": {"installed": False, "signed_in": False}, "npm": True},
    "mac_permissions": [{"id": p, "granted": True} for p in ("microphone", "input", "accessibility", "screen")],
    "memory": [],
    "check_update": {"latest": None, "current": None},
}
STATE = {"event": "state", "phase": "idle", "brain": "Claude Code", "jobs": 0, "mode": "assistant"}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15")
SIZES = {"1440x900": (1440, 900), "1280x800": (1280, 800)}
BRIDGE = """
Object.defineProperty(navigator, "platform", { get: () => "MacIntel" });
window.pywebview = { api: new Proxy({}, { get: (_, name) => (...args) => window.novaCall(name, args) }) };
"""
# what overflows: the page scrolling sideways, and boxes whose text is cut off at the side (not ones meant to scroll)
OVERFLOW_JS = """() => {
  const out = [];
  if (document.documentElement.scrollWidth > innerWidth + 1) out.push("page " + document.documentElement.scrollWidth + "px wide");
  for (const el of document.querySelectorAll("body *")) {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (!r.width || cs.display === "none" || cs.visibility === "hidden" || el.closest("[hidden]")) continue;
    if (["auto", "scroll"].includes(cs.overflowX) || cs.textOverflow === "ellipsis" || el.tagName === "svg" || el.closest("svg")) continue;
    // a label folded away on purpose (a tab showing only its icon) or text for screen readers only isn't cut off
    if (el.clientWidth < 8 || el.classList.contains("sr-only") || cs.opacity === "0") continue;
    if (cs.overflowX === "hidden" && el.scrollWidth > el.clientWidth + 2 && el.children.length === 0 && el.textContent.trim())
      out.push((el.id ? "#" + el.id : el.className ? "." + String(el.className).split(" ")[0] : el.tagName) + ": " + el.textContent.trim().slice(0, 40));
    if (r.right > innerWidth + 1 && cs.position !== "fixed") out.push("past the right edge: " + (el.id || el.className || el.tagName));
  }
  return [...new Set(out)].slice(0, 20);
}"""


def bridge(api):
    def call(source, name, args):
        if name in FAKE:
            return FAKE[name]
        if name not in READS:
            return None
        result = getattr(api, name)(*args)
        if name == "hello":
            result.update(platform="mac", connected=True, page="home")
            result["config"] = {**result["config"], "onboarded": True, "walked": True}
        return json.loads(json.dumps(result, default=str))
    return call


def run(out, sizes, schemes):
    out.mkdir(parents=True, exist_ok=True)
    html = phone.page(app.HTML)
    problems, shots = [], []
    with sync_playwright() as pw:
        browser = pw.webkit.launch()
        for size in sizes:
            for scheme in schemes:
                w, h = SIZES[size]
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2, user_agent=UA,
                                          color_scheme=scheme, locale="en-US")
                ctx.add_init_script(BRIDGE)
                ctx.expose_binding("novaCall", bridge(app.Api()))
                page = ctx.new_page()
                errors = []
                page.on("console", lambda m, errors=errors: m.type == "error" and errors.append(m.text))
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                page.set_content(html)
                page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
                page.wait_for_function("document.documentElement.classList.contains('mac')", timeout=15000)
                page.evaluate(f"nova.recv({json.dumps(STATE)})")
                page.wait_for_timeout(1500)
                tag = f"{size}-{scheme}"

                def shot(name, tag=tag, page=page):
                    page.wait_for_timeout(700)
                    path = out / f"{tag}-{name}.png"
                    page.screenshot(path=str(path), full_page=True)
                    shots.append(path.name)
                    for p in page.evaluate(OVERFLOW_JS):
                        problems.append(f"{tag} {name}: overflow: {p}")

                linked = page.evaluate("[...new Set([...document.querySelectorAll('[data-go]')].map(e => e.dataset.go))]")
                targets = list(dict.fromkeys(["home", "chat", "skills", *linked]))  # the top tabs aren't data-go links
                for target in targets:
                    p, _, t = target.partition(":")
                    page.evaluate(f"go({json.dumps(p)}, {json.dumps(t or None)})")
                    shot(target.replace(":", "-"))
                page.evaluate("go('home')")
                page.keyboard.press("Meta+k")  # ⌘K: the command palette
                if page.is_hidden("#pal"):
                    problems.append(f"{tag}: ⌘K didn't open the command palette")
                shot("palette")
                page.keyboard.press("Escape")
                page.evaluate("openOnboarding()")
                shot("onboarding")
                page.evaluate("closeOnboarding ? closeOnboarding() : null") if page.evaluate("typeof closeOnboarding") == "function" else page.reload()
                problems += [f"{tag}: console error: {e}" for e in errors]
                ctx.close()
        browser.close()
    return problems, shots


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", type=Path, nargs="?", default=ROOT / "macos-ui-snapshots")
    ap.add_argument("--sizes", default=",".join(SIZES))
    ap.add_argument("--schemes", default="light,dark")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ⌘ in a Windows console
    problems, shots = run(args.out, args.sizes.split(","), args.schemes.split(","))
    report = "\n".join(problems) or "No problems found."
    (args.out / "report.txt").write_text(f"{len(shots)} pictures\n{report}\n", encoding="utf-8")
    print(f"{len(shots)} pictures in {args.out}\n{report}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
