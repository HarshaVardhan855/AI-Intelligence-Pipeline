from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from ai_pipeline.crawlers import AsyncFetcher
from ai_pipeline.schemas import ProductRecord, Source, StartupRecord

LOGGER = logging.getLogger(__name__)


class YCStartupCrawler:
    """Collect YC company records.

    Primary path: the public YC company index published at
    https://yc-oss.github.io/api/companies/all.json which is updated regularly
    and requires no authentication or JavaScript rendering.

    Fallback path: if the public index is unavailable or returns fewer records
    than requested, a headless Playwright session captures the Algolia search
    response from https://www.ycombinator.com/companies.
    """

    public_index_endpoint = "https://yc-oss.github.io/api/companies/all.json"

    def __init__(self, start_url: str = "https://www.ycombinator.com/companies"):
        self.start_url = start_url

    async def crawl(self, limit: int = 1000) -> list[StartupRecord]:
        collected = datetime.now(timezone.utc)
        # Primary: use the public JSON index (fast, reliable, no JS needed)
        hits = await self._fetch_public_index()
        if len(hits) < limit:
            LOGGER.info(
                "yc_public_index_insufficient count=%s limit=%s, trying playwright",
                len(hits),
                limit,
            )
            playwright_hits = await self._fetch_via_playwright()
            if len(playwright_hits) > len(hits):
                hits = playwright_hits
        return self._hits_to_records(hits, limit, collected)

    async def _fetch_public_index(self) -> list[dict]:
        """Fetch the public YC company index JSON."""
        fetcher = AsyncFetcher()
        try:
            async with aiohttp.ClientSession(
                timeout=fetcher.timeout, connector=fetcher.connector()
            ) as session:
                raw = await fetcher.get(session, self.public_index_endpoint)
            data = json.loads(raw)
            if isinstance(data, list) and data:
                LOGGER.info("yc_public_index_fetched count=%s", len(data))
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            LOGGER.warning("yc_public_index_failed error=%s", error)
        return []

    async def _fetch_via_playwright(self) -> list[dict]:
        """Render the YC companies page with Playwright and capture Algolia hits."""
        response_objects = []
        search_request: dict[str, str] = {}
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                page = await browser.new_page()

                def capture(response) -> None:
                    if "algolia.net/1/indexes" not in response.url:
                        return
                    response_objects.append(response)

                def capture_request(request) -> None:
                    if (
                        "algolia.net/1/indexes" in request.url
                        and request.method == "POST"
                        and request.post_data
                    ):
                        search_request["url"] = request.url
                        search_request["body"] = request.post_data

                page.on("response", capture)
                page.on("request", capture_request)
                await page.goto(self.start_url, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(1000)
                responses = []
                if search_request:
                    try:
                        responses.append(
                            await page.evaluate(
                                """async ({url, body}) => {
                                const response = await fetch(url, {method: 'POST', headers: {'content-type': 'application/json'}, body});
                                if (!response.ok) throw new Error(`YC search HTTP ${response.status}`);
                                return response.json();
                            }""",
                                search_request,
                            )
                        )
                    except Exception as error:
                        LOGGER.warning("yc_search_request_failed error=%s", error)
                for response in response_objects:
                    try:
                        payload = await response.json()
                        if payload.get("results", [{}])[0].get("hits", []):
                            responses.append(payload)
                    except Exception:
                        continue
                if not responses:
                    dom_links = await page.locator(
                        'a[href*="/companies/"]'
                    ).evaluate_all(
                        "links => links.map(link => ({name: link.innerText.trim(), url: link.href}))"
                    )
                    dom_hits = [
                        {
                            "name": item["name"].split("\n", 1)[0].strip(),
                            "slug": item["url"].rstrip("/").split("/")[-1],
                        }
                        for item in dom_links
                        if item.get("name") and item.get("url")
                    ]
                    responses = [{"results": [{"hits": dom_hits}]}]
                await browser.close()
            return max(
                (
                    payload.get("results", [{}])[0].get("hits", [])
                    for payload in responses
                ),
                key=len,
                default=[],
            )
        except Exception as error:
            LOGGER.warning("yc_playwright_failed error=%s", error)
            return []

    def _hits_to_records(
        self, hits: list[dict], limit: int, collected: datetime
    ) -> list[StartupRecord]:
        records: list[StartupRecord] = []
        seen: set[str] = set()
        for item in hits:
            slug = item.get("slug")
            name = item.get("name")
            if not slug or not name:
                continue
            url = item.get("url") or f"https://www.ycombinator.com/companies/{slug}"
            if url in seen:
                continue
            seen.add(url)
            employee_count = (
                item.get("team_size")
                if isinstance(item.get("team_size"), int)
                else None
            )
            records.append(
                StartupRecord(
                    source=Source(
                        name="Y Combinator Startup Directory",
                        url=url,
                        record_id=str(item.get("id")) if item.get("id") else None,
                    ),
                    collectedAt=collected,
                    entityName=name,
                    employeeCount=employee_count,
                )
            )
            if len(records) >= limit:
                break
        return records


class PublicDirectoryCrawler:
    def __init__(self, source_name: str, start_url: str, kind: str):
        if kind not in {"startup", "product"}:
            raise ValueError("kind must be startup or product")
        self.source_name = source_name
        self.start_url = start_url
        self.kind = kind
        self.max_pages = int(os.getenv("DIRECTORY_MAX_PAGES", "100"))

    async def crawl(self, limit: int = 1000) -> list[StartupRecord | ProductRecord]:
        records: list[StartupRecord | ProductRecord] = []
        seen_urls: set[str] = set()
        next_url: str | None = self.start_url
        fetcher = AsyncFetcher()
        async with aiohttp.ClientSession(
            timeout=fetcher.timeout, connector=fetcher.connector()
        ) as session:
            for _ in range(self.max_pages):
                if not next_url or len(records) >= limit:
                    break
                try:
                    html = await fetcher.get(session, next_url)
                    page_records, next_url = self._parse_page(html, next_url, seen_urls)
                    for record in page_records:
                        record_url = str(record.source.url)
                        if record_url not in seen_urls:
                            seen_urls.add(record_url)
                            records.append(record)
                            if len(records) >= limit:
                                break
                except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                    LOGGER.warning(
                        "directory_page_failed source=%s url=%s error=%s",
                        self.source_name,
                        next_url,
                        error,
                    )
                    break
        return records[:limit]

    def _parse_page(
        self, html: str, page_url: str, seen_urls: set[str]
    ) -> tuple[list[StartupRecord | ProductRecord], str | None]:
        try:
            payload = json.loads(html)
        except json.JSONDecodeError:
            payload = None
        if payload is not None:
            return self._parse_json_api(payload, page_url, seen_urls)
        soup = BeautifulSoup(html, "html.parser")
        collected = datetime.now(timezone.utc)
        records: list[StartupRecord | ProductRecord] = self._parse_json_ld(
            soup, page_url, collected, seen_urls
        )
        page_seen_urls = seen_urls | {str(record.source.url) for record in records}
        for link in soup.select("a[data-record-url], a.company-link, a.product-link"):
            href = link.get("data-record-url") or link.get("href")
            name = link.get_text(" ", strip=True)
            if not href or not name:
                continue
            source_url = urljoin(page_url, str(href))
            if source_url in page_seen_urls:
                continue
            if self.kind == "startup":
                employee_text = str(link.get("data-employee-count") or "")
                employee_count = int(employee_text) if employee_text.isdigit() else None
                records.append(
                    StartupRecord(
                        source=Source(name=self.source_name, url=source_url),
                        collectedAt=collected,
                        entityName=name,
                        employeeCount=employee_count,
                    )
                )
            else:
                pricing = link.get("data-pricing-model")
                if pricing not in {"FREE", "FREEMIUM", "PAID", "ENTERPRISE"}:
                    pricing = None
                records.append(
                    ProductRecord(
                        source=Source(name=self.source_name, url=source_url),
                        collectedAt=collected,
                        startupName=name,
                        pricingModel=pricing,
                    )
                )
            page_seen_urls.add(source_url)
        next_link = soup.select_one("a[rel='next'], a.next-page")
        return (
            records,
            urljoin(page_url, str(next_link["href"]))
            if next_link and next_link.get("href")
            else None,
        )

    def _parse_json_api(
        self, payload: object, page_url: str, seen_urls: set[str]
    ) -> tuple[list[StartupRecord | ProductRecord], str | None]:
        items = (
            payload.get("data", payload.get("items", []))
            if isinstance(payload, dict)
            else payload
        )
        if not isinstance(items, list):
            return [], None
        collected = datetime.now(timezone.utc)
        records: list[StartupRecord | ProductRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("name")
                or item.get("company_name")
                or item.get("companyName")
            )
            href = item.get("url") or item.get("website") or item.get("company_url")
            if not name or not href:
                continue
            source_url = urljoin(page_url, str(href))
            if source_url in seen_urls:
                continue
            if self.kind == "startup":
                employee_count = item.get("employee_count", item.get("team_size"))
                employee_count = (
                    int(employee_count)
                    if isinstance(employee_count, int)
                    or str(employee_count).isdigit()
                    else None
                )
                records.append(
                    StartupRecord(
                        source=Source(name=self.source_name, url=source_url),
                        collectedAt=collected,
                        entityName=str(name),
                        employeeCount=employee_count,
                    )
                )
            else:
                pricing = item.get("pricing_model", item.get("pricingModel"))
                pricing = (
                    pricing
                    if pricing in {"FREE", "FREEMIUM", "PAID", "ENTERPRISE"}
                    else None
                )
                records.append(
                    ProductRecord(
                        source=Source(name=self.source_name, url=source_url),
                        collectedAt=collected,
                        startupName=str(name),
                        pricingModel=pricing,
                    )
                )
        next_url = payload.get("next") if isinstance(payload, dict) else None
        return records, urljoin(page_url, next_url) if next_url else None

    def _parse_json_ld(
        self,
        soup: BeautifulSoup,
        page_url: str,
        collected: datetime,
        seen_urls: set[str],
    ) -> list[StartupRecord | ProductRecord]:
        records: list[StartupRecord | ProductRecord] = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                payload = json.loads(script.string or script.get_text())
            except (TypeError, json.JSONDecodeError):
                continue
            objects = (
                payload.get("itemListElement", [])
                if isinstance(payload, dict) and payload.get("@type") == "ItemList"
                else [payload]
            )
            for entry in objects:
                item = entry.get("item", entry) if isinstance(entry, dict) else {}
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                href = item.get("url")
                if not name or not href:
                    continue
                source_url = urljoin(page_url, href)
                if source_url in seen_urls:
                    continue
                if self.kind == "startup":
                    employee_count = item.get("numberOfEmployees")
                    if isinstance(employee_count, dict):
                        employee_count = employee_count.get("value")
                    employee_count = (
                        int(employee_count)
                        if employee_count is not None
                        and (
                            isinstance(employee_count, int)
                            or str(employee_count).isdigit()
                        )
                        else None
                    )
                    records.append(
                        StartupRecord(
                            source=Source(name=self.source_name, url=source_url),
                            collectedAt=collected,
                            entityName=str(name),
                            employeeCount=employee_count,
                        )
                    )
                elif item.get("@type") in {"Product", "SoftwareApplication"}:
                    pricing = (
                        item.get("offers", {}).get("category")
                        if isinstance(item.get("offers"), dict)
                        else None
                    )
                    pricing = (
                        pricing
                        if pricing in {"FREE", "FREEMIUM", "PAID", "ENTERPRISE"}
                        else None
                    )
                    records.append(
                        ProductRecord(
                            source=Source(name=self.source_name, url=source_url),
                            collectedAt=collected,
                            startupName=str(name),
                            pricingModel=pricing,
                        )
                    )
        return records


class ProductHuntCrawler:
    endpoint = "https://api.producthunt.com/v2/api/graphql"
    query = "query Products($after: String) { posts(first: 100, after: $after, order: NEWEST) { edges { node { id name url } } pageInfo { hasNextPage endCursor } } }"
    public_directory = "https://www.producthunt.com/products"
    product_path = re.compile(r"^/products/([^/?#]+)$")

    @staticmethod
    def _get_token() -> str:
        """Return the Product Hunt API token with leading/trailing whitespace stripped."""
        return os.getenv("PRODUCT_HUNT_TOKEN", "").strip()

    async def crawl(self, limit: int = 1000) -> list[ProductRecord]:
        token = self._get_token()
        if not token:
            raise RuntimeError(
                "PRODUCT_HUNT_TOKEN is required for Product Hunt ingestion"
            )
        records: list[ProductRecord] = []
        seen: set[str] = set()
        after = None
        collected = datetime.now(timezone.utc)
        fetcher = AsyncFetcher()
        async with aiohttp.ClientSession(
            timeout=fetcher.timeout, connector=fetcher.connector()
        ) as session:
            while len(records) < limit:
                async with session.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                    json={"query": self.query, "variables": {"after": after}},
                ) as response:
                    if response.status in {401, 403}:
                        raise RuntimeError(
                            f"Product Hunt API authentication failed (HTTP {response.status}). "
                            "Rotate PRODUCT_HUNT_TOKEN and update .env."
                        )
                    if response.status == 429:
                        raise RuntimeError(
                            "Product Hunt API rate limit reached. "
                            "Retry later or use a valid token with sufficient quota."
                        )
                    response.raise_for_status()
                    payload = await response.json()
                if payload.get("errors"):
                    raise RuntimeError(
                        f"Product Hunt API error: {payload['errors'][0].get('message', 'unknown error')}"
                    )
                posts = payload.get("data", {}).get("posts", {})
                for edge in posts.get("edges", []):
                    product = edge.get("node", {})
                    url = product.get("url")
                    name = product.get("name")
                    if not url or not name or url in seen:
                        continue
                    seen.add(url)
                    records.append(
                        ProductRecord(
                            source=Source(
                                name="Product Hunt",
                                url=url,
                                record_id=(
                                    str(product.get("id"))
                                    if product.get("id")
                                    else None
                                ),
                            ),
                            collectedAt=collected,
                            startupName=name,
                            pricingModel=None,
                        )
                    )
                    if len(records) >= limit:
                        break
                page_info = posts.get("pageInfo", {})
                if not page_info.get("hasNextPage"):
                    break
                after = page_info.get("endCursor")
        return records

    async def crawl_public(self, limit: int = 1000) -> list[ProductRecord]:
        if limit <= 0:
            return []
        fetcher = AsyncFetcher()
        collected = datetime.now(timezone.utc)
        records: list[ProductRecord] = []
        seen: set[str] = set()
        max_pages = max(1, int(os.getenv("PRODUCT_HUNT_MAX_PAGES", "30")))
        page_concurrency = max(
            1, int(os.getenv("PRODUCT_HUNT_PAGE_CONCURRENCY", "5"))
        )

        async def fetch_page(
            session: aiohttp.ClientSession, page_number: int
        ) -> list[ProductRecord]:
            page_url = (
                self.public_directory
                if page_number == 1
                else f"{self.public_directory}?page={page_number}"
            )
            return self._parse_public_page(
                await fetcher.get(session, page_url), collected
            )

        async with aiohttp.ClientSession(
            timeout=fetcher.timeout, connector=fetcher.connector()
        ) as session:
            for first_page in range(1, max_pages + 1, page_concurrency):
                page_numbers = range(
                    first_page, min(first_page + page_concurrency, max_pages + 1)
                )
                pages = await asyncio.gather(
                    *(fetch_page(session, page) for page in page_numbers),
                    return_exceptions=True,
                )
                successful_pages = 0
                for page_records in pages:
                    if isinstance(page_records, BaseException):
                        LOGGER.warning(
                            "product_hunt_public_page_failed error=%s", page_records
                        )
                        continue
                    successful_pages += 1
                    for record in page_records:
                        url = str(record.source.url)
                        if url in seen:
                            continue
                        seen.add(url)
                        records.append(record)
                        if len(records) >= limit:
                            return records
                if successful_pages == 0:
                    break
        return records

    @classmethod
    def _parse_public_page(
        cls, html: str, collected: datetime
    ) -> list[ProductRecord]:
        """Parse only explicit Product Hunt product anchors with an explicit name."""
        records: list[ProductRecord] = []
        page_seen: set[str] = set()
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("a[href]"):
            href = str(link.get("href") or "").split("?", 1)[0].split("#", 1)[0]
            match = cls.product_path.fullmatch(href)
            name = link.get_text(" ", strip=True)
            if not match or not name:
                continue
            url = f"https://www.producthunt.com/products/{match.group(1)}"
            if url in page_seen:
                continue
            page_seen.add(url)
            records.append(
                ProductRecord(
                    source=Source(name="Product Hunt public directory", url=url),
                    collectedAt=collected,
                    startupName=name,
                    pricingModel=None,
                )
            )
        return records


class GitHubProductCrawler:
    """Collect explicit open-source AI software products from GitHub's public API.

    Uses multiple search topic queries to reliably reach the requested limit.
    Each page returns up to 100 results; GitHub search caps each query at 1000
    results (10 pages).  By cycling through several AI-related topics and
    deduplicating by html_url, the crawler can collect well over 1,000 unique
    repositories.
    """

    endpoint = "https://api.github.com/search/repositories"
    # Topics queried in order; cycling allows >1000 unique results.
    _topics = [
        "artificial-intelligence",
        "machine-learning",
        "deep-learning",
        "natural-language-processing",
        "computer-vision",
        "large-language-model",
        "generative-ai",
        "llm",
        "transformers",
        "neural-network",
    ]

    async def crawl(self, limit: int = 1000) -> list[ProductRecord]:
        if limit <= 0:
            return []
        fetcher = AsyncFetcher()
        headers = {"Accept": "application/vnd.github+json"}
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        collected = datetime.now(timezone.utc)
        records: list[ProductRecord] = []
        seen: set[str] = set()
        pages_per_topic = 10  # GitHub search API caps at 1000 results per query
        async with aiohttp.ClientSession(
            timeout=fetcher.timeout, headers=headers, connector=fetcher.connector()
        ) as session:
            for topic in self._topics:
                if len(records) >= limit:
                    break
                for page in range(1, pages_per_topic + 1):
                    if len(records) >= limit:
                        break
                    url = (
                        f"{self.endpoint}?q=topic%3A{topic}"
                        f"&sort=updated&order=desc&per_page=100&page={page}"
                    )
                    try:
                        payload = json.loads(await fetcher.get(session, url))
                    except (
                        aiohttp.ClientError,
                        asyncio.TimeoutError,
                        json.JSONDecodeError,
                    ) as error:
                        LOGGER.warning(
                            "github_product_page_failed topic=%s page=%s error=%s",
                            topic,
                            page,
                            error,
                        )
                        break
                    items = (
                        payload.get("items", [])
                        if isinstance(payload, dict)
                        else []
                    )
                    if not items:
                        break
                    for item in items:
                        name = item.get("full_name") or item.get("name")
                        source_url = item.get("html_url")
                        if not name or not source_url or source_url in seen:
                            continue
                        seen.add(source_url)
                        records.append(
                            ProductRecord(
                                source=Source(
                                    name="GitHub AI software repository",
                                    url=source_url,
                                    record_id=(
                                        str(item.get("id"))
                                        if item.get("id")
                                        else None
                                    ),
                                ),
                                collectedAt=collected,
                                startupName=str(name),
                                pricingModel=None,
                            )
                        )
                        if len(records) >= limit:
                            return records
        return records
