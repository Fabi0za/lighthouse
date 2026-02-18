"""Migrate existing HTML table chunks to Markdown format in-place."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ingestion.parser import _html_table_to_markdown
from app.models.database import DatabaseClient


def main():
    db = DatabaseClient()
    # Find all chunks containing any HTML table markup
    seen_ids = set()
    chunks = []
    for pattern in ["%<table%", "%<td%", "%<th%", "%<tr%"]:
        results = db.client.table("document_chunks").select("id,content").ilike("content", pattern).execute()
        for r in results.data:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                chunks.append(r)

    print(f"Found {len(chunks)} chunks with HTML table markup.")

    for chunk in chunks:
        old = chunk["content"]
        new = _html_table_to_markdown(old)
        if old != new:
            db.client.table("document_chunks").update({"content": new}).eq("id", chunk["id"]).execute()
            print(f"  Updated chunk {chunk['id'][:8]}")

    print("Done.")


if __name__ == "__main__":
    main()
