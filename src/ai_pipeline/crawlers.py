from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import logging
import os
import random
import re
import ssl
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup
from pydantic import HttpUrl, TypeAdapter
import truststore

from ai_pipeline.schemas import ProductRecord, ResearchPaperRecord, Source, StartupRecord
from ai_pipeline.utils.dates import parse_date

LOGGER = logging.getLogger(__name__)


class AsyncFetcher:
    def __init__(self, concurrency: int | None = None, timeout_seconds: int | None = None):
        concurrency = concurrency if concurrency is not None else int(os.getenv("HTTP_CONCURRENCY", "20"))
        timeout_seconds = timeout_seconds if timeout_seconds is not None else int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
        if concurrency < 1:
            raise ValueError("HTTP_CONCURRENCY must be at least 1")
        if timeout_seconds < 1:
            raise ValueError("REQUEST_TIMEOUT_SECONDS must be at least 1")
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def connector(self) -> aiohttp.TCPConnector:
        """Use the operating-system trust store while retaining TLS validation."""
        return aiohttp.TCPConnector(ssl=self.ssl_context)

    async def get(self, session: aiohttp.ClientSession, url: str) -> str:
        retries = int(os.getenv("MAX_RETRIES", "4"))
        for attempt in range(retries):
            try:
                async with self.semaphore:
                    async with session.get(url, headers={"User-Agent": "ai-intelligence-pipeline/0.1"}) as response:
                        if response.status == 429:
                            retry_after = response.headers.get("Retry-After")
                            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt + random.uniform(0, 0.4)
                            LOGGER.warning("http_retry url=%s status=429 attempt=%s delay=%.2f", url, attempt + 1, delay)
                            if attempt == retries - 1:
                                response.raise_for_status()
                            await asyncio.sleep(delay)
                            continue
                        response.raise_for_status()
                        return await response.text()
            except aiohttp.ClientResponseError as error:
                if error.status != 429 and error.status < 500:
                    raise
                if attempt == retries - 1:
                    raise
                delay = 2 ** attempt + random.uniform(0, 0.4)
                LOGGER.warning("http_retry url=%s status=%s attempt=%s delay=%.2f", url, error.status, attempt + 1, delay)
                await asyncio.sleep(delay)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == retries - 1:
                    raise
                delay = 2 ** attempt + random.uniform(0, 0.4)
                LOGGER.warning("http_retry url=%s attempt=%s delay=%.2f", url, attempt + 1, delay)
                await asyncio.sleep(delay)
        raise RuntimeError("request retries exhausted")


class ArxivCrawler:
    endpoint = "https://export.arxiv.org/api/query?search_query=all:%22artificial%20intelligence%22&start={start}&max_results={limit}"

    async def crawl(self, limit: int = 1000) -> list[ResearchPaperRecord]:
        records: list[ResearchPaperRecord] = []
        seen_urls: set[str] = set()
        checkpoint_path = Path(os.getenv("CHECKPOINT_FILE", "data/arxiv_checkpoint.json"))
        start_offset = 0
        if checkpoint_path.exists():
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                records = [ResearchPaperRecord.model_validate(item) for item in checkpoint.get("records", [])]
                seen_urls = {str(record.paper_url) for record in records}
                start_offset = int(checkpoint.get("next_offset", 0))
                LOGGER.info("checkpoint_resumed records=%s next_offset=%s", len(records), start_offset)
            except (OSError, ValueError, TypeError) as error:
                LOGGER.warning("checkpoint_ignored path=%s error=%s", checkpoint_path, error)
        fetcher = AsyncFetcher()
        async with aiohttp.ClientSession(timeout=fetcher.timeout, connector=fetcher.connector()) as session:
            for start in range(start_offset, limit + 1000, 100):
                if len(records) >= limit:
                    break
                url = self.endpoint.format(start=start, limit=100)
                try:
                    page_records = self._parse(await fetcher.get(session, url))
                    new_records = [record for record in page_records if str(record.paper_url) not in seen_urls]
                    seen_urls.update(str(record.paper_url) for record in new_records)
                    records.extend(new_records)
                    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                    checkpoint_path.write_text(json.dumps({"next_offset": start + 100, "records": [record.model_dump(mode="json") for record in records]}), encoding="utf-8")
                    if not page_records:
                        break
                except Exception as error:
                    LOGGER.warning("paper page failed url=%s error=%s", url, error)
                    # If the first page is unavailable, later offsets will use the
                    # same unavailable source and cannot add valid records.
                    if not records:
                        break
        result = records[:limit]
        if len(result) >= limit or not records:
            checkpoint_path.unlink(missing_ok=True)
        return result

    @staticmethod
    def _parse(xml: str) -> list[ResearchPaperRecord]:
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        collected = datetime.now(timezone.utc)
        records = []
        for entry in ElementTree.fromstring(xml).findall("atom:entry", namespace):
            paper_url = entry.findtext("atom:id", namespaces=namespace)
            title = " ".join((entry.findtext("atom:title", namespaces=namespace) or "").split())
            published = parse_date(entry.findtext("atom:published", namespaces=namespace))
            if not paper_url or not title or not published:
                continue
            records.append(ResearchPaperRecord(source=Source(name="arXiv", url=paper_url), collectedAt=collected, title=title, authors=[author.findtext("atom:name", namespaces=namespace) or "" for author in entry.findall("atom:author", namespace)], paper_url=paper_url, published_date=published))
        return records


class GitHubVerifier:
    github_link = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")
    url_adapter = TypeAdapter(HttpUrl)

    async def enrich(self, records: list[ResearchPaperRecord]) -> list[ResearchPaperRecord]:
        concurrency = int(os.getenv("GITHUB_CONCURRENCY", "10"))
        timeout = aiohttp.ClientTimeout(total=float(os.getenv("GITHUB_TIMEOUT_SECONDS", "15")))
        semaphore = asyncio.Semaphore(concurrency)
        headers = {"Accept": "application/vnd.github+json"}
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        fetcher = AsyncFetcher(timeout_seconds=int(timeout.total or 15))
        async with aiohttp.ClientSession(timeout=timeout, headers=headers, connector=fetcher.connector()) as session:
            async def enrich_one(record: ResearchPaperRecord) -> ResearchPaperRecord:
                async with semaphore:
                    try:
                        async with session.get(str(record.paper_url), headers={"User-Agent": "ai-intelligence-pipeline/0.1"}) as page_response:
                            if page_response.status != 200:
                                return record
                            html = await page_response.text()
                        candidate = self._candidate(html)
                        if not candidate:
                            return record
                        owner_repo = candidate.removeprefix("https://github.com/").rstrip("/")
                        repository = await self._get_repository(session, owner_repo)
                        if repository is None:
                            return record
                        verified_url = self.url_adapter.validate_python(candidate)
                        return record.model_validate({**record.model_dump(), "github_url": verified_url, "github_stars": repository.get("stargazers_count")})
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
                        LOGGER.warning("github_verification_failed paper=%s error=%s", record.paper_url, error)
                        return record

            tasks = [asyncio.create_task(enrich_one(record)) for record in records]
            enriched = []
            for index, task in enumerate(asyncio.as_completed(tasks), start=1):
                enriched.append(await task)
                if index % 100 == 0:
                    LOGGER.info("github_progress completed=%s total=%s", index, len(records))
        return enriched

    async def _get_repository(self, session: aiohttp.ClientSession, owner_repo: str) -> dict | None:
        retries = int(os.getenv("MAX_RETRIES", "4"))
        for attempt in range(retries):
            async with session.get(f"https://api.github.com/repos/{owner_repo}") as response:
                if response.status == 200:
                    return await response.json()
                if response.status != 429 and response.status < 500:
                    return None
                if attempt == retries - 1:
                    return None
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt + random.uniform(0, 0.4)
                LOGGER.warning("github_retry owner_repo=%s status=%s attempt=%s delay=%.2f", owner_repo, response.status, attempt + 1, delay)
                await asyncio.sleep(delay)
        return None

    @classmethod
    def _candidate(cls, html: str) -> str | None:
        for match in cls.github_link.finditer(html):
            path = match.group(1).split("#", 1)[0].split("?", 1)[0]
            if path.count("/") == 1:
                return f"https://github.com/{path}"
        return None


def load_verified_csv(path: Path, kind: str) -> list[StartupRecord | ProductRecord]:
    records = []
    collected = datetime.now(timezone.utc)
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            url = row.get("source_url", "").strip()
            if not url or not row.get("name", "").strip():
                continue
            source = Source(name=row.get("source_name", "user-supplied public source"), url=url, record_id=row.get("source_record_id"))
            if kind == "startup":
                employee_count = int(row["employee_count"]) if row.get("employee_count", "").isdigit() else None
                records.append(StartupRecord(source=source, collectedAt=collected, entityName=row["name"].strip(), employeeCount=employee_count))
            else:
                pricing = row.get("pricing_model") or None
                records.append(ProductRecord(source=source, collectedAt=collected, startupName=row["name"].strip(), pricingModel=pricing if pricing in {"FREE", "FREEMIUM", "PAID", "ENTERPRISE"} else None))
    return records


def validate_verified_csv(path: Path, kind: str) -> list[str]:
    if kind not in {"startup", "product"}:
        raise ValueError("kind must be startup or product")
    errors: list[str] = []
    seen_urls: set[str] = set()
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        required = {"name", "source_url", "source_name", "source_record_id"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            return [f"missing columns: {', '.join(sorted(missing))}"]
        for line_number, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            source_url = (row.get("source_url") or "").strip()
            parsed = urlparse(source_url)
            if not name:
                errors.append(f"line {line_number}: name is empty")
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"line {line_number}: source_url is not a valid HTTP(S) URL")
            if source_url in seen_urls:
                errors.append(f"line {line_number}: duplicate source_url")
            seen_urls.add(source_url)
            if kind == "startup" and row.get("employee_count"):
                try:
                    if int(row["employee_count"]) < 0:
                        errors.append(f"line {line_number}: employee_count cannot be negative")
                except ValueError:
                    errors.append(f"line {line_number}: employee_count must be an integer")
            if kind == "product" and row.get("pricing_model") and row["pricing_model"] not in {"FREE", "FREEMIUM", "PAID", "ENTERPRISE"}:
                errors.append(f"line {line_number}: invalid pricing_model")
    return errors


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    return "\n\n".join(part.strip() for part in soup.stripped_strings if len(part.strip()) > 20)


def stable_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]
