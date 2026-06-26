# pf2e-ofk

An [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
(OKF v0.1, Google Cloud, 2026) bundle of **Pathfinder Second Edition** spell
data, generated from the [pf2e](https://github.com/k-lisovskiy/pf2e) Foundry VTT
system JSON.

OKF represents knowledge as a directory tree of plain Markdown files with YAML
frontmatter — one file per concept, designed to be read by humans and AI agents
alike with no SDK or runtime.

## Layout

```
index.md            # bundle entry point (OKF reserved)
log.md              # change history (OKF reserved)
cantrips/
  index.md          # listing of every cantrip
  <spell-slug>.md   # one concept per cantrip
tools/
  build_okf.py      # producer / validator
```

Each cantrip document carries the required OKF `type` field plus recommended
fields (`title`, `description`, `resource`, `tags`, `timestamp`) and a few
custom fields useful for agents (`rank`, `actions`, `traditions`, `range`,
`targets`, `area`, `defense`, `duration`, `publication`). The body holds an
`# Overview` stat block, the spell's `## Description`, and `## Citations`.

## Regenerating

The bundle is generated from a sibling checkout of the `pf2e` repo:

```bash
python3 tools/build_okf.py --source ../pf2e/packs/pf2e/spells/spells/cantrip
```

Validate the bundle:

```bash
python3 tools/build_okf.py --check
```

## Scope

Currently covers all **cantrips**. Other spell ranks, focus spells, and rituals
can be added by extending the producer to additional source directories.

## License

Spell text is © Paizo Inc., used under the OGL / ORC terms noted in each
document's source. Bundle tooling follows the upstream pf2e project license.
