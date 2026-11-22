"""Words from the project this repository started as must not return to schema or code.

The store's vocabulary is source, version, scope, level, rank, flag, answer.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_WORDS = re.compile(r"grid|provider|hierarch|solar|\bpv\b|electrical", re.IGNORECASE)
def _scanned_files() -> list[Path]:
    files = [ROOT / "supabase" / "schema.sql"]
    for folder in ("app", "eval", "scripts"):
        files += sorted((ROOT / folder).rglob("*.py"))
    return files


def test_no_old_project_words():
    hits = [
        f"{path.relative_to(ROOT)}:{n}: {line.strip()}"
        for path in _scanned_files()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if OLD_WORDS.search(line)
    ]
    assert hits == []


OLD_STORE_NAMES = re.compile(
    r"""\b(from|into|update|join|references|on|table)\s+documents\b|table\(["']documents["']\)"""
    r"|document_chunks|query_log|document_id|document_title|\blog_id\b"
    r"|keyword_search|content_tsv|QueryLogger|file_path|stored_path"
)


def test_no_old_store_names():
    """The store's words are versions, chunks, answers, answer_versions."""
    hits = [
        f"{path.relative_to(ROOT)}:{n}: {line.strip()}"
        for path in _scanned_files()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if OLD_STORE_NAMES.search(line)
    ]
    assert hits == []


def test_package_name():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "lighthouse"
    assert "RAG" not in project["description"]
