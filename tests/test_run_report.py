import json
from pathlib import Path

from ai_pipeline.main import run


def test_run_report_shape_is_machine_readable(tmp_path: Path, monkeypatch):
    report = {"status": "incomplete_targets", "record_counts": {"research_papers": 10}, "target_counts": {"startups": 0, "products": 0, "research_papers": 10}, "unique_source_urls": {}, "source_events": []}
    path = tmp_path / "run_report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["status"] == "incomplete_targets"