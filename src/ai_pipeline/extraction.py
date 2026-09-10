from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

from ai_pipeline.crawlers import AsyncFetcher
from ai_pipeline.utils.chunking import chunk_text

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Provider:
    name: str
    api_key: str | None
    model: str


class LLMOrchestrator:
    def __init__(self):
        self.providers = [Provider("gemini", os.getenv("GEMINI_API_KEY"), os.getenv("GEMINI_MODEL", "gemini-2.5-flash")), Provider("groq", os.getenv("GROQ_API_KEY"), os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")), Provider("deepseek", os.getenv("DEEPSEEK_API_KEY"), os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))]
        self.last_provider: str | None = None

    def available_providers(self) -> list[str]:
        return [provider.name for provider in self.providers if provider.api_key]

    def prepare_chunks(self, content: str, max_chars: int = 12000) -> list[str]:
        return chunk_text(content, max_chars=max_chars)

    async def extract(self, content: str, schema: dict[str, Any]) -> dict[str, Any]:
        chunks = self.prepare_chunks(content, int(os.getenv("LLM_MAX_CHARS", "12000")))
        if not chunks:
            return {}
        results: list[dict[str, Any]] = []
        for chunk in chunks:
            results.append(await self._extract_chunk(chunk, schema))
        return self._merge(results)

    async def _extract_chunk(self, content: str, schema: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "Extract only facts explicitly present in the supplied source text. "
            "Return valid JSON matching the requested schema. Use null or empty arrays "
            "when a value is absent. Never infer, guess, or add outside knowledge.\n\n"
            f"Requested schema:\n{json.dumps(schema)}\n\nSource text:\n{content}"
        )
        errors = []
        for provider in self.providers:
            if not provider.api_key:
                continue
            try:
                result = await self._request(provider, prompt)
                self.last_provider = provider.name
                return result
            except Exception as error:
                errors.append(f"{provider.name}: {error}")
                LOGGER.warning("llm_provider_failed provider=%s error=%s", provider.name, error)
        raise RuntimeError("No LLM provider succeeded: " + "; ".join(errors) if errors else "No LLM API keys configured")

    async def _request(self, provider: Provider, prompt: str) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")))
        retries = int(os.getenv("MAX_RETRIES", "4"))
        if provider.name == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{provider.model}:generateContent?key={provider.api_key}"
            body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}}
            request_headers = {}
        else:
            url = "https://api.groq.com/openai/v1/chat/completions" if provider.name == "groq" else "https://api.deepseek.com/chat/completions"
            body = {"model": provider.model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": "Return JSON only."}, {"role": "user", "content": prompt}]}
            request_headers = {"Authorization": f"Bearer {provider.api_key}"}
        fetcher = AsyncFetcher(timeout_seconds=int(timeout.total or 60))
        async with aiohttp.ClientSession(timeout=timeout, connector=fetcher.connector()) as session:
            for attempt in range(retries):
                async with session.post(url, json=body, headers=request_headers) as response:
                    if response.status == 413:
                        raise ValueError("payload rejected with HTTP 413; reduce LLM_MAX_CHARS")
                    if response.status == 429 or response.status >= 500:
                        if attempt == retries - 1:
                            raise RuntimeError(f"HTTP {response.status}")
                        retry_after = response.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt + random.uniform(0, 0.4)
                        LOGGER.warning("llm_retry provider=%s status=%s attempt=%s delay=%.2f", provider.name, response.status, attempt + 1, delay)
                        await asyncio.sleep(delay)
                        continue
                    response.raise_for_status()
                    payload = await response.json()
                    return self._parse_response(provider.name, payload)
        raise RuntimeError("LLM retries exhausted")

    @staticmethod
    def _parse_response(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
        if provider == "gemini":
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        else:
            text = payload["choices"][0]["message"]["content"]
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("LLM response must be a JSON object")
        return value

    @staticmethod
    def _merge(results: list[dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for result in results:
            for key, value in result.items():
                if value not in (None, "", [], {}):
                    if key not in merged or merged[key] in (None, "", [], {}):
                        merged[key] = value
        return merged
