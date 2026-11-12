import json
from pathlib import Path

from tools.import_bcore_csv import load_rows, to_part
from tools.validate_knowledge import validate

ROOT = Path(__file__).resolve().parents[1]

CSV = '''TagNumber,version,tagName,interface,comments,availability,implemented,example,modifiedBy,modifiedTime,oldTagInfo,clientTagNumber,description,parametersField,validValues
1,1,ALGO,," specifies the algorithm of the order",NULL,NULL,NULL,pcheng,2016-06-24 00:00:00.000,NULL,,NULL,NULL
1,2,ALGO,"aiidope, algorithm()"," specifies the algorithm of the order with 9012 tag instead of 9001",NULL,NULL,1=VWAP set algorithm to vwap.,mgu,2016-09-20 17:05:54.100,NULL,0,an alternative tag,_algorithm,string
10,1,,"iwould ,iwouldPrice,iwouldPrice()","a float number representing price, with
a newline","Shadow, Inline",Yes,10=15.0,mgu,2016-09-20 09:16:50.987,NULL,9010,Would Good Price,_iwould,"any positive double"
'''


def test_bcore_latest_version_wins(tmp_path):
    p = tmp_path / "b.csv"
    p.write_text(CSV, encoding="utf-8")
    part = {e["number"]: e for e in to_part(load_rows([p]))}
    assert part["1"]["bcore"]["version"] == "2"
    assert part["1"]["bcore"]["example"].startswith("1=VWAP")
    assert "newline" in part["10"]["bcore"]["comments"]
    assert part["10"]["clientNumber"] == "9010"


def test_skill_copies_identical():
    claude = (ROOT / "skills/claude/tag-knowledge/SKILL.md").read_text(encoding="utf-8")
    assert (ROOT / ".claude/skills/tag-knowledge/SKILL.md").read_text(encoding="utf-8") == claude
    cop = (ROOT / "skills/copilot/tag-knowledge.prompt.md").read_text(encoding="utf-8")
    assert (ROOT / ".github/prompts/tag-knowledge.prompt.md").read_text(encoding="utf-8") == cop


def test_shipped_knowledge_is_valid():
    kb_path = ROOT / "knowledge" / "tag-knowledge.json"
    kb = json.loads(kb_path.read_text(encoding="utf-8"))
    errors, _ = validate(kb)
    assert errors == []
    assert len(kb["tags"]) >= 700
    assert kb["ruleSets"] and kb["ruleSets"][0]["rules"]
