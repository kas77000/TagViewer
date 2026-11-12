# TagViewer — Copilot instructions

* To regenerate or update the tag knowledge base (`knowledge/tag-knowledge.json`), follow
  `.github/prompts/tag-knowledge.prompt.md` (run it as the `/tag-knowledge` prompt). The
  same procedure lives in `skills/` for other agents.
* The JSON contract is `knowledge/schema.md`; never hand-edit the generated file — put
  corrections in `knowledge/curated/`.
* Core logic is in `tagviewer/` (standard library only). Run `python -m pytest -q` after changes.
