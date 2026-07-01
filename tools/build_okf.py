#!/usr/bin/env python3
"""Generate an Open Knowledge Format (OKF) bundle from PF2e rules JSON.

OKF v0.1 (Google Cloud, 2026-06-12) represents knowledge as a directory tree of
Markdown files with YAML frontmatter, one file per concept. This producer reads
Foundry VTT PF2e compendium documents (spells and feats so far) and emits a
conformant OKF bundle under rules/, organized so further categories (equipment,
bestiary, conditions, ...) can be added the same way.

Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

Usage:
    python3 tools/build_okf.py --spells-source ../pf2e/packs/pf2e/spells \\
                                --feats-source ../pf2e/packs/pf2e/feats
    python3 tools/build_okf.py --check        # validate the existing bundle
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

# Bundle root is the repo root (parent of this tools/ directory).
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPELLS_SOURCE = ROOT.parent / "pf2e" / "packs" / "pf2e" / "spells"
DEFAULT_FEATS_SOURCE = ROOT.parent / "pf2e" / "packs" / "pf2e" / "feats"
TIMESTAMP = "2026-06-26T00:00:00Z"

# The whole rules bundle lives under rules/ so it can grow beyond spells
# (feats, equipment, bestiary, ...). Each domain is nested at rules/<domain>/.
RULES_DIR = "rules"
SPELLS_OUT = f"{RULES_DIR}/spells"
FEATS_OUT = f"{RULES_DIR}/feats"

# Spell categories: (concept type, source subdir under --source, output leaf
# under rules/spells/, resource-URI leaf, trait that duplicates the type and is
# dropped from tags). Ranked spells expand from spells/rank-1 .. spells/rank-10.
CATEGORIES = [
    ("Cantrip",    "spells/cantrip", "spells/cantrips", "cantrip", "cantrip"),
    ("Focus Spell","focus",          "focus",           "focus",   "focus"),
    ("Ritual",     "rituals",        "rituals",         "rituals", None),
]
for _r in range(1, 11):
    CATEGORIES.append(
        ("Spell", f"spells/rank-{_r}", f"spells/rank-{_r}", f"rank-{_r}", "cantrip")
    )

# Feat categories: (category key, source subdir under --feats-source, human
# label, grouped). "grouped" categories have named subfolders (an ancestry,
# class, archetype, or misc subcategory) that become their own output
# directory with its own index; each is globbed recursively so ancestry's
# extra level-N nesting is transparently flattened. Ungrouped categories glob
# everything recursively into one flat output directory.
FEAT_CATEGORIES = [
    ("ancestry",      "ancestry",      "Ancestry Feats",      True),
    ("archetype",     "archetype",     "Archetype Feats",     True),
    ("class",         "class",         "Class Feats",         True),
    ("general",       "general",       "General Feats",       False),
    ("skill",         "skill",         "Skill Feats",         False),
    ("mythic",        "mythic",        "Mythic Feats",        False),
    ("miscellaneous", "miscellaneous", "Miscellaneous Feats", True),
]


# --------------------------------------------------------------------------- #
# Foundry inline reference cleanup
# --------------------------------------------------------------------------- #

def _balanced(text: str, start: int) -> tuple[str, int]:
    """Given text[start] == '[', return (inner, index_after_closing_bracket)."""
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    return text[start + 1 :], len(text)


def _clean_formula(formula: str) -> str:
    """Make a Foundry damage formula human-readable."""
    formula = formula.replace("@item.level", "level").replace("@item.rank", "rank")
    formula = formula.replace("@actor.level", "actor level")
    return formula.strip()


def _render_damage(body: str, label: str | None) -> str:
    if label:
        return label.strip()
    # body looks like  FORMULA[trait,trait]
    idx = body.rfind("[")
    if idx == -1:
        return _clean_formula(body)
    formula = _clean_formula(body[:idx])
    traits = body[idx + 1 :].rstrip("]")
    words = [t.strip() for t in traits.split(",") if t.strip()]
    parts = [p for p in (formula, " ".join(words)) if p]
    return " ".join(parts)


def _render_uuid(body: str, label: str | None) -> str:
    if label:
        return label.strip()
    # Compendium.pf2e.actionspf2e.Item.Climb  ->  Climb
    if ".Item." in body:
        seg = body.split(".Item.", 1)[1]
    else:
        seg = body.rsplit(".", 1)[-1]
    return seg.strip()


def _render_check(body: str) -> str:
    parts = body.split("|")
    stat = parts[0].strip()
    dc = None
    for p in parts[1:]:
        if p.startswith("dc:"):
            dc = p[3:].strip()
    base = "flat check" if stat == "flat" else f"{stat} save"
    if dc and dc.isdigit():
        base += f" (DC {dc})"
    return base


def _render_template(body: str) -> str:
    parts = body.split("|")
    shape = parts[0].strip()
    dist = None
    for p in parts[1:]:
        if p.startswith("distance:"):
            dist = p[len("distance:") :].strip()
    return f"{dist}-foot {shape}" if dist else shape


def clean_inline(text: str) -> str:
    """Replace Foundry @Tag[...]{label} references with readable prose."""
    out = []
    i = 0
    pattern = re.compile(r"@(\w+)\[")
    while i < len(text):
        m = pattern.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i : m.start()])
        tag = m.group(1)
        body, after = _balanced(text, m.end() - 1)
        label = None
        if after < len(text) and text[after] == "{":
            end = text.find("}", after)
            if end != -1:
                label = text[after + 1 : end]
                after = end + 1
        if tag == "Damage":
            out.append(_render_damage(body, label))
        elif tag == "UUID":
            out.append(_render_uuid(body, label))
        elif tag == "Check":
            out.append(_render_check(body))
        elif tag == "Template":
            out.append(_render_template(body))
        else:
            out.append(label.strip() if label else body)
        i = after
    return "".join(out)


# --------------------------------------------------------------------------- #
# HTML -> Markdown
# --------------------------------------------------------------------------- #

def convert_tables(text: str) -> str:
    """Turn <table> markup into a Markdown pipe table, cell HTML stripped."""
    def repl(match: re.Match) -> str:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", match.group(0), flags=re.I | re.S)
        md_rows = []
        for i, row in enumerate(rows):
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.I | re.S)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if not cells:
                continue
            md_rows.append("| " + " | ".join(cells) + " |")
            if i == 0:
                md_rows.append("| " + " | ".join("---" for _ in cells) + " |")
        return "\n\n" + "\n".join(md_rows) + "\n\n"
    return re.sub(r"<table[^>]*>.*?</table>", repl, text, flags=re.I | re.S)


def html_to_markdown(text: str) -> str:
    text = convert_tables(text)
    text = clean_inline(text)
    text = re.sub(r"<hr\s*/?>", "\n\n---\n\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(strong|b)\s*>", "**", text, flags=re.I)
    text = re.sub(r"</?(em|i)\s*>", "*", text, flags=re.I)
    text = re.sub(r"<li\s*>", "- ", text, flags=re.I)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</?(ul|ol)\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<p\s*>", "", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"</?h[1-6]\s*>", "\n\n**", text, flags=re.I)  # demote headings
    text = re.sub(r"<[^>]+>", "", text)  # strip any remaining tags
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_CALLOUT_LABELS = {"requirements", "requirement", "trigger", "frequency", "cost",
                   "special", "prerequisite", "prerequisites"}


def _strip_leading_callouts(markdown: str) -> str:
    """Skip leading '**Requirements** ...'-style callout paragraphs so the
    one-line summary reflects the actual description, not a precondition."""
    paragraphs = markdown.split("\n\n")
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i].strip()
        if not p or p == "---":
            i += 1
            continue
        m = re.match(r"^\*\*([A-Za-z ]+?)\*\*", p)
        if m and m.group(1).strip().lower() in _CALLOUT_LABELS:
            i += 1
            continue
        break
    return "\n\n".join(paragraphs[i:]).strip()


def first_sentence(markdown: str) -> str:
    """Plain-text one-line summary derived from the body."""
    text = _strip_leading_callouts(markdown)
    text = re.sub(r"(?m)^-{3,}$", "", text)  # drop standalone --- dividers
    plain = re.sub(r"[*_`#>]", "", text)  # keep hyphens inside real words
    plain = re.sub(r"\s+", " ", plain).strip()
    m = re.search(r"(.+?[.!?])(\s|$)", plain)
    summary = m.group(1) if m else plain
    if len(summary) > 200:
        summary = summary[:197].rstrip() + "..."
    return summary.strip()


# --------------------------------------------------------------------------- #
# YAML emission
# --------------------------------------------------------------------------- #

def yaml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_list(values: list[str]) -> str:
    return "[" + ", ".join(yaml_str(v) for v in values) + "]"


# --------------------------------------------------------------------------- #
# Spell -> concept document
# --------------------------------------------------------------------------- #

def summarize_area(area) -> str:
    if not area:
        return ""
    value = area.get("value")
    shape = area.get("type", "")
    if value is not None:
        return f"{value}-foot {shape}".strip()
    return shape


def summarize_defense(defense) -> str:
    if not defense:
        return ""
    save = defense.get("save")
    if not save:
        return ""
    stat = save.get("statistic", "")
    return f"basic {stat}".strip() if save.get("basic") else stat


def build_concept(type_name: str, slug: str, data: dict, resource: str,
                  source_relpath: str, drop_trait: str | None) -> str:
    sys_ = data["system"]
    name = data["name"]
    traits = sys_.get("traits", {})
    rarity = traits.get("rarity", "common")
    traditions = traits.get("traditions", []) or []
    trait_values = traits.get("value", []) or []
    rank = sys_.get("level", {}).get("value", 0)
    actions = str(sys_.get("time", {}).get("value", "")).strip()
    rng = (sys_.get("range") or {}).get("value", "") or ""
    targets = (sys_.get("target") or {}).get("value", "") or ""
    area = summarize_area(sys_.get("area"))
    defense = summarize_defense(sys_.get("defense"))
    duration = (sys_.get("duration") or {}).get("value", "") or ""
    cost = (sys_.get("cost") or {}).get("value", "") or ""
    publication = (sys_.get("publication") or {}).get("title", "") or ""
    ritual = sys_.get("ritual") or {}

    body_md = html_to_markdown(sys_.get("description", {}).get("value", ""))
    description = first_sentence(body_md) or f"The {name} {type_name.lower()}."

    # tags hold genuine spell traits only; rarity and traditions have their own
    # fields, and the trait that names the category (e.g. "cantrip"/"focus")
    # duplicates the type field, so it is dropped.
    tags = [t for t in trait_values if t != drop_trait]
    rank_suffix = f" ({type_name.lower()})" if type_name in ("Cantrip", "Focus Spell") else ""

    fm = ["---"]
    fm.append(f"type: {type_name}")
    fm.append(f"title: {yaml_str(name)}")
    fm.append(f"description: {yaml_str(description)}")
    fm.append(f"resource: {yaml_str(resource)}")
    fm.append(f"tags: {yaml_list(tags)}")
    fm.append(f"timestamp: {TIMESTAMP}")
    fm.append(f"rarity: {yaml_str(rarity)}")
    fm.append(f"rank: {rank}")
    fm.append(f"actions: {yaml_str(actions)}")
    fm.append(f"traditions: {yaml_list(list(traditions))}")
    fm.append(f"range: {yaml_str(rng)}")
    fm.append(f"targets: {yaml_str(targets)}")
    fm.append(f"area: {yaml_str(area)}")
    fm.append(f"defense: {yaml_str(defense)}")
    fm.append(f"duration: {yaml_str(duration)}")
    fm.append(f"cost: {yaml_str(cost)}")
    if ritual:
        primary = (ritual.get("primary") or {}).get("check", "") or ""
        secondary = ritual.get("secondary") or {}
        fm.append(f"primary_check: {yaml_str(primary)}")
        fm.append(f"secondary_casters: {yaml_str(str(secondary.get('casters', '')))}")
        fm.append(f"secondary_checks: {yaml_str(secondary.get('checks', '') or '')}")
    fm.append(f"publication: {yaml_str(publication)}")
    fm.append("---")

    overview = ["# Overview", ""]
    overview.append(f"- **Rank**: {rank}{rank_suffix}")
    if actions:
        overview.append(f"- **Cast**: {actions}")
    if ritual:
        primary = (ritual.get("primary") or {}).get("check", "") or ""
        secondary = ritual.get("secondary") or {}
        if primary:
            overview.append(f"- **Primary Check**: {primary}")
        if secondary.get("casters"):
            overview.append(f"- **Secondary Casters**: {secondary['casters']}")
        if secondary.get("checks"):
            overview.append(f"- **Secondary Checks**: {secondary['checks']}")
    if cost:
        overview.append(f"- **Cost**: {cost}")
    if rng:
        overview.append(f"- **Range**: {rng}")
    if targets:
        overview.append(f"- **Targets**: {targets}")
    if area:
        overview.append(f"- **Area**: {area}")
    if defense:
        overview.append(f"- **Defense**: {defense}")
    if duration:
        overview.append(f"- **Duration**: {duration}")
    if traditions:
        overview.append(f"- **Traditions**: {', '.join(traditions)}")
    if trait_values:
        overview.append(f"- **Traits**: {', '.join(trait_values)}")

    citations = [
        "# Citations",
        "",
        f"[1] {publication}" if publication else "[1] Pathfinder 2e",
        f"[2] Source: `{source_relpath}` (pf2e system data)",
    ]

    doc = "\n".join(fm) + "\n\n"
    doc += "\n".join(overview) + "\n\n"
    doc += "## Description\n\n" + body_md + "\n\n"
    doc += "\n".join(citations) + "\n"
    return doc


def write_index(out_dir: Path, type_name: str, heading: str, description: str,
                entries: list[tuple[str, str]], written: list) -> None:
    """Write an index.md listing concept entries (slug, name) for a directory."""
    rel = out_dir.relative_to(ROOT).as_posix()
    prefix = "" if rel == "." else f"/{rel}"
    lines = [
        "---",
        "type: Index",
        f"title: {yaml_str(heading)}",
        f"description: {yaml_str(description)}",
        f"timestamp: {TIMESTAMP}",
        "---",
        "",
        f"# {heading}",
        "",
        description,
        "",
    ]
    for slug, name in sorted(entries, key=lambda e: e[1].lower()):
        lines.append(f"- [{name}]({prefix}/{slug}.md)")
    text = "\n".join(lines) + "\n"
    (out_dir / "index.md").write_text(text, encoding="utf-8")
    written.append(((out_dir / "index.md").relative_to(ROOT).as_posix(), text))


# --------------------------------------------------------------------------- #
# Feat -> concept document
# --------------------------------------------------------------------------- #

_ISO_DURATION = re.compile(r"^PT?(\d+)?([HMS])$")
_ISO_UNITS = {"H": "hour", "M": "minute", "S": "second"}


def format_frequency(freq) -> str:
    """Humanize a {max, per} frequency dict; per may be a plain word ("day")
    or an ISO-8601 duration ("PT10M", "PT1H")."""
    if not freq:
        return ""
    maxv = freq.get("max")
    per = str(freq.get("per") or "").strip()
    if not per:
        return ""
    m = _ISO_DURATION.match(per)
    if m:
        num = m.group(1) or "1"
        unit = _ISO_UNITS.get(m.group(2), m.group(2))
        per = unit if num == "1" else f"{num} {unit}s"
    return f"{maxv} per {per}" if maxv else per


def build_feat_concept(type_name: str, category: str, subcategory: str, data: dict,
                       resource: str, source_relpath: str) -> str:
    sys_ = data["system"]
    name = data["name"]
    traits = sys_.get("traits", {})
    rarity = traits.get("rarity", "common")
    trait_values = traits.get("value", []) or []
    level = sys_.get("level", {}).get("value", 0)
    action_type = (sys_.get("actionType") or {}).get("value", "") or ""
    actions_val = (sys_.get("actions") or {}).get("value")
    actions = str(actions_val) if action_type == "action" and actions_val else ""
    frequency = format_frequency(sys_.get("frequency"))
    prerequisites = [p.get("value", "") for p in (sys_.get("prerequisites") or {}).get("value", [])]
    only_level_1 = bool(sys_.get("onlyLevel1", False))
    max_takable = sys_.get("maxTakable")
    self_effect = (sys_.get("selfEffect") or {}).get("name", "") or ""
    publication = (sys_.get("publication") or {}).get("title", "") or ""

    body_md = html_to_markdown(sys_.get("description", {}).get("value", ""))
    description = first_sentence(body_md) or f"The {name} feat."

    fm = ["---"]
    fm.append(f"type: {type_name}")
    fm.append(f"title: {yaml_str(name)}")
    fm.append(f"description: {yaml_str(description)}")
    fm.append(f"resource: {yaml_str(resource)}")
    fm.append(f"tags: {yaml_list(list(trait_values))}")
    fm.append(f"timestamp: {TIMESTAMP}")
    fm.append(f"rarity: {yaml_str(rarity)}")
    fm.append(f"level: {level}")
    fm.append(f"category: {yaml_str(category)}")
    fm.append(f"subcategory: {yaml_str(subcategory)}")
    fm.append(f"action_type: {yaml_str(action_type)}")
    fm.append(f"actions: {yaml_str(actions)}")
    fm.append(f"frequency: {yaml_str(frequency)}")
    fm.append(f"prerequisites: {yaml_list(prerequisites)}")
    fm.append(f"only_level_1: {'true' if only_level_1 else 'false'}")
    fm.append(f"max_takable: {max_takable if max_takable else ''}")
    fm.append(f"self_effect: {yaml_str(self_effect)}")
    fm.append(f"publication: {yaml_str(publication)}")
    fm.append("---")

    action_label = {
        "passive": "Passive", "reaction": "Reaction", "free": "Free Action",
    }.get(action_type, f"{actions} action{'s' if actions != '1' else ''}" if actions else action_type)

    overview = ["# Overview", ""]
    overview.append(f"- **Level**: {level}")
    cat_line = category.capitalize()
    if subcategory:
        cat_line += f" ({subcategory})"
    overview.append(f"- **Category**: {cat_line}")
    if action_label:
        overview.append(f"- **Action**: {action_label}")
    if frequency:
        overview.append(f"- **Frequency**: {frequency}")
    if prerequisites:
        overview.append(f"- **Prerequisites**: {', '.join(prerequisites)}")
    special = []
    if only_level_1:
        special.append("Can only be selected at 1st level.")
    if max_takable:
        special.append(f"Can be taken up to {max_takable} times.")
    if self_effect:
        special.append(f"Grants effect: {self_effect}.")
    if special:
        overview.append(f"- **Special**: {' '.join(special)}")
    if trait_values:
        overview.append(f"- **Traits**: {', '.join(trait_values)}")

    citations = [
        "# Citations",
        "",
        f"[1] {publication}" if publication else "[1] Pathfinder 2e",
        f"[2] Source: `{source_relpath}` (pf2e system data)",
    ]

    doc = "\n".join(fm) + "\n\n"
    doc += "\n".join(overview) + "\n\n"
    doc += "## Description\n\n" + body_md + "\n\n"
    doc += "\n".join(citations) + "\n"
    return doc


# --------------------------------------------------------------------------- #
# Bundle assembly
# --------------------------------------------------------------------------- #

def generate_spells(source: Path) -> tuple[list[tuple[str, str]], dict[str, int]]:
    written: list[tuple[str, str]] = []
    counts: dict[str, int] = {}

    for type_name, src_sub, out_leaf, uri_leaf, drop_trait in CATEGORIES:
        src_dir = source / src_sub
        files = sorted(src_dir.glob("*.json"))
        if not files:
            sys.exit(f"No JSON spell files found in {src_dir}")
        out_dir = ROOT / SPELLS_OUT / out_leaf
        out_dir.mkdir(parents=True, exist_ok=True)
        entries = []
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            slug = path.stem
            resource = f"pf2e://spells/{uri_leaf}/{slug}"
            source_relpath = f"packs/pf2e/spells/{src_sub}/{slug}.json"
            doc = build_concept(type_name, slug, data, resource, source_relpath, drop_trait)
            (out_dir / f"{slug}.md").write_text(doc, encoding="utf-8")
            written.append(((out_dir / f"{slug}.md").relative_to(ROOT).as_posix(), doc))
            entries.append((slug, data["name"]))

        counts[out_leaf] = len(entries)
        m = re.match(r"spells/rank-(\d+)$", out_leaf)
        if m:
            write_index(out_dir, type_name, f"Rank {m.group(1)} Spells",
                        f"All {len(entries)} rank {m.group(1)} spells.", entries, written)
        else:
            label = {"spells/cantrips": "Cantrips", "focus": "Focus Spells",
                     "rituals": "Rituals"}[out_leaf]
            write_index(out_dir, type_name, f"PF2e {label}",
                        f"All {len(entries)} Pathfinder 2e {label.lower()}.", entries, written)

    rank_total = sum(counts[f"spells/rank-{r}"] for r in range(1, 11))
    slot_spells_total = counts["spells/cantrips"] + rank_total
    spells_total = sum(counts.values())

    # rules/spells/spells/index.md — slot spells (cantrips + ranked).
    slot_lines = [
        "---", "type: Index", 'title: "PF2e Slot Spells"',
        f'description: "All {slot_spells_total} Pathfinder 2e slot spells: cantrips and ranks 1-10."',
        f"timestamp: {TIMESTAMP}", "---", "",
        "# Slot Spells", "",
        f"{slot_spells_total} spell concepts.", "",
        f"- [Cantrips](/{SPELLS_OUT}/spells/cantrips/index.md) — {counts['spells/cantrips']} cantrips",
        "",
        f"## Ranked spells (ranks 1-10) — {rank_total} spells",
        "",
    ]
    for r in range(1, 11):
        slot_lines.append(f"- [Rank {r}](/{SPELLS_OUT}/spells/rank-{r}/index.md) — {counts[f'spells/rank-{r}']} spells")
    slot_index = "\n".join(slot_lines) + "\n"
    (ROOT / SPELLS_OUT / "spells" / "index.md").write_text(slot_index, encoding="utf-8")
    written.append((f"{SPELLS_OUT}/spells/index.md", slot_index))

    # rules/spells/index.md — all spell categories.
    spells_lines = [
        "---", "type: Index", 'title: "PF2e Spells"',
        f'description: "All {spells_total} Pathfinder 2e spells: slot spells, focus spells, and rituals."',
        f"timestamp: {TIMESTAMP}", "---", "",
        "# Spells", "",
        f"{spells_total} spell concepts.", "",
        f"- [Slot Spells](/{SPELLS_OUT}/spells/index.md) — {slot_spells_total} spells (cantrips + ranks 1-10)",
        f"- [Focus Spells](/{SPELLS_OUT}/focus/index.md) — {counts['focus']} focus spells",
        f"- [Rituals](/{SPELLS_OUT}/rituals/index.md) — {counts['rituals']} rituals",
    ]
    spells_index = "\n".join(spells_lines) + "\n"
    (ROOT / SPELLS_OUT / "index.md").write_text(spells_index, encoding="utf-8")
    written.append((f"{SPELLS_OUT}/index.md", spells_index))

    print(f"  spells: cantrips={counts['spells/cantrips']}, ranked={rank_total}, "
          f"focus={counts['focus']}, rituals={counts['rituals']} (total {spells_total})")
    return written, counts


# Grouped feat categories' subfolders are named by this kind of entity.
_FEAT_GROUPING_NOUN = {"ancestry": "ancestry", "archetype": "archetype",
                       "class": "class", "miscellaneous": "subcategory"}


def generate_feats(source: Path) -> tuple[list[tuple[str, str]], dict[str, int]]:
    written: list[tuple[str, str]] = []
    counts: dict[str, int] = {}

    for category, src_sub, label, grouped in FEAT_CATEGORIES:
        src_dir = source / src_sub
        if not src_dir.is_dir():
            sys.exit(f"No feats source directory found at {src_dir}")
        out_dir = ROOT / FEATS_OUT / category
        out_dir.mkdir(parents=True, exist_ok=True)
        type_name = label[:-1] if label.endswith("s") else label  # "Ancestry Feats" -> "Ancestry Feat"

        if grouped:
            group_dirs = sorted(p for p in src_dir.iterdir() if p.is_dir())
            if not group_dirs:
                sys.exit(f"No group subdirectories found in {src_dir}")
            group_entries: list[tuple[str, int]] = []
            for group_dir in group_dirs:
                group_slug = group_dir.name
                files = sorted(group_dir.rglob("*.json"))
                if not files:
                    continue
                group_out = out_dir / group_slug
                group_out.mkdir(parents=True, exist_ok=True)
                group_title = group_slug.replace("-", " ").title()
                entries = []
                seen_slugs: set[str] = set()
                for path in files:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    slug = path.stem
                    if slug in seen_slugs:
                        sys.exit(f"Duplicate feat slug {slug!r} in {group_out}")
                    seen_slugs.add(slug)
                    resource = f"pf2e://feats/{category}/{group_slug}/{slug}"
                    source_relpath = f"packs/pf2e/feats/{path.relative_to(source).as_posix()}"
                    doc = build_feat_concept(type_name, category, group_slug, data,
                                             resource, source_relpath)
                    (group_out / f"{slug}.md").write_text(doc, encoding="utf-8")
                    written.append(((group_out / f"{slug}.md").relative_to(ROOT).as_posix(), doc))
                    entries.append((slug, data["name"]))
                write_index(group_out, type_name, f"{group_title} — {label}",
                            f"All {len(entries)} {label.lower()} for {group_title}.",
                            entries, written)
                group_entries.append((group_slug, len(entries)))

            category_total = sum(c for _s, c in group_entries)
            noun = _FEAT_GROUPING_NOUN.get(category, "group")
            cat_lines = [
                "---", "type: Index", f'title: "PF2e {label}"',
                f'description: "All {category_total} Pathfinder 2e {label.lower()}, grouped by {noun}."',
                f"timestamp: {TIMESTAMP}", "---", "",
                f"# {label}", "",
                f"{category_total} feat concepts across {len(group_entries)} {noun} groups.", "",
            ]
            for group_slug, count in sorted(group_entries, key=lambda g: g[0]):
                group_title = group_slug.replace("-", " ").title()
                cat_lines.append(f"- [{group_title}](/{FEATS_OUT}/{category}/{group_slug}/index.md) — {count} feats")
            cat_index = "\n".join(cat_lines) + "\n"
            (out_dir / "index.md").write_text(cat_index, encoding="utf-8")
            written.append((f"{FEATS_OUT}/{category}/index.md", cat_index))
        else:
            files = sorted(src_dir.rglob("*.json"))
            if not files:
                sys.exit(f"No JSON feat files found in {src_dir}")
            entries = []
            seen_slugs = set()
            for path in files:
                data = json.loads(path.read_text(encoding="utf-8"))
                slug = path.stem
                if slug in seen_slugs:
                    sys.exit(f"Duplicate feat slug {slug!r} in {out_dir}")
                seen_slugs.add(slug)
                resource = f"pf2e://feats/{category}/{slug}"
                source_relpath = f"packs/pf2e/feats/{path.relative_to(source).as_posix()}"
                doc = build_feat_concept(type_name, category, "", data, resource, source_relpath)
                (out_dir / f"{slug}.md").write_text(doc, encoding="utf-8")
                written.append(((out_dir / f"{slug}.md").relative_to(ROOT).as_posix(), doc))
                entries.append((slug, data["name"]))
            write_index(out_dir, type_name, f"PF2e {label}",
                        f"All {len(entries)} Pathfinder 2e {label.lower()}.", entries, written)
            category_total = len(entries)

        counts[category] = category_total

    total = sum(counts.values())
    counts["total"] = total

    # rules/feats/index.md — roll-up of all feat categories.
    feats_lines = [
        "---", "type: Index", 'title: "PF2e Feats"',
        f'description: "All {total} Pathfinder 2e feats across ancestry, archetype, '
        'class, general, skill, mythic, and miscellaneous categories."',
        f"timestamp: {TIMESTAMP}", "---", "",
        "# Feats", "",
        f"{total} feat concepts.", "",
    ]
    for category, _src_sub, label, _grouped in FEAT_CATEGORIES:
        feats_lines.append(f"- [{label}](/{FEATS_OUT}/{category}/index.md) — {counts[category]} feats")
    feats_index = "\n".join(feats_lines) + "\n"
    (ROOT / FEATS_OUT / "index.md").write_text(feats_index, encoding="utf-8")
    written.append((f"{FEATS_OUT}/index.md", feats_index))

    print(f"  feats: " + ", ".join(f"{c}={counts[c]}" for c, *_ in FEAT_CATEGORIES) + f" (total {total})")
    return written, counts


def finalize(spell_counts: dict[str, int] | None,
            feat_counts: dict[str, int] | None) -> list[tuple[str, str]]:
    """Write the shared root/rules index files and log.md from both domains'
    counts, so either can be regenerated independently and re-finalized."""
    written: list[tuple[str, str]] = []

    spells_total = sum(spell_counts.values()) if spell_counts else 0
    feats_total = feat_counts["total"] if feat_counts else 0
    grand_total = spells_total + feats_total

    categories_lines = []
    if spell_counts:
        categories_lines.append(f"- [Spells](/{SPELLS_OUT}/index.md) — {spells_total} spell concepts")
    if feat_counts:
        categories_lines.append(f"- [Feats](/{FEATS_OUT}/index.md) — {feats_total} feat concepts")

    rules_index = (
        "---\n"
        "type: Index\n"
        'title: "PF2e Rules"\n'
        'description: "Pathfinder 2e rules content, organized by category."\n'
        f"timestamp: {TIMESTAMP}\n"
        "---\n\n"
        "# PF2e Rules\n\n"
        "Pathfinder Second Edition rules content. New categories (equipment, "
        "bestiary, conditions, ...) can be added alongside spells and feats.\n\n"
        "## Categories\n\n"
        + "\n".join(categories_lines) + "\n"
    )
    (ROOT / RULES_DIR / "index.md").write_text(rules_index, encoding="utf-8")
    written.append((f"{RULES_DIR}/index.md", rules_index))

    contents_parts = []
    if spell_counts:
        contents_parts.append(f"[Spells](/{SPELLS_OUT}/index.md) ({spells_total})")
    if feat_counts:
        contents_parts.append(f"[Feats](/{FEATS_OUT}/index.md) ({feats_total})")
    root_index = (
        "---\n"
        "type: Index\n"
        'title: "PF2e OKF Knowledge Bundle"\n'
        'description: "Open Knowledge Format bundle of Pathfinder 2e rules."\n'
        f"timestamp: {TIMESTAMP}\n"
        "---\n\n"
        "# PF2e OKF Knowledge Bundle\n\n"
        "An [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)"
        " (OKF v0.1) bundle of Pathfinder Second Edition rules.\n\n"
        "## Contents\n\n"
        f"- [Rules](/{RULES_DIR}/index.md) — {', '.join(contents_parts)}; "
        f"{grand_total} concepts total; more categories to come\n"
    )
    (ROOT / "index.md").write_text(root_index, encoding="utf-8")
    written.append(("index.md", root_index))

    log_lines = [
        "---", "type: Log", 'title: "Change Log"', f"timestamp: {TIMESTAMP}", "---", "",
        "# Change Log", "", f"## {TIMESTAMP[:10]}", "",
    ]
    if spell_counts:
        rank_total = sum(spell_counts[f"spells/rank-{r}"] for r in range(1, 11))
        log_lines.append(
            f"- OKF v0.1 bundle: {spells_total} PF2e spell concepts under `rules/spells/` "
            f"({spell_counts['spells/cantrips']} cantrips, {rank_total} ranked spells, "
            f"{spell_counts['focus']} focus spells, {spell_counts['rituals']} rituals) "
            "from the pf2e system JSON."
        )
    if feat_counts:
        breakdown = ", ".join(f"{feat_counts[c]} {label.lower()}" for c, _s, label, _g in FEAT_CATEGORIES)
        log_lines.append(
            f"- Added the PF2e feat catalogue under `rules/feats/` ({feats_total} feat "
            f"concepts: {breakdown}), grouped by ancestry/archetype/class/subcategory "
            "where the source data has one."
        )
    log = "\n".join(log_lines) + "\n"
    (ROOT / "log.md").write_text(log, encoding="utf-8")
    written.append(("log.md", log))

    print(f"  finalize: spells={spells_total}, feats={feats_total}, total={grand_total}")
    return written


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def check() -> int:
    # README.md is project documentation, not an OKF concept document.
    md_files = [f for f in ROOT.rglob("*.md") if f.name != "README.md"]
    if not md_files:
        print("No bundle files found — run the generator first.")
        return 1
    errors = 0
    concepts = 0
    for f in md_files:
        text = f.read_text(encoding="utf-8")
        if f.name != "index.md" and f.name != "log.md":
            concepts += 1
        if not text.startswith("---\n"):
            print(f"  MISSING frontmatter: {f.relative_to(ROOT)}")
            errors += 1
            continue
        fm = text.split("---\n", 2)[1]
        if not re.search(r"^type:\s*\S", fm, flags=re.M):
            print(f"  MISSING required 'type': {f.relative_to(ROOT)}")
            errors += 1
        for leftover in ("@UUID[", "@Damage[", "@Check[", "@Template[", "<p>", "</p>", "<table"):
            if leftover in text:
                print(f"  LEFTOVER {leftover!r} in {f.relative_to(ROOT)}")
                errors += 1
    # Verify intra-bundle links resolve.
    for f in md_files:
        for link in re.findall(r"\]\((/[^)]+\.md)\)", f.read_text(encoding="utf-8")):
            target = ROOT / link.lstrip("/")
            if not target.exists():
                print(f"  BROKEN link {link} in {f.relative_to(ROOT)}")
                errors += 1
    print(f"Checked {len(md_files)} markdown files, {concepts} concepts.")
    print("OK" if errors == 0 else f"{errors} problem(s) found.")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spells-source", type=Path, default=DEFAULT_SPELLS_SOURCE,
                        help="PF2e spells pack directory (packs/pf2e/spells).")
    parser.add_argument("--feats-source", type=Path, default=DEFAULT_FEATS_SOURCE,
                        help="PF2e feats pack directory (packs/pf2e/feats).")
    parser.add_argument("--skip-spells", action="store_true",
                        help="Don't regenerate the spells domain.")
    parser.add_argument("--skip-feats", action="store_true",
                        help="Don't regenerate the feats domain.")
    parser.add_argument("--check", action="store_true",
                        help="Validate the existing bundle instead of generating.")
    args = parser.parse_args()
    if args.check:
        return check()

    written: list[tuple[str, str]] = []
    spell_counts = None
    feat_counts = None
    if not args.skip_spells:
        w, spell_counts = generate_spells(args.spells_source)
        written += w
    if not args.skip_feats:
        w, feat_counts = generate_feats(args.feats_source)
        written += w
    written += finalize(spell_counts, feat_counts)

    print(f"Generated {len(written)} files into {ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
