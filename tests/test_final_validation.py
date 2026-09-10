from datetime import datetime, timezone

import pytest

from ai_pipeline.final_validation import AcceptanceError, validate_acceptance
from ai_pipeline.schemas import ResearchPaperRecord, Source


def test_acceptance_validator_rejects_missing_target_groups():
    with pytest.raises(AcceptanceError, match="startups: 0 records"):
        validate_acceptance({"research_papers": []})


def test_acceptance_validator_accepts_complete_paper_record():
    collected = datetime.now(timezone.utc)
    paper = ResearchPaperRecord(source=Source(name="arXiv", url="https://arxiv.org/abs/1"), collectedAt=collected, title="Paper", authors=["Author"], paper_url="https://arxiv.org/abs/1", published_date=collected)
    with pytest.raises(AcceptanceError, match="startups: 0 records"):
        validate_acceptance({"research_papers": [paper]})