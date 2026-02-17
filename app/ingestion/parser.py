from __future__ import annotations

from typing import Any

import httpx


HEADER_TYPES = {"Title", "Section Header", "Header"}


class ReductoParser:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url="https://platform.reducto.ai",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=300.0,
        )

    async def parse_pdf(self, file_path: str) -> tuple[dict[str, Any], list[dict]]:
        """Parse a PDF file via Reducto API (upload then parse).

        Returns:
            Tuple of (raw_output, sections) where sections is a list of
            {"title": str, "content": str, "page": int} dicts.
        """
        # Step 1: Upload the file
        with open(file_path, "rb") as f:
            upload_response = await self.client.post(
                "/upload",
                files={"file": (file_path.split("/")[-1], f, "application/pdf")},
            )
        upload_response.raise_for_status()
        file_id = upload_response.json()["file_id"]

        # Step 2: Parse the uploaded file
        parse_response = await self.client.post(
            "/parse",
            json={"input": file_id},
        )
        parse_response.raise_for_status()
        raw_output = parse_response.json()

        # Handle URL result (large documents)
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
                        "content": " ".join(current_content),
                        "page": current_page,
                    })
                    current_content = []
                current_title = content or "Untitled Section"
                current_page = page
            else:
                if content.strip():
                    current_content.append(content)
                if not sections and current_title == "Untitled Section":
                    current_page = page

        # Don't forget the last section
        if current_content:
            sections.append({
                "title": current_title,
                "content": " ".join(current_content),
                "page": current_page,
            })

        return sections

    async def close(self):
        await self.client.aclose()
