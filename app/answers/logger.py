from __future__ import annotations

import uuid
from typing import Any

from app.models.database import DatabaseClient


class AnswerLogger:
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
        version_ids: list[str],
    ) -> uuid.UUID:
        """Store the answer and the versions its top chunks came from, in one transaction."""
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
        return uuid.UUID(str(self.db.log_answer(log_data, version_ids)))
