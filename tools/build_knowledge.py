"""Assemble ``knowledge/tag-knowledge.json`` from the generated parts.

Inputs (all produced by the regeneration skill, see skills/claude/tag-knowledge/SKILL.md):

* ``<parts>/global.json``          parsing, algorithms, conditionFields, topLevelTags,
                                   relationships, knownConflicts
* ``<parts>/tags_*.json``          arrays of 9012 sub-tag definitions
* ``<build>/raw_java_tags.json``   mechanical extraction (completeness check / stubs)
* ``*.fixmsg.properties`` files    parsed into ruleSets (tagviewer.rules)
* ``knowledge/curated/*.json``     optional hand corrections, merged last, by tag id

    python -m tools.build_knowledge --ai3 ../ai3 [--version 2026-11-13.1]
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
from pathlib import Path

from tagviewer.rules import parse_file

ROOT = Path(__file__).resolve().parents[1]


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def stub(raw):
    num = raw["number"]
    return {
        "id": f"9012.{num}", "number": num, "parent": "9012", "alias": raw.get("alias"),
        "name": raw.get("alias") or f"9012 sub-tag {num}", "category": "other",
        "description": "Not yet documented. Parsed by " + raw["method"].split("(")[0].split()[-1]
                       + f"; sets {', '.join(raw.get('assigns') or []) or 'no field'}.",
        "valueFormat": "", "type": "string", "allowedValues": [], "default": None, "example": None,
        "appliesTo": [], "algorithmDependent": [], "interactions": [],
        "internal": int(num) >= 1500, "confidence": "low",
        "sources": [f"{raw['file']}:{raw['line']}"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai3", required=True, help="path to the ai3 project")
    ap.add_argument("--parts", default=str(ROOT / "knowledge/build/parts"))
    ap.add_argument("--raw", default=str(ROOT / "knowledge/build/raw_java_tags.json"))
    ap.add_argument("--curated", default=str(ROOT / "knowledge/curated"))
    ap.add_argument("--out", default=str(ROOT / "knowledge/tag-knowledge.json"))
    ap.add_argument("--version", default=None)
    ap.add_argument("--properties", nargs="*", default=None,
                    help="rule files; default: every *fixmsg.properties in <ai3>/config")
    a = ap.parse_args(argv)

    ai3 = Path(a.ai3)
    parts = Path(a.parts)
    glob_ = load(parts / "global.json") if (parts / "global.json").exists() else {}

    tags = {}
    for t in glob_.get("topLevelTags", []):
        t.setdefault("parent", None)
        tags[t["id"]] = t
    for f in sorted(glob.glob(str(parts / "tags_*.json"))):
        for t in load(f):
            t["id"] = t.get("id") or f"9012.{t['number']}"
            t.setdefault("parent", "9012")
            tags[t["id"]] = t

    stubs = 0
    if Path(a.raw).exists():
        for raw in load(a.raw)["tags"]:
            if f"9012.{raw['number']}" not in tags:
                tags[f"9012.{raw['number']}"] = stub(raw)
                stubs += 1

    # BCORE_Tags dictionary (tools/import_bcore_csv.py): attach, and fill gaps in stubs
    bcore_file = parts / "bcore.json"
    if bcore_file.exists():
        for b in load(bcore_file):
            t = tags.get(b["id"])
            if t is None:
                t = tags[b["id"]] = stub({"number": b["number"], "alias": None, "method": "(not in Parameters.java)",
                                          "assigns": [], "file": b.get("bcoreSource", "BCORE_Tags"), "line": 0})
                t["description"] = "Listed in the BCORE_Tags dictionary but not parsed by Parameters.java."
            t["bcore"] = b["bcore"]
            if b.get("clientNumber"):
                t["clientNumber"] = b["clientNumber"]
            bc = b["bcore"]
            if t.get("confidence") == "low":
                name = bc.get("tagName") or (bc.get("interface") or "").split(",")[0].strip()
                if name and (not t.get("name") or t["name"].startswith("9012 sub-tag")):
                    t["name"] = name
                desc = " ".join(x for x in (bc.get("comments"), bc.get("description")) if x)
                if desc:
                    t["description"] = desc
                if bc.get("example") and not t.get("example"):
                    t["example"] = {"value": bc["example"], "explanation": "from BCORE_Tags"}
                if bc.get("availability") and not t.get("appliesTo"):
                    t["appliesTo"] = [x.strip() for x in bc["availability"].split(",") if x.strip()]
                t["confidence"] = "medium"
            t.setdefault("sources", []).append(f"{b.get('bcoreSource', 'BCORE_Tags')}:TagNumber={b['number']}")

    curated = Path(a.curated)
    rel_fixes = {}
    if curated.exists():
        for f in sorted(curated.glob("*.json")):
            for fix in load(f):
                if fix.get("object") == "relationship":
                    rel_fixes[fix["id"]] = {k: v for k, v in fix.items() if k != "object"}
                    continue
                base = tags.setdefault(fix["id"], {"id": fix["id"]})
                base.update(fix)
    for r in glob_.get("relationships", []):
        if r.get("id") in rel_fixes:
            r.update(rel_fixes[r["id"]])

    def sort_key(t):
        num = str(t.get("number", "0"))
        return (0 if t.get("parent") is None else 1, int(num) if num.isdigit() else 10 ** 9, num)


    props = a.properties or sorted(str(p) for p in (ai3 / "config").glob("*fixmsg.properties"))
    rule_sets = [parse_file(p) for p in props]

    # ---- normalise aliases to numbers everywhere (9012.PQS -> 9012.1546, tag9012(PQS) -> tag9012(1546))
    alias = {str(t["alias"]).upper(): str(t["number"]) for t in tags.values()
             if t.get("parent") == "9012" and t.get("alias")}

    def norm_tag(tid):
        if isinstance(tid, str) and tid.startswith("9012."):
            k = tid[5:]
            return "9012." + alias.get(k.upper(), k)
        if isinstance(tid, str) and tid.startswith("fixTag(") and tid.endswith(")"):
            return tid[7:-1]
        return tid

    def norm_conds(conds):
        for c in conds or []:
            if c.get("value") is None and c.get("op") not in ("js", "invalid"):
                c["value"] = "null"
            f = str(c.get("field", ""))
            if f.lower().startswith("tag9012(") and f.endswith(")"):
                k = f[8:-1].strip()
                c["field"] = f"tag9012({alias.get(k.upper(), k)})"
        return conds

    def norm_rel(r):
        r["tags"] = [norm_tag(x) for x in r.get("tags") or []]
        norm_conds(r.get("trigger"))
        return r

    for t in tags.values():
        for it in t.get("interactions") or []:
            norm_rel(it)
    rels = [norm_rel(r) for r in glob_.get("relationships", [])]
    for c in glob_.get("knownConflicts", []):
        c["tags"] = [norm_tag(x) for x in c.get("tags") or []]

    # ---- config-only 9012 keys: written/tested by rules but not parsed by the engine
    usage = {}
    for rs in rule_sets:
        for r in rs["rules"]:
            for w in r["writes"]:
                if w["tag"].startswith("9012."):
                    usage.setdefault(w["key"], {"writes": [], "reads": []})["writes"].append(f"{r['file']}:{r['line']}")
            for c in r["conditions"]:
                f = c["field"]
                if f.lower().startswith(("tag9012(", "9012(")) and f.endswith(")"):
                    k = f[f.index("(") + 1:-1].strip()
                    usage.setdefault(k, {"writes": [], "reads": []})["reads"].append(f"{r['file']}:{r['line']}")
    config_keys = 0
    for key, u in sorted(usage.items()):
        num = alias.get(key.upper(), key)
        tid = f"9012.{num}"
        if tid in tags or not key or key.startswith("<"):
            continue
        config_keys += 1
        tags[tid] = {
            "id": tid, "number": key, "parent": "9012", "alias": None, "name": key,
            "category": "config-key",
            "description": "Config-only key: the engine has no parser for it (it is kept as-is in the 9012 map), "
                           "but ai.fixmsg.properties rules write it and/or test it with tag9012(" + key + ") to "
                           "steer which other rules apply. Its effect is the effect of those rules.",
            "valueFormat": "", "type": "string", "allowedValues": [], "default": None, "example": None,
            "appliesTo": [], "algorithmDependent": [], "interactions": [], "internal": False,
            "confidence": "medium",
            "usedByRules": {"writes": sorted(set(u["writes"])), "reads": sorted(set(u["reads"]))},
            "sources": sorted(set(u["writes"] + u["reads"]))[:20],
        }

    version = a.version or dt.date.today().isoformat() + ".1"
    kb = {
        "meta": {
            "schemaVersion": 1, "version": version,
            "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generatedBy": "tools/build_knowledge.py",
            "sources": ["ai3/src/com/kas/ai/Parameters.java", "ai3/src/com/kas/ai/*.java",
                        *[f"ai3/config/{Path(p).name}" for p in props], "ai3/*.md",
                        "ai3/config/AI-FIXMSG-CONFLICTS.md"],
            "notes": f"{stubs} sub-tags had no generated definition and were stubbed; "
                     f"{config_keys} config-only 9012 keys documented from the rule files.",
        },
        "parsing": glob_.get("parsing", {
            "tagDelimiter": ";", "pairDelimiter": "=", "subDelimiter": "^",
            "quote": ["<tq>", "</tq>"], "nestedTags": ["9012"], "appendTo9012": ["9050", "9052"]}),
        "algorithms": glob_.get("algorithms", []),
        "clientAlgorithmTemplates": glob_.get("clientAlgorithmTemplates", []),
        "conditionFields": glob_.get("conditionFields", []),
        "tags": sorted(tags.values(), key=sort_key),
        "ruleSets": rule_sets,
        "relationships": rels,
        "knownConflicts": glob_.get("knownConflicts", []),
    }
    Path(a.out).write_text(json.dumps(kb, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(kb['tags'])} tags ({stubs} stubs), {sum(len(r['rules']) for r in rule_sets)} rules in "
          f"{len(rule_sets)} rule sets, {len(kb['relationships'])} relationships, "
          f"{len(kb['knownConflicts'])} conflicts -> {a.out}")


if __name__ == "__main__":
    main()
