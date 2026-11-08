"""Step 2: every transcript the way Nova should type it. Hindi and Hinglish in Roman letters ("continue पर click करें"
-> "continue par click karein"); English all in capitals with no punctuation (LibriSpeech) gets its casing and
punctuation back, words unchanged; other English stays as it is. Claude (the Claude Code CLI, Haiku) does 50 lines a
call, 4 calls at once.

    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/romanize.py

Reads manifest.jsonl, writes roman.jsonl {id, split, lang, text, seconds, source}; a line that comes back wrong is left
out. Resumable: run it again to fill in what a failed call left out."""
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT  # noqa: E402

BATCH, WORKERS = 50, 4
ROMAN = """Convert each numbered line to Roman Hinglish, the way an Indian types Hindi in a chat message.
- Write exactly the words that were spoken. Transliterate every Hindi word into Latin letters, even formal or rare
  ones (निष्पादित -> nishpadit, संस्थापित -> sansthapit); never replace a Hindi word with an English one.
- English words (already in Latin letters) keep normal English spelling.
- Use common chat spellings: hai, hain, karein, kya, mein, nahi, aap, yeh, woh, kaise, liye, bhi, ki, ke, ko.
- Write numbers as digits. Lowercase except names and acronyms. No Devanagari at all.
- Return exactly the same numbers, one line each, as "N. text", and nothing else."""
PUNCTUATE = """Each numbered line is an English transcript in capitals with no punctuation. Rewrite it with normal
sentence casing and punctuation (commas, full stops, question marks, apostrophes such as don't and it's).
- Keep exactly the same words in the same order: add or remove no words, fix no grammar.
- Return exactly the same numbers, one line each, as "N. text", and nothing else."""
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def claude(prompt, lines):
    exe = shutil.which("claude") or shutil.which("claude.cmd")
    numbered = "\n".join(f"{n}. {text}" for n, text in enumerate(lines, 1))
    try:
        r = subprocess.run([exe, "-p", "--model", "haiku", "--tools", "", "--no-session-persistence",
                            "--system-prompt", prompt], input=numbered, capture_output=True, text=True, encoding="utf-8",
                           timeout=300, env=dict(os.environ))
    except subprocess.TimeoutExpired:  # this batch is left out; the next run tries it again
        return [None] * len(lines)
    got = {}
    for line in r.stdout.splitlines():
        m = re.match(r"\s*(\d+)\.\s*(.+)", line)
        if m:
            got[int(m.group(1))] = m.group(2).strip()
    return [got.get(n) for n in range(1, len(lines) + 1)]


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("'", ""))


def good(text, row):
    if not text or DEVANAGARI.search(text):
        return False
    if row.get("lang") == "en":  # punctuated: the same words, nothing more
        return words(text) == words(row["text"])
    return 0.4 < len(text) / max(1, len(row["text"])) < 2.5


def job(row):
    """The prompt this row needs, or None when it is written as it is (English already cased)."""
    if row.get("lang", "hi") == "hi":
        return ROMAN
    return PUNCTUATE if row["text"].isupper() else None


def main():
    rows = [json.loads(line) for line in (OUT / "manifest.jsonl").open(encoding="utf-8")]
    target = OUT / "roman.jsonl"
    done = {json.loads(line)["id"] for line in target.open(encoding="utf-8")} if target.exists() else set()
    todo = [r for r in rows if r["id"] not in done]
    keep = lambda row, text: out.write(json.dumps({"id": row["id"], "split": row["split"], "lang": row.get("lang", "hi"),  # noqa: E731
                                                   "text": text, "seconds": row["seconds"], "source": row.get("source", "")},
                                                  ensure_ascii=False) + "\n")
    batches = []
    for prompt in (ROMAN, PUNCTUATE):
        mine = [r for r in todo if job(r) == prompt]
        batches += [(prompt, mine[i:i + BATCH]) for i in range(0, len(mine), BATCH)]
    print(f"{len(todo)} transcripts, {len(batches)} calls", flush=True)
    kept = dropped = 0
    with target.open("a", encoding="utf-8") as out, concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        for row in todo:
            if job(row) is None:
                keep(row, row["text"])
                kept += 1
        answers = pool.map(lambda b: claude(b[0], [r["text"] for r in b[1]]), batches)
        for n, ((_, batch), answer) in enumerate(zip(batches, answers), 1):
            for row, text in zip(batch, answer):
                if good(text, row):
                    keep(row, text)
                    kept += 1
                else:
                    dropped += 1
            out.flush()
            if n % 10 == 0:
                print(f"{n}/{len(batches)} calls, {kept} kept, {dropped} dropped", flush=True)
    print(f"done: {kept} kept, {dropped} dropped (run again to retry those)")


if __name__ == "__main__":
    sys.exit(main())
