from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are a technical knowledge assistant for field engineers working with electrical installation documents. Your role is to provide accurate, cited answers based on the provided context.

Rules:
1. Answer based ONLY on the provided context. Never use information outside the context.
2. Cite every claim with [Document Title, Section, Page X].
3. When sources conflict, prefer the document with higher hierarchy priority and explain the override.
4. If you don't have enough information to answer confidently, say: "I don't have enough information to answer this confidently." Do not guess.
5. When synthesizing across multiple documents, clearly indicate which information comes from which source.
6. End your response with a confidence assessment: high, medium, or low."""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def build_user_prompt(question: str, chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return f"""Question: {question}

No relevant context documents were found. State that you have no relevant context to answer this question."""

    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        title = chunk.get("document_title", "Unknown Document")
        section = chunk.get("section_title", "Unknown Section")
        page = chunk.get("page_number", "?")
        priority = chunk.get("hierarchy_priority", 0)
        doc_type = chunk.get("doc_type", "unknown")
        content = chunk.get("content", "")

        context_parts.append(
            f"[Source {i}] {title} — {section}, Page {page} (Type: {doc_type}, Priority: {priority})\n{content}"
        )

    context_block = "\n\n---\n\n".join(context_parts)

    return f"""Context:
{context_block}

---

Question: {question}

Provide a precise, cited answer based on the context above."""
