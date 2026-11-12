"""Order lookup on the RDB (pykx), plus a fake backend for tests and demos.

Only two queries are ever sent, both built from an integer the service has validated::

    select from target where id_target=<n>
    select from target_stock where id_target=<n>     (optional, STOCK_TABLE)
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional


def _plain(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, float):
        return None if math.isnan(v) else v
    if isinstance(v, (str, int, bool)):
        return v
    if hasattr(v, "item"):          # numpy scalar
        try:
            return _plain(v.item())
        except Exception:
            pass
    if isinstance(v, (dt.datetime, dt.date, dt.time, dt.timedelta)):
        return str(v)
    try:
        import pandas as pd  # noqa: WPS433
        if v is pd.NaT:
            return None
    except Exception:
        pass
    return str(v)


def _records(table) -> List[Dict[str, Any]]:
    df = table.pd()
    if hasattr(df, "reset_index") and getattr(df.index, "names", [None])[0] is not None:
        df = df.reset_index()        # keyed tables
    return [{str(k): _plain(v) for k, v in row.items()} for row in df.to_dict("records")]


class KdbClient:
    def __init__(self, host: str, port: int, user: Optional[str] = None, password: Optional[str] = None,
                 timeout: float = 10.0, target_table: str = "target", stock_table: Optional[str] = None):
        if not host or not port:
            raise ValueError("KDB_HOST / KDB_PORT are not set (service/local_settings.py)")
        self.args = dict(host=host, port=int(port), timeout=float(timeout))
        if user:
            self.args.update(username=user, password=password or "")
        self.target_table = target_table
        self.stock_table = stock_table
        self._conn = None

    def _connection(self):
        if self._conn is None:
            try:
                import pykx  # noqa: WPS433  (imported lazily: tests and fake mode don't need it)
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("pykx is not installed: pip install pykx") from exc
            self._conn = pykx.SyncQConnection(**self.args)
        return self._conn

    def _query(self, q: str):
        try:
            return self._connection()(q)
        except Exception:
            self.close()           # drop a broken handle, retry once on a fresh one
            return self._connection()(q)

    def find_orders(self, id_target: int) -> List[Dict[str, Any]]:
        return _records(self._query(f"select from {self.target_table} where id_target={int(id_target)}"))

    def find_stock(self, id_target: int) -> Optional[Dict[str, Any]]:
        if not self.stock_table:
            return None
        try:
            rows = _records(self._query(f"select from {self.stock_table} where id_target={int(id_target)}"))
        except Exception:
            return None
        return rows[-1] if rows else None

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


class FakeKdb:
    """Answers from a JSON file: ``{"target": [rows...], "target_stock": [rows...]}``."""

    def __init__(self, path: Path | str):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.target = data.get("target", [])
        self.stock = data.get("target_stock", [])

    def find_orders(self, id_target: int):
        return [r for r in self.target if int(r.get("id_target", -1)) == int(id_target)]

    def find_stock(self, id_target: int):
        rows = [r for r in self.stock if int(r.get("id_target", -1)) == int(id_target)]
        return rows[-1] if rows else None

    def close(self):
        pass
