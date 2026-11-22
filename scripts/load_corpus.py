"""Load every source and version listed in corpus.yaml.

Usage:
    python scripts/load_corpus.py [--corpus corpus.yaml] [--dry-run]

Versions are identified by fingerprint, not by path (app/ingestion/versions.py):
a file whose bytes are already stored is skipped, a file with new bytes but the
same text is dismissed as repackaging, and new content is promoted to current,
retiring the previous version. Each source's versions are loaded oldest first,
as listed; after a failure, later versions of that source are not attempted,
so an older version can never be promoted over a newer one.

Sources are matched by title: renaming a source title creates a new source. For a
source that already exists, issuer, level, listing address and scopes are updated
to match corpus.yaml, and the output says what changed.

With --parsed-cache DIR, a file DIR/<pdf sha256>.json is used as the parser output
instead of calling the parser; the output says which versions came from the cache.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import get_settings
from app.ingestion.chunker import Chunker
from app.ingestion.embedder import Embedder
from app.ingestion.fingerprint import file_sha256
from app.ingestion.parser import ReductoParser
from app.ingestion.versions import cached_output, first_pages, load_version  # noqa: F401 - first_pages re-exported
from app.models.database import DatabaseClient

AUTHORITY_RANK = {"national": 1, "operator": 2}
SOURCE_FIELDS = ("title", "issuer", "level")
VERSION_FIELDS = ("path", "title")


@dataclass
class CorpusVersion:
    path: str
    title: str
    address: str | None
    max_pages: int | None


@dataclass
class CorpusSource:
    title: str
    issuer: str
    level: str
    scopes: list[str]
    listing_address: str | None
    versions: list[CorpusVersion] = field(default_factory=list)

    @property
    def authority_rank(self) -> int:
        return AUTHORITY_RANK[self.level]


def load_corpus(corpus_path: Path, repo_root: Path) -> list[CorpusSource]:
    """Read and validate corpus.yaml. Raises ValueError listing every problem found."""
    data = yaml.safe_load(corpus_path.read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    sources: list[CorpusSource] = []
    seen_titles: set[str] = set()
    seen_paths: set[str] = set()

    for i, raw in enumerate(data.get("sources") or [], 1):
        label = raw.get("title") or f"source {i}"
        missing = [f for f in SOURCE_FIELDS if not raw.get(f)]
        if missing:
            problems.append(f"{label}: missing {', '.join(missing)}")
            continue
        if raw["level"] not in AUTHORITY_RANK:
            problems.append(f"{label}: level must be one of {sorted(AUTHORITY_RANK)}")
            continue
        scopes = list(raw.get("scopes") or [])
        if raw["level"] == "operator" and not scopes:
            problems.append(f"{label}: operator sources need scopes")
            continue
        if raw["title"] in seen_titles:
            problems.append(f"{label}: source title listed twice")
            continue
        raw_versions = raw.get("versions") or []
        if not raw_versions:
            problems.append(f"{label}: no versions")
            continue

        versions: list[CorpusVersion] = []
        for j, rv in enumerate(raw_versions, 1):
            vlabel = rv.get("path") or f"{label} version {j}"
            vmissing = [f for f in VERSION_FIELDS if not rv.get(f)]
            if vmissing:
                problems.append(f"{vlabel}: missing {', '.join(vmissing)}")
                continue
            if rv["path"] in seen_paths:
                problems.append(f"{vlabel}: listed twice")
                continue
            if not (repo_root / rv["path"]).is_file():
                problems.append(f"{vlabel}: file not found")
                continue
            max_pages = rv.get("max_pages")
            if max_pages is not None and (not isinstance(max_pages, int) or max_pages < 1):
                problems.append(f"{vlabel}: max_pages must be a positive integer")
                continue
            seen_paths.add(rv["path"])
            versions.append(CorpusVersion(
                path=rv["path"], title=rv["title"],
                address=rv.get("address") or None, max_pages=max_pages,
            ))

        seen_titles.add(raw["title"])
        sources.append(CorpusSource(
            title=raw["title"], issuer=raw["issuer"], level=raw["level"], scopes=scopes,
            listing_address=raw.get("listing_address") or None, versions=versions,
        ))

    if problems:
        raise ValueError("corpus.yaml has problems:\n  " + "\n  ".join(problems))
    return sources


def plan(
    sources: list[CorpusSource], known_file_hashes: set[str], repo_root: Path,
    parsed_cache: Path | None = None,
) -> list[tuple[CorpusSource, CorpusVersion, str]]:
    """For --dry-run, per version: 'skip' (its bytes are already a stored version),
    'cache' (to load, parser output read from the cache) or 'parse' (to load, parsed).

    Whether a load ends as promoted or dismissed is only known after reading the text.
    """
    def action(v: CorpusVersion) -> str:
        h = file_sha256(repo_root / v.path)
        if h in known_file_hashes:
            return "skip"
        return "cache" if cached_output(parsed_cache, h) else "parse"

    return [(s, v, action(v)) for s in sources for v in s.versions]


def sync_source(db, stored: dict, s: CorpusSource) -> None:
    """Bring a stored source's fields and scopes in line with corpus.yaml, and say what changed."""
    wanted = {"issuer": s.issuer, "level": s.level, "authority_rank": s.authority_rank,
              "listing_address": s.listing_address}
    changed = {k: v for k, v in wanted.items() if stored.get(k) != v}
    notes = [f"{k} {stored.get(k)!r} -> {v!r}" for k, v in changed.items()]
    if changed:
        db.update_source(stored["id"], changed)
    old_scopes, new_scopes = sorted(db.get_scopes(stored["id"])), sorted(s.scopes)
    if old_scopes != new_scopes:
        db.set_scopes(stored["id"], new_scopes)
        notes.append(f"scopes {old_scopes} -> {new_scopes}")
    if notes:
        print(f"updated source {s.title!r}: " + "; ".join(notes))


async def load_all(sources, repo_root, db, parser, chunker, embedder, load=None,
                   parsed_cache: Path | None = None) -> dict[str, int]:
    """Load every version in order. Returns a count per action, plus 'failed' and 'not attempted'."""
    load = load or load_version
    counts: Counter[str] = Counter()
    for s in sources:
        source = db.find_source(s.title)
        if source:
            sync_source(db, source, s)
        else:
            source = db.insert_source(
                s.title, s.issuer, s.level, s.authority_rank, s.scopes, None, s.listing_address
            )
        for k, v in enumerate(s.versions):
            cached = cached_output(parsed_cache, file_sha256(repo_root / v.path))
            print(f"{v.path} ..." + (f" (parser output from cache: {cached.name})" if cached else ""),
                  flush=True)
            try:
                action, doc_id = await load(
                    db, source, repo_root / v.path, v.title, v.address,
                    parser, chunker, embedder, max_pages=v.max_pages, stored_path=v.path,
                    parsed_cache=parsed_cache,
                )
            except Exception as e:  # noqa: BLE001 - report, then skip this source's later versions
                print(f"  FAILED: {type(e).__name__}: {e}")
                counts["failed"] += 1
                rest = len(s.versions) - k - 1
                if rest:
                    print(f"  {rest} later version(s) of {s.title!r} not attempted")
                    counts["not attempted"] += rest
                break
            print(f"  {action} ({doc_id})")
            counts[action] += 1
    return dict(counts)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="corpus.yaml")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    ap.add_argument("--parsed-cache", type=Path, default=None,
                    help="directory of <pdf sha256>.json parser outputs to use instead of parsing")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    corpus_path = Path(args.corpus)
    if not corpus_path.is_absolute():
        corpus_path = repo_root / corpus_path

    try:
        sources = load_corpus(corpus_path, repo_root)
    except ValueError as e:
        print(e)
        return 2

    db = DatabaseClient()
    if args.dry_run:
        known = {d["file_sha256"] for d in db.list_versions() if d.get("status") != "pending"}
        for s, v, action in plan(sources, known, repo_root, parsed_cache=args.parsed_cache):
            pages = f", first {v.max_pages} pages" if v.max_pages else ""
            print(f"{action:5}  {v.path}  [{s.level}/{','.join(s.scopes) or '-'}{pages}]")
        return 0

    settings = get_settings()
    parser = ReductoParser(api_key=settings.reducto_api_key)
    chunker = Chunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    embedder = Embedder(
        api_key=settings.cohere_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    try:
        counts = await load_all(sources, repo_root, db, parser, chunker, embedder,
                                parsed_cache=args.parsed_cache)
    finally:
        await parser.close()
        await embedder.close()

    print("\nDone: " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items())))
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
