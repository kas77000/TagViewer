"""The ``ai.fixmsg.properties`` condition language: parsing and three-valued evaluation.

A condition list is the text right of ``::``, split on ``,`` (ConfigFilter splits the same
way) except inside ``<js>...</js>`` and parentheses. Each condition is one of:

* ``field OP value`` with OP in ``>= <= != !~ = ~ < >``;
* ``tag9012(X)`` / ``fixTag(N)`` / any ``name(arg)`` as the field;
* ``<js> expression </js>`` - JavaScript run by the engine (never evaluated here);
* anything else is recorded as ``op: "invalid"`` (e.g. a bare token, see C-05).

Values: ``a^b^c`` is an or-list; ``null`` means "not set"; ``~``/``!~`` are Java
``String.matches`` (full-match regex). Numbers compare numerically.

Evaluation returns ``True``, ``False`` or ``None`` (unknown: the field is not available in
the context, or the condition is JavaScript/invalid). A list is True only if all are True,
False if any is False, else None.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

OPS = (">=", "<=", "!=", "!~", "=", "~", "<", ">")
_COND = re.compile(
    r"^\s*(?P<field>[A-Za-z_][\w.]*(?:\([^)]*\))?)\s*(?P<op>>=|<=|!=|!~|=|~|<|>)\s*(?P<value>.*?)\s*$",
    re.S,
)
_FUNC = re.compile(r"^(?P<name>[A-Za-z_]\w*)\((?P<arg>[^)]*)\)$")
UNKNOWN = object()


def split_top(text: str, delim: str = ",") -> List[str]:
    """Split on ``delim`` outside ``<js>...</js>`` and parentheses."""
    out, buf, depth, i = [], [], 0, 0
    while i < len(text):
        if text.startswith("<js>", i):
            j = text.find("</js>", i)
            j = len(text) if j < 0 else j + len("</js>")
            buf.append(text[i:j])
            i = j
            continue
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        if ch == delim and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def parse_condition(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("<js>"):
        code = raw[4:]
        if code.endswith("</js>"):
            code = code[:-5]
        return {"field": "<js>", "op": "js", "value": code.strip(), "raw": raw}
    m = _COND.match(raw)
    if not m:
        return {"field": raw, "op": "invalid", "value": "", "raw": raw}
    return {"field": m.group("field"), "op": m.group("op"), "value": m.group("value"), "raw": raw}


def parse_conditions(text: str) -> List[Dict[str, Any]]:
    return [parse_condition(c) for c in split_top(text or "")]


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _eq(actual: Optional[str], expected: str) -> bool:
    if expected == "null":
        return actual is None or actual == ""
    if actual is None:
        return False
    a, e = _num(actual), _num(expected)
    if a is not None and e is not None:
        return a == e
    return str(actual).strip().lower() == expected.strip().lower()


def _match(actual: Optional[str], pattern: str) -> bool:
    if actual is None:
        return False
    try:
        return re.fullmatch(pattern, str(actual)) is not None
    except re.error:
        return False


Resolver = Callable[[str], Any]  # returns value, None (known absent) or UNKNOWN


def evaluate(cond: Dict[str, Any], resolve: Resolver) -> Optional[bool]:
    op = cond["op"]
    if op in ("js", "invalid"):
        return None
    actual = resolve(cond["field"])
    if actual is UNKNOWN:
        return None
    value = cond.get("value")
    if value is None:          # JSON null written by hand/agents means the keyword null
        value = "null"
    cond = {**cond, "value": value}
    alts = [v.strip() for v in str(value).split("^")]
    sval = None if actual is None else str(actual)
    if op == "=":
        return any(_eq(sval, v) for v in alts)
    if op == "!=":
        return not any(_eq(sval, v) for v in alts)
    if op == "~":
        return any(_match(sval, v) for v in alts)
    if op == "!~":
        return not any(_match(sval, v) for v in alts)
    a, e = _num(sval), _num(cond["value"])
    if a is None or e is None:
        return None if sval is None else False
    return {"<": a < e, "<=": a <= e, ">": a > e, ">=": a >= e}[op]


def evaluate_all(conds: List[Dict[str, Any]], resolve: Resolver):
    """Return (result, unresolved_raw_conditions)."""
    unresolved: List[str] = []
    for c in conds:
        r = evaluate(c, resolve)
        if r is False:
            return False, []
        if r is None:
            unresolved.append(c["raw"])
    return (None if unresolved else True), unresolved


def func_call(field: str):
    """``tag9012(154)`` -> ("tag9012", "154"); plain field -> (None, None)."""
    m = _FUNC.match(field)
    return (m.group("name"), m.group("arg").strip()) if m else (None, None)
