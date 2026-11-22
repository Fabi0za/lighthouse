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

from app.ingestion import chunker

ROOT = Path(__file__).resolve().parent.parent

RECORDED = {
    "app/ingestion/chunker.py": ("CHUNKER_VERSION", 1, "552ef27c36e7584f83868573a7a2a093e86cedcdce99ea919b5da152a5d79a8d"),
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
    monkeypatch.setitem(RECORDED, "app/ingestion/chunker.py", ("CHUNKER_VERSION", 1, "0" * 64))
    with pytest.raises(AssertionError) as e:
        _check("app/ingestion/chunker.py", "CHUNKER_VERSION", 1)
    assert "raise CHUNKER_VERSION" in str(e.value) and "only re-record the hash" in str(e.value)


def test_guard_fails_when_the_version_was_raised_without_recording(monkeypatch):
    with pytest.raises(AssertionError, match="was recorded for 1"):
        _check("app/ingestion/chunker.py", "CHUNKER_VERSION", 2)
