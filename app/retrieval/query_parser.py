from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParsedQuery:
    original_question: str
    detected_scope: str | None = None

    def to_filters(self) -> dict[str, str]:
        filters = {}
        if self.detected_scope:
            filters["scope"] = self.detected_scope
        return filters


class QueryParser:
    def __init__(self, known_scopes: list[str]):
        self.known_scopes = known_scopes

    def parse(self, question: str) -> ParsedQuery:
        question_lower = question.lower()
        detected_scope = None

        for scope in self.known_scopes:
            if scope.lower() in question_lower:
                detected_scope = scope
                break

        return ParsedQuery(
            original_question=question,
            detected_scope=detected_scope,
        )
