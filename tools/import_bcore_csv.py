"""Convert a BCORE_Tags CSV export (the tag dictionary) into a knowledge part.

Header (from the BCORE_Tags_2026.csv export)::

    TagNumber,version,tagName,interface,comments,availability,implemented,example,
    modifiedBy,modifiedTime,oldTagInfo,clientTagNumber,description,parametersField,validValues

Rows are versioned; the latest ``modifiedTime`` (then highest ``version``) per TagNumber
wins. Fields are quoted and contain commas/newlines, so this uses the csv module. The
TagNumber is the 9012 sub-tag number. ``NULL`` means empty.

    python -m tools.import_bcore_csv BCORE_Tags_2026.csv [more.csv] --out knowledge/build/parts/bcore.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def clean(v):
    v = (v or "").strip()
    return "" if v.upper() == "NULL" else v


def load_rows(paths):
    best = {}
    for p in paths:
        with open(p, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                row = {(k or "").strip(): clean(v) for k, v in row.items()}
                num = row.get("TagNumber", "")
                if not num:
                    continue
                key = (row.get("modifiedTime", ""), int(row["version"]) if row.get("version", "").isdigit() else 0)
                if num not in best or key >= best[num][0]:
                    best[num] = (key, row, str(p))
    return best


def to_part(best):
    out = []
    for num, (_, r, src) in sorted(best.items(), key=lambda kv: (len(kv[0]), kv[0])):
        entry = {
            "id": f"9012.{num}", "number": num,
            "bcore": {k: r.get(k, "") for k in ("tagName", "interface", "comments", "availability", "implemented",
                                                  "example", "clientTagNumber", "description",
                                                  "parametersField", "validValues", "version", "modifiedTime",
                                                  "modifiedBy")},
            "bcoreSource": Path(src).name,
        }
        if r.get("clientTagNumber"):
            entry["clientNumber"] = r["clientTagNumber"]
        out.append(entry)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "knowledge/build/parts/bcore.json"))
    a = ap.parse_args(argv)
    part = to_part(load_rows(a.csv))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(part, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(part)} tags from {len(a.csv)} CSV file(s) -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
