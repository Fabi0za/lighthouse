# Changelog

Each entry: what changed and why, then the evidence.

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
