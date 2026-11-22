from __future__ import annotations

from typing import Any

import anthropic
from pydantic import BaseModel

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
    required_source_keys: list[str],
    retrieved_chunks: list[dict[str, Any]],
) -> float:
    """Share of the required sources that at least one retrieved chunk came from."""
    if not required_source_keys:
        return 1.0
    retrieved = {chunk.get("source_key") for chunk in retrieved_chunks}
    return sum(1 for key in required_source_keys if key in retrieved) / len(required_source_keys)


JUDGE_PROMPT = """You are an evaluation judge for a German technical RAG system. Your job is to check whether a generated answer contains specific required facts.

For each required fact, respond with:
- "yes" if the fact is correctly present in the answer (paraphrasing is fine)
- "no" if the fact is missing or contradicted

Return one result per required fact, with the fact text, whether it is present, and a short reason.

Question: {question}

Expected answer: {expected_answer}

Generated answer: {generated_answer}

Required facts to check:
{facts_list}"""


class FactResult(BaseModel):
    fact: str
    present: bool
    reason: str


class JudgeVerdict(BaseModel):
    results: list[FactResult]


async def answer_correctness(
    question: str,
    generated_answer: str,
    expected_answer: str,
    facts: list[str],
    anthropic_api_key: str,
    model: str,
) -> dict[str, Any]:
    """Use LLM-as-judge to check if required facts are present in the answer."""
    if not facts:
        return {"score": 1.0, "details": []}

    facts_list = "\n".join(f"- {fact}" for fact in facts)
    prompt = JUDGE_PROMPT.format(
        question=question,
        expected_answer=expected_answer,
        generated_answer=generated_answer,
        facts_list=facts_list,
    )

    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
    try:
        response = await client.messages.parse(
            model=model,
            max_tokens=16000,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
            output_format=JudgeVerdict,
        )
    finally:
        await client.close()

    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError(f"Judge returned no verdict (stop_reason={response.stop_reason})")

    details = [r.model_dump() for r in response.parsed_output.results]
    present_count = sum(1 for d in details if d.get("present"))
    score = present_count / len(facts)

    return {"score": score, "details": details}


def refusal_accuracy(question_type: str, answer: str) -> bool:
    answer_lower = answer.lower()
    is_refusal = any(phrase in answer_lower for phrase in REFUSAL_PHRASES)

    if question_type == "unanswerable":
        return is_refusal
    else:
        return not is_refusal
