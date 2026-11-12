"""Mechanically extract every 9012 sub-tag parser from ``Parameters.java``.

``Parameters.setupParamParser`` registers each method named ``__p_<number>[_<ALIAS>]`` as
the parser of 9012 sub-tag ``<number>`` (alias ``<ALIAS>``). This tool lists them with
their source span, body, the fields they assign, and where those fields are read
elsewhere in the source tree - the raw material an agent turns into tag definitions.

It also lists the top-level FIX tag constants (``_C..._PARAMETER = "9001"``).

    python -m tools.extract_java_tags --src <ai3>/src --out knowledge/build/raw_java_tags.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

METHOD = re.compile(r"^\s*(?:private|public|protected)?\s*(?:static\s+)?void\s+__p_(\d+)(?:_(\w+))?\s*\(")
CONST = re.compile(r'static\s+final\s+String\s+(_C\w*PARAMETER)\s*=\s*"([^"]*)"')
ASSIGN = re.compile(r"\b(_[A-Za-z]\w*)\s*(?:=(?!=)|\+=|-=|\*=)")


def method_span(lines, start):
    depth, seen = 0, False
    for i in range(start, len(lines)):
        code = re.sub(r'"(?:\\.|[^"\\])*"', '""', lines[i].split("//", 1)[0])
        depth += code.count("{") - code.count("}")
        if "{" in code:
            seen = True
        if seen and depth <= 0:
            return i
    return start


def leading_comment(lines, start):
    out, i = [], start - 1
    while i >= 0 and (lines[i].strip().startswith(("//", "*", "/*")) or lines[i].strip().endswith("*/")):
        out.insert(0, lines[i].strip())
        i -= 1
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="ai3/src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-usages", type=int, default=12)
    a = ap.parse_args(argv)
    src = Path(a.src)
    params = next(src.rglob("Parameters.java"))
    lines = params.read_text(encoding="utf-8", errors="replace").splitlines()

    java = {p: p.read_text(encoding="utf-8", errors="replace").splitlines()
            for p in src.rglob("*.java") if "pics" not in p.parts}

    tags, consts = [], {}
    for i, line in enumerate(lines):
        c = CONST.search(line)
        if c:
            consts[c.group(1)] = {"value": c.group(2), "line": i + 1}
        m = METHOD.match(line)
        if not m:
            continue
        end = method_span(lines, i)
        body = "\n".join(lines[i:end + 1])
        fields = sorted({f for f in ASSIGN.findall("\n".join(lines[i + 1:end + 1]))})
        tags.append({"number": m.group(1), "alias": m.group(2), "method": line.strip(),
                     "file": params.name, "line": i + 1, "endLine": end + 1,
                     "comment": leading_comment(lines, i), "body": body, "assigns": fields})

    # where are the assigned fields read? one pass builds identifier -> lines index
    ident = re.compile(r"\b_[A-Za-z]\w*\b")
    wanted = {f for t in tags for f in t["assigns"][:4]}
    index = {f: [] for f in wanted}
    for path, ls in java.items():
        for j, l in enumerate(ls):
            for f in set(ident.findall(l)) & wanted:
                if len(index[f]) < 200:
                    index[f].append((path.name, j + 1, l.strip()[:200]))
    for t in tags:
        uses = []
        for f in t["assigns"][:4]:
            for name, ln, text in index[f]:
                if name == params.name and t["line"] <= ln <= t["endLine"]:
                    continue
                uses.append(f"{name}:{ln}: {text}")
                if len(uses) >= a.max_usages:
                    break
        t["usages"] = uses

    out = {"source": str(params), "count": len(tags),
           "topLevelConstants": [{"name": k, **v} for k, v in consts.items()], "tags": tags}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(tags)} sub-tag parsers, {len(consts)} constants -> {a.out}")


if __name__ == "__main__":
    main()
