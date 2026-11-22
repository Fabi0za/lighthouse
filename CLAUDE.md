# Repository rules

The standard for schema, code and docs is in `docs/conventions.md`.

This repository is public-facing. Keep history and files clean.

## Never commit

- `.env` or any API key, token or secret
- `data/` or any PDF
- Supabase project IDs or project URLs
- Local paths (home directories, temp or scratch directories)

## Commits

- Conventional prefix (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`), imperative subject under 72 characters.
- The body says why the change was made and what evidence supports it.
- No references to chat steps or assistant prompts; describe the change, not who asked for it.
- One logical change per commit.
- Tests pass before every commit, including the database tests:
  `TEST_DATABASE_URL=postgresql://localhost/postgres .venv/bin/pytest -q`
  (local Postgres 18 with pgvector: `brew services start postgresql@18`; see README, Tests).
  Without the variable the database tests are skipped, which does not count as passing.

## Changelog

Every behaviour change gets an entry in `docs/CHANGELOG.md`, two lines at most:

```
- **What changed.** Why.
  Evidence: test, measurement or observed output.
```

Measurements and experiment results go in `docs/baseline.md`, not in the changelog.

## Experiments

- Every experiment run saves its raw output under `plans-local/` (not committed).
- Docs that report a number say where it came from: the script and mode, and the local file holding the raw output.

## Pushing

- Never push without being asked.
- Before any push, scan the commits to be pushed for secrets (keys, `.env` values, project IDs, local paths), then list the commits and the scan result for approval.
