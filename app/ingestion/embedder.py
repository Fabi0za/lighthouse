from __future__ import annotations

import asyncio

import cohere
from cohere.errors import TooManyRequestsError

from app.generation.prompts import display_title

# Cohere's v2 embed endpoint accepts at most 96 texts per request.
MAX_BATCH = 96


def embedding_input(version_title: str, version_label: str | None, section_title: str, content: str) -> str:
    """The text embedded for a chunk: a header naming the version and section, then the chunk text."""
    title = display_title(version_title, version_label)
    header = f"[{title} — {section_title}]" if section_title else f"[{title}]"
    return f"{header}\n{content}"


class Embedder:
    """Cohere embeddings. Documents and queries use different input_type values.

    A rate-limit error on a batch is waited out (rate_limit_wait_seconds, a little over
    Cohere's one-minute window) and that batch retried, up to rate_limit_retries
    times; any other error is raised at once.
    """

    def __init__(self, api_key: str, model: str = "embed-v5.0-pro", dimensions: int = 1536,
                 rate_limit_wait_seconds: int = 61, rate_limit_retries: int = 5, sleep=asyncio.sleep):
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.rate_limit_wait_seconds = rate_limit_wait_seconds
        self.rate_limit_retries = rate_limit_retries
        self._sleep = sleep
        self.client = cohere.AsyncClientV2(api_key=api_key)

    async def _embed_batch(self, batch: list[str], input_type: str) -> list[list[float]]:
        for attempt in range(self.rate_limit_retries + 1):
            try:
                response = await self.client.embed(
                    model=self.model,
                    texts=batch,
                    input_type=input_type,
                    output_dimension=self.dimensions,
                    embedding_types=["float"],
                )
                return response.embeddings.float_
            except TooManyRequestsError:
                if attempt == self.rate_limit_retries:
                    raise
                print(f"embedding rate limit: waiting {self.rate_limit_wait_seconds} s "
                      f"(retry {attempt + 1} of {self.rate_limit_retries})", flush=True)
                await self._sleep(self.rate_limit_wait_seconds)
        raise AssertionError("unreachable")

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH):
            embeddings.extend(await self._embed_batch(texts[start : start + MAX_BATCH], input_type))
        return embeddings

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed document chunks for indexing."""
        return await self._embed(texts, "search_document")

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
        results = await self._embed([text], "search_query")
        return results[0]

    async def close(self):
        pass
