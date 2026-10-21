"""Run a long command and let Nova tell you how it went, so you can work in another window meanwhile.

    python D:/projects/NOVA/helpers/watch.py npm run build
    python D:/projects/NOVA/helpers/watch.py python train.py --epochs 20

Output still shows in your terminal as usual. When the command ends, Nova says it finished, or, if it failed,
explains why from the last lines of output and asks whether to fix it. Stdlib only, so any Python runs it."""
import collections
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notify import send  # noqa: E402


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    command = subprocess.list2cmdline(sys.argv[1:]) if os.name == "nt" else " ".join(sys.argv[1:])
    tail, started = collections.deque(maxlen=60), time.time()
    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", bufsize=1)
    try:
        for line in p.stdout:
            sys.stdout.write(line)
            tail.append(line.rstrip()[:400])
        code = p.wait()
    except KeyboardInterrupt:  # Ctrl+C: stop the command quietly, don't report it as a failure
        p.terminate()
        sys.exit(130)
    send({"event": "command_done", "command": command, "code": code, "cwd": os.getcwd(),
          "seconds": round(time.time() - started), "tail": "\n".join(tail)})
    sys.exit(code)


if __name__ == "__main__":
    main()
