"""Fingerprints that identify a version by its content, never by name or date.

text_sha256 decides whether a file is a new version. Its normalisation rule is
unproven (see docs/plans/2026-11-21-versioned-store-design.md, "Unproven, to be tested"):
section texts in order, Unicode NFC, whitespace runs collapsed to one space,
sections joined with a newline. Nothing else is removed.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

_WHITESPACE = re.compile(r"\s+")


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def _normalise(text: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def text_sha256(sections: list[dict]) -> str:
    joined = "\n".join(_normalise(s.get("content", "")) for s in sections)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
