import csv
import json
from pathlib import Path
from typing import Any


CONTENT_FIELDS = {
    "STARTUP": ("entityName", "employeeCount"),
    "PRODUCT": ("startupName", "pricingModel"),
    "JOB": ("company", "date", "is_remote", "role_family"),
    "NEWS": ("title", "publication_timestamp", "content", "fields"),
}


def record_to_row(record: Any) -> dict[str, Any]:
    row = record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
    fields = CONTENT_FIELDS.get(row.get("recordType"), ())
    if fields:
        row["content"] = {field: row.pop(field) for field in fields if field in row}
    return row


def export_records(records: dict[str, list[Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, values in records.items():
        rows = [record_to_row(value) for value in values]
        (output_dir / f"{name}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        fields = sorted({field for row in rows for field in row}) if rows else []
        with (output_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
