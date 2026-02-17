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
