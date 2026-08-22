"""Test different LLM models on selected eval questions.

Usage:
    python scripts/test_models.py [question_id ...]

With no arguments, runs every question in the `eval_questions` table. Pass one
or more question IDs to compare models on a specific subset — useful for
drilling into the questions a previous eval run got wrong.

Runs each question through the same retrieval pipeline and only swaps the LLM
used for answer generation, so differences are attributable to the model.
"""
from __future__ import annotations

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.generation.llm import LLMClient
from app.generation.prompts import build_system_prompt, build_user_prompt
from app.ingestion.embedder import Embedder
from app.models.database import DatabaseClient
from app.retrieval.reranker import Reranker
from app.retrieval.search import VectorSearch
from app.retrieval.query_parser import QueryParser
from eval.metrics import answer_correctness

MODELS = [
    ("openai", "gpt-4o"),
    ("anthropic", "claude-sonnet-4-6"),
]


async def main():
    selected_ids = set(sys.argv[1:])

    settings = get_settings()
    db = DatabaseClient()
    embedder = Embedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    known_providers = db.get_known_providers()
    query_parser = QueryParser(known_providers=known_providers)
    vector_search = VectorSearch(db=db, embedder=embedder, top_k=settings.retrieval_top_k)
    reranker = Reranker(top_n=settings.rerank_top_n)
    system_prompt = build_system_prompt()

    # Load questions — all of them, or just the requested subset
    all_questions = db.get_eval_questions()
    questions = [q for q in all_questions if q["id"] in selected_ids] if selected_ids else all_questions
    print(f"Testing {len(questions)} questions across {len(MODELS)} models\n")

    # Build LLM clients
    clients: list[tuple[str, LLMClient]] = []
    for provider, model in MODELS:
        api_key = settings.anthropic_api_key if provider == "anthropic" else settings.openai_api_key
        if not api_key:
            print(f"  SKIP {provider}/{model} — no API key")
            continue
        clients.append((f"{provider}/{model}", LLMClient(provider=provider, api_key=api_key, model=model)))

    # Run each question through retrieval once, then each model
    for q in questions:
        question_text = q["question"]
        required_facts = q.get("required_facts", [])
        expected_answer = q.get("expected_answer", "")

        # Retrieve + rerank once
        parsed = query_parser.parse(question_text)
        retrieved = await vector_search.search(question_text)
        reranked = reranker.rerank(retrieved, detected_provider=parsed.detected_provider)
        user_prompt = build_user_prompt(question_text, reranked)

        print(f"{'='*80}")
        print(f"Q: {question_text}")
        print(f"Facts: {json.dumps(required_facts, ensure_ascii=False)}")
        print()

        for model_name, client in clients:
            try:
                answer = await client.generate(system_prompt, user_prompt)
            except Exception as e:
                answer = f"ERROR: {e}"

            # Judge correctness
            score = None
            details = []
            if required_facts and settings.openai_api_key:
                try:
                    judge_result = await answer_correctness(
                        question=question_text,
                        generated_answer=answer,
                        expected_answer=expected_answer,
                        required_facts=required_facts,
                        openai_api_key=settings.openai_api_key,
                    )
                    score = judge_result["score"]
                    details = judge_result["details"]
                except Exception as e:
                    score = f"JUDGE_ERROR: {e}"

            print(f"  [{model_name}] score={score}")
            print(f"  Answer: {answer[:200]}")
            if score is not None and score != 1.0 and isinstance(score, (int, float)):
                for d in details:
                    if not d.get("met"):
                        print(f"    MISS: {d['fact']} — {d.get('reason', '')[:100]}")
            print()

    # Cleanup
    for _, client in clients:
        await client.close()
    await embedder.close()


if __name__ == "__main__":
    asyncio.run(main())
