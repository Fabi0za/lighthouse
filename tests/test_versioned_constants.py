"""Version constants must be raised when the behaviour they name changes.

Each guarded file's sha256 is recorded here for each constant whose behaviour it shapes,
together with the version it was recorded for. When a file changes, decide for each of its
constants: if the behaviour changed, raise the constant (for CHUNKER_VERSION and
FINGERPRINT_RULE that means a new indexing settings key and a full reload); if it did not
(comments, formatting, moving code), only re-record the hash.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.generation import prompts
from app.ingestion import chunker, fingerprint

ROOT = Path(__file__).resolve().parent.parent
CONSTANTS = {
    "CHUNKER_VERSION": lambda: chunker.CHUNKER_VERSION,
    "FINGERPRINT_RULE": lambda: fingerprint.FINGERPRINT_RULE,
    "PROMPT_VERSION": lambda: prompts.PROMPT_VERSION,
}

# (file, constant): (version the hash was recorded for, sha256 of the file)
RECORDED = {
    ("app/retrieval/reranker.py", "PROMPT_VERSION"): (4, "c322c71430db3c8d2d7f2de5303d0bb09d57ef70266f4ca9398bcb09f9485c8d"),
    ("app/generation/prompts.py", "PROMPT_VERSION"): (4, "cfff915f860d13e376141ab6babe785cca1cd264f8e598f5a6a7f80f950fecd7"),
    ("app/ingestion/fingerprint.py", "FINGERPRINT_RULE"): (1, "340022d8019f445ecd4fd9413e424804dd875a96afc3fb54246ae75aeb7b3970"),
    ("app/ingestion/parser.py", "CHUNKER_VERSION"): (2, "39c3c68eae055930fa1346d131f154aa14f07da54aeafea49a8b2425549ebcbd"),
    ("app/ingestion/chunker.py", "CHUNKER_VERSION"): (2, "baa0469266ad40e786a120adb99fd1f9f05f66cedb0fae1e0a6e40df21f52f33"),
    ("app/ingestion/embedder.py", "CHUNKER_VERSION"): (2, "c53119ea45928dfe4c804cb31d955f6c9c3b9c4d30367f5e5c21b4ea21be7e8c"),  # the embedding input
    ("app/ingestion/embedder.py", "PROMPT_VERSION"): (4, "c53119ea45928dfe4c804cb31d955f6c9c3b9c4d30367f5e5c21b4ea21be7e8c"),   # titles shown to the model, rerank input
}


def _sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def _check(path: str, constant: str, current_version: int) -> None:
    version, sha = RECORDED[(path, constant)]
    assert current_version == version, (
        f"{constant} is {current_version} but the hash of {path} was recorded for {version}: "
        f"record ({current_version}, {_sha(path)!r}) for ({path!r}, {constant!r}) in RECORDED")
    assert _sha(path) == sha, (
        f"{path} changed since its hash was recorded for {constant}. If its behaviour changed, raise "
        f"{constant} and record the new hash with it; if not (comments, formatting, moving code), only "
        f"re-record the hash: {_sha(path)!r}")


@pytest.mark.parametrize("path, constant", sorted(RECORDED))
def test_guarded_file_matches_its_recorded_hash(path, constant):
    _check(path, constant, CONSTANTS[constant]())


def test_embedder_is_guarded_by_both_versions():
    assert {c for p, c in RECORDED if p == "app/ingestion/embedder.py"} == {"CHUNKER_VERSION", "PROMPT_VERSION"}


def test_display_title_lives_in_the_guarded_embedder():
    from app.generation.prompts import display_title
    assert display_title.__module__ == "app.ingestion.embedder"


def test_guard_names_both_choices_when_the_file_changed(monkeypatch):
    current = chunker.CHUNKER_VERSION
    monkeypatch.setitem(RECORDED, ("app/ingestion/chunker.py", "CHUNKER_VERSION"), (current, "0" * 64))
    with pytest.raises(AssertionError) as e:
        _check("app/ingestion/chunker.py", "CHUNKER_VERSION", current)
    assert "raise CHUNKER_VERSION" in str(e.value) and "only re-record the hash" in str(e.value)


def test_guard_fails_when_the_version_was_raised_without_recording():
    current = chunker.CHUNKER_VERSION
    with pytest.raises(AssertionError, match=f"was recorded for {current}"):
        _check("app/ingestion/chunker.py", "CHUNKER_VERSION", current + 1)
