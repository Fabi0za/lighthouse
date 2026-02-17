from __future__ import annotations

from typing import Any

REFUSAL_PHRASES = [
    "i don't have enough information",
    "i do not have enough information",
    "insufficient information",
    "cannot answer",
    "unable to answer",
    "no relevant context",
]


def retrieval_recall(
    required_doc_ids: list[str],
    retrieved_chunks: list[dict[str, Any]],
) -> float:
    if not required_doc_ids:
        return 1.0
    retrieved_ids = {chunk.get("document_id") for chunk in retrieved_chunks}
    found = sum(1 for doc_id in required_doc_ids if doc_id in retrieved_ids)
    return found / len(required_doc_ids)


def refusal_accuracy(question_type: str, answer: str) -> bool:
    answer_lower = answer.lower()
    is_refusal = any(phrase in answer_lower for phrase in REFUSAL_PHRASES)

    if question_type == "unanswerable":
        return is_refusal
    else:
        return not is_refusal
