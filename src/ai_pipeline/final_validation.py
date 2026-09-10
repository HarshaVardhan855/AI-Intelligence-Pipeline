from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


class AcceptanceError(ValueError):
    pass


def validate_acceptance(records: dict[str, list[Any]], minimum: int = 1000, groups: tuple[str, ...] = ("startups", "products", "research_papers")) -> None:
    problems: list[str] = []
    for group in groups:
        values = records.get(group, [])
        if len(values) < minimum:
            problems.append(f"{group}: {len(values)} records, need at least {minimum}")
        urls = [str(record.source.url) for record in values if getattr(record, "source", None)]
        if len(urls) != len(set(urls)):
            problems.append(f"{group}: duplicate source URLs found")
        for url in urls:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                problems.append(f"{group}: invalid source URL {url}")
    for record in records.get("research_papers", []) if "research_papers" in groups else []:
        if not record.title or not record.authors or not record.paper_url or not record.published_date:
            problems.append("research_papers: missing required paper field")
    if problems:
        raise AcceptanceError("Acceptance validation failed: " + "; ".join(problems))
