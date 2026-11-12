---
mode: agent
description: Regenerate or update TagViewer's knowledge/tag-knowledge.json (tags, values, examples, relationships, conflicts, rules) from the ai3 project, its config files and the BCORE_Tags CSV.
---

# Regenerate the TagViewer tag knowledge base

TagViewer explains an order's `fixmsg`. Everything it knows comes from
`knowledge/tag-knowledge.json` (contract: `knowledge/schema.md` - read it first). This
procedure rebuilds that file from the **ai3** project. Work from the TagViewer repo root.

## Inputs (ask the user for any path you cannot find)

| Input | Typical location | Used for |
|---|---|---|
| ai3 source | `<ai3>/src/com/kas/ai/*.java` (`Parameters.java` is the core) | every 9012 sub-tag, top-level tags, behaviour |
| rule files | `<ai3>/config/*fixmsg.properties` (`ai.fixmsg.properties`, `APIB.ai.fixmsg.properties`, ...) | rules that set/override tags |
| other config | `<ai3>/config/ai.server.properties`, `ai.compoundtrigger_*.js`, `AI-FIXMSG-CONFLICTS.md` | defaults, compound triggers, known conflicts |
| docs | `<ai3>/*.md` runbooks | combinations that change behaviour |
| tag dictionary | `BCORE_Tags*.csv` (anywhere the user says; header `TagNumber,version,tagName,interface,comments,availability,implemented,example,modifiedBy,modifiedTime,oldTagInfo,clientTagNumber,description,parametersField,validValues`) | official names/descriptions/examples |

Use only these text sources. Do **not** rely on photos, OCR output or folders of images:
they will not exist on the production machine. Ignore `src/**/pics`.

## Ground truth you must respect (from the engine code)

* `fixmsg` = `;`-separated `tag=value`. `9012` holds `^`-separated sub-tags; values may be
  quoted `<tq>...</tq>`. `9050`/`9052` are appended into `9012`. Several `9012=` segments
  merge, later values win (`Parameters.stripFixTags`, `parse9012`).
* Each 9012 sub-tag is parsed by a method `__p_<number>[_<ALIAS>]` in `Parameters.java`
  (`setupParamParser`). The alias may be used instead of the number. Numbers >= 1500 are
  internal ("not meant to be known by traders").
* `ai.fixmsg.properties`: `[IR=n;]writes :: conditions`; **every** matching rule applies,
  top to bottom, last writer wins (`combine_fix_msg_config=false`); `tag9012(X)=null` means
  "only if nothing set X yet". Each applied rule **appends** its writes to the stored
  fixmsg - TagViewer uses that to detect which rules fired.
* If any of this changed in the source (delimiters, rule semantics, parser naming), stop
  and update `tagviewer/` (and its tests) before regenerating data.

## Procedure

1. **Extract** (mechanical, seconds):
   ```
   python -m tools.extract_java_tags --src <ai3>/src --out knowledge/build/raw_java_tags.json
   ```
   Check the count against `grep -c "void __p_" Parameters.java`.

2. **Plan batches.** Full rebuild: `python -m tools.plan_batches --size 110`.
   Update after an algo change: `python -m tools.plan_batches --changed-only` (only
   new/changed/undocumented sub-tags; unchanged definitions are kept from the current
   knowledge file - copy them into the parts as described in step 5).

3. **Enrich sub-tags** - one agent per `knowledge/build/batches/batch_N.json`, in parallel
   when you can spawn subagents. Give each this brief:

   > For each tag in `<batch file>` (fields: number, alias, line/endLine in Parameters.java,
   > body, assigns, usages) produce a Tag object per `knowledge/schema.md`. Read the parser
   > body, then grep its fields/accessors across `<ai3>/src` to learn what the engine does
   > with the value: value format (comma fields, prefixes like B/C/R/S, times), default
   > (AlgoConfig `setField(..., "_field", getProperty("prop","default"))` or initialiser),
   > which algorithms read it, algorithm-dependent behaviour (`_algorithm == Algorithm.X`).
   > Record in `interactions` every case where the tag overrides/is overridden by another
   > tag, is ignored for some algos or when another tag is set, requires another tag,
   > causes a reject (`_err_msg`, `KO`), converts the algo, or changes other parameters.
   > Also check the rule files for rules writing this tag (by number or alias) and cite
   > them (`ai.fixmsg.properties:<line>`). Triggers use `tag9012(<number>)`, `fixTag(<n>)`,
   > `algorithm`, `side`, or engine condition field names, and must include
   > `tag9012(<n>)!=null`. Cite `File.java:line` for every claim; unknown → say so and set
   > `confidence: "low"`; never invent. `internal: true` for numbers >= 1500. Cover every
   > tag in the batch (short treatment for trivial setters). Write a JSON array to
   > `knowledge/build/parts/tags_batch_N.json` and check it parses and has the batch count.

4. **Global part** - one agent writes `knowledge/build/parts/global.json` with keys
   `parsing`, `algorithms` (every `Algorithm` enum value), `conditionFields` (every field
   used right of `::` in all rule files, with how the engine computes it and
   `resolvableFrom`: fixmsg | target | target_stock | engine), `topLevelTags` (9001-9010,
   9012, 9050, 9052, 9060, 9065, 9066, 9703 and every other top-level tag the engine reads),
   `relationships` (cross-cutting effects: ALGO overriding 9001, 9012 merging, 9060
   sub-params/compound algos, relay/IR, CUSTOM conversion via 58/61, AUCTIONS forcing
   14/15/171, market-specific conversions, KO rejects, runbook combinations) and
   `knownConflicts` (each C-xx and appendix row of `AI-FIXMSG-CONFLICTS.md`; re-derive
   them if the rule file changed - look for unguarded writers after other writers, dead
   `null`-guarded rules, misspelled fields, bare tokens without a field).

5. **Changed-only runs:** copy the unchanged tag objects from the current
   `knowledge/tag-knowledge.json` into `knowledge/build/parts/tags_kept.json` (array) so the
   build sees them; agents' new parts override them by id (later files win; name them so
   they sort after `tags_kept`, e.g. `tags_update_1.json`).

6. **Tag dictionary:**
   ```
   python -m tools.import_bcore_csv <path>/BCORE_Tags*.csv
   ```
   (writes `knowledge/build/parts/bcore.json`; the build attaches it to every tag and fills
   gaps in low-confidence entries.)

7. **Build + validate:**
   ```
   python -m tools.build_knowledge --ai3 <ai3> --version <yyyy-mm-dd>.<n>
   python -m tools.validate_knowledge
   python -m pytest -q
   ```
   Fix every ERROR. Hand corrections go in `knowledge/curated/*.json` (arrays of partial tag
   objects with `id`), never into the generated file.

8. **Spot-check** with real fixmsgs (ask the user for a few, or take them from kdb):
   ```
   python -m tools.explain "<fixmsg>" --side sellshort --algo SDMA --context compositeExchangeCode=HK
   ```
   Confirm names/meanings read correctly and effects are plausible.

9. **Report and commit**: counts (tags, low-confidence, stubs, relationships, rules,
   conflicts), what changed since the previous version, then commit
   `knowledge/tag-knowledge.json` (the service reloads it automatically when the file
   changes on its machine).

## Quality bar

* Every tag the engine parses is present (stubs only as a last resort).
* Descriptions say what the tag *does to the order*, in trader language, 1-4 sentences.
* `allowedValues` for flags/enums with the meaning of each value; `example` with a real
  value and what it does.
* Interactions are specific (which tag, which algo, what happens) and cited.
