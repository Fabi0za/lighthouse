"""Answers recorded in the store.

Usage:
    python scripts/answers.py saw --source KEY --label LABEL
    python scripts/answers.py saw --version VERSION_ID

`saw` lists the answers that saw a version (it was among their top chunks), newest
first, with the other versions each answer saw. Use it after a version is retired
to see which earlier answers relied on it.
"""
from __future__ import annotations

import argparse
import sys

from app.models.database import DatabaseClient


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    saw = sub.add_parser("saw", help="answers that saw a version")
    which = saw.add_mutually_exclusive_group(required=True)
    which.add_argument("--version", help="version id")
    which.add_argument("--source", help="source key (with --label)")
    saw.add_argument("--label", help="version label as printed, with --source")
    return ap


def saw(db, version_id: str) -> None:
    rows = db.answers_that_saw(version_id)
    print(f"{len(rows)} answers saw this version")
    for r in rows:
        when = r["created_at"][:16].replace("T", " ")
        print(f"{when}  {r['question']}")
        if r["other_versions"]:
            print(f"    also saw: {', '.join(r['other_versions'])}")


def main(argv: list[str] | None = None, db=None) -> int:
    ap = _parser()
    args = ap.parse_args(argv)
    if args.source and not args.label:
        ap.error("--source needs --label")
    db = db or DatabaseClient()
    version_id = args.version
    if version_id is None:
        version = db.find_version(args.source, args.label)
        if version is None:
            print(f"no version of {args.source} labelled {args.label!r}")
            return 2
        version_id = version["id"]
    saw(db, version_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
