from datetime import datetime, timezone

from ai_pipeline.schemas import NewsRecord, Source
from ai_pipeline.extraction import LLMOrchestrator


def test_news_record_can_store_structured_extraction_fields():
    now = datetime.now(timezone.utc)
    record = NewsRecord(source=Source(name="News", url="https://example.com/article"), collectedAt=now, title="AI", publication_timestamp=now, content="Verified article text", fields={"summary": "A summary"}, extraction_timestamp=now, extraction_provider="configured-fallback-chain")
    assert record.fields["summary"] == "A summary"
    assert record.content == "Verified article text"


def test_orchestrator_starts_without_provider_claim():
    orchestrator = LLMOrchestrator()
    assert orchestrator.last_provider is None