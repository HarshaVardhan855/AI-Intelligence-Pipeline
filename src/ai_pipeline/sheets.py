from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook

from ai_pipeline.exporter import record_to_row


TAB_NAMES = {
    "startups": "Startups",
    "products": "Products",
    "research_papers": "Research Papers",
    "jobs": "Jobs",
    "news": "News",
    "entity_mapping": "Entity Mapping Log",
}


def write_workbook(records: dict[str, list[Any]], path: Path) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for key, title in TAB_NAMES.items():
        sheet = workbook.create_sheet(title)
        rows = [_as_row(record) for record in records.get(key, [])]
        fields = sorted({field for row in rows for field in row})
        if fields:
            sheet.append(fields)
            for row in rows:
                sheet.append([row.get(field) for field in fields])
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def _as_row(record: Any) -> dict[str, Any]:
    value = record_to_row(record)
    return {key: "; ".join(str(item) for item in value) if isinstance(value, list) else str(value) if isinstance(value, dict) else value for key, value in value.items()}