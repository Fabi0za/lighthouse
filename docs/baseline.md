# Baseline: superseded versions

How the existing assistant answers when a document has been replaced by a newer version. Measured before any versioning logic exists.

## Setup

- **Corpus:** 11 documents, 1183 chunks, loaded from `corpus.yaml`. National VSE recommendations have priority 1; BKW and EKZ operator rules have priority 2.
- **Document pair:** BKW *Vorgaben an Niederspannungs-Installationen* V1.2 (valid from 01.03.2025) and V1.3 (valid from 21.05.2025, cover reads "Ersetzt V1.2"). Both are loaded, both have priority 2, 27 chunks each.
- **Difference:** in section 4, *Steuern oder Sperren von Anlagen*:
  - V1.2 says only that new installations and self-consumption systems are no longer controlled or blocked.
  - V1.3 narrows this to audio-frequency ripple-control receivers and requires a spare mounting slot with a control circuit breaker, plus sealable terminals for control wires 1 and 0. It also makes wire 2 (dual tariff) optional.
- **Pipeline:** `embed-v5.0-pro` (1536 dimensions), vector search top-40, Cohere `rerank-v3.5` top-8, `claude-sonnet-5-5` with the existing prompt.
- **Questions:**
  - Q1: "Was muss bei Neuinstallationen im Netz der BKW für Steuerlösungen vorbereitet werden?"
  - Q2: "Muss bei Neuinstallationen im Netz der BKW ein Steuerdraht 2 für den Doppeltarif vorgesehen werden?"

## Retrieval

Both versions loaded, normal pipeline.

| Q | Top-40 chunks: V1.2 / V1.3 / other | Rank of V1.3 section 4 | Rank of V1.2 section 4 |
|---|---|---|---|
| Q1 | 12 / 14 / 14 | 1 and 2 | 4 |
| Q2 | 10 / 10 / 20 | 1 and 2 | 5 |

The superseded section reaches the top-8 for both questions. Both versions have priority 2, so only the version and date in their titles, written in `corpus.yaml`, tell them apart.

## Answers

Not measured yet: answer generation fails with HTTP 400 because `llm.py` sends `temperature`, which `claude-sonnet-5-5` rejects.

## Not yet shown

- One document pair and two questions.
- Version labels were written by hand in `corpus.yaml`; nothing in the pipeline derives them.
