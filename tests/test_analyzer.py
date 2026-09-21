import json
import httpx
import pytest
from docstracker_framework.models import AnalyzerConfig, SectionDiff, PageAnalysis, NavNodeAdded, NavNodeRemoved, NavNodeRenamed
from docstracker_framework.analyzer import Analyzer


def make_config(**kwargs):
    defaults = dict(endpoint="http://localhost:11434/v1", model="gemma3:4b", api_key="")
    return AnalyzerConfig(**{**defaults, **kwargs})


def test_analyzer_instantiates_from_config():
    config = make_config()
    analyzer = Analyzer(config)
    assert analyzer is not None


def test_analyzer_uses_injected_client():
    config = make_config()
    mock_client = httpx.Client()
    analyzer = Analyzer(config, client=mock_client)
    assert analyzer._client is mock_client


def make_mock_transport(payload: dict):
    content = json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]})

    def handler(request):
        return httpx.Response(200, content=content.encode())

    return httpx.MockTransport(handler)


def test_analyze_page_returns_page_analysis():
    payload = {
        "relevance": "high",
        "category": "breaking-change",
        "summary": "The endpoint signature changed.",
    }
    client = httpx.Client(transport=make_mock_transport(payload), base_url="http://localhost:11434/v1")
    analyzer = Analyzer(make_config(), client=client)
    diffs = [SectionDiff(heading="Auth", added=["new line"], removed=[])]

    result = analyzer.analyze_page("https://docs.example.com/page", diffs)

    assert isinstance(result, PageAnalysis)
    assert result.page_url == "https://docs.example.com/page"
    assert result.relevance == "high"
    assert result.category == "breaking-change"
    assert result.summary == "The endpoint signature changed."


def test_analyze_page_raises_when_all_diffs_are_whitespace():
    analyzer = Analyzer(make_config(), client=httpx.Client(transport=make_mock_transport({}), base_url="http://localhost"))
    diffs = [SectionDiff(heading="Auth", added=["   ", "\t"], removed=[""])]

    with pytest.raises(ValueError, match="no meaningful diffs"):
        analyzer.analyze_page("https://docs.example.com/page", diffs)


def test_analyze_page_raises_on_missing_field():
    payload = {"relevance": "high", "category": "clarification"}  # missing summary
    client = httpx.Client(transport=make_mock_transport(payload), base_url="http://localhost:11434/v1")
    analyzer = Analyzer(make_config(), client=client)
    diffs = [SectionDiff(heading="Intro", added=["something"], removed=[])]

    with pytest.raises(ValueError, match="missing field"):
        analyzer.analyze_page("https://docs.example.com/page", diffs)


def test_analyze_page_raises_on_invalid_enum_value():
    payload = {"relevance": "critical", "category": "clarification", "summary": "Something changed."}
    client = httpx.Client(transport=make_mock_transport(payload), base_url="http://localhost:11434/v1")
    analyzer = Analyzer(make_config(), client=client)
    diffs = [SectionDiff(heading="Intro", added=["something"], removed=[])]

    with pytest.raises(ValueError, match="invalid relevance"):
        analyzer.analyze_page("https://docs.example.com/page", diffs)


def test_analyze_page_request_shape_and_whitespace_filtering():
    payload = {"relevance": "low", "category": "cosmetic", "summary": "Minor wording."}
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:11434/v1")
    analyzer = Analyzer(make_config(), client=client)
    diffs = [
        SectionDiff(heading="Real", added=["real content"], removed=[]),
        SectionDiff(heading="Empty", added=["   "], removed=[""]),
    ]

    analyzer.analyze_page("https://docs.example.com/page", diffs)

    assert captured["url"].endswith("/chat/completions")
    assert captured["body"]["response_format"] == {"type": "json_object"}
    prompt = captured["body"]["messages"][0]["content"]
    assert "real content" in prompt
    assert "Empty" not in prompt


def test_analyze_page_with_topics_includes_them_in_prompt():
    payload = {
        "relevance": "high",
        "category": "new-feature",
        "summary": "Networking config changed.",
        "topics_matched": ["networking"],
    }
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:11434/v1")
    analyzer = Analyzer(make_config(), client=client)
    diffs = [SectionDiff(heading="Network", added=["VNet peering now supported"], removed=[])]

    result = analyzer.analyze_page("https://docs.example.com/page", diffs, topics=["networking", "regional availability"])

    prompt = captured["body"]["messages"][0]["content"]
    assert "networking" in prompt
    assert "regional availability" in prompt
    assert result.topics_matched == ["networking"]


def test_analyze_page_without_topics_returns_empty_topics_matched():
    payload = {
        "relevance": "low",
        "category": "cosmetic",
        "summary": "Minor change.",
    }
    client = httpx.Client(transport=make_mock_transport(payload), base_url="http://localhost:11434/v1")
    analyzer = Analyzer(make_config(), client=client)
    diffs = [SectionDiff(heading="Intro", added=["text"], removed=[])]

    result = analyzer.analyze_page("https://docs.example.com/page", diffs)

    assert result.topics_matched == []


# --- Navigation change analysis ---

def test_analyze_nav_changes_returns_page_analysis():
    payload = {
        "relevance": "high",
        "category": "new-feature",
        "summary": "New top-level section 'Best practices' added.",
    }
    client = httpx.Client(transport=make_mock_transport(payload), base_url="http://localhost:11434/v1")
    analyzer = Analyzer(make_config(), client=client)
    nav_changes = [
        NavNodeAdded(title="Best practices", url="https://docs.example.com/best-practices"),
    ]

    result = analyzer.analyze_nav_changes("https://docs.example.com/", nav_changes)

    assert isinstance(result, PageAnalysis)
    assert result.page_url == "https://docs.example.com/"
    assert result.relevance == "high"
    assert result.category == "new-feature"
    assert result.summary == "New top-level section 'Best practices' added."


def test_analyze_nav_changes_sends_nav_specific_prompt():
    payload = {"relevance": "low", "category": "cosmetic", "summary": "Minor reorder."}
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:11434/v1")
    analyzer = Analyzer(make_config(), client=client)
    nav_changes = [
        NavNodeAdded(title="Best practices"),
        NavNodeRemoved(title="Legacy guide"),
        NavNodeRenamed(old_title="API reference", new_title="Reference"),
    ]

    analyzer.analyze_nav_changes("https://docs.example.com/", nav_changes)

    prompt = captured["body"]["messages"][0]["content"]
    assert "navigation" in prompt.lower()
    assert "+ Added: Best practices" in prompt
    assert "- Removed: Legacy guide" in prompt
    assert "~ Renamed: API reference → Reference" in prompt
    # must NOT contain page-diff markers
    assert "Section diffs" not in prompt
