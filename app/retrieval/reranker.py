from __future__ import annotations

from typing import Any


class Reranker:
    def __init__(
        self,
        top_n: int = 8,
        provider_boost: float = 0.3,
        hierarchy_weight: float = 0.02,
    ):
        self.top_n = top_n
        self.provider_boost = provider_boost
        self.hierarchy_weight = hierarchy_weight

    def rerank(
        self,
        chunks: list[dict[str, Any]],
        detected_provider: str | None,
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []

        scored = []
        for chunk in chunks:
            score = chunk.get("similarity", 0.0)

            # Boost chunks from detected provider
            if detected_provider and chunk.get("grid_provider") == detected_provider:
                score += self.provider_boost

            # Boost by hierarchy priority
            score += chunk.get("hierarchy_priority", 0) * self.hierarchy_weight

            scored.append({**chunk, "rerank_score": score})

        scored.sort(key=lambda c: c["rerank_score"], reverse=True)
        return scored[: self.top_n]
