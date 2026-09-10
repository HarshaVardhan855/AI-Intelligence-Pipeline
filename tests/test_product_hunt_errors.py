import pytest
from datetime import datetime, timezone

from ai_pipeline.directory_sources import ProductHuntCrawler


@pytest.mark.asyncio
async def test_product_hunt_missing_token_is_actionable(monkeypatch):
    monkeypatch.delenv("PRODUCT_HUNT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="PRODUCT_HUNT_TOKEN"):
        await ProductHuntCrawler().crawl(1)


def test_product_hunt_public_parser_is_available():
    assert hasattr(ProductHuntCrawler, "crawl_public")


def test_product_hunt_public_parser_requires_explicit_product_url_and_name():
    html = """
    <a href=\"/products/verified-tool?ref=home\">Verified Tool</a>
    <a href=\"/products\">All products</a>
    <a href=\"/products/missing-name\"></a>
    <a href=\"/topics/artificial-intelligence\">Not a product</a>
    """
    records = ProductHuntCrawler._parse_public_page(html, datetime.now(timezone.utc))
    assert [(record.startupName, str(record.source.url)) for record in records] == [
        ("Verified Tool", "https://www.producthunt.com/products/verified-tool")
    ]


@pytest.mark.asyncio
async def test_product_hunt_public_crawl_stops_after_requested_limit(monkeypatch):
    requested_urls = []

    async def get(_, __, url):
        requested_urls.append(url)
        page = 1 if "?page=" not in url else int(url.rsplit("=", 1)[1])
        return f'<a href="/products/tool-{page}">Tool {page}</a>'

    monkeypatch.setenv("PRODUCT_HUNT_MAX_PAGES", "10")
    monkeypatch.setenv("PRODUCT_HUNT_PAGE_CONCURRENCY", "2")
    monkeypatch.setattr("ai_pipeline.directory_sources.AsyncFetcher.get", get)

    records = await ProductHuntCrawler().crawl_public(2)

    assert len(records) == 2
    assert len(requested_urls) == 2
