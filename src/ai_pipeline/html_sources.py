from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ai_pipeline.crawlers import clean_html
from ai_pipeline.schemas import NewsRecord, Source
from ai_pipeline.utils.dates import extract_date_from_html, is_fresh


def parse_fresh_article(html: str, source_name: str, source_url: str, now: datetime | None = None) -> NewsRecord | None:
    now = now or datetime.now(timezone.utc)
    publication_date = extract_date_from_html(html, now)
    if not publication_date or not is_fresh(publication_date, now):
        return None
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("meta", attrs={"property": "og:title"}) or soup.find("title")
    title_text = title.get("content", "") if title and title.name == "meta" else title.get_text(" ", strip=True) if title else ""
    content = clean_html(html)
    if not title_text or not content:
        return None
    return NewsRecord(source=Source(name=source_name, url=source_url), collectedAt=now, title=title_text, publication_timestamp=publication_date, content=content)


def classify_blocked_page(status: int, html: str) -> str | None:
    text = html.lower()
    if status in {401, 403}:
        return "access_denied"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    if any(marker in text for marker in ("captcha", "cf-chl-", "cloudflare", "access denied")):
        return "bot_protection"
    return None


def source_domain(url: str) -> str:
    return urlparse(url).netloc
