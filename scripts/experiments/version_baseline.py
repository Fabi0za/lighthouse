"""Baseline experiments on the BKW V1.2 / V1.3 pair, on the versioned store. Changes nothing in app/.

Reuses the app's own components step by step (vector search, Cohere rerank, prompt
builders, LLM, formatter) so one variable can be changed in between:

  current -- the normal pipeline: only current versions are searchable, so V1.3
             (V1.2 is retired). Each answer is logged through log_answer, which
             records the versions of its top-8 in answer_versions.
  stale   -- as if the store held only V1.2: V1.2's chunks no longer exist, so they
             are rebuilt in memory from its retained parsed_output (same chunker
             settings and title as the loader), embedded, and scored against the
             query. The top-40 is then the top-40 of current chunks plus these, with
             V1.3's chunks removed: the same set as the baseline's stale case.
             Nothing is written to the store.

The earlier "nolabels" mode is gone: only one version can reach the model now.

Usage:
    python scripts/experiments/version_baseline.py {current|stale} --runs 3 --out results.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import time

from app.config import get_settings
from app.generation.formatter import ResponseFormatter
from app.generation.llm import LLMClient
from app.generation.prompts import build_system_prompt, build_user_prompt
from app.ingestion.chunker import Chunker
from app.ingestion.embedder import Embedder, embedding_input
from app.ingestion.parser import ReductoParser
from app.answers.logger import AnswerLogger
from app.models.database import DatabaseClient
from app.retrieval.query_parser import QueryParser
from app.retrieval.reranker import CohereReranker
from app.settings_rows import answer_settings_row, indexing_settings_row

MODES = ("current", "stale")
QUESTIONS = {
    "Q1": "Was muss bei Neuinstallationen im Netz der BKW für Steuerlösungen vorbereitet werden?",
    "Q2": "Muss bei Neuinstallationen im Netz der BKW ein Steuerdraht 2 für den Doppeltarif vorgesehen werden?",
}
SOURCE_KEY = "bkw-vorgaben-niederspannung"
V12_LABEL = "Version: V1.2, Gültigkeit 1. März 2025"  # as in corpus.yaml
V13_LABEL = "Version: V1.3, Gültig ab 21.05.2025"


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def scratch_chunks(chunks, embeddings, query_embedding, version: dict, source_fields: dict) -> list[dict]:
    """Search-row-shaped dicts for chunks rebuilt in memory, scored against the query."""
    return [
        {
            "id": f"scratch-{version['id']}-{c.chunk_index}",
            "version_id": version["id"],
            "content": c.content,
            "section_title": c.section_title,
            "page_number": c.page_number,
            "chunk_index": c.chunk_index,
            "version_title": version["title"],
            "version_label": version["version_label"],
            "similarity": cosine(e, query_embedding),
            **source_fields,
        }
        for c, e in zip(chunks, embeddings)
    ]


def pick_versions(versions: list[dict], v12_label: str, v13_label: str) -> tuple[dict, dict]:
    """The V1.2 and V1.3 rows of the BKW Vorgaben source, found by their printed labels."""
    by_label = {v["version_label"]: v for v in versions if v["source_key"] == SOURCE_KEY}
    return by_label[v12_label], by_label[v13_label]


def stale_candidates(live: list[dict], scratch: list[dict], drop_version_id: str, k: int) -> list[dict]:
    """Top-k by similarity of live plus scratch chunks, then without the dropped version."""
    union = sorted(live + scratch, key=lambda c: c["similarity"], reverse=True)[:k]
    return [c for c in union if c["version_id"] != drop_version_id]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=MODES)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    s = get_settings()
    db = DatabaseClient()
    v12, v13 = pick_versions(db.list_versions(SOURCE_KEY), V12_LABEL, V13_LABEL)
    label = {v12["id"]: "V1.2", v13["id"]: "V1.3"}

    embedder = Embedder(s.cohere_api_key, s.embedding_model, s.embedding_dimensions,
                        rate_limit_wait_seconds=s.embed_rate_limit_wait_seconds,
                        rate_limit_retries=s.embed_rate_limit_retries)
    llm = LLMClient(api_key=s.anthropic_api_key, model=s.llm_model)
    query_parser = QueryParser(known_scopes=db.get_known_scopes())
    reranker = CohereReranker(api_key=s.cohere_api_key, top_n=s.rerank_top_n, model=s.rerank_model)
    indexing_settings, answer_settings = indexing_settings_row(s), answer_settings_row(s)
    db.save_indexing_settings(indexing_settings)
    db.save_answer_settings(answer_settings)
    formatter = ResponseFormatter()
    logger = AnswerLogger(db=db)

    results = {"mode": args.mode, "model": s.llm_model,
               "statuses": {"V1.2": v12["status"], "V1.3": v13["status"]}, "runs": []}

    scratch_built = None
    if args.mode == "stale":
        parser = ReductoParser(api_key="unused")  # only _extract_sections is used; no API call
        sections = parser._extract_sections(v12["parsed_output"])
        await parser.close()
        chunks = Chunker(chunk_size=s.chunk_size, chunk_overlap=s.chunk_overlap).chunk_sections(sections)
        embeddings = await embedder.embed_texts(
            [embedding_input(v12["title"], v12["version_label"], c.section_title, c.content) for c in chunks])
        source = db.client.table("sources").select("*").eq("key", v12["source_key"]).execute().data[0]
        source_rank = db.client.table("levels").select("rank").eq("key", source["level"]) \
            .execute().data[0]["rank"]
        scopes = [r["scope_key"] for r in db.client.table("source_scopes").select("scope_key")
                  .eq("source_key", v12["source_key"]).execute().data]
        source_fields = {"source_key": source["key"], "level": source["level"],
                         "rank": source_rank, "scopes": sorted(scopes)}
        scratch_built = (chunks, embeddings, source_fields)
        results["scratch_chunk_count"] = len(chunks)

    try:
        for qid, question in QUESTIONS.items():
            query_embedding = await embedder.embed_query(question)
            for i in range(1, args.runs + 1):
                start = time.monotonic()
                parsed = query_parser.parse(question)
                retrieved = db.vector_search(query_embedding, s.retrieval_top_k)
                if scratch_built:
                    chunks, embeddings, source_fields = scratch_built
                    scratch = scratch_chunks(chunks, embeddings, query_embedding, v12, source_fields)
                    retrieved = stale_candidates(retrieved, scratch, v13["id"], s.retrieval_top_k)
                reranked = reranker.rerank(retrieved, query=question)
                user_prompt = build_user_prompt(question, reranked)
                answer = await llm.generate(build_system_prompt(), user_prompt)
                formatted = formatter.format(answer, reranked)

                run = {
                    "question_id": qid, "run": i, "question": question,
                    "detected_scope": parsed.detected_scope,
                    "retrieved_counts": {v: sum(1 for c in retrieved if label.get(c["version_id"], "other") == v)
                                         for v in ("V1.2", "V1.3", "other")},
                    "reranked": [
                        {"version": label.get(c["version_id"], "other"), "document": c["version_title"],
                         "section": c["section_title"], "page": c["page_number"],
                         "score": round(c["rerank_score"], 3)}
                        for c in reranked
                    ],
                    "answer": formatted["answer"],
                    "citations": re.findall(r"\[([^\[\]]+?)\]", answer),
                }
                if args.mode == "current":
                    version_ids = list(dict.fromkeys(c["version_id"] for c in reranked))
                    answer_id = logger.log(
                        question=question, detected_scope=parsed.detected_scope,
                        retrieved_chunks=retrieved, reranked_chunks=reranked, llm_prompt=user_prompt,
                        llm_response=answer, latency_ms=int((time.monotonic() - start) * 1000),
                        indexing_settings_key=indexing_settings["key"],
                        answer_settings_key=answer_settings["key"], version_ids=version_ids,
                    )
                    logged = db.client.table("answer_versions").select("version_id") \
                        .eq("answer_id", str(answer_id)).execute().data
                    run["answer_id"] = str(answer_id)
                    run["versions_logged"] = sorted(label.get(r["version_id"], "other") for r in logged)
                results["runs"].append(run)
                print(f"{args.mode} {qid} run {i}: done", flush=True)
    finally:
        await llm.close()
        await embedder.close()
    return args.out, results


if __name__ == "__main__":
    out, results = asyncio.run(main())
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
