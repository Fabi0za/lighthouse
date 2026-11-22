"""The docs describe the store as built: every schema object, script and rule is named."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
DESIGN = (ROOT / "docs" / "plans" / "2026-11-21-versioned-store-design.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
CONVENTIONS = ROOT / "docs" / "conventions.md"


def _schema_objects() -> set[str]:
    found = re.findall(r"^create (?:table|view|function) ([a-z_]+)", SCHEMA, re.MULTILINE)
    return set(found)


def test_design_names_every_table_view_and_function():
    # named as code: `name` or at the start of a code span, `name (columns…)`
    missing = sorted(o for o in _schema_objects() if not re.search(rf"`{o}[`( ]", DESIGN))
    assert missing == []


def test_readme_names_every_script():
    scripts = [p.relative_to(ROOT).as_posix() for p in (ROOT / "scripts").rglob("*.py")]
    missing = sorted(s for s in scripts if s not in README)
    assert missing == []


def test_conventions_list_the_nine_rules_on_one_page():
    text = CONVENTIONS.read_text(encoding="utf-8")
    for n in range(1, 10):
        assert re.search(rf"^{n}\. ", text, re.MULTILINE), f"rule {n}"
    assert len(text.splitlines()) <= 80  # one page


def test_readme_says_what_it_does_not_do():
    assert "## What it does not do" in README
    for item in ("user accounts", "permissions", "performance tuning", "review screen"):
        assert item in README.lower(), item


def test_no_stale_names_in_readme():
    for stale in ("grid provider", "doc_type", "hierarchy_priority", "match_document_chunks",
                  "Optimization history", "GPT-4o"):
        assert stale not in README, stale
