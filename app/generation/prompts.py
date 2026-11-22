from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are a technical knowledge assistant for field engineers working with electrical installation documents. Your role is to provide accurate, cited answers based on the provided context.

Rules:
1. Always respond in German, regardless of the language used in the context documents.
2. Answer based ONLY on the provided context. Never use information outside the context.
3. Cite every claim with [Document Title, Section, Page X].
4. When sources conflict, prefer the document with higher hierarchy priority and explain the override.
5. Only refuse to answer if the provided context contains no relevant information at all. In that case say: "Ich habe nicht genügend Informationen, um diese Frage sicher zu beantworten." If the context contains partial or related information, use it to answer as precisely as possible and note any limitations.
6. When synthesizing across multiple documents, clearly indicate which information comes from which source.
7. End your response with a confidence assessment: high, medium, or low."""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def build_user_prompt(question: str, chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return f"""Question: {question}

No relevant context documents were found. State that you have no relevant context to answer this question."""

    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        title = chunk.get("version_title", "Unknown Document")
        section = chunk.get("section_title", "Unknown Section")
        page = chunk.get("page_number", "?")
        priority = chunk.get("authority_rank", 0)
        level = chunk.get("level", "unknown")
        content = chunk.get("content", "")

        context_parts.append(
            f"[Source {i}] {title} — {section}, Page {page} (Type: {level}, Priority: {priority})\n{content}"
        )

    context_block = "\n\n---\n\n".join(context_parts)

    return f"""Context:
{context_block}

---

Question: {question}

Provide a precise, cited answer based on the context above."""
