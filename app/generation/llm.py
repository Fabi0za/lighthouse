from __future__ import annotations

import httpx


class LLMClient:
    def __init__(self, provider: str, api_key: str, model: str):
        self.provider = provider
        self.model = model

        if provider == "anthropic":
            self.client = httpx.AsyncClient(
                base_url="https://api.anthropic.com/v1",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                timeout=120.0,
            )
        elif provider == "openai":
            self.client = httpx.AsyncClient(
                base_url="https://api.openai.com/v1",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.provider == "anthropic":
            return await self._generate_anthropic(system_prompt, user_prompt)
        elif self.provider == "openai":
            return await self._generate_openai(system_prompt, user_prompt)
        raise ValueError(f"Unsupported provider: {self.provider}")

    async def _generate_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        response = await self.client.post(
            "/messages",
            json={
                "model": self.model,
                "max_tokens": 4096,
                "temperature": 0,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]

    async def _generate_openai(self, system_prompt: str, user_prompt: str) -> str:
        response = await self.client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def close(self):
        await self.client.aclose()
