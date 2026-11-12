# TagViewer — design

Date: 2026-11-13
Repo: https://github.com/kas77000/TagViewer

## Purpose

A user enters an **ALGOIDT** (kdb `target.id_target`) in a single HTML page. A backend
service on another machine looks the order up on the OMS **RDB**, decodes its `fixmsg`,
and answers with:

1. every tag present, with its full definition (name, number, description, possible
   values, meaning of the value set, example, applicable algos, source);
2. the **effects of the combination** of tags present (plus the order's algo/side):
   rules that will rewrite or override a tag, tags made ineffective by another,
   incompatible pairs, combinations that lead to a reject (`KO`), each with severity,
   explanation and source (file:line).

The definitions and relationships come from a large generated **knowledge JSON** built
from the ai3 project. A skill (Claude + GitHub Copilot) lets any agent regenerate it when
the algo changes.

## Sub-projects

1. **Knowledge base** — `knowledge/tag-knowledge.json` + schema doc + regeneration skill.
2. **App** — HTML page, share-folder protocol, Python service, analyzer, configure script.

The app only reads the knowledge JSON; the JSON schema is the contract between them.

## Repo layout

```
web/tagviewer.html                     single file, no build, Edge/Chrome
tools/configure_share.py               bakes share path into the HTML, prepares the share
service/tagviewer_service.py           folder watcher, kdb lookup, writes responses
service/analyzer.py                    fixmsg parsing + rule/relationship evaluation (pure)
service/kdb_client.py                  pykx access to the RDB (lazy import), fake mode
service/local_settings.py.example      RDB host/port, share path, poll interval
knowledge/tag-knowledge.json           generated knowledge base
knowledge/schema.md                    schema of the knowledge JSON
skills/claude/tag-knowledge/SKILL.md   Claude skill to regenerate the knowledge base
skills/copilot/tag-knowledge.prompt.md Copilot prompt file (same content)
.github/copilot-instructions.md        points Copilot at the prompt file
tests/                                 pytest
```

## Share-folder protocol

Share root (configured once):

```
<share>/.tagviewer-share         marker {shareId, createdAt}
<share>/requests/                pages write here
<share>/responses/<userGuid>/    service writes here
<share>/processed/  failed/      service archives handled requests
```

**User identity.** On first launch the page generates a GUID (`crypto.randomUUID()`) and
stores it in localStorage + IndexedDB. That GUID is the user. Clearing browser data gives
a new GUID; only in-flight requests are lost.

**Request** — `requests/<userGuid>__<requestId>.json`, written as `.tmp` then renamed:

```json
{ "schemaVersion": 1, "requestId": "<uuid>", "userGuid": "<uuid>",
  "algoidt": 12345678, "createdAt": "2026-11-13T09:12:00Z" }
```

**Response** — `responses/<userGuid>/<requestId>.json`, written `.tmp` then renamed:

```json
{ "schemaVersion": 1, "requestId": "...", "userGuid": "...", "algoidt": 12345678,
  "status": "ok | not_found | error", "message": "...", "answeredAt": "...",
  "knowledgeVersion": "...",
  "order":   { "sym": "...", "side": "...", "algo": "...", "trader": "...", "size": 0,
               "basket": "...", "time": "...", "fixmsg": "<raw>" },
  "tags":    [ { "tag": "9001", "path": "9001", "value": "VWAP", "known": true,
                 "name": "...", "description": "...", "valueMeaning": "...",
                 "allowedValues": [...], "example": "...", "appliesTo": [...],
                 "sources": ["file:line"] } ],
  "effects": [ { "id": "...", "kind": "override|rewrite|ineffective|incompatible|reject|side_effect",
                 "severity": "high|medium|low|info", "status": "fires|may_fire",
                 "tags": ["9012.154", "9001"], "title": "...", "explanation": "...",
                 "unresolvedConditions": ["adv", "<js>"], "sources": ["file:line"] } ],
  "overrideChains": [ { "tag": "9012.154", "steps": [ {"line": 44, "value": "1"},
                                                      {"line": 402, "value": "0"} ],
                        "final": "0" } ]
}
```

The service validates `userGuid` and `requestId` (UUID format) before using them in paths.
The page reads only `responses/<its guid>/<requestId>.json` for requestIds it created, and
deletes a response after displaying it.

## Configure script

`python tools/configure_share.py --share "\\\\server\\TagViewer" [--out dist/tagviewer.html]`

- creates the folders and the marker file (`shareId` = new UUID) if absent;
- writes a copy of `web/tagviewer.html` with `SHARE_PATH` and `SHARE_ID` substituted into a
  clearly delimited config block;
- prints what to distribute.

Browsers cannot open a folder from a path string. On first launch the page shows the
configured path and asks the user to pick it with `showDirectoryPicker`; it verifies the
marker's `shareId` and refuses a wrong folder. The handle is persisted in IndexedDB;
afterwards only a permission re-grant click may be needed.

## Service

- Polls `requests/` every N seconds (default 1s); handles `*.json` (ignores `.tmp`).
- Parses and validates the request; malformed → `failed/` (+ error response if the GUID
  and requestId are readable).
- kdb: `select from target where id_target=X` on the RDB via pykx. No date, no id_server.
  Several rows → the last one. Zero rows → `not_found`.
- Runs the analyzer with the row and the knowledge JSON; writes the response; moves the
  request to `processed/`.
- kdb unreachable / exception → `status: error` with message; the service keeps running.
- `--fake-kdb fixtures.json` mode answers from a local file for testing without an RDB.
- Reloads the knowledge JSON when its mtime changes.
- Logs to a file; runnable as a plain process or a scheduled task.

## Analyzer

Pure functions, no I/O:

1. **Parse fixmsg** — split on `;` into `tag=value`; tags with nested sub-messages (9012 and
   any other declared in the knowledge base with a `subDelimiter`) are split on `^` into
   `9012.<subtag>`. Values containing `,` stay intact. Delimiter configurable (`\x01`, `|`).
2. **Describe tags** — join each tag/sub-tag with `tags[]`; add `valueMeaning` from
   `allowedValues`. Unknown tags are reported with `known: false`, never dropped.
3. **Order context** — fields available for condition evaluation: tags/sub-tags,
   `algorithm` (9012 algo overrides 9001, else `target.algo`), `side`, `basket`, `trader`,
   `size`, and any other `target` column mapped in the knowledge base's `fieldMap`.
4. **Evaluate rules** (`rules[]`, file order) — each condition is `true`, `false` or
   `unknown` (field not in context, `<js>` blocks, market data). A rule is `fires` if all
   conditions are true, `may_fire` if none false and some unknown, else skipped. Writes of
   firing rules are applied in order (last writer wins, `tag9012(X)=null` guards see earlier
   writes, matching `combine_fix_msg_config=false`), producing `overrideChains` and
   `rewrite`/`override`/`reject` effects.
5. **Evaluate relationships** (`relationships[]`) — each has a trigger expressed in the same
   condition language; triggered ones become effects (incompatible pairs, ineffective tags,
   side effects described in the Java source/runbooks).
6. Sort effects by severity, then status (`fires` before `may_fire`).

## Knowledge JSON (contract)

```
{
  "meta":    { "version", "generatedAt", "sources": [...], "notes" },
  "conditionLanguage": { documented operators: =, !=, <, <=, >, >=, ~ (regex), !~,
                         ^ (or-list), tag9012(X), fixTag(N), null, <js> (unknown) },
  "fieldMap": { "<rule field>": "<context key>" },
  "tags": [ { "id": "9012.154", "number": "154", "parent": "9012", "clientNumber",
              "name", "description", "type", "subDelimiter",
              "allowedValues": [ {"value", "meaning"} ], "default", "example",
              "appliesTo": [algos], "relatedTags": [...], "sources": ["file:line"] } ],
  "rules": [ { "id": "R-0005", "file", "line", "order", "comment",
               "writes": [ {"tag": "9012.244", "value": "1"} ],
               "conditions": [ {"field", "op", "value", "raw"} ], "raw" } ],
  "relationships": [ { "id", "kind", "severity", "tags": [...], "trigger": [conditions],
                       "title", "explanation", "sources": [...] } ],
  "knownConflicts": [ C-01 .. C-20 style entries, also mirrored as relationships ]
}
```

Full field definitions live in `knowledge/schema.md`.

## Knowledge-base build (now)

Uses **everything** in ai3 on this machine: `src/` Java, `config/` properties and JS
compound triggers, the markdown runbooks/specs, `AI-FIXMSG-CONFLICTS.md`,
`_transcribe_work/`, and the photos (BCORE_Tags header/rows, APIB properties, kdb table
pictures). `ai3.zip` is not unpacked if `src/` already holds the same content.

## Regeneration skill (later)

Same procedure, but the skill must assume **no pictures**: inputs are the ai3 project
source, the config files and tag CSVs (BCORE_Tags export). It describes the
inputs, extraction steps, the schema, validation (`python -m tools.validate_knowledge`),
and how to diff against the previous version. Shipped as a Claude skill (`SKILL.md`) and a
Copilot prompt file with identical content.

## Page UX

- First launch: GUID generated; "Connect share folder" with the configured path shown.
- Input ALGOIDT (digits only) → Submit → pending state with elapsed time; timeout (default
  60 s) says the service may be down, keeps polling quietly a while longer.
- Result: order header; tag table (tag, name, value, value meaning, description; expandable
  row for allowed values, example, applies-to, sources); effects panel grouped by severity
  with `fires`/`may fire` badges and override chains.
- `not_found` / `error` shown as clear messages. Recent requests list (localStorage).
- Several requests can be in flight; each is matched by requestId.

## Testing

- pytest for the analyzer: fixmsg parsing (nesting, commas, empty), condition evaluation
  (each operator, null guards, unknown), last-writer-wins chains, relationships.
- Knowledge JSON validation test (schema, unique ids, every rule's tags exist in `tags`).
- Service round-trip test with `--fake-kdb` and a temp share folder.
- configure script test on a temp folder.

## Out of scope

Historical (HDB) lookups, `target_stock`/market-data condition evaluation, authentication,
editing tags.
