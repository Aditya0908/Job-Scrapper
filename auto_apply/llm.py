"""LLM abstraction layer supporting Gemini and OpenRouter."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class LLMError(Exception):
    pass


class LLMClient:
    """Unified LLM client that routes to Gemini or OpenRouter based on config.

    Environment variables:
        LLM_PROVIDER:       "gemini" (default) or "openrouter"
        GEMINI_API_KEY:      API key for Google Gemini
        OPENROUTER_API_KEY:  API key for OpenRouter
        LLM_MODEL:           Model override (default depends on provider)
    """

    def __init__(self) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "gemini").lower()
        self.model = os.getenv("LLM_MODEL", "")
        self._http = httpx.AsyncClient(timeout=_TIMEOUT)

        if self.provider == "gemini":
            self.api_key = os.getenv("GEMINI_API_KEY", "")
            if not self.api_key:
                raise LLMError(
                    "GEMINI_API_KEY not set. Export it or switch to LLM_PROVIDER=openrouter"
                )
            self.model = self.model or "gemini-2.0-flash"
        elif self.provider == "openrouter":
            self.api_key = os.getenv("OPENROUTER_API_KEY", "")
            if not self.api_key:
                raise LLMError("OPENROUTER_API_KEY not set.")
            self.model = self.model or "google/gemini-2.0-flash-001"
        else:
            raise LLMError(f"Unknown LLM_PROVIDER: {self.provider}")

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """Send a prompt and return the text response."""
        if self.provider == "gemini":
            return await self._gemini_generate(prompt, system, temperature, max_tokens)
        return await self._openrouter_generate(prompt, system, temperature, max_tokens)

    async def generate_json(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> Any:
        """Send a prompt and parse the response as JSON."""
        raw = await self.generate(prompt, system, temperature, max_tokens)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]  # drop opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        return json.loads(cleaned)

    async def _gemini_generate(
        self, prompt: str, system: str, temperature: float, max_tokens: int
    ) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": system}]})
            contents.append(
                {"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]}
            )
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        resp = await self._http.post(url, json=payload)
        if resp.status_code != 200:
            raise LLMError(f"Gemini API error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected Gemini response structure: {e}") from e

    async def _openrouter_generate(
        self, prompt: str, system: str, temperature: float, max_tokens: int
    ) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        resp = await self._http.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise LLMError(f"OpenRouter API error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected OpenRouter response structure: {e}") from e

    async def close(self) -> None:
        await self._http.aclose()
