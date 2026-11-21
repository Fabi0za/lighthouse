# Baseline: superseded versions

How the assistant answers when a document has been replaced by a newer version: first measured before any versioning logic existed ("before"), then again on the versioned store ("after", see [the design](plans/2026-11-21-versioned-store-design.md)).

## Setup

- **Corpus:** 11 documents, 1183 chunks, loaded from `corpus.yaml`. National VSE recommendations have priority 1; BKW and EKZ operator rules have priority 2.
- **Document pair:** BKW *Vorgaben an Niederspannungs-Installationen* V1.2 (valid from 01.03.2025) and V1.3 (valid from 21.05.2025, cover reads "Ersetzt V1.2"). 27 chunks each.
- **Difference:** in section 4, *Steuern oder Sperren von Anlagen*:
  - V1.2 says only that new installations and self-consumption systems are no longer controlled or blocked.
  - V1.3 narrows this to audio-frequency ripple-control receivers and requires a spare mounting slot with a control circuit breaker, plus sealable terminals for control wires 1 and 0. It also makes wire 2 (dual tariff) optional.
- **Pipeline:** `embed-v5.0-pro` (1536 dimensions), vector search top-40, Cohere `rerank-v3.5` top-8, `claude-sonnet-5-5` with the existing prompt. Sampling is not fixed, so each question was run 3 times.
- **Questions:**
  - Q1: "Was muss bei Neuinstallationen im Netz der BKW für Steuerlösungen vorbereitet werden?"
  - Q2: "Muss bei Neuinstallationen im Netz der BKW ein Steuerdraht 2 für den Doppeltarif vorgesehen werden?"
- **Scoring:** the author compared each answer and its citations against the V1.3 text. The pipeline's own confidence field is not used, because it recognises only an English "Confidence:" line.

## Cases

| Case | Store | What the model sees |
|---|---|---|
| **Stale, before** | Both versions, unversioned | All V1.3 chunks removed from the top-40 before reranking, as if the store held only the old version. |
| **Both, labelled, before** | Both versions, unversioned | The normal pipeline. Titles carry version and validity date, taken from `corpus.yaml`. |
| **Both, unlabelled, before** | Both versions, unversioned | The same top-8 as the labelled case, but V1.2 and V1.3 both titled "Vorgaben an Niederspannungs-Installationen im Verteilnetz der BKW", in the source label and in the chunk prefix. Text inside the documents is unchanged. |
| **Current, after** | Versioned: V1.3 current, V1.2 retired (chunks deleted) | The normal pipeline. Only current versions are searchable. |
| **Stale, after** | Versioned, as above | V1.2's chunks rebuilt in memory from its retained parsed output and scored against the query; the top-40 is the top-40 of current chunks plus these, minus V1.3. This is the same set as *Stale, before*. Nothing is written to the store. |

The unlabelled case has no "after": with one current version per source, two versions can no longer reach the model together.

In every case the reranked top-8 was identical across the 3 runs of a question.

## Results

3 runs per cell.

| Case | Q | Answer follows | All V1.3 facts | Uses V1.2 text as valid | Notes two versions | Treats difference as conflict |
|---|---|---|---|---|---|---|
| Stale, before | Q1 | V1.2 | 0/3 | 3/3 | – (0/3 suspect a newer version) | – |
| Stale, **after** | Q1 | V1.2 | 0/3 | 3/3 | – (0/3 suspect a newer version) | – |
| Stale, before | Q2 | none: "not in the sources, probably not needed" | 0/3 | 3/3 | – (0/3 suspect a newer version) | – |
| Stale, **after** | Q2 | none: "not stated explicitly; tends towards not needed" | 0/3 | 3/3 | – (0/3 suspect a newer version) | – |
| Both, labelled, before | Q1 | V1.3 | 3/3 | 1/3 | 3/3 | 0/3 |
| **Current, after** | Q1 | V1.3 | 3/3 | 0/3 | – (only V1.3 reached the model) | 0/3 |
| Both, labelled, before | Q2 | V1.3 | 3/3 | 2/3 | 3/3 | 0/3 |
| **Current, after** | Q2 | V1.3 | 3/3 | 0/3 | – | 0/3 |
| Both, unlabelled, before | Q1 | V1.3 and V1.2 merged | 3/3 | 3/3 | 0/3 | 0/3 |
| Both, unlabelled, before | Q2 | V1.3 and V1.2 merged | 3/3 | 3/3 | 0/3 | 0/3 |

**Before:**

- **Stale:** the answer is wrong for Q1. It states V1.2's blanket rule as current, and nothing signals that a newer version exists.
- **Labelled:** the model picks V1.3 by the version and date in the titles. It still cites V1.2 in every run and calls the two versions compatible. That is wrong for Q1, where V1.2 alone would mean nothing needs preparing. V1.3's own "Ersetzt V1.2" chunk was never in the top-8.
- **Unlabelled:** the model can no longer tell that there are two versions, and presents both sentences as one document's rules.

**After:**

- **Current:** V1.2 is in neither the top-40 nor the top-8 in any of the 6 runs. Every answer contains all V1.3 facts and none uses V1.2 text. For each run, `query_log_documents` lists V1.3 and other documents, never V1.2.
- **Stale:** unchanged in substance: 0/6 contain a V1.3 fact and 0/6 suspect a newer version. The retrieval matches the before run: 26 (Q1) and 30 (Q2) chunks left in the top-40 after V1.3 is removed. The top-8 is V1.2 sections 4, 1, 6.1 and 6.6 plus Notfallsteuerung for Q1, and V1.2 sections 4, 1, 2 and 6.6 ×2 plus Notfallsteuerung for Q2.
- **Stale Q1 tone, unexplained:** before, all 3 answers noticed the tension between "no control" and the Notfallsteuerung document and resolved it by their own interpretation. After, all 3 call it an apparent contradiction and recommend clarifying with BKW, at medium confidence. One answer reasons about "Typ operator, Priorität 2", so the prompt label change below is a plausible cause, not a proven one.
- What the store fixes is the labelled and unlabelled failure: an old version cannot reach the model. The stale failure is unchanged, as the design expects. Against it the store offers flags, the confirmation date, and the list of answers that saw a retired version.

## Differences between before and after, other than the store

- **Prompt labels:** each source line in the prompt shows the level (`national`, `operator`) where it showed the old type string (`general_regulation`, `grid_provider_rule`). The format `(Type: …, Priority: …)` and the priorities are unchanged.
- **Identical text:** the reload read the parser output saved from the before store (`--parsed-cache`) instead of parsing again, so the parsed text and the chunks are the same. 1183 chunks before, 1156 after (V1.2's 27 deleted on retirement). The 2 V1.2 chunks recorded in earlier query logs match their rebuilt versions exactly.
- **Embeddings:** all chunks were embedded again on reload with the same model and settings. The top-40 counts and top-8 makeup above match the before run; embedding values were not compared.

## Where the numbers come from

- **Before, stale and unlabelled:** the author's reading of the runs of `scripts/experiments/version_baseline.py` (modes `stale`, `nolabels`) at the commits before the versioned store. The raw run output was not kept. The retrieval counts and top-8 makeup for the stale case survive only in a local, unpublished draft of the changelog from the same day.
- **Before, labelled:** the author's reading of the normal pipeline's answers. Its 6 query logs (Q1 and Q2, 3 each), with 2 unrelated ones, are kept locally in `plans-local/baseline-query-logs.json` (not committed).
- **After:** `scripts/experiments/version_baseline.py current|stale --runs 3` on the versioned store. The raw output is kept locally in `plans-local/after-current.json` and `plans-local/after-stale.json` (not committed). Scores are the author's, confirmed against the V1.3 text.

## Not yet shown

- 3 runs per cell, one document pair, two questions, one model.
- The before traces of the experiment runs were not kept, so the before rows rest on the author's notes, not on saved output.
- Version labels were written by hand in `corpus.yaml`; nothing in the pipeline derives them.
- The other real cases are untested: an in-place change under the same file name (EKZ), and the archive history.
- Answers were checked by the author against the source text, not by a licensed expert.
