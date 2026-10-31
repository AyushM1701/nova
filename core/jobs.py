"""A record of every request the AI is given, in data/jobs/<id>.json: what was asked, which engine and folder, the
session to resume, and how it ended. When Nova closes mid-request the record says "running"; the next start turns
that into "interrupted" and offers to pick it up. Background jobs (kind "background") keep their files in
workspace/jobs/<id>/ and use the same records."""
import json
import os
import re
import time
import uuid

from core.config import DATA, WORKSPACE, log

DIR = DATA / "jobs"
FOLDERS = WORKSPACE / "jobs"  # a background job's own working folder, with output/ and tmp/
KEEP = 60  # records kept; older ones are deleted (a job's folder stays)
PRUNE_EVERY = 20  # new records between two tidy-ups
_began = 0
RESUMABLE_S = 24 * 3600


def _path(job_id):
    return DIR / f"{job_id}.json"


def _write(rec):
    """Atomic, and never fatal: a full disk or a locked file must not stop the request itself."""
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        tmp = _path(rec["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _path(rec["id"]))
    except OSError as e:
        log("error", error=f"couldn't write job record {rec['id']}: {e!r}")


def begin(prompt, kind="request", engine="", folder=""):
    rec = {"id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4], "kind": kind, "status": "running",
           "prompt": prompt[:4000], "engine": engine, "folder": str(folder), "session_id": None,
           "started": time.time(), "finished": None, "reply": "", "say": "", "ask": None, "files": []}
    _write(rec)
    global _began
    _began += 1
    if _began % PRUNE_EVERY == 0:  # Nova runs for weeks: tidy as it goes, not only when it starts
        prune()
    return rec


def update(rec, **fields):
    rec.update(fields)
    _write(rec)


def finish(rec, status, **fields):
    update(rec, status=status, finished=time.time(), **fields)


def load(job_id):
    if not re.fullmatch(r"[\w-]+", str(job_id)):  # an id comes from a process's environment: never a path
        return None
    try:
        return json.loads(_path(job_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def all_records():
    """Newest first. A record that can't be read is skipped."""
    recs = [load(p.stem) for p in sorted(DIR.glob("*.json"), reverse=True)] if DIR.is_dir() else []
    return [r for r in recs if isinstance(r, dict) and {"id", "status", "started"} <= r.keys()]


def prune():
    """Delete all but the newest KEEP records."""
    for rec in all_records()[KEEP:]:
        _path(rec["id"]).unlink(missing_ok=True)


def interrupt_stale():
    """At start: whatever still says "running" was cut off when Nova closed. Also deletes the oldest records."""
    for rec in all_records():
        if rec["status"] == "running":
            update(rec, status="interrupted", finished=time.time())
    prune()


def resumable():
    """The newest interrupted record that has a session to resume and is recent enough, or None."""
    for rec in all_records():
        if rec["status"] == "interrupted" and rec.get("session_id") and time.time() - rec["started"] < RESUMABLE_S:
            return rec
    return None
