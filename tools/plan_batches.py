"""Split the extracted sub-tags into batches for agents, optionally only what changed.

    python -m tools.plan_batches                       # every tag, batches of 110
    python -m tools.plan_batches --changed-only        # new/changed parser bodies vs last run
    python -m tools.plan_batches --size 60 --out knowledge/build/batches

A tag counts as changed when its parser body (whitespace-insensitive) differs from the
snapshot ``knowledge/build/raw_java_tags.prev.json`` written by the previous run, or when
it has no definition yet in ``knowledge/tag-knowledge.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "knowledge" / "build"


def body_hash(t):
    return hashlib.sha1("".join(t["body"].split()).encode()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(BUILD / "raw_java_tags.json"))
    ap.add_argument("--prev", default=str(BUILD / "raw_java_tags.prev.json"))
    ap.add_argument("--kb", default=str(ROOT / "knowledge" / "tag-knowledge.json"))
    ap.add_argument("--out", default=str(BUILD / "batches"))
    ap.add_argument("--size", type=int, default=110)
    ap.add_argument("--changed-only", action="store_true")
    a = ap.parse_args(argv)

    raw = json.loads(Path(a.raw).read_text(encoding="utf-8"))["tags"]
    raw.sort(key=lambda t: int(t["number"]))
    selected, reasons = raw, {}
    if a.changed_only:
        prev = {}
        if Path(a.prev).exists():
            prev = {t["number"]: body_hash(t) for t in json.loads(Path(a.prev).read_text(encoding="utf-8"))["tags"]}
        documented = set()
        if Path(a.kb).exists():
            kb = json.loads(Path(a.kb).read_text(encoding="utf-8"))
            documented = {t["id"] for t in kb.get("tags", []) if t.get("confidence") != "low"
                          or "Not yet documented" not in str(t.get("description"))}
        selected = []
        for t in raw:
            if f"9012.{t['number']}" not in documented:
                reasons[t["number"]] = "undocumented"
            elif t["number"] not in prev:
                reasons[t["number"]] = "new"
            elif prev[t["number"]] != body_hash(t):
                reasons[t["number"]] = "changed"
            else:
                continue
            selected.append(t)

    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    n = 0
    for i in range(0, len(selected), a.size):
        n += 1
        (out / f"batch_{n}.json").write_text(json.dumps(selected[i:i + a.size], indent=1), encoding="utf-8")
    print(f"{len(selected)} of {len(raw)} sub-tags in {n} batch(es) -> {out}")
    if reasons:
        from collections import Counter
        print("reasons:", dict(Counter(reasons.values())))
    shutil.copyfile(a.raw, a.prev)   # snapshot for the next --changed-only run


if __name__ == "__main__":
    main()
