"""Step 2: write every transcript in Roman Hinglish, the way Nova should type it ("continue पर click करें" ->
"continue par click karein"). Claude (through the Claude Code CLI, Haiku) converts 50 lines a call, 4 calls at once.

    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/romanize.py

Reads manifest.jsonl, writes roman.jsonl {id, split, text, seconds}; a line that comes back wrong is left out. Resumable."""
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "data" / "hinglish-train"
BATCH, WORKERS = 50, 4
PROMPT = """Convert each numbered line to Roman Hinglish, the way an Indian types Hindi in a chat message.
- Write exactly the words that were spoken. Transliterate every Hindi word into Latin letters, even formal or rare
  ones (निष्पादित -> nishpadit, संस्थापित -> sansthapit); never replace a Hindi word with an English one.
- English words (already in Latin letters) keep normal English spelling.
- Use common chat spellings: hai, hain, karein, kya, mein, nahi, aap, yeh, woh, kaise, liye, bhi, ki, ke, ko.
- Write numbers as digits. Lowercase except names and acronyms. No Devanagari at all.
- Return exactly the same numbers, one line each, as "N. text", and nothing else."""
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def claude(lines):
    exe = shutil.which("claude") or shutil.which("claude.cmd")
    numbered = "\n".join(f"{n}. {text}" for n, text in enumerate(lines, 1))
    r = subprocess.run([exe, "-p", "--model", "haiku", "--tools", "", "--no-session-persistence",
                        "--system-prompt", PROMPT], input=numbered, capture_output=True, text=True, encoding="utf-8",
                       timeout=300, env=dict(os.environ))
    got = {}
    for line in r.stdout.splitlines():
        m = re.match(r"\s*(\d+)\.\s*(.+)", line)
        if m:
            got[int(m.group(1))] = m.group(2).strip()
    return [got.get(n) for n in range(1, len(lines) + 1)]


def good(text, original):
    return bool(text) and not DEVANAGARI.search(text) and 0.4 < len(text) / max(1, len(original)) < 2.5


def main():
    rows = [json.loads(line) for line in (OUT / "manifest.jsonl").open(encoding="utf-8")]
    target = OUT / "roman.jsonl"
    done = {json.loads(line)["id"] for line in target.open(encoding="utf-8")} if target.exists() else set()
    todo = [r for r in rows if r["id"] not in done]
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    print(f"{len(todo)} transcripts in {len(batches)} calls", flush=True)
    kept = dropped = 0
    with target.open("a", encoding="utf-8") as out, concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        for n, (batch, answer) in enumerate(zip(batches, pool.map(lambda b: claude([r["text"] for r in b]), batches)), 1):
            for row, text in zip(batch, answer):
                if good(text, row["text"]):
                    out.write(json.dumps({"id": row["id"], "split": row["split"], "text": text, "seconds": row["seconds"]},
                                         ensure_ascii=False) + "\n")
                    kept += 1
                else:
                    dropped += 1
            out.flush()
            if n % 10 == 0:
                print(f"{n}/{len(batches)} calls, {kept} kept, {dropped} dropped", flush=True)
    print(f"done: {kept} kept, {dropped} dropped")


if __name__ == "__main__":
    sys.exit(main())
