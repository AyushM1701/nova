"""Nova: say "Hey Nova", press the shortcut or click the bar, then speak.

Assistant mode (default) hands the request to Claude Code or Codex and speaks the answer.
Dictation mode works like Wispr Flow: clean text (no fillers, self-corrections applied) is typed
into whatever app you are in. Say "switch to dictation" / "switch to assistant" to change modes.
Everything Nova keeps (config, logs, notes, speech models) stays on this computer.
"""
import json
import os
import queue
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
import tkinter as tk
from multiprocessing.connection import Listener
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
if (ROOT / "data" / "models-ready").exists():  # setup downloaded the speech models: never call home again
    os.environ["HF_HUB_OFFLINE"] = "1"

import pystray  # noqa: E402

from core import audio, cleanup, clipboard, icon, system, tts, wake  # noqa: E402
from core.bar import Bar  # noqa: E402
from core.brain import discover_projects, find_cli, make_brain  # noqa: E402
from core.overlay import Card  # noqa: E402

CONFIG, DEFAULTS = ROOT / "config.json", ROOT / "config.default.json"
LOGS, DATA, WORKSPACE = ROOT / "logs", ROOT / "data", ROOT / "workspace"
NOTES = WORKSPACE / "notes"
CLAUDE_GUARDED = "Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|Glob"
CLAUDE_ALLOWED = ["Read", "Glob", "Grep", "Bash", "PowerShell", "Write", "Edit", "WebSearch", "WebFetch", "TodoWrite"]
SINGLE_INSTANCE_PORT = 47821

MODE_PHRASES = {
    "dictation": r"(switch|change|go)( to)? dictation( mode)?|dictation mode|start dictation",
    "assistant": r"(switch|change|go)( to)? assistant( mode)?|assistant mode|stop dictation",
}
MEDIA = {  # local fast path: no Claude/Codex round trip for these
    r"(pause|play|resume)( the)?( music| song| playback)?": ("play_pause", 1),
    r"(next|skip)( the)?( song| track)?": ("next", 1),
    r"previous( song| track)?|last song": ("previous", 1),
    r"(mute|unmute)( the)?( volume| sound)?": ("mute", 1),
    r"(turn )?(the )?volume up|louder|turn it up": ("volume_up", 5),
    r"(turn )?(the )?volume down|quieter|turn it down": ("volume_down", 5),
}


def log(event, **fields):
    with open(LOGS / time.strftime("nova-%Y-%m-%d.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "event": event, **fields}, ensure_ascii=False, default=str) + "\n")


def merged(base, override):
    """Defaults with the user's settings on top, so new settings from an update appear automatically."""
    out = dict(base)
    for k, v in override.items():
        out[k] = merged(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_config():
    user = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    return merged(json.loads(DEFAULTS.read_text(encoding="utf-8")), user)


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


class Nova:
    def __init__(self):
        for d in (LOGS, NOTES, DATA):
            d.mkdir(parents=True, exist_ok=True)
        self.cfg = load_config()
        self.mode, self.paused, self.phase = self.cfg["start_mode"], False, "idle"  # idle | listening | busy
        self.stt, self.target, self.pending = None, None, None
        self.ui_queue = queue.Queue()
        self.stop_rec, self.cancel, self.stop_tts = threading.Event(), threading.Event(), threading.Event()
        self.approval_lock = threading.Lock()
        # vars inherited from a Claude desktop/IDE session make the CLI ignore your own login
        for k in [k for k in os.environ if k.startswith(("CLAUDE", "ANTHROPIC"))]:
            os.environ.pop(k)

        # approvals from guard.py arrive over an authenticated local pipe / socket
        self.pipe = (rf"\\.\pipe\nova-{secrets.token_hex(6)}" if os.name == "nt"
                     else os.path.join(tempfile.gettempdir(), f"nova-{secrets.token_hex(6)}.sock"))
        key = secrets.token_bytes(32)
        self.listener = Listener(self.pipe, authkey=key)
        self.env = dict(os.environ, NOVA_PIPE=self.pipe, NOVA_KEY=key.hex(), NOVA_HOME=str(ROOT),
                        NOVA_NOTES=str(NOTES), NOVA_LOG=str(LOGS),
                        NOVA_TIMEOUT=str(self.cfg["safety"]["confirm_timeout_s"]),
                        # Claude Code: no telemetry, error reports or other non-essential traffic
                        DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1",
                        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        python = Path(sys.executable)
        if os.name == "nt":  # pythonw has no stdout, and the hook must answer on stdout
            python = python.with_name("python.exe")
        self.hook = system.hook_command(python, ROOT / "guard" / "guard.py")
        self.settings = self.write_claude_settings()
        self.brain = make_brain(self.cfg, str(WORKSPACE), self.env, self.settings, self.hook)

        system.before_tk()
        self.root = tk.Tk()
        self.root.withdraw()
        system.after_tk()
        self.card = Card(self.root, lambda: self.answer(True), lambda: self.answer(False))
        self.bar = Bar(self.root, self.on_hotkey)  # clicking the bar works like the shortcut

    # ---------- setup ----------
    def write_claude_settings(self):
        """Claude Code settings: tools pre-allowed so the guard hook, not a prompt, makes every decision."""
        settings = {
            "permissions": {"allow": CLAUDE_ALLOWED},
            "hooks": {"PreToolUse": [{"matcher": CLAUDE_GUARDED, "hooks": [
                {"type": "command", "command": self.hook,
                 "timeout": self.cfg["safety"]["confirm_timeout_s"] + 30}]}]},
        }
        path = DATA / "claude-settings.json"
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return str(path)

    def run(self):
        threading.Thread(target=self.serve_approvals, daemon=True).start()
        threading.Thread(target=self.load_stt, daemon=True).start()
        self.hotkey = self.cfg["hotkey"] or system.DEFAULT_HOTKEY
        self.keys = system.Hotkeys(self.hotkey, lambda: self.ui(self.on_hotkey), lambda: self.ui(self.on_esc))
        self.start_tray()
        self.card.show("Nova is starting", "Loading the speech model…")
        self.root.after(30, self.pump)
        self.root.mainloop()

    def load_stt(self):
        from core.stt import STT  # heavy import, kept off the startup path
        v = self.cfg["voice"]
        stt = STT(v["stt_model"], v["stt_accurate_model"])
        self.stt = stt
        hint = (f"Say \"Hey Nova\", press {self.hotkey} or click the bar. Mode: {self.mode}. "
                f"Brain: {self.brain.name if self.brain else 'none'}. Speech runs on the {stt.device}.")
        if not self.brain:
            hint += " No Claude Code or Codex CLI found: run setup again to connect one."
        self.ui(lambda: self.card.show("Nova is ready", hint, hide_after=6))
        log("start", mode=self.mode, brain=self.brain and self.brain.exe, stt_device=stt.device)
        if self.cfg["wake_word"]:
            threading.Thread(target=self.run_wake, daemon=True).start()
        stt.load_accurate()  # CPU only: the Hindi/Hinglish model loads after Nova is already usable

    def start_tray(self):
        engine = lambda name: pystray.MenuItem(
            "Claude Code" if name == "claude" else "Codex", lambda: self.ui(lambda: self.set_engine(name)),
            checked=lambda _: self.cfg["brain"]["engine"] == name, radio=True, enabled=bool(find_cli(name)))
        menu = pystray.Menu(
            pystray.MenuItem("Assistant mode", lambda: self.ui(lambda: self.set_mode("assistant")),
                             checked=lambda _: self.mode == "assistant", radio=True),
            pystray.MenuItem("Dictation mode", lambda: self.ui(lambda: self.set_mode("dictation")),
                             checked=lambda _: self.mode == "dictation", radio=True),
            pystray.MenuItem("Brain", pystray.Menu(engine("claude"), engine("codex"))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Pause", lambda: self.ui(self.toggle_pause), checked=lambda _: self.paused),
            pystray.MenuItem("Open log folder", lambda: system.open_path(LOGS)),
            pystray.MenuItem("Edit settings", lambda: system.edit_file(CONFIG if CONFIG.exists() else DEFAULTS)),
            pystray.MenuItem("Quit Nova", lambda: self.ui(self.quit)),
        )
        self.icon = pystray.Icon("nova", icon.draw(), "Nova", menu)
        self.icon.run_detached()

    # ---------- UI thread ----------
    def ui(self, fn):
        self.ui_queue.put(fn)

    def pump(self):
        while not self.ui_queue.empty():
            self.ui_queue.get_nowait()()
        self.root.after(30, self.pump)

    def on_hotkey(self):
        if self.pending:
            return self.answer(True)
        if self.phase == "listening":
            return self.stop_rec.set()
        if self.phase == "busy":
            return self.abort()
        if self.paused:
            return self.card.show("Nova is paused", "Resume it from the Nova icon.", hide_after=2)
        if self.stt is None:
            return self.card.show("Still loading", "The speech model is loading, try again in a moment.", hide_after=3)
        self.start_job()

    def on_wake(self, clip):
        if self.phase == "idle" and not self.paused and not self.pending:
            log("wake", with_request=clip is not None)
            self.start_job(clip)  # "Hey Nova, play music" runs at once; "Hey Nova" alone starts listening

    def start_job(self, clip=None):
        self.target = system.foreground()  # where dictation will be typed
        self.phase = "busy" if clip is not None else "listening"
        threading.Thread(target=self.job, args=(clip,), daemon=True).start()

    def run_wake(self):
        try:
            wake.listen(self.stt.quick, lambda clip: self.ui(lambda: self.on_wake(clip)),
                        lambda: self.phase == "idle" and not self.paused and not self.pending)
        except Exception as e:  # no microphone, device unplugged: the shortcut still works
            log("error", error=f"wake word stopped: {e!r}")

    def on_esc(self):
        if self.pending:
            self.answer(False)
        elif self.phase != "idle":
            self.abort()

    def abort(self):
        for event in (self.cancel, self.stop_rec, self.stop_tts):
            event.set()
        if self.brain:
            self.brain.cancel()
        self.card.show("Cancelled", hide_after=2)

    def answer(self, ok):
        if self.pending:
            done, box = self.pending
            box[0] = ok
            done.set()
            self.card.show("Allowed" if ok else "Denied", "Continuing…")
            self.bar.set("thinking")

    def set_mode(self, mode):
        self.mode = mode
        self.icon.update_menu()
        where = self.brain.name if self.brain else "your AI CLI"
        self.card.show(f"{mode.title()} mode", "Dictation types into the focused app." if mode == "dictation"
                       else f"Requests go to {where}.", hide_after=2)

    def set_engine(self, name):
        if self.phase != "idle":
            return self.card.show("Busy", "Switch brains when Nova has finished.", hide_after=2)
        self.cfg["brain"]["engine"] = name
        save_config(self.cfg)
        self.brain = make_brain(self.cfg, str(WORKSPACE), self.env, self.settings, self.hook)
        self.icon.update_menu()
        self.card.show("Brain", f"Nova now uses {self.brain.name}.", hide_after=2)

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused and self.phase != "idle":
            self.abort()
        self.card.show("Paused" if self.paused else "Resumed", hide_after=2)
        self.bar.set("paused" if self.paused else "idle")

    def quit(self):
        self.abort()
        self.icon.stop()
        self.root.destroy()
        if os.name != "nt":
            Path(self.pipe).unlink(missing_ok=True)
        os._exit(0)

    # ---------- worker thread: one request ----------
    def job(self, clip=None):
        for event in (self.cancel, self.stop_rec, self.stop_tts):
            event.clear()
        self.cfg = load_config()  # pick up settings edits
        if self.brain:
            self.brain.cfg = self.cfg
        mode, v, d = self.mode, self.cfg["voice"], self.cfg["dictation"]
        silence, cap = (d["silence_ms"], d["max_record_s"]) if mode == "dictation" else (v["silence_ms"], v["max_record_s"])
        try:
            if clip is None:  # shortcut, click or a bare "Hey Nova": record the request now
                self.ui(lambda: self.bar.set("listening"))
                system.beep(start=True)
                clip = audio.record(silence, cap, self.stop_rec, lambda x: self.ui(lambda: self.bar.level(x)))
                self.phase = "busy"
                system.beep(start=False)
                if self.cancel.is_set() or clip is None:
                    return
            self.ui(lambda: self.bar.set("thinking"))
            text = self.stt.transcribe(clip, v["language"], d["dictionary"])
            if self.cancel.is_set() or not text:
                return
            log("heard", mode=mode, text=text)
            if not self.command(text):
                (self.dictate if mode == "dictation" else self.assist)(text)
        except Exception as e:
            log("error", error=repr(e))
            self.ui(lambda: self.card.show("Something went wrong", repr(e), hide_after=8))
        finally:
            self.phase = "idle"
            self.ui(lambda: self.bar.set("paused" if self.paused else "idle"))

    def say(self, title, spoken, body=""):
        self.ui(lambda: self.card.show(title, body or spoken))
        self.ui(lambda: self.bar.set("speaking"))
        tts.speak(spoken, self.cfg["voice"]["tts_voice"], self.stop_tts)
        self.ui(lambda: self.card.hide_later(self.cfg["overlay"]["hide_after_s"]))

    def command(self, text):
        """Voice commands that never reach the AI or get typed. Whole-utterance matches only."""
        n = re.sub(r"[^\w\s]", "", text.lower()).strip()
        for mode, pattern in MODE_PHRASES.items():
            if re.fullmatch(pattern, n):
                self.ui(lambda: self.set_mode(mode))
                self.say(f"{mode.title()} mode", f"{mode.title()} mode.")
                return True
        if re.fullmatch(r"(start a )?new (conversation|chat)|reset( the)? conversation", n):
            if self.brain:
                self.brain.reset()
            self.say("New conversation", "Okay, starting fresh.")
            return True
        m = re.fullmatch(r"add (.+?) to (?:my )?(?:dictionary|vocabulary)", text.strip(" .!"), re.I)
        if m:
            word = m.group(1).strip(" \"'.,")
            self.cfg["dictation"]["dictionary"].append(word)
            save_config(self.cfg)
            self.say("Dictionary", f"Added {word}.")
            return True
        if self.mode != "assistant":
            return False
        for pattern, (key, times) in MEDIA.items():
            if re.fullmatch(pattern, n):
                system.media(key, times)
                self.ui(lambda: self.card.show("Done", text, hide_after=2))
                return True
        vol = re.fullmatch(r"(?:set )?(?:the )?volume (?:to )?(\d{1,3})(?: percent)?", n)
        if vol:
            system.set_volume(int(vol.group(1)))
            self.ui(lambda: self.card.show("Done", f"Volume {vol.group(1)}", hide_after=2))
            return True
        return False

    def dictate(self, raw):
        text, how = cleanup.clean(raw, self.cfg["dictation"], self.brain)
        if self.cancel.is_set():
            return
        log("dictation", raw=raw, text=text, how=how)
        self.paste(text)

    def paste(self, text):
        saved = clipboard.snapshot()  # images, copied files and rich text survive the paste
        clipboard.set_text(text)
        system.focus(self.target)
        time.sleep(0.08)
        system.paste()
        time.sleep(0.3)
        clipboard.restore(saved)

    def assist(self, text):
        if not self.brain:
            return self.say("No AI connected", "I can't find Claude Code or Codex. Run Nova's setup to connect one.")
        projects = discover_projects(self.cfg["projects"]["exclude"], ROOT)
        self.env["NOVA_ROOTS"] = os.pathsep.join(projects.values())
        shown, spoken = self.brain.run(text, projects, self.cfg["projects"]["aliases"],
                                       lambda step: self.ui(lambda: self.card.show("Working…", step)))
        if self.cancel.is_set():
            return
        log("reply", brain=self.brain.name, request=text, reply=shown, say=spoken)
        self.say("Nova", spoken, shown)

    # ---------- approvals from guard.py ----------
    def serve_approvals(self):
        while True:
            try:
                conn = self.listener.accept()
            except Exception:  # bad auth key or broken client
                continue
            threading.Thread(target=self.handle_approval, args=(conn,), daemon=True).start()

    def handle_approval(self, conn):
        with conn:
            try:
                req = conn.recv()
                conn.send(False if self.paused else self.ask(req))
            except (EOFError, OSError):
                pass

    def ask(self, req):
        with self.approval_lock:
            done, box = threading.Event(), [False]
            self.pending = (done, box)
            who = self.brain.name if self.brain else "The AI"
            body = f"{who} wants to run something that {req['reason']}:\n\n{req['summary']}"
            self.ui(lambda: self.card.show("Needs your OK", body, buttons=True))
            self.ui(lambda: self.bar.set("approval"))
            threading.Thread(target=tts.speak, daemon=True, args=(
                "I need your OK for this. Press the shortcut to allow, or Escape to deny.",
                self.cfg["voice"]["tts_voice"], threading.Event())).start()
            done.wait(self.cfg["safety"]["confirm_timeout_s"])
            self.pending = None
            log("approval", request=req, allowed=box[0])
            return box[0]


def main():
    lock = socket.socket()
    try:  # one Nova at a time (autostart plus a manual launch would double every shortcut)
        lock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        print("Nova is already running (look for its icon near the clock / in the menu bar).")
        return
    Nova().run()


if __name__ == "__main__":
    main()
