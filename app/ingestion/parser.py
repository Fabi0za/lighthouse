from __future__ import annotations

import re
from typing import Any

import httpx


HEADER_TYPES = {"Title", "Section Header", "Header"}
MIN_BLOCK_LENGTH = 10  # Skip blocks shorter than this (OCR artefacts, icons)


def _is_table_block(text: str) -> bool:
    """Check if a text block looks like a Markdown table."""
    return "|" in text and text.strip().startswith("|")


def _join_blocks(blocks: list[str]) -> str:
    """Join content blocks, preserving newlines for Markdown tables."""
    if not blocks:
        return ""
    parts: list[str] = []
    for block in blocks:
        if _is_table_block(block):
            # Ensure table blocks are separated by newlines
            parts.append("\n" + block + "\n")
        else:
            parts.append(block)
    # Join prose blocks with space, then clean up extra whitespace
    result = " ".join(parts)
    # Normalize multiple newlines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _html_table_to_markdown(html: str) -> str:
    """Convert HTML table markup in a string to Markdown tables.

    Handles both complete <table>...</table> blocks and fragments
    that contain <tr>/<td>/<th> tags without a wrapping <table>.
    """
    if "<tr" not in html and "<td" not in html and "<th" not in html:
        return html

    def _rows_to_markdown(rows: list[list[str]]) -> str:
        if not rows:
            return ""
        max_cols = max(len(r) for r in rows)
        for r in rows:
            while len(r) < max_cols:
                r.append("")
        lines = []
        lines.append("| " + " | ".join(rows[0]) + " |")
        lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    def _extract_rows(table_html: str) -> list[list[str]]:
        rows: list[list[str]] = []
        for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL):
            cells: list[str] = []
            for cell_match in re.finditer(
                r"<(?:td|th)([^>]*)>(.*?)</(?:td|th)>", row_match.group(1), re.DOTALL
            ):
                attrs = cell_match.group(1)
                text = re.sub(r"<[^>]+>", " ", cell_match.group(2)).strip()
                colspan = int(m.group(1)) if (m := re.search(r'colspan="(\d+)"', attrs)) else 1
                cells.append(text)
                for _ in range(colspan - 1):
                    cells.append(text)
            if cells:
                rows.append(cells)
        return rows

    # First pass: convert complete <table>...</table> blocks
    def _convert_complete(match: re.Match) -> str:
        rows = _extract_rows(match.group(0))
        return _rows_to_markdown(rows)

    result = re.sub(r"<table[^>]*>.*?</table>", _convert_complete, html, flags=re.DOTALL)

    # Second pass: handle remaining fragments with <tr>/<td> but no <table> wrapper
    if "<tr" in result or "<td" in result:
        rows = _extract_rows(result)
        if rows:
            # Extract non-HTML text before/after the table fragment
            before = re.split(r"<(?:tr|td|th)", result, maxsplit=1)[0].strip()
            after_match = re.search(r"</(?:tr|td|th|table)>[^<]*$", result)
            after = after_match.group(0).split(">", 1)[-1].strip() if after_match else ""
            parts = []
            if before:
                parts.append(before)
            parts.append(_rows_to_markdown(rows))
            if after:
                parts.append(after)
            result = "\n".join(parts)

    return result


class ReductoParser:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url="https://platform.reducto.ai",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=300.0,
        )

    async def parse_pdf(self, path: str) -> tuple[dict[str, Any], list[dict]]:
        """Parse a PDF file via Reducto API (upload then parse).

        Returns:
            Tuple of (raw_output, sections) where sections is a list of
            {"title": str, "content": str, "page": int} dicts.
        """
        # Step 1: Upload the file
        with open(path, "rb") as f:
            upload_response = await self.client.post(
                "/upload",
                files={"file": (path.split("/")[-1], f, "application/pdf")},
            )
        upload_response.raise_for_status()
        file_id = upload_response.json()["file_id"]

        # Step 2: Parse the uploaded file
        parse_response = await self.client.post(
            "/parse",
            json={
                "input": file_id,
                "retrieval": {
                    "filter_blocks": ["Footer", "Page Number"],
                },
            },
        )
        parse_response.raise_for_status()
        raw_output = parse_response.json()

        # Handle URL result (large files)
        result = raw_output.get("result", {})
        if result.get("type") == "url":
            result_url = result["url"]
            async with httpx.AsyncClient(timeout=60.0) as dl_client:
                dl_response = await dl_client.get(result_url)
                dl_response.raise_for_status()
                result = dl_response.json()
                raw_output["result"] = result

        sections = self._extract_sections(raw_output)
        return raw_output, sections

    def _extract_sections(self, raw_output: dict[str, Any]) -> list[dict]:
        result = raw_output.get("result", {})
        chunks = result.get("chunks", [])

        # Collect all blocks across all chunks
        all_blocks = []
        for chunk in chunks:
            for block in chunk.get("blocks", []):
                all_blocks.append(block)

        if not all_blocks:
            return []

        sections: list[dict] = []
        current_title = "Untitled Section"
        current_content: list[str] = []
        current_page = 1

        for block in all_blocks:
            block_type = block.get("type", "Text")
            content = block.get("content", "")
            bbox = block.get("bbox", {})
            page = bbox.get("page", current_page)

            if block_type in HEADER_TYPES:
                # Save previous section if it has content
                if current_content:
                    sections.append({
                        "title": current_title,
                        "content": _join_blocks(current_content),
                        "page": current_page,
                    })
                    current_content = []
                current_title = content or "Untitled Section"
                current_page = page
            else:
                if content.strip() and len(content.strip()) >= MIN_BLOCK_LENGTH:
                    current_content.append(_html_table_to_markdown(content))
                if not sections and current_title == "Untitled Section":
                    current_page = page

        # Don't forget the last section
        if current_content:
            sections.append({
                "title": current_title,
                "content": _join_blocks(current_content),
                "page": current_page,
            })

        return sections

    async def close(self):
        await self.client.aclose()
