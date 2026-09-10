from datetime import datetime, timedelta, timezone
import json
import re

from bs4 import BeautifulSoup
import dateparser


_RELATIVE = re.compile(r"^(?P<amount>\d+)\s+(?P<unit>minute|minutes|hour|hours|day|days)\s+ago$", re.I)


def parse_date(value: str | int | float | datetime | None, now: datetime | None = None) -> datetime | None:
    if value is None:
        return None
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if text.lower() == "yesterday":
            parsed = now - timedelta(days=1)
        else:
            match = _RELATIVE.match(text)
            if match:
                amount = int(match.group("amount"))
                unit = match.group("unit").lower()
                delta = {"minutes": amount} if unit.startswith("minute") else {"hours": amount} if unit.startswith("hour") else {"days": amount}
                parsed = now - timedelta(**delta)
            else:
                parsed = dateparser.parse(text, settings={"RETURN_AS_TIMEZONE_AWARE": True, "TIMEZONE": "UTC", "TO_TIMEZONE": "UTC"})
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_fresh(value: str | int | float | datetime | None, now: datetime | None = None, max_age_hours: int = 24) -> bool:
    parsed = parse_date(value, now)
    if parsed is None:
        return False
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = current - parsed
    return timedelta(0) <= age <= timedelta(hours=max_age_hours)


def extract_date_from_html(html: str, now: datetime | None = None) -> datetime | None:
    """Extract a publication date conservatively from common page metadata."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str | int | float] = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        objects = data if isinstance(data, list) else [data]
        for item in objects:
            if isinstance(item, dict):
                for key in ("datePublished", "dateCreated", "uploadDate"):
                    if item.get(key):
                        candidates.append(item[key])

    for selector in (
        {"name": "date"},
        {"name": "publish_date"},
        {"name": "published_time"},
        {"property": "article:published_time"},
        {"property": "og:published_time"},
    ):
        tag = soup.find("meta", attrs=selector)
        if tag and tag.get("content"):
            candidates.append(tag["content"])

    for tag in soup.find_all("time"):
        candidates.extend(value for value in (tag.get("datetime"), tag.get_text(" ", strip=True)) if value)

    visible_text = soup.get_text(" ", strip=True)
    relative = re.search(r"\b(?:\d+\s+(?:minutes?|hours?|days?)\s+ago|yesterday)\b", visible_text, re.I)
    if relative:
        candidates.append(relative.group(0))

    for candidate in candidates:
        parsed = parse_date(candidate, now)
        if parsed:
            return parsed
    return None
