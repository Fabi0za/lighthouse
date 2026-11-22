from __future__ import annotations

import time
from typing import Any

import cohere
from cohere.errors import TooManyRequestsError


class CohereReranker:
    """Neural reranker using Cohere's rerank API."""

    def __init__(self, api_key: str, top_n: int, model: str):
        self.client = cohere.Client(api_key=api_key)
        self.top_n = top_n
        self.model = model

    def rerank(self, chunks: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        if not chunks:
            return []

        docs = [c["content"] for c in chunks]
        response = self._rerank_with_retry(query, docs)

        reranked = []
        for result in response.results:
            chunk = {**chunks[result.index], "rerank_score": result.relevance_score}
            reranked.append(chunk)

        return reranked

    def _rerank_with_retry(self, query: str, docs: list[str], max_retries: int = 3):
        for attempt in range(max_retries + 1):
            try:
                return self.client.rerank(
                    query=query,
                    documents=docs,
                    top_n=self.top_n,
                    model=self.model,
                )
            except TooManyRequestsError:
                if attempt == max_retries:
                    raise
                wait = 7 * (attempt + 1)
                time.sleep(wait)

