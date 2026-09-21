import json
import httpx
import pytest
from docstracker_framework.models import AnalyzerConfig
from docstracker_framework.synthesizer import Synthesizer


def make_config(**kwargs):
    defaults = dict(endpoint="http://localhost:11434/v1", model="gemma3:27b", api_key="")
    return AnalyzerConfig(**{**defaults, **kwargs})


def make_mock_transport(text: str):
    content = json.dumps({"choices": [{"message": {"content": text}}]})

    def handler(request):
        return httpx.Response(200, content=content.encode())

    return httpx.MockTransport(handler)


def test_synthesizer_instantiates_from_config():
    config = make_config()
    synth = Synthesizer(config)
    assert synth is not None


def test_synthesizer_uses_long_read_timeout_for_slow_model_responses():
    synth = Synthesizer(make_config())

    assert synth._client.timeout.connect == 30.0
    assert synth._client.timeout.read == 900.0
    assert synth._client.timeout.write == 60.0
    assert synth._client.timeout.pool == 30.0


def test_synthesizer_uses_injected_client():
    config = make_config()
    mock_client = httpx.Client()
    synth = Synthesizer(config, client=mock_client)
    assert synth._client is mock_client


def test_generate_overview_returns_markdown_string():
    markdown = "# Overview\n\n## Scope\n\nThis target covers authentication APIs."
    client = httpx.Client(transport=make_mock_transport(markdown), base_url="http://localhost:11434/v1")
    synth = Synthesizer(make_config(), client=client)

    result = synth.generate_overview("My Target", "some page content")

    assert isinstance(result, str)
    assert result == markdown


def test_generate_overview_posts_to_chat_completions():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps({"choices": [{"message": {"content": "# Overview"}}]}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:11434/v1")
    synth = Synthesizer(make_config(), client=client)

    synth.generate_overview("My Target", "some page content")

    assert captured["url"].endswith("/chat/completions")
    prompt = captured["body"]["messages"][0]["content"]
    assert "My Target" in prompt
    assert "some page content" in prompt


def test_generate_overview_raises_on_http_error():
    def handler(request):
        return httpx.Response(500, content=b"Internal Server Error")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:11434/v1")
    synth = Synthesizer(make_config(), client=client)

    with pytest.raises(httpx.HTTPStatusError):
        synth.generate_overview("My Target", "some content")


def make_digest_transport(bullets: list):
    body = json.dumps({"choices": [{"message": {"content": json.dumps({"bullets": bullets})}}]})

    def handler(request):
        return httpx.Response(200, content=body.encode())

    return httpx.MockTransport(handler)


def test_synthesize_run_digest_returns_bullets():
    bullets = [
        {"rel": "high", "text": "RBAC roles renamed across 71 pages."},
        {"rel": "medium", "text": "Update scripts referencing role names."},
    ]
    client = httpx.Client(transport=make_digest_transport(bullets), base_url="http://localhost:11434/v1")
    synth = Synthesizer(make_config(), client=client)

    changes = [
        {"page_url": "https://example.com/rbac", "relevance": "high", "category": "breaking-change", "summary": "Role renamed."},
    ]
    result = synth.synthesize_run_digest(changes)

    assert result == bullets


def test_synthesize_run_digest_includes_changes_in_prompt():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        body = json.dumps({"choices": [{"message": {"content": json.dumps({"bullets": []})}}]})
        return httpx.Response(200, content=body.encode())

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:11434/v1")
    synth = Synthesizer(make_config(), client=client)

    changes = [{"page_url": "https://example.com/page", "relevance": "high", "summary": "Something changed."}]
    synth.synthesize_run_digest(changes)

    prompt = captured["body"]["messages"][0]["content"]
    assert "https://example.com/page" in prompt
    assert "Something changed." in prompt


def test_synthesize_run_digest_raises_on_http_error():
    def handler(request):
        return httpx.Response(500, content=b"Internal Server Error")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:11434/v1")
    synth = Synthesizer(make_config(), client=client)

    with pytest.raises(httpx.HTTPStatusError):
        synth.synthesize_run_digest([{"page_url": "https://example.com", "summary": "x"}])
