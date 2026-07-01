# pf2e-ofk

An [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
(OKF v0.1, Google Cloud, 2026) bundle of **Pathfinder Second Edition** rules
data, generated from the [pf2e](https://github.com/k-lisovskiy/pf2e) Foundry VTT
system JSON.

OKF represents knowledge as a directory tree of plain Markdown files with YAML
frontmatter — one file per concept, designed to be read by humans and AI agents
alike with no SDK or runtime.

## Layout

The whole bundle lives under `rules/` so it can grow beyond spells and feats
(equipment, bestiary, conditions, ...). Each domain is nested at `rules/<domain>/`.

```
index.md              # bundle entry point (OKF reserved)
log.md                # change history (OKF reserved)
rules/
  index.md            # rules index (categories)
  spells/
    index.md          # all spell categories
    spells/
      index.md        # slot spells (cantrips + ranked)
      cantrips/{index.md, <slug>.md}
      rank-1/ ... rank-10/{index.md, <slug>.md}
    focus/{index.md, <slug>.md}
    rituals/{index.md, <slug>.md}
  feats/
    index.md          # all feat categories
    ancestry/
      index.md        # 54 ancestries
      <ancestry>/{index.md, <slug>.md}
    archetype/
      index.md        # 245 archetypes
      <archetype>/{index.md, <slug>.md}
    class/
      index.md        # 28 classes
      <class>/{index.md, <slug>.md}
    general/{index.md, <slug>.md}
    skill/{index.md, <slug>.md}
    mythic/{index.md, <slug>.md}
    miscellaneous/
      index.md        # aftermath, deviant, reincarnated, variant-rules
      <subcategory>/{index.md, <slug>.md}
tools/
  build_okf.py        # producer / validator
```

Every concept document carries the required OKF `type` field plus recommended
fields (`title`, `description`, `resource`, `tags`, `timestamp`). Spells add
`rarity`, `rank`, `actions`, `traditions`, `range`, `targets`, `area`,
`defense`, `duration`, `cost`, `publication` (rituals also `primary_check`,
`secondary_casters`, `secondary_checks`). Feats add `rarity`, `level`,
`category`/`subcategory`, `action_type`/`actions`, `frequency`,
`prerequisites`, `only_level_1`, `max_takable`, `self_effect`, `publication`.
The body holds an `# Overview` stat block, `## Description`, and `## Citations`.

## Regenerating

The bundle is generated from a sibling checkout of the `pf2e` repo:

```bash
python3 tools/build_okf.py --spells-source ../pf2e/packs/pf2e/spells \
                            --feats-source ../pf2e/packs/pf2e/feats
```

Use `--skip-spells` or `--skip-feats` to regenerate only one domain. Validate
the bundle:

```bash
python3 tools/build_okf.py --check
```

## Scope

- **Spells**: cantrips, ranked spells (1-10), focus spells, and rituals — 1,796 concepts.
- **Feats**: ancestry, archetype, class, general, skill, mythic, and
  miscellaneous feats — 5,987 concepts.

**7,783 concepts in total.**

## License

Rules text is © Paizo Inc., used under the OGL / ORC terms noted in each
document's source. Bundle tooling follows the upstream pf2e project license.
