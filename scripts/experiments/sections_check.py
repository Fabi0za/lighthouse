"""Sections and chunks per cached parse, with page headers as headings (old rule) and as
page furniture (new rule, CHUNKER_VERSION 2). Changes nothing.

Usage:
    python scripts/experiments/sections_check.py [--corpus corpus.yaml] [--cache plans-local/parsed]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from app.config import get_settings
from app.ingestion.chunker import Chunker
from app.ingestion.fingerprint import file_sha256
from app.ingestion.parser import HEADING_TYPES, PAGE_FURNITURE, ReductoParser


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.yaml")
    ap.add_argument("--cache", default="plans-local/parsed")
    args = ap.parse_args()
    s = get_settings()
    parser = ReductoParser(api_key="unused")  # only _extract_sections is used; no API call
    chunker = Chunker(chunk_size=s.chunk_size, chunk_overlap=s.chunk_overlap)
    old_rule = {"heading_types": HEADING_TYPES | {"Header"}, "page_furniture": PAGE_FURNITURE - {"Header"}}
    corpus = yaml.safe_load(Path(args.corpus).read_text(encoding="utf-8"))
    totals = [0, 0, 0, 0]
    print(f"{'source (label)':60} {'sections old→new':>17} {'chunks old→new':>15}")
    for source in corpus["sources"]:
        for v in source["versions"]:
            raw = json.loads((Path(args.cache) / f"{file_sha256(v['path'])}.json").read_text(encoding="utf-8"))
            old = parser._extract_sections(raw, **old_rule)
            new = parser._extract_sections(raw)
            counts = [len(old), len(new), len(chunker.chunk_sections(old)), len(chunker.chunk_sections(new))]
            totals = [a + b for a, b in zip(totals, counts)]
            name = f"{source['key']} ({v.get('label') or '-'})"[:60]
            print(f"{name:60} {counts[0]:>7} → {counts[1]:<7} {counts[2]:>6} → {counts[3]:<6}")
            gone = sorted({sec['title'] for sec in old} - {sec['title'] for sec in new})
            for title in gone:
                print(f"    section title no longer used: {title.replace(chr(10), ' ')[:80]}")
    print(f"{'total':60} {totals[0]:>7} → {totals[1]:<7} {totals[2]:>6} → {totals[3]:<6}")


if __name__ == "__main__":
    main()
