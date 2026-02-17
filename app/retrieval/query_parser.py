from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParsedQuery:
    original_question: str
    detected_provider: str | None = None

    def to_filters(self) -> dict[str, str]:
        filters = {}
        if self.detected_provider:
            filters["grid_provider"] = self.detected_provider
        return filters


class QueryParser:
    def __init__(self, known_providers: list[str]):
        self.known_providers = known_providers

    def parse(self, question: str) -> ParsedQuery:
        question_lower = question.lower()
        detected_provider = None

        for provider in self.known_providers:
            if provider.lower() in question_lower:
                detected_provider = provider
                break

        return ParsedQuery(
            original_question=question,
            detected_provider=detected_provider,
        )
