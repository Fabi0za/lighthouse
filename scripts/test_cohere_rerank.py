"""Compare the rule-based reranker against the Cohere neural reranker.

Usage:
    python scripts/test_cohere_rerank.py [question_id ...]

With no arguments, runs every question in the `eval_questions` table. Pass one
or more question IDs to focus on a subset — typically the questions that scored
0.0 across every model in a previous eval run.

For each question it shows which chunks end up in the top-8 under each approach,
then generates and judges an answer from the Cohere-reranked chunks.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cohere

from app.config import get_settings
from app.generation.llm import LLMClient
from app.generation.prompts import build_system_prompt, build_user_prompt
from app.ingestion.embedder import Embedder
from app.models.database import DatabaseClient
from app.retrieval.reranker import Reranker
from app.retrieval.search import VectorSearch
from app.retrieval.query_parser import QueryParser
from eval.metrics import answer_correctness


def cohere_rerank(
    co: cohere.Client, query: str, chunks: list[dict], top_n: int = 8
) -> list[dict]:
    """Rerank chunks using Cohere's rerank API."""
    docs = [c["content"] for c in chunks]
    response = co.rerank(
        query=query,
        documents=docs,
        top_n=top_n,
        model="rerank-v3.5",
    )
    reranked = []
    for result in response.results:
        chunk = {**chunks[result.index], "cohere_score": result.relevance_score}
        reranked.append(chunk)
    return reranked


async def main():
    selected_ids = set(sys.argv[1:])

    settings = get_settings()
    db = DatabaseClient()
    embedder = Embedder(
        api_key=settings.cohere_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    query_parser = QueryParser(known_providers=db.get_known_providers())
    vector_search = VectorSearch(db=db, embedder=embedder, top_k=settings.retrieval_top_k)
    rule_reranker = Reranker(top_n=settings.rerank_top_n)
    system_prompt = build_system_prompt()

    co = cohere.Client(api_key=settings.cohere_api_key)

    llm = LLMClient(provider=settings.llm_provider, api_key=(
        settings.anthropic_api_key if settings.llm_provider == "anthropic"
        else settings.openai_api_key
    ), model=settings.llm_model)

    all_questions = db.get_eval_questions()
    questions = [q for q in all_questions if q["id"] in selected_ids] if selected_ids else all_questions
    print(f"Testing {len(questions)} questions\n")

    for q in questions:
        text = q["question"]
        facts = q.get("required_facts", [])

        # Retrieve once
        parsed = query_parser.parse(text)
        retrieved = await vector_search.search(text)

        # Rule-based rerank
        rule_top8 = rule_reranker.rerank(retrieved, detected_provider=parsed.detected_provider)

        # Cohere rerank
        cohere_top8 = cohere_rerank(co, text, retrieved, top_n=8)

        print("=" * 80)
        print(f"Q: {text}")
        print(f"Facts: {json.dumps(facts, ensure_ascii=False)}")

        # Compare top-8 composition
        rule_ids = {c["id"] for c in rule_top8}
        cohere_ids = {c["id"] for c in cohere_top8}
        only_rule = rule_ids - cohere_ids
        only_cohere = cohere_ids - rule_ids

        print(f"\nRule-based top-8:")
        for i, c in enumerate(rule_top8, 1):
            marker = " " if c["id"] not in only_rule else "*"
            print(f"  {marker}{i}. [{c.get('document_title','')[:30]}] {c['section_title'][:30]} | {c['content'][:60]}...")

        print(f"\nCohere top-8:")
        for i, c in enumerate(cohere_top8, 1):
            marker = " " if c["id"] not in only_cohere else "*"
            print(f"  {marker}{i}. score={c['cohere_score']:.3f} [{c.get('document_title','')[:30]}] {c['section_title'][:30]} | {c['content'][:60]}...")

        if only_cohere:
            print(f"\n  NEW chunks from Cohere (not in rule-based top-8):")
            for c in cohere_top8:
                if c["id"] in only_cohere:
                    print(f"    [{c.get('document_title','')[:30]}] {c['section_title'][:30]}")
                    print(f"    {c['content'][:120]}...")

        # Generate answer with Cohere-reranked chunks
        user_prompt = build_user_prompt(text, cohere_top8)
        try:
            answer = await llm.generate(system_prompt, user_prompt)
        except Exception as e:
            answer = f"ERROR: {e}"

        # Judge
        score = None
        if facts and settings.anthropic_api_key:
            try:
                judge = await answer_correctness(
                    question=text,
                    generated_answer=answer,
                    expected_answer=q.get("expected_answer", ""),
                    required_facts=facts,
                    anthropic_api_key=settings.anthropic_api_key,
                )
                score = judge["score"]
            except Exception:
                score = "ERROR"

        print(f"\n  Cohere-reranked answer (score={score}):")
        print(f"  {answer[:200]}")
        print()

    await llm.close()
    await embedder.close()


if __name__ == "__main__":
    asyncio.run(main())
