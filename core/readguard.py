"""What the AI may read of a page, and which addresses are on your own network.

A page that shows credentials (API keys, access tokens, recovery codes, saved cards) is withheld whole, credential-like
query values are cut from every address in what the AI reads, and JWT-shaped strings are hidden. Rules ported from
Hedwig Desktop's secret guard. Shortcut: judged from the address and the text, not from what the page really holds."""
import ipaddress
import re
import urllib.parse

SECRET_PARAM = re.compile(
    r"^(access_?token|id_?token|refresh_?token|token|auth|auth_?token|authorization|api_?key|apikey|key|secret|"
    r"client_?secret|password|passwd|pwd|sig|signature|x-amz-signature|x-amz-credential|x-amz-security-token|"
    r"x-goog-signature|x-goog-credential|session|session_?id|sid|otp|verifier|ticket|nonce|jwt|assertion|"
    r"samlresponse|samlrequest)$", re.I)
SECRET_PART = re.compile(
    r"^(api[-_]?keys?|apikeys?|access[-_]?tokens?|personal[-_]?access[-_]?tokens?|auth[-_]?tokens?|tokens|secrets?|"
    r"credentials?|recovery[-_]?codes?|backup[-_]?codes?|ssh[-_]?keys?|gpg[-_]?keys?|signing[-_]?keys?|"
    r"app[-_]?passwords?|security[-_]?keys?|payment[-_]?methods?)$", re.I)
SECRET_IN_SETTINGS = re.compile(r"^(security|keys|api|passwords?|2fa|two[-_]?factor|mfa|authentication)$", re.I)
SETTINGS_PART = re.compile(
    r"^(settings|account|accounts|profile|user|admin|preferences|developer|developers|org|orgs|organization|"
    r"organizations|project|projects|team|teams|workspace|workspaces|dashboard|console)$", re.I)
DOCS_PART = re.compile(r"^(docs?|documentation|help|guides?|learn|blog|reference|api-reference|tutorials?|kb|"
                       r"articles?|support)$", re.I)
JWT = re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}\b")
URL = re.compile(r"https?://[^\s\"'<>)\]]+")
WITHHELD = ("[Nova withheld this page: it shows keys, tokens, recovery codes or saved cards. "
            "Tell the user to open it themselves.]")


def redact_url(url):
    """The address with credential-like query values, a one-time OAuth code, a password and a token fragment cut."""
    try:
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        return url
    if parts.scheme not in ("http", "https"):
        return url
    keep = [(k, v) for k, v in query if not SECRET_PARAM.match(k)]
    if any(k == "code" for k, _ in keep) and (any(k == "state" for k, _ in keep)
                                              or re.search(r"callback|oauth|auth", parts.path, re.I)):
        keep = [(k, v) for k, v in keep if k not in ("code", "state")]  # a plain ?code= (a coupon) stays
    fragment = "" if re.search(r"(^|&)(access_token|id_token|token|code)=", parts.fragment, re.I) else parts.fragment
    host = parts.netloc.rpartition("@")[2]
    if len(keep) == len(query) and fragment == parts.fragment and host == parts.netloc:
        return url
    return urllib.parse.urlunsplit((parts.scheme, host, parts.path, urllib.parse.urlencode(keep), fragment))


def secret_page(url):
    """Does this address show credentials? Path parts only; documentation about keys is not a page of keys."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    path = [urllib.parse.unquote(p) for p in parts.path.split("/") if p]
    if any(DOCS_PART.match(p) for p in path) or re.match(r"(docs|help|support|developers?|learn)\.", parts.hostname or "", re.I):
        return False
    if any(SECRET_PART.match(p) for p in path):
        return True
    at = next((i for i, p in enumerate(path) if SETTINGS_PART.match(p)), -1)
    return at >= 0 and any(SECRET_IN_SETTINGS.match(p) for p in path[at + 1:])


def clean(text):
    """A browser read (title, address, body) as the AI may see it."""
    head = text.split("\n", 2)
    if len(head) > 1 and secret_page(head[1].strip()):
        return f"{head[0]}\n{redact_url(head[1].strip())}\n\n{WITHHELD}"
    return JWT.sub("[hidden]", URL.sub(lambda m: redact_url(m[0]), text))


def lan_host(url):
    """An address on your own network, not this computer: a private or link-local IP (169.254.169.254 is cloud
    metadata), *.local, or a bare name like "router". localhost stays allowed: it is where dev servers run.
    shortcut: judged from the hostname only, so a public name that resolves to a LAN address, or a redirect to one,
    passes; upgrade by resolving the name in the extension before the page loads."""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith((".local", ".internal", ".lan", ".home.arpa")) or "." not in host
    return not ip.is_loopback and not ip.is_global


BLOCKED = "[Nova hid this page: its site is on your block list (Settings → Browsers).]"


def _bare(host):
    return (host or "").lower().lstrip("*.").removeprefix("www.")


def blocked_site(url, sites):
    """The block-list entry this address falls under, or "". An entry is a hostname (a URL or `*.bank.com` works too);
    its subdomains count."""
    try:
        host = _bare(urllib.parse.urlsplit(url).hostname)
        for site in sites:
            entry = _bare(urllib.parse.urlsplit(site if "//" in str(site) else "//" + str(site)).hostname)
            if entry and host and (host == entry or host.endswith("." + entry)):
                return entry
    except ValueError:
        pass
    return ""


def hide_blocked(result, sites):
    """What a browser tool returned, minus the block list: tabs on it are left out, and a page that landed on it (a
    redirect, or a tab you opened yourself) is replaced by a notice."""
    if not sites:
        return result
    if isinstance(result, list):
        return [r for r in result if not (isinstance(r, dict) and blocked_site(str(r.get("url", "")), sites))]
    if isinstance(result, dict):
        return {"blocked": BLOCKED} if blocked_site(str(result.get("url", "")), sites) else result
    head = result.split("\n", 2) if isinstance(result, str) else []
    return BLOCKED if len(head) > 1 and blocked_site(head[1].strip(), sites) else result


def page_host(text):
    """The site a browser read came from ("github.com"), or "" for anything that isn't a page read."""
    head = text.split("\n", 2) if isinstance(text, str) else []
    try:
        return _bare(urllib.parse.urlsplit(head[1].strip()).hostname) if len(head) > 1 and head[1].startswith("http") else ""
    except ValueError:
        return ""
