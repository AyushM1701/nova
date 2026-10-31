"""Nova's secrets in the operating system's own store instead of files in data/: Windows Credential Manager, the
macOS Keychain. An API key or a pairing key written to a file sits there in plain text for backups, sync tools and
anything that can read the folder; in the store it is encrypted for this user's login.

The files are still how every secret is *named*: `read(DATA / "fallback.key")` looks in the store first, and a file
left by an older Nova is moved into it on the first read (then deleted). Where there is no store (Linux), or it
refuses, the file is kept as before. A path outside data/ (a test's folder) is always just a file.

Not here: data/events.key and the browser token. Other programs read those (the terminal watcher, the browser
extension's own folder), and they have no way to ask a store for them.
"""
import ctypes
import re
import subprocess
import sys
from pathlib import Path

from core.config import DATA, write_private

ACCOUNT = "Nova"


class Unavailable(OSError):
    """The store is there but won't answer (a locked Keychain): that is not the same as "no secret stored"."""


# ---------- Windows: Credential Manager (advapi32, no extra library) ----------
def _win_api():
    from ctypes import wintypes as w

    class Credential(ctypes.Structure):
        _fields_ = [("Flags", w.DWORD), ("Type", w.DWORD), ("TargetName", w.LPWSTR), ("Comment", w.LPWSTR),
                    ("LastWritten", w.FILETIME), ("CredentialBlobSize", w.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", w.DWORD),
                    ("AttributeCount", w.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", w.LPWSTR),
                    ("UserName", w.LPWSTR)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    advapi.CredWriteW.argtypes = [ctypes.POINTER(Credential), w.DWORD]
    advapi.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    return Credential, advapi


def _win_get(name):
    Credential, advapi = _win_api()
    found = ctypes.POINTER(Credential)()
    if not advapi.CredReadW(name, 1, 0, ctypes.byref(found)):  # 1: a generic credential
        error = ctypes.get_last_error()
        if error == 1168:  # ERROR_NOT_FOUND
            return None
        raise Unavailable(f"Credential Manager answered with error {error}")
    try:
        blob = found.contents
        return ctypes.string_at(blob.CredentialBlob, blob.CredentialBlobSize).decode("utf-16-le")
    finally:
        advapi.CredFree(found)


def _win_put(name, value):
    Credential, advapi = _win_api()
    data = value.encode("utf-16-le")
    if len(data) > 2560:  # Windows' limit for one credential's secret
        return False
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    credential = Credential()
    credential.Type, credential.TargetName, credential.UserName = 1, name, ACCOUNT
    credential.CredentialBlobSize, credential.CredentialBlob = len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE: kept across restarts, not roamed to other computers
    return bool(advapi.CredWriteW(ctypes.byref(credential), 0))


def _win_drop(name):
    _, advapi = _win_api()
    advapi.CredDeleteW(name, 1, 0)


# ---------- macOS: the Keychain, through the `security` tool ----------
def _mac_get(name):
    r = subprocess.run(["security", "find-generic-password", "-a", ACCOUNT, "-s", name, "-w"], capture_output=True,
                       text=True, timeout=10)
    if r.returncode == 0:
        return r.stdout.rstrip("\n")
    if r.returncode == 44:  # errSecItemNotFound
        return None
    raise Unavailable(f"the Keychain answered with {r.returncode}: {r.stderr.strip()[:100]}")


def _mac_put(name, value):
    if re.search(r"['\"\\\r\n]", value):  # it goes in a quoted line below; such a secret stays in its file
        return False
    # on stdin, not in the argument list: `ps` shows every program's arguments to every user
    line = f"add-generic-password -a {ACCOUNT} -s '{name}' -U -w '{value}'\n"
    subprocess.run(["security", "-i"], input=line, capture_output=True, text=True, timeout=10)
    try:
        return _mac_get(name) == value  # the tool's exit code isn't reliable in this mode: look
    except Unavailable:
        return False


def _mac_drop(name):
    subprocess.run(["security", "delete-generic-password", "-a", ACCOUNT, "-s", name], capture_output=True, timeout=10)


# ---------- the one the rest of Nova uses ----------
if sys.platform == "win32":
    _get, _put, _drop = _win_get, _win_put, _win_drop
elif sys.platform == "darwin":
    _get, _put, _drop = _mac_get, _mac_put, _mac_drop
else:
    _get, _put, _drop = (lambda name: None), (lambda name, value: False), (lambda name: None)


def _name(path):
    """The store's name for one of Nova's data files; None for a file anywhere else, which stays a file."""
    path = Path(path)
    return f"Nova/{path.name}" if path.parent.resolve() == DATA.resolve() else None


def _safely(call, *args):
    try:
        return call(*args)
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):  # locked Keychain, odd Windows: use the file
        return None


def read(path, strict=False):
    """The secret stored for `path` ("" when there is none). A file from before the store existed is moved into it.
    `strict`: a store that won't answer raises Unavailable instead of reading as "none", for a caller that would
    otherwise make a new secret (and so lose the one that is there)."""
    path, name = Path(path), _name(path)
    if name:
        failed = None
        try:
            value = _get(name)
        except (OSError, ValueError, subprocess.SubprocessError, AttributeError) as e:
            value, failed = None, e
        if value is not None:
            if path.exists():  # a plain copy left over (a restored backup): the store has the secret, the file goes
                path.unlink(missing_ok=True)
            return value
        if failed and strict and not path.exists():
            raise Unavailable(str(failed)) from failed
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if name and text and _safely(_put, name, text):
        path.unlink(missing_ok=True)
    return text


def write(path, text):
    """Store the secret for `path`: in the store when there is one, else in the file only this user can read."""
    path, name = Path(path), _name(path)
    if name and _safely(_put, name, text):
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_private(path, text)


def delete(path):
    path, name = Path(path), _name(path)
    if name:
        _safely(_drop, name)
    path.unlink(missing_ok=True)

