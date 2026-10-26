"""Apps the AI can reach: the user's own MCP servers (Linear, Notion, Jira, GitHub, Composio, anything with an MCP
address), set in Settings → AI → Apps (config.json, `mcp.servers`):

    "mcp": {"servers": {"linear": "https://mcp.linear.app/mcp",
                        "github": {"url": "https://api.githubcopilot.com/mcp/",
                                   "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"}},
                        "files": {"command": "npx", "args": ["-y", "some-mcp-server"], "env": {"API_KEY": "${API_KEY}"}}}}

Only the user adds a server (the guard blocks the AI from editing this setting), and a token is never written in the
file, because the AI can read it: a secret goes in an environment variable and is named as ${NAME}. The guard decides
every tool call (guard/guard.py: reads pass, anything that changes an app asks).

Claude Code gets these servers. Codex doesn't yet: its hook isn't known to cover MCP tools, so they would run
without the guard."""
import json
import re

RESERVED = {"nova-browser", "nova-notes"}  # Nova's own servers
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")  # no "__": a tool is mcp__<server>__<tool>
SECRETY = re.compile(r"token|key|secret|password|passwd|auth|cookie|credential", re.I)
ENV_REF = re.compile(r"\$\{[A-Z_][A-Z0-9_]*\}")
LOCAL = ("http://localhost", "http://127.0.0.1", "http://[::1]")
PRESETS = {  # the servers' own addresses; sign in once from Settings
    "linear": ("Linear", "https://mcp.linear.app/mcp"),
    "notion": ("Notion", "https://mcp.notion.com/mcp"),
    "jira": ("Jira and Confluence", "https://mcp.atlassian.com/v1/mcp"),
    "github": ("GitHub", "https://api.githubcopilot.com/mcp/"),
}


def _url(value):
    return isinstance(value, str) and value.strip().startswith(("https://",) + LOCAL) and " " not in value.strip()


def _secrets_ok(pairs):
    """Every value whose name looks like a credential must be a ${VARIABLE}: never a secret in a file the AI reads."""
    return all(isinstance(v, str) and (not SECRETY.search(k) or ENV_REF.search(v)) for k, v in pairs.items())


def servers(cfg):
    """({name: spec for Claude Code's --mcp-config}, [what was left out and why]) from the `mcp.servers` setting."""
    ok, problems = {}, []
    for name, spec in ((cfg.get("mcp") or {}).get("servers") or {}).items():
        name = str(name)
        if not NAME_RE.match(name) or name in RESERVED:
            problems.append(f"{name}: not a usable name (letters, digits and - only)")
        elif isinstance(spec, str):
            if _url(spec):
                ok[name] = {"type": "http", "url": spec.strip()}
            else:
                problems.append(f"{name}: the address must be https://…")
        elif isinstance(spec, dict) and spec.get("enabled", True) is False:
            continue
        elif isinstance(spec, dict) and "url" in spec:
            headers = spec.get("headers") or {}
            if not _url(spec["url"]) or not isinstance(headers, dict) or not _secrets_ok(headers):
                problems.append(f"{name}: needs an https:// address, and a secret in a header written as ${{NAME}}")
            else:
                ok[name] = {"type": "http", "url": spec["url"].strip(), **({"headers": headers} if headers else {})}
        elif isinstance(spec, dict) and isinstance(spec.get("command"), str):
            args, env = spec.get("args") or [], spec.get("env") or {}
            if not (isinstance(args, list) and len(args) <= 20 and all(isinstance(a, str) for a in args)
                    and isinstance(env, dict) and _secrets_ok(env)):
                problems.append(f"{name}: args must be text, and a secret in env written as ${{NAME}}")
            else:
                ok[name] = {"command": spec["command"], "args": args, **({"env": env} if env else {})}
        else:
            problems.append(f"{name}: an address, or an object with url or command")
    return ok, problems


def config_json(servers_, extra=None):
    """The --mcp-config file's text: the user's servers plus `extra` (Nova's own)."""
    return json.dumps({"mcpServers": {**(extra or {}), **servers_}}, indent=2)


def allow_list(servers_):
    """Claude Code permissions: each server's tools are pre-allowed so Nova's guard, not a prompt, decides."""
    return [f"mcp__{name}" for name in servers_]
