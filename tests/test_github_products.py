"""Tests for GitHubProductCrawler multi-topic queries and deduplication."""

import asyncio
import json
import pytest
from datetime import datetime, timezone

from ai_pipeline.directory_sources import GitHubProductCrawler
from ai_pipeline.schemas import ProductRecord


def _make_github_response(items):
    """Build a minimal GitHub search API response."""
    return json.dumps({"total_count": len(items), "items": items})


@pytest.mark.asyncio
async def test_github_product_crawler_uses_multiple_topics(monkeypatch):
    """Verify the crawler cycles through topics when needed."""
    topics_seen = set()

    async def mock_get(_, __, url):
        # Extract topic from URL
        if "topic%3A" in url:
            topic = url.split("topic%3A")[1].split("&")[0]
            topics_seen.add(topic)
        return _make_github_response([])

    monkeypatch.setattr("ai_pipeline.directory_sources.AsyncFetcher.get", mock_get)

    await GitHubProductCrawler().crawl(limit=5)
    # Must have tried multiple topics
    assert len(topics_seen) > 1


@pytest.mark.asyncio
async def test_github_product_crawler_deduplicates_across_topics(monkeypatch):
    """Repos appearing under multiple topics are not counted twice."""
    call_count = 0

    async def mock_get(_, __, url):
        nonlocal call_count
        call_count += 1
        # Return the same repo from every topic
        return _make_github_response([
            {"id": 1, "full_name": "org/shared-repo", "html_url": "https://github.com/org/shared-repo"},
            {"id": call_count + 100, "full_name": f"org/unique-{call_count}", "html_url": f"https://github.com/org/unique-{call_count}"},
        ])

    monkeypatch.setattr("ai_pipeline.directory_sources.AsyncFetcher.get", mock_get)

    records = await GitHubProductCrawler().crawl(limit=100)
    urls = [str(r.source.url) for r in records]
    # shared-repo should appear only once
    assert urls.count("https://github.com/org/shared-repo") == 1


@pytest.mark.asyncio
async def test_github_product_crawler_stops_at_limit(monkeypatch):
    """Crawler stops fetching once the limit is reached."""

    async def mock_get(_, __, url):
        page = 1
        if "page=" in url:
            page = int(url.split("page=")[-1])
        return _make_github_response([
            {"id": page * 100 + i, "full_name": f"org/repo-{page}-{i}", "html_url": f"https://github.com/org/repo-{page}-{i}"}
            for i in range(100)
        ])

    monkeypatch.setattr("ai_pipeline.directory_sources.AsyncFetcher.get", mock_get)

    records = await GitHubProductCrawler().crawl(limit=5)
    assert len(records) == 5


@pytest.mark.asyncio
async def test_github_product_crawler_handles_empty_response(monkeypatch):
    async def mock_get(_, __, url):
        return _make_github_response([])

    monkeypatch.setattr("ai_pipeline.directory_sources.AsyncFetcher.get", mock_get)

    records = await GitHubProductCrawler().crawl(limit=100)
    assert records == []


@pytest.mark.asyncio
async def test_github_product_crawler_zero_limit():
    records = await GitHubProductCrawler().crawl(limit=0)
    assert records == []


def test_github_product_records_have_valid_schema():
    """Construct a ProductRecord as the crawler would and verify schema."""
    collected = datetime.now(timezone.utc)
    record = ProductRecord(
        source={"name": "GitHub AI software repository", "url": "https://github.com/org/repo", "record_id": "123"},
        collectedAt=collected,
        startupName="org/repo",
        pricingModel=None,
    )
    assert record.recordType == "PRODUCT"
    assert record.pricingModel is None
    assert record.source.record_id == "123"


def test_github_product_crawler_has_multiple_topics():
    """The crawler must have multiple topics to reach 1000+ unique results."""
    assert len(GitHubProductCrawler._topics) >= 3
