# pf2e-ofk

An [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
(OKF v0.1, Google Cloud, 2026) bundle of **Pathfinder Second Edition** spell
data, generated from the [pf2e](https://github.com/k-lisovskiy/pf2e) Foundry VTT
system JSON.

OKF represents knowledge as a directory tree of plain Markdown files with YAML
frontmatter — one file per concept, designed to be read by humans and AI agents
alike with no SDK or runtime.

## Layout

The whole bundle lives under `rules/` so it can grow beyond spells (feats,
equipment, bestiary, conditions, ...). Spells are nested at `rules/spells/`.

```
index.md              # bundle entry point (OKF reserved)
log.md                # change history (OKF reserved)
rules/
  index.md            # rules index (categories)
  spells/
    index.md          # all spell categories
    cantrips/
      index.md
      <spell-slug>.md
    rank-1/ ... rank-10/
      index.md
      <spell-slug>.md
    focus/
      index.md
      <spell-slug>.md
    rituals/
      index.md
      <spell-slug>.md
tools/
  build_okf.py        # producer / validator
```

Each spell document carries the required OKF `type` field (`Cantrip`, `Spell`,
`Focus Spell`, or `Ritual`) plus recommended fields (`title`, `description`,
`resource`, `tags`, `timestamp`) and custom fields useful for agents (`rarity`,
`rank`, `actions`, `traditions`, `range`, `targets`, `area`, `defense`,
`duration`, `cost`, `publication`; rituals also carry `primary_check`,
`secondary_casters`, `secondary_checks`). The body holds an `# Overview` stat
block, the spell's `## Description`, and `## Citations`.

## Regenerating

The bundle is generated from a sibling checkout of the `pf2e` repo:

```bash
python3 tools/build_okf.py --source ../pf2e/packs/pf2e/spells
```

Validate the bundle:

```bash
python3 tools/build_okf.py --check
```

## Scope

Covers the full PF2e spell catalogue: **cantrips**, **ranked spells (1-10)**,
**focus spells**, and **rituals** — 1,796 concepts in total.

## License

Spell text is © Paizo Inc., used under the OGL / ORC terms noted in each
document's source. Bundle tooling follows the upstream pf2e project license.
