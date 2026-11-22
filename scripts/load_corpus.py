"""Load every source and version listed in corpus.yaml.

Usage:
    python scripts/load_corpus.py [--corpus corpus.yaml] [--dry-run]

Versions are identified by fingerprint, not by path (app/ingestion/versions.py):
a file whose bytes are already stored is skipped, a file with new bytes but the
same text is dismissed as repackaging, and new content is promoted to current,
retiring the previous version. Each source's versions are loaded oldest first,
as listed; after a failure, later versions of that source are not attempted,
so an older version can never be promoted over a newer one.

Sources are identified by their key. Each run saves every source's level and scopes
as listed in corpus.yaml and says what changed.

With --parsed-cache DIR, a file DIR/<pdf sha256>.json is used as the parser output
instead of calling the parser; the output says which versions came from the cache.
"""
from __future__ import annotations

import argparse
import asyncio
import re
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
from app.settings_rows import indexing_settings_row

SOURCE_FIELDS = ("key", "level")
KEY_FORMAT = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")  # as checked by the sources table
WORD_KEY_FORMAT = re.compile(r"^[a-z]+(-[a-z]+)*$")   # as checked by the levels and scopes tables
VERSION_FIELDS = ("path", "title")


@dataclass
class CorpusVersion:
    path: str
    title: str
    label: str | None
    obtained_from: str | None
    max_pages: int | None


@dataclass
class CorpusLevel:
    key: str
    rank: int
    requires_scope: bool


@dataclass
class CorpusScope:
    key: str
    name: str


@dataclass
class CorpusSource:
    key: str
    level: str
    scopes: list[str]
    watch_address: str | None
    versions: list[CorpusVersion] = field(default_factory=list)


@dataclass
class Corpus:
    levels: list[CorpusLevel]
    scopes: list[CorpusScope]
    sources: list[CorpusSource]


def _read_levels(raw_levels, problems: list[str]) -> list[CorpusLevel]:
    levels: list[CorpusLevel] = []
    ranks: set[int] = set()
    for raw in raw_levels or []:
        key, rank = raw.get("key"), raw.get("rank")
        label = f"level {key}"
        ok = True
        if not key or not WORD_KEY_FORMAT.match(str(key)):
            problems.append(f"{label}: key must be lowercase words joined by hyphens")
            ok = False
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
            problems.append(f"{label}: rank must be a positive integer")
            ok = False
        elif rank in ranks:
            problems.append(f"{label}: rank {rank} used twice")
            ok = False
        if ok:
            ranks.add(rank)
            levels.append(CorpusLevel(key, rank, bool(raw.get("requires_scope", False))))
    return levels


def _read_scopes(raw_scopes, problems: list[str]) -> list[CorpusScope]:
    scopes: list[CorpusScope] = []
    for raw in raw_scopes or []:
        key, name = raw.get("key"), raw.get("name")
        label = f"scope {key}"
        if not key or not WORD_KEY_FORMAT.match(str(key)):
            problems.append(f"{label}: key must be lowercase words joined by hyphens")
        elif not name:
            problems.append(f"{label}: missing name")
        else:
            scopes.append(CorpusScope(key, name))
    return scopes


def load_corpus(corpus_path: Path, repo_root: Path) -> Corpus:
    """Read and validate corpus.yaml. Raises ValueError listing every problem found."""
    data = yaml.safe_load(corpus_path.read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    levels = {lv.key: lv for lv in _read_levels(data.get("levels"), problems)}
    scopes = _read_scopes(data.get("scopes"), problems)
    scope_keys = {sc.key for sc in scopes}
    sources: list[CorpusSource] = []
    seen_keys: set[str] = set()
    seen_paths: set[str] = set()

    for i, raw in enumerate(data.get("sources") or [], 1):
        label = raw.get("key") or f"source {i}"
        missing = [f for f in SOURCE_FIELDS if not raw.get(f)]
        if missing:
            problems.append(f"{label}: missing {', '.join(missing)}")
            continue
        if not KEY_FORMAT.match(str(raw["key"])):
            problems.append(f"{label}: key must be lowercase letters and digits joined by hyphens")
            continue
        level = levels.get(raw["level"])
        if level is None:
            problems.append(f"{label}: unknown level {raw['level']!r}")
        source_scopes = list(raw.get("scopes") or [])
        unknown = [sc for sc in source_scopes if sc not in scope_keys]
        for sc in unknown:
            problems.append(f"{label}: unknown scope {sc!r}")
        if level is None or unknown:
            continue
        if level.requires_scope and not source_scopes:
            problems.append(f"{label}: level {level.key!r} needs a scope")
            continue
        if raw["key"] in seen_keys:
            problems.append(f"{label}: source key listed twice")
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
                path=rv["path"], title=rv["title"], label=rv.get("label") or None,
                obtained_from=rv.get("obtained_from") or None, max_pages=max_pages,
            ))

        seen_keys.add(raw["key"])
        sources.append(CorpusSource(
            key=raw["key"], level=raw["level"], scopes=source_scopes,
            watch_address=raw.get("watch_address") or None, versions=versions,
        ))

    if problems:
        raise ValueError("corpus.yaml has problems:\n  " + "\n  ".join(problems))
    return Corpus(levels=list(levels.values()), scopes=scopes, sources=sources)


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


def report_source(stored: dict | None, s: CorpusSource) -> None:
    """Say whether saving s adds the source or changes its level or scopes."""
    if stored is None:
        print(f"added source {s.key!r}")
        return
    notes = []
    if stored["level"] != s.level:
        notes.append(f"level {stored['level']!r} -> {s.level!r}")
    if sorted(stored["scopes"]) != sorted(s.scopes):
        notes.append(f"scopes {sorted(stored['scopes'])} -> {sorted(s.scopes)}")
    if stored.get("watch_address") != s.watch_address:
        notes.append(f"watch address {stored.get('watch_address')!r} -> {s.watch_address!r} (reconfirmed)")
    if notes:
        print(f"updated source {s.key!r}: " + "; ".join(notes))


async def load_all(corpus: Corpus, repo_root, db, parser, chunker, embedder, *,
                   indexing_settings: dict, load=None, parsed_cache: Path | None = None) -> dict[str, int]:
    """Save indexing settings, levels, scopes and sources, then load every version in order.

    Returns a count per action, plus 'failed' and 'not attempted'. Raises ValueError,
    before writing anything, if the store holds a source that corpus.yaml no longer
    lists (a renamed key would otherwise leave the old source current and searchable),
    or if current versions were loaded under other indexing settings (chunks embedded
    differently cannot share one search; changing settings needs a fresh store).
    """
    load = load or load_version
    listed = {s.key for s in corpus.sources}
    unlisted = sorted(set(db.list_source_keys()) - listed)
    if unlisted:
        raise ValueError(
            "stored sources not in corpus.yaml (a source key never changes; "
            f"restore them in corpus.yaml): {', '.join(unlisted)}"
        )
    key = indexing_settings["key"]
    other = [k for k in db.current_indexing_settings_keys() if k != key]
    if other:
        raise ValueError(
            f"current versions use indexing settings {', '.join(other)}, the configuration gives {key}; "
            "changing indexing settings needs a reload into a fresh store"
        )
    db.save_indexing_settings(indexing_settings)
    db.save_levels([{"key": lv.key, "rank": lv.rank, "requires_scope": lv.requires_scope}
                    for lv in corpus.levels])
    db.save_scopes([{"key": sc.key, "name": sc.name} for sc in corpus.scopes])
    counts: Counter[str] = Counter()
    for s in corpus.sources:
        stored = db.find_source(s.key)
        try:
            db.save_source(s.key, s.level, s.scopes, s.watch_address)
        except Exception as e:  # noqa: BLE001 - report, then skip this source's versions
            print(f"{s.key}: FAILED to save source: {type(e).__name__}: {e}")
            counts["failed"] += 1
            if s.versions:
                counts["not attempted"] += len(s.versions)
            continue
        report_source(stored, s)
        for k, v in enumerate(s.versions):
            cached = cached_output(parsed_cache, file_sha256(repo_root / v.path))
            print(f"{v.path} ..." + (f" (parser output from cache: {cached.name})" if cached else ""),
                  flush=True)
            try:
                action, doc_id, retired_seen_by = await load(
                    db, s.key, repo_root / v.path, v.title, v.obtained_from,
                    parser, chunker, embedder, version_label=v.label, max_pages=v.max_pages,
                    listed_path=v.path, indexing_settings_key=key,
                    parsed_cache=parsed_cache,
                )
            except Exception as e:  # noqa: BLE001 - report, then skip this source's later versions
                print(f"  FAILED: {type(e).__name__}: {e}")
                counts["failed"] += 1
                rest = len(s.versions) - k - 1
                if rest:
                    print(f"  {rest} later version(s) of {s.key!r} not attempted")
                    counts["not attempted"] += rest
                break
            print(f"  {action} ({doc_id})")
            if retired_seen_by is not None:
                print(f"  the version it retired was seen by {retired_seen_by} earlier answers"
                      + (" (scripts/answers.py saw lists them)" if retired_seen_by else ""))
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
        corpus = load_corpus(corpus_path, repo_root)
    except ValueError as e:
        print(e)
        return 2

    db = DatabaseClient()
    if args.dry_run:
        known = {d["file_sha256"] for d in db.list_versions() if d.get("status") not in ("loading", "failed")}
        for s, v, action in plan(corpus.sources, known, repo_root, parsed_cache=args.parsed_cache):
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
        counts = await load_all(corpus, repo_root, db, parser, chunker, embedder,
                                indexing_settings=indexing_settings_row(settings),
                                parsed_cache=args.parsed_cache)
    except ValueError as e:
        print(e)
        return 2
    finally:
        await parser.close()
        await embedder.close()

    print("\nDone: " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items())))
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
