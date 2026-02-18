from __future__ import annotations

from typing import Any


class Reranker:
    def __init__(
        self,
        top_n: int = 8,
        provider_boost: float = 0.3,
        hierarchy_weight: float = 0.02,
        diversity_penalty: float = 0.3,
    ):
        self.top_n = top_n
        self.provider_boost = provider_boost
        self.hierarchy_weight = hierarchy_weight
        self.diversity_penalty = diversity_penalty

    def rerank(
        self,
        chunks: list[dict[str, Any]],
        detected_provider: str | None,
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []

        # Score all chunks
        scored = []
        for chunk in chunks:
            score = chunk.get("similarity", 0.0)

            if detected_provider and chunk.get("grid_provider") == detected_provider:
                score += self.provider_boost

            score += chunk.get("hierarchy_priority", 0) * self.hierarchy_weight

            scored.append({**chunk, "rerank_score": score})

        scored.sort(key=lambda c: c["rerank_score"], reverse=True)

        if self.diversity_penalty == 0.0:
            return scored[: self.top_n]

        # MMR-style greedy selection with diversity penalty
        return self._select_diverse(scored)

    def _select_diverse(self, scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        remaining = list(scored)

        while len(selected) < self.top_n and remaining:
            if not selected:
                # First pick: always the highest-scoring chunk
                selected.append(remaining.pop(0))
                continue

            best_idx = 0
            best_adjusted = -1.0

            for i, candidate in enumerate(remaining):
                penalty = self._redundancy_penalty(candidate, selected)
                adjusted = candidate["rerank_score"] - penalty
                if adjusted > best_adjusted:
                    best_adjusted = adjusted
                    best_idx = i

            selected.append(remaining.pop(best_idx))

        return selected

    def _redundancy_penalty(
        self, candidate: dict[str, Any], selected: list[dict[str, Any]]
    ) -> float:
        max_overlap = 0.0

        for s in selected:
            overlap = 0.0

            # Same section title = high redundancy
            if candidate.get("section_title") and candidate["section_title"] == s.get(
                "section_title"
            ):
                overlap = max(overlap, 1.0)
            # Same document but different section = moderate redundancy
            elif candidate.get("document_id") and candidate["document_id"] == s.get(
                "document_id"
            ):
                overlap = max(overlap, 0.3)

            max_overlap = max(max_overlap, overlap)

        return self.diversity_penalty * max_overlap
