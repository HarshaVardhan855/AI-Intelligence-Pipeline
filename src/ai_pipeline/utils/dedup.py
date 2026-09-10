from collections.abc import Iterable
from typing import Any


def deduplicate_records(records: Iterable[Any]) -> list[Any]:
    unique: dict[str, Any] = {}
    for record in records:
        source = getattr(record, "source", None)
        source_url = getattr(source, "url", None)
        key = str(source_url) if source_url else str(record)
        unique.setdefault(key, record)
    return list(unique.values())
