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
        detected_scope: str | None,
        retrieved_chunks: list[dict[str, Any]],
        reranked_chunks: list[dict[str, Any]],
        llm_prompt: str,
        llm_response: str,
        latency_ms: int,
        indexing_settings_key: str,
        answer_settings_key: str,
        version_ids: list[str],
    ) -> uuid.UUID:
        """Store the answer and the versions its top chunks came from, in one transaction."""
        log_data = {
            "question": question,
            "detected_scope": detected_scope,
            "retrieved_chunks": retrieved_chunks,
            "reranked_chunks": reranked_chunks,
            "llm_prompt": llm_prompt,
            "llm_response": llm_response,
            "latency_ms": latency_ms,
            "indexing_settings_key": indexing_settings_key,
            "answer_settings_key": answer_settings_key,
        }
        return uuid.UUID(str(self.db.log_answer(log_data, version_ids)))
