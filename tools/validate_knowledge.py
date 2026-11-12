"""Validate ``tag-knowledge.json`` against the contract in knowledge/schema.md.

    python -m tools.validate_knowledge [knowledge/tag-knowledge.json]

Exit code 0 = valid (warnings allowed), 1 = errors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tagviewer.conditions import OPS

KINDS = {"override", "rewrite", "ineffective", "incompatible", "requires", "side_effect", "reject",
         "conversion"}
SEVERITIES = {"high", "medium", "low", "info"}
VALID_OPS = set(OPS) | {"js", "invalid"}


def validate(kb):
    errors, warnings = [], []
    for k in ("meta", "tags", "ruleSets", "relationships"):
        if k not in kb:
            errors.append(f"missing top-level key: {k}")
    ids = set()
    aliases = {}
    for t in kb.get("tags", []):
        tid = t.get("id")
        if not tid:
            errors.append(f"tag without id: {str(t)[:80]}")
            continue
        if tid in ids:
            errors.append(f"duplicate tag id: {tid}")
        ids.add(tid)
        if t.get("parent") == "9012" and tid != f"9012.{t.get('number')}":
            errors.append(f"{tid}: id does not match number {t.get('number')}")
        if t.get("alias"):
            a = str(t["alias"]).upper()
            if a in aliases:
                errors.append(f"alias {a} used by {aliases[a]} and {tid}")
            aliases[a] = tid
        for f in ("name", "description"):
            if not t.get(f):
                warnings.append(f"{tid}: empty {f}")

    def check_rel(r, where):
        if r.get("kind") not in KINDS:
            errors.append(f"{where}: bad kind {r.get('kind')!r}")
        if r.get("severity") not in SEVERITIES:
            errors.append(f"{where}: bad severity {r.get('severity')!r}")
        for c in r.get("trigger") or []:
            if not isinstance(c, dict) or c.get("op") not in VALID_OPS or "field" not in c:
                errors.append(f"{where}: bad trigger condition {c!r}")
        for tg in r.get("tags") or []:
            if tg not in ids:
                warnings.append(f"{where}: references unknown tag {tg}")

    rel_ids = set()
    for r in kb.get("relationships", []):
        rid = r.get("id")
        if rid in rel_ids:
            errors.append(f"duplicate relationship id {rid}")
        rel_ids.add(rid)
        check_rel(r, f"relationship {rid}")
    for t in kb.get("tags", []):
        for i, it in enumerate(t.get("interactions") or []):
            check_rel(it, f"{t.get('id')} interaction {i}")
    for rs in kb.get("ruleSets", []):
        for r in rs.get("rules", []):
            for w in r.get("writes", []):
                tg = w.get("tag")
                if tg and tg != "<js>" and tg not in ids and not tg.startswith("9012."):
                    warnings.append(f"{r['id']}: writes top-level tag {tg} not in tags")
    return errors, warnings


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    path = Path(argv[0]) if argv else Path(__file__).resolve().parents[1] / "knowledge/tag-knowledge.json"
    kb = json.loads(path.read_text(encoding="utf-8"))
    errors, warnings = validate(kb)
    for w in warnings[:50]:
        print("WARN ", w)
    if len(warnings) > 50:
        print(f"WARN  ... {len(warnings) - 50} more warnings")
    for e in errors:
        print("ERROR", e)
    print(f"{len(kb.get('tags', []))} tags, {len(kb.get('relationships', []))} relationships: "
          f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
