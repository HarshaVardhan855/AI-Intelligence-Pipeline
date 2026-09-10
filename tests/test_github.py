from ai_pipeline.crawlers import GitHubVerifier
from ai_pipeline.extraction import LLMOrchestrator


def test_github_candidate_requires_owner_and_repository():
    html = '<a href="https://github.com/example/project">code</a> <a href="https://github.com/example">profile</a>'
    assert GitHubVerifier._candidate(html) == "https://github.com/example/project"


def test_missing_github_link_stays_null():
    assert GitHubVerifier._candidate("<p>No repository</p>") is None


def test_llm_response_parser_accepts_json_fences():
    value = LLMOrchestrator._parse_response("groq", {"choices": [{"message": {"content": "```json\n{\"company\": \"Verified Co\"}\n```"}}]})
    assert value == {"company": "Verified Co"}