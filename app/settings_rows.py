"""Rows for the settings tables, made from the app's configuration and code constants.

A settings key is built from its values, so the same configuration always gives the
same key and a person can read the values from it.
"""
from __future__ import annotations

import re
from typing import Any

from app.config import Settings
from app.ingestion.chunker import CHUNKER_VERSION

_NOT_KEY = re.compile(r"[^a-z0-9.]+")


def settings_key(*parts: Any) -> str:
    """Lowercase parts joined by hyphens; anything but letters, digits and dots becomes a hyphen."""
    return "-".join(p for p in (_NOT_KEY.sub("-", str(part).lower()).strip("-") for part in parts) if p)


def indexing_settings_row(settings: Settings) -> dict[str, Any]:
    values = {
        "embedding_model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "chunker_version": CHUNKER_VERSION,
    }
    key = settings_key(values["embedding_model"], values["dimensions"], values["chunk_size"],
                       values["chunk_overlap"], f"c{CHUNKER_VERSION}")
    return {"key": key, **values}
