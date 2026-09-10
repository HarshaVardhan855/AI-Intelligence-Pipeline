from pathlib import Path

from ai_pipeline.entity.resolver import EntityResolver, normalize_name


def test_normalization_and_resolution():
    assert normalize_name("OpenAI, Inc.") == "openai"
    resolver = EntityResolver(Path("data/seed_entities.json"))
    result = resolver.resolve("Open AI")
    assert result.canonical_name == "OpenAI"
    assert result.resolution_method == "exact"


def test_unknowns_remain_unresolved():
    resolver = EntityResolver(Path("data/seed_entities.json"))
    assert resolver.resolve("Definitely Not A Company").canonical_name is None
