"""The Nova window: first-run setup, chat, history, dictionary and settings.

Its own process (pywebview and Nova's Tk both need the main thread), started by Nova from the tray icon.
It talks to Nova over an authenticated local channel and edits config.json directly; Nova notices the
change and applies it within a second. Run: python -m core.app (Nova starts it for you).
"""
import base64
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from multiprocessing.connection import Client
from pathlib import Path

import webview

from core import browser as web
from core import (calendar_ics, clipboard, cloud_stt, deepgram, diagnostics, fallback, meetings, models, phone,
                  stats, system, tts, update)
from core.brain import find_cli, too_broad
from core.local_llm import LocalLLM
from core.config import (CONFIG, DATA, LOGS, NOTES, ROOT, defaults, load_config, log, read_history, save_config,
                         update_config, write_private)

HTML = Path(__file__).with_name("app.html")
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
PACKAGES = {"claude": "@anthropic-ai/claude-code", "codex": "@openai/codex"}
STATUS = {"claude": ["auth", "status"], "codex": ["login", "status"]}
LOGIN = {"claude": ["auth", "login"], "codex": ["login"]}
SHOWN = {"heard", "reply", "dictation", "edit", "approval", "error"}  # log events the window lists
LANGUAGES = {"auto": "Detect automatically", "en": "English", "hi": "Hindi", "bn": "Bengali", "mr": "Marathi",
             "ta": "Tamil", "te": "Telugu", "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu", "es": "Spanish",
             "fr": "French", "de": "German", "pt": "Portuguese", "it": "Italian", "ja": "Japanese", "ko": "Korean",
             "zh": "Chinese", "ar": "Arabic", "ru": "Russian"}


# taken out of the environment, so nothing this window starts (npm, winget, a CLI login) inherits the key
CTRL = os.environ.pop("NOVA_CTRL", None), os.environ.pop("NOVA_CTRL_KEY", None)


class Api:
    """Everything the page can call as `pywebview.api.<name>(...)`. Underscored names stay private."""

    def __init__(self):
        self._window, self._conn, self._mic, self._level = None, None, None, 0.0
        self._send_lock = threading.Lock()

    # ---------- link to Nova ----------
    def hello(self):
        """First call from the page: connect to Nova and return everything the page needs to draw."""
        if self._conn is None and CTRL[0]:
            try:
                self._conn = Client(CTRL[0], authkey=bytes.fromhex(CTRL[1]))
                threading.Thread(target=self._receive, daemon=True).start()
            except OSError:
                self._conn = None
        cfg, error = load_config()
        return {"config": cfg, "defaults": defaults(), "error": error, "connected": self._conn is not None,
                "platform": "mac" if system.IS_MAC else "win", "page": os.environ.get("NOVA_PAGE", ""),
                "autostart": system.autostart_enabled(), "default_hotkey": system.DEFAULT_HOTKEY,
                "claude_hook": self._hook_installed(), "version": update.current(),
                "languages": LANGUAGES, "paths": {"config": str(CONFIG), "logs": str(LOGS), "notes": str(NOTES), "root": str(ROOT)}}

    def _receive(self):
        try:
            while True:
                event = self._conn.recv()
                if event.get("event") == "focus":
                    self._focus()
                self._push(event)
        except (EOFError, OSError):
            self._push({"event": "gone"})  # Nova quit

    def _push(self, event):
        if self._window:
            self._window.evaluate_js(f"window.nova && nova.recv({json.dumps(event, default=str)})")

    def _focus(self):
        self._window.restore()
        self._window.show()
        self._window.on_top = True  # bring it in front of whatever has focus, then behave normally
        self._window.on_top = False

    def send(self, op, data=None):
        """A request for Nova: ask, approve, cancel, listen, mode, pause, reset, state."""
        if not self._conn:
            raise RuntimeError("Nova isn't running. Start it from the Start menu or Applications.")
        with self._send_lock:
            self._conn.send({"op": op, **(data or {})})
        return True

    # ---------- settings ----------
    def save(self, changes):
        """Apply {"dotted.path": value} on top of the settings on disk now, so changes Nova or the AI made
        while the window was open survive. Only values that differ from the defaults are written."""
        update_config(changes)
        return True

    def local_llm_test(self, url, model):
        """Settings → Dictation's Test: "ok" when the local model answers, else what to check."""
        if LocalLLM(url, model).clean("Reply with the word ok.", "ok", model, timeout=30):
            return "ok"
        return f"Nova couldn't get an answer from {model} at {url}. Is Ollama (or your server) running, with that model?"

    def stats(self):
        """Words dictated, speaking speed and minutes saved, for the Home page."""
        return stats.summary()

    def settings(self):
        """The settings on disk now (the page's list editors re-read theirs before changing them)."""
        return load_config()[0]

    def reset_settings(self):
        cfg, _ = load_config()
        # browsers stay: the extension is still installed in them, so forgetting them would strand it
        keep = {"onboarded": cfg.get("onboarded", False), "brain": {"engine": cfg["brain"]["engine"]},
                "browser": cfg["browser"]}
        CONFIG.write_text(json.dumps(keep, indent=2), encoding="utf-8")
        return load_config()[0]

    def check_hotkey(self, combo):
        """'' if the shortcut can be used, else why not."""
        if combo.split("+")[-1] in ("ctrl", "alt", "shift", "cmd", "windows"):
            return "Add a normal key, like Space or a letter."
        if not system.IS_MAC:
            import keyboard
            try:
                keyboard.parse_hotkey(combo)
            except ValueError as e:
                return str(e)
        return ""

    # ---------- "Claude Code finished" announcements: a Stop hook in the user's own Claude settings ----------
    def _hook(self):
        return system.hook_command(system.CONSOLE_PYTHON, ROOT / "helpers" / "on_stop.py")

    def _hook_installed(self):
        try:
            hooks = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8")).get("hooks", {}).get("Stop", [])
        except (OSError, ValueError):
            return False
        return any("on_stop.py" in h.get("command", "") for group in hooks for h in group.get("hooks", []))

    def claude_hook(self, on):
        """Add or remove Nova's Stop hook in ~/.claude/settings.json, keeping everything else in that file."""
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8")) if CLAUDE_SETTINGS.exists() else {}
        except ValueError:
            raise RuntimeError(f"{CLAUDE_SETTINGS} isn't valid JSON, so Nova won't touch it. Fix it and try again.")
        hooks = settings.setdefault("hooks", {})
        groups = [g for g in hooks.get("Stop", [])
                  if not any("on_stop.py" in h.get("command", "") for h in g.get("hooks", []))]
        if on:
            groups.append({"hooks": [{"type": "command", "command": self._hook(), "timeout": 10}]})
        hooks["Stop"] = groups
        if not groups:
            hooks.pop("Stop")
        if not hooks:
            settings.pop("hooks")
        CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        if CLAUDE_SETTINGS.exists():
            CLAUDE_SETTINGS.with_suffix(".json.nova-backup").write_bytes(CLAUDE_SETTINGS.read_bytes())
        CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return self._hook_installed()

    # ---------- the phone page (core/phone.py) ----------
    def phone_info(self):
        """The pairing links (home Wi-Fi, then Tailscale) with a QR code for each, while the phone page is on."""
        cfg, _ = load_config()
        out = []
        for link in phone.links() if cfg["phone"]["enabled"] else []:
            qr = ""
            try:
                import qrcode
                buf = io.BytesIO()
                qrcode.make(link, box_size=8, border=2).save(buf)
                qr = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            except ImportError:  # set up before the phone page existed: the link still works, typed or copied
                pass
            tailscale = link.split("//")[1].startswith("100.")
            out.append({"link": link, "qr": qr, "tailscale": tailscale,
                        "where": "Tailscale (recommended)" if tailscale else "Home Wi-Fi"})
        # Tailscale first: its address never changes, it works on any network, and it's encrypted
        return sorted(out, key=lambda c: not c["tailscale"])

    def phone_forget(self):
        """A new pairing key: every phone has to scan the new QR code."""
        phone.token(new=True)
        phone.token(new=True, path=phone.SIRI)
        if self._conn:
            self.send("phone_forget")
        return self.phone_info()

    # ---------- updates (core/update.py) ----------
    def check_update(self):
        return update.newer()

    def update(self):
        """Fetch the new version and start setup, which restarts Nova (and closes this window)."""
        update.install()
        return True

    def close(self):
        """Cmd+W on a Mac: close the window, like its red button."""
        self._window.destroy()

    def demo(self):
        """First-run "Show me": this window gets out of the way, then Nova points at something on the screen."""
        self._window.minimize()
        return self.send("demo")

    # ---------- folders Nova may edit without asking (core/brain.py) ----------
    def pick_folder(self):
        """Ask for a folder; returns its path, None if cancelled. Folders that are too broad are refused."""
        picked = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not picked:
            return None
        why = too_broad(picked[0])
        if why:
            raise ValueError(why)
        return str(Path(picked[0]).resolve())

    # ---------- the backup brain (core/fallback.py) ----------
    def fallback_status(self):
        return {"set": bool(fallback.key())}

    def fallback_save(self, key):
        """Check the key with Google first; only a working key is saved."""
        key = str(key).strip()
        cfg, _ = load_config()
        problem = fallback.check(key, cfg["brain"]["fallback_model"]) if key else "Paste a key first."
        if problem:
            raise RuntimeError(problem)
        fallback.KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_private(fallback.KEY_FILE, key)
        return True

    def fallback_remove(self):
        fallback.KEY_FILE.unlink(missing_ok=True)
        return True

    def open_key_page(self):
        system.open_url("https://aistudio.google.com/apikey")
        return True

    # ---------- speech engines: cloud keys (core/cloud_stt.py, core/deepgram.py) and models (core/models.py) ----------
    def stt_key_status(self, provider):
        return {"set": bool(cloud_stt.key(provider))}

    def stt_key_save(self, provider, key):
        """Check the key with the provider first; only a working key is saved."""
        key, cfg = str(key).strip(), load_config()[0]
        if provider not in (*cloud_stt.PROVIDERS, "deepgram"):
            raise ValueError("unknown speech service")
        if not key:
            raise RuntimeError("Paste a key first.")
        problem = deepgram.check(key) if provider == "deepgram" else cloud_stt.check(
            provider, key, cfg["voice"]["custom_stt_url"] if provider == "custom" else "")
        if problem:
            raise RuntimeError(problem)
        cloud_stt.key_file(provider).parent.mkdir(parents=True, exist_ok=True)
        write_private(cloud_stt.key_file(provider), key)
        return True

    def stt_key_remove(self, provider):
        if provider in (*cloud_stt.PROVIDERS, "deepgram"):
            cloud_stt.key_file(provider).unlink(missing_ok=True)
        return True

    def open_stt_key_page(self, provider):
        page = "https://console.deepgram.com/signup" if provider == "deepgram" else cloud_stt.PROVIDERS[provider][2]
        if page:
            system.open_url(page)
        return True

    def model_status(self):
        return {name: {"installed": models.installed(name), "size": d[3]} for name, d in models.DOWNLOADS.items()}

    def download_model(self, name):
        """Fetch an on-device model; progress arrives as {event: 'install'} lines."""
        if name not in models.DOWNLOADS:
            raise ValueError("unknown model")
        if self._run([sys.executable, "-m", "core.models", "download", name], cwd=ROOT) != 0:
            raise RuntimeError("The download didn't finish. Check your internet connection and try again.")
        return models.installed(name)

    # ---------- meetings (core/meetings.py; Nova writes them, the window reads them) ----------
    def meetings_list(self, folder="", query=""):
        every, mc = meetings.all_meetings(), load_config()[0]["meetings"]  # read once: they can be large
        return {"meetings": meetings.search(every, query, folder or None),
                "folders": sorted({m["folder"] for m in every} | {mc["folder"]}),
                "actions": {**meetings.ACTIONS, **mc["actions"]}}

    def meeting_get(self, mid):
        return meetings.load(mid)

    def open_meeting_note(self, mid):
        m = meetings.load(mid)
        if not m.get("note"):
            raise RuntimeError("The note is written once the meeting is transcribed.")
        system.open_path(NOTES / m["note"])
        return True

    def export_meeting(self, mid, kind):
        """Save the transcript as subtitles (srt), plain text (txt) or the full note (md); None if cancelled."""
        m = meetings.load(mid)
        write = {"srt": meetings.srt, "txt": meetings.transcript_text, "md": meetings.markdown}[kind]
        safe = "".join(c for c in m["title"] if c not in '<>:"/\\|?*').strip(" .") or "Meeting"
        picked = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"{safe}.{kind}")
        if not picked:
            return None
        path = Path(picked if isinstance(picked, str) else picked[0])
        path.write_text(write(m), encoding="utf-8")
        return str(path)

    def pick_audio(self):
        """Ask for audio or video files to transcribe; returns their paths ([] if cancelled)."""
        kinds = ("Audio and video (*.mp3;*.wav;*.m4a;*.webm;*.ogg;*.flac;*.aac;*.opus;*.mp4;*.mov;*.mkv)",
                 "All files (*.*)")
        picked = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=kinds)
        return [str(p) for p in picked or []]

    def calendar_status(self):
        return {"set": bool(calendar_ics.url())}

    def calendar_save(self, address):
        """Check that the address is a calendar first; only a working one is saved."""
        address = str(address).strip()
        try:
            calendar_ics.fetch(address)
        except ValueError as e:
            raise RuntimeError(str(e)) from None
        except Exception:
            raise RuntimeError("Couldn't read a calendar at that address. Copy the secret iCal (ICS) address "
                               "again.") from None
        calendar_ics.KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_private(calendar_ics.KEY_FILE, address)
        return True

    def calendar_remove(self):
        calendar_ics.KEY_FILE.unlink(missing_ok=True)
        return True

    def upcoming(self):
        """Today's and tomorrow's calendar meetings still to come (or happening now)."""
        import datetime as dt
        if not calendar_ics.url():
            return []
        now = dt.datetime.now()
        try:
            found = calendar_ics.events(now - dt.timedelta(hours=2), now + dt.timedelta(days=2))
        except Exception as e:
            raise RuntimeError(f"Couldn't read your calendar: {e}") from None
        return [{"title": e["title"], "start": e["start"].timestamp(), "end": e["end"].timestamp()}
                for e in found if e["end"] > now][:8]

    # ---------- browsers (core/browser.py) ----------
    def browsers(self):
        cfg, _ = load_config()
        found = web.detect()
        for b in found:
            b["folder"] = str(web.folder(b["id"]))
        return {"found": found, "enabled": cfg["browser"]["enabled"], "default": cfg["browser"]["default"]}

    def browser_set(self, bid, on):
        """Set Nova up in a browser (copy the extension, add the launch flag) or remove it."""
        token = (DATA / "browser-token").read_text(encoding="utf-8").strip()
        report = web.install(bid, token) if on else web.uninstall(bid)
        cfg, _ = load_config()
        b = cfg["browser"]
        b["enabled"] = [x for x in b["enabled"] if x != bid] + ([bid] if on else [])
        if b["default"] not in b["enabled"] and b["enabled"]:
            b["default"] = b["enabled"][0]
        save_config(cfg)
        return {**report, "running": web.running(bid), "default": b["default"], "enabled": b["enabled"]}

    def browser_default(self, bid):
        cfg, _ = load_config()
        cfg["browser"]["default"] = bid
        save_config(cfg)
        return bid

    def browser_restart(self, bid):
        threading.Thread(target=web.restart, args=(bid,), daemon=True).start()
        return True

    def browser_guide(self, bid):
        """Chrome, Edge and Arc: open their extensions page and put the folder to load on the clipboard.
        Safari: open it and say whether its "Allow JavaScript from Apple Events" is on yet."""
        if web.BROWSERS[bid][3] == "applescript":
            if not web.running(bid):
                web.launch(bid)
                time.sleep(3)
            return web.safari_ready()
        page = {"chrome": "chrome://extensions", "edge": "edge://extensions",
                "arc": "arc://extensions"}.get(bid, "about:blank")
        clipboard.set_text(str(web.folder(bid)))
        subprocess.Popen([web.exe(bid), page], creationflags=system.NO_WINDOW)
        return str(web.folder(bid))

    def autostart(self, on):
        system.set_autostart(bool(on), Path(sys.executable), ROOT / "nova.py", DATA / "nova.ico")
        return system.autostart_enabled()

    def voice_enrolled(self):
        """The "Hey Nova" voiceprint's state for Settings (Nova records it: send("enroll_voice")): whether there is one,
        whether this microphone is one its tries were recorded on, the try-out's end, and the last 7 days' counts."""
        from core import wakeword
        if not wakeword.enrolled():
            return {"enrolled": False}
        mic, known, since = wakeword.mic_name(), wakeword.levels(), time.time() - 7 * 86400
        recent = [e for e in read_history({"wake_check", "wake_ignored", "wake_shadow"}) if e.get("t", 0) > since]
        count = lambda kind, **want: sum(e["event"] == kind and all(e.get(k) == v for k, v in want.items())  # noqa: E731
                                         for e in recent)
        return {"enrolled": True, "mic": mic, "new_mic": bool(mic and known and mic not in known),
                "tryout_until": wakeword.tryout_until(), "woke": count("wake_check"), "ignored": count("wake_ignored"),
                "would": count("wake_shadow", would_wake=True)}

    # ---------- history ----------
    def history(self, limit=None):
        """Everything the History page lists: all of it, since the logs only keep 30 days anyway."""
        return read_history(SHOWN, limit)

    def memory(self, lines=None):
        """Nova's long-term memory (notes/memory.md), one fact per line. With `lines`, replace it first."""
        path = NOTES / "memory.md"
        if lines is not None:
            NOTES.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(f"{line.strip()}\n" for line in lines if line.strip()), encoding="utf-8")
        try:
            return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            return []

    def clear_history(self):
        for f in LOGS.glob("nova-*.jsonl"):
            f.unlink(missing_ok=True)
        return True

    def copy(self, text):
        clipboard.set_text(str(text))
        return True

    # ---------- voice and microphone ----------
    def voices(self):
        try:
            system_voices = tts.voices()
        except OSError:
            system_voices = []
        return {"system": system_voices, "natural": tts.ENGLISH, "kitten": tts.KITTEN_VOICES,
                "installed": {e: tts.installed(e) for e in tts.ENGINES},
                "capable": {e: tts.capable(e) for e in tts.ENGINES}}

    def voice_preview(self, engine, voice=""):
        """A recorded sample of a voice, to play right away (see tts.preview)."""
        return tts.preview(engine, voice)

    def test_voice(self, settings):
        """Play a sample with the unsaved voice settings; Nova speaks it, so the model is loaded only once."""
        if self._conn:
            return self.send("test_voice", settings)
        threading.Thread(target=tts.speak, args=("Hi, I'm Nova.", settings, threading.Event()), daemon=True).start()
        return True

    def download_voice(self, engine="kokoro"):
        """Fetch a voice (Kokoro: about 330 MB); progress arrives as {event: 'install'} lines."""
        if engine not in tts.ENGINES:
            raise ValueError("unknown voice")
        if self._run([sys.executable, "-m", "core.tts", "download", engine], cwd=ROOT) != 0:
            raise RuntimeError("The download didn't finish. Check your internet connection and try again.")
        return tts.installed(engine)

    def mic_start(self):
        """Start the microphone test; levels arrive as {event: 'mic'}. Returns the device name."""
        import numpy as np
        import sounddevice as sd
        from core import audio
        if self._mic is None:
            def callback(data, *_):
                self._level = max(self._level * 0.6, audio.level(float(np.sqrt(np.mean(data ** 2)))))
            self._mic = sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=480,
                                       callback=callback)
            self._mic.start()
            threading.Thread(target=self._meter, daemon=True).start()
        return sd.query_devices(kind="input")["name"]

    def _meter(self):
        while self._mic is not None:
            self._push({"event": "mic", "value": round(self._level, 3)})
            time.sleep(0.05)

    def mic_stop(self):
        mic, self._mic = self._mic, None
        if mic:
            mic.close()
        return True

    # ---------- Claude Code / Codex ----------
    def engines(self):
        """Which CLIs are installed and signed in, and whether Node.js is there to install one."""
        system.refresh_path()
        out = {}
        for name in ("claude", "codex"):
            exe, signed_in = find_cli(name), False
            if exe:
                try:
                    signed_in = subprocess.run([exe, *STATUS[name]], capture_output=True, timeout=25,
                                               cwd=tempfile.gettempdir(), creationflags=system.NO_WINDOW).returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    pass
            out[name] = {"installed": bool(exe), "signed_in": signed_in}
        out["npm"] = bool(shutil.which("npm"))
        return out

    def _run(self, args, cwd=None):
        self._push({"event": "install", "line": "$ " + " ".join(Path(args[0]).name if i == 0 else a
                                                                  for i, a in enumerate(args))})
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                             errors="replace", cwd=cwd or tempfile.gettempdir(), creationflags=system.NO_WINDOW)
        for line in p.stdout:
            if line.strip():
                self._push({"event": "install", "line": line.rstrip()[:300]})
        return p.wait()

    def install(self, name):
        """Install Node.js if needed, then the CLI. Progress arrives as {event: 'install'} lines."""
        if not shutil.which("npm"):
            if system.IS_MAC and shutil.which("brew"):
                self._run(["brew", "install", "node"])
            elif not system.IS_MAC and shutil.which("winget"):
                self._run(["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                           "--accept-source-agreements", "--accept-package-agreements"])
            system.refresh_path()
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("Node.js is needed first. Install the LTS version from nodejs.org, then try again.")
        if self._run([npm, "install", "-g", PACKAGES[name]]) != 0:
            raise RuntimeError("The install didn't finish. The last lines above say why.")
        system.refresh_path()
        return bool(find_cli(name))

    def login(self, name):
        """Open the CLI's own sign-in in a terminal window; the page polls engines() until it's done."""
        exe = find_cli(name)
        if not exe:
            raise RuntimeError("Install it first.")
        if system.IS_MAC:
            command = " ".join(shlex.quote(a) for a in [exe, *LOGIN[name]])
            script = command.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(["osascript", "-e", 'tell application "Terminal" to activate',
                              "-e", f'tell application "Terminal" to do script "{script}"'])
        else:
            subprocess.Popen([exe, *LOGIN[name]], cwd=str(Path.home()), creationflags=subprocess.CREATE_NEW_CONSOLE)
        return True

    # ---------- macOS permissions: live status, and one way to grant each (system.ask_permission) ----------
    def mac_permissions(self):
        return system.mac_permissions()

    def mac_allow(self, name):
        if name not in system.MAC_PANES:
            raise ValueError(name)
        return system.ask_permission(name)

    def restart(self):
        """macOS applies Screen Recording (and sometimes Input Monitoring) only after Nova starts again."""
        return self.send("restart")

    # ---------- files ----------
    def diagnostics(self):
        """Save the diagnostics zip (core/diagnostics.py), show it in its folder and open a new GitHub issue."""
        path = diagnostics.save(version=update.current())
        system.open_path(path.parent)
        system.open_url(f"https://github.com/{update.REPO}/issues/new")
        return path.name

    # ---------- files ----------
    def open(self, what):
        if what == "config":
            if not CONFIG.exists():
                CONFIG.write_text("{}\n", encoding="utf-8")
            return system.edit_file(CONFIG)
        if what == "nova-app":  # to drag into a Privacy & Security list when Nova isn't in it
            subprocess.Popen(["open", "-R", str(system.MAC_APP)])
            return True
        system.open_path({"logs": LOGS, "notes": NOTES, "folder": ROOT}[what])
        return True


def stale(drawn):
    """An icon file drawn before core/icon.py last changed (an update brought a new design)."""
    return not drawn.exists() or drawn.stat().st_mtime < (ROOT / "core" / "icon.py").stat().st_mtime


def nova_icon():
    """Nova's .ico (setup makes one; draw it if this copy has none, or core/icon.py changed since)."""
    ico = DATA / "nova.ico"
    if stale(ico):
        from core.icon import draw
        ico.parent.mkdir(parents=True, exist_ok=True)
        draw(256).save(ico)
    return ico


def set_window_icon(window):
    """Nova's icon on the window and its taskbar button, instead of Python's."""
    import ctypes
    try:
        hwnd = int(window.native.Handle.ToInt64())
        load = ctypes.windll.user32.LoadImageW
        load.restype = ctypes.c_void_p
        for size, which in ((16, 0), (32, 1)):  # ICON_SMALL (title bar), ICON_BIG (taskbar, Alt+Tab)
            icon = load(None, str(nova_icon()), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
            ctypes.windll.user32.SendMessageW(hwnd, 0x80, which, ctypes.c_void_p(icon))  # WM_SETICON
    except Exception as e:  # cosmetic: the window still works with the default icon
        log("error", error=f"window icon: {e!r}")


def window_bg():
    """The colour the window shows before the page paints: app.html's --bg for the system's light or dark mode."""
    try:
        if system.IS_MAC:
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True, timeout=3)
            dark = out.stdout.strip() == "Dark"
        else:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                dark = winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:  # no setting saved means the system default, which is light
        dark = False
    return "#0d0f1a" if dark else "#f5f6fb"


def main():
    if not system.IS_MAC:  # its own taskbar identity, so Windows doesn't group the window under "Python"
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Nova.Assistant")
    else:  # Nova's icon in the Dock while the window is open, instead of Python's rocket
        try:
            from AppKit import NSApplication, NSImage
            png = DATA / "nova.png"
            if stale(png):
                from core.icon import draw
                draw(512).save(png)
            NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(str(png)))
        except Exception as e:
            log("error", error=f"dock icon: {e!r}")
    api = Api()
    window = webview.create_window("Nova", html=phone.page(HTML), js_api=api, width=1080, height=740,
                                   min_size=(820, 580), background_color=window_bg())
    api._window = window
    window.events.closed += api.mic_stop
    if not system.IS_MAC:
        window.events.shown += lambda: set_window_icon(window)
    webview.start(debug=bool(os.environ.get("NOVA_DEBUG")))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # pythonw has no console: leave the reason in Nova's log
        log("error", error=f"Nova window: {e!r}")
        raise
