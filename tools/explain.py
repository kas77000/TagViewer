"""Explain a fixmsg locally, without kdb or the share - for checks and for agents.

    python -m tools.explain "9001=VWAP;9012=154=0^PQS=0.5,1,0,1" --side buy --algo VWAP
    python -m tools.explain --order order.json --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tagviewer.analyzer import analyze

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("fixmsg", nargs="?")
    ap.add_argument("--order", help="JSON file with a target row (needs a fixmsg column)")
    ap.add_argument("--side")
    ap.add_argument("--algo")
    ap.add_argument("--sym")
    ap.add_argument("--context", action="append", default=[], help="field=value, e.g. compositeExchangeCode=HK")
    ap.add_argument("--rule-set", default="ai.fixmsg.properties")
    ap.add_argument("--kb", default=str(ROOT / "knowledge" / "tag-knowledge.json"))
    ap.add_argument("--json", action="store_true", help="print the full JSON result")
    a = ap.parse_args(argv)

    order = json.loads(Path(a.order).read_text(encoding="utf-8")) if a.order else {}
    if a.fixmsg:
        order["fixmsg"] = a.fixmsg
    for k in ("side", "algo", "sym"):
        if getattr(a, k):
            order[k] = getattr(a, k)
    if not order.get("fixmsg"):
        ap.error("give a fixmsg or --order")
    extra = dict(c.split("=", 1) for c in a.context)
    kb = json.loads(Path(a.kb).read_text(encoding="utf-8"))
    res = analyze(order, kb, rule_set=a.rule_set, extra_context=extra)
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0
    print(f"{res['counts']}")
    print("\nTAGS")
    for t in res["tags"]:
        label = (f"9012/{t['number']}" if t["parent"] else t["id"]) + (f" ({t['alias']})" if t.get("alias") else "")
        print(f"  {label:<22} = {t['value']:<20} {t.get('name', '')}" + (f"  [{t['valueMeaning']}]" if t.get("valueMeaning") else ""))
    print("\nEFFECTS")
    for e in res["effects"]:
        print(f"  [{e['severity']:<6}] {e['status']:<8} {e['kind']:<15} {e['title']}")
        print(f"           {e['explanation'][:300]}")
        if e.get("unresolvedConditions"):
            print(f"           depends on: {', '.join(e['unresolvedConditions'])[:200]}")
    if res["overrideChains"]:
        print("\nOVERRIDES")
        for c in res["overrideChains"]:
            print("  " + c["label"] + ": " + " -> ".join(f"{s['value']}@{s['source']}" for s in c["steps"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
