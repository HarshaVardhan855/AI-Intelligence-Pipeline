import pytest

from ai_pipeline.crawlers import AsyncFetcher


def test_fetcher_uses_runtime_concurrency_and_timeout(monkeypatch):
    monkeypatch.setenv("HTTP_CONCURRENCY", "7")
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "13")

    fetcher = AsyncFetcher()

    assert fetcher.semaphore._value == 7
    assert fetcher.timeout.total == 13


@pytest.mark.parametrize(("name", "value"), [("HTTP_CONCURRENCY", "0"), ("REQUEST_TIMEOUT_SECONDS", "0")])
def test_fetcher_rejects_invalid_runtime_settings(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        AsyncFetcher()
