# Versioned store: design as built

Approved 2026-11-21; rebuilt to [the conventions](../conventions.md) in the cleanup of 2026-11-22. This document describes `supabase/schema.sql` as it is. Implementation plans are kept out of the repository.

## Why

The assistant had no defence against a superseded document (see `docs/project-brief.md`). `docs/baseline.md` shows three failures on BKW Vorgaben V1.2 / V1.3:

1. **Stale.** Only V1.2 reaches the model; it states V1.2's rule as current, with no signal.
2. **Both, labelled.** Both versions reach the model; it follows V1.3 but cites V1.2 as valid.
3. **Both, unlabelled.** Both versions reach the model; it merges them into one document's rules.

## Goals

- **G1. One current version per source; search sees only current versions.** Makes failures 2 and 3 impossible.
- **G2. A known successor is never silently ignored.** Once a newer version or candidate is in the store, it is current, or held with an open flag, or failed with a flag.
- **G3. Retirement is traceable.** Every earlier answer that saw a retired version can be listed, and the version cannot be rewritten or deleted.
- **G4. Every source carries the date a person last confirmed it**, so "not confirmed for too long" can be flagged. This is the backstop for successors the system never saw.

Failure 1 cannot be made impossible: the store cannot act on a version it never learned about. G2–G4 are the defence.

## Decisions

- **Retired versions keep record, fingerprints and parsed text; their chunks are deleted.** Old text cannot reach the model even if a filter is missed, and the vector index holds only current (and briefly loading or held) chunks. Rollback means re-chunking from `parsed_output`.
- **What an answer "used" is the top 8 chunks passed to the model**, recorded per distinct version.
- **Scopes are a join table**, so a source can apply to several.
- **Every multi-step change is one SQL function.** The Supabase client has no multi-statement transactions.
- **A version is identified by its text fingerprint**, never by its file name, address or date.

## Schema

### Reference tables

- `levels (key, rank unique, requires_scope)`: higher rank wins where sources conflict (stated on the column). `operator` rank 2 requires a scope; `national` rank 1 does not.
- `scopes (key, name)`: where a source applies. A question's scope is detected by the key as a whole word.
- `indexing_settings (key, embedding_model, dimensions, chunk_size, chunk_overlap, chunker_version, fingerprint_rule)`: what turns text into chunks and decides identity. `dimensions = 1536` (the vector column). The key is built from the values (`embed-v5.0-pro-1536-500-50-c2-f1`).
- `answer_settings (key, retrieval_top_k, rerank_top_n, rerank_model, answer_model, prompt_version)`: what an answer depends on besides the text.

Rows of `levels` and `scopes` come from `corpus.yaml`. Rows of the settings tables come from the app's configuration and the constants `CHUNKER_VERSION`, `FINGERPRINT_RULE` and `PROMPT_VERSION`, each guarded by a source hash (`tests/test_versioned_constants.py`).

### Sources

- `sources (key, level → levels, watch_address unique, confirmed_at, created_at)`. The key is `publisher-publication`, lowercase, with no version or year. It is immutable (trigger `sources_key_immutable`, function `sources_key_immutable`).
- `source_scopes (source_key, scope_key → scopes)`. The deferred constraint triggers `sources_scope_required` and `source_scopes_scope_required` (function `sources_scope_required`) refuse, at commit, a source whose level requires a scope but which has none.
- `save_source(key, level, scopes, watch_address)` writes a source with its scopes in one transaction. Adding a source or changing its watch address stamps `confirmed_at` and resolves an open overdue flag (via `resolve_overdue`).

### Flags

`flags (id bigint identity, source_key, kind, reason, detail, raised_at, resolved_at, resolution, resolved_by)`:

- `id` is the running number people use.
- `kind`, `reason`, `resolution` and `resolved_by` come from fixed lists, and `flags_reason_matches_kind` pairs reasons with kinds:
  - candidate / possible_successor;
  - check_failed / unreachable, parse_failed or load_failed;
  - confirmation_overdue / overdue.
- `resolution` is in (promoted, rejected, fixed, confirmed); `resolved_by` is system or person.
- The three resolution fields are set together.
- `detail` is `{"file"}` (load failures) or `{"address"}` (the rest), plus an optional `"message"`, checked by `flags_detail_shape`.
- `flags_resolve_guard` (trigger and function) refuses to resolve a flag that still holds a held version.
- `flags_one_open_overdue_per_source` keeps at most one open overdue flag per source.

### Versions

`versions (id, source_key, status, flag_id, title, version_label, obtained_from, page_limit, indexing_settings_key, file_sha256, text_sha256, parsed_output, created_at, became_current_at, retired_at)`:

- `status` is in (loading, failed, held, current, retired).
- `versions_one_current_per_source` is a partial unique index (G1).
- `unique (source_key, text_sha256)`: one version per content.
- `versions_status_needs_flag` (trigger and function): held needs an open candidate flag of the same source, and failed needs a check_failed flag (G2).
- `versions_record_immutable` (trigger and function): fingerprints, `obtained_from` once set, label, page limit and settings never change (G3).
- `versions_no_mixed_settings` (trigger and function): current versions share one set of indexing settings.
- `parsed_output` is the parser response without its links into the parser's service.

### Chunks and search

- `chunks (id, version_id, content, section_title, page_number, chunk_index, embedding vector(1536) not null)`, with `unique (version_id, chunk_index)` and an HNSW index (`chunks_embedding_idx`).
- Chunk text carries no header. The embedding input and the prompt build "title (label) — section" from the columns. An empty section title falls back to the page.
- `match_chunks(embedding, count)` returns current versions' chunks with the source key, level, rank, scopes, title and label.

### Answers

- `answers (…, detected_scope → scopes, indexing_settings_key, answer_settings_key, retrieved_chunks, reranked_chunks, llm_prompt, llm_response, latency_ms)`. The two chunk lists are the raw audit of what the model saw.
- `answer_versions (answer_id, version_id → versions on delete restrict)`, with index `answer_versions_version_idx`. A version an answer saw cannot be deleted.
- `log_answer(answer, version_ids)` stores both in one transaction.
- `answers_that_saw(version_id)` lists the answers that saw a version, newest first, with the other versions each saw.

### Eval

- `eval_questions (key, question, question_type, case_type, expected_answer)`.
- `eval_question_facts (question_key, position, text)`.
- `eval_question_sources (question_key, source_key, written_from_text_sha256)`, which references `versions (source_key, text_sha256)`.
- The view `eval_questions_to_review` lists questions whose source now has another current version, or none.
- `save_eval_question(question)` writes a question with its sources and facts. Once a question has results, its question and facts are fixed.
- `eval_runs (id, run_at, indexing_settings_key, answer_settings_key, judge_model, notes)`.
- `eval_results (run_id, question_key, answer_id → answers, refusal_correct, retrieval_recall, answer_correctness, judge_error)`. A failed judgement has no score.
- `eval_fact_results (run_id, question_key, position, present, reason)`.
- `record_eval_run(run)` stores a run whole.
- The view `eval_run_scores` derives the scores. It counts scored and not-scored results and averages only real values.

Both views run with the caller's rights (`security_invoker`). Every table has row level security with no policies, and every write function is executable only by `service_role`.

### JSON audit records

The only JSON columns are raw records nobody queries by content (rule 5), plus the transport parameters of `log_answer`, `record_eval_run` and `save_eval_question`, whose shapes are in their SQL comments:

- `versions.parsed_output`: the parser's response without `pdf_url`, `studio_link` and block `image_url`: `{usage, job_id, duration, parse_mode, response_type, document_properties, result: {type, ocr, custom, chunks: [{content, embed, enriched, enrichment_success, blocks: [{type, content, bbox: {page, original_page, top, left, width, height}, confidence, granular_confidence, extra, chart_data}]}]}}`. Sections and the text fingerprint are derived from `result.chunks[].blocks[]`.
- `answers.retrieved_chunks` (top 40) and `answers.reranked_chunks` (top 8, plus `rerank_score`): rows as `match_chunks` returns them: `{id, version_id, source_key, content, section_title, page_number, chunk_index, level, rank, scopes, similarity, version_title, version_label}`. `id` names a chunk that is deleted when its version retires, so it is a record, not a reference; the reference is `answer_versions`.
- `flags.detail`: `{"file": …}` or `{"address": …}`, with an optional `"message"`, checked by `flags_detail_shape`.

## Lifecycle

**Routine load** (`scripts/load_corpus.py` → `load_version`):

1. `begin_load` inserts a loading version without a flag. If a loading or failed version of the same source has the same bytes and settings, it takes that one up again and clears its chunks.
2. The text fingerprint decides: the same text as a current or retired version means the new row is discarded (`discard_version`, "dismissed", no flag). The same text as another unfinished version means that one is discarded instead.
3. The loader chunks and embeds the text.
4. `promote_version` retires the previous current version, deletes its chunks, makes this one current, resolves the version's flag if it has one, and returns how many answers saw the retired version. The source is not changed.
5. On error, `fail_load` marks the version failed and raises one check_failed flag naming the file, or updates the open one. A successful retry resolves it as fixed by the system.

**Candidate** (a successor found elsewhere):

- `hold_candidate` holds a loaded version under a candidate flag with the address and evidence.
- A person then runs `approve_candidate` or `reject_version` (`scripts/flags.py`). Approval promotes the version, sets the source's watch address to where the candidate was obtained, and confirms the source. It refuses a candidate without an address.

**Checks and confirmation:**

- `raise_check_failed` is what a monitor reports for an unreachable address; a person settles it with `resolve_check` once the address works again.
- A person gives up a failed or stuck loading version with `discard_version(version, 'person')`, which resolves its flag as rejected. `scripts/flags.py list` shows versions still loading with their age, so a crashed load is never invisible.
- `raise_overdue_flags(age)` flags each source not confirmed within the age, once per source.
- `confirm_source` confirms a source and resolves its overdue flag (`resolve_overdue`).

The loader stops before writing anything if the store holds a source that `corpus.yaml` no longer lists, or if current versions use other indexing settings.

## Tests per rule

| Rule | Tested by (all against a real Postgres unless noted) |
|---|---|
| One current per source; search sees only current | `tests/db/test_schema.py`, `test_functions.py` |
| Statuses need their flags; flags from fixed lists, detail shape | `test_schema.py`, `test_flags.py` |
| Load, fail, retry, discard, promote, reject, hold, approve | `test_lifecycle.py`, `test_load_version.py` (through `load_version`) |
| Immutable keys, fingerprints, addresses, labels, settings | `test_schema.py`, `test_settings.py` |
| No mixed indexing settings; settings checks | `test_settings.py` |
| Answers reference versions and settings; listing answers that saw a version | `test_functions.py`, `test_settings.py` |
| Eval tables, review and score views, freeze once scored | `test_eval.py` |
| Row level security, function and view rights | `test_access.py` |
| Version constants follow their code | `tests/test_versioned_constants.py` (unit) |
| One vocabulary | `tests/test_vocabulary.py` (unit) |

## Unproven, to be tested

- **Text normalisation behind `text_sha256`.** Which differences count as packaging (whitespace, page headers, a date in the footer) is not known. Starting rule (`FINGERPRINT_RULE` 1): the parser's blocks in order, headings and short blocks included, page headers, footers, page numbers and figures left out, Unicode NFC, whitespace runs collapsed to one space. Test it against the EKZ archive captures (52 distinct contents for 34 files), scoring each pair as real change or cosmetic. On the 11 cached parses the rule gives 11 distinct fingerprints and keeps V1.2 and V1.3 apart (`scripts/experiments/fingerprint_check.py`, output in `plans-local/fingerprint-check.txt`).
- **A version statement printed in a page header is outside the fingerprint.** BKW Vorgaben V1.2 prints "Gültigkeit 1. März 2025 / Version: V1.2" in a page header block, so a successor that changed only its version number would create no new version.
- **Rebuilt chunks equal the originals only under the same indexing settings.** Reinstating or rolling back relies on it. First check (2026-11-21): BKW V1.2's chunks rebuilt from its parsed output gave the same 27 chunks; the 2 recorded in earlier logs matched exactly in text, section and page. Embeddings were not compared.

## Limitations

- **Original files are not stored.** The parsed text is the retained record; if a publisher removes a file, re-parsing it with a better parser is impossible.
- **Retiring without a successor** (a source withdrawn) is not covered. Only replacement retires.
- **Scopes sit on the source, not the version.** Past answers keep their version references but not the scopes in force at the time.
- **Changing indexing settings needs a reload into a fresh store** (see *Known gaps* in `docs/build-notes.md`).
