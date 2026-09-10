import json
from datetime import datetime, timezone

from ai_pipeline.exporter import export_records
from ai_pipeline.schemas import JobRecord, Source, StartupRecord


def test_exports_assignment_content_shape(tmp_path):
    now = datetime.now(timezone.utc)
    records = {
        "startups": [StartupRecord(source=Source(name="Directory", url="https://example.com/startup"), collectedAt=now, entityName="Verified", employeeCount=None)],
        "jobs": [JobRecord(source=Source(name="Jobs", url="https://example.com/job"), collectedAt=now, company="Verified", date=now)],
    }
    export_records(records, tmp_path)
    startups = json.loads((tmp_path / "startups.json").read_text(encoding="utf-8"))
    jobs = json.loads((tmp_path / "jobs.json").read_text(encoding="utf-8"))
    assert startups[0]["content"] == {"entityName": "Verified", "employeeCount": None}
    assert jobs[0]["content"]["company"] == "Verified"
    assert "entityName" not in startups[0]