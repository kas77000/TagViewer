# `tag-knowledge.json` — schema

The knowledge base TagViewer uses to explain an order's `fixmsg`. Generated from the ai3
project (see `skills/claude/tag-knowledge/SKILL.md`); never edited by hand except through
the `knowledge/curated/` overrides.

```jsonc
{
  "meta": {
    "schemaVersion": 1,
    "version": "2026-11-13.1",          // bump on every regeneration: <date>.<n>
    "generatedAt": "2026-11-13T12:00:00Z",
    "generatedBy": "agent / tool name",
    "sources": ["ai3/src/com/kas/ai/Parameters.java", "ai3/config/ai.fixmsg.properties", ...],
    "notes": "free text"
  },

  "parsing": {                          // how a fixmsg is read (mirrors Parameters.java)
    "tagDelimiter": ";", "pairDelimiter": "=", "subDelimiter": "^",
    "quote": ["<tq>", "</tq>"], "nestedTags": ["9012"], "appendTo9012": ["9050", "9052"],
    "notes": "..."
  },

  "algorithms": [                       // values of 9001 / 9012 sub-tag 1 (ALGO)
    { "name": "VWAP", "description": "...", "family": "schedule|participation|liquidity-seeking|dma|auction|compound|...",
      "aliases": [], "sources": ["Algorithm.java:12"] }
  ],

  "clientAlgorithmTemplates": [        // client algo names (9001 / clientAlgorithm) that rules turn into real algos
    { "name": "FMRPOP", "description": "...", "becomes": "...", "sources": [...] }
  ],

  "conditionFields": [                  // fields usable in rule conditions / triggers
    { "name": "compositeExchangeCode", "description": "...", "resolvableFrom": "target|target_stock|fixmsg|engine",
      "examples": ["HK", "JP"] }
  ],

  "tags": [ Tag, ... ],                 // every top-level tag and every 9012 sub-tag
  "ruleSets": [ RuleSet, ... ],         // parsed ai.fixmsg.properties files
  "relationships": [ Relationship, ... ],
  "knownConflicts": [ Conflict, ... ]   // config defects (C-01 ...), also mirrored as relationships
}
```

## Tag

```jsonc
{
  "id": "9012.1546",           // top-level: "9001"; 9012 sub-tag: "9012.<number>"
  "number": "1546",
  "parent": "9012",            // null for top-level tags
  "alias": "PQS",              // alphabetic id usable instead of the number, or null
  "name": "Post quote size factor",
  "category": "posting",       // see categories below
  "description": "What it does, in plain words, 1-4 sentences.",
  "valueFormat": "factor[,level[,useavg[,strictcheck]]]",
  "type": "float",             // int|float|bool|string|enum|list|time|price|percent|composite
  "allowedValues": [ { "value": "0", "meaning": "..." } ],   // enums / flags; [] for free numbers
  "default": "1 (AlgoConfig post_quotesize_factor)",
  "example": { "value": "0.5,1,0,1", "explanation": "Post at most half the quote size, ..." },
  "appliesTo": ["ALL"],        // or algorithm names
  "algorithmDependent": [ { "algorithms": ["PART2"], "behavior": "sets lit target rate instead" } ],
  "interactions": [ Interaction ],   // tag-level effects, merged into relationships
  "internal": false,           // true for numbers >= 1500 (engine-internal per Parameters.java)
  "confidence": "high",        // high: read from code; medium: inferred from usage; low: guessed from name
  "sources": ["Parameters.java:6562"]
}
```

Categories: `algorithm`, `schedule`, `participation`, `limit-price`, `would`, `dark`,
`posting`, `taking`, `auction-open`, `auction-close`, `routing-venue`, `risk-control`,
`short-sell`, `market-specific`, `compound`, `client-info`, `reject`, `monitoring`,
`internal`, `other`.

## Interaction (inside a tag) / Relationship (top level)

```jsonc
{
  "id": "REL-9012.1546-01",     // relationships: unique
  "kind": "override",           // override | rewrite | ineffective | incompatible | requires | side_effect | reject | conversion
  "severity": "medium",         // high | medium | low | info
  "tags": ["9012.1546", "9012.6"],
  "algorithms": ["VWAP"],       // [] = any
  "trigger": [ Condition ],     // evaluable: when all hold for an order, the effect applies
  "title": "PQS ignored when ...",
  "explanation": "What happens to the order and why.",
  "sources": ["Parameters.java:12345"]
}
```

* `override` — one tag's value replaces/beats another's (e.g. 9012 ALGO beats 9001).
* `rewrite` — the engine or a config rule changes the tag/algorithm (e.g. SDMA+sellshort HK → PEG).
* `ineffective` — the tag is accepted but has no effect in this combination.
* `incompatible` — tags/values that should not be used together (unexpected behaviour).
* `requires` — the tag only works if another tag/value is present.
* `side_effect` — setting the tag also changes other behaviour.
* `reject` — the combination makes the engine reject the order (`KO`, `_err_msg`).
* `conversion` — the order is converted to another algo/strategy.

## Condition (shared by rules, triggers)

```jsonc
{ "field": "tag9012(154)", "op": "=", "value": "0^1", "raw": "tag9012(154)=0^1" }
```

Ops: `= != < <= > >= ~ !~` plus `js` (JavaScript, never evaluated) and `invalid`.
`value` `a^b` is an or-list; `null` means not set. Fields: `tag9012(<number|alias>)`,
`fixTag(<top-level tag>)`, `algorithm`, `side`, `size`, `basket`, `trader`, and any name in
`conditionFields`. Triggers must include the presence of their own tag(s), e.g.
`tag9012(1546)!=null`.

## RuleSet

Produced by `python -m tools.build_rules` from `ai.fixmsg.properties` files (see
`tagviewer/rules.py`): `{ruleSet, file, includes, rules: [{id, line, order, comment,
irelay, writes: [{tag, key, value, dynamic}], writesRaw, conditions, raw}]}`.
Rules are evaluated top to bottom, every matching rule is applied, last writer wins
(`combine_fix_msg_config=false`).

## Conflict

`{id: "C-01", severity, lines: [..], currentLines: [..], ruleSet, title, problem, fix,
tags: [..]}` from the conflict analysis of the rule file. `lines` are as cited by the
report; `currentLines` are the same rules in the rule file as shipped (the analyzer uses
`currentLines` when present, to match rules by line).
