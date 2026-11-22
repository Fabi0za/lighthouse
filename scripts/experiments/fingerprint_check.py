"""Compare the old and new text fingerprint rule on cached parser outputs. Changes nothing.

Old rule (until FINGERPRINT_RULE 1): the extracted sections' content, normalised and joined;
headings and blocks under 10 characters were left out, page headers, footers and figures
were in. New rule: app/ingestion/fingerprint.py.

Usage:
    python scripts/experiments/fingerprint_check.py [--corpus corpus.yaml] [--cache plans-local/parsed]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import yaml

from app.ingestion.fingerprint import EXCLUDED_BLOCKS, file_sha256, text_sha256
from app.ingestion.parser import ReductoParser


def old_text_sha256(sections: list[dict]) -> str:
    norm = lambda s: re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()  # noqa: E731
    return hashlib.sha256("\n".join(norm(s.get("content", "")) for s in sections).encode("utf-8")).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.yaml")
    ap.add_argument("--cache", default="plans-local/parsed")
    args = ap.parse_args()
    parser = ReductoParser(api_key="unused")  # only _extract_sections is used; no API call
    corpus = yaml.safe_load(Path(args.corpus).read_text(encoding="utf-8"))
    rows = []
    for source in corpus["sources"]:
        for v in source["versions"]:
            raw = json.loads((Path(args.cache) / f"{file_sha256(v['path'])}.json").read_text(encoding="utf-8"))
            blocks = [b for ch in raw["result"]["chunks"] for b in ch["blocks"]]
            excluded = Counter(b["type"] for b in blocks if b["type"] in EXCLUDED_BLOCKS)
            headers = [b["content"].replace("\n", " ")[:70] for b in blocks if b["type"] == "Header"]
            old = old_text_sha256(parser._extract_sections(raw))
            new = text_sha256(raw)
            rows.append((source["key"], v.get("label"), old, new))
            print(f"{source['key']} ({v.get('label') or '-'})")
            print(f"  old {old[:16]}  new {new[:16]}  changed: {old != new}")
            print(f"  excluded blocks: {dict(sorted(excluded.items()))}")
            for h in headers:
                print(f"  page header left out: {h}")
    news = [r[3] for r in rows]
    v12 = next(r for r in rows if r[1] and "V1.2" in r[1])[3]
    v13 = next(r for r in rows if r[1] and "V1.3" in r[1])[3]
    print()
    print(f"versions: {len(rows)}; distinct new fingerprints: {len(set(news))}; "
          f"changed from old rule: {sum(r[2] != r[3] for r in rows)}; V1.2 != V1.3: {v12 != v13}")


if __name__ == "__main__":
    main()
