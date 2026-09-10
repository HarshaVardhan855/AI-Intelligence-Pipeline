from datetime import datetime, timezone

from ai_pipeline.feeds import parse_fresh_jobs, parse_fresh_news, parse_job_api


FEED = """<rss><channel><item><title>Fresh item</title><link>https://example.com/item</link><pubDate>2 hours ago</pubDate><description>Verified content</description></item><item><title>Old item</title><link>https://example.com/old</link><pubDate>3 days ago</pubDate></item><item><title>No date</title><link>https://example.com/none</link></item></channel></rss>"""


def test_news_parser_accepts_only_fresh_dated_items():
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    records = parse_fresh_news(FEED, "Test News", "https://example.com/feed", now)
    assert len(records) == 1
    assert records[0].title == "Fresh item"
    assert records[0].content == "Verified content"


def test_job_parser_rejects_stale_and_undated_items():
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    records = parse_fresh_jobs(FEED, "Test Jobs", "https://example.com/feed", now)
    assert len(records) == 1
    assert records[0].role_family == "Fresh item"


def test_remotive_api_parser_uses_source_fields_and_freshness():
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    body = '{"jobs": [{"company_name": "Verified Co", "title": "AI Engineer", "url": "https://example.com/job", "publication_date": "2026-09-10T10:00:00Z", "candidate_required_location": "Worldwide"}]}'
    records = parse_job_api(body, "Remotive", "https://remotive.com/api/remote-jobs", now)
    assert len(records) == 1
    assert records[0].company == "Verified Co"
    assert records[0].is_remote is True