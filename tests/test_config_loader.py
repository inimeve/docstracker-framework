import textwrap
import pytest
from docstracker_framework.config_loader import load_config
from docstracker_framework.models import AnalyzerConfig
from docstracker_framework.watch_targets import DuplicateWatchTargetName


def write_config(tmp_path, content: str) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(content))
    return str(path)


def test_parses_email_and_targets(tmp_path):
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Foundry Docs
            url: https://learn.microsoft.com/en-us/azure/foundry/
    """)
    config = load_config(path)
    assert config.email == "user@gmail.com"
    assert len(config.targets) == 1
    assert config.targets[0].name == "Foundry Docs"
    assert config.targets[0].url == "https://learn.microsoft.com/en-us/azure/foundry/"


def test_max_pages_defaults_to_500(tmp_path):
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Docs
            url: https://example.com/docs/
    """)
    config = load_config(path)
    assert config.targets[0].max_pages == 500


def test_explicit_max_pages_is_respected(tmp_path):
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Docs
            url: https://example.com/docs/
            max_pages: 50
    """)
    config = load_config(path)
    assert config.targets[0].max_pages == 50


def test_loads_analyzer_block(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Docs
            url: https://example.com/docs/
        analyzer:
          endpoint: "http://localhost:11434/v1"
          model: "gemma3:4b"
    """)
    config = load_config(path)
    assert isinstance(config.analyzer, AnalyzerConfig)
    assert config.analyzer.endpoint == "http://localhost:11434/v1"
    assert config.analyzer.model == "gemma3:4b"
    assert config.analyzer.api_key == ""


def test_analyzer_absent_when_block_missing(tmp_path):
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Docs
            url: https://example.com/docs/
    """)
    config = load_config(path)
    assert config.analyzer is None


def test_api_key_read_from_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-secret")
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Docs
            url: https://example.com/docs/
        analyzer:
          endpoint: "https://opencode.ai/zen/go/v1"
          model: "deepseek-v4-flash"
    """)
    config = load_config(path)
    assert config.analyzer.api_key == "sk-secret"


def test_api_key_empty_when_env_var_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Docs
            url: https://example.com/docs/
        analyzer:
          endpoint: "https://opencode.ai/zen/go/v1"
          model: "deepseek-v4-flash"
    """)
    config = load_config(path)
    assert config.analyzer.api_key == ""


def test_synthesizer_block_loads_as_analyzer_config(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Docs
            url: https://example.com/docs/
        synthesizer:
          endpoint: "http://localhost:11434/v1"
          model: "llama3:8b"
    """)
    config = load_config(path)
    assert isinstance(config.synthesizer, AnalyzerConfig)
    assert config.synthesizer.endpoint == "http://localhost:11434/v1"
    assert config.synthesizer.model == "llama3:8b"
    assert config.synthesizer.api_key == ""


def test_synthesizer_absent_when_block_missing(tmp_path):
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Docs
            url: https://example.com/docs/
    """)
    config = load_config(path)
    assert config.synthesizer is None


def test_duplicate_target_names_raise_on_load(tmp_path):
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Docs
            url: https://example.com/docs/
          - name: Docs
            url: https://example.com/other/
    """)
    with pytest.raises(DuplicateWatchTargetName) as exc_info:
        load_config(path)
    assert exc_info.value.name == "Docs"


def test_topics_parsed_per_watch_target(tmp_path):
    path = write_config(tmp_path, """
        email: user@gmail.com
        targets:
          - name: Foundry Docs
            url: https://example.com/docs/
            topics:
              - networking
              - regional availability
          - name: Stripe Docs
            url: https://stripe.example.com/docs/
    """)
    config = load_config(path)
    assert config.targets[0].topics == ["networking", "regional availability"]
    assert config.targets[1].topics == []
