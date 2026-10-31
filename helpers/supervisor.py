"""Starts Nova at login and starts it again if it crashes: `pythonw helpers/supervisor.py nova.py`.

Quit (and a second copy finding Nova already running) end Nova with exit code 0, which ends this too. Any other end is a
crash or a kill, so Nova starts again after a short pause; three starts within a minute means something is badly
wrong, and it gives up instead of looping. The pause also lets setup.ps1 / uninstall.ps1, which stop every process
mentioning nova.py, finish stopping this one before it can start a new copy. Stdlib only.
"""
import os
import subprocess
import sys
import time

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def supervise(command, cwd, run=subprocess.run, now=time.time, sleep=time.sleep, pause=5, limit=3, window=60,
              report=lambda message: None):
    """Run `command` until it exits with 0. Returns 0 then, or 1 after `limit` starts within `window` seconds
    (`report` is told, so Nova doesn't just vanish without a trace)."""
    starts = []
    while True:
        starts = [t for t in starts if now() - t < window]
        if len(starts) >= limit:
            report(f"Nova stopped {limit} times within {window} seconds, so it was not started again.")
            return 1
        starts.append(now())
        if run(command, cwd=cwd, creationflags=NO_WINDOW).returncode == 0:
            return 0
        sleep(pause)


if __name__ == "__main__":
    script = os.path.abspath(sys.argv[1])
    crash_log = os.path.join(os.path.dirname(script), "logs", "crash.txt")  # where Nova's own native crashes go too

    def report(message):
        os.makedirs(os.path.dirname(crash_log), exist_ok=True)
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} supervisor: {message}\n")

    sys.exit(supervise([sys.executable, script], cwd=os.path.dirname(script), report=report))
