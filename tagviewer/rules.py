"""Parse ``ai.fixmsg.properties`` into structured rules (``FixMsgConfig.FixMsgRule``).

Line shape::

    [IR=n;]<writes> :: <conditions>
    # comment              (attached to the rules that follow until a blank line)
    internal_config_include_files: a,b   (recorded, not a rule)

``writes`` is a fixmsg fragment (``9001=PEG;9012=152=1^244=1``) and may contain
``<js>...</js>`` computed values. ``IR`` restricts the rule to relay states
(0: no relay algo, 1: relay algo, 2: no parent relay, 3: parent relay).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .conditions import parse_conditions
from .fixmsg import split_quoted, unquote

_IR = re.compile(r"^IR=(\d+);")


def parse_writes(text: str) -> List[Dict[str, Any]]:
    writes: List[Dict[str, Any]] = []
    for item in split_quoted(text.strip(), ";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, val = item.split("=", 1)
        key = key.strip()
        if key in ("9012", "9050", "9052"):
            for sub in split_quoted(val, "^"):
                sub = sub.strip()
                if "=" not in sub:
                    continue
                sk, sv = sub.split("=", 1)
                sv = unquote(sv)
                writes.append({"tag": "9012." + sk.strip(), "key": sk.strip(), "value": sv.strip(),
                               "dynamic": "<js>" in sv})
        else:
            writes.append({"tag": key, "key": key, "value": val.strip(), "dynamic": "<js>" in val})
    return writes


def parse_file(path: Path | str, rule_set: Optional[str] = None,
               id_prefix: Optional[str] = None) -> Dict[str, Any]:
    """Return ``{"ruleSet", "file", "includes", "rules": [...]}``."""
    path = Path(path)
    rule_set = rule_set or path.name
    prefix = id_prefix or re.sub(r"[^A-Za-z0-9]+", "-", rule_set).strip("-")
    rules: List[Dict[str, Any]] = []
    includes: List[str] = []
    comment: List[str] = []
    order = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            s = line.strip()
            if not s:
                comment = []
                continue
            if s.startswith("#"):
                comment.append(s.lstrip("#").strip())
                continue
            if s.startswith("internal_config_include_files"):
                includes = [x.strip() for x in s.split(":", 1)[1].split(",") if x.strip()]
                continue
            if "::" not in s:
                continue
            left, right = s.split("::", 1)
            left = left.strip()
            irelay = None
            m = _IR.match(left)
            if m:
                irelay = int(m.group(1))
                left = left[m.end():]
            order += 1
            writes = parse_writes(left)
            if not writes and "<js>" in left:
                # a pure script rule: it acts on the order (e.g. _param.setEndstamp) without
                # writing a tag
                writes = [{"tag": "<js>", "key": "<js>", "value": left, "dynamic": True}]
            rules.append({
                "id": f"{prefix}:L{lineno}",
                "ruleSet": rule_set,
                "file": path.name,
                "line": lineno,
                "order": order,
                "comment": " / ".join(comment) if comment else "",
                "irelay": irelay,
                "writes": writes,
                "writesRaw": left,
                "conditions": parse_conditions(right),
                "raw": s,
            })
    return {"ruleSet": rule_set, "file": path.name, "includes": includes, "rules": rules}
