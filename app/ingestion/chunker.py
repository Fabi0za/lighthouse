from __future__ import annotations

import re
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

    def _token_count(self, text: str) -> int:
        return len(self.encoder.encode(text))

    def _split_into_segments(self, text: str) -> list[dict]:
        """Split text into segments: table blocks and prose blocks.

        A table block is a contiguous run of lines starting with '|'.
        Everything else is a prose block.
        """
        lines = text.split("\n")
        segments: list[dict] = []
        current_lines: list[str] = []
        current_type: str | None = None

        for line in lines:
            is_table_line = line.strip().startswith("|")
            line_type = "table" if is_table_line else "prose"

            if current_type is None:
                current_type = line_type

            if line_type != current_type:
                if current_lines:
                    segments.append({"type": current_type, "lines": current_lines})
                current_lines = [line]
                current_type = line_type
            else:
                current_lines.append(line)

        if current_lines:
            segments.append({"type": current_type, "lines": current_lines})

        return segments

    def _extract_table_header(self, table_lines: list[str]) -> list[str]:
        """Extract header rows from a Markdown table (header + separator)."""
        header: list[str] = []
        for line in table_lines:
            header.append(line)
            if re.match(r"^\|[\s\-|]+\|$", line.strip()):
                break
        # If no separator found, assume first line is header
        if len(header) == len(table_lines):
            return [table_lines[0]]
        return header

    def _chunk_table(
        self,
        table_lines: list[str],
        section_title: str,
        page_number: int,
        start_index: int,
    ) -> list[Chunk]:
        """Chunk a table at row boundaries, copying the header to each chunk."""
        header = self._extract_table_header(table_lines)
        header_text = "\n".join(header)
        header_tokens = self._token_count(header_text)

        # Data rows = everything after the header
        data_rows = table_lines[len(header):]

        if not data_rows:
            # Table is header-only
            chunk_text = header_text
            return [Chunk(
                content=chunk_text,
                section_title=section_title,
                page_number=page_number,
                chunk_index=start_index,
                token_count=self._token_count(chunk_text),
            )]

        chunks: list[Chunk] = []
        chunk_idx = start_index
        budget = self.chunk_size - header_tokens
        current_rows: list[str] = []
        current_tokens = 0

        for row in data_rows:
            row_tokens = self._token_count(row)

            if current_rows and (current_tokens + row_tokens) > budget:
                # Emit chunk with header + accumulated rows
                chunk_text = header_text + "\n" + "\n".join(current_rows)
                chunks.append(Chunk(
                    content=chunk_text,
                    section_title=section_title,
                    page_number=page_number,
                    chunk_index=chunk_idx,
                    token_count=self._token_count(chunk_text),
                ))
                chunk_idx += 1
                current_rows = []
                current_tokens = 0

            current_rows.append(row)
            current_tokens += row_tokens

        # Emit final chunk
        if current_rows:
            chunk_text = header_text + "\n" + "\n".join(current_rows)
            chunks.append(Chunk(
                content=chunk_text,
                section_title=section_title,
                page_number=page_number,
                chunk_index=chunk_idx,
                token_count=self._token_count(chunk_text),
            ))

        return chunks

    def _chunk_prose(
        self,
        text: str,
        section_title: str,
        page_number: int,
        start_index: int,
    ) -> list[Chunk]:
        """Chunk prose text by word count with overlap."""
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
            token_count = self._token_count(chunk_text)

            while token_count > self.chunk_size and len(chunk_words) > 1:
                chunk_words = chunk_words[:-1]
                chunk_text = " ".join(chunk_words)
                token_count = self._token_count(chunk_text)

            chunks.append(Chunk(
                content=chunk_text,
                section_title=section_title,
                page_number=page_number,
                chunk_index=chunk_idx,
                token_count=token_count,
            ))
            chunk_idx += 1

            advance = len(chunk_words) - self.chunk_overlap
            if advance <= 0:
                advance = max(1, len(chunk_words))
            pos += advance

        return chunks

    def chunk_text(
        self,
        text: str,
        section_title: str,
        page_number: int,
        start_index: int = 0,
    ) -> list[Chunk]:
        segments = self._split_into_segments(text)
        chunks: list[Chunk] = []
        idx = start_index

        for segment in segments:
            if segment["type"] == "table":
                new_chunks = self._chunk_table(
                    segment["lines"], section_title, page_number, idx,
                )
            else:
                prose_text = "\n".join(segment["lines"])
                new_chunks = self._chunk_prose(
                    prose_text, section_title, page_number, idx,
                )
            chunks.extend(new_chunks)
            idx += len(new_chunks)

        return chunks

    def chunk_sections(
        self,
        sections: list[dict],
        doc_title: str | None = None,
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
            # Add contextual header to each chunk for better embedding & LLM context
            if doc_title:
                for chunk in chunks:
                    header = f"[{doc_title} — {chunk.section_title}]\n"
                    chunk.content = header + chunk.content
                    chunk.token_count = self._token_count(chunk.content)
            all_chunks.extend(chunks)
            idx += len(chunks)
        return all_chunks
