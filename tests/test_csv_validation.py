from pathlib import Path

from ai_pipeline.crawlers import validate_verified_csv


def test_verified_csv_rejects_duplicate_and_invalid_urls(tmp_path: Path):
    path = tmp_path / "startups.csv"
    path.write_text("name,source_url,source_name,source_record_id,employee_count\nA,https://example.com/a,Source,1,10\nB,https://example.com/a,Source,2,not-a-number\n", encoding="utf-8")
    errors = validate_verified_csv(path, "startup")
    assert any("duplicate source_url" in error for error in errors)
    assert any("employee_count must be an integer" in error for error in errors)


def test_verified_csv_requires_provenance_columns(tmp_path: Path):
    path = tmp_path / "products.csv"
    path.write_text("name,pricing_model\nTool,PAID\n", encoding="utf-8")
    assert validate_verified_csv(path, "product") == ["missing columns: source_name, source_record_id, source_url"]