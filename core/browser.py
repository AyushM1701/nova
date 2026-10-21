"""Nova in your real browsers (Opera GX, Brave, …) through a small unpacked extension.

The extension (browser/extension) connects to this bridge over a WebSocket on 127.0.0.1, proving itself with
its exact extension origin and a per-install token. Claude Code and Codex reach the browser through the local
MCP server helpers/browser_mcp.py, which asks Nova to run each tool. Nova, not the AI, decides what is safe:
reading and navigating are allowed, submitting/buying/posting/sending need your OK, and typing passwords,
card numbers or one-time codes is blocked. Page text is untrusted data.

Install: the extension is copied to %LOCALAPPDATA%/Nova/browser/<browser> and `--load-extension=<that folder>`
is added to the browser's user-level shortcuts, taskbar pin, start-at-login entry and link-open command.
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "browser" / "extension"
HOME = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Nova" / "browser"
PORT = 47822
_L, _PF, _PF86 = os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")
# id: (name, executable candidates, ProgId for links, install method, ticked by default)
BROWSERS = {
    "opera-gx": ("Opera GX", [rf"{_L}\Programs\Opera GX\opera.exe"], "Opera GXStable", "flag", True),
    "brave": ("Brave", [rf"{_PF}\BraveSoftware\Brave-Browser\Application\brave.exe",
                        rf"{_L}\BraveSoftware\Brave-Browser\Application\brave.exe"], "BraveHTML", "flag", True),
    "opera": ("Opera", [rf"{_L}\Programs\Opera\opera.exe"], "OperaStable", "flag", False),
    "vivaldi": ("Vivaldi", [rf"{_L}\Vivaldi\Application\vivaldi.exe", rf"{_PF}\Vivaldi\Application\vivaldi.exe"],
                "VivaldiHTM", "flag", False),
    # Chrome 137+ ignores --load-extension in official builds; Edge is treated the same until proven otherwise
    "edge": ("Microsoft Edge", [rf"{_PF86}\Microsoft\Edge\Application\msedge.exe",
                                rf"{_PF}\Microsoft\Edge\Application\msedge.exe"], "MSEdgeHTM", "guided", False),
    "chrome": ("Google Chrome", [rf"{_PF}\Google\Chrome\Application\chrome.exe",
                                 rf"{_L}\Google\Chrome\Application\chrome.exe"], "ChromeHTML", "guided", False),
}
SPOKEN = {"opera gx": "opera-gx", "operagx": "opera-gx", "oprah gx": "opera-gx", "opera g x": "opera-gx", "brave": "brave", "opera": "opera", "vivaldi": "vivaldi",
          "edge": "edge", "microsoft edge": "edge", "chrome": "chrome", "google chrome": "chrome"}
NAMES_RE = "|".join(sorted(map(re.escape, SPOKEN), key=len, reverse=True))

# ---------- safety: what a browser action may do without asking ----------
RISKY = re.compile(r"\b(?:buy|pay|purchase|order|checkout|check out|place order|book|reserve|subscribe|donate|"
                   r"post|publish|tweet|share|send|reply|comment|submit|delete|remove|transfer|withdraw|confirm|"
                   r"sign up|register|apply|upload|accept|agree|install|unsubscribe|deactivate|close account|"
                   r"log ?out|sign ?out|save changes|update payment)\b", re.I)
SECRET_FIELD = re.compile(r"pass(?:word|code|phrase)?|\bpwd\b|card ?(?:number|no)|cc-?num|\bcvv|\bcvc|security code|"
                          r"\botp\b|one[- ]time|verification code|2fa|\bmfa\b|\bpin\b|\bssn\b|social security|"
                          r"\biban\b|account number|routing number|aadhaar|\bpan\b", re.I)
SECRET_AUTOCOMPLETE = re.compile(r"cc-|one-time-code|current-password|new-password", re.I)
CARD_DIGITS = re.compile(r"^\D*(?:\d[ -]?){13,19}\D*$")
SEARCH = re.compile(r"search|query|\bq\b|find", re.I)


def classify(tool, args, element=None):
    """('allow' | 'confirm' | 'block', why) for one browser action. `element` is what the extension reports
    about the real element on the page (not what the AI says it is)."""
    el = element or {}
    what = f'"{el.get("name") or el.get("field") or "an element"}" on {el.get("host") or "the page"}'
    if tool in ("tabs", "navigate", "read", "inspect", "scroll", "screenshot"):
        return "allow", "reads or moves around"
    if tool == "type":
        field = f'{el.get("type", "")} {el.get("field", "")} {el.get("name", "")}'
        if el.get("type") == "password" or SECRET_AUTOCOMPLETE.search(el.get("autocomplete", "")) or \
                SECRET_FIELD.search(field) or CARD_DIGITS.match(str(args.get("text", ""))):
            return "block", f"types into a password, card or one-time-code field ({what}); you do that yourself"
        if args.get("submit") and not (el.get("type") == "search" or SEARCH.search(field)):
            return "confirm", f"types into {what} and submits the form"
        return "allow", "types into a field"
    if tool == "click":
        if el.get("isSubmit") or RISKY.search(el.get("name", "")):
            return "confirm", f"clicks {what}, which may submit, buy, post or send something"
        return "allow", "clicks"
    if tool == "select":
        return "allow", "picks from a dropdown"
    if tool == "press":
        if args.get("key") == "Enter":
            return "confirm", "presses Enter, which may submit a form"
        return "allow", "presses a key"
    if tool == "download":
        return "confirm", f"downloads {str(args.get('url', ''))[:120]}"
    if tool == "script":
        return "confirm", "runs a script inside the page"
    return "confirm", f"unknown browser tool {tool}"


# ---------- install ----------
def extension_id(folder):
    """Chromium's ID for an unpacked extension: SHA-256 of its folder path (UTF-16), first 32 hex digits as a-p."""
    digest = hashlib.sha256(str(folder).encode("utf-16-le")).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def folder(bid):
    return HOME / bid


def exe(bid):
    return next((p for p in BROWSERS[bid][1] if p and Path(p).exists()), None)


def detect():
    """Installed browsers, for the Browsers step."""
    out = []
    for bid, (name, _, _, method, ticked) in BROWSERS.items():
        path = exe(bid)
        if path:
            out.append({"id": bid, "name": name, "method": method, "default_ticked": ticked, "running": running(bid)})
    return out


def running(bid):
    path = exe(bid)
    if not path:
        return False
    r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {Path(path).name}", "/NH"], capture_output=True, text=True,
                       creationflags=0x08000000)
    return Path(path).name.lower() in r.stdout.lower()


def with_flag(command, ext, on=True):
    """`command` (a shortcut's arguments or a full command line) with Nova's --load-extension added or removed."""
    command = re.sub(r'\s*--load-extension=(?:"[^"]*"|\S+)', "", command)
    if not on:
        return command
    flag = f'--load-extension="{ext}"'
    m = re.match(r'\s*("[^"]+"|\S+\.exe)', command, re.I)  # a full command line: the flag goes after the program
    if m:
        return f"{command[:m.end()]} {flag}{command[m.end():]}"
    return f"{flag} {command}".strip()


def install_files(bid, token):
    """Copy the extension for one browser, with its own token file. True if the files changed."""
    dest = folder(bid)
    new = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))["version"]
    try:
        old = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError):
        old = None
    shutil.copytree(SOURCE, dest, dirs_exist_ok=True)
    (dest / "nova.json").write_text(json.dumps({"token": token, "port": PORT, "browser": bid}), encoding="utf-8")
    return old != new


LNK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$job = $env:NOVA_JOB | ConvertFrom-Json
$sh = New-Object -ComObject WScript.Shell
$dirs = @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'),
          "$env:APPDATA\Microsoft\Internet Explorer\Quick Launch",
          [Environment]::GetFolderPath('CommonPrograms'), [Environment]::GetFolderPath('CommonDesktopDirectory'))
$out = @()
foreach ($d in $dirs) {
  if (-not (Test-Path $d)) { continue }
  foreach ($f in Get-ChildItem $d -Filter *.lnk -Recurse -ErrorAction SilentlyContinue) {
    try { $l = $sh.CreateShortcut($f.FullName) } catch { continue }
    if ($l.TargetPath -ne $job.exe) { continue }
    $args = $l.Arguments -replace '\s*--load-extension=("[^"]*"|\S+)', ''
    if ($job.on) { $args = ('--load-extension="' + $job.ext + '" ' + $args).Trim() }
    if ($args -eq $l.Arguments) { $out += "ok|$($f.FullName)"; continue }
    try { $l.Arguments = $args; $l.Save(); $out += "changed|$($f.FullName)" } catch { $out += "skipped|$($f.FullName)" }
  }
}
$out -join "`n"
"""


def set_flag(bid, on):
    """Add (or remove) --load-extension everywhere this browser starts from. Returns {changed, skipped}."""
    import winreg
    path, ext = exe(bid), str(folder(bid))
    report = {"changed": [], "skipped": []}
    if not path:
        return report
    r = subprocess.run(["powershell", "-NoProfile", "-Command", LNK_SCRIPT], capture_output=True, text=True,
                       env=dict(os.environ, NOVA_JOB=json.dumps({"exe": path, "ext": ext, "on": on})),
                       creationflags=0x08000000)
    for line in r.stdout.splitlines():
        kind, _, where = line.partition("|")
        if kind in report:  # "skipped" is a shortcut only an administrator may change
            report[kind].append(where)

    def edit(hive, key, name):
        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
            value = winreg.QueryValueEx(k, name)[0]
            new = with_flag(value, ext, on)
            if new != value:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, new)
                report["changed"].append(f"{key}\\{name or '(default)'}")

    run = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:  # start-at-login entries the browser added for itself
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run) as k:
            names = [winreg.EnumValue(k, i)[0] for i in range(winreg.QueryInfoKey(k)[1])]
        for name in names:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run) as k:
                value = winreg.QueryValueEx(k, name)[0]
            if path.lower() in value.lower():
                edit(winreg.HKEY_CURRENT_USER, run, name)
    except OSError:
        pass
    command = rf"Software\Classes\{BROWSERS[bid][2]}\shell\open\command"  # opening a link from another app
    try:
        edit(winreg.HKEY_CURRENT_USER, command, "")
    except FileNotFoundError:
        if on:  # the browser registered itself machine-wide: add a user-level copy with the flag
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, command) as k:
                    value = winreg.QueryValueEx(k, "")[0]
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command) as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, with_flag(value, ext, True))
                    winreg.SetValueEx(k, "NovaCreated", 0, winreg.REG_SZ, "1")
                report["changed"].append(f"HKCU\\{command}")
            except OSError:
                pass
    except OSError:
        report["skipped"].append(f"HKCU\\{command}")
    if not on:  # remove the user-level copy Nova made, so the machine-wide one applies again
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, command) as k:
                winreg.QueryValueEx(k, "NovaCreated")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, command)
        except OSError:
            pass
    return report


def install(bid, token):
    changed = install_files(bid, token)
    report = set_flag(bid, True) if BROWSERS[bid][3] == "flag" else {"changed": [], "skipped": []}
    return {"files_changed": changed, **report}


def uninstall(bid):
    report = set_flag(bid, False)
    shutil.rmtree(folder(bid), ignore_errors=True)
    return report


def launch(bid):
    path = exe(bid)
    if path:
        subprocess.Popen([path, f"--load-extension={folder(bid)}"], creationflags=0x08000000)


def restart(bid):
    """Close the browser (it restores its tabs) and start it again with the extension."""
    path = exe(bid)
    if path:
        subprocess.run(["taskkill", "/IM", Path(path).name], capture_output=True, creationflags=0x08000000)
        for _ in range(40):
            if not running(bid):
                break
            time.sleep(0.25)
        else:
            subprocess.run(["taskkill", "/F", "/IM", Path(path).name], capture_output=True, creationflags=0x08000000)
            time.sleep(1)
        launch(bid)


# ---------- the live connection ----------
class Bridge:
    """WebSocket server the extensions connect to. Thread-safe: call() and broadcast() work from any thread."""

    def __init__(self, token, enabled, on_panel):
        self.token, self.enabled, self.on_panel = token, list(enabled), on_panel
        self.conns, self.pending, self.next_id = {}, {}, 0
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run, daemon=True).start()

    def _origins(self):
        return [f"chrome-extension://{extension_id(folder(b))}" for b in BROWSERS]

    def _run(self):
        import websockets
        asyncio.set_event_loop(self.loop)

        async def main():
            async with websockets.serve(self._client, "127.0.0.1", PORT, origins=self._origins(), max_size=2 ** 24):
                await asyncio.Future()
        try:
            self.loop.run_until_complete(main())
        except OSError:  # port in use: the browser features are unavailable, Nova itself keeps working
            pass

    async def _client(self, ws):
        bid = None
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if hello.get("type") != "hello" or hello.get("token") != self.token or hello.get("browser") not in BROWSERS:
                return
            origin = ws.request.headers.get("Origin", "")
            if origin != f"chrome-extension://{extension_id(folder(hello['browser']))}":
                return  # an extension from another folder (or a web page) claiming to be Nova's
            bid = hello["browser"]
            self.conns[bid] = ws
            threading.Thread(target=self.on_panel, args=(bid, {"op": "connected"}), daemon=True).start()
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "result" and msg.get("id") in self.pending:
                    future = self.pending.pop(msg["id"])
                    if not future.done():
                        future.set_result(msg)
                elif msg.get("type") == "panel":
                    threading.Thread(target=self.on_panel, args=(bid, msg), daemon=True).start()
        except Exception:
            pass
        finally:
            if bid and self.conns.get(bid) is ws:
                del self.conns[bid]
                threading.Thread(target=self.on_panel, args=(bid, {"op": "connected"}), daemon=True).start()

    def connected(self, bid):
        return bid in self.conns

    def call(self, bid, tool, args, timeout=60):
        async def go():
            self.next_id += 1
            future = self.loop.create_future()
            self.pending[self.next_id] = future
            await self.conns[bid].send(json.dumps({"type": "call", "id": self.next_id, "tool": tool, "args": args}))
            return await asyncio.wait_for(future, timeout)
        reply = asyncio.run_coroutine_threadsafe(go(), self.loop).result(timeout + 5)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error") or "the browser didn't say why")
        return reply.get("result")

    def send(self, bid, msg):
        ws = self.conns.get(bid)
        if ws:
            asyncio.run_coroutine_threadsafe(ws.send(json.dumps(msg, default=str)), self.loop)

    def broadcast(self, event):
        for bid in list(self.conns):
            self.send(bid, {"type": "event", "event": event})

    def ensure(self, bid, wait_s=25):
        """Connected to this browser's extension, starting the browser if it's closed."""
        if self.connected(bid):
            return
        if bid not in self.enabled:
            raise RuntimeError(f"Nova isn't set up for {BROWSERS[bid][0]}. Turn it on in Nova's Settings → Browsers.")
        if not running(bid):  # an open browser ignores the flag, so only a closed one is started
            launch(bid)
        for _ in range(int(wait_s * 4)):
            if self.connected(bid):
                return
            time.sleep(0.25)
        raise RuntimeError(f"{BROWSERS[bid][0]} is open but the Nova extension isn't connected. Restart "
                           f"{BROWSERS[bid][0]} once from Nova's Settings → Browsers so the extension loads.")

    def run_tool(self, bid, tool, args, ask):
        """Run one browser tool for the AI, applying Nova's safety rules to the real page element."""
        self.ensure(bid)
        element = self.call(bid, "inspect", {"ref": args["ref"], "tab_id": args.get("tab_id")}) \
            if tool in ("click", "type", "select") and args.get("ref") is not None else None
        verdict, why = classify(tool, args, element)
        if verdict == "block":
            raise PermissionError(f"Blocked by Nova: this {why}. Don't try another way; tell the user.")
        if verdict == "confirm":
            summary = json.dumps({k: v for k, v in args.items() if k != "tab_id"})[:300]
            where = (element or {}).get("url") or ""
            if not ask({"tool": f"browser.{tool}", "reason": why, "summary": f"{BROWSERS[bid][0]}: {summary}\n{where}"}):
                raise PermissionError(f"The user didn't allow this ({why}). Don't try another way; ask them.")
        return self.call(bid, tool, args)
