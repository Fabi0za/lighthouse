from __future__ import annotations

import time
from typing import Any

from app.generation.formatter import ResponseFormatter
from app.generation.llm import LLMClient
from app.generation.prompts import build_system_prompt, build_user_prompt
from app.answers.logger import AnswerLogger
from app.retrieval.query_parser import QueryParser
from app.retrieval.reranker import CohereReranker
from app.retrieval.search import VectorSearch


class QueryPipeline:
    def __init__(
        self,
        query_parser: QueryParser,
        vector_search: VectorSearch,
        reranker: CohereReranker,
        llm: LLMClient,
        formatter: ResponseFormatter,
        logger: AnswerLogger,
    ):
        self.query_parser = query_parser
        self.vector_search = vector_search
        self.reranker = reranker
        self.llm = llm
        self.formatter = formatter
        self.logger = logger

    async def run(self, question: str) -> dict[str, Any]:
        start = time.monotonic()

        # 1. Parse query for metadata hints
        parsed = self.query_parser.parse(question)

        # 2. Vector search
        retrieved_chunks = await self.vector_search.search(question)

        # 3. Re-rank
        reranked_chunks = self.reranker.rerank(retrieved_chunks, query=question)

        # 4. Generate answer
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(question, reranked_chunks)
        llm_response = await self.llm.generate(system_prompt, user_prompt)

        # 5. Format response
        formatted = self.formatter.format(llm_response, reranked_chunks)

        # 6. Log full trace
        latency_ms = int((time.monotonic() - start) * 1000)
        answer_id = self.logger.log(
            question=question,
            detected_scope=parsed.detected_scope,
            retrieved_chunks=retrieved_chunks,
            reranked_chunks=reranked_chunks,
            llm_prompt=user_prompt,
            llm_response=llm_response,
            formatted_answer=formatted,
            model_used=self.llm.model,
            latency_ms=latency_ms,
            version_ids=list(dict.fromkeys(c["version_id"] for c in reranked_chunks)),
        )

        return {
            "answer": formatted["answer"],
            "sources": formatted["sources"],
            "confidence": formatted["confidence"],
            "answer_id": str(answer_id),
            "retrieved_chunks": retrieved_chunks,
            "reranked_chunks": reranked_chunks,
        }
