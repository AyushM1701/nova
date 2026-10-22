"""PreToolUse hook for Claude Code and Codex: sorts every tool call into allow / confirm / block.

Block wins over confirm, confirm over allow, and anything unrecognised is confirm, never allow.
Confirm asks Nova over an authenticated local pipe; no answer (or Nova not running) means deny.
Stdlib only, so it runs under any Python.
"""
import json
import os
import re
import sys
import time
from multiprocessing.connection import Client

UNTIL_END = r"[^;|&\n]*"  # rest of the current command segment
SECRETS = (r"login data|logins\.json|key4\.db|web data|cookies\.sqlite|[\\/]network[\\/]cookies|local state"
           r"|library/keychains|cookies\.binarycookies"
           # browser profiles (Chrome, Edge, Brave: "User Data"; Firefox: "Profiles") hold saved passwords
           r"|user data[\\/]|firefox[\\/]profiles"
           # whole key folders, so "cat ~/.ssh/*" or a Grep of the folder can't get round a file name (a named .pub is fine)
           r"|(?:^|[\\/\s\"'=:])\.(?:ssh(?![\\/][\w.-]+\.pub\b)|aws|kube|docker|gnupg)\b"
           # ...and the key files by name, wherever a wildcard put them ("~\*\id_ed25519", "~\*\credentials")
           r"|\bid_(?:rsa|ecdsa|ed25519|dsa)\b(?!\.pub)|[\\/*]credentials(?:$|[\s\"'*;|)])"
           # Nova's own keys, and the browser extension's copy of its token (%LOCALAPPDATA%\Nova\browser\..., and
           # ~/Library/Application Support/Nova/browser/... on a Mac)
           r"|fallback\.key|deepgram\.key|stt-\w+\.key|calendar\.key|browser-token|events\.key|phone-token"
           r"|(?:appdata[\\/]local|localappdata%?|application support)[\\/]nova\b"
           # other tools' saved logins: git, package registries, and the AI CLIs themselves
           r"|\.git-credentials|\.netrc\b|\.npmrc|\.pypirc|gh[\\/]hosts\.yml|\.claude[\\/]\.credentials"
           r"|\.codex[\\/]auth\.json")
NOVA_DATA = "reads Nova's own keys"
# the home folder, all users' folders or a whole drive: a search through one of these goes into .ssh, .aws and the
# browser profiles too, which the rules above can only see when they are named
WIDE = (r"(?:~|\$home|\$env:userprofile|%userprofile%|[a-z]:(?:[\\/]users(?:[\\/][^\\/\s\"';|&,)]+)?)?"
        r"|/(?:users|home)(?:/[^/\s\"';|&,)]+)?|/)[\\/]?\*?(?=$|[\s\"';|&,)])")
RECURSIVE = (r"\b(?:rg|ag|find|tree)\b|\b(?:grep|ls)\b[^;|&\n]*\s-(?:-recursive\b|[a-z]*r)|-recurse\b|\s-r\b"
             r"|\s/s\b")
WIDE_WHY = "searches your whole home folder or drive, where your keys are"
NOVA_SEARCH_WHY = "searches Nova's own folder, where Nova's keys are"
DELETE = r"(\b(rm|del|erase|rd|rmdir|remove-item|ri)\b|(\.|::)delete\w*)"

BLOCK = [
    (r"\bformat(\.com)?\s+[a-z]:|\bdiskpart\b|\bbcdedit\b|\bcipher\s+/w|\bvssadmin\s+delete|\bwbadmin\s+delete"
     r"|clear-disk|initialize-disk|format-volume", "wipes a disk or the boot configuration"),
    # ...also through .NET or COM ([IO.Directory]::Delete("C:\Windows", $true), $fso.DeleteFolder($HOME))
    (DELETE + UNTIL_END +
     r"([\s(,][\"']?[a-z]:[\\/]?[\"']?(\s|$|\*|\)|,)|\s/(\s|$|\*)|[\s(,]~[\\/]?(\s|$|\)|,)"
     r"|[\s(,][\"']?\$(home|env:userprofile)[\\/]?[\"']?(\s|$|\)|,)|\\windows\b|system32|program files|programdata"
     r"|\$env:(windir|systemroot|programfiles)|%(windir|systemroot)%"
     r"|\s/(system|library|applications|users|usr|bin|sbin|etc|private|volumes)/?[\"']?(\s|$|\*))",
     "deletes system folders or a whole drive"),
    (r"\bdiskutil\s+(erase\w*|partition\w*|zero\w*|secureerase|reformat)|\bcsrutil\s+disable|\bspctl\s+--master-disable"
     r"|\bsecurity\s+(find|dump|export|delete)-|\bdscl\b|\bsysadminctl\b|\bfdesetup\s+disable",
     "changes disks, macOS security settings, accounts or the keychain"),
    (r"set-mppreference" + UNTIL_END + r"-disable|add-mppreference" + UNTIL_END + r"-exclusion"
     r"|netsh\s+(adv)?firewall" + UNTIL_END + r"\b(off|disable)|set-netfirewallprofile" + UNTIL_END +
     r"-enabled\s+(\$?false|0)|(stop|set|disable|sc(\.exe)?\s+(stop|config|delete))" + UNTIL_END +
     r"\b(windefend|mpssvc)\b", "disables Defender or the firewall"),
    (r"\bnet\s+(user|localgroup)\b|(new|set|remove|disable|enable)-localuser|add-localgroupmember"
     r"|\bcmdkey\b|\bvaultcmd\b", "changes user accounts or reads saved credentials"),
    (SECRETS, "reads browser or SSH secrets"),
    (r"(iwr|irm|invoke-webrequest|invoke-restmethod|curl|wget|downloadstring|downloadfile)[^\n]*\|\s*"
     r"(iex|invoke-expression|sh|bash|zsh|python3?|py|pwsh|powershell|cmd)\b"
     r"|\b(iex|invoke-expression)[\s(][^\n]*(iwr|irm|invoke-|downloadstring|net\.webclient)",
     "runs code downloaded from the internet"),
    (r"reg(\.exe)?\s+delete\s+hk(lm|ey_local_machine)|remove-item" + UNTIL_END + r"hklm:",
     "deletes machine-wide registry keys"),
]

CONFIRM = [
    (r"\b(rm|del|erase|rd|rmdir|remove-item|ri|move-item|mi|mv|move|ren|rename-item|clear-content|clc|shred|unlink"
     r"|clear-recyclebin|rimraf|truncate)\b"
     r"|\s-(delete|exec|execdir)\b", "deletes or moves files"),
    (r"\bgit\s+(push|reset\s+--hard|clean|rebase|checkout\s+(--|\.)|restore|branch\s+-d|stash\s+(drop|clear)"
     r"|filter-branch|commit\s+--amend)", "rewrites or publishes git history"),
    (r"\b(vercel|netlify|firebase\s+deploy|npm\s+publish|docker\s+push|kubectl|terraform\s+apply"
     r"|gh\s+(pr|release|repo|issue)\s+(create|merge|delete|close|comment))\b", "deploys or publishes"),
    (r"\b(pip3?|uv|pipx|npm|pnpm|yarn|winget|choco|scoop|cargo|gem|go|brew|port)\s+(install|i|add|uninstall|remove|upgrade"
     r"|update|un|rm)\b|\b(install-module|install-package|add-appxpackage|msiexec)\b|\buninstall-\w+",
     "installs or removes software"),
    (r"\b(stop-process|spps|taskkill|kill|pkill|killall)\b|\.kill\s*\(", "closes a program"),
    (r"\bsudo\b|administrator privileges", "runs as administrator"),
    (r"\b(launchctl|pmset|networksetup|scutil|chmod|chown|chflags|xattr)\b|\bdefaults\s+(write|delete)\b",
     "changes system configuration"),
    (r"\bosascript\b[^\n]*(do shell script|keystroke|key code)", "scripts other apps or types keystrokes"),
    # AppleScript that deletes, sends mail/messages or runs page scripts ("tell Finder to delete every item")
    (r"\bosascript\b[^\n]*\b(delete|empty|move|duplicate|erase|eject|send|do javascript|run script|shut down"
     r"|restart|log out)\b", "lets an app delete, move or send something"),
    (r"\bopen\s" + UNTIL_END + r"\.(pkg|dmg|command|sh|mpkg)\b", "opens an installer or script"),
    (r"\b(shutdown|restart-computer|stop-computer|logoff)\b", "shuts down or restarts the laptop"),
    (r"\breg(\.exe)?\s+(add|delete|import|load)\b|\b(new-itemproperty|remove-itemproperty)\b"
     r"|\bset-itemproperty\b(?!" + UNTIL_END + r"\\themes\\personalize)", "changes the registry"),
    (r"-method\s+(post|put|patch|delete)|\bcurl\b" + UNTIL_END +
     r"\s(-d|--data\S*|-f|--form|-t|--upload-file|-x\s*(post|put|patch|delete))\b"
     r"|\b(scp|sftp|ftp|rsync|send-mailmessage)\b", "sends data over the network"),
    (r"\bcurl\b" + UNTIL_END + r"\s(-o|--output|--remote-name\S*|--config)\b", "downloads a file"),
    (r"\b(set-executionpolicy|schtasks|register-scheduledtask|new-service)\b|\bsc(\.exe)?\s+(create|config|delete)\b",
     "changes system configuration"),
    (r"\s-enc(odedcommand)?\b|frombase64string", "runs an encoded command"),
    (r"&\s*[\$\"']|(^|[;|&\s])\.\s+\$|\binvoke-expression\b|\biex\b|\binvoke-command\b|\bicm\b|\beval\b",
     "runs a dynamically built command"),
    # [Type]::Delete( too, and names with any ending (.DeleteFolder, .CopyFile); start, stop and run stay exact
    (r"(\.|::)(delete\w*|kill|move\w*|copy\w*|terminate\w*|invoke|run|exec\w*|create\w*|stop|start|close|clear\w*"
     r"|write\w*|set\w*|rmtree|unlink|remove\w*|download\w*|upload\w*)\s*\(",
     "calls a method that changes things"),
    (r"\b(start-process|start|saps)\s+[\"']?(powershell|pwsh|cmd|wscript|cscript|mshta|regsvr32|python|py|node|bash"
     r"|wsl)\b|-verb\s+runas", "starts a shell or an elevated process"),
    (r"\b(start-process|start|saps|invoke-item|ii|explorer(\.exe)?)\s" + UNTIL_END +
     r"(\.(ps1|bat|cmd|vbs|vbe|js|jse|wsf|msi|scr|hta|py|pyw|jar|reg|cpl)\b|\\(downloads|temp)\\)",
     "runs a script or a downloaded file"),
    # -ArgumentList (any prefix, e.g. -Args, -a) hides "git push" or "winget install" from the rules above
    # (except plain editors that only open a file: "Start-Process notepad -ArgumentList notes.txt")
    (r"\b(start-process|saps|start)\s+(?!(-filepath\s+)?[\"']?(notepad|mspaint|wordpad|write)(\.exe)?[\"']?\s)"
     + UNTIL_END +
     r"\s-a\w*\b|\bopen\s" + UNTIL_END + r"\s--args\b",
     "starts a program with arguments"),
    (r"\b(out-file|set-content|sc|add-content|ac|tee-object|tee|copy-item|cp|cpi|copy|xcopy|robocopy|ni)\b"
     r"|\bnew-item\b(?!\s+-itemtype\s+directory)", "writes files outside the edit tools"),
]

# every segment of a command must start like one of these to be allowed without asking
ALLOW = [
    r"(get-\w+|gci|gc|gi|gps|ls|dir|cat|type|echo|printf|write-output|write-host|pwd|cd|set-location|sl"
    r"|push-location|pop-location|where(\.exe)?|which|select-string|sls|findstr|measure-object|measure|sort-object"
    r"|sort|select-object|select|format-\w+|ft|fl|out-string|out-host|test-path|resolve-path|split-path|join-path"
    r"|convertto-json|convertfrom-json|out-null|whoami|hostname|date|tree|head|tail|wc|grep|rg|find|true|exit|mkdir|md"
    r"|new-item\s+-itemtype\s+directory|foreach-object|%|where-object|\?)(\s|$)",
    r"(start-process|start|saps|explorer(\.exe)?|invoke-item|ii)(\s|$)",
    r"(nohup\s+)?(notepad|mspaint|wordpad|write)(\.exe)?(\s|$)",  # editors that only open a file to show it
    r"(open|say|osascript|mdfind|mdls|pbpaste|pbcopy|sw_vers|uname|afplay|defaults\s+read)(\s|$)",  # macOS
    r"(set-clipboard|scb|get-clipboard|gcb)(\s|$)",  # putting text on the clipboard (pbcopy's Windows twin)
    r"sed\s+-n\s+\d+(,\d+)?p(\s|$)",  # printing lines 340-420 of a file; sed -i (editing) isn't allowed
    r"git\s+(status|diff|log|show|add|commit|branch|fetch|pull|switch|checkout|stash|remote|rev-parse|ls-files"
    r"|blame|grep|tag)(\s|$)",
    r"(npm|pnpm|yarn)\s+(test|run|start|ls|list|outdated)(\s|$)",
    r"(pytest|python\s+-m\s+pytest|py\s+-m\s+pytest|npx\s+(jest|vitest|tsc|playwright\s+test))(\s|$)",
    r"rundll32(\.exe)?\s+user32\.dll,\s*lockworkstation$",
    r"new-object\s+-comobject\s+wscript\.shell$", r"\.(sendkeys|wmisetbrightness)$",
    r"\.\w+$",  # reading a property, e.g. (Get-Date).DayOfWeek; risky method calls were caught by CONFIRM
    r"invoke-cimmethod\s+-methodname\s+wmisetbrightness(\s|$)",
    r"set-itemproperty\s" + UNTIL_END + r"\\themes\\personalize\b",
    r"\[char\]\s*\d+$", r"[\d\s,.]+$", r"[@$]?$", r"[\w$]+\s*=\s*[\w.\-]*$",
    r"(if|elseif|else|!)$",  # PowerShell's if (...) {...}: its condition and body are checked as their own segments
    r"\[(system\.)?(uri|math|datetime|string)\]::\w+$",  # pure helpers: [uri]::EscapeDataString(...), [math]::Round
    # a web address glued together from quoted parts and variables: ('https://...?to=' + $to + '&body=' + $body)
    r"(?:\+?\s*(?:url|\\?\$[\w:]+|[\w-]+=)\s*)+\+?$",
    r"curl\s",  # a plain web fetch; posting, uploading or saving a file was caught by CONFIRM above
    r"\$",  # an expression on a variable; anything that runs it was caught by CONFIRM above
]
SEPARATORS = r"[;&|\n{}()`]"
SHELL_WRAPPER = (r"\b(powershell|pwsh)(\.exe)?((\s+-(noprofile|nologo|noninteractive|sta|executionpolicy\s+\w+|command|c))*)"
                 r"|\bcmd(\.exe)?\s+/[ck]|\b(ba|z)?sh\s+-l?c\b")


# ---------- permission modes (Settings → Privacy & safety): how much asks, on top of the rules above ----------
MODES = ("auto", "manual", "accept_edits", "plan", "bypass")
PLAN = ("Plan mode is on, so nothing may change yet. Finish investigating, describe your plan, and end with an "
        "ASK: line asking the user to go ahead")
UNFAMILIAR = ("isn't on the known-safe list", "writes a file through a redirect", "unrecognised tool")
# Auto still asks for code typed straight into a command: the easy way around every rule above
INLINE_CODE = r"\b(python3?|py|node|deno|bun|ruby|perl|php)(\.exe)?\s+(-c|-e|--eval|-p)\b"
# known-safe commands that still change something, which Plan mode holds back too
CHANGES = (r"\bgit\s+(add|commit|pull|switch|checkout|stash|fetch|tag|branch\s+\S)|\b(start-process|start|saps|"
           r"invoke-item|ii|explorer(\.exe)?|open|npm|pnpm|yarn|npx|pytest|mkdir|md|new-item|set-clipboard|scb|pbcopy"
           r"|say|afplay|osascript|curl|rundll32|notepad|mspaint|wordpad|write|nohup)\b|sendkeys|wmisetbrightness"
           r"|set-itemproperty|clipboard\.(ps1|sh)")
# ...and of those, the ones Manual mode asks about (opening an app or a page isn't a change)
EDITS = (r"\bgit\s+(add|commit|pull|switch|checkout|stash|tag|branch\s+\S)|\b(npm|pnpm|yarn|npx|pytest|mkdir|md"
         r"|new-item)\b|sendkeys|wmisetbrightness|set-itemproperty")
# outside your projects, Auto writes freely except where a file could start programs or change the system
PROTECTED = (r"[\\/](windows|program files[^\\/]*|programdata|appdata|library|system|usr|bin|sbin|etc|private"
             r"|applications)[\\/]|[\\/]start menu[\\/]|launch(agents|daemons)|[\\/]documents[\\/](windows)?powershell"
             r"[\\/]|[\\/]\.(ssh|config|local|bashrc|zshrc|zshenv|zprofile|profile|bash_profile|gitconfig|npmrc)\b")


def with_mode(tier, why, mode, unfamiliar=None):
    """Adjust one verdict for the permission mode. Blocks always stay blocks."""
    if tier == "block" or mode not in MODES:
        return tier, why
    if mode == "bypass":
        return "allow", f"Bypass mode ({why})"
    if mode == "plan":
        return (tier, why) if tier == "allow" else ("block", PLAN)
    unfamiliar = why.startswith(UNFAMILIAR) if unfamiliar is None else unfamiliar
    if mode == "auto" and tier == "confirm" and unfamiliar:
        return "allow", f"Auto mode ({why})"
    return tier, why


def classify_command(cmd, home=None, mode="accept_edits", cwd=None):
    """`cwd`: the folder the command runs in, as the CLI reports it (a Set-Location into a project sticks)."""
    tier, why = _command(cmd, home, cwd)
    if mode == "plan" and tier == "allow" and re.search(CHANGES, cmd.lower()):
        return "block", PLAN
    if mode == "manual" and tier == "allow" and re.search(EDITS, cmd.lower()):
        return "confirm", "changes something (Manual mode asks before every change)"
    if mode == "auto" and re.search(INLINE_CODE, cmd.lower()):
        return with_mode(tier, why, mode, unfamiliar=False)
    return with_mode(tier, why, mode)


def _command(cmd, home=None, cwd=None):
    c = cmd.lower()
    # Nova's own clipboard helper, only from Nova's folder (a same-named script elsewhere is not trusted)
    helper = home and (r"(-file\s+|(ba|z)?sh\s+)?" + re.escape(home.lower().replace("\\", "/") + "/helpers/clipboard.")
                       + r"(ps1|sh)(\s|$)")
    # a commit message is prose, not commands (only when bash can't expand anything inside it)
    c = re.sub(r"(git\s+commit\b" + UNTIL_END + r"?-m\s*)('[^']*'|\"[^\"$`]*\")", r"\1''", c)
    # searches that run a program on each file, checked before search text is set aside below (on `cmd`: case
    # matters, git grep's -o is harmless)
    if re.search(r"\brg\b[^;|&\n]*\s--pre\b|\bgit\s+grep\b[^;|&\n]*\s(?:-(?!-)[a-zA-Z]*O|--open-files-in-pager)", cmd):
        return "confirm", "runs a program on every file it searches"
    # a search pattern is text to look for, never a file or a command ("rg 'def .*\(' src", "sls -pattern 'a.*\.'"),
    # so it can't trip the secret or wildcard rules; a pattern with $ or ` in it could run code, so it stays
    word = r"(?:'[^']*'|\"[^\"$`]*\"|[^\s'\"|;&$`()<>]+)"
    c = re.sub(r"\b(grep|rg)((?:\s+-(?!f\b|-file\b)[\w-]+(?:=\S+)?)*)\s+" + word, r"\1\2 x", c)  # -f: a file
    c = re.sub(r"\b(findstr)((?:\s+/[\w:]+)*)\s+" + word, r"\1\2 x", c)  # findstr's switches start with /
    c = re.sub(r"\b(select-string|sls)\s+('[^']*'|\"[^\"$`]*\")", r"\1 x", c)  # its first, unnamed argument
    c = re.sub(r"(\s-{1,2}(?:\w*pattern\w*|grep))(?:=|\s+)" + word, r"\1 x", c)  # -Pattern, --testPathPattern
    if home and re.search(re.escape(home.lower().replace("\\", "/").rstrip("/")) + r"/data\b", c.replace("\\", "/")):
        return "block", NOVA_DATA
    # shortcut: "..\data" is Nova's data folder only from Nova's workspace (where the AI runs), so ask, don't block
    if re.search(r"(^|[\s\"'=(])\.\.[\\/]data\b", c):
        return "confirm", "may read Nova's own keys, which are in ..\\data from Nova's workspace"
    for pattern, why in BLOCK:
        if re.search(pattern, c):
            return "block", why
    # ...and deleting the home folder, the Users folder or a drive however it's spelled: "$HOME"/*, ${HOME}, ~\*
    bare = re.sub(r"[\"']", "", re.sub(r"\$\{(\w+)\}", r"$\1", c))
    if re.search(DELETE + UNTIL_END + r"[\s(,=]" + WIDE, bare) or \
            re.search(r"\bfind\s+" + WIDE + UNTIL_END + r"\s-delete\b", bare):
        return "block", "deletes system folders or a whole drive"
    if re.search(RECURSIVE, c) and re.search(r"(?:^|[\s\"'=(,])" + WIDE, c):  # "grep -r . ~", "rg --hidden x C:\"
        return "confirm", WIDE_WHY
    # ...and through Nova's own folder or one above it, which hold data\ with Nova's keys ("grep -r . ..": from
    # Nova's workspace, where the AI runs, ".." is Nova's folder); grep ignores .gitignore, so data\ isn't skipped
    if home and re.search(RECURSIVE, c):
        parts = home.lower().replace("\\", "/").rstrip("/").split("/")
        above = [r"[\\/]".join(map(re.escape, parts[:n])) for n in range(2, len(parts) + 1)] + [r"\.\."]
        if re.search(r"(?:^|[\s\"'=(,])(?:" + "|".join(above) + r")[\\/]?\*?(?=$|[\s\"';|&,)])", c):
            return "confirm", NOVA_SEARCH_WHY
    # ...and with no folder named, from where it runs: "Set-Location ~" in one call, "rg --hidden x ." in the next
    if cwd and re.search(RECURSIVE, c):
        if _wide(cwd):
            return "confirm", WIDE_WHY
        if home and _under(os.path.join(home, "data"), os.path.realpath(cwd)):
            return "confirm", NOVA_SEARCH_WHY
    # a wildcard in a folder name ("~\*\id_ed25519", "~/.ss?/*") can reach a secret folder the rules can't name
    if re.search(r"[*?][^\s\\/\"'*?]*[\\/]", re.sub(r"https?://\S+", "", c)):
        return "confirm", "uses a wildcard in a folder name, which could reach secret files"
    for pattern, why in CONFIRM:
        if re.search(pattern, c):
            return "confirm", why
    if ">" in re.sub(r"\d?>\s*&\s*\d|\d?>\s*(\$null|/dev/null|nul)\b", "", c):
        return "confirm", "writes a file through a redirect"
    # an escaped \| is regex alternation inside a grep pattern ("ask\|follow"), not a pipe to another command
    # a quoted web address is one value: its "&" and "?" aren't command separators ("...?view=cm&to=x")
    urls = re.sub(r"(['\"])https?://[^'\"\s`$]*\1", " url ", c.replace("\\|", " "))
    # quoted text that is only data: a pure helper's argument ([uri]::EscapeDataString('a b'))
    urls = re.sub(r"(\]::\w+\s*)\(\s*(?:'[^']*'|\"[^\"$`]*\")\s*\)", r"\1()", urls)
    flat = re.sub(r"[\"']", " ", re.sub(SHELL_WRAPPER, ";", urls))
    for seg in re.split(SEPARATORS, flat):
        seg = re.sub(r"^\\?\$[\w:]+\s*=\s*", "", seg.strip())  # "\$x=" is $x= escaped for bash
        if not any(re.match(p, seg) for p in ALLOW) and not (helper and re.match(helper, seg.replace("\\", "/"))):
            return "confirm", f"isn't on the known-safe list ({seg[:60]})"
    return "allow", "known safe command"


def _wide(folder):
    """The home folder, a folder holding it (the Users folder) or a whole drive."""
    full = os.path.realpath(os.path.expanduser(folder))
    return bool(re.match(WIDE, full.lower())) or _under(os.path.expanduser("~"), full)


def _under(path, root):
    path, root = os.path.normcase(path), os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives
        return False


READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "view_image", "update_plan", "web_search", "read_file", "list_dir",
                   "grep_files"}
SEVERITY = {"allow": 0, "confirm": 1, "block": 2}


def classify_patch(patch, cwd, roots, home, notes, mode="accept_edits"):
    """Codex's apply_patch: judge every file the patch touches; the most severe verdict wins."""
    files = re.findall(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", patch, re.M)
    if not files:
        return with_mode("confirm", "edits files in a way Nova can't read", mode, unfamiliar=False)
    verdicts = [with_mode("confirm", "deletes a file", mode, unfamiliar=False) if kind == "Delete"
                else classify("Write", {"file_path": path or moved}, cwd, roots, home, notes, mode)
                for kind, path, moved in files]
    return max(verdicts, key=lambda v: SEVERITY[v[0]])


def classify(tool, inp, cwd, roots, home, notes, mode="accept_edits"):
    if tool in ("Bash", "PowerShell"):
        command = inp.get("command", "")
        return classify_command(" ".join(command) if isinstance(command, list) else command, home, mode, cwd)
    if tool == "apply_patch":
        return classify_patch(inp.get("command", "") or inp.get("patch", ""), cwd, roots, home, notes, mode)
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
    where = f"{path} {inp.get('pattern', '') if tool == 'Glob' else ''} {inp.get('glob', '')}"  # Grep's pattern is text
    if re.search(SECRETS, where.lower()):
        return "block", "reads browser or SSH secrets"
    if home and path and _under(os.path.realpath(os.path.join(cwd, os.path.expandvars(path))), os.path.join(home, "data")):
        return "block", NOVA_DATA
    if tool in ("Grep", "grep_files") and path:  # a search tool always goes through every folder below its path
        full = os.path.realpath(os.path.join(cwd, os.path.expandvars(os.path.expanduser(path))))
        if _wide(full):
            return with_mode("confirm", WIDE_WHY, mode, unfamiliar=False)
        if home and _under(os.path.join(home, "data"), full):  # it obeys .gitignore only in a git repo, not a ZIP install
            return with_mode("confirm", NOVA_SEARCH_WHY, mode, unfamiliar=False)
    if tool in READ_ONLY_TOOLS:
        return "allow", "read only"
    if "nova-browser" in tool or "nova_browser" in tool:  # Nova applies its own rules to the real page element
        return "allow", "browser action checked by Nova"
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        full = os.path.realpath(os.path.join(cwd, os.path.expandvars(path)))
        tier, why = _write(full, roots, home, notes)
        if mode == "plan":
            return "block", PLAN
        if mode == "manual" and tier == "allow":
            return "confirm", "changes a file (Manual mode asks before every change)"
        # Auto: an ordinary file outside your projects (Desktop, Downloads...) is fine; system and startup spots ask
        outside = why == "writes outside your projects" and not re.search(PROTECTED, full.lower())
        return with_mode(tier, why, mode, unfamiliar=outside)
    return with_mode("confirm", f"unrecognised tool {tool}", mode)


def _write(full, roots, home, notes):
    parts = [p.lower() for p in full.split(os.sep)]
    if ".claude" in parts or ".codex" in parts:
        return "confirm", "changes Claude Code's or Codex's own settings"
    if ".git" in parts:  # e.g. a hook in .git/hooks would run on the next (allowed) git commit
        return "confirm", "changes git's internals"
    if notes and _under(full, notes):
        return "allow", "Nova notes"
    if home and _under(full, home):
        return "confirm", "changes Nova itself"
    if any(_under(full, r) for r in roots):
        return "allow", "edit inside a project"
    return "confirm", "writes outside your projects"


def ask_nova(tool, summary, reason):
    try:
        # a named pipe on Windows, a Unix socket on macOS: Client works out which from the address
        with Client(os.environ["NOVA_PIPE"], authkey=bytes.fromhex(os.environ["NOVA_KEY"])) as conn:
            conn.send({"tool": tool, "summary": summary, "reason": reason})
            return conn.poll(float(os.environ.get("NOVA_TIMEOUT", "30")) + 5) and conn.recv() is True
    except Exception:  # Nova not running, bad key, broken pipe: deny
        return False


def decide(decision, reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}))


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    tool, inp = data.get("tool_name", ""), data.get("tool_input") or {}
    env = os.environ.get
    roots = [r for r in env("NOVA_ROOTS", "").split(os.pathsep) if r]
    tier, reason = classify(tool, inp, data.get("cwd") or os.getcwd(), roots, env("NOVA_HOME"), env("NOVA_NOTES"),
                            env("NOVA_MODE") or "accept_edits")
    summary = str(inp.get("command") or inp.get("file_path") or inp.get("notebook_path") or inp)[:400]
    decision = tier
    if tier == "confirm":
        decision = "allow" if ask_nova(tool, summary, reason) else "deny"
        reason = f"{reason}: user {'approved' if decision == 'allow' else 'declined or did not answer'}"
    elif tier == "block" and reason == PLAN:
        decision = "deny"
    elif tier == "block":
        decision, reason = "deny", f"blocked by Nova's safety rules: {reason}. Do not try another way; tell the user."
    if env("NOVA_HOOK_MARK"):  # lets Nova verify the CLI really ran this hook
        with open(env("NOVA_HOOK_MARK"), "a", encoding="utf-8") as f:
            f.write(tool + "\n")
    if env("NOVA_LOG"):
        with open(os.path.join(env("NOVA_LOG"), time.strftime("nova-%Y-%m-%d.jsonl")), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "event": "guard", "tool": tool, "summary": summary,
                                "tier": tier, "decision": decision, "reason": reason}) + "\n")
    decide(decision, reason)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail closed: a crashing hook must never let the tool run
        decide("deny", f"Nova's safety guard failed ({e!r}); the action was not run.")
