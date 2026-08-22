# First Eval Run — Design Document

**Date**: 2026-02-18
**Status**: Approved

## Goal

Run the first baseline evaluation against 5 ingested documents with 20 hand-crafted test questions (15 answerable, 5 unanswerable). Establish a repeatable eval workflow via the API.

## Changes Required

### 1. Seed Script (`scripts/seed_eval_questions.py`)

Insert eval questions into the `eval_questions` Supabase table:
- Strip `[cite_start]` and `[cite: ...]` markers from expected answers and facts
- Map German field names to English schema columns
- `required_facts` stored as JSON arrays of individual facts
- `required_source_docs` populated for answerable questions, empty for unanswerable
- Idempotent: clears existing rows before inserting

### 2. Pipeline Change (`app/pipeline.py`)

Add `retrieved_chunks` and `reranked_chunks` to the `pipeline.run()` return dict. This gives the eval runner direct access to chunk data without extra DB queries.

### 3. Wire Retrieval Recall (`eval/runner.py`)

The `retrieval_recall()` function exists in `eval/metrics.py` but is not called. Wire it into `_evaluate_question()` using the `retrieved_chunks` from the pipeline result and `required_source_docs` from the eval question.

### 4. Wire `/eval/run` Endpoint (`app/main.py`)

Replace the stub `{"status": "not yet implemented"}` with actual `EvalRunner` invocation using the existing `db`, `pipeline`, and a config snapshot from current settings.

### 5. Run the Eval

- Start API server
- `POST /eval/run` with notes describing this as the first baseline
- Review results via `GET /eval/runs`

## Metrics Available in This Run

| Metric | Status | Source |
|--------|--------|--------|
| Refusal accuracy | Working | `eval/metrics.py` |
| Retrieval recall | Wiring needed | `eval/metrics.py` |
| Answer correctness (LLM-as-judge) | Not yet built | Future iteration |
| Citation accuracy | Not yet built | Future iteration |
| Hallucination detection | Not yet built | Future iteration |

## Question Design

The question set is built so that retrieval quality and refusal behaviour are
measured separately:

| Group | Count | Purpose |
|-------|-------|---------|
| Single-document factual | 8 | Baseline retrieval + extraction from one source |
| Multi-document / conflicting | 4 | Verifies hierarchy priority — grid provider rules override general regulations |
| Cross-reference | 3 | Answer requires combining facts from two documents |
| Unanswerable | 5 | Facts absent from the corpus; the system must refuse rather than guess |

Each answerable question records `required_source_docs` (the document UUIDs that
must appear in the retrieved set) and `required_facts` (the atomic claims the
answer must contain), so recall and correctness can be scored independently.
