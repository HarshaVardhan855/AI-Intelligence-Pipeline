from __future__ import annotations

from datetime import datetime, timezone
import asyncio
import json
import logging
from xml.etree import ElementTree

import aiohttp

from ai_pipeline.crawlers import AsyncFetcher
from ai_pipeline.schemas import JobRecord, NewsRecord, Source
from ai_pipeline.utils.dates import is_fresh, parse_date

LOGGER = logging.getLogger(__name__)

NEWS_FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Google AI Blog": "https://blog.research.google/feeds/posts/default/-/Artificial%20Intelligence",
    "Microsoft Research": "https://www.microsoft.com/en-us/research/feed/",
    "DeepMind": "https://deepmind.google/blog/rss.xml",
    "OpenAI News": "https://openai.com/news/rss.xml",
}
JOB_SOURCES = {
    "Remotive": ("https://remotive.com/api/remote-jobs?search=ai", "json"),
    "Arbeitnow": ("https://www.arbeitnow.com/api/job-board-api", "json"),
    "Jobicy": ("https://jobicy.com/api/v2/remote-jobs?count=50", "json"),
    "Remote OK": ("https://remoteok.com/api", "json"),
    "We Work Remotely": ("https://weworkremotely.com/categories/remote-programming-jobs.rss", "rss"),
}


async def crawl_feeds(feed_map: dict[str, str], parser, events: list[dict] | None = None) -> list[NewsRecord | JobRecord]:
    fetcher = AsyncFetcher()
    async with aiohttp.ClientSession(timeout=fetcher.timeout, connector=fetcher.connector()) as session:
        async def collect(source_name: str, feed_url: str) -> list[NewsRecord | JobRecord]:
            try:
                xml = await fetcher.get(session, feed_url)
                return parser(xml, source_name, feed_url)
            except (aiohttp.ClientError, asyncio.TimeoutError, ElementTree.ParseError) as error:
                LOGGER.warning("feed_failed source=%s url=%s error=%s", source_name, feed_url, error)
                if events is not None:
                    events.append({"source": source_name, "url": feed_url, "status": getattr(error, "status", None), "block_type": _block_type(error), "error": str(error)})
                return []

        results = await asyncio.gather(*(collect(name, url) for name, url in feed_map.items()))
    return [record for records in results for record in records]


async def crawl_job_sources(events: list[dict] | None = None) -> list[JobRecord]:
    fetcher = AsyncFetcher()
    async with aiohttp.ClientSession(timeout=fetcher.timeout, connector=fetcher.connector()) as session:
        async def collect(source_name: str, source: tuple[str, str]) -> list[JobRecord]:
            url, format_name = source
            try:
                body = await fetcher.get(session, url)
                if format_name == "json":
                    return parse_job_api(body, source_name, url)
                return parse_fresh_jobs(body, source_name, url)
            except (aiohttp.ClientError, asyncio.TimeoutError, ElementTree.ParseError, json.JSONDecodeError) as error:
                LOGGER.warning("job_source_failed source=%s url=%s error=%s", source_name, url, error)
                if events is not None:
                    events.append({"source": source_name, "url": url, "status": getattr(error, "status", None), "block_type": _block_type(error), "error": str(error)})
                return []

        results = await asyncio.gather(*(collect(name, source) for name, source in JOB_SOURCES.items()))
    return [record for records in results for record in records]


def _block_type(error: Exception) -> str:
    status = getattr(error, "status", None)
    if status in {401, 403}:
        return "access_denied"
    if status == 429:
        return "rate_limited"
    if status is not None and status >= 500:
        return "server_error"
    if isinstance(error, ElementTree.ParseError):
        return "invalid_feed"
    return "request_failed"


def parse_fresh_news(xml: str, source_name: str, feed_url: str, now: datetime | None = None) -> list[NewsRecord]:
    now = now or datetime.now(timezone.utc)
    root = ElementTree.fromstring(xml)
    output = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        date_text = item.findtext("pubDate") or item.findtext("published") or item.findtext("updated")
        date = parse_date(date_text, now)
        content = (item.findtext("description") or item.findtext("content") or "").strip()
        if title and link and date and is_fresh(date, now):
            output.append(NewsRecord(source=Source(name=source_name, url=link), collectedAt=now, title=title, publication_timestamp=date, content=content))
    return output


def parse_fresh_jobs(xml: str, source_name: str, feed_url: str, now: datetime | None = None) -> list[JobRecord]:
    now = now or datetime.now(timezone.utc)
    root = ElementTree.fromstring(xml)
    output = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        date = parse_date(item.findtext("pubDate") or item.findtext("published"), now)
        if title and link and date and is_fresh(date, now):
            output.append(JobRecord(source=Source(name=source_name, url=link), collectedAt=now, company=source_name, date=date, role_family=title))
    return output


def parse_job_api(body: str, source_name: str, source_url: str, now: datetime | None = None) -> list[JobRecord]:
    now = now or datetime.now(timezone.utc)
    payload = json.loads(body)
    if source_name == "Remotive":
        items = payload.get("jobs", [])
        get_value = lambda item: (item.get("company_name"), item.get("title"), item.get("url"), item.get("publication_date"), item.get("candidate_required_location"))
    elif source_name == "Arbeitnow":
        items = payload.get("data", [])
        get_value = lambda item: (item.get("company_name"), item.get("title"), item.get("url"), item.get("created_at"), item.get("location"))
    elif source_name == "Jobicy":
        items = payload.get("jobs", [])
        get_value = lambda item: (item.get("companyName"), item.get("jobTitle"), item.get("url"), item.get("pubDate"), item.get("jobGeo"))
    else:
        items = [item for item in payload if isinstance(item, dict) and item.get("id")]
        get_value = lambda item: (item.get("company"), item.get("position"), item.get("url") or item.get("apply_url"), item.get("date"), item.get("location"))
    output = []
    for item in items:
        company, title, url, date_text, location = get_value(item)
        date = parse_date(date_text, now)
        if not title or not url or not date or not is_fresh(date, now):
            continue
        output.append(JobRecord(source=Source(name=source_name, url=url), collectedAt=now, company=company or source_name, date=date, is_remote=True if str(location or "").lower() in {"remote", "worldwide", "anywhere"} else None, role_family=title))
    return output
