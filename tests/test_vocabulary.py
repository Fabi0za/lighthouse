"""Words from the project this repository started as must not return to schema or code.

The store's vocabulary is source, version, scope, level, rank, flag, answer.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_WORDS = re.compile(r"grid|provider|hierarch|solar|\bpv\b|electrical", re.IGNORECASE)
NOT_YET = {
    "app/generation/prompts.py": "prompt wording changes in Slice F",
    "scripts/seed_eval_questions.py": "replaced in Slice E",
}


def _scanned_files() -> list[Path]:
    files = [ROOT / "supabase" / "schema.sql"]
    for folder in ("app", "eval", "scripts"):
        files += sorted((ROOT / folder).rglob("*.py"))
    return [f for f in files if f.relative_to(ROOT).as_posix() not in NOT_YET]


def test_no_old_project_words():
    hits = [
        f"{path.relative_to(ROOT)}:{n}: {line.strip()}"
        for path in _scanned_files()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if OLD_WORDS.search(line)
    ]
    assert hits == []


def test_package_name():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "lighthouse"
    assert "RAG" not in project["description"]
