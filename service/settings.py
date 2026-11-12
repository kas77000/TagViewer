"""Service settings: defaults here, overridden by ``service/local_settings.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

SHARE_PATH = None
KDB_HOST = None
KDB_PORT = None
KDB_USER = None
KDB_PASSWORD = None
KDB_TIMEOUT = 10.0
TARGET_TABLE = "target"
STOCK_TABLE = None
STOCK_FIELD_MAP: dict = {}
SYM_EXCHANGE_REGEX = None
RULE_SET = "ai.fixmsg.properties"
KNOWLEDGE_PATH = str(ROOT / "knowledge" / "tag-knowledge.json")
POLL_SECONDS = 1.0
KEEP_DAYS = 7
LOG_DIR = str(HERE / "logs")


def load(path: Path | None = None) -> dict:
    """Return the effective settings as a dict."""
    values = {k: v for k, v in globals().items() if k.isupper()}
    path = path or HERE / "local_settings.py"
    if path.exists():
        spec = importlib.util.spec_from_file_location("tagviewer_local_settings", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        values.update({k: getattr(mod, k) for k in dir(mod) if k.isupper()})
    return values
