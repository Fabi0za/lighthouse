from __future__ import annotations

from typing import Any

from app.ingestion.embedder import Embedder
from app.models.database import DatabaseClient


class VectorSearch:
    def __init__(self, db: DatabaseClient, embedder: Embedder, top_k: int = 20):
        self.db = db
        self.embedder = embedder
        self.top_k = top_k

    async def search(self, query: str) -> list[dict[str, Any]]:
        embedding = await self.embedder.embed_query(query)
        return self.db.vector_search(embedding, self.top_k)


class HybridSearch:
    """Combines vector similarity search with BM25 keyword search via RRF."""

    def __init__(
        self,
        db: DatabaseClient,
        embedder: Embedder,
        top_k: int = 20,
        rrf_k: int = 60,
    ):
        self.db = db
        self.embedder = embedder
        self.top_k = top_k
        self.rrf_k = rrf_k

    async def search(self, query: str) -> list[dict[str, Any]]:
        # Run vector search
        embedding = await self.embedder.embed_query(query)
        vector_results = self.db.vector_search(embedding, self.top_k)

        # Run keyword search
        keyword_results = self.db.keyword_search(query, self.top_k)

        return self._rrf_merge(vector_results, keyword_results)

    def _rrf_merge(
        self,
        vector_results: list[dict[str, Any]],
        keyword_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion: score = 1/(k+rank_v) + 1/(k+rank_kw)."""
        k = self.rrf_k

        # Build lookup by chunk id
        chunks_by_id: dict[str, dict[str, Any]] = {}
        rrf_scores: dict[str, float] = {}

        # Score from vector results (rank 1-based)
        for rank, chunk in enumerate(vector_results, start=1):
            chunk_id = chunk["id"]
            chunks_by_id[chunk_id] = chunk
            rrf_scores[chunk_id] = 1.0 / (k + rank)

        # Add score from keyword results
        for rank, chunk in enumerate(keyword_results, start=1):
            chunk_id = chunk["id"]
            if chunk_id not in chunks_by_id:
                chunks_by_id[chunk_id] = chunk
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

        # Sort by RRF score descending, return top_k
        sorted_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)
        merged = []
        for chunk_id in sorted_ids[: self.top_k]:
            chunk = chunks_by_id[chunk_id]
            chunk["rrf_score"] = rrf_scores[chunk_id]
            merged.append(chunk)

        return merged
