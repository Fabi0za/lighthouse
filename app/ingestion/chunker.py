from __future__ import annotations

from dataclasses import dataclass

import tiktoken


@dataclass
class Chunk:
    content: str
    section_title: str
    page_number: int
    chunk_index: int
    token_count: int


class Chunker:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoder = tiktoken.get_encoding("cl100k_base")

    def chunk_text(
        self,
        text: str,
        section_title: str,
        page_number: int,
        start_index: int = 0,
    ) -> list[Chunk]:
        words = text.split()
        if not words:
            return []

        chunks = []
        pos = 0
        chunk_idx = start_index

        while pos < len(words):
            end = pos + self.chunk_size
            chunk_words = words[pos:end]
            chunk_text = " ".join(chunk_words)
            token_count = len(self.encoder.encode(chunk_text))

            # Adjust if over token limit
            while token_count > self.chunk_size and len(chunk_words) > 1:
                chunk_words = chunk_words[:-1]
                chunk_text = " ".join(chunk_words)
                token_count = len(self.encoder.encode(chunk_text))

            chunks.append(
                Chunk(
                    content=chunk_text,
                    section_title=section_title,
                    page_number=page_number,
                    chunk_index=chunk_idx,
                    token_count=token_count,
                )
            )
            chunk_idx += 1

            advance = len(chunk_words) - self.chunk_overlap
            if advance <= 0:
                advance = max(1, len(chunk_words))
            pos += advance

        return chunks

    def chunk_sections(
        self,
        sections: list[dict],
    ) -> list[Chunk]:
        all_chunks = []
        idx = 0
        for section in sections:
            chunks = self.chunk_text(
                text=section["content"],
                section_title=section["title"],
                page_number=section.get("page", 1),
                start_index=idx,
            )
            all_chunks.extend(chunks)
            idx += len(chunks)
        return all_chunks
