"""Background jobs: "in the background, research X" runs the AI on its own, in a folder of its own, while Nova stays free.
A mixin of the Nova class (nova.py); it uses the Nova window's state (self.cfg, self.bg, self.ui, self.say...)."""
import os
import re
import threading
import time
from pathlib import Path

from core import jobs, system
from core.brain import discover_projects, make_brain, project_folders
from core.config import ROOT, log
from core.errors import friendly
from core.sketch import strip as strip_sketch

# "in the background, research X" / "background job: X" / "X, as a background task". The comma or colon is required:
# "in the background of this photo, what is that?" and "background task manager shows high CPU" are questions.
# Not a bare "... in the background" either: "start the server in the background" is a request about the server
BACKGROUND_RE = re.compile(r"(?:(?:do|run|handle|work on) (?:this|that|it) )?in the background[,:]\s+(.+)|"
                           r"(?:as a )?background (?:job|task)[,:]\s+(.+)|(.+?),?\s+as a background (?:job|task)",
                           re.I | re.S)
STOP_BACKGROUND_RE = r"(?:stop|cancel|kill) (?:the |all |my )?background (?:jobs?|tasks?)"

# a result is opened for the user only if it is a document: a .bat or .lnk the AI wrote would run
SAFE_OPEN = {".pdf", ".md", ".txt", ".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".csv", ".docx", ".xlsx", ".pptx"}

JOB_PROMPT = """[This is a background job. The user is doing something else, so work on your own.
- Your folder is {folder}. Put what you make in output/ and scratch files in tmp/, and do not write anywhere else.
- Don't ask questions or end with an ASK: line. If something is missing, make a sensible choice and say which.
- Finish with a SAY: line (one or two short sentences about the result). In the reply, name each file in output/.]
{task}"""


class BackgroundMixin:
    # ---------- background jobs: a request that runs on its own while Nova stays free ----------
    def background(self, task, resume=None):
        """Start `task` as a background job: its own CLI run in its own folder (workspace/jobs/<id>/ with output/ and
        tmp/), no card, no speech until it is done. The guard still checks every action; approvals name the job."""
        if not self.brain:
            return self.note("No AI connected", "I can't find Claude Code or Codex, so I can't run a background job.")
        if self.cfg["safety"]["mode"] == "plan":
            return self.note("Background jobs need Auto mode", "Plan mode only plans, so a background job would stop and wait.")
        limit = self.cfg["brain"]["max_background"]
        if sum(j["thread"].is_alive() for j in list(self.bg.values())) >= limit:  # a copy: a finishing job removes itself
            return self.note("Already busy", f"{limit} background jobs are already running. Say “stop the background "
                             "jobs” to cancel them, or wait for one to finish.")
        rec = jobs.begin(task if not resume else resume["prompt"], kind="background", engine=self.brain.name,
                         folder=resume["folder"] if resume else "")
        folder = Path(resume["folder"]) if resume else jobs.FOLDERS / rec["id"]
        for sub in ("output", "tmp"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        jobs.update(rec, folder=str(folder))
        projects = discover_projects(self.cfg["projects"]["exclude"], ROOT)
        env = dict(self.env, NOVA_JOB=rec["id"], NOVA_MODE=self.cfg["safety"]["mode"], NOVA_ROOTS=os.pathsep.join(
            [*projects.values(), *project_folders(projects, self.cfg["projects"]["folders"]), str(folder)]))
        brain = make_brain(self.cfg, str(folder), env, self.settings, self.hook)
        brain.mode, brain.browser, brain.apps = env["NOVA_MODE"], False, sorted(self.apps)  # no browser: shared with the user
        brain.on_session = lambda session_id: jobs.update(rec, session_id=session_id)
        if resume and resume.get("session_id") and resume["engine"] == brain.name:
            brain.session_id, brain.last = resume["session_id"], time.time()
        job = {"brain": brain, "cancel": threading.Event(), "label": (resume or rec)["prompt"][:60]}
        job["thread"] = threading.Thread(target=self.run_background, args=(rec, job, task, folder, projects), daemon=True)
        self.bg[rec["id"]] = job
        job["thread"].start()
        log("background", job=rec["id"], task=task[:300])
        self.outbox.put({"event": "note", "title": "Background job started", "text": job["label"]})
        self.ui(self.push_state)
        self.say("Background job", "Okay, I'll work on that in the background.", job["label"])

    def run_background(self, rec, job, task, folder, projects):
        brain, status, shown, spoken = job["brain"], "failed", "", ""
        step = lambda text: self.outbox.put({"event": "step", "text": f"Background job: {text}"})  # noqa: E731
        try:
            prompt = JOB_PROMPT.format(folder=folder, task=task)
            shown, spoken, ask = brain.run(prompt, projects, self.cfg["projects"]["aliases"], step)
            shown = strip_sketch(shown)
            if ask:  # nobody can answer a job: the question goes in the reply
                shown = f"{shown}\n\nA question for you: {ask}"
            status = "done"
            if brain.limited:
                status, shown = "failed", f"{brain.name} is at its usage limit.\n\n{shown}"
        except Exception as e:
            log("error", error=repr(e), job=rec["id"])
            shown, spoken = f"The job failed: {friendly(e)}", "The background job failed."
        if self.quitting:
            status = "interrupted"  # Nova is closing: "pick that up" carries it on next time
        elif job["cancel"].is_set():
            status = "cancelled"
        out = folder / "output"
        files = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())[:30]
        jobs.finish(rec, status, reply=shown[:4000], say=spoken[:500], files=files)
        self.bg.pop(rec["id"], None)
        self.ui(self.push_state)
        log("background_done", job=rec["id"], status=status, files=files)
        if status in ("done", "failed"):
            self.report_job(job["label"], status, shown, spoken, out, files)

    def report_job(self, label, status, shown, spoken, out, files):
        """Tell the user, once Nova is idle (never over another request): say the result, open a lone document."""
        title = "Background job done" if status == "done" else "Background job failed"
        body = shown + (("\n\nFiles: " + ", ".join(files)) if files else "")
        self.outbox.put({"event": "note", "title": title, "text": body})
        spoken = spoken or title
        deadline = time.monotonic() + 600
        took = threading.Event()
        while time.monotonic() < deadline and not self.quitting:
            def speak():
                if took.is_set() or self.phase != "idle" or self.pending or self.paused:
                    return
                took.set()
                self.target, self.voice = system.foreground(), True
                self.spawn(lambda: self.say(title, spoken, f"{label}\n\n{body}"), "busy")
                if status == "done" and len(files) == 1 and Path(files[0]).suffix.lower() in SAFE_OPEN:
                    system.open_path(out / files[0])
            self.ui(speak)
            time.sleep(2)
            if took.is_set():
                return

    def cancel_background(self):
        for job in list(self.bg.values()):
            job["cancel"].set()
            job["brain"].cancel()

