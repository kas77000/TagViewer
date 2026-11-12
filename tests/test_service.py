import json
import uuid
from pathlib import Path

import pytest

from service.tagviewer_service import RequestError, Service, validate_request
from tests.test_core import KB
from tools.configure_share import configure_html, prepare_share

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def share(tmp_path):
    prepare_share(tmp_path / "share")
    kb = tmp_path / "kb.json"
    kb.write_text(json.dumps(KB), encoding="utf-8")
    return tmp_path / "share", kb


class Fake:
    def __init__(self, rows, boom=False):
        self.rows, self.boom = rows, boom

    def find_orders(self, i):
        if self.boom:
            raise ConnectionError("kdb down")
        return [r for r in self.rows if r["id_target"] == i]

    def find_stock(self, i):
        return {"id_target": i, "pex": "HK"}

    def close(self):
        pass


def submit(share, algoidt, guid=None):
    guid, rid = guid or str(uuid.uuid4()), str(uuid.uuid4())
    (share / "requests" / f"{guid}__{rid}.json").write_text(json.dumps(
        {"schemaVersion": 1, "requestId": rid, "userGuid": guid, "algoidt": algoidt}), encoding="utf-8")
    return guid, rid


def read_resp(share, guid, rid):
    return json.loads((share / "responses" / guid / f"{rid}.json").read_text(encoding="utf-8"))


def make(share, kb, rows, **kw):
    cfg = {"SHARE_PATH": str(share), "KNOWLEDGE_PATH": str(kb), "RULE_SET": "test.properties",
           "STOCK_FIELD_MAP": {"compositeExchangeCode": "pex"}, "KEEP_DAYS": 7, "POLL_SECONDS": 0.1}
    return Service(cfg, Fake(rows, **kw))


def test_round_trip_ok_and_isolated_per_user(share):
    sh, kb = share
    rows = [{"id_target": 5, "sym": "0700.HK", "side": "sellshort", "algo": "PEG",
             "fixmsg": "9001=SDMA;9012=1=SDMA;9012=244=1;9001=PEG;9012=152=1"}]
    a = submit(sh, 5)
    b = submit(sh, 5)
    make(sh, kb, rows).run(once=True)
    ra, rb = read_resp(sh, *a), read_resp(sh, *b)
    assert ra["status"] == "ok" and ra["userGuid"] == a[0] and rb["userGuid"] == b[0]
    assert not (sh / "responses" / a[0] / f"{b[1]}.json").exists()
    assert any(e["id"] == "t:L6" and e["status"] == "applied" for e in ra["effects"])
    assert list((sh / "requests").glob("*.json")) == []
    assert len(list((sh / "processed").rglob("*.json"))) == 2
    assert json.loads((sh / "status" / "service.json").read_text())["handled"] == 2


def test_not_found(share):
    sh, kb = share
    g, r = submit(sh, 999)
    make(sh, kb, []).run(once=True)
    assert read_resp(sh, g, r)["status"] == "not_found"


def test_kdb_error_is_answered(share):
    sh, kb = share
    g, r = submit(sh, 1)
    make(sh, kb, [], boom=True).run(once=True)
    resp = read_resp(sh, g, r)
    assert resp["status"] == "error" and "kdb down" in resp["message"]
    assert len(list((sh / "failed").rglob("*.json"))) == 1


def test_bad_algoidt_answered_as_error(share):
    sh, kb = share
    g, r = submit(sh, "12a")
    make(sh, kb, []).run(once=True)
    assert read_resp(sh, g, r)["status"] == "error"


def test_validate_request_rejects_mismatch():
    g, r = str(uuid.uuid4()), str(uuid.uuid4())
    with pytest.raises(RequestError):
        validate_request(f"{g}__{r}.json", {"userGuid": str(uuid.uuid4()), "requestId": r, "algoidt": 1})
    with pytest.raises(RequestError):
        validate_request("../../evil.json", {})


def test_configure_html_and_share(tmp_path):
    data = prepare_share(tmp_path / "s")
    again = prepare_share(tmp_path / "s")
    assert data["shareId"] == again["shareId"]
    for d in ("requests", "responses", "status", "processing"):
        assert (tmp_path / "s" / d).is_dir()
    html = configure_html((ROOT / "web" / "tagviewer.html").read_text(encoding="utf-8"),
                          {"sharePath": r"\\srv\x", "shareId": data["shareId"]})
    assert data["shareId"] in html and r'\\\\srv\\x' in html
