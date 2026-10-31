"""Nova in your real browsers (Opera GX, Brave, …) through a small unpacked extension.

The extension (browser/extension) connects to this bridge over a WebSocket on 127.0.0.1, proving itself with
its exact extension origin and a per-install token. Claude Code and Codex reach the browser through the local
MCP server helpers/browser_mcp.py, which asks Nova to run each tool. Nova, not the AI, decides what is safe:
reading and navigating are allowed, submitting/buying/posting/sending need your OK, and typing passwords,
card numbers or one-time codes is blocked. Page text is untrusted data.

Install: the extension is copied to %LOCALAPPDATA%/Nova/browser/<browser> and `--load-extension=<that folder>`
is added to the browser's user-level shortcuts, taskbar pin, start-at-login entry and link-open command.
On a Mac the copy lives in ~/Library/Application Support/Nova/browser/<browser>, and Nova starts the browser with
the flag itself (macOS has no per-app shortcut to edit).
"""
import asyncio
import hashlib
import json
import os
import plistlib
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from core.config import NO_WINDOW, write_private
from guard.guard import PLAN, with_mode

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "browser" / "extension"
MAC = sys.platform == "darwin"
HOME = Path.home() / "Library" / "Application Support" / "Nova" / "browser" if MAC else \
    Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Nova" / "browser"
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
# on a Mac the candidates are app bundles (exe() finds the program inside); no ProgId
MAC_BROWSERS = {bid: (name, [f"{d}/{app}.app" for d in ("/Applications", Path.home() / "Applications")], None, method,
                      ticked)
                for bid, name, app, method, ticked in [
                    ("opera-gx", "Opera GX", "Opera GX", "flag", True), ("brave", "Brave", "Brave Browser", "flag", True),
                    ("opera", "Opera", "Opera", "flag", False), ("vivaldi", "Vivaldi", "Vivaldi", "flag", False),
                    ("edge", "Microsoft Edge", "Microsoft Edge", "guided", False),
                    ("chrome", "Google Chrome", "Google Chrome", "guided", False),
                    # Arc: not known to honour --load-extension, so the one-time step that works in any Chromium
                    ("arc", "Arc", "Arc", "guided", False),
                    # Safari can't load this extension: read, navigate and tabs only, through AppleScript (below)
                    ("safari", "Safari", "Safari", "applescript", False)]}
if MAC:
    BROWSERS = MAC_BROWSERS
SPOKEN = {k: v for k, v in {"opera gx": "opera-gx", "operagx": "opera-gx", "oprah gx": "opera-gx", "opera g x": "opera-gx", "brave": "brave", "opera": "opera", "vivaldi": "vivaldi",
          "edge": "edge", "microsoft edge": "edge", "chrome": "chrome", "google chrome": "chrome", "arc": "arc",
                            "safari": "safari"}.items()
          if v in BROWSERS}
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
# a page's own words can't be trusted to say "this buys something": the address of a payment or checkout page can
PAY_HOST = re.compile(r"(?:^|[.-])(?:checkout|pay|payment|payments|billing|buy|cart|secure)(?:[.-]|$)|paypal|stripe|"
                      r"razorpay|paytm|braintree", re.I)
SCRIPT_URL = re.compile(r"^\s*(?:javascript|data|file|blob|vbscript):", re.I)  # run code, or read this computer's files
MAX_SCRIPT = 600  # a longer script can't be read through on a card


def classify(tool, args, element=None, mode="accept_edits", trusted=True):
    """('allow' | 'confirm' | 'block', why) for one browser action. `element` is what the extension reports
    about the real element on the page (not what the AI says it is). `mode` is the permission mode: Plan only
    reads, Manual also asks before typing or picking, Bypass never asks; blocked typing stays blocked.
    `trusted` False: the element report came from the page's own JavaScript (Safari), which the page could fake,
    so every click, type and pick asks."""
    tier, why = _classify(tool, args, element)
    # ...except a search: a page faking a search box could only get a search's text submitted to itself
    if not trusted and tier == "allow" and tool in ("click", "type", "select") and why != "searches":
        tier, why = "confirm", f"{why} in Safari, where Nova can't check the page element for itself"
    if tier == "allow" and mode == "plan" and tool not in ("tabs", "navigate", "read", "inspect", "scroll", "screenshot"):
        return "block", PLAN
    if tier == "allow" and mode == "manual" and tool in ("type", "select"):
        return "confirm", f"{why} (Manual mode asks before every change)"
    return with_mode(tier, why, mode, unfamiliar=False)


def _search_box(el):
    """The element is a site's search box (YouTube, Spotify, …): submitting what's typed there only searches."""
    return el.get("type") == "search" or el.get("search") or \
        bool(SEARCH.search(f'{el.get("field", "")} {el.get("name", "")}'))


def _classify(tool, args, element=None):
    el = element or {}
    what = f'"{el.get("name") or el.get("field") or "an element"}" on {el.get("host") or "the page"}'
    if tool in ("tabs", "navigate"):
        url = str(args.get("url") or "")
        if SCRIPT_URL.match(url):
            return "block", "opens a script or a file on this computer instead of a web page"
        parts = urllib.parse.urlsplit(url)
        # shortcut: a short query (a search) still passes; text in the address is how a page could be handed data
        if url and (parts.scheme not in ("http", "https") and url != "about:blank"):
            return "confirm", f"opens {url[:80]}, which isn't a web address"
        if len(parts.query) + len(parts.fragment) > 40 or len(url) > 300:
            return "confirm", "opens a web address that carries a lot of text, which is how data is handed to a site"
        return "allow", "reads or moves around"
    if tool in ("read", "inspect", "scroll", "screenshot"):
        return "allow", "reads or moves around"
    if tool == "type":
        field = f'{el.get("type", "")} {el.get("field", "")} {el.get("name", "")}'
        if el.get("type") == "password" or SECRET_AUTOCOMPLETE.search(el.get("autocomplete", "")) or \
                SECRET_FIELD.search(field) or CARD_DIGITS.match(str(args.get("text", ""))):
            return "block", f"types into a password, card or one-time-code field ({what}); you do that yourself"
        if _search_box(el):
            return "allow", "searches"
        if args.get("submit"):
            return "confirm", f"types into {what} and submits the form"
        return "allow", "types into a field"
    if tool == "click":
        if el.get("isSubmit") or el.get("formSecret") or PAY_HOST.search(el.get("host", "")) or \
                RISKY.search(el.get("name", "")):
            return "confirm", f"clicks {what}, which may submit, buy, post or send something"
        return "allow", "clicks"
    if tool == "select":
        return "allow", "picks from a dropdown"
    if tool == "press":
        if args.get("key") in ("Enter", "\r", "\n") and el.get("tag") in ("input", "textarea") and _search_box(el):
            return "allow", "searches"  # Enter in the focused search box (Nova checked which element has focus)
        if args.get("key") in ("Enter", "Space", " ", "\r", "\n"):  # on a focused button these click it
            return "confirm", f"presses {args['key']!r}, which may submit a form or click a button"
        return "allow", "presses a key"
    if tool == "download":
        if args.get("filename") and not re.fullmatch(r"[\w. -]{1,100}", str(args["filename"])):
            return "block", "gives the download a file name with folders or odd characters in it"
        return "confirm", f"downloads {str(args.get('url', ''))[:120]}"
    if tool == "script":
        if len(str(args.get("code", ""))) > MAX_SCRIPT:
            return "block", f"runs a script of more than {MAX_SCRIPT} characters, too long to read through on a card"
        return "confirm", "runs a script inside the page"
    return "confirm", f"unknown browser tool {tool}"


# ---------- install ----------
def extension_id(folder):
    """Chromium's ID for an unpacked extension: SHA-256 of its folder path, first 32 hex digits as a-p."""
    # the path's bytes as Chromium stores them: UTF-16 on Windows, UTF-8 elsewhere
    digest = hashlib.sha256(str(folder).encode("utf-8" if MAC else "utf-16-le")).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def folder(bid):
    return HOME / bid


def app_binary(app):
    """The program inside a macOS app bundle, named by its Info.plist (None if it isn't a usable app)."""
    try:
        name = plistlib.loads((Path(app) / "Contents" / "Info.plist").read_bytes())["CFBundleExecutable"]
    except (OSError, ValueError, KeyError):
        return None
    return str(Path(app) / "Contents" / "MacOS" / name)


def exe(bid):
    paths = (app_binary(p) for p in BROWSERS[bid][1]) if MAC else BROWSERS[bid][1]
    return next((p for p in paths if p and Path(p).exists()), None)


def detect():
    """Installed browsers, for the Browsers step."""
    out = []
    for bid, (name, _, _, method, ticked) in BROWSERS.items():
        path = exe(bid)
        if path:
            out.append({"id": bid, "name": name, "method": method, "default_ticked": ticked, "running": running(bid),
                        "ready": method == "applescript" and safari_ready()})
    return out


def running(bid):
    path = exe(bid)
    if not path:
        return False
    if MAC:  # the main program only: helpers live elsewhere in the bundle
        return subprocess.run(["pgrep", "-f", path], capture_output=True).returncode == 0
    return bool(_pids(path))


def _pids(path):
    """Windows: the processes running this exact program (Opera and Opera GX are both opera.exe)."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Process -Name $env:NOVA_NAME -ErrorAction "
                        "SilentlyContinue | Where-Object Path -eq $env:NOVA_EXE).Id"], capture_output=True, text=True,
                       env=dict(os.environ, NOVA_NAME=Path(path).stem, NOVA_EXE=str(path)), creationflags=NO_WINDOW)
    return r.stdout.split()


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
    write_private((dest / "nova.json"), json.dumps({"token": token, "port": PORT, "browser": bid}))
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
    path, ext = exe(bid), str(folder(bid))
    report = {"changed": [], "skipped": []}
    # shortcut: on a Mac only a launch by Nova (launch/restart/ensure) carries the flag; a Dock launch doesn't, until
    # Nova restarts it. Upgrade if users hit that often (e.g. a small launcher app that adds the flag).
    if not path or MAC:
        return report
    import winreg
    r = subprocess.run(["powershell", "-NoProfile", "-Command", LNK_SCRIPT], capture_output=True, text=True,
                       env=dict(os.environ, NOVA_JOB=json.dumps({"exe": path, "ext": ext, "on": on})),
                       creationflags=NO_WINDOW)
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
    if BROWSERS[bid][3] == "applescript":  # nothing to copy: Nova talks to Safari directly
        return {"files_changed": False, "changed": [], "skipped": []}
    changed = install_files(bid, token)
    report = set_flag(bid, True) if BROWSERS[bid][3] == "flag" else {"changed": [], "skipped": []}
    return {"files_changed": changed, **report}


def uninstall(bid):
    report = set_flag(bid, False)
    shutil.rmtree(folder(bid), ignore_errors=True)
    return report


def launch(bid):
    path = exe(bid)
    if path and BROWSERS[bid][3] == "applescript":
        subprocess.Popen(["open", "-a", str(Path(path).parents[2])])
    elif path:
        subprocess.Popen([path, f"--load-extension={folder(bid)}"], creationflags=NO_WINDOW, start_new_session=MAC)


def restart(bid):
    """Close the browser (it restores its tabs) and start it again with the extension."""
    path = exe(bid)
    if path:
        pids = [] if MAC else [arg for pid in _pids(path) for arg in ("/PID", pid)]  # this browser's own processes
        subprocess.run(["osascript", "-e", f'quit app "{Path(path).parents[2].stem}"'] if MAC else
                       ["taskkill", *pids], capture_output=True, creationflags=NO_WINDOW)
        for _ in range(40):
            if not running(bid):
                break
            time.sleep(0.25)
        else:
            subprocess.run(["pkill", "-9", "-f", path] if MAC else ["taskkill", "/F", *pids], capture_output=True,
                           creationflags=NO_WINDOW)
            time.sleep(1)
        launch(bid)


# ---------- Safari (macOS): the extension's page functions through AppleScript ----------
# Safari can't run this extension (it needs an Xcode-built, signed app and has no chrome.debugger), so Nova drives
# it with AppleScript and runs the extension's own page functions with `do JavaScript`. Those run in the page's
# world, where the page could fake what an element is, so clicks, typing and picks always ask (see classify).
# Pressing keys and scripts need chrome.debugger, and screenshots captureVisibleTab: those stay off.
SAFARI_STEPS = ("Safari isn't letting Nova in yet. In Safari: Settings › Advanced, tick “Show features for web "
                "developers” (on Safari 16: “Show Develop menu in menu bar”); then tick “Allow JavaScript from Apple "
                "Events” in Settings › Developer (on Safari 16: the Develop menu) and confirm with your password or "
                "Touch ID. If macOS asks whether Nova may control Safari, click OK.")
SAFARI_ONLY = ("Nova can't press keys, take screenshots, download or run scripts in Safari. Use read, click, type, "
               "select or scroll, or tell the user to do that step themselves or use another browser set up in Nova.")
# tool → the extension's function that does it inside the page (background.js), and its arguments
PAGE = {"read": ("readPage", lambda a, ref: [a.get("mode", "outline")]),
        "inspect": ("elementInfo", lambda a, ref: [ref]), "click": ("clickElement", lambda a, ref: [ref]),
        "type": ("typeInto", lambda a, ref: [ref, str(a.get("text", "")), bool(a.get("submit"))]),
        "select": ("selectOption", lambda a, ref: [ref, str(a.get("value", ""))]),
        "scroll": ("scrollPage", lambda a, ref: [a.get("direction", "down"), ref])}
SAFARI_TABS = '''set sep to tab
set out to {}
tell application "Safari"
  repeat with w in (every window where its document is not missing value)
    try
      set wid to id of w
      set ct to index of current tab of w
      repeat with t in tabs of w
        set end of out to (wid as text) & sep & (index of t as text) & sep & ((index of t = ct) as text) & sep & ¬
          (URL of t as text) & sep & (name of t as text)
      end repeat
    end try
  end repeat
end tell
set AppleScript's text item delimiters to linefeed
return out as text'''

# a new tab, in the front browser window (a new window if there's none); about:blank, not the Start Page, so
# JavaScript runs in it right away
SAFARI_OPEN = '''on run argv
tell application "Safari"
  activate
  set wins to every window where its document is not missing value
  if (count of wins) = 0 then
    make new document with properties {URL:(item 1 of argv)}
    set w to item 1 of (every window where its document is not missing value)
  else
    set w to item 1 of wins
    tell w to set current tab to (make new tab with properties {URL:(item 1 of argv)})
  end if
  return ((id of w) as text) & " " & (index of current tab of w as text)
end tell
end run'''


def _osa(script, *args):
    r = subprocess.run(["osascript", "-e", script, *map(str, args)], capture_output=True, text=True, timeout=30)
    if r.returncode:
        err = r.stderr.strip()
        if "Apple Events" in err or "-1743" in err:  # the Develop setting is off, or macOS's Automation prompt was denied
            raise RuntimeError(SAFARI_STEPS)
        raise RuntimeError(err or "Safari didn't answer")
    return r.stdout.rstrip("\n")


def _safari_tab(tab_id):
    """AppleScript for one tab. Nova's tab id is the window's id × 1000 + the tab's position in it."""
    return f"tab {int(tab_id) % 1000} of window id {int(tab_id) // 1000}" if tab_id else "front document"


def _safari_js(where, code):
    return _osa(f'on run argv\ntell application "Safari" to do JavaScript (item 1 of argv) in {where}\nend run', code)


def _web_address(url):
    if not re.match(r"https?://|about:blank$", url or "", re.I):  # no javascript: or file: through "navigate"
        raise RuntimeError(f"Safari: Nova only opens http(s) addresses, not {str(url)[:80]!r}.")
    return url


def safari_tabs():
    tabs = []
    for line in filter(None, _osa(SAFARI_TABS).split("\n")):
        wid, idx, active, url, title = (line.split("\t", 4) + [""] * 5)[:5]
        url = "" if url == "missing value" else url  # a Start Page tab has no address
        tabs.append({"id": int(wid) * 1000 + int(idx), "title": title, "url": url, "active": active == "true",
                     "window": int(wid)})
    return tabs


def safari_ready():
    """Safari is open and runs JavaScript from Nova (its "Allow JavaScript from Apple Events" is on)."""
    try:
        return running("safari") and _safari_js("front document", "1") == "1"
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return False


def safari_call(tool, args):
    """One browser tool in Safari, in the same shape the extension answers with."""
    where = _safari_tab(args.get("tab_id"))

    def settle(where):
        time.sleep(0.3)
        for _ in range(60):  # up to 15 s, like the extension
            try:
                if _safari_js(where, "document.readyState") == "complete":
                    break
            except RuntimeError:
                pass
            time.sleep(0.25)
        return json.loads(_safari_js(where, "JSON.stringify({title: document.title, url: location.href})"))

    if tool in PAGE:
        name, make = PAGE[tool]
        source = (SOURCE / "background.js").read_text(encoding="utf-8")
        fn = re.search(rf"^function {name}\(.*?^\}}\r?$", source, re.S | re.M).group(0)
        ref = None if args.get("ref") is None else str(args["ref"])
        params = ", ".join(json.dumps(x) for x in make(args, ref))
        result = json.loads(_safari_js(where, f"JSON.stringify(({fn})({params}))"))
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(result["error"])
        if tool == "click":  # it may have opened another page
            settle(where)
        return result
    if tool == "navigate":
        action = args.get("action", "go")
        if action == "go":
            _osa(f'on run argv\ntell application "Safari" to set URL of {where} to (item 1 of argv)\nend run',
                 _web_address(args.get("url")))
        elif action in ("back", "forward", "reload"):
            _safari_js(where, {"back": "history.back()", "forward": "history.forward()",
                               "reload": "location.reload()"}[action])
        else:
            raise RuntimeError(f"Unknown navigate action {action}")
        return {"id": args.get("tab_id"), **settle(where)}
    if tool == "tabs":
        action = args.get("action", "list")
        if action == "list":
            return safari_tabs()
        if action == "open":
            wid, idx = _osa(SAFARI_OPEN, _web_address(args.get("url") or "about:blank")).split()
            tab_id = int(wid) * 1000 + int(idx)
            return {"id": tab_id, **settle(_safari_tab(tab_id))}
        if action == "switch":
            tab_id = int(args["tab_id"])
            _osa(f'tell application "Safari"\nactivate\nset current tab of window id {tab_id // 1000} to '
                 f'{_safari_tab(tab_id)}\nset index of window id {tab_id // 1000} to 1\nend tell')
            return {"id": tab_id, **settle(_safari_tab(tab_id))}
        if action == "close":
            ids = args.get("tab_ids") or [args["tab_id"]]
            for tab_id in sorted(map(int, ids), reverse=True):  # the last first, so the others keep their positions
                _osa(f'tell application "Safari" to close {_safari_tab(tab_id)}')
            return "closed"
        raise RuntimeError(f"Safari can't {action} tabs.")
    raise RuntimeError(SAFARI_ONLY)


# ---------- the live connection ----------
class Bridge:
    """WebSocket server the extensions connect to. Thread-safe: call() and broadcast() work from any thread."""

    def __init__(self, token, enabled, on_panel):
        self.token, self.enabled, self.on_panel = token, list(enabled), on_panel
        self.conns, self.pending, self.next_id = {}, {}, 0
        self.ready = set()  # browsers Nova drives without the extension (Safari) that answered last time
        self.read_pages = set()  # (browser, tab) the AI read since it last changed a page there (see run_tool)
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
            if (hello.get("type") != "hello" or hello.get("browser") not in BROWSERS
                    or not secrets.compare_digest(str(hello.get("token", "")).encode(), self.token.encode())):
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
        return bid in self.conns or bid in self.ready

    def call(self, bid, tool, args, timeout=60):
        if BROWSERS[bid][3] == "applescript":
            try:
                result = safari_call(tool, args)
            except RuntimeError as e:
                if str(e) == SAFARI_STEPS:
                    self.ready.discard(bid)
                raise
            self.ready.add(bid)
            return result
        async def go():
            self.next_id += 1
            cid, future = self.next_id, self.loop.create_future()
            self.pending[cid] = future
            try:
                await self.conns[bid].send(json.dumps({"type": "call", "id": cid, "tool": tool, "args": args}))
                return await asyncio.wait_for(future, timeout)
            finally:  # no answer (the browser closed mid-action): don't keep its slot
                self.pending.pop(cid, None)
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

    def ensure(self, bid, wait_s=35):
        """Connected to this browser's extension, starting the browser if it's closed."""
        # 35 s: a browser that put the extension to sleep wakes it within one 30 s alarm
        if bid in self.ready and not running(bid):  # Safari was quit: open it and check it again below
            self.ready.discard(bid)
        if self.connected(bid):
            return
        if bid not in self.enabled:
            raise RuntimeError(f"Nova isn't set up for {BROWSERS[bid][0]}. Turn it on in Nova's Settings → Browsers.")
        if BROWSERS[bid][3] == "applescript":
            if not running(bid):
                launch(bid)
            for _ in range(40):  # Safari opens its window within a few seconds
                if safari_ready():
                    self.ready.add(bid)
                    return
                time.sleep(0.25)
            raise RuntimeError(SAFARI_STEPS)
        if not running(bid):  # an open browser ignores the flag, so only a closed one is started
            launch(bid)
        for _ in range(int(wait_s * 4)):
            if self.connected(bid):
                return
            time.sleep(0.25)
        raise RuntimeError(f"{BROWSERS[bid][0]} is open but the Nova extension isn't connected. Restart "
                           f"{BROWSERS[bid][0]} once from Nova's Settings → Browsers so the extension loads.")

    def run_tool(self, bid, tool, args, ask, mode="accept_edits"):
        """Run one browser tool for the AI, applying Nova's safety rules to the real page element."""
        self.ensure(bid)
        element = self.call(bid, "inspect", {"ref": args["ref"], "tab_id": args.get("tab_id")}) \
            if tool in ("click", "type", "select") and args.get("ref") is not None else None
        if tool == "press" and args.get("key") in ("Enter", "\r", "\n") and BROWSERS[bid][3] != "applescript":
            try:  # the element that has focus, which decides what Enter does
                element = self.call(bid, "inspect", {"ref": "", "tab_id": args.get("tab_id")})
            except RuntimeError:
                element = None
        verdict, why = classify(tool, args, element, mode, trusted=BROWSERS[bid][3] != "applescript")
        if verdict == "block" and why == PLAN:
            raise PermissionError(PLAN)
        if verdict == "block":
            raise PermissionError(f"Blocked by Nova: this {why}. Don't try another way; tell the user.")
        if verdict == "confirm" and tool == "script" and (bid, args.get("tab_id")) not in self.read_pages:
            # a script needs the user's OK every time, and is usually a shortcut past read + click: send the AI
            # there first instead of interrupting the user
            raise PermissionError("Read the page first (read with mode=outline), then use click, type, select or "
                                  "press with a [ref], and read or screenshot to check the result. Those don't need "
                                  "the user's OK; a script does. Use script only if those can't do it.")
        if verdict == "confirm":
            summary = json.dumps({k: v for k, v in args.items() if k != "tab_id"})[:900 if tool == "script" else 300]
            where = (element or {}).get("url") or ""
            if not ask({"tool": f"browser.{tool}", "reason": why, "summary": f"{BROWSERS[bid][0]}: {summary}\n{where}"}):
                raise PermissionError(f"The user didn't allow this ({why}). Don't try another way; ask them.")
        result = self.call(bid, tool, args)
        if tool == "read":
            self.read_pages.add((bid, args.get("tab_id")))
        elif tool not in ("screenshot", "scroll", "inspect") and args.get("action") != "list":
            # may show another page, in that tab or (a click opening a tab) another: every tab of it reads again
            self.read_pages = {page for page in self.read_pages if page[0] != bid}
        return result
