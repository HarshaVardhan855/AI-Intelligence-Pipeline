from datetime import datetime, timezone

from ai_pipeline.html_sources import classify_blocked_page, parse_fresh_article


def test_fresh_html_article_preserves_full_text():
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    html = '<html><head><title>AI Update</title><script type="application/ld+json">{"datePublished":"2026-09-10T10:00:00Z"}</script></head><body><article>This is verified article content that is long enough to survive cleaning.</article></body></html>'
    record = parse_fresh_article(html, "Example News", "https://example.com/article", now)
    assert record is not None
    assert record.title == "AI Update"
    assert "verified article content" in record.content


def test_stale_html_article_is_rejected():
    html = '<meta property="article:published_time" content="2020-01-01T00:00:00Z"><title>Old</title><article>Old content</article>'
    assert parse_fresh_article(html, "Example", "https://example.com/old", datetime(2026, 9, 10, tzinfo=timezone.utc)) is None


def test_blocked_page_is_classified():
    assert classify_blocked_page(403, "Access denied") == "access_denied"
    assert classify_blocked_page(200, "captcha challenge") == "bot_protection"