from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any, cast
import os
import sys
from pathlib import Path

_SRC_DIR = str(Path(__file__).resolve().parent.parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from dotenv import load_dotenv
from playwright.async_api import Error as PlaywrightError

from ai_pipeline.crawlers import ArxivCrawler, GitHubVerifier, load_verified_csv, validate_verified_csv
from ai_pipeline.schemas import NewsRecord
from ai_pipeline.directory_sources import GitHubProductCrawler, ProductHuntCrawler, PublicDirectoryCrawler, YCStartupCrawler
from ai_pipeline.entity.resolver import EntityResolver
from ai_pipeline.extraction import LLMOrchestrator
from ai_pipeline.exporter import export_records
from ai_pipeline.exporter import record_to_row
from ai_pipeline.final_validation import AcceptanceError, validate_acceptance
from ai_pipeline.feeds import NEWS_FEEDS, crawl_feeds, crawl_job_sources, parse_fresh_news
from ai_pipeline.sheets import write_workbook
from ai_pipeline.storage import SQLiteStore
from ai_pipeline.utils.dedup import deduplicate_records

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Default public source URLs used when --startup-source / --product-source
# are not explicitly provided but a limit > 0 is requested.
DEFAULT_STARTUP_SOURCE = "https://www.ycombinator.com/companies"
DEFAULT_PRODUCT_SOURCE = "https://www.producthunt.com"


async def run(args: argparse.Namespace) -> None:
    load_dotenv()
    output = Path(args.output or os.getenv("OUTPUT_DIR", "data/output"))
    source_events: list[dict] = []
    records: dict[str, list[Any]] = {}

    # --- Startups ---
    if args.startups:
        input_errors = validate_verified_csv(Path(args.startups), "startup")
        if input_errors:
            raise ValueError("Startup CSV validation failed: " + "; ".join(input_errors))
        records["startups"] = load_verified_csv(Path(args.startups), "startup")
    else:
        startup_source = args.startup_source
        # When no explicit startup source is given but a limit is requested,
        # use the default YC public source.
        if not startup_source and args.startup_limit > 0:
            startup_source = DEFAULT_STARTUP_SOURCE
        if startup_source:
            if "ycombinator.com/companies" in startup_source:
                records["startups"] = await YCStartupCrawler(startup_source).crawl(args.startup_limit)
            else:
                records["startups"] = await PublicDirectoryCrawler("configured startup directory", startup_source, "startup").crawl(args.startup_limit)
            if not records.get("startups"):
                logging.warning("startup_source_returned_zero_records source=%s", startup_source)

    # --- Products ---
    if args.products:
        input_errors = validate_verified_csv(Path(args.products), "product")
        if input_errors:
            raise ValueError("Product CSV validation failed: " + "; ".join(input_errors))
        records["products"] = load_verified_csv(Path(args.products), "product")
    else:
        product_source = args.product_source
        # When no explicit product source is given but a limit is requested,
        # use the default Product Hunt + GitHub sources.
        if not product_source and args.product_limit > 0:
            product_source = DEFAULT_PRODUCT_SOURCE
        if product_source:
            if "producthunt.com" in product_source:
                crawler = ProductHuntCrawler()
                token = ProductHuntCrawler._get_token()
                if token:
                    try:
                        records["products"] = await crawler.crawl(args.product_limit)
                    except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as error:
                        source_events.append({"source": "Product Hunt API", "url": product_source, "status": getattr(error, "status", None), "block_type": "authentication_failed" if "authentication" in str(error).lower() else "request_failed", "error": str(error)})
                        records["products"] = await crawler.crawl_public(args.product_limit)
                else:
                    records["products"] = await crawler.crawl_public(args.product_limit)
                if len(records.get("products", [])) < args.product_limit:
                    remaining = args.product_limit - len(records.get("products", []))
                    try:
                        fallback_records = await GitHubProductCrawler().crawl(remaining)
                        records.setdefault("products", []).extend(fallback_records)
                        logging.info("product_hunt_fallback_used product_hunt_records=%s github_product_records=%s", args.product_limit - remaining, len(fallback_records))
                    except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
                        source_events.append({"source": "GitHub AI software repository", "url": GitHubProductCrawler.endpoint, "status": getattr(error, "status", None), "block_type": "request_failed", "error": str(error)})
            else:
                records["products"] = await PublicDirectoryCrawler("configured product directory", product_source, "product").crawl(args.product_limit)
            if not records.get("products"):
                logging.warning("product_source_returned_zero_records source=%s", product_source)

    if args.validate_targets:
        validate_acceptance(records, groups=("startups", "products"))
    papers = await ArxivCrawler().crawl(args.paper_limit)
    if args.github:
        papers = await GitHubVerifier().enrich(papers)
    records["research_papers"] = papers
    records = {name: deduplicate_records(values) for name, values in records.items()}
    if records.get("startups") or records.get("products"):
        resolver = EntityResolver(Path(__file__).parents[2] / "data" / "seed_entities.json")
        names = [record.entityName for record in records.get("startups", [])]
        names.extend(record.startupName for record in records.get("products", []))
        records["entity_mapping"] = [resolver.resolve(name) for name in dict.fromkeys(names)]
    records["news"] = await crawl_feeds(NEWS_FEEDS, parse_fresh_news, source_events)
    records["jobs"] = await crawl_job_sources(source_events)
    if args.validate_targets:
        validate_acceptance(records)
    if args.extract_news:
        orchestrator = LLMOrchestrator()
        for index, record in enumerate(records["news"]):
            news_record: NewsRecord = cast(NewsRecord, record)
            extracted = await orchestrator.extract(news_record.content, {"summary": "string or null", "topics": "array of strings", "companies": "array of strings"})
            records["news"][index] = news_record.model_copy(update={"fields": extracted, "extraction_timestamp": datetime.now(timezone.utc), "extraction_provider": orchestrator.last_provider})
    export_records(records, output)
    write_workbook(records, output / "ai_intelligence_pipeline.xlsx")
    counts = {key: len(value) for key, value in records.items()}
    target_groups = {name: counts.get(name, 0) for name in ("startups", "products", "research_papers")}
    report = {
        "status": "complete" if all(count >= 1000 for count in target_groups.values()) else "incomplete_targets",
        "record_counts": counts,
        "target_counts": target_groups,
        "unique_source_urls": {name: len({str(record.source.url) for record in values if getattr(record, "source", None)}) for name, values in records.items()},
        "source_events": source_events,
    }
    (output / "run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    store = SQLiteStore(output / "pipeline.db")
    for table, values in records.items():
        batch = []
        for index, record in enumerate(values):
            payload = record_to_row(record)
            source = payload.get("source", {})
            batch.append((str(source.get("url") or payload.get("raw_name") or index), payload, source.get("url")))
        if batch:
            store.upsert_records(table, batch)
    store.record_run(counts, source_events)
    store.close()
    logging.info("exported record_counts=%s output=%s", counts, output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect provenance-backed AI intelligence records")
    parser.add_argument("--paper-limit", type=int, default=10)
    parser.add_argument("--github", action="store_true", help="Verify GitHub links found on paper pages")
    parser.add_argument("--startups")
    parser.add_argument("--products")
    parser.add_argument("--startup-source", help="Public paginated startup directory URL")
    parser.add_argument("--product-source", help="Public paginated product directory URL")
    parser.add_argument("--startup-limit", type=int, default=1000)
    parser.add_argument("--product-limit", type=int, default=1000)
    parser.add_argument("--output")
    parser.add_argument("--validate-targets", action="store_true", help="Fail unless 1,000 valid startup, product, and paper records exist")
    parser.add_argument("--extract-news", action="store_true", help="Run configured LLM extraction on fresh news content")
    try:
        asyncio.run(run(parser.parse_args()))
    except (AcceptanceError, RuntimeError, ValueError, FileNotFoundError, PlaywrightError) as error:
        logging.error("%s", error)
        if isinstance(error, AcceptanceError):
            logging.error("Provide verified source files/URLs, or inspect the configured sources and collect more valid unique records before using --validate-targets.")
        elif isinstance(error, RuntimeError):
            if "Product Hunt" in str(error):
                logging.error("Check PRODUCT_HUNT_TOKEN in .env or omit --product-source https://www.producthunt.com.")
            else:
                logging.error("Configure at least one LLM API key in .env before using --extract-news.")
        elif isinstance(error, FileNotFoundError):
            logging.error("Create the referenced CSV file first, or provide an existing verified source file path.")
        elif "Executable doesn't exist" in str(error):
            logging.error("Install the Playwright browser once with: python -m playwright install chromium")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
