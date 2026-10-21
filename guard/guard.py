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
           r"|\.ssh[\\/]id_|library/keychains|cookies\.binarycookies|fallback\.key|browser-token|events\.key"
           # other tools' saved logins: cloud, git, package registries, and the AI CLIs themselves
           r"|\.aws[\\/]credentials|\.git-credentials|\.netrc\b|\.npmrc|\.pypirc|\.docker[\\/]config\.json"
           r"|\.kube[\\/]config|gh[\\/]hosts\.yml|\.claude[\\/]\.credentials|\.codex[\\/]auth\.json|\.gnupg")

BLOCK = [
    (r"\bformat(\.com)?\s+[a-z]:|\bdiskpart\b|\bbcdedit\b|\bcipher\s+/w|\bvssadmin\s+delete|\bwbadmin\s+delete"
     r"|clear-disk|initialize-disk|format-volume", "wipes a disk or the boot configuration"),
    (r"\b(rm|del|erase|rd|rmdir|remove-item|ri)\b" + UNTIL_END +
     r"(\s[\"']?[a-z]:[\\/]?[\"']?(\s|$|\*)|\s/(\s|$|\*)|\s~[\\/]?(\s|$)|\\windows\b|system32|program files|programdata"
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
    (r"\b(rm|del|erase|rd|rmdir|remove-item|ri|move-item|mi|mv|move|ren|rename-item|clear-content|clc|shred|unlink)\b"
     r"|\s-(delete|exec|execdir)\b", "deletes or moves files"),
    (r"\bgit\s+(push|reset\s+--hard|clean|rebase|checkout\s+(--|\.)|restore|branch\s+-d|stash\s+(drop|clear)"
     r"|filter-branch|commit\s+--amend)", "rewrites or publishes git history"),
    (r"\b(vercel|netlify|firebase\s+deploy|npm\s+publish|docker\s+push|kubectl|terraform\s+apply"
     r"|gh\s+(pr|release|repo|issue)\s+(create|merge|delete|close|comment))\b", "deploys or publishes"),
    (r"\b(pip3?|uv|pipx|npm|pnpm|yarn|winget|choco|scoop|cargo|gem|go|brew|port)\s+(install|i|add|uninstall|remove|upgrade"
     r"|update|un|rm)\b|\b(install-module|install-package|add-appxpackage|msiexec)\b", "installs or removes software"),
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
    (r"\b(set-executionpolicy|schtasks|register-scheduledtask|new-service)\b|\bsc(\.exe)?\s+(create|config|delete)\b",
     "changes system configuration"),
    (r"\s-enc(odedcommand)?\b|frombase64string", "runs an encoded command"),
    (r"&\s*[\$\"']|(^|[;|&\s])\.\s+\$|\binvoke-expression\b|\biex\b|\binvoke-command\b|\bicm\b|\beval\b",
     "runs a dynamically built command"),
    (r"\.(delete|kill|moveto|copyto|terminate|invoke|run|exec|create|stop|start|close|clear|write\w*|set\w*"
     r"|remove\w*|deletesubkey\w*|download\w*|upload\w*)\s*\(",
     "calls a method that changes things"),
    (r"\b(start-process|start|saps)\s+[\"']?(powershell|pwsh|cmd|wscript|cscript|mshta|regsvr32|python|py|node|bash"
     r"|wsl)\b|-verb\s+runas", "starts a shell or an elevated process"),
    (r"\b(start-process|start|saps|invoke-item|ii|explorer(\.exe)?)\s" + UNTIL_END +
     r"(\.(ps1|bat|cmd|vbs|vbe|js|jse|wsf|msi|scr|hta|py|pyw|jar|reg|cpl)\b|\\(downloads|temp)\\)",
     "runs a script or a downloaded file"),
    # -ArgumentList (any prefix, e.g. -Args, -a) hides "git push" or "winget install" from the rules above
    (r"\b(start-process|saps|start)\s" + UNTIL_END + r"\s-a\w*\b|\bopen\s" + UNTIL_END + r"\s--args\b",
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
    r"\$",  # an expression on a variable; anything that runs it was caught by CONFIRM above
]
SEPARATORS = r"[;&|\n{}()`]"
SHELL_WRAPPER = (r"\b(powershell|pwsh)(\.exe)?((\s+-(noprofile|nologo|noninteractive|sta|executionpolicy\s+\w+|command|c))*)"
                 r"|\bcmd(\.exe)?\s+/[ck]|\b(ba|z)?sh\s+-l?c\b")


def classify_command(cmd, home=None):
    c = cmd.lower()
    # Nova's own clipboard helper, only from Nova's folder (a same-named script elsewhere is not trusted)
    helper = home and (r"(-file\s+|(ba|z)?sh\s+)?" + re.escape(home.lower().replace("\\", "/") + "/helpers/clipboard.")
                       + r"(ps1|sh)(\s|$)")
    # a commit message is prose, not commands (only when bash can't expand anything inside it)
    c = re.sub(r"(git\s+commit\b" + UNTIL_END + r"?-m\s*)('[^']*'|\"[^\"$`]*\")", r"\1''", c)
    for pattern, why in BLOCK:
        if re.search(pattern, c):
            return "block", why
    for pattern, why in CONFIRM:
        if re.search(pattern, c):
            return "confirm", why
    if ">" in re.sub(r"\d?>\s*&\s*\d|\d?>\s*(\$null|/dev/null|nul)\b", "", c):
        return "confirm", "writes a file through a redirect"
    # an escaped \| is regex alternation inside a grep pattern ("ask\|follow"), not a pipe to another command
    flat = re.sub(r"[\"']", " ", re.sub(SHELL_WRAPPER, ";", c.replace("\\|", " ")))
    for seg in re.split(SEPARATORS, flat):
        seg = re.sub(r"^\$[\w:]+\s*=\s*", "", seg.strip())
        if not any(re.match(p, seg) for p in ALLOW) and not (helper and re.match(helper, seg.replace("\\", "/"))):
            return "confirm", f"isn't on the known-safe list ({seg[:60]})"
    return "allow", "known safe command"


def _under(path, root):
    path, root = os.path.normcase(path), os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives
        return False


READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "view_image", "update_plan", "web_search", "read_file", "list_dir",
                   "grep_files"}
SEVERITY = {"allow": 0, "confirm": 1, "block": 2}


def classify_patch(patch, cwd, roots, home, notes):
    """Codex's apply_patch: judge every file the patch touches; the most severe verdict wins."""
    files = re.findall(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", patch, re.M)
    if not files:
        return "confirm", "edits files in a way Nova can't read"
    verdicts = [("confirm", "deletes a file") if kind == "Delete"
                else classify("Write", {"file_path": path or moved}, cwd, roots, home, notes)
                for kind, path, moved in files]
    return max(verdicts, key=lambda v: SEVERITY[v[0]])


def classify(tool, inp, cwd, roots, home, notes):
    if tool in ("Bash", "PowerShell"):
        command = inp.get("command", "")
        return classify_command(" ".join(command) if isinstance(command, list) else command, home)
    if tool == "apply_patch":
        return classify_patch(inp.get("command", "") or inp.get("patch", ""), cwd, roots, home, notes)
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
    if re.search(SECRETS, f"{path} {inp.get('pattern', '')} {inp.get('glob', '')}".lower()):
        return "block", "reads browser or SSH secrets"
    if tool in READ_ONLY_TOOLS:
        return "allow", "read only"
    if "nova-browser" in tool or "nova_browser" in tool:  # Nova applies its own rules to the real page element
        return "allow", "browser action checked by Nova"
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        full = os.path.realpath(os.path.join(cwd, os.path.expandvars(path)))
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
    return "confirm", f"unrecognised tool {tool}"


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
    tier, reason = classify(tool, inp, data.get("cwd") or os.getcwd(), roots, env("NOVA_HOME"), env("NOVA_NOTES"))
    summary = str(inp.get("command") or inp.get("file_path") or inp.get("notebook_path") or inp)[:400]
    decision = tier
    if tier == "confirm":
        decision = "allow" if ask_nova(tool, summary, reason) else "deny"
        reason = f"{reason}: user {'approved' if decision == 'allow' else 'declined or did not answer'}"
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
