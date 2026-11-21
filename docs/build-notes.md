# Lighthouse: build notes

Working notes for the build. Not for the README.

## Do first

- Reproduce the failure before designing further: load both versions of one document into the existing pipeline, ask a question whose answer differs, see what comes back. Everything else assumes this failure happens.

## Decisions taken

- A clear new version replaces the old one automatically. A person only handles what the system cannot settle.
- Old versions are retired, not deleted.
- A source is an address plus the page that links to it. Watching the file alone misses a new version under a new name.
- Compare content, never names or dates.
- A check that could not run is a failure, never "no change".
- Every source carries the date a person last confirmed it. Past a set age it is flagged.
- Fetching and change detection come from existing tools. The project starts where a monitor stops.
- Anything derived from a document records the version it came from: stored text, answers, test questions, evaluation runs.
- Start simple, change one thing at a time, and log each change: what, why (which failures), expected, measured, kept or not.

## Real cases to test against

- BKW requirements: V1.3 published under a new file name, V1.2 still online and unchanged at its old address. Both files in hand.
- EKZ special provisions: content changed while the file name stayed the same and still carries the earlier date.
- EKZ in the web archive: 34 files with 52 distinct captured contents, and 21 versions of the page that lists them (2021 to 2026). Several in-place changes and several renames. Capture dates are not change dates, and a different fingerprint can be cosmetic.
- BKW in the web archive: almost nothing.
- Controlled edits to a document, where the exact change is known, for precise counts.

## Open questions, to settle by testing

- How to recognise that a new document replaces a held one: file name, title, version statement on the first page, similarity of content.
- After a change: check which test questions point at changed text, re-run the questions, or both. Compare by section text, not by stored pieces, and by scored facts, not by wording.
- Whether a capable model picks the newer version unaided when both are found.
- Whole documents or cut pieces as model input.
- Whether long documents crowd out short ones in search, and whether searching per level of authority helps.
- A document can apply to several scopes (BE/JU/SO rules cover many operators); one scope field per document cannot express that.
- issuer, level and source_url have no column yet; they live only in corpus.yaml until the store is remodelled.

## What the surrounding system must provide

- Every stored piece knows its source and version.
- Retired versions can be excluded from use.
- Outputs record which versions they used.
- Test cases can be run on demand.
- Flags reach a person.

## Ideas borrowed from existing products

- A tripwire: if a large share of content changes at once, send it to review. It usually means a redesign or a fault.
- Mark old content as retired before removing it, so a replacement can be rolled back.
- Named measures: delay between a source changing and the knowledge catching up; share of questions answered from an outdated document.

## The bigger system, for later

- Scope: use only documents that apply to the question, never borrow across scopes, say so when the answer depends on context that was not given.
- Authority: where documents conflict, the higher one wins and the answer says so.
- Cite document, version and location for every statement.
- Decline when the sources do not settle the question.
- Measure correct, declined and wrong on a golden set, including on a scope not used in development.
- A new scope needs new data, not new code.
