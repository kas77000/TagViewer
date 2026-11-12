"""Explain one order: decode its tags and work out the effects of their combination.

Inputs: the kdb ``target`` row (dict), the knowledge base (dict), optional extra context
(e.g. from ``target_stock``). Output: the ``order``/``tags``/``effects``/``overrideChains``
parts of a TagViewer response (see docs/protocol.md).

How the effects are found
-------------------------
1. **Observed history.** ``Parameters.parseFixMsg`` stores the client message first and
   then appends one segment per ``ai.fixmsg.properties`` rule that fired. A rule whose
   literal writes appear (in order) after the client part is *applied* - confirmed by the
   fixmsg itself. The client part is what precedes the first such segment.
2. **Simulation.** Starting from the client part, the rules are evaluated top to bottom
   (last writer wins, ``tag9012(X)=null`` guards see earlier writes). Each rule is
   ``applied`` (seen in the fixmsg), ``fires`` (all conditions true), ``may_fire`` (no
   condition false, some unknown - market data, ``<js>``, engine-only fields) or skipped.
   When the fixmsg shows rule segments, an unseen literal rule is known not to have fired.
3. **Relationships** from the knowledge base (and each tag's ``interactions``) are
   evaluated against the final tags + order fields; one whose tag conditions all hold is
   reported as ``fires`` or ``may_fire``.
4. **Known conflicts** (C-xx) are reported when a rule they cite was applied/may fire.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import fixmsg as fm
from .conditions import UNKNOWN, evaluate_all, func_call
from .fixmsg import split_quoted

DEFAULT_RULE_SET = "ai.fixmsg.properties"
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}
STATUS_RANK = {"applied": 0, "fires": 1, "may_fire": 2}
REJECT_KEYS = {"9012.KO", "9012.1525"}
ALGO_KEYS = {"9001", "9012.1"}

# order field -> target column (kdb), lower-case
ORDER_FIELDS = {
    "side": "side", "size": "size", "basket": "basket", "symbol": "sym", "trader": "trader",
    "price": "limit_price", "doClose": "doclose", "doOpen": "doopen", "doCash": "docash",
    "portfolio": "portfolio", "wave": "wave", "tif": "tif", "otype": "otype",
}
SIDE_ALIASES = {"ss": "sellshort", "short": "sellshort", "sell_short": "sellshort",
                "sellshort": "sellshort", "sshort": "sellshort", "b": "buy", "s": "sell"}


class KnowledgeIndex:
    """Fast lookups over a knowledge-base dict."""

    def __init__(self, kb: Dict[str, Any]):
        self.kb = kb
        self.tags: Dict[str, Dict[str, Any]] = {t["id"]: t for t in kb.get("tags", [])}
        self.alias: Dict[str, str] = {}
        for t in kb.get("tags", []):
            if t.get("parent") == "9012" and t.get("alias"):
                self.alias[str(t["alias"]).upper()] = str(t["number"])
        self.relationships: List[Dict[str, Any]] = list(kb.get("relationships", []))
        seen = {r.get("id") for r in self.relationships}
        for t in kb.get("tags", []):
            for i, it in enumerate(t.get("interactions") or [], 1):
                rid = it.get("id") or f"INT-{t['id']}-{i:02d}"
                if rid in seen:
                    continue
                srcs = [str(s) for s in it.get("sources") or []]
                if srcs and all(".properties" in s for s in srcs):
                    continue  # restates a config rule: the rules are evaluated directly
                seen.add(rid)
                r = dict(it)
                r["id"] = rid
                r.setdefault("tags", [t["id"]])
                self.relationships.append(r)
        self.rule_sets = {rs["ruleSet"]: rs for rs in kb.get("ruleSets", [])}
        self.conflicts = kb.get("knownConflicts", [])

    def canonical(self, key: str) -> str:
        k = key.strip()
        if fm.is_numeric_key(k):
            return k
        return self.alias.get(k.upper(), k)

    def tag(self, tag_id: str) -> Optional[Dict[str, Any]]:
        return self.tags.get(tag_id)


# --------------------------------------------------------------------------- state


class State:
    def __init__(self, top: Dict[str, str], sub: Dict[str, str]):
        self.top = dict(top)
        self.sub = dict(sub)

    def copy(self) -> "State":
        return State(self.top, self.sub)

    def get(self, tag_id: str) -> Optional[str]:
        return self.sub.get(tag_id) if tag_id.startswith("9012.") else self.top.get(tag_id)

    def set(self, tag_id: str, value: str) -> None:
        (self.sub if tag_id.startswith("9012.") else self.top)[tag_id] = value


def _items(raw: str) -> List[str]:
    return [i.strip() for i in split_quoted(raw or "", ";") if i.strip()]


def _norm_item(item: str) -> str:
    return "".join(item.split())


def make_resolver(state: State, order: Dict[str, Any], extra: Dict[str, Any],
                  idx: KnowledgeIndex, client_top: Dict[str, str]):
    lower = {str(k).lower(): v for k, v in (order or {}).items()}

    def resolve(field: str):
        name, arg = func_call(field)
        if name:
            n = name.lower()
            if n == "tag9012":
                return state.get("9012." + idx.canonical(arg))
            if n == "fixtag":
                if arg == "9012":
                    return "^".join(f"{k[5:]}={v}" for k, v in state.sub.items()) or None
                return state.get(arg)
            return UNKNOWN
        f = field.strip()
        if f.lower().startswith("tag") and f[3:].isdigit():
            return state.get(f[3:])
        if f == "algorithm":
            v = state.get("9012.1") or state.get("9001") or lower.get("algo")
            return str(v).upper() if v else None
        if f == "clientAlgorithm":
            v = client_top.get("9001")
            return str(v).upper() if v else UNKNOWN
        if f in extra:
            return extra[f]
        col = ORDER_FIELDS.get(f)
        if col and col in lower and lower[col] not in (None, ""):
            v = lower[col]
            if f == "side":
                s = str(v).strip().lower()
                return SIDE_ALIASES.get(s, s)
            return v
        return UNKNOWN

    return resolve


# --------------------------------------------------------------------------- rules


def _rule_items(rule: Dict[str, Any]) -> Optional[List[str]]:
    if any(w.get("dynamic") for w in rule.get("writes", [])) or not rule.get("writes"):
        return None
    raw = rule.get("writesRaw", "")
    if raw.startswith("IR="):
        raw = raw.split(";", 1)[1] if ";" in raw else ""
    return [_norm_item(i) for i in _items(raw)]


def _find(seq: List[str], items: List[str], start: int) -> int:
    n = len(seq)
    for k in range(start, len(items) - n + 1):
        if items[k:k + n] == seq:
            return k
    return -1


def simulate(raw: str, rules: List[Dict[str, Any]], idx: KnowledgeIndex,
             order: Dict[str, Any], extra: Dict[str, Any]):
    items = _items(raw)
    norm = [_norm_item(i) for i in items]
    full = fm.parse(raw, idx.canonical)

    # pass 1: provisional match positions (greedy, in rule order)
    pos, matches = 0, {}
    first = None
    for r in rules:
        seq = _rule_items(r)
        if not seq:
            continue
        k = _find(seq, norm, pos)
        if k >= 0 and k > 0:  # the client part is never empty
            matches[r["id"]] = (k, k + len(seq))
            pos = k + len(seq)
            first = k if first is None else first

    client_raw = ";".join(items[:first]) if first is not None else raw
    client = fm.parse(client_raw, idx.canonical)
    have_segments = first is not None

    state = State(client.top, client.sub)
    chains: Dict[str, List[Dict[str, Any]]] = {}
    for tid, val in list(client.top.items()) + list(client.sub.items()):
        chains[tid] = [{"source": "client", "value": val}]

    outcomes: List[Dict[str, Any]] = []
    for r in rules:
        before = state.copy()
        resolve = make_resolver(state, order, extra, idx, client.top)
        result, unresolved = evaluate_all(r.get("conditions", []), resolve)
        if r.get("irelay") is not None and result is not False:
            unresolved = unresolved + [f"IR={r['irelay']} (relay algo state)"]
            result = None
        observed = r["id"] in matches
        if observed and result is False:
            observed = False  # text matched but conditions say no: coincidence
        if observed:
            status = "applied"
        elif result is True:
            status = "fires"
        elif result is None and not (have_segments and _rule_items(r)):
            status = "may_fire"
        else:
            continue
        for w in r.get("writes", []):
            if w["tag"] == "<js>":
                continue
            tid = w["tag"] if not w["tag"].startswith("9012.") else "9012." + idx.canonical(w["key"])
            step = {"source": f"{r['file']}:{r['line']}", "ruleId": r["id"], "value": w["value"],
                    "status": status}
            chains.setdefault(tid, []).append(step)
            if status != "may_fire":
                state.set(tid, w["value"])
        outcomes.append({"rule": r, "status": status, "unresolved": unresolved, "before": before})
    return full, client, state, chains, outcomes, have_segments


# --------------------------------------------------------------------------- effects


def _tag_label(idx: KnowledgeIndex, tid: str) -> str:
    t = idx.tag(tid)
    num = tid.split(".", 1)[1] if tid.startswith("9012.") else tid
    base = f"9012/{num}" if tid.startswith("9012.") else tid
    if t and t.get("alias"):
        base += f" ({t['alias']})"
    if t and t.get("name"):
        base += f" {t['name']}"
    return base


def rule_effect(o: Dict[str, Any], idx: KnowledgeIndex) -> Optional[Dict[str, Any]]:
    r, status, before = o["rule"], o["status"], o["before"]
    writes = [w for w in r.get("writes", [])]
    tids, changes, kind, severity = [], [], "side_effect", "low"
    for w in writes:
        if w["tag"] == "<js>":
            changes.append("runs a script on the order: " + w["value"][:160])
            severity = "medium"
            continue
        tid = w["tag"] if not w["tag"].startswith("9012.") else "9012." + idx.canonical(w["key"])
        tids.append(tid)
        old = before.get(tid)
        if tid in REJECT_KEYS:
            kind, severity = "reject", "high"
            changes.append(f"rejects the order: {w['value'].replace('+', ' ')}")
        elif tid in ALGO_KEYS:
            if kind != "reject":
                kind, severity = "conversion", "high"
            changes.append(f"sets algorithm {tid}={w['value']}" + (f" (was {old})" if old else ""))
        elif old is not None and old != w["value"]:
            if kind not in ("reject", "conversion"):
                kind, severity = "override", "medium"
            changes.append(f"overrides {_tag_label(idx, tid)}: {old} -> {w['value']}")
        else:
            changes.append(f"sets {_tag_label(idx, tid)} = {w['value']}")
    if not changes:
        return None
    cond = ", ".join(c["raw"] for c in r.get("conditions", []))
    comment = (r.get("comment") or "").split(" / ")[0]
    if len(comment) > 140:
        comment = comment[:137].rsplit(" ", 1)[0] + "…"
    title = f"{comment} (line {r['line']})" if comment else f"Config rule line {r['line']}"
    if r.get("comment") and r["comment"] != comment:
        changes.append("Rule comment: " + r["comment"])
    return {
        "id": r["id"], "origin": "rule", "kind": kind, "severity": severity, "status": status,
        "tags": tids, "title": title,
        "explanation": "; ".join(changes) + (f". Conditions: {cond}" if cond else ""),
        "unresolvedConditions": o["unresolved"], "sources": [f"{r['file']}:{r['line']}"],
    }


def relationship_effects(idx: KnowledgeIndex, state: State, order, extra, client_top,
                         present: Iterable[str]) -> List[Dict[str, Any]]:
    present = set(present)
    resolve = make_resolver(state, order, extra, idx, client_top)
    out = []
    for rel in idx.relationships:
        trig = rel.get("trigger") or []
        rel_tags = [t for t in rel.get("tags", []) if t]
        if not trig and not rel_tags:
            continue
        # relevance: every tag-condition must hold; at least one tag must be present
        tag_conds = [c for c in trig if func_call(c.get("field", ""))[0] in ("tag9012", "fixTag")
                     or str(c.get("field", "")).startswith("tag9")]
        presence = [c for c in tag_conds if not (c.get("op") == "=" and str(c.get("value")) == "null")]
        # in knowledge triggers "tag != value" means "the tag is set, to something else"
        if any(c.get("op") in ("!=", "!~") and "null" not in str(c.get("value"))
               and resolve(c["field"]) is None for c in tag_conds):
            continue
        if tag_conds:
            ok, _ = evaluate_all(tag_conds, resolve)
            if ok is not True:
                continue
        elif not (set(rel_tags) & present):
            continue
        result, unresolved = evaluate_all(trig, resolve)
        if result is False:
            continue
        if tag_conds and not presence and result is not True:
            continue  # "tag X missing" effects are only shown when fully confirmed
        algos = [a.upper() for a in rel.get("algorithms") or []]
        if algos and "ALL" not in algos:
            cur = resolve("algorithm")
            if cur is UNKNOWN or cur is None:
                unresolved.append("algorithm in " + "^".join(algos))
            elif str(cur).upper() not in algos:
                continue
        if rel.get("kind") == "reject" and not unresolved and len(tag_conds) == len(trig) \
                and all(c.get("op") == "!=" and str(c.get("value")) == "null" for c in trig):
            # only "tag present" is known: whether the engine rejects depends on its own checks
            unresolved.append("engine validation of the value at run time")
        out.append({
            "id": rel.get("id"), "origin": "knowledge", "kind": rel.get("kind", "side_effect"),
            "severity": rel.get("severity", "info"),
            "status": "fires" if not unresolved else "may_fire",
            "tags": rel_tags, "title": rel.get("title", ""), "explanation": rel.get("explanation", ""),
            "unresolvedConditions": unresolved, "sources": rel.get("sources", []),
        })
    return out


def conflict_effects(idx: KnowledgeIndex, rule_set: str, outcomes) -> List[Dict[str, Any]]:
    hit_lines = {o["rule"]["line"]: o["status"] for o in outcomes}
    out = []
    for c in idx.conflicts:
        if c.get("ruleSet") and c["ruleSet"] != rule_set:
            continue
        # currentLines: line numbers in the rule file as shipped (the conflict report may
        # cite an older revision of the file in `lines`)
        lines = [int(x) for x in (c.get("currentLines") or c.get("lines") or []) if str(x).isdigit()]
        hits = [ln for ln in lines if ln in hit_lines]
        if not hits:
            continue
        status = "applied" if any(hit_lines[ln] in ("applied", "fires") for ln in hits) else "may_fire"
        out.append({
            "id": c.get("id"), "origin": "conflict", "kind": "config_conflict",
            "severity": str(c.get("severity", "medium")).lower(), "status": status,
            "tags": c.get("tags", []), "title": c.get("title", c.get("id", "")),
            "explanation": (c.get("problem", "") + (" Suggested fix: " + c["fix"] if c.get("fix") else "")).strip(),
            "unresolvedConditions": [], "sources": [f"{c.get('ruleSet') or rule_set}:{ln}" for ln in hits],
        })
    return out


# --------------------------------------------------------------------------- main


def describe_tag(idx: KnowledgeIndex, tid: str, key: str, value: str,
                 history: List[str]) -> Dict[str, Any]:
    t = idx.tag(tid)
    entry: Dict[str, Any] = {"id": tid, "key": key, "value": value, "known": t is not None,
                             "parent": "9012" if tid.startswith("9012.") else None,
                             "number": tid.split(".", 1)[1] if tid.startswith("9012.") else tid}
    if len(history) > 1:
        entry["history"] = history
    if not t:
        entry.update({"name": "(unknown tag)", "description": "This tag is not in the knowledge base."})
        return entry
    meaning = None
    for av in t.get("allowedValues") or []:
        if str(av.get("value")) == value:
            meaning = av.get("meaning")
    for k in ("alias", "name", "category", "description", "valueFormat", "type", "allowedValues",
              "default", "example", "appliesTo", "algorithmDependent", "internal", "confidence", "sources"):
        if t.get(k) not in (None, "", []):
            entry[k] = t[k]
    if meaning:
        entry["valueMeaning"] = meaning
    return entry


def analyze(order: Dict[str, Any], kb: Dict[str, Any], rule_set: Optional[str] = None,
            extra_context: Optional[Dict[str, Any]] = None,
            index: Optional[KnowledgeIndex] = None) -> Dict[str, Any]:
    idx = index or KnowledgeIndex(kb)
    extra = dict(extra_context or {})
    raw = str(order.get("fixmsg") or "")
    rs = idx.rule_sets.get(rule_set or DEFAULT_RULE_SET)
    if rs is None and idx.rule_sets:
        rs = next(iter(idx.rule_sets.values()))
    rules = rs["rules"] if rs else []
    rs_name = rs["ruleSet"] if rs else ""

    full, client, state, chains, outcomes, have_segments = simulate(raw, rules, idx, order, extra)

    # tags: final values in order of first appearance
    seen, tags = {}, []
    for occ in full.occurrences:
        seen.setdefault(occ.tag_id, occ.key)
    for tid, key in seen.items():
        hist = [o.value for o in full.history(tid)]
        tags.append(describe_tag(idx, tid, key, hist[-1], hist))

    effects = [e for e in (rule_effect(o, idx) for o in outcomes) if e]
    effects += relationship_effects(idx, state, order, extra, client.top, seen.keys())
    effects += conflict_effects(idx, rs_name, outcomes)
    for tid, hist in full.overridden().items():
        effects.append({
            "id": f"OBS-{tid}", "origin": "fixmsg", "kind": "override", "severity": "medium",
            "status": "applied", "tags": [tid],
            "title": f"{_tag_label(idx, tid)} set several times in the fixmsg",
            "explanation": "Values in order: " + " -> ".join(o.value for o in hist)
                           + f". The engine keeps the last one ({hist[-1].value}).",
            "unresolvedConditions": [], "sources": ["fixmsg"],
        })
    effects.sort(key=lambda e: (SEVERITY_RANK.get(e["severity"], 9), STATUS_RANK.get(e["status"], 9),
                                str(e.get("id"))))

    override_chains = []
    for tid, steps in chains.items():
        sure = [s for s in steps if s.get("status") != "may_fire"]   # possible writes are in effects
        if len(sure) > 1 and len({s["value"] for s in sure}) > 1:
            override_chains.append({"tag": tid, "label": _tag_label(idx, tid), "steps": sure,
                                    "final": state.get(tid)})

    order_view = {k: _plain(order.get(k)) for k in
                  ("id_target", "sym", "side", "size", "algo", "trader", "basket", "portfolio",
                   "time", "limit_price", "tif", "otype", "oes_oid") if k in order}
    order_view["fixmsg"] = raw
    return {
        "order": order_view,
        "ruleSet": rs_name,
        "clientFixmsg": client.raw,
        "ruleSegmentsDetected": have_segments,
        "tags": tags,
        "effects": effects,
        "overrideChains": override_chains,
        "parseErrors": full.errors,
        "counts": {"tags": len(tags), "unknownTags": sum(1 for t in tags if not t["known"]),
                   "effects": len(effects),
                   "rulesApplied": sum(1 for o in outcomes if o["status"] == "applied"),
                   "rulesFire": sum(1 for o in outcomes if o["status"] == "fires"),
                   "rulesMayFire": sum(1 for o in outcomes if o["status"] == "may_fire")},
    }


def _plain(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)
