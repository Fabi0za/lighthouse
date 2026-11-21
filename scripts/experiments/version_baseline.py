"""Baseline experiments on the BKW V1.2 / V1.3 pair. Changes nothing in app/.

Reuses the app's own components step by step (parse, vector search, Cohere rerank,
prompt builders, LLM, formatter) so one variable can be changed in between:

  stale     -- drop every V1.3 chunk from the retrieved set before reranking
  nolabels  -- after reranking, give V1.2 and V1.3 chunks the same neutral title,
               both in document_title and in the "[title — section]" prefix the
               chunker writes into chunk content. Text inside the documents
               themselves (e.g. "Version: V1.3") is left as it is.

Nothing is written to query_logs. Results go to a JSON file (--out) and stdout.

Usage:
    python scripts/experiments/version_baseline.py {stale|nolabels} --runs 3 --out results.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re

from app.config import get_settings
from app.generation.formatter import ResponseFormatter
from app.generation.llm import LLMClient
from app.generation.prompts import build_system_prompt, build_user_prompt
from app.ingestion.embedder import Embedder
from app.models.database import DatabaseClient
from app.retrieval.query_parser import QueryParser
from app.retrieval.reranker import CohereReranker
from app.retrieval.search import VectorSearch

QUESTIONS = {
    "Q1": "Was muss bei Neuinstallationen im Netz der BKW für Steuerlösungen vorbereitet werden?",
    "Q2": "Muss bei Neuinstallationen im Netz der BKW ein Steuerdraht 2 für den Doppeltarif vorgesehen werden?",
}
V12_PATH = "data/BKW/DE_Vorgaben_BKW_V1.2.pdf"
V13_PATH = "data/BKW/20250521_DE_Vorgaben_BKW_V1.3.pdf"
NEUTRAL_TITLE = "Vorgaben an Niederspannungs-Installationen im Verteilnetz der BKW"
VERSION_CUE = re.compile(r"V1\.[123]|20250521|20250301|21\.05\.2025|01\.03\.2025|1\. März 2025")


def neutralise(chunk: dict, titles: dict[str, str]) -> dict:
    original = titles[chunk["document_id"]]
    content = chunk["content"]
    prefix = f"[{original} — "
    if content.startswith(prefix):
        content = f"[{NEUTRAL_TITLE} — " + content[len(prefix):]
    return {**chunk, "document_title": NEUTRAL_TITLE, "content": content}


async def run_once(mode, question, ids, titles, parts):
    parser, search, reranker, llm, formatter = parts
    parsed = parser.parse(question)
    retrieved = await search.search(question)
    if mode == "stale":
        retrieved = [c for c in retrieved if c["document_id"] != ids["V1.3"]]
    reranked = reranker.rerank(retrieved, query=question, detected_provider=parsed.detected_provider)

    label = {ids["V1.2"]: "V1.2", ids["V1.3"]: "V1.3"}
    trace = [
        {"version": label.get(c["document_id"], "other"), "document": c["document_title"],
         "section": c["section_title"], "page": c["page_number"], "score": round(c["rerank_score"], 3)}
        for c in reranked
    ]
    prompt_chunks = reranked
    if mode == "nolabels":
        prompt_chunks = [neutralise(c, titles) if c["document_id"] in label else c for c in reranked]
        for t, c in zip(trace, prompt_chunks):
            if t["version"] != "other":
                t["version_cues_left_in_prompt"] = sorted(set(VERSION_CUE.findall(c["content"])))

    user_prompt = build_user_prompt(question, prompt_chunks)
    answer = await llm.generate(build_system_prompt(), user_prompt)
    return {
        "detected_provider": parsed.detected_provider,
        "retrieved_counts": {v: sum(1 for c in retrieved if label.get(c["document_id"], "other") == v)
                             for v in ("V1.2", "V1.3", "other")},
        "reranked": trace,
        "answer": formatter.format(answer, prompt_chunks)["answer"],
        "citations": re.findall(r"\[([^\[\]]+?)\]", answer),
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["stale", "nolabels"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    s = get_settings()
    db = DatabaseClient()
    docs = db.list_documents()
    ids = {"V1.2": next(d["id"] for d in docs if d["file_path"] == V12_PATH),
           "V1.3": next(d["id"] for d in docs if d["file_path"] == V13_PATH)}
    titles = {d["id"]: d["title"] for d in docs}

    embedder = Embedder(s.cohere_api_key, s.embedding_model, s.embedding_dimensions)
    llm = LLMClient(provider=s.llm_provider, api_key=s.anthropic_api_key, model=s.llm_model)
    parts = (
        QueryParser(known_providers=db.get_known_scopes()),
        VectorSearch(db=db, embedder=embedder, top_k=s.retrieval_top_k),
        CohereReranker(api_key=s.cohere_api_key, top_n=s.rerank_top_n),
        llm,
        ResponseFormatter(),
    )

    results = {"mode": args.mode, "model": s.llm_model, "runs": []}
    try:
        for qid, question in QUESTIONS.items():
            for i in range(1, args.runs + 1):
                r = await run_once(args.mode, question, ids, titles, parts)
                results["runs"].append({"question_id": qid, "run": i, "question": question, **r})
                print(f"{args.mode} {qid} run {i}: done", flush=True)
    finally:
        await llm.close()
    return args.out, results


if __name__ == "__main__":
    out, results = asyncio.run(main())
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
