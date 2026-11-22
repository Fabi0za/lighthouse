"""Fingerprints that identify a version by its content, never by name or date.

text_sha256 decides whether a file is a new version. Starting rule (FINGERPRINT_RULE 1,
unproven until tested on the EKZ archive, see the design document): the parser's blocks
in order, headings and short blocks included; page headers, footers, page numbers and
figures left out (figures are image descriptions written by the parser, not stable
between parses); each block in Unicode NFC with whitespace runs collapsed to one space;
blocks joined with a newline.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any

# Raise when a change to this file changes which fingerprint a text gets: a new value
# means a new indexing settings key and a full reload. tests/test_versioned_constants.py
# guards it.
FINGERPRINT_RULE = 1

EXCLUDED_BLOCKS = {"Header", "Footer", "Page Number", "Figure"}
_WHITESPACE = re.compile(r"\s+")


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def _normalise(text: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def fingerprinted_blocks(raw_output: dict[str, Any]) -> list[str]:
    """The normalised block texts the fingerprint is made of, in document order."""
    result = raw_output.get("result") or {}
    texts = []
    for chunk in result.get("chunks") or []:
        for block in chunk.get("blocks") or []:
            if block.get("type") in EXCLUDED_BLOCKS:
                continue
            text = _normalise(block.get("content") or "")
            if text:
                texts.append(text)
    return texts


def text_sha256(raw_output: dict[str, Any]) -> str:
    return hashlib.sha256("\n".join(fingerprinted_blocks(raw_output)).encode("utf-8")).hexdigest()
