# Versioned store: design

Status: approved 2026-11-21. Implementation plans are kept out of the repository.

Partly superseded by `docs/plans/2026-11-22-audit.md` and the decisions recorded there; rewritten as built at the end of the cleanup.

## Why

The assistant has no defence against a superseded document (see `docs/project-brief.md`). `docs/baseline.md` shows three failures on BKW Vorgaben V1.2 / V1.3:

1. **Stale.** Only V1.2 reaches the model; it states V1.2's rule as current, with no signal.
2. **Both, labelled.** Both versions reach the model; it follows V1.3 but cites V1.2 as valid in every run.
3. **Both, unlabelled.** Both versions reach the model; it merges them into one document's rules.

Today a document row is the only unit: two versions of one publication are two unrelated rows, both searchable, and nothing records which rows an answer rested on.

## Goals

The store guarantees, by schema constraint where possible:

- **G1. One current version per source; search sees only current versions.** Makes failures 2 and 3 impossible: an old version's text cannot reach the model.
- **G2. A known successor is never silently ignored.** Once a newer version or candidate successor is in the store, it is either current or held with an open flag.
- **G3. Retirement is traceable.** Once a version is retired, every earlier answer that saw it can be listed, and later changes cannot break that reference.
- **G4. Every source carries the date a person last confirmed it**, so "not confirmed for too long" can be flagged. This is the backstop for successors the system never saw.

Failure 1 cannot be made impossible: the store cannot act on, or flag, a version it never learned about (brief, *Limits*). G2–G4 are the defence: a held candidate is flagged, an unconfirmed source ages into a flag, and once the successor is promoted, the answers that saw the old version are listed.

## Non-goals

- Fetching, change detection, recognising a successor at a new address. The schema only receives their results.
- Resolution screen, scheduling of confirmation checks, flag delivery to a person.
- Scope-based filtering in retrieval, authority conflict handling, citation per statement (build notes, *The bigger system, for later*).
- Storing original files.
- Migrating existing data: the schema is created fresh and the corpus reloaded.

## Anti-goals

- Solar-specific names in tables or columns.
- A version's identity depending on its file name, address or date.
- Any path by which a retired version's chunks can be returned by search.
- A logged answer whose version references can dangle or silently change meaning.

## Approaches considered

**Keeping retired versions.**

- *A. Retired versions keep their chunks, hidden by a status filter.* Instant rollback. But every search function must remember the filter, and retired chunks accumulate in the vector index (the EKZ archive alone has dozens of versions). pgvector applies a filter *after* the HNSW scan, so retired chunks would crowd the top-40 and silently shrink the result set.
- *B. Retired versions keep record, fingerprints and parsed text; their chunks are deleted.* **Chosen.** Old text cannot reach the model even if a filter is missed, and the index holds only current (and briefly pending) chunks. The current-only filter stays in search, because a pending version's chunks exist while it is loaded and before it is promoted.
  What B costs: rollback means re-chunking and re-embedding (minutes, cents); rebuilt chunks equal the originals only if chunker settings are unchanged; answer records cannot point at chunk rows; `scripts/experiments/version_baseline.py` needed V1.2 indexed; its stale mode now rebuilds V1.2's chunks in memory.

**What an answer "used".**

- Top-40 retrieved: lists answers that never touched the old text.
- Cited only: misses answers shaped by uncited text (the unlabelled baseline runs merged V1.2 text without distinguishing it) and depends on citation parsing that does not exist.
- **Top-8 seen by the model: chosen.**

**Scope.** One scope column cannot express a document covering many operators (WV BE/JU/SO is currently scoped "BKW" only). Options: an array column, or a join table. **Join table chosen**: indexable per scope, one row per fact, no array operators in every query.

**Swapping versions.** The Supabase client has no multi-statement transactions, and retire-then-promote as separate calls leaves a window with zero or two current versions. **A single SQL function does the swap** (only sensible way; listed so it is not mistaken for a choice).

## Schema

Fresh `supabase/schema.sql`. `hierarchy_rules` is dropped (unused in code). Unchanged tables: `eval_questions`, `eval_runs`, and `query_logs` columns.

### `sources`: a watched publication

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `title` | text not null | Name of the publication, without version. |
| `issuer` | text not null | Was only in `corpus.yaml`. |
| `level` | text not null | Was `doc_type`. Values are data (`national`, `operator`), not schema. |
| `authority_rank` | integer not null | Was `hierarchy_priority`. |
| `address` | text, unique when not null | Address watched now. Set to the promoted version's address on every promotion. |
| `listing_address` | text | Page that links to the file (build notes: a source is an address plus the page linking to it). |
| `confirmed_at` | timestamptz | Last confirmation by a person; null = never confirmed. The age limit is configuration, not schema. |
| `created_at` | timestamptz not null | |

### `source_scopes`: where a source applies

`(source_id → sources on delete cascade, scope text not null)`, primary key on both.
A source with no rows applies everywhere. The loader keeps refusing an `operator`-level entry without a scope, so "forgotten" cannot pass as "applies everywhere".

### `documents`: one version of a source

The table keeps its name so `document_chunks.document_id` and existing code paths keep their meaning: *a document is a version.*

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `source_id` | uuid not null → sources, on delete restrict | |
| `status` | text not null, check in (`pending`, `current`, `retired`) | |
| `flag_id` | uuid → flags | The flag that holds this version. |
| `title` | text not null | Title as shown to the model, including version label (baseline: the label is how the model tells versions apart). |
| `address` | text | Where this version was obtained. |
| `file_path` | text | Local path at load time. |
| `file_sha256` | text not null | Hash of the file bytes. Identical bytes need no parse. |
| `text_sha256` | text | Hash of normalised parsed text; null until parsed. **This decides whether a file is a new version.** |
| `parsed_output` | jsonb | Was `raw_reducto_output`. The retained record of a version's content. |
| `ingestion_status` | text not null | As today. |
| `created_at`, `became_current_at`, `retired_at` | timestamptz | |

Constraints:

- **One current per source:** `unique index on documents(source_id) where status = 'current'`. (G1)
- **One version per content:** `unique (source_id, text_sha256)`. The same text cannot become a second version, and a rejected candidate cannot be re-flagged over and over. Same text under different packaging resolves to the existing version.
- **Current means loaded:** `check (status <> 'current' or ingestion_status = 'completed')`.
- **Pending means flagged:** `check (status <> 'pending' or flag_id is not null)`, and a trigger requires that flag to be open and to belong to the same source, whenever a version is inserted as or set back to `pending`. (G2)
- **Retired has a date:** `check ((status = 'retired') = (retired_at is not null))`.
- **Fingerprints are immutable:** a trigger rejects changing `file_sha256`, or `text_sha256` once set. In-place replacement, which `scripts/replace_document.py` does today, becomes impossible; that script is removed. (G3)

A retired version with `became_current_at` null was a candidate that was rejected. No separate status is needed.

### `document_chunks`

As today, minus `doc_type`, `grid_provider` and `hierarchy_priority`. These are no longer copied onto chunks. At about 1,200 chunks the join costs nothing, and under B the index holds only current chunks. Revisit only if search latency grows at about 100× the corpus. `on delete cascade` from `documents` stays, but versions are not deleted (see `query_log_documents`).

### `flags`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `source_id` | uuid not null → sources | |
| `kind` | text not null, check in (`new_version`, `candidate`, `check_failed`, `confirmation_overdue`) | `new_version`: same address, content changed. `candidate`: possible successor elsewhere. |
| `detail` | jsonb not null default `{}` | Evidence from the monitor or check. |
| `raised_at` | timestamptz not null | |
| `resolved_at` | timestamptz | Null = open. |
| `resolution` | text | E.g. `promoted (auto)`, `promoted`, `rejected`, `moved to other source`, `dismissed`. |

Rule: a flag cannot be resolved while a `pending` document still points at it (trigger). Together with *pending means flagged*, a pending version always has an open flag. (G2)

Every new version gets a flag when it is inserted, including the clear same-address case. There the promotion resolves the flag in the same call as `promoted (auto)`, so no open flag remains, which matches the brief's "no flag". If loading crashes, the flag stays open and visible instead of leaving a silent half-loaded row.

### `query_log_documents`: versions an answer saw

`(query_log_id → query_logs on delete cascade, document_id → documents on delete restrict)`, primary key on both, index on `document_id`. One row per distinct version among the top-8 chunks passed to the model. (G3)

- `on delete restrict` means a version that any answer saw cannot be deleted.
- Fingerprint immutability means the version cannot be rewritten in place.
- The chunk text in `query_logs.reranked_chunks` remains the record of exactly what the model saw.
- "Answers that used version X" = `select query_log_id from query_log_documents where document_id = X`.
- Eval runs go through `QueryPipeline.run`, so their answers are covered too.

**Cited flag: left out.** It is not free. `formatter.py` lists every top-8 chunk as a source and nothing parses citations from the answer text. A nullable `cited boolean` can be added when a citation parser exists.

### Functions

- **`promote_version(document_id, resolution)`**, one transaction. It locks the source row and requires the document to be `pending` and loaded. Then it:
  1. sets the previous current version to `retired`, stamps `retired_at`, and deletes its chunks;
  2. sets this document to `current` and stamps `became_current_at`;
  3. sets `sources.address` to this document's address when that address is not null;
  4. resolves the flag.
- **`reject_version(document_id, resolution)`**: sets `retired`, deletes the version's chunks, resolves the flag.
- **`match_document_chunks`, `keyword_search_chunks`**: join `documents` with `status = 'current'` and join `sources`. They return `source_id`, `level`, `authority_rank`, `scopes text[]` and the version `title` as `document_title`.

Code that changes as a consequence: the reranker boost becomes "detected scope in `scopes`", the prompt shows `level` / `authority_rank`, the pipeline writes `query_log_documents`, and the loader keys on fingerprints.

## How the two arrival cases flow

**Same file name and address, new content (EKZ).**
1. The monitor reports a change for source S. The system inserts a flag (`new_version`) and a `pending` document with `address = S.address`.
2. It parses the file and computes `text_sha256`.
3. If the hash equals an existing version of S, it was repackaging: the row is not kept and the flag is resolved `dismissed`.
4. Otherwise it chunks and embeds the new text, then calls `promote_version(…, 'promoted (auto)')`.

**New file name, old one still online (BKW).**
1. Something reports a candidate successor to S. The system inserts a flag (`candidate`, with evidence in `detail`) and a `pending` document under S with the new address.
2. It is parsed, and may be chunked; its chunks stay invisible because search sees only `current`.
3. A person promotes it (S's address moves to the new file, V1.2 is retired and its chunks removed), rejects it, or moves it to a different source while it is still pending.
4. V1.2's address remains on its retired row. Watching it further is the monitor's business.

**Reinstating an old version** (content reverts A → B → A): the unique fingerprint finds A's retired row. It is set back to `pending` with a new flag, its chunks are rebuilt from `parsed_output`, and then it is promoted. Undoing a wrong promotion uses the same path, and the wrongly promoted version is retired by that promotion.

**Loading the corpus.** `corpus.yaml` groups entries by source, and versions are listed oldest first. The loader loads each version and promotes it in order. BKW V1.2 is promoted and then retired by V1.3, so a fresh load exercises the retirement path. If a version fails to load, the loader does not attempt that source's later versions in the same run: otherwise a rerun would load the failed older version after the newer one and promote it over the newer. The later versions wait for the next run.

## Tests per choice

| Choice | Tested by |
|---|---|
| One current per source | Inserting a second `current` row for a source fails. |
| Search sees only current | After loading V1.2 then V1.3, both search functions return no V1.2 chunk for Q1/Q2. Rerunning the *Both, labelled* baseline gives "uses V1.2 text as valid" 0/3. |
| B: retire deletes chunks | After promotion, V1.2 has zero chunk rows and still has its `documents` row with fingerprints and `parsed_output`. |
| Atomic swap | `promote_version` that fails midway (for example, the document is not loaded) leaves the previous version current and its chunks intact. |
| Fingerprint, not path | Loading a changed file at the same path creates a new version (the EKZ case, which the path-keyed loader skips today). Loading byte-different but text-identical files creates no version and leaves no open flag. |
| Pending means flagged | Inserting `pending` without `flag_id`, with a resolved flag, or with another source's flag fails; so does setting a version back to `pending` with a resolved flag. Resolving a flag whose document is still pending fails. |
| Immutable fingerprints | Updating `text_sha256` on a loaded version fails. |
| Answers reference versions | A Q1 run writes one row per distinct version in its top-8. After V1.3 retires, the list query returns that run. Deleting a referenced version fails. |
| Multiple scopes | WV BE/JU/SO with two scopes: the reranker boost applies for a question naming either one. |
| Confirmation date | A source loaded without `confirmed_at` reads as never confirmed. (The overdue flag itself is later work.) |
| No solar names | Grep of `schema.sql` for `grid`, `provider`, `solar`, `pv` returns nothing. |

### Where these tests run

The constraint, trigger and function tests above run against a real Postgres with pgvector, not mocks. The existing mocked unit tests stay as they are.

**Chosen: a local Postgres with pgvector**, installed with Homebrew (`postgresql@18` and `pgvector`; Homebrew's pgvector is not built for 17). The local major version may differ from the Supabase project's; applying the schema and reloading the corpus there (Slice 1, Task 6) is the check against the real version. This machine has no Docker. A separate test schema in the Supabase project was rejected: `schema.sql` writes to `public` and grants on it, so it would need parameterising; the tests would need the project's database password and network access; and test runs would share the project with the real corpus.

- The tests connect through `psycopg` using a `TEST_DATABASE_URL` environment variable. When it is unset they are skipped, so `pytest -q` stays green on a machine without Postgres.
- Each test session creates a fresh database, creates the role `service_role` that Supabase normally provides, and applies `supabase/schema.sql` unchanged. Applying the real file is itself the test that the file loads.
- Each test runs in a transaction that is rolled back. Only `promote_version` tests that need to observe a failure halfway through commit, and they use their own database.
- Limits: the major version should match the Supabase project's; PostgREST and Supabase RPC are not exercised here, so the client calls stay covered by the mocked tests.

## Build order

**Slice 1: the store holds versions and search sees only current ones.**

- Fresh schema, `promote_version` and `reject_version`.
- Loader keyed on fingerprints.
- The pipeline writes `query_log_documents`.
- Search returns only current versions.

Then reload the corpus oldest first, so BKW V1.2 is promoted and then retired by V1.3. Re-run the baseline questions and record the result in `docs/baseline.md` as "after".

The *Stale* case needs V1.2's chunks, which the store no longer holds. Its scratch load happens in memory, in the experiment script:

1. Chunk and embed V1.2's retained `parsed_output` (27 chunks).
2. Score those chunks against the query.
3. Use them in place of V1.3's chunks in the top-40 before reranking.

The store is not touched, and the result matches the baseline's definition of the case.

**Slice 2: flags and history end to end.**

- A held candidate is promoted or rejected; an old version is reinstated.
- Multiple scopes in the reranker.
- The list of answers that saw a retired version.

**Later, not planned now:** detection, the EKZ archive test of the normalisation rule, and a resolution screen.

## Unproven, to be tested

- **Text normalisation behind `text_sha256`.** Which differences count as packaging (whitespace, page headers, a date in the footer) is not known. Starting rule (designer's call): parsed section texts in order, Unicode NFC, whitespace runs collapsed to one space, nothing else removed. Test against the EKZ archive captures (52 distinct contents for 34 files), scoring each pair as real change or cosmetic.
- **Rebuilt chunks equal the originals only if chunker settings are unchanged.** Reinstating or rolling back relies on it. Test by rebuilding a version's chunks and comparing them with those recorded in a query log.
  First check (2026-11-21, after the Slice 1 reload): BKW V1.2's chunks rebuilt from its retained parsed output, with unchanged chunker settings, give 27 chunks, the same count as originally loaded. The 2 V1.2 chunks recorded in the 8 earlier query logs (indexes 2 and 5) match their rebuilt counterparts exactly in text, section and page. That covers 2 of 27 chunks, and embeddings were not compared.

## Limitations

- **Original files are not stored.** Fingerprint, path and address are kept, and the parsed text is the retained record. If a publisher removes a file, re-parsing it with a better parser is impossible.
- **Retiring without a successor** (a source withdrawn) is not covered. Only replacement retires.
- **Scopes sit on the source, not the version.** A new version that changes where it applies updates the source. Past answers keep their version references but not the scopes in force at the time.
- **The loader matches sources by title**, since `sources` has no other key. Renaming a source's title in `corpus.yaml` creates a new source instead of a new version of the old one.

## Left to the builder

- Exact SQL, trigger bodies, index names, and whether hold-and-insert is one RPC or two calls (an orphan open flag after a crash is acceptable).
- The `corpus.yaml` layout for grouping versions by source.
- `eval_questions.required_source_docs` holds document IDs that a reload invalidates. Recommendation: hold source IDs and treat "retrieved" as "a current version of that source was retrieved". Making test questions record versions (build notes) is later work.
- Removing `scripts/replace_document.py` and updating `scripts/migrate_html_chunks.py` if it touches the removed chunk columns.
