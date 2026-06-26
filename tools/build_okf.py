#!/usr/bin/env python3
"""Generate an Open Knowledge Format (OKF) bundle from PF2e cantrip JSON.

OKF v0.1 (Google Cloud, 2026-06-12) represents knowledge as a directory tree of
Markdown files with YAML frontmatter, one file per concept. This producer reads
the Foundry VTT PF2e cantrip documents and emits a conformant OKF bundle.

Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

Usage:
    python3 tools/build_okf.py --source ../pf2e/packs/pf2e/spells/spells/cantrip
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
CANTRIPS_DIR = ROOT / "cantrips"
DEFAULT_SOURCE = ROOT.parent / "pf2e" / "packs" / "pf2e" / "spells" / "spells" / "cantrip"
TIMESTAMP = "2026-06-26T00:00:00Z"


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


def build_concept(slug: str, data: dict) -> str:
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
    publication = (sys_.get("publication") or {}).get("title", "") or ""

    body_md = html_to_markdown(sys_.get("description", {}).get("value", ""))
    description = first_sentence(body_md) or f"The {name} cantrip."

    tags = [rarity] + list(traditions) + list(trait_values)

    fm = ["---"]
    fm.append(f"type: Cantrip")
    fm.append(f"title: {yaml_str(name)}")
    fm.append(f"description: {yaml_str(description)}")
    fm.append(f"resource: {yaml_str(f'pf2e://spells/cantrip/{slug}')}")
    fm.append(f"tags: {yaml_list(tags)}")
    fm.append(f"timestamp: {TIMESTAMP}")
    fm.append(f"rank: {rank}")
    fm.append(f"actions: {yaml_str(actions)}")
    fm.append(f"traditions: {yaml_list(list(traditions))}")
    fm.append(f"range: {yaml_str(rng)}")
    fm.append(f"targets: {yaml_str(targets)}")
    fm.append(f"area: {yaml_str(area)}")
    fm.append(f"defense: {yaml_str(defense)}")
    fm.append(f"duration: {yaml_str(duration)}")
    fm.append(f"publication: {yaml_str(publication)}")
    fm.append("---")

    overview = ["# Overview", ""]
    overview.append(f"- **Rank**: {rank} (cantrip)")
    if actions:
        overview.append(f"- **Cast**: {actions}")
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
        f"[2] Source: `packs/pf2e/spells/spells/cantrip/{slug}.json` (pf2e system data)",
    ]

    doc = "\n".join(fm) + "\n\n"
    doc += "\n".join(overview) + "\n\n"
    doc += "## Description\n\n" + body_md + "\n\n"
    doc += "\n".join(citations) + "\n"
    return doc


# --------------------------------------------------------------------------- #
# Bundle assembly
# --------------------------------------------------------------------------- #

def generate(source: Path) -> list[tuple[str, str]]:
    files = sorted(source.glob("*.json"))
    if not files:
        sys.exit(f"No JSON spell files found in {source}")
    concepts = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        slug = path.stem
        concepts.append((slug, data["name"], build_concept(slug, data)))

    CANTRIPS_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for slug, _name, doc in concepts:
        out = CANTRIPS_DIR / f"{slug}.md"
        out.write_text(doc, encoding="utf-8")
        written.append((str(out.relative_to(ROOT)), doc))

    # cantrips/index.md
    lines = [
        "---",
        "type: Index",
        'title: "PF2e Cantrips"',
        f'description: "Index of all {len(concepts)} Pathfinder 2e cantrips in this bundle."',
        f"timestamp: {TIMESTAMP}",
        "---",
        "",
        "# Cantrips",
        "",
        f"{len(concepts)} cantrips, sorted alphabetically.",
        "",
    ]
    for slug, name, _doc in sorted(concepts, key=lambda c: c[1].lower()):
        lines.append(f"- [{name}](/cantrips/{slug}.md)")
    cantrip_index = "\n".join(lines) + "\n"
    (CANTRIPS_DIR / "index.md").write_text(cantrip_index, encoding="utf-8")
    written.append(("cantrips/index.md", cantrip_index))

    # root index.md
    root_index = (
        "---\n"
        "type: Index\n"
        'title: "PF2e Spell Knowledge Bundle"\n'
        'description: "Open Knowledge Format bundle of Pathfinder 2e spells."\n'
        f"timestamp: {TIMESTAMP}\n"
        "---\n\n"
        "# PF2e Spell Knowledge Bundle\n\n"
        "An [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)"
        " (OKF v0.1) bundle of Pathfinder Second Edition spell data.\n\n"
        "## Contents\n\n"
        f"- [Cantrips](/cantrips/index.md) — {len(concepts)} cantrips\n"
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
        f"- Initial OKF v0.1 bundle: generated {len(concepts)} PF2e cantrip concepts"
        " from the pf2e system JSON.\n"
    )
    (ROOT / "log.md").write_text(log, encoding="utf-8")
    written.append(("log.md", log))

    return written


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def check() -> int:
    # README.md is project documentation, not an OKF concept document.
    md_files = [f for f in ROOT.glob("*.md") if f.name != "README.md"]
    md_files += list(CANTRIPS_DIR.glob("*.md"))
    if not md_files:
        print("No bundle files found — run the generator first.")
        return 1
    errors = 0
    for f in sorted(md_files):
        text = f.read_text(encoding="utf-8")
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
    for f in sorted(md_files):
        for link in re.findall(r"\]\((/[^)]+\.md)\)", f.read_text(encoding="utf-8")):
            target = ROOT / link.lstrip("/")
            if not target.exists():
                print(f"  BROKEN link {link} in {f.relative_to(ROOT)}")
                errors += 1
    concept_count = len(list(CANTRIPS_DIR.glob("*.md"))) - 1  # minus index.md
    print(f"Checked {len(md_files)} markdown files, {concept_count} cantrip concepts.")
    print("OK" if errors == 0 else f"{errors} problem(s) found.")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                        help="Directory of PF2e cantrip JSON files.")
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
