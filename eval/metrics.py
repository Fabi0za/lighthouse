from __future__ import annotations

import json
from typing import Any

import httpx

REFUSAL_PHRASES = [
    "i don't have enough information",
    "i do not have enough information",
    "insufficient information",
    "cannot answer",
    "unable to answer",
    "no relevant context",
    "ich habe nicht genügend informationen",
    "nicht genug informationen",
    "kann nicht beantwortet werden",
    "keine relevanten informationen",
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


JUDGE_PROMPT = """You are an evaluation judge for a German technical RAG system. Your job is to check whether a generated answer contains specific required facts.

For each required fact, respond with:
- "yes" if the fact is correctly present in the answer (paraphrasing is fine)
- "no" if the fact is missing or contradicted

Respond ONLY with a JSON object: {{"results": [{{"fact": "...", "present": true/false, "reason": "..."}}]}}

Question: {question}

Expected answer: {expected_answer}

Generated answer: {generated_answer}

Required facts to check:
{facts_list}"""


async def answer_correctness(
    question: str,
    generated_answer: str,
    expected_answer: str,
    required_facts: list[str],
    openai_api_key: str,
    model: str = "gpt-4o-mini",
) -> dict[str, Any]:
    """Use LLM-as-judge to check if required facts are present in the answer."""
    if not required_facts:
        return {"score": 1.0, "details": []}

    facts_list = "\n".join(f"- {fact}" for fact in required_facts)
    prompt = JUDGE_PROMPT.format(
        question=question,
        expected_answer=expected_answer,
        generated_answer=generated_answer,
        facts_list=facts_list,
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    details = parsed.get("results", [])

    present_count = sum(1 for d in details if d.get("present"))
    score = present_count / len(required_facts)

    return {"score": score, "details": details}


def refusal_accuracy(question_type: str, answer: str) -> bool:
    answer_lower = answer.lower()
    is_refusal = any(phrase in answer_lower for phrase in REFUSAL_PHRASES)

    if question_type == "unanswerable":
        return is_refusal
    else:
        return not is_refusal
