from __future__ import annotations

import uuid
from typing import Any

from app.models.database import DatabaseClient


class QueryLogger:
    def __init__(self, db: DatabaseClient):
        self.db = db

    def log(
        self,
        question: str,
        detected_filters: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
        reranked_chunks: list[dict[str, Any]],
        llm_prompt: str,
        llm_response: str,
        formatted_answer: dict[str, Any],
        model_used: str,
        latency_ms: int,
    ) -> uuid.UUID:
        log_data = {
            "question": question,
            "detected_filters": detected_filters,
            "retrieved_chunks": retrieved_chunks,
            "reranked_chunks": reranked_chunks,
            "llm_prompt": llm_prompt,
            "llm_response": llm_response,
            "formatted_answer": formatted_answer,
            "model_used": model_used,
            "latency_ms": latency_ms,
        }
        result = self.db.insert_query_log(log_data)
        return uuid.UUID(result["id"])
