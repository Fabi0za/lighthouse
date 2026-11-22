from __future__ import annotations

from typing import Any

# Raise when a change to this file changes what the model is given: answers record it
# through their answer settings. tests/test_versioned_constants.py guards it.
PROMPT_VERSION = 2

SYSTEM_PROMPT = """You are an assistant that answers from the provided documents. Your role is to provide accurate, cited answers based on the provided context.

Rules:
1. Always respond in German, regardless of the language used in the context documents.
2. Answer based ONLY on the provided context. Never use information outside the context.
3. Cite every claim with [Document Title, Section, Page X].
4. When sources conflict, prefer the source with the higher rank and explain which one prevails.
5. Only refuse to answer if the provided context contains no relevant information at all. In that case say: "Ich habe nicht genügend Informationen, um diese Frage sicher zu beantworten." If the context contains partial or related information, use it to answer as precisely as possible and note any limitations.
6. When synthesizing across multiple documents, clearly indicate which information comes from which source.
7. End your response with a confidence assessment: high, medium, or low."""


def display_title(title: str, version_label: str | None) -> str:
    """A version's title as shown to the model and in citations: title and printed label."""
    return f"{title} ({version_label})" if version_label else title


def source_line(chunk: dict[str, Any]) -> str:
    """Where a chunk comes from: title and label, section if it has one, page."""
    title = display_title(chunk.get("version_title", "Unknown Document"), chunk.get("version_label"))
    section = chunk.get("section_title") or ""
    page = chunk.get("page_number", "?")
    return f"{title} — {section}, Page {page}" if section else f"{title}, Page {page}"


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def build_user_prompt(question: str, chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return f"""Question: {question}

No relevant context documents were found. State that you have no relevant context to answer this question."""

    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        rank = chunk.get("rank", 0)
        level = chunk.get("level", "unknown")
        content = chunk.get("content", "")

        context_parts.append(
            f"[Source {i}] {source_line(chunk)} (Level: {level}, Rank: {rank})\n{content}"
        )

    context_block = "\n\n---\n\n".join(context_parts)

    return f"""Context:
{context_block}

---

Question: {question}

Provide a precise, cited answer based on the context above."""
