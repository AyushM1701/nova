"""Review how Nova routed your requests, to see whether a learned router (plan Phase 6) would be worth having.

    python D:/projects/NOVA/helpers/route_review.py

Nova logs one `route` line per request: tier 1 (a built-in command, no AI), 2 (the small model) or 3 (the full model or a
background job). This copies new ones into data/route-review.csv. Open that file in a spreadsheet and put the tier the
request should have gone to in the `correct_tier` column, only where it went wrong or you're sure it went right. Run this
again to see where you stand against the gate: 4 weeks of logging, 200 requests reviewed, and more than 5% of them
routed wrongly. Until then rules-first routing is enough. Stdlib only, so any Python runs it."""
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["t", "text", "tier", "why", "correct_tier"]
GATE = {"days": 28, "reviewed": 200, "wrong": 0.05}


def review(logs=ROOT / "logs", table=ROOT / "data" / "route-review.csv", now=None):
    """Add new `route` log lines to the table (keeping the labels already there) and return where the gate stands."""
    rows = {}
    if table.exists():
        with table.open(encoding="utf-8", newline="") as f:
            rows = {r["t"]: r for r in csv.DictReader(f)}
    first = None
    for path in sorted(logs.glob("nova-*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") == "route":
                first = min(first or e["t"], e["t"])
                rows.setdefault(str(e["t"]), {"t": e["t"], "text": e.get("text", ""), "tier": e.get("tier", ""),
                                              "why": e.get("why", ""), "correct_tier": ""})
    table.parent.mkdir(parents=True, exist_ok=True)
    with table.open("w", encoding="utf-8", newline="") as f:
        out = csv.DictWriter(f, FIELDS, extrasaction="ignore")
        out.writeheader()
        out.writerows(sorted(rows.values(), key=lambda r: float(r["t"])))
    labelled = [r for r in rows.values() if str(r.get("correct_tier", "")).strip() in ("1", "2", "3")]
    wrong = [r for r in labelled if str(r["correct_tier"]).strip() != str(r["tier"])]
    days = ((now or time.time()) - first) / 86400 if first else 0
    share = len(wrong) / len(labelled) if labelled else 0
    return {"logged": len(rows), "days": round(days, 1), "reviewed": len(labelled), "wrong": len(wrong),
            "wrong_share": round(share, 3), "table": str(table),
            "met": days >= GATE["days"] and len(labelled) >= GATE["reviewed"] and share > GATE["wrong"]}


def main():
    r = review()
    print(f"{r['logged']} requests logged over {r['days']} days (gate: {GATE['days']}). Table: {r['table']}")
    print(f"{r['reviewed']} reviewed (gate: {GATE['reviewed']}), {r['wrong']} routed wrongly = {r['wrong_share']:.1%} "
          f"(gate: more than {GATE['wrong']:.0%}).")
    print("Gate met: a learned router may be worth building." if r["met"] else
          "Gate not met: rules-first routing is enough for now.")


if __name__ == "__main__":
    sys.exit(main())
