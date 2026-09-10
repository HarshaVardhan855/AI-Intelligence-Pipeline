from datetime import datetime, timezone

from ai_pipeline.schemas import ResearchPaperRecord, Source
from ai_pipeline.utils.dedup import deduplicate_records


def test_records_are_deduplicated_by_source_url():
    collected = datetime.now(timezone.utc)
    first = ResearchPaperRecord(source=Source(name="arXiv", url="https://arxiv.org/abs/1"), collectedAt=collected, title="Paper", authors=["Author"], paper_url="https://arxiv.org/abs/1", published_date=collected)
    assert len(deduplicate_records([first, first.model_copy()])) == 1