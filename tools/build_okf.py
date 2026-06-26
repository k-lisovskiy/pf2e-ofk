#!/usr/bin/env python3
"""Generate an Open Knowledge Format (OKF) bundle from PF2e spell JSON.

OKF v0.1 (Google Cloud, 2026-06-12) represents knowledge as a directory tree of
Markdown files with YAML frontmatter, one file per concept. This producer reads
the Foundry VTT PF2e spell documents (cantrips, ranked spells, focus spells and
rituals) and emits a conformant OKF bundle.

Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

Usage:
    python3 tools/build_okf.py --source ../pf2e/packs/pf2e/spells
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
DEFAULT_SOURCE = ROOT.parent / "pf2e" / "packs" / "pf2e" / "spells"
TIMESTAMP = "2026-06-26T00:00:00Z"

# The whole rules bundle lives under rules/ so it can grow beyond spells
# (feats, equipment, bestiary, ...). Spells are nested at rules/spells/.
RULES_DIR = "rules"
SPELLS_OUT = f"{RULES_DIR}/spells"

# Spell categories: (concept type, source subdir under --source, output leaf
# under rules/spells/, resource-URI leaf, trait that duplicates the type and is
# dropped from tags). Ranked spells expand from spells/rank-1 .. spells/rank-10.
CATEGORIES = [
    ("Cantrip", "spells/cantrip", "cantrips", "cantrip", "cantrip"),
    ("Focus Spell", "focus", "focus", "focus", "focus"),
    ("Ritual", "rituals", "rituals", "rituals", None),
]
for _r in range(1, 11):
    CATEGORIES.append(
        ("Spell", f"spells/rank-{_r}", f"rank-{_r}", f"rank-{_r}", "cantrip")
    )


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

def html_to_markdown(text: str) -> str:
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


def first_sentence(markdown: str) -> str:
    """Plain-text one-line summary derived from the body."""
    plain = re.sub(r"[*_`#>\-]", "", markdown)
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
# Bundle assembly
# --------------------------------------------------------------------------- #

def generate(source: Path) -> list[tuple[str, str]]:
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
        m = re.match(r"rank-(\d+)$", out_leaf)
        if m:
            write_index(out_dir, type_name, f"Rank {m.group(1)} Spells",
                        f"All {len(entries)} rank {m.group(1)} spells.", entries, written)
        else:
            label = {"cantrips": "Cantrips", "focus": "Focus Spells",
                     "rituals": "Rituals"}[out_leaf]
            write_index(out_dir, type_name, f"PF2e {label}",
                        f"All {len(entries)} Pathfinder 2e {label.lower()}.", entries, written)

    rank_total = sum(counts[f"rank-{r}"] for r in range(1, 11))
    spells_total = sum(counts.values())

    # rules/spells/index.md — all spell categories.
    spells_lines = [
        "---", "type: Index", 'title: "PF2e Spells"',
        f'description: "All {spells_total} Pathfinder 2e spells: cantrips, ranks 1-10, focus spells, and rituals."',
        f"timestamp: {TIMESTAMP}", "---", "",
        "# Spells", "",
        f"{spells_total} spell concepts.", "",
        f"- [Cantrips](/{SPELLS_OUT}/cantrips/index.md) — {counts['cantrips']} cantrips",
        f"- [Focus Spells](/{SPELLS_OUT}/focus/index.md) — {counts['focus']} focus spells",
        f"- [Rituals](/{SPELLS_OUT}/rituals/index.md) — {counts['rituals']} rituals",
        "",
        f"## Ranked spells (ranks 1-10) — {rank_total} spells",
        "",
    ]
    for r in range(1, 11):
        spells_lines.append(f"- [Rank {r}](/{SPELLS_OUT}/rank-{r}/index.md) — {counts[f'rank-{r}']} spells")
    spells_index = "\n".join(spells_lines) + "\n"
    (ROOT / SPELLS_OUT / "index.md").write_text(spells_index, encoding="utf-8")
    written.append((f"{SPELLS_OUT}/index.md", spells_index))

    # rules/index.md — the rules bundle index (room for future categories).
    rules_index = (
        "---\n"
        "type: Index\n"
        'title: "PF2e Rules"\n'
        'description: "Pathfinder 2e rules content, organized by category."\n'
        f"timestamp: {TIMESTAMP}\n"
        "---\n\n"
        "# PF2e Rules\n\n"
        "Pathfinder Second Edition rules content. New categories (feats, "
        "equipment, bestiary, conditions, ...) can be added alongside spells.\n\n"
        "## Categories\n\n"
        f"- [Spells](/{SPELLS_OUT}/index.md) — {spells_total} spell concepts\n"
    )
    (ROOT / RULES_DIR / "index.md").write_text(rules_index, encoding="utf-8")
    written.append((f"{RULES_DIR}/index.md", rules_index))

    # root index.md — bundle entry point.
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
        f"- [Rules](/{RULES_DIR}/index.md) — [Spells](/{SPELLS_OUT}/index.md) "
        f"({spells_total} concepts); more categories to come\n"
    )
    (ROOT / "index.md").write_text(root_index, encoding="utf-8")
    written.append(("index.md", root_index))

    # log.md
    log = (
        "---\n"
        "type: Log\n"
        'title: "Change Log"\n'
        f"timestamp: {TIMESTAMP}\n"
        "---\n\n"
        "# Change Log\n\n"
        f"## {TIMESTAMP[:10]}\n\n"
        f"- Reorganized the bundle under `rules/`; spells now live at "
        f"`rules/spells/` (cantrips, ranks 1-10, focus, rituals) to make room "
        "for future rules categories.\n"
        f"- OKF v0.1 bundle: {spells_total} PF2e spell concepts "
        f"({counts['cantrips']} cantrips, {rank_total} ranked spells, "
        f"{counts['focus']} focus spells, {counts['rituals']} rituals) "
        "from the pf2e system JSON.\n"
    )
    (ROOT / "log.md").write_text(log, encoding="utf-8")
    written.append(("log.md", log))

    print(f"  cantrips: {counts['cantrips']}, ranked: {rank_total}, "
          f"focus: {counts['focus']}, rituals: {counts['rituals']} (total {spells_total})")
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
        for leftover in ("@UUID[", "@Damage[", "@Check[", "@Template[", "<p>", "</p>"):
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
    print(f"Checked {len(md_files)} markdown files, {concepts} spell concepts.")
    print("OK" if errors == 0 else f"{errors} problem(s) found.")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                        help="PF2e spells pack directory (packs/pf2e/spells).")
    parser.add_argument("--check", action="store_true",
                        help="Validate the existing bundle instead of generating.")
    args = parser.parse_args()
    if args.check:
        return check()
    written = generate(args.source)
    print(f"Generated {len(written)} files into {ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
