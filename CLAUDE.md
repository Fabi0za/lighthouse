# Repository rules

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
- Tests pass before every commit: `pytest -q`.

## Changelog

Every behaviour change gets an entry in `docs/CHANGELOG.md`, two lines at most:

```
- **What changed.** Why.
  Evidence: test, measurement or observed output.
```

Measurements and experiment results go in `docs/baseline.md`, not in the changelog.

## Pushing

- Never push without being asked.
- Before any push, scan the commits to be pushed for secrets (keys, `.env` values, project IDs, local paths), then list the commits and the scan result for approval.
