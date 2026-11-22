"""Load the eval questions from a YAML file into the store.

Usage:
    python scripts/load_eval_questions.py [--file eval/questions.yaml]

File format:

    questions:
      - key: bkw-steuerdraht-2-doppeltarif      # lowercase words joined by hyphens; never changes
        question: "..."
        question_type: answerable                # answerable | unanswerable
        case_type: changed_between_versions     # standard | changed_between_versions |
                                                 # not_covered | unknown_scope
        expected_answer: "..."
        sources:                                 # the versions the expected answer was written from
          - {source_key: bkw-vorgaben-niederspannung, version_label: "Version: V1.3, Gültig ab 21.05.2025"}
        facts:                                   # one fact per row, judged one by one
          - "..."

Each source is named by its key and the version label as printed; the loader stores the
fingerprint of that version. Every problem is reported by question key before anything
is written. Once a question has eval results, its question and facts cannot change.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from app.models.database import DatabaseClient

DEFAULT_FILE = Path(__file__).resolve().parent.parent / "eval" / "questions.yaml"
KEY_FORMAT = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")  # as checked by eval_questions
QUESTION_TYPES = ("answerable", "unanswerable")       # as checked by eval_questions
CASE_TYPES = ("standard", "changed_between_versions", "not_covered", "unknown_scope")


def read_questions(path: Path, db) -> list[dict]:
    """The questions in path with their sources resolved; raises ValueError listing every problem."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    questions: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(data.get("questions") or [], 1):
        key = raw.get("key") or f"question {i}"
        before = len(problems)
        if not KEY_FORMAT.match(str(key)):
            problems.append(f"{key}: key must be lowercase letters and digits joined by hyphens")
        elif key in seen:
            problems.append(f"{key}: listed twice")
        if not raw.get("question"):
            problems.append(f"{key}: missing question")
        if raw.get("question_type") not in QUESTION_TYPES:
            problems.append(f"{key}: question_type must be one of {', '.join(QUESTION_TYPES)}")
        if raw.get("case_type") not in CASE_TYPES:
            problems.append(f"{key}: case_type must be one of {', '.join(CASE_TYPES)}")
        sources = []
        for s in raw.get("sources") or []:
            version = db.find_version(s.get("source_key"), s.get("version_label"))
            if not version or not version.get("text_sha256"):
                problems.append(f"{key}: no version of {s.get('source_key')} labelled {s.get('version_label')!r}")
                continue
            sources.append({"source_key": s["source_key"], "written_from_text_sha256": version["text_sha256"]})
        if len(problems) == before:
            seen.add(key)
            questions.append({
                "key": key, "question": raw["question"], "question_type": raw["question_type"],
                "case_type": raw["case_type"], "expected_answer": raw.get("expected_answer"),
                "sources": sources, "facts": [str(f) for f in raw.get("facts") or []],
            })
    if problems:
        raise ValueError("eval questions have problems:\n  " + "\n  ".join(problems))
    return questions


def main(argv: list[str] | None = None, db=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = ap.parse_args(argv)
    if not args.file.is_file():
        print(f"no eval question file at {args.file}")
        return 2
    db = db or DatabaseClient()
    try:
        questions = read_questions(args.file, db)
    except ValueError as e:
        print(e)
        return 2
    for q in questions:
        db.save_eval_question(q)
    print(f"saved {len(questions)} eval questions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
