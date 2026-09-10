import aiohttp
import pytest

from ai_pipeline.crawlers import ArxivCrawler, AsyncFetcher


@pytest.mark.asyncio
async def test_arxiv_stops_after_initial_source_failure(monkeypatch, tmp_path):
    calls = 0

    async def unavailable(*_):
        nonlocal calls
        calls += 1
        raise aiohttp.ClientError("source unavailable")

    monkeypatch.setenv("CHECKPOINT_FILE", str(tmp_path / "checkpoint.json"))
    monkeypatch.setattr(AsyncFetcher, "get", unavailable)

    assert await ArxivCrawler().crawl(1000) == []
    assert calls == 1
