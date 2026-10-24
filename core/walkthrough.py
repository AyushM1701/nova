"""The walkthrough's video clips (the window plays them after first-run setup, each followed by a "your turn" step).

They aren't part of the download, so installs and updates stay small: the first time the walkthrough opens, Nova
fetches this version's nova-walkthrough.zip from its GitHub release and checks it against the release's SHA256SUMS,
like an update. A git checkout plays its own copy in docs/media/walkthrough instead.
"""
import base64
import io
import zipfile

from core import update
from core.config import DATA, ROOT

CLIPS = ("00-welcome", "01-talk", "02-dictate", "03-rewrite", "04-screen", "05-safety", "06-finish")
ASSET = "nova-walkthrough.zip"
DIR = DATA / "walkthrough"  # data/ is this computer's own: updates leave it alone
LOCAL = ROOT / "docs" / "media" / "walkthrough"


def _have(folder):
    return all((folder / f"{name}.mp4").exists() for name in CLIPS)


def folder(fetch=update.fetch):
    """Where the clips are, downloading them once if needed. ValueError if the download doesn't match its checksum."""
    if _have(LOCAL):
        return LOCAL
    if not _have(DIR):
        base = f"https://github.com/{update.REPO}/releases/download/v{update.current()}/"
        archive = update.verified(fetch(base + ASSET), fetch(base + update.SUMS, 10).decode("utf-8", "replace"), ASSET)
        DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for name in CLIPS:  # only the known clips, by name: nothing else in the zip is written anywhere
                (DIR / f"{name}.mp4").write_bytes(z.read(f"{name}.mp4"))
    return DIR


def clip(name, fetch=update.fetch):
    """One clip as a data: URL the window's <video> can play (the window is a page with no files of its own)."""
    if name not in CLIPS:
        raise ValueError(f"No walkthrough clip called {name!r}.")
    data = (folder(fetch) / f"{name}.mp4").read_bytes()
    return "data:video/mp4;base64," + base64.b64encode(data).decode("ascii")
