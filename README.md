# TagViewer

Type an **ALGOIDT** (kdb `target.id_target`) in a web page and get back every tag on that
order's `fixmsg` — name, meaning, possible values, example — **and what the combination of
tags does**: config rules that rewrote or overrode a tag, tags made ineffective by others,
incompatible pairs, conversions and rejects.

```
 user's browser (Edge/Chrome)            share folder                      service machine
 ┌───────────────────────┐   request   ┌──────────────────────┐   poll   ┌─────────────────────────┐
 │ tagviewer.html        │───────────▶ │ requests/<guid>__<id>│ ───────▶ │ tagviewer_service.py    │
 │  user = GUID made on  │             │ responses/<guid>/<id>│ ◀─────── │  kdb RDB: select from   │
 │  first launch         │◀─────────── │ status/service.json  │  answer  │  target where id_target │
 └───────────────────────┘   answer    └──────────────────────┘          │  + tag-knowledge.json   │
                                                                         └─────────────────────────┘
```

* Each browser generates a **GUID** on first launch and keeps it; requests carry it and a
  random request id, and answers land in `responses/<guid>/`, so a user only ever reads
  their own answers.
* The service evaluates the order against `knowledge/tag-knowledge.json`, a generated
  knowledge base of ~800 tags, their relationships, the parsed `ai.fixmsg.properties`
  rules and the known config conflicts.

## Repository

| Path | What |
|---|---|
| `web/tagviewer.html` | the page (single file, no dependencies) |
| `tools/configure_share.py` | prepares the share and writes the share path into a copy of the page |
| `service/` | the backend: `tagviewer_service.py`, `kdb_client.py`, `settings.py`, `local_settings.py.example` |
| `tagviewer/` | core library: fixmsg parsing, rule parsing, condition evaluation, `analyzer.py` |
| `knowledge/tag-knowledge.json` | the knowledge base; contract in `knowledge/schema.md` |
| `knowledge/build/` | intermediate files of the last generation (raw extraction, parts) |
| `knowledge/curated/` | hand corrections merged over the generated data |
| `skills/` | the regeneration procedure as a Claude skill and a Copilot prompt (copies in `.claude/skills/` and `.github/prompts/`) |
| `tools/` | extraction, build, validation, BCORE CSV import, `explain` CLI |
| `docs/` | protocol and design notes |

Python 3.9+. The service needs `pykx` (`pip install -r requirements.txt`); everything else
is standard library. Tests: `python -m pytest -q`.

## Set up

### 1. Share and page (you, once)

```bat
python tools\configure_share.py --share "\\server\share\TagViewer"
```

This creates the folders and a `.tagviewer-share` marker on the share and writes
`dist\tagviewer.html` with that path built in. Give `dist\tagviewer.html` to the users.

Users open it in **Edge or Chrome**. The first time, they click *Select folder…* and pick
the share path shown on the page (browsers cannot open a folder from a typed path; the page
checks the marker and refuses a wrong folder). The browser remembers it; later at most a
one-click *Allow access again*.

Re-running the script keeps the same share id, so pages handed out earlier keep working.

### 2. Service (the machine with kdb access)

```bat
pip install -r requirements.txt
copy service\local_settings.py.example service\local_settings.py
rem edit SHARE_PATH, KDB_HOST, KDB_PORT (and optionally STOCK_TABLE / STOCK_FIELD_MAP)
python -m service.tagviewer_service
```

It polls `requests/`, claims each file atomically (so two services never answer the same
request), queries `select from target where id_target=<n>` on the RDB (the last row if
several), analyses `fixmsg`, writes `responses/<guid>/<requestId>.json`, archives the request
under `processed/` or `failed/`, and writes a heartbeat to `status/service.json` that the
page shows as *Service: online*. Logs: `service/logs/`. It reloads the knowledge file when it
changes. To run it unattended, create a Task Scheduler task *At startup* running
`python -m service.tagviewer_service` with *Start in* = the repo folder.

Try it without kdb:

```bat
python -m service.tagviewer_service --share C:\temp\tvshare --fake-kdb tests\fixtures\fake_kdb.json
```

## What the answer contains

* **Tags** — each top-level tag and 9012 sub-tag (aliases like `PQS` resolved to their
  number), its final value, earlier values if it was set more than once, name, category,
  description, value format, possible values and the meaning of the one set, default,
  example, algos it applies to, algorithm-dependent behaviour, source lines.
* **Effects** — sorted by severity:
  * `applied`: a config rule whose segment is **in the fixmsg** (the engine appends one
    segment per rule that fired, after the client's message);
  * `applies`: every condition holds for this order;
  * `may apply`: depends on data the service cannot see (market data, `<js>` scripts,
    engine-only fields) — the unresolved conditions are listed;
  * kinds: override, rewrite, conversion, ineffective, incompatible, requires,
    side effect, reject, config conflict (C-xx defects of the rule file).
* **Tags changed after the client sent them** — the chain client value → rule → rule.

## Keeping the knowledge base current

Ask an agent (Claude Code or Copilot) to run the **tag-knowledge** skill/prompt:
it re-extracts every `__p_<n>` parser from `Parameters.java`, re-documents only what
changed (`tools/plan_batches.py --changed-only`), re-parses the rule files, imports the
`BCORE_Tags` CSV, rebuilds, validates and tests. Check a fixmsg locally at any time:

```bat
python -m tools.explain "9001=SDMA;9012=PQS=0.5,1,0,1" --side sellshort --context compositeExchangeCode=HK
```

## Assumptions to verify on the real system

* `target.fixmsg` is the engine's accumulated `Parameters.fixmsg()` (client message, then
  one segment per applied config rule). If it only holds the client message, effects are
  still computed, but as `applies`/`may apply` instead of `applied`.
* `side` values: `sellshort`, `ss`, `short` are all read as short sell (`tagviewer/analyzer.py`, `SIDE_ALIASES`).
* `target_stock` column names for `STOCK_FIELD_MAP` — check with `meta target_stock`.
