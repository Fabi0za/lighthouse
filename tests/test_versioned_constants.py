"""Version constants must be raised when the behaviour they name changes.

Each guarded file's sha256 is recorded here together with the version it was recorded
for. When a file changes, decide: if its behaviour changed, raise the constant (for the
chunker that means a new indexing settings key and a full reload); if it did not
(comments, formatting), only re-record the hash.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.generation import prompts
from app.ingestion import chunker, fingerprint

ROOT = Path(__file__).resolve().parent.parent

RECORDED = {
    "app/generation/prompts.py": ("PROMPT_VERSION", 2, "edc6fdf619645034cddf45b19027a5b4e41a34ee12a94aa841b86f45c6263222"),
    "app/ingestion/fingerprint.py": ("FINGERPRINT_RULE", 1, "340022d8019f445ecd4fd9413e424804dd875a96afc3fb54246ae75aeb7b3970"),
    "app/ingestion/parser.py": ("CHUNKER_VERSION", 2, "39c3c68eae055930fa1346d131f154aa14f07da54aeafea49a8b2425549ebcbd"),  # sections become chunks
    "app/ingestion/chunker.py": ("CHUNKER_VERSION", 2, "baa0469266ad40e786a120adb99fd1f9f05f66cedb0fae1e0a6e40df21f52f33"),
}


def _sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def _check(path: str, constant: str, current_version: int) -> None:
    name, version, sha = RECORDED[path]
    assert current_version == version, (
        f"{constant} is {current_version} but the hash of {path} was recorded for {version}: "
        f"record ({constant!r}, {current_version}, {_sha(path)!r}) in RECORDED")
    assert _sha(path) == sha, (
        f"{path} changed since its hash was recorded. If its behaviour changed, raise {constant} "
        f"and record the new hash with it; if not (comments, formatting), only re-record the hash: "
        f"{_sha(path)!r}")


def test_chunker_version_matches_its_source():
    _check("app/ingestion/chunker.py", "CHUNKER_VERSION", chunker.CHUNKER_VERSION)


def test_guard_names_both_choices_when_the_file_changed(monkeypatch):
    current = chunker.CHUNKER_VERSION
    monkeypatch.setitem(RECORDED, "app/ingestion/chunker.py", ("CHUNKER_VERSION", current, "0" * 64))
    with pytest.raises(AssertionError) as e:
        _check("app/ingestion/chunker.py", "CHUNKER_VERSION", current)
    assert "raise CHUNKER_VERSION" in str(e.value) and "only re-record the hash" in str(e.value)


def test_guard_fails_when_the_version_was_raised_without_recording(monkeypatch):
    current = chunker.CHUNKER_VERSION
    with pytest.raises(AssertionError, match=f"was recorded for {current}"):
        _check("app/ingestion/chunker.py", "CHUNKER_VERSION", current + 1)


def test_prompt_version_matches_its_source():
    _check("app/generation/prompts.py", "PROMPT_VERSION", prompts.PROMPT_VERSION)


def test_fingerprint_rule_matches_its_source():
    _check("app/ingestion/fingerprint.py", "FINGERPRINT_RULE", fingerprint.FINGERPRINT_RULE)



def test_parser_sections_are_guarded_by_the_chunker_version():
    _check("app/ingestion/parser.py", "CHUNKER_VERSION", chunker.CHUNKER_VERSION)
