"""Prepare the TagViewer share folder and produce the HTML to hand to users.

    python tools/configure_share.py --share "\\\\server\\share\\TagViewer"
    python tools/configure_share.py --share "\\\\server\\share\\TagViewer" --out dist/tagviewer.html --timeout 90

* creates ``requests/ processing/ processed/ failed/ responses/ status/`` in the share;
* writes ``.tagviewer-share`` (``shareId``) - kept if it already exists, so pages
  configured earlier keep working;
* copies ``web/tagviewer.html`` to ``--out`` with the share path and id written into the
  ``TAGVIEWER-CONFIG`` block. Distribute that file.

Browsers cannot open a folder from a path, so each user still picks the folder once; the
page shows this path and refuses any folder whose ``.tagviewer-share`` id differs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("requests", "processing", "processed", "failed", "responses", "status")
BLOCK = re.compile(r"(/\* TAGVIEWER-CONFIG-BEGIN \*/\s*)const CONFIG = .*?;(\s*/\* TAGVIEWER-CONFIG-END \*/)", re.S)


def prepare_share(share: Path) -> dict:
    share.mkdir(parents=True, exist_ok=True)
    for d in FOLDERS:
        (share / d).mkdir(exist_ok=True)
    marker = share / ".tagviewer-share"
    if marker.exists():
        data = json.loads(marker.read_text(encoding="utf-8"))
    else:
        data = {"shareId": str(uuid.uuid4()),
                "createdAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    data["sharePath"] = str(share)
    marker.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def configure_html(template: str, config: dict) -> str:
    js = "const CONFIG = " + json.dumps(config) + ";"
    new, n = BLOCK.subn(lambda m: m.group(1) + js + m.group(2), template)
    if n != 1:
        raise SystemExit("config block not found in the HTML template")
    return new


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--share", required=True, help="share folder path as users see it (UNC path)")
    ap.add_argument("--template", default=str(ROOT / "web" / "tagviewer.html"))
    ap.add_argument("--out", default=str(ROOT / "dist" / "tagviewer.html"))
    ap.add_argument("--timeout", type=int, default=60, help="seconds before the page warns")
    ap.add_argument("--poll-ms", type=int, default=1500)
    ap.add_argument("--no-create", action="store_true", help="only write the HTML, do not touch the share")
    a = ap.parse_args(argv)

    share = Path(a.share)
    if a.no_create:
        marker = share / ".tagviewer-share"
        if not marker.exists():
            raise SystemExit(f"{marker} does not exist; run without --no-create first")
        data = json.loads(marker.read_text(encoding="utf-8"))
    else:
        data = prepare_share(share)

    html = configure_html(Path(a.template).read_text(encoding="utf-8"), {
        "sharePath": a.share, "shareId": data["shareId"],
        "responseTimeoutSec": a.timeout, "pollMs": a.poll_ms})
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"share ready : {share}  (shareId {data['shareId']})")
    print(f"page written: {out}")
    print("Give that HTML file to the users. On first launch (Edge/Chrome) they select the share folder once.")
    print(f"Service: set SHARE_PATH = r\"{a.share}\" in service/local_settings.py and start it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
