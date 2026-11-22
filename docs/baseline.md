# Baseline: superseded versions

How the assistant answers when a document has been replaced by a newer version. It was measured three times:

- **before**: before any versioning logic existed;
- **after**: on the versioned store, 2026-11-21 (see [the design](plans/2026-11-21-versioned-store-design.md));
- **after cleanup**: once the store had been rebuilt to [the conventions](conventions.md) and reloaded into a fresh schema, 2026-11-22.

## Setup

- **Corpus:** 11 documents loaded from `corpus.yaml`. National VSE recommendations have rank 1; BKW and EKZ operator rules have rank 2. Chunks: 1183 before; 1156 after (V1.2's 27 deleted on retirement); 1154 after cleanup (page headers no longer start sections, see below).
- **Document pair:** BKW *Vorgaben an Niederspannungs-Installationen* V1.2 (valid from 01.03.2025) and V1.3 (valid from 21.05.2025; its cover reads "Ersetzt V1.2"). 27 chunks each.
- **Difference:** section 4, *Steuern oder Sperren von Anlagen*.
  - V1.2 says only that new installations and self-consumption systems are no longer controlled or blocked.
  - V1.3 narrows this to audio-frequency ripple-control receivers. It requires a spare mounting slot with a control circuit breaker, plus sealable terminals for control wires 1 and 0, and it makes wire 2 (dual tariff) optional.
- **Pipeline:** `embed-v5.0-pro` (1536 dimensions), vector search top 40, Cohere `rerank-v3.5` top 8, `claude-sonnet-5-5`. Sampling is not fixed, so each question was run 3 times.
  - After cleanup, the settings are recorded per version and per answer: indexing `embed-v5.0-pro-1536-500-50-c2-f1`, answers `top40-rerank8-rerank-v3.5-claude-sonnet-5-5-p4`.
- **Questions:**
  - Q1: "Was muss bei Neuinstallationen im Netz der BKW für Steuerlösungen vorbereitet werden?"
  - Q2: "Muss bei Neuinstallationen im Netz der BKW ein Steuerdraht 2 für den Doppeltarif vorgesehen werden?"
- **Scoring:** the author compared each answer and its citations against the V1.3 text. The pipeline's own confidence field is not used, because it recognises only an English "Confidence:" line.

## Cases

| Case | Store | What the model sees |
|---|---|---|
| **Stale** | before: both versions, unversioned; after and after cleanup: V1.3 current, V1.2 retired | The top 40 without V1.3's chunks, as if the store held only the old version. After and after cleanup, V1.2's chunks are rebuilt in memory from its retained parsed output and scored against the query; the top 40 is the top 40 of current chunks plus these, minus V1.3. Nothing is written to the store. |
| **Normal pipeline** | before: both versions, labelled by title ("Both, labelled"); after and after cleanup: V1.3 current, V1.2 retired ("Current") | The normal pipeline. Before, both versions were searchable; after, only current versions are. |
| **Both, unlabelled** (before only) | Both versions, unversioned | The same top 8 as "Both, labelled", but V1.2 and V1.3 have the same title. With one current version per source this case cannot occur after. |

In every case the reranked top 8 was identical across the 3 runs of a question.

## Results

3 runs per cell. Each cell reads **before · after · after cleanup**; a dash means the case does not occur at that stage.

| Case | Q | Answer follows | All V1.3 facts | Uses V1.2 text as valid | Notes two versions | Treats difference as conflict |
|---|---|---|---|---|---|---|
| Stale | Q1 | V1.2 · V1.2 · V1.2 | 0/3 · 0/3 · 0/3 | 3/3 · 3/3 · 3/3 | 0/3 suspect a newer version, at every stage | – |
| Stale | Q2 | none ("not in the sources, probably not needed") · none ("not stated explicitly; tends towards not needed") · none (same) | 0/3 · 0/3 · 0/3 | 3/3 · 3/3 · 3/3 | 0/3 suspect a newer version, at every stage | – |
| Normal pipeline | Q1 | V1.3 · V1.3 · V1.3 | 3/3 · 3/3 · 3/3 | 1/3 · 0/3 · 0/3 | 3/3 · – · – | 0/3 · 0/3 · 0/3 |
| Normal pipeline | Q2 | V1.3 · V1.3 · V1.3 | 3/3 · 3/3 · 3/3 | 2/3 · 0/3 · 0/3 | 3/3 · – · – | 0/3 · 0/3 · 0/3 |
| Both, unlabelled | Q1 | V1.3 and V1.2 merged · – · – | 3/3 · – · – | 3/3 · – · – | 0/3 · – · – | 0/3 · – · – |
| Both, unlabelled | Q2 | V1.3 and V1.2 merged · – · – | 3/3 · – · – | 3/3 · – · – | 0/3 · – · – | 0/3 · – · – |

**Before:**

- **Stale:** the answer is wrong for Q1. It states V1.2's blanket rule as current, and nothing signals that a newer version exists.
- **Labelled:** the model picks V1.3 by the version and date in the titles.
  - It still cites V1.2 in every run and calls the two versions compatible. That is wrong for Q1, where V1.2 alone would mean nothing needs preparing.
  - V1.3's own "Ersetzt V1.2" chunk was never in the top 8.
- **Unlabelled:** the model can no longer tell that there are two versions, and presents both sentences as one document's rules.

**After (versioned store, 2026-11-21):**

- **Current:** V1.2 is in neither the top 40 nor the top 8 in any of the 6 runs. Every answer contains all V1.3 facts, and none uses V1.2 text. For each run, `query_log_documents` lists V1.3 and other documents, never V1.2.
- **Stale:** unchanged in substance: 0/6 contain a V1.3 fact, and 0/6 suspect a newer version.
  - The retrieval matches the before run: 26 (Q1) and 30 (Q2) chunks are left in the top 40 after V1.3 is removed.
  - The top 8 is V1.2 sections 4, 1, 6.1 and 6.6 plus Notfallsteuerung for Q1, and V1.2 sections 4, 1, 2 and 6.6 ×2 plus Notfallsteuerung for Q2.
- **Stale Q1 tone, unexplained:** before, all 3 answers noticed the tension between "no control" and the Notfallsteuerung document and resolved it by their own interpretation. After, all 3 call it an apparent contradiction and recommend clarifying with BKW, at medium confidence. One answer reasons about "Typ operator, Priorität 2", so the prompt label change is a plausible cause, not a proven one.
- What the store fixes is the labelled and unlabelled failure: an old version cannot reach the model. The stale failure is unchanged, as the design expects. Against it the store offers flags, the confirmation date, and the list of answers that saw a retired version.

**After cleanup (2026-11-22):**

- **Current:** as after. V1.2 is in no top 40. The top 40 holds 21 V1.3 chunks for Q1 and 13 for Q2, and V1.3's section 4 ranks first. Every answer contains all V1.3 facts and none uses V1.2 text. `answer_versions` lists V1.3 and Notfallsteuerung for each run, never V1.2.
- **Stale:** as after.
  - The top 40 holds 26 (Q1) and 30 (Q2) candidates.
  - The top 8 is V1.2 sections 4, 1, 6.6 and 6.1 plus Notfallsteuerung for Q1, and V1.2 sections 4, 1, 2 and 6.6 ×2 plus Notfallsteuerung for Q2.
  - 0/6 contain a V1.3 fact or suspect a newer version.
- **Citations name the edition:** every citation of the BKW Vorgaben carries the version label. That is 19 citations in the 6 current answers, all "V1.3", and 16 in the 6 stale answers, all "V1.2". A reader of a stale answer can now see that it rests on V1.2.
- **Tone, current Q1:** all 3 answers state V1.3's control circuit breaker requirement next to the Notfallsteuerung document's "breaker not needed", without calling it a contradiction. In the runs just before the citation fix, all 3 added a note on a "scheinbarer/möglicher Widerspruch" (apparent or possible contradiction). This is the known disagreement between two current documents (build notes), not a version conflict, so the conflict column stays 0/3.
- **Tone, stale:** for Q1, 2 of 3 answers settle the tension between "no control" and Notfallsteuerung by rank ("same rank (2)") and by where each rule applies; the third says the documents do not explain it. None recommends asking BKW. For Q2, 2 of 3 recommend asking BKW. Confidence is medium or low throughout.
- **Eval run on the two questions** (`eval/questions.yaml`): both answers are judged correct on every fact (Q1 4/4, Q2 1/1). Recall is 1.0, refusal is correct, and there is no judge error. The scores view reads 2 questions, 2 scored, 0 not scored.

## Differences in what the model sees, other than the store

**Between before and after:** each source line showed the level (`national`, `operator`) where it showed the old type string (`general_regulation`, `grid_provider_rule`). The parsed text and the chunks were the same: the reload read the parser output saved from the before store (`--parsed-cache`).

**Between after and after cleanup**, with the commit that made each change:

1. **Header once** (`d87bfc5`). Chunk text no longer starts with "[title — section]". The prompt shows each source's header once, in its source line, instead of twice.
2. **Title and label as printed** (`0c0a557`, `5c1da5a`). The source line reads "Vorgaben an Niederspannungs-Installationen im Verteilnetz der BKW (Version: V1.3, Gültig ab 21.05.2025)" instead of the hand-written "… der BKW (V1.3, gültig ab 21.05.2025)". The same string is part of the embedding input.
3. **Prompt words** (`66db515`).
   - "You are a technical knowledge assistant for field engineers working with electrical installation documents." → "You are an assistant that answers from the provided documents."
   - "prefer the document with higher hierarchy priority and explain the override" → "prefer the source with the higher rank and explain which one prevails".
   - `(Type: …, Priority: …)` → `(Level: …, Rank: …)`.
4. **Citation rule** (`b9e8b8e`). "Cite every claim with [Document Title, Section, Page X]" → "Cite every claim with [Document Title (Version Label), Section, Page X], with the title and version label exactly as shown in the source line; leave out the parentheses for a source with no label."
5. **Sections without a heading** (`9322a43`). They have an empty title instead of "Untitled Section", and their source line and citation fall back to the page.
6. **Page headers** (`30e9916`). Page headers no longer start sections. Over the corpus this gives 421 → 419 sections and 1183 → 1181 chunks, both changes in WV CH. BKW V1.2's and V1.3's cover version box is no longer a section title.
7. **Rerank input** (`91dee56`). The reranker scores the same "[title (label) — section]" header and text as the embedding. Before the cleanup it scored the chunk text, which then started with that header.
8. **Not model input:** the text fingerprints changed (`2f89cbf`; identity only), parsed output no longer keeps the parser's links (`f438441`), and answers record their settings (`e3ba12e`).

**Reload:** all chunks were embedded again with the same model. The reload read the same cached parser output, so the parsed text is unchanged. It ran in one pass with a production Cohere key: 11 versions promoted, 0 failed, 0 rate-limit waits, 0 open flags.

## Found and fixed during the cleanup

Both were found by the after-cleanup baseline runs, before any number was recorded here.

- **The reranker lost the header** (introduced with change 1, fixed in `91dee56`). With the header removed from chunk text, the reranker scored bare text. In the stale case, V1.2's section 4 left the top 8 (Q1 and Q2 kept only section 6.6). Reranking the same candidates with the header gave back the earlier top 8 exactly. Fixed by reranking on the embedding input; `PROMPT_VERSION` 3 now covers the reranker.
- **Citations lost the version label** (introduced with change 2, fixed in `b9e8b8e`). The label moved from the title into its own column, while the citation rule asked only for "Document Title". The model then cited the title alone. In the stale case nothing in an answer said V1.2. Fixed by asking for "[Document Title (Version Label), …]" (`PROMPT_VERSION` 4). After the fix, every one of the 35 Vorgaben citations in the 12 answers carries its label.

## Where the numbers come from

- **Before, stale and unlabelled:** the author's reading of the runs of `scripts/experiments/version_baseline.py` (modes `stale` and `nolabels`) at the commits before the versioned store. The raw run output was not kept. The retrieval counts and top-8 makeup for the stale case survive only in a local, unpublished draft of the changelog from the same day.
- **Before, labelled:** the author's reading of the normal pipeline's answers. Its 6 query logs (Q1 and Q2, 3 each), with 2 unrelated ones, are kept locally in `plans-local/baseline-query-logs.json` (not committed).
- **After:** `scripts/experiments/version_baseline.py current|stale --runs 3` on the versioned store. Raw output: `plans-local/after-current.json` and `plans-local/after-stale.json` (not committed). Scores are the author's, confirmed against the V1.3 text.
- **After cleanup:** the same script and modes after the reload. Raw output: `plans-local/after-cleanup-current.json` and `plans-local/after-cleanup-stale.json`.
  - The runs made before each fix are kept as `*-before-rerank-fix.*` and `*-before-citation-fix.*`.
  - Citation labels per answer: `plans-local/citation-check.txt`.
  - The rerank comparison: `plans-local/rerank-header-check.txt`.
  - Reload and checks: `plans-local/reload-slice-f.log`, `plans-local/reload-checks.txt`.
  - The eval run: `plans-local/eval-run-slice-f.json`.
  - Scores proposed by the assistant and confirmed by the author against the V1.3 text. All files are local and not committed.

## Not yet shown

- 3 runs per cell, one document pair, two questions, one model.
- The before traces of the experiment runs were not kept, so the before rows rest on the author's notes, not on saved output.
- Version labels are taken from the cover where it parses as text, and from the file name for the three VSE covers (see `corpus.yaml`). Nothing in the pipeline derives them.
- The other real cases are untested: an in-place change under the same file name (EKZ), and the archive history.
- Tone varies between batches of runs that have the same top 8 (stale Q1 across stages; current Q1 just before and after the citation fix). Three runs per cell do not separate a prompt effect from sampling.
- Answers were checked by the author against the source text, not by a licensed expert.
