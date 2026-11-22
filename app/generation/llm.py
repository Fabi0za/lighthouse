from __future__ import annotations

import httpx


class LLMClient:
    """The answer model, called through Anthropic's Messages API."""

    def __init__(self, api_key: str, model: str):
        self.model = model
        self.client = httpx.AsyncClient(
            base_url="https://api.anthropic.com/v1",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=120.0,
        )

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = await self.client.post(
            "/messages",
            json={
                "model": self.model,
                "max_tokens": 4096,
                # No temperature: current Claude models reject it ("deprecated for this model").
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        # The response may start with a thinking block; the answer is in the text block(s).
        texts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        if not texts:
            raise RuntimeError(
                f"Anthropic response has no text block (stop_reason={data.get('stop_reason')})"
            )
        return "".join(texts)

    async def close(self):
        await self.client.aclose()
