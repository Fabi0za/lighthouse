from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedQuery:
    original_question: str
    detected_scope: str | None = None


def _scope_pattern(key: str) -> re.Pattern[str]:
    """A scope key as a whole word; the words of a hyphenated key may be joined by spaces or hyphens."""
    words = [re.escape(w) for w in key.split("-")]
    return re.compile(r"\b" + r"[\s-]+".join(words) + r"\b", re.IGNORECASE)


class QueryParser:
    def __init__(self, known_scopes: list[str]):
        self.known_scopes = known_scopes
        self._patterns = [(key, _scope_pattern(key)) for key in known_scopes]

    def parse(self, question: str) -> ParsedQuery:
        detected = next((key for key, pattern in self._patterns if pattern.search(question)), None)
        return ParsedQuery(original_question=question, detected_scope=detected)
