# Changelog

Each entry: what changed and why, then the evidence. Measurements live in [baseline.md](baseline.md).

## 2026-11-21

- **Declare `cohere` and limit package discovery to `app/` and `eval/`.** The reranker imported an undeclared package, and the editable install broke once `data/` existed.
  Evidence: `pip install -e ".[dev]"` failed with "Multiple top-level packages discovered"; after the change it installs and 76/76 tests pass.
- **Align `.env.example`, config defaults and README: top-k 40, rerank 8, Anthropic as LLM provider, `COHERE_API_KEY` listed.** The example file still said top-k 20 and the README named GPT-4o.
  Evidence: `config.py` defaults were already 40 / 8 / anthropic; the other two files now match.
- **Embed with Cohere instead of OpenAI: `input_type` `search_document` for indexing and `search_query` for queries, `output_dimension` 1536, batches of 96.** Removes the OpenAI dependency without changing the `vector(1536)` schema.
  Evidence: a live call returns 1536-dimension vectors for documents and queries; embedder tests check input type, dimension and batching.
- **Eval judge: `claude-haiku-5-5` with structured output instead of `gpt-4o-mini`.** Removes the last OpenAI call; structured output means a malformed JSON reply cannot break the judge.
  Evidence: on a live check with one fact present and one absent, it scores 0.5; judge tests mock the Anthropic client.
- **Embedding model `embed-v5.0-pro` instead of `embed-v4.0`.** Newest Cohere embedding family, still at 1536 dimensions.
  Evidence: Cohere docs list 1536 among its dimensions (default 2048); a live call returns 1536 for documents and queries.
- **Grant `service_role` access at the end of `supabase/schema.sql`.** On a fresh project the secret key could not read tables created in the SQL editor.
  Evidence: before the grants, 6/6 tables and 2/2 search functions returned 42501 "permission denied"; afterwards all were readable and a test insert and delete succeeded.
- **Add `corpus.yaml` (path, title, issuer, level, scope, source_url per document).** One declared source of document metadata; level and scope map to the existing `doc_type`, `hierarchy_priority` and `grid_provider` columns.
  Evidence: titles, issuers and versions were read from each PDF's first pages; the `doc_type` strings come from the original design doc.
- **Add `scripts/load_corpus.py`.** Repeatable, idempotent load through the same steps as `POST /ingest`: skips completed documents, reloads partial ones, honours `max_pages`.
  Evidence: 6 loader tests; a second run after a rate-limit failure skipped 9 documents and reloaded the 2 failed ones, with no duplicates.
- **Add BKW Vorgaben V1.2 next to V1.3 as a separate document.** Reproduces the case of a new version published under a new name while the old one stays online.
  Evidence: the V1.2 cover reads "Version V1.2, valid from 1 March 2025"; the V1.3 cover reads "Ersetzt V1.2"; the text differs in section 4.
- **Anthropic call in `llm.py`: drop `temperature`, return the text block(s) instead of `content[0]`.** `claude-sonnet-5-5` rejects `temperature`, and with thinking the first block need not be text. Answers are no longer deterministic.
  Evidence: before the change every query failed with HTTP 400 "`temperature` is deprecated for this model"; 3 new tests; 86/86 pass.
- **Add `scripts/experiments/version_baseline.py` (stale and no-label variants), with no change to `app/`.** Measures how answers behave when versions are missing or unlabelled.
  Evidence: results in [baseline.md](baseline.md).
- **Fresh schema: documents are versions of sources, with scopes, flags and answer-to-version links; `hierarchy_rules` and the solar-specific columns removed.** Two versions of one source could both be searched, and nothing recorded which versions an answer used (see baseline).
  Evidence: 14 constraint and trigger tests against local Postgres 18 + pgvector pass (one current per source, pending needs a flag, immutable fingerprints, used versions undeletable); 87 others pass, 13 skip without `TEST_DATABASE_URL`.
- **`promote_version`, `reject_version` and `log_answer` as SQL functions; both search functions return current versions only, with source level, rank and scopes.** Retire-then-promote as separate client calls could leave zero or two current versions, and an answer could be stored without its versions.
  Evidence: 12 function tests on local Postgres pass, including a failed promotion that leaves the previous version current with its chunks, and search ignoring pending and retired chunks.
- **Remove `scripts/replace_document.py`; add content fingerprints and client methods for holding, promoting and rejecting versions.** Replacing a document in place erased the old version and made logged answers point at text that no longer existed.
  Evidence: 23 new unit tests (fingerprint normalisation, flag inserted before its pending version, RPC parameters); 130 tests pass with the database tests.
- **Loader and `POST /ingest` load versions by fingerprint; `corpus.yaml` lists sources with versions oldest first; `DELETE /documents` removed.** The path-keyed loader skipped a changed file at an unchanged path (the EKZ case), and deleting a version would break the answers that used it.
  Evidence: 25 new or rewritten tests: same bytes skipped, same text with new bytes dismissed with no open flag, an interrupted load resumed, a failed version stops later ones of its source; 146 tests pass.
- **Each answer is logged together with the distinct versions of its top-8 chunks; the prompt, query filter and legacy reranker read `level`, `authority_rank` and `scopes`.** Earlier answers that relied on a retired version must be listable, and answers shaped by uncited text count (baseline, unlabelled case).
  Evidence: pipeline test with chunks from d1, d1, d2 logs ["d1", "d2"]; prompt renders "(Type: operator, Priority: 2)"; reranker boosts when any of a chunk's scopes matches; 149 tests pass.
