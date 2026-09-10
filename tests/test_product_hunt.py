import pytest

from ai_pipeline.directory_sources import ProductHuntCrawler


@pytest.mark.asyncio
async def test_product_hunt_requires_token(monkeypatch):
    monkeypatch.delenv("PRODUCT_HUNT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="PRODUCT_HUNT_TOKEN"):
        await ProductHuntCrawler().crawl(1)