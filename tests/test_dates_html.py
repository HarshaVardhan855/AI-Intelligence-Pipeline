from datetime import datetime, timezone

from ai_pipeline.utils.dates import extract_date_from_html


def test_html_date_prefers_json_ld():
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    html = '<meta property="og:published_time" content="2020-01-01T00:00:00Z"><script type="application/ld+json">{"datePublished":"2026-09-10T10:00:00Z"}</script>'
    assert extract_date_from_html(html, now) == datetime(2026, 9, 10, 10, tzinfo=timezone.utc)


def test_html_date_returns_none_when_undated():
    assert extract_date_from_html("<html><body>No publication date</body></html>") is None


def test_html_date_supports_visible_relative_date():
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    assert extract_date_from_html("<p>Published 2 hours ago</p>", now) == datetime(2026, 9, 10, 10, tzinfo=timezone.utc)