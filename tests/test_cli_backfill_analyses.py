import json
import sys
import httpx
import pytest
import yaml


SAMPLE_RECORD = {
    "date": "2026-09-07",
    "targets": [
        {
            "target_name": "My Docs",
            "pages": [
                {
                    "type": "modified",
                    "url": "https://docs.example.com/page1",
                    "diffs": [
                        {"heading": "Auth", "added": ["new line"], "removed": ["old line"]}
                    ],
                },
                {
                    "type": "new",
                    "url": "https://docs.example.com/page2",
                    "sections": [{"heading": "Intro", "body": "Hello"}],
                },
            ],
        }
    ],
}

SAMPLE_ANALYSIS_PAYLOAD = {
    "relevance": "high",
    "category": "breaking-change",
    "summary": "The auth flow changed.",
}

SAMPLE_DIGEST = [{"rel": "high", "text": "Algo importante cambió."}]


def write_run_analyses_file(tmp_path, date_str, record):
    d = tmp_path / "run_analyses"
    d.mkdir(exist_ok=True)
    (d / f"{date_str}.json").write_text(json.dumps(record))


def make_config_yaml(tmp_path, synthesizer=True, analyzer=True):
    config = {
        "email": "test@example.com",
        "targets": [{"name": "My Docs", "url": "https://docs.example.com/"}],
    }
    if synthesizer:
        config["synthesizer"] = {"endpoint": "http://localhost:11434/v1", "model": "gemma3:27b"}
    if analyzer:
        config["analyzer"] = {"endpoint": "http://localhost:11434/v1", "model": "gemma3:27b"}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(config))
    return str(path)


def make_mock_analyzer_transport(payload=None):
    if payload is None:
        payload = SAMPLE_ANALYSIS_PAYLOAD
    content = json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]})

    def handler(request):
        return httpx.Response(200, content=content.encode())

    return httpx.MockTransport(handler)


def make_mock_synthesizer_transport(bullets=None):
    if bullets is None:
        bullets = SAMPLE_DIGEST
    content = json.dumps({"choices": [{"message": {"content": json.dumps({"bullets": bullets})}}]})

    def handler(request):
        return httpx.Response(200, content=content.encode())

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def patch_clients(monkeypatch):
    import docstracker_framework.analyzer as analyzer_mod
    import docstracker_framework.synthesizer as synth_mod

    original_analyzer_init = analyzer_mod.Analyzer.__init__

    def patched_analyzer_init(self, config, client=None):
        original_analyzer_init(self, config, client=httpx.Client(
            transport=make_mock_analyzer_transport(),
            base_url=config.endpoint,
        ))

    original_synth_init = synth_mod.Synthesizer.__init__

    def patched_synth_init(self, config, client=None):
        original_synth_init(self, config, client=httpx.Client(
            transport=make_mock_synthesizer_transport(),
            base_url=config.endpoint,
        ))

    monkeypatch.setattr(analyzer_mod.Analyzer, "__init__", patched_analyzer_init)
    monkeypatch.setattr(synth_mod.Synthesizer, "__init__", patched_synth_init)


def run_cli(argv):
    import docstracker_framework.cli as cli
    sys.argv = argv
    cli.main()


def test_backfill_analyses_errors_when_no_analyzer_configured(tmp_path, capsys):
    config_path = make_config_yaml(tmp_path, analyzer=False)
    write_run_analyses_file(tmp_path, "2026-09-07", SAMPLE_RECORD)

    with pytest.raises(SystemExit) as exc:
        run_cli(["docstracker", "--config", config_path, "backfill-analyses", "--dates", "2026-09-07"])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "analyzer" in captured.err.lower()


def test_backfill_analyses_skips_missing_date_file(tmp_path, capsys):
    config_path = make_config_yaml(tmp_path)

    run_cli(["docstracker", "--config", config_path, "backfill-analyses", "--dates", "2026-09-07"])

    captured = capsys.readouterr()
    assert "no run_analyses file found" in captured.out.lower()


def test_backfill_analyses_fills_missing_page_analysis_and_digest(tmp_path):
    config_path = make_config_yaml(tmp_path)
    write_run_analyses_file(tmp_path, "2026-09-07", SAMPLE_RECORD)

    run_cli(["docstracker", "--config", config_path, "backfill-analyses", "--dates", "2026-09-07"])

    from docstracker_framework.run_analysis_store import RunAnalysisStore
    record = RunAnalysisStore(str(tmp_path / "run_analyses")).read("2026-09-07")

    modified_page = record["targets"][0]["pages"][0]
    assert modified_page["analysis"]["relevance"] == "high"
    assert modified_page["analysis"]["category"] == "breaking-change"
    assert record["run_digest"] == SAMPLE_DIGEST


def test_backfill_analyses_skips_new_pages(tmp_path):
    config_path = make_config_yaml(tmp_path)
    write_run_analyses_file(tmp_path, "2026-09-07", SAMPLE_RECORD)

    run_cli(["docstracker", "--config", config_path, "backfill-analyses", "--dates", "2026-09-07"])

    from docstracker_framework.run_analysis_store import RunAnalysisStore
    record = RunAnalysisStore(str(tmp_path / "run_analyses")).read("2026-09-07")

    new_page = record["targets"][0]["pages"][1]
    assert "analysis" not in new_page


def test_backfill_analyses_is_idempotent_and_preserves_existing_analysis(tmp_path):
    config_path = make_config_yaml(tmp_path)
    record = json.loads(json.dumps(SAMPLE_RECORD))
    record["targets"][0]["pages"][0]["analysis"] = {
        "relevance": "low", "category": "cosmetic", "summary": "Already analyzed.", "topics_matched": [],
    }
    write_run_analyses_file(tmp_path, "2026-09-07", record)

    run_cli(["docstracker", "--config", config_path, "backfill-analyses", "--dates", "2026-09-07"])

    captured_out = "nothing to backfill"
    from docstracker_framework.run_analysis_store import RunAnalysisStore
    stored = RunAnalysisStore(str(tmp_path / "run_analyses")).read("2026-09-07")
    # existing analysis untouched, no digest generated since nothing new was backfilled
    assert stored["targets"][0]["pages"][0]["analysis"]["relevance"] == "low"
    assert "run_digest" not in stored


def test_backfill_analyses_handles_multiple_dates(tmp_path):
    config_path = make_config_yaml(tmp_path)
    write_run_analyses_file(tmp_path, "2026-09-07", SAMPLE_RECORD)
    record_09 = json.loads(json.dumps(SAMPLE_RECORD))
    record_09["date"] = "2026-09-09"
    write_run_analyses_file(tmp_path, "2026-09-09", record_09)

    run_cli(["docstracker", "--config", config_path, "backfill-analyses", "--dates", "2026-09-07,2026-09-09"])

    from docstracker_framework.run_analysis_store import RunAnalysisStore
    store = RunAnalysisStore(str(tmp_path / "run_analyses"))
    assert store.read("2026-09-07")["run_digest"] == SAMPLE_DIGEST
    assert store.read("2026-09-09")["run_digest"] == SAMPLE_DIGEST
