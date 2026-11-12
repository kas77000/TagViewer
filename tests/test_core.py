from tagviewer import fixmsg as fm
from tagviewer.analyzer import KnowledgeIndex, analyze
from tagviewer.conditions import UNKNOWN, evaluate, evaluate_all, parse_conditions
from tagviewer.rules import parse_writes

KB = {
    "tags": [
        {"id": "9001", "number": "9001", "parent": None, "name": "Algorithm",
         "allowedValues": [{"value": "VWAP", "meaning": "volume weighted"}]},
        {"id": "9012.1", "number": "1", "parent": "9012", "alias": "ALGO", "name": "Algorithm (9012)"},
        {"id": "9012.154", "number": "154", "parent": "9012", "name": "Queue mode"},
        {"id": "9012.152", "number": "152", "parent": "9012", "name": "Peg mode"},
        {"id": "9012.244", "number": "244", "parent": "9012", "name": "X"},
        {"id": "9012.1546", "number": "1546", "parent": "9012", "alias": "PQS", "name": "Post quote size",
         "interactions": [{"kind": "ineffective", "severity": "medium", "tags": ["9012.1546"],
                           "trigger": parse_conditions("tag9012(1546)!=null, algorithm=SDMA"),
                           "title": "PQS ignored for SDMA", "explanation": "..."}]},
        {"id": "9012.1525", "number": "1525", "parent": "9012", "alias": "KO", "name": "Reject"},
    ],
    "relationships": [
        {"id": "REL-1", "kind": "override", "severity": "high", "tags": ["9012.1", "9001"],
         "trigger": parse_conditions("tag9012(1)!=null, fixTag(9001)!=null"),
         "title": "9012 ALGO overrides 9001", "explanation": "..."},
    ],
    "ruleSets": [{
        "ruleSet": "test.properties", "rules": [
            {"id": "t:L5", "file": "test.properties", "line": 5, "order": 1, "comment": "HK short sell",
             "irelay": None, "writes": parse_writes("9012=244=1"), "writesRaw": "9012=244=1",
             "conditions": parse_conditions("side=sellshort, algorithm=SDMA, tag9012(244)=null")},
            {"id": "t:L6", "file": "test.properties", "line": 6, "order": 2, "comment": "convert",
             "irelay": None, "writes": parse_writes("9001=PEG;9012=152=1"), "writesRaw": "9001=PEG;9012=152=1",
             "conditions": parse_conditions("side=sellshort, compositeExchangeCode=HK, algorithm=SDMA")},
            {"id": "t:L9", "file": "test.properties", "line": 9, "order": 3, "comment": "",
             "irelay": None, "writes": parse_writes("9012=154=0"), "writesRaw": "9012=154=0",
             "conditions": parse_conditions("compositeExchangeCode=C1^C2")},
            {"id": "t:L10", "file": "test.properties", "line": 10, "order": 4, "comment": "",
             "irelay": None, "writes": parse_writes("9012=KO=bad"), "writesRaw": "9012=KO=bad",
             "conditions": parse_conditions("tag9012(154)=0, side=buy")},
        ]}],
    "knownConflicts": [{"id": "C-99", "severity": "HIGH", "lines": [9], "ruleSet": "test.properties",
                        "title": "dup", "problem": "p", "fix": "f", "tags": ["9012.154"]}],
}


def test_parse_merges_9012_and_aliases():
    idx = KnowledgeIndex(KB)
    p = fm.parse("9001=VWAP;9012=154=1^PQS=0.5,1;9012=154=0;9050=6=50", idx.canonical)
    assert p.top == {"9001": "VWAP"}
    assert p.sub["9012.154"] == "0"
    assert p.sub["9012.1546"] == "0.5,1"
    assert p.sub["9012.6"] == "50"
    assert [o.value for o in p.history("9012.154")] == ["1", "0"]
    assert "9012.154" in p.overridden()


def test_quoted_values_keep_delimiters():
    p = fm.parse("9012=X=<tq>a^b;c</tq>^Y=1")
    assert p.sub["9012.X"] == "a^b;c"
    assert p.sub["9012.Y"] == "1"


def test_empty_values_are_absent():
    p = fm.parse("9002=;9008=ABC")
    assert "9002" not in p.top and p.top["9008"] == "ABC"


def test_conditions_three_valued():
    vals = {"side": "sellshort", "tag9012(5)": None, "size": "100"}
    r = lambda f: vals.get(f, UNKNOWN)
    c = parse_conditions("side=sellshort^short, tag9012(5)=null, size >= 50, adv > 3")
    assert evaluate(c[0], r) is True
    assert evaluate(c[1], r) is True
    assert evaluate(c[2], r) is True
    assert evaluate(c[3], r) is None
    assert evaluate_all(c, r) == (None, ["adv > 3"])
    assert evaluate(parse_conditions("side!=buy^sell")[0], r) is True
    assert evaluate(parse_conditions("side~sell.*")[0], r) is True
    assert evaluate(parse_conditions("<js> 1 < 2 </js>")[0], r) is None
    assert parse_conditions("APIH^APIC")[0]["op"] == "invalid"


def test_js_commas_do_not_split():
    c = parse_conditions("a=1, <js> f(x, y) </js>, b=2")
    assert [x["op"] for x in c] == ["=", "js", "="]


def test_analyze_observed_rules_and_relationships():
    order = {"id_target": 7, "sym": "0700.HK", "side": "SS", "algo": "PEG",
             "fixmsg": "9001=SDMA;9012=1=SDMA^PQS=1;9012=244=1;9001=PEG;9012=152=1"}
    res = analyze(order, KB)
    by_id = {e["id"]: e for e in res["effects"]}
    assert res["ruleSegmentsDetected"] is True
    assert res["clientFixmsg"] == "9001=SDMA;9012=1=SDMA^PQS=1"
    assert by_id["t:L5"]["status"] == "applied"
    assert by_id["t:L6"]["status"] == "applied" and by_id["t:L6"]["kind"] == "conversion"
    assert "t:L9" not in by_id          # literal rule not in the fixmsg -> did not fire
    assert by_id["REL-1"]["status"] == "fires"
    tags = {t["id"]: t for t in res["tags"]}
    assert tags["9001"]["value"] == "PEG" and tags["9001"]["history"] == ["SDMA", "PEG"]
    assert tags["9012.1546"]["name"] == "Post quote size"
    # severity ordering: high first
    assert res["effects"][0]["severity"] == "high"


def test_analyze_without_rule_segments_reports_may_fire_and_conflicts():
    order = {"id_target": 8, "side": "buy", "algo": "VWAP", "fixmsg": "9001=VWAP;9012=154=1"}
    res = analyze(order, KB)
    by_id = {e["id"]: e for e in res["effects"]}
    assert by_id["t:L9"]["status"] == "may_fire"
    assert by_id["t:L9"]["kind"] == "override"
    assert by_id["C-99"]["kind"] == "config_conflict"
    assert "t:L10" not in by_id   # 154 stays 1 (L9 only may fire) -> KO condition false
    # only possible (may_fire) writes: no confirmed change chain, the effect carries it
    assert "9012.154" not in {c["tag"] for c in res["overrideChains"]}


def test_unknown_tag_kept():
    res = analyze({"fixmsg": "9012=99999=1;77=X"}, KB)
    ids = {t["id"]: t for t in res["tags"]}
    assert ids["9012.99999"]["known"] is False and ids["77"]["known"] is False
    assert res["counts"]["unknownTags"] == 2


def test_json_null_value_means_null_keyword():
    r = lambda f: None
    assert evaluate({"field": "tag9012(5)", "op": "!=", "value": None, "raw": ""}, r) is False
    assert evaluate({"field": "tag9012(5)", "op": "=", "value": None, "raw": ""}, r) is True


def test_knowledge_not_equal_requires_presence():
    kb = dict(KB)
    kb["relationships"] = [{"id": "R-NE", "kind": "reject", "severity": "high", "tags": ["9012.289"],
                            "trigger": parse_conditions("tag9012(289)!=0, tag9012(154)!=null"),
                            "title": "t", "explanation": "e"}]
    absent = analyze({"fixmsg": "9012=154=1"}, kb)
    assert "R-NE" not in {e["id"] for e in absent["effects"]}
    present = analyze({"fixmsg": "9012=154=1^289=5"}, kb)
    assert "R-NE" in {e["id"] for e in present["effects"]}
