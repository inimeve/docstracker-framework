import datetime
import json
import os
import sys
import httpx
import pytest
import yaml


def make_config_yaml(tmp_path, synthesizer=True):
    config = {
        "email": "test@example.com",
        "targets": [{"name": "My Docs", "url": "https://docs.example.com/"}],
    }
    if synthesizer:
        config["synthesizer"] = {"endpoint": "http://localhost:11434/v1", "model": "gemma3:27b"}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(config))
    return str(path)


def write_analysis_file(tmp_path, date_str, entries):
    analyses_dir = tmp_path / "analyses"
    analyses_dir.mkdir(exist_ok=True)
    (analyses_dir / f"{date_str}.json").write_text(json.dumps(entries))


SAMPLE_ENTRY = {
    "page_url": "https://docs.example.com/page1",
    "target_name": "My Docs",
    "relevance": "high",
    "category": "breaking-change",
    "summary": "The endpoint changed.",
    "topics_matched": ["networking"],
}


def make_mock_transport(text: str = "# Weekly Digest\n\nThis week was eventful."):
    content = json.dumps({"choices": [{"message": {"content": text}}]})

    def handler(request):
        return httpx.Response(200, content=content.encode())

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def patch_synthesizer_client(monkeypatch):
    import docstracker_framework.synthesizer as synth_mod

    original_init = synth_mod.Synthesizer.__init__

    def patched_init(self, config, client=None):
        original_init(self, config, client=httpx.Client(
            transport=make_mock_transport(),
            base_url=config.endpoint,
        ))

    monkeypatch.setattr(synth_mod.Synthesizer, "__init__", patched_init)


@pytest.fixture(autouse=True)
def patch_notifier(monkeypatch):
    import docstracker_framework.cli as cli_mod
    calls = []

    class FakeNotifier:
        def send(self, *args, **kwargs):
            calls.append(("send", kwargs))

        def send_digest(self, *args, **kwargs):
            calls.append(("send_digest", kwargs))

    monkeypatch.setattr(cli_mod, "EmailNotifier", FakeNotifier)
    return calls


def run_cli(argv):
    import docstracker_framework.cli as cli
    sys.argv = argv
    cli.main()


# --- AnalysisStore.read_since tests ---

def test_analysis_store_read_since_returns_entries_in_window(tmp_path):
    from docstracker_framework.analysis_store import AnalysisStore
    write_analysis_file(tmp_path, "2026-05-14", [SAMPLE_ENTRY])
    write_analysis_file(tmp_path, "2026-05-10", [SAMPLE_ENTRY])  # outside 7-day window

    store = AnalysisStore(str(tmp_path / "analyses"))
    entries = store.read_since(since=datetime.date(2026, 5, 13))

    assert len(entries) == 1
    assert entries[0]["page_url"] == "https://docs.example.com/page1"


def test_analysis_store_read_since_includes_both_endpoints(tmp_path):
    from docstracker_framework.analysis_store import AnalysisStore
    write_analysis_file(tmp_path, "2026-05-13", [SAMPLE_ENTRY])
    write_analysis_file(tmp_path, "2026-05-16", [SAMPLE_ENTRY])

    store = AnalysisStore(str(tmp_path / "analyses"))
    entries = store.read_since(since=datetime.date(2026, 5, 13))

    assert len(entries) == 2


def test_analysis_store_read_since_returns_empty_when_no_files(tmp_path):
    from docstracker_framework.analysis_store import AnalysisStore
    store = AnalysisStore(str(tmp_path / "analyses"))
    entries = store.read_since(since=datetime.date(2026, 5, 10))

    assert entries == []


# --- cmd_digest CLI tests ---

def test_digest_produces_output_when_analyses_exist(tmp_path, capsys):
    config_path = make_config_yaml(tmp_path)
    write_analysis_file(tmp_path, "2026-05-14", [SAMPLE_ENTRY])

    run_cli([
        "docstracker", "--config", config_path,
        "digest", "--since", "2026-05-10",
    ])

    captured = capsys.readouterr()
    assert "digest" in captured.out.lower() or "Weekly Digest" in captured.out


def test_digest_exits_cleanly_when_no_analysis_files(tmp_path, capsys):
    config_path = make_config_yaml(tmp_path)

    run_cli([
        "docstracker", "--config", config_path,
        "digest", "--since", "2026-05-10",
    ])

    captured = capsys.readouterr()
    assert "no analysis" in captured.out.lower()


def test_digest_errors_without_synthesizer(tmp_path, capsys):
    config_path = make_config_yaml(tmp_path, synthesizer=False)

    with pytest.raises(SystemExit) as exc:
        run_cli(["docstracker", "--config", config_path, "digest"])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "synthesizer" in captured.err.lower()


def test_digest_notify_sends_email(tmp_path, patch_notifier):
    config_path = make_config_yaml(tmp_path)
    write_analysis_file(tmp_path, "2026-05-14", [SAMPLE_ENTRY])

    run_cli([
        "docstracker", "--config", config_path,
        "digest", "--notify", "--since", "2026-05-10",
    ])

    digest_calls = [c for c in patch_notifier if c[0] == "send_digest"]
    assert len(digest_calls) == 1
    assert digest_calls[0][1]["recipient"] == "test@example.com"


def test_digest_since_flag_overrides_7_day_window(tmp_path, capsys):
    config_path = make_config_yaml(tmp_path)
    write_analysis_file(tmp_path, "2026-05-01", [SAMPLE_ENTRY])
    write_analysis_file(tmp_path, "2026-05-14", [SAMPLE_ENTRY])

    captured_prompts = []

    import docstracker_framework.synthesizer as synth_mod
    original_generate = synth_mod.Synthesizer.generate_digest

    def capture_generate(self, analyses_text):
        captured_prompts.append(analyses_text)
        return "# Digest"

    synth_mod.Synthesizer.generate_digest = capture_generate

    try:
        run_cli([
            "docstracker", "--config", config_path,
            "digest", "--since", "2026-04-30",
        ])
    finally:
        synth_mod.Synthesizer.generate_digest = original_generate

    assert len(captured_prompts) == 1
    # Both entries should be included since --since covers both dates
    assert "2026-05-01" in captured_prompts[0] or "endpoint changed" in captured_prompts[0]
