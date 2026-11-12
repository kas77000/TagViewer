"""TagViewer backend: watch the share for requests, look the order up on kdb, answer.

    python -m service.tagviewer_service                 # uses service/local_settings.py
    python -m service.tagviewer_service --once          # handle what is there, then exit
    python -m service.tagviewer_service --fake-kdb tests/fixtures/fake_kdb.json --share C:\\tmp\\share

Share layout (created by tools/configure_share.py)::

    requests/<userGuid>__<requestId>.json    written by the page (.tmp then rename)
    processing/                              claimed by this service (atomic rename)
    processed/<yyyymmdd>/  failed/<yyyymmdd>/
    responses/<userGuid>/<requestId>.json    written here (.tmp then rename)
    status/service.json                      heartbeat, read by the page
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import logging.handlers
import os
import re
import shutil
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service import settings as settings_mod  # noqa: E402
from service.kdb_client import FakeKdb, KdbClient  # noqa: E402
from tagviewer import __version__  # noqa: E402
from tagviewer.analyzer import KnowledgeIndex, analyze  # noqa: E402

log = logging.getLogger("tagviewer")
SCHEMA_VERSION = 1
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
NAME_RE = re.compile(r"^(?P<guid>[0-9a-f-]{36})__(?P<rid>[0-9a-f-]{36})\.json$")
MAX_ID = 2 ** 31 - 1          # target.id_target is a kdb int


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class RequestError(Exception):
    pass


def validate_request(name: str, data: Any) -> Dict[str, Any]:
    m = NAME_RE.match(name)
    if not m:
        raise RequestError(f"bad file name {name!r}")
    if not isinstance(data, dict):
        raise RequestError("request is not a JSON object")
    guid, rid = str(data.get("userGuid", "")).lower(), str(data.get("requestId", "")).lower()
    if not UUID_RE.match(guid) or not UUID_RE.match(rid):
        raise RequestError("userGuid/requestId must be UUIDs")
    if (guid, rid) != (m.group("guid"), m.group("rid")):
        raise RequestError("file name does not match userGuid/requestId")
    algoidt = str(data.get("algoidt", "")).strip()
    if not algoidt.isdigit() or not (0 < int(algoidt) <= MAX_ID):
        raise RequestError(f"ALGOIDT must be a positive integer up to {MAX_ID}, got {algoidt!r}")
    return {"userGuid": guid, "requestId": rid, "algoidt": int(algoidt),
            "createdAt": data.get("createdAt")}


class Service:
    def __init__(self, cfg: Dict[str, Any], kdb):
        self.cfg = cfg
        self.kdb = kdb
        self.share = Path(cfg["SHARE_PATH"])
        self.kb_path = Path(cfg["KNOWLEDGE_PATH"])
        self._kb_mtime = None
        self.kb = None
        self.index = None
        self.started = now_iso()
        self.handled = 0
        self.last_error = None
        self._last_cleanup = 0.0
        self._last_beat = 0.0
        for d in ("requests", "processing", "processed", "failed", "responses", "status"):
            (self.share / d).mkdir(parents=True, exist_ok=True)

    # -- knowledge ---------------------------------------------------------------------------
    def knowledge(self):
        mtime = self.kb_path.stat().st_mtime
        if mtime != self._kb_mtime:
            self.kb = json.loads(self.kb_path.read_text(encoding="utf-8"))
            self.index = KnowledgeIndex(self.kb)
            self._kb_mtime = mtime
            log.info("knowledge loaded: %s version %s, %d tags", self.kb_path,
                     self.kb.get("meta", {}).get("version"), len(self.kb.get("tags", [])))
        return self.kb, self.index

    # -- context -----------------------------------------------------------------------------
    def extra_context(self, order: Dict[str, Any], stock: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        extra: Dict[str, Any] = {}
        if stock:
            low = {k.lower(): v for k, v in stock.items()}
            for field, col in (self.cfg.get("STOCK_FIELD_MAP") or {}).items():
                v = low.get(str(col).lower())
                if v not in (None, ""):
                    extra[field] = v
        rx = self.cfg.get("SYM_EXCHANGE_REGEX")
        if rx and "compositeExchangeCode" not in extra and order.get("sym"):
            m = re.search(rx, str(order["sym"]))
            if m:
                extra["compositeExchangeCode"] = m.group("code")
        return extra

    # -- one request -------------------------------------------------------------------------
    def answer(self, req: Dict[str, Any]) -> Dict[str, Any]:
        kb, index = self.knowledge()
        base = {"schemaVersion": SCHEMA_VERSION, "requestId": req["requestId"], "userGuid": req["userGuid"],
                "algoidt": req["algoidt"], "answeredAt": now_iso(),
                "knowledgeVersion": kb.get("meta", {}).get("version"), "service": socket.gethostname()}
        rows = self.kdb.find_orders(req["algoidt"])
        if not rows:
            return {**base, "status": "not_found",
                    "message": f"ALGOIDT {req['algoidt']} does not exist in today's target table."}
        order = rows[-1]
        stock = None
        try:
            stock = self.kdb.find_stock(req["algoidt"])
        except Exception as exc:  # optional context only
            log.info("stock lookup failed for %s: %s", req["algoidt"], exc)
        result = analyze(order, kb, rule_set=self.cfg.get("RULE_SET"),
                         extra_context=self.extra_context(order, stock), index=index)
        msg = "" if len(rows) == 1 else f"{len(rows)} rows matched; showing the last one."
        return {**base, "status": "ok", "message": msg, "matches": len(rows), **result}

    def handle(self, path: Path) -> None:
        day = dt.date.today().strftime("%Y%m%d")
        claimed = self.share / "processing" / path.name
        try:
            os.replace(path, claimed)          # atomic claim: a second service gets an error
        except OSError:
            return
        req = None
        try:
            data = json.loads(claimed.read_text(encoding="utf-8"))
            req = validate_request(path.name, data)
            log.info("request %s user %s ALGOIDT %s", req["requestId"], req["userGuid"], req["algoidt"])
            resp = self.answer(req)
            dest = "processed"
        except Exception as exc:  # every failure is answered when we know who asked
            log.exception("request %s failed", path.name)
            self.last_error = f"{now_iso()} {type(exc).__name__}: {exc}"
            dest = "failed"
            resp = None
            if req is None:
                m = NAME_RE.match(path.name)
                if m and UUID_RE.match(m.group("guid")) and UUID_RE.match(m.group("rid")):
                    req = {"userGuid": m.group("guid"), "requestId": m.group("rid"), "algoidt": None}
            if req is not None:
                resp = {"schemaVersion": SCHEMA_VERSION, "requestId": req["requestId"],
                        "userGuid": req["userGuid"], "algoidt": req.get("algoidt"), "answeredAt": now_iso(),
                        "status": "error", "message": str(exc) if isinstance(exc, RequestError)
                        else f"The service could not answer: {type(exc).__name__}: {exc}"}
        if resp is not None:
            write_json_atomic(self.share / "responses" / resp["userGuid"] / f"{resp['requestId']}.json", resp)
        target = self.share / dest / day
        target.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(claimed, target / path.name)
        except OSError:
            claimed.unlink(missing_ok=True)
        self.handled += 1

    # -- loop --------------------------------------------------------------------------------
    def pending(self):
        reqs = self.share / "requests"
        return sorted((p for p in reqs.glob("*.json") if p.is_file()), key=lambda p: p.stat().st_mtime)

    def recover(self):
        """Requests left in processing/ by a crash go back to the queue."""
        for p in (self.share / "processing").glob("*.json"):
            try:
                os.replace(p, self.share / "requests" / p.name)
            except OSError:
                pass

    def heartbeat(self, force=False):
        if not force and time.time() - self._last_beat < 5:
            return
        self._last_beat = time.time()
        write_json_atomic(self.share / "status" / "service.json", {
            "service": socket.gethostname(), "pid": os.getpid(), "version": __version__,
            "startedAt": self.started, "heartbeatAt": now_iso(), "handled": self.handled,
            "knowledgeVersion": (self.kb or {}).get("meta", {}).get("version"), "lastError": self.last_error})

    def cleanup(self):
        if time.time() - self._last_cleanup < 3600:
            return
        self._last_cleanup = time.time()
        cutoff = dt.date.today() - dt.timedelta(days=int(self.cfg.get("KEEP_DAYS") or 7))
        for d in ("processed", "failed"):
            for sub in (self.share / d).iterdir():
                if sub.is_dir() and sub.name.isdigit() and sub.name < cutoff.strftime("%Y%m%d"):
                    shutil.rmtree(sub, ignore_errors=True)
        # answers nobody collected
        old = time.time() - int(self.cfg.get("KEEP_DAYS") or 7) * 86400
        for p in (self.share / "responses").glob("*/*.json"):
            if p.stat().st_mtime < old:
                p.unlink(missing_ok=True)

    def run(self, once=False):
        self.knowledge()
        self.recover()
        self.heartbeat(force=True)
        log.info("watching %s", self.share)
        while True:
            for p in self.pending():
                self.handle(p)
            self.heartbeat(force=once)
            if once:
                return
            self.cleanup()
            time.sleep(float(self.cfg.get("POLL_SECONDS") or 1.0))


def setup_logging(log_dir: str) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.handlers.TimedRotatingFileHandler(Path(log_dir) / "tagviewer_service.log", when="midnight",
                                                   backupCount=14, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.handlers[:] = [fh, sh]
    log.setLevel(logging.INFO)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--share", help="override SHARE_PATH")
    ap.add_argument("--knowledge", help="override KNOWLEDGE_PATH")
    ap.add_argument("--fake-kdb", help="answer from a JSON file instead of kdb")
    ap.add_argument("--once", action="store_true", help="process pending requests and exit")
    ap.add_argument("--settings", help="path to a local_settings.py")
    a = ap.parse_args(argv)

    cfg = settings_mod.load(Path(a.settings) if a.settings else None)
    if a.share:
        cfg["SHARE_PATH"] = a.share
    if a.knowledge:
        cfg["KNOWLEDGE_PATH"] = a.knowledge
    if not cfg.get("SHARE_PATH"):
        ap.error("SHARE_PATH is not set (service/local_settings.py or --share)")
    setup_logging(cfg["LOG_DIR"])
    kdb = FakeKdb(a.fake_kdb) if a.fake_kdb else KdbClient(
        cfg["KDB_HOST"], cfg["KDB_PORT"], cfg.get("KDB_USER"), cfg.get("KDB_PASSWORD"),
        cfg.get("KDB_TIMEOUT", 10.0), cfg.get("TARGET_TABLE", "target"), cfg.get("STOCK_TABLE"))
    svc = Service(cfg, kdb)
    try:
        svc.run(once=a.once)
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        kdb.close()


if __name__ == "__main__":
    main()
