import os
import pytest
from docstracker_framework.models import AnalyzerConfig, SectionDiff
from docstracker_framework.analyzer import Analyzer


@pytest.fixture
def analyzer_config():
    api_key = os.environ.get("OPENCODE_API_KEY", "")
    if not api_key:
        pytest.skip("OPENCODE_API_KEY not set")
    return AnalyzerConfig(
        endpoint="https://opencode.ai/zen/go/v1",
        model="deepseek-v4-flash",
        api_key=api_key,
    )


@pytest.mark.integration
def test_analyzer_real_endpoint(analyzer_config):
    analyzer = Analyzer(analyzer_config)
    diffs = [
        SectionDiff(
            heading="Authentication",
            added=["You must now use OAuth 2.0 instead of API keys."],
            removed=["API key authentication is supported."],
        )
    ]
    result = analyzer.analyze_page("https://docs.example.com/auth", diffs)

    assert result.relevance in {"high", "medium", "low"}
    assert result.category in {
        "breaking-change", "behavior-change", "new-feature", "limit-or-quota",
        "clarification", "new-example", "deprecation", "cosmetic",
    }
    assert len(result.summary) > 0
