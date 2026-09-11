"""Tests for YCStartupCrawler public index path, fallback, and record validation."""

import asyncio
import json
import pytest
from datetime import datetime, timezone

from ai_pipeline.directory_sources import YCStartupCrawler
from ai_pipeline.schemas import StartupRecord


SAMPLE_INDEX = [
    {"id": 1, "name": "Airbnb", "slug": "airbnb", "team_size": 6000, "url": "https://www.ycombinator.com/companies/airbnb"},
    {"id": 2, "name": "Stripe", "slug": "stripe", "team_size": 8000, "url": "https://www.ycombinator.com/companies/stripe"},
    {"id": 3, "name": "DoorDash", "slug": "doordash", "team_size": 12000},
    {"id": 4, "name": "NoSlug", "slug": "", "team_size": 5},
    {"id": 5, "name": "", "slug": "empty-name", "team_size": 5},
]


def test_yc_hits_to_records_produces_valid_records():
    crawler = YCStartupCrawler()
    records = crawler._hits_to_records(SAMPLE_INDEX, 100, datetime.now(timezone.utc))
    # Only 3 valid records (NoSlug missing slug, empty-name missing name)
    assert len(records) == 3
    for record in records:
        assert isinstance(record, StartupRecord)
        assert record.entityName
        assert "ycombinator.com/companies/" in str(record.source.url)
        assert record.source.name == "Y Combinator Startup Directory"


def test_yc_hits_to_records_respects_limit():
    crawler = YCStartupCrawler()
    records = crawler._hits_to_records(SAMPLE_INDEX, 2, datetime.now(timezone.utc))
    assert len(records) == 2


def test_yc_hits_to_records_deduplicates_by_url():
    duplicated = SAMPLE_INDEX[:2] + SAMPLE_INDEX[:2]  # same 2 items twice
    crawler = YCStartupCrawler()
    records = crawler._hits_to_records(duplicated, 100, datetime.now(timezone.utc))
    assert len(records) == 2


def test_yc_hits_to_records_generates_url_from_slug():
    crawler = YCStartupCrawler()
    records = crawler._hits_to_records(
        [{"id": 10, "name": "TestCo", "slug": "testco"}],
        100,
        datetime.now(timezone.utc),
    )
    assert str(records[0].source.url) == "https://www.ycombinator.com/companies/testco"


def test_yc_hits_to_records_preserves_employee_count_only_when_int():
    crawler = YCStartupCrawler()
    records = crawler._hits_to_records(
        [
            {"id": 1, "name": "WithSize", "slug": "a", "team_size": 42},
            {"id": 2, "name": "NoSize", "slug": "b"},
            {"id": 3, "name": "StringSize", "slug": "c", "team_size": "many"},
        ],
        100,
        datetime.now(timezone.utc),
    )
    assert records[0].employeeCount == 42
    assert records[1].employeeCount is None
    assert records[2].employeeCount is None


def test_yc_hits_to_records_retains_source_record_id():
    crawler = YCStartupCrawler()
    records = crawler._hits_to_records(
        [{"id": 42, "name": "IDTest", "slug": "idtest"}],
        100,
        datetime.now(timezone.utc),
    )
    assert records[0].source.record_id == "42"


@pytest.mark.asyncio
async def test_yc_crawl_uses_public_index_first(monkeypatch):
    """Verify crawl() tries the public index first and succeeds without Playwright."""
    sample = [{"id": i, "name": f"Company{i}", "slug": f"co{i}"} for i in range(10)]

    async def mock_fetch_public(_self):
        return sample

    async def mock_fetch_playwright(_self):
        raise AssertionError("Playwright should not be called when public index is sufficient")

    monkeypatch.setattr(YCStartupCrawler, "_fetch_public_index", mock_fetch_public)
    monkeypatch.setattr(YCStartupCrawler, "_fetch_via_playwright", mock_fetch_playwright)

    records = await YCStartupCrawler().crawl(limit=5)
    assert len(records) == 5


@pytest.mark.asyncio
async def test_yc_crawl_falls_back_to_playwright_when_index_insufficient(monkeypatch):
    """When public index returns fewer than limit, Playwright is tried as fallback."""
    playwright_called = []

    async def mock_fetch_public(_self):
        return [{"id": 1, "name": "Only", "slug": "only"}]

    async def mock_fetch_playwright(_self):
        playwright_called.append(True)
        return [{"id": i, "name": f"PW{i}", "slug": f"pw{i}"} for i in range(10)]

    monkeypatch.setattr(YCStartupCrawler, "_fetch_public_index", mock_fetch_public)
    monkeypatch.setattr(YCStartupCrawler, "_fetch_via_playwright", mock_fetch_playwright)

    records = await YCStartupCrawler().crawl(limit=5)
    assert playwright_called, "Playwright fallback should be called"
    assert len(records) == 5


def test_yc_empty_index_returns_no_records():
    crawler = YCStartupCrawler()
    records = crawler._hits_to_records([], 100, datetime.now(timezone.utc))
    assert records == []


def test_yc_schema_validation_on_records():
    """Every record must pass StartupRecord schema validation."""
    crawler = YCStartupCrawler()
    records = crawler._hits_to_records(SAMPLE_INDEX, 100, datetime.now(timezone.utc))
    for record in records:
        # Re-validate through model_validate to confirm schema compliance
        validated = StartupRecord.model_validate(record.model_dump(mode="json"))
        assert validated.recordType == "STARTUP"
        assert validated.schemaVersion == "1.0"
