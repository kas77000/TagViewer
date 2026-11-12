"""Parse an order's ``fixmsg`` the way ``com.kas.ai.Parameters`` does.

Shape (from Parameters.java):

* top level ``;``-separated ``tag=value`` items (``_CFIX_TAG_DELIMITER``);
* ``9012`` carries ``^``-separated ``subtag=value`` items (``_CFIX_TAG_SUB_DELIMITER``),
  values may be quoted with ``<tq>...</tq>`` and then may contain ``^``;
* ``9050``/``9052`` are appended to ``9012``; several ``9012=`` segments are merged in
  order, so a later sub-tag value overrides an earlier one;
* the stored ``fixmsg`` grows: the client message first, then one segment per
  ``ai.fixmsg.properties`` rule that fired (``Parameters.parseFixMsg``), so repeated
  sub-tags in the string are the *observed* override history.

Sub-tags may be written by number (``154``) or by alias (``PQS``); ``canonical`` maps an
alias to its number using the knowledge base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

TAG_DELIM = ";"
SUB_DELIM = "^"
PAIR_DELIM = "="
QBEG, QEND = "<tq>", "</tq>"
NESTED_TAGS = ("9012",)
APPEND_TO_9012 = ("9050", "9052")


@dataclass
class Occurrence:
    """One appearance of a tag or sub-tag in the fixmsg, in string order."""

    key: str            # as written: "9001", "154", "PQS"
    tag_id: str         # canonical id: "9001" or "9012.154"
    value: str
    segment: int        # index of the top-level item it came from
    position: int       # global order of appearance


@dataclass
class ParsedFixMsg:
    raw: str
    top: Dict[str, str] = field(default_factory=dict)      # last value per top-level tag
    sub: Dict[str, str] = field(default_factory=dict)      # last value per 9012 sub-tag id
    occurrences: List[Occurrence] = field(default_factory=list)
    segments9012: int = 0
    errors: List[str] = field(default_factory=list)

    def history(self, tag_id: str) -> List[Occurrence]:
        return [o for o in self.occurrences if o.tag_id == tag_id]

    def overridden(self) -> Dict[str, List[Occurrence]]:
        """Tag ids written more than once with at least two different values."""
        out: Dict[str, List[Occurrence]] = {}
        for tid in dict.fromkeys(o.tag_id for o in self.occurrences):
            h = self.history(tid)
            if len(h) > 1 and len({o.value for o in h}) > 1:
                out[tid] = h
        return out


def split_quoted(text: str, delim: str) -> List[str]:
    """Split on ``delim`` except inside ``<tq>...</tq>`` (Util.split semantics)."""
    out, buf, i, depth = [], [], 0, 0
    while i < len(text):
        if text.startswith(QBEG, i):
            depth += 1
            buf.append(QBEG)
            i += len(QBEG)
            continue
        if text.startswith(QEND, i) and depth:
            depth -= 1
            buf.append(QEND)
            i += len(QEND)
            continue
        ch = text[i]
        if ch == delim and not depth:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out


def unquote(v: str) -> str:
    v = v.strip()
    if v.startswith(QBEG) and v.endswith(QEND):
        return v[len(QBEG):-len(QEND)]
    return v


def parse(raw: Optional[str], canonical: Optional[Callable[[str], str]] = None,
          tag_delim: str = TAG_DELIM) -> ParsedFixMsg:
    """Parse ``raw``. ``canonical`` maps a sub-tag key (number or alias) to its number."""
    canon = canonical or (lambda k: k)
    res = ParsedFixMsg(raw=raw or "")
    if not raw:
        return res
    pos = 0
    for seg_idx, item in enumerate(split_quoted(raw, tag_delim)):
        item = item.strip()
        if not item:
            continue
        if PAIR_DELIM not in item:
            res.errors.append(f"item without '=': {item!r}")
            continue
        key, val = item.split(PAIR_DELIM, 1)
        key, val = key.strip(), val.strip()
        if not val:
            continue  # stripFixTags: an empty value is treated as absent
        if key in NESTED_TAGS or key in APPEND_TO_9012:
            res.segments9012 += 1
            for sub_item in split_quoted(val, SUB_DELIM):
                sub_item = sub_item.strip()
                if not sub_item:
                    continue
                if PAIR_DELIM not in sub_item:
                    res.errors.append(f"9012 item without '=': {sub_item!r}")
                    continue
                sk, sv = sub_item.split(PAIR_DELIM, 1)
                sk, sv = sk.strip(), unquote(sv)
                if not sk or not sv:
                    continue
                tid = "9012." + canon(sk)
                res.sub[tid] = sv
                res.occurrences.append(Occurrence(sk, tid, sv, seg_idx, pos))
                pos += 1
            continue
        res.top[key] = val
        res.occurrences.append(Occurrence(key, key, val, seg_idx, pos))
        pos += 1
    return res


_NUM = re.compile(r"^\d+$")


def is_numeric_key(k: str) -> bool:
    return bool(_NUM.match(k))
