from __future__ import annotations

import re
from typing import Any


class ResponseFormatter:
    def format(
        self,
        raw_response: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        confidence = self._extract_confidence(raw_response)
        answer = self._strip_confidence_line(raw_response)
        sources = self._build_sources(chunks)

        return {
            "answer": answer,
            "sources": sources,
            "confidence": confidence,
        }

    def _extract_confidence(self, text: str) -> str:
        match = re.search(r"[Cc]onfidence(?:\s+assessment)?:\s*(high|medium|low)", text, re.IGNORECASE)
        return match.group(1).lower() if match else "low"

    def _strip_confidence_line(self, text: str) -> str:
        return re.sub(
            r"\n*[Cc]onfidence(?:\s+assessment)?:\s*(high|medium|low)\.?\s*$", "", text
        ).strip()

    def _build_sources(self, chunks: list[dict[str, Any]]) -> list[dict[str, str | int]]:
        seen = set()
        sources = []
        for chunk in chunks:
            key = (
                chunk.get("document_title", ""),
                chunk.get("section_title", ""),
                chunk.get("page_number", 0),
            )
            if key not in seen:
                seen.add(key)
                sources.append({
                    "document_title": chunk.get("document_title", "Unknown"),
                    "section": chunk.get("section_title", "Unknown"),
                    "page": chunk.get("page_number", 0),
                })
        return sources
