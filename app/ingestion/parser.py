from __future__ import annotations

from typing import Any

import httpx


class ReductoParser:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url="https://api.reducto.ai/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120.0,
        )

    async def parse_pdf(self, file_path: str) -> tuple[dict[str, Any], list[dict]]:
        with open(file_path, "rb") as f:
            response = await self.client.post(
                "/parse",
                files={"file": (file_path.split("/")[-1], f, "application/pdf")},
            )
        response.raise_for_status()
        raw_output = response.json()

        sections = self._extract_sections(raw_output)
        return raw_output, sections

    def _extract_sections(self, raw_output: dict[str, Any]) -> list[dict]:
        blocks = raw_output.get("result", {}).get("blocks", [])
        sections: list[dict] = []
        current_title = "Untitled Section"
        current_content: list[str] = []
        current_page = 1

        for block in blocks:
            if block.get("type") == "header":
                if current_content:
                    sections.append({
                        "title": current_title,
                        "content": " ".join(current_content),
                        "page": current_page,
                    })
                    current_content = []
                current_title = block.get("content", "Untitled Section")
                current_page = block.get("page", current_page)
            else:
                current_content.append(block.get("content", ""))
                if not sections and current_title == "Untitled Section":
                    current_page = block.get("page", current_page)

        if current_content:
            sections.append({
                "title": current_title,
                "content": " ".join(current_content),
                "page": current_page,
            })

        return sections

    async def close(self):
        await self.client.aclose()
