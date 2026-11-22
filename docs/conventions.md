# Conventions

The standard every table, column, function, script and document in this repository is held to.
Each rule names where it is enforced. Details are in [the design](plans/2026-11-21-versioned-store-design.md).

## The nine rules

1. **Categories are fixed lists enforced by the database.** Any field one would filter, group or join on takes values from a defined list. *Enforced:* `check` constraints (version `status`, flag `kind` and `reason`) and lookup tables (`levels`, `scopes`). *Example:* `flags_reason_matches_kind`.
2. **Free text only for content people read** (title, question, answer, note), never used to group or decide. *Example:* `versions.title` and `version_label` are shown to the model; identity is `text_sha256`, never the title.
3. **References are real foreign keys**, never names or ids inside text or JSON. *Example:* `answer_versions`, `eval_results.answer_id`, `eval_question_sources` → `versions (source_key, text_sha256)`.
4. **Each fact is stored once; derived values are derived.** *Example:* a source's rank comes from its level; eval scores are the view `eval_run_scores`; the formatted answer is computed on read.
5. **Anything one would query is a column or table.** JSON only for raw audit records with a documented shape. *Example:* `versions.parsed_output` (parser output without its links), `answers.retrieved_chunks`, `flags.detail` (checked by `flags_detail_shape`).
6. **Everything is used.** Every column, function, endpoint, script, module and test is read by something or enforces a rule. Otherwise it goes. *Enforced:* review; the docs test names every table, function and script.
7. **Stable readable identifiers** for anything a person or config refers to. *Example:* `sources.key` (`bkw-vorgaben-niederspannung`, immutable), `eval_questions.key`, flag numbers, settings keys built from their values.
8. **One vocabulary** across database, code and docs. *Enforced:* `tests/test_vocabulary.py` (no old-project words, no old store names).
9. **Rules live in the database and are tested against a real database.** *Enforced:* constraints, triggers and one SQL function per multi-step change; `tests/db/` runs on local Postgres with pgvector (`TEST_DATABASE_URL`).

## What lives where

`corpus.yaml` declares which sources exist, with their level, scopes and starting address, and lists their files. The store holds what has happened since: versions and their statuses, flags, confirmations, and the watch address once a person has changed it. A load never overwrites the store's history from the file.

## Fixed lists

- Lists that grow or carry data are lookup tables with foreign keys: `levels`, `scopes`, `indexing_settings`, `answer_settings`.
- Small closed lists are `text` columns with `check` constraints: version status, flag kind, reason, resolution and resolver, `case_type`, `question_type`.
- No PostgreSQL enum types.

## Versions of behaviour

`CHUNKER_VERSION`, `FINGERPRINT_RULE` and `PROMPT_VERSION` name the behaviour that settings rows record. `tests/test_versioned_constants.py` holds a hash of each guarded file. When it fails: raise the constant if the behaviour changed (a new settings key; for indexing settings, a full reload), or re-record the hash if it did not.

## Vocabulary

| Word | Means |
|---|---|
| source | a watched publication, named by its key |
| version | one file of a source, identified by its text fingerprint (table `versions`) |
| current / held / retired | the version searched / waiting for a person / replaced or rejected |
| chunk | a searchable piece of a version's text |
| answer | a logged answer and the versions it saw (`answers`, `answer_versions`) |
| flag | a case a person must handle, by running number |
| level, rank | how authoritative a source is; higher rank wins |
| scope | where a source applies |
| eval question, eval run | a test question with facts; one run of all of them |
