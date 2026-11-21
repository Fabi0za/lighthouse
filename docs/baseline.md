# Baseline: superseded versions

How the existing assistant answers when a document has been replaced by a newer version. Measured before any versioning logic exists.

## Setup

- **Corpus:** 11 documents, 1183 chunks, loaded from `corpus.yaml`. National VSE recommendations have priority 1; BKW and EKZ operator rules have priority 2.
- **Document pair:** BKW *Vorgaben an Niederspannungs-Installationen* V1.2 (valid from 01.03.2025) and V1.3 (valid from 21.05.2025, cover reads "Ersetzt V1.2"). Both are loaded, both have priority 2, 27 chunks each.
- **Difference:** in section 4, *Steuern oder Sperren von Anlagen*:
  - V1.2 says only that new installations and self-consumption systems are no longer controlled or blocked.
  - V1.3 narrows this to audio-frequency ripple-control receivers and requires a spare mounting slot with a control circuit breaker, plus sealable terminals for control wires 1 and 0. It also makes wire 2 (dual tariff) optional.
- **Pipeline:** `embed-v5.0-pro` (1536 dimensions), vector search top-40, Cohere `rerank-v3.5` top-8, `claude-sonnet-5-5` with the existing prompt. Sampling is not fixed, so each question was run 3 times.
- **Questions:**
  - Q1: "Was muss bei Neuinstallationen im Netz der BKW für Steuerlösungen vorbereitet werden?"
  - Q2: "Muss bei Neuinstallationen im Netz der BKW ein Steuerdraht 2 für den Doppeltarif vorgesehen werden?"
- **Scoring:** the author compared each answer and its citations against the V1.3 text. The pipeline's own confidence field is not used, because it recognises only an English "Confidence:" line.

## Cases

| Case | What the model sees |
|---|---|
| **Both, labelled** | The normal pipeline. Titles carry version and validity date, taken from `corpus.yaml`. |

The reranked top-8 was identical across the 3 runs of each question.

## Results

3 runs per cell.

| Case | Q | Answer follows | All V1.3 facts | Uses V1.2 text as valid | Notes two versions | Treats difference as conflict |
|---|---|---|---|---|---|---|
| Labelled | Q1 | V1.3 | 3/3 | 1/3 | 3/3 | 0/3 |
| Labelled | Q2 | V1.3 | 3/3 | 2/3 | 3/3 | 0/3 |

- **Labelled:** the model picks V1.3 by the version and date in the titles. It still cites V1.2 in every run and calls the two versions compatible. That is wrong for Q1, where V1.2 alone would mean nothing needs preparing. V1.3's own "Ersetzt V1.2" chunk was never in the top-8.

## Not yet shown

- One document pair and two questions, 3 runs each, one model.
- Version labels were written by hand in `corpus.yaml`; nothing in the pipeline derives them.
- The stale case (only the old version stored) and an unlabelled case.
- The other real cases are untested: an in-place change under the same file name (EKZ), and the archive history.
- Answers were checked by the author against the source text, not by a licensed expert.
