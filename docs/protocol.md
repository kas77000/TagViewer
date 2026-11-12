# Share-folder protocol (schemaVersion 1)

```
<share>/.tagviewer-share                 {"shareId", "createdAt", "sharePath"}
<share>/requests/<userGuid>__<requestId>.json
<share>/processing/                      claimed by the service (atomic rename)
<share>/processed/<yyyymmdd>/  failed/<yyyymmdd>/
<share>/responses/<userGuid>/<requestId>.json
<share>/status/service.json              heartbeat every 5 s
```

GUIDs and request ids are lower-case UUIDs. Writers make files appear atomically (the
browser's `createWritable` swaps on close; the service writes `.tmp` and renames).

## Request (page → service)

```json
{"schemaVersion": 1, "requestId": "uuid", "userGuid": "uuid", "algoidt": 12345678,
 "createdAt": "2026-11-13T09:12:00.000Z"}
```

The file name must equal `<userGuid>__<requestId>.json`; `algoidt` is an integer
1..2147483647. Anything else is answered with `status: "error"` (when the name carries a
valid guid/id) and archived in `failed/`.

## Response (service → page)

```jsonc
{
  "schemaVersion": 1, "requestId": "...", "userGuid": "...", "algoidt": 12345678,
  "status": "ok",                       // ok | not_found | error
  "message": "",                        // human text for not_found/error, or a note
  "answeredAt": "...", "knowledgeVersion": "2026-11-13.1", "service": "<host>",
  "matches": 1,                         // rows found for the id (the last one is used)
  "order": {"id_target", "sym", "side", "size", "algo", "trader", "basket", "time", "limit_price", "fixmsg"},
  "ruleSet": "ai.fixmsg.properties",
  "clientFixmsg": "...",                // part of fixmsg before the first config-rule segment
  "ruleSegmentsDetected": true,
  "tags": [{"id": "9012.1546", "key": "PQS", "number": "1546", "parent": "9012", "value": "0.5,1,0,1",
            "known": true, "history": ["1", "0.5,1,0,1"], "alias": "PQS", "name": "...", "category": "...",
            "description": "...", "valueMeaning": "...", "valueFormat": "...", "type": "...",
            "allowedValues": [], "default": "...", "example": {}, "appliesTo": [], "algorithmDependent": [],
            "internal": false, "confidence": "high", "sources": []}],
  "effects": [{"id": "...", "origin": "rule|knowledge|conflict|fixmsg",
               "kind": "override|rewrite|conversion|ineffective|incompatible|requires|side_effect|reject|config_conflict",
               "severity": "high|medium|low|info", "status": "applied|fires|may_fire",
               "tags": [], "title": "...", "explanation": "...", "unresolvedConditions": [], "sources": []}],
  "overrideChains": [{"tag": "9012.154", "label": "...", "final": "0",
                      "steps": [{"source": "client", "value": "1"},
                                {"source": "ai.fixmsg.properties:44", "ruleId": "...", "value": "0", "status": "applied"}]}],
  "parseErrors": [],
  "counts": {"tags", "unknownTags", "effects", "rulesApplied", "rulesFire", "rulesMayFire"}
}
```

The page reads only `responses/<its own guid>/<requestId>.json` for request ids it sent,
checks both ids inside the file, then deletes the file. Uncollected responses are deleted
by the service after `KEEP_DAYS`.

## Heartbeat

`status/service.json`: `{"service", "pid", "version", "startedAt", "heartbeatAt", "handled",
"knowledgeVersion", "lastError"}`. The page shows the service offline when `heartbeatAt` is
older than 30 s; queued requests are answered when it comes back.
