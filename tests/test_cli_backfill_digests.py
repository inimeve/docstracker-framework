import json
import sys
import httpx
import pytest
import yaml


SAMPLE_ENTRY = {
    "page_url": "https://docs.example.com/page1",
    "target_name": "My Docs",
    "relevance": "high",
    "category": "new-feature",
    "summary": "Something changed.",
    "topics_matched": [],
}

SAMPLE_DIGEST = [{"rel": "high", "text": "Algo importante cambió."}]


def write_flat_file(tmp_path, date_str, entries):
    d = tmp_path / "analyses"
    d.mkdir(exist_ok=True)
    (d / f"{date_str}.json").write_text(json.dumps(entries))


def write_wrapped_file(tmp_path, date_str, entries, digest):
    d = tmp_path / "analyses"
    d.mkdir(exist_ok=True)
    (d / f"{date_str}.json").write_text(json.dumps({"entries": entries, "digest": digest}))


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


def make_mock_synthesizer_transport(bullets=None):
    if bullets is None:
        bullets = SAMPLE_DIGEST
    content = json.dumps({"choices": [{"message": {"content": json.dumps({"bullets": bullets})}}]})

    def handler(request):
        return httpx.Response(200, content=content.encode())

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def patch_synthesizer_client(monkeypatch):
    import docstracker_framework.synthesizer as synth_mod

    original_init = synth_mod.Synthesizer.__init__

    def patched_init(self, config, client=None):
        original_init(self, config, client=httpx.Client(
            transport=make_mock_synthesizer_transport(),
            base_url=config.endpoint,
        ))

    monkeypatch.setattr(synth_mod.Synthesizer, "__init__", patched_init)


def run_cli(argv):
    import docstracker_framework.cli as cli
    sys.argv = argv
    cli.main()


# --- AnalysisStore.read_run ---

def test_read_run_flat_file_returns_entries_and_no_digest(tmp_path):
    from docstracker_framework.analysis_store import AnalysisStore
    write_flat_file(tmp_path, "2026-05-08", [SAMPLE_ENTRY])

    store = AnalysisStore(str(tmp_path / "analyses"))
    entries, digest = store.read_run("2026-05-08")

    assert entries == [SAMPLE_ENTRY]
    assert digest is None


def test_read_run_wrapped_file_returns_entries_and_digest(tmp_path):
    from docstracker_framework.analysis_store import AnalysisStore
    write_wrapped_file(tmp_path, "2026-05-08", [SAMPLE_ENTRY], SAMPLE_DIGEST)

    store = AnalysisStore(str(tmp_path / "analyses"))
    entries, digest = store.read_run("2026-05-08")

    assert entries == [SAMPLE_ENTRY]
    assert digest == SAMPLE_DIGEST


def test_backfill_errors_when_no_synthesizer_or_analyzer(tmp_path, capsys):
    config_path = make_config_yaml(tmp_path, synthesizer=False, analyzer=False)
    write_flat_file(tmp_path, "2026-05-08", [SAMPLE_ENTRY])

    with pytest.raises(SystemExit) as exc:
        run_cli(["docstracker", "--config", config_path, "backfill-digests"])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "synthesizer" in captured.err.lower() or "analyzer" in captured.err.lower()


def test_backfill_date_flag_targets_single_file(tmp_path):
    config_path = make_config_yaml(tmp_path)
    write_flat_file(tmp_path, "2026-05-08", [SAMPLE_ENTRY])
    write_flat_file(tmp_path, "2026-05-09", [SAMPLE_ENTRY])

    run_cli(["docstracker", "--config", config_path, "backfill-digests", "--date", "2026-05-08"])

    from docstracker_framework.analysis_store import AnalysisStore
    store = AnalysisStore(str(tmp_path / "analyses"))
    _, digest_08 = store.read_run("2026-05-08")
    _, digest_09 = store.read_run("2026-05-09")
    assert digest_08 == SAMPLE_DIGEST
    assert digest_09 is None


def test_backfill_force_overwrites_existing_digest(tmp_path):
    config_path = make_config_yaml(tmp_path)
    old_digest = [{"rel": "low", "text": "Viejo."}]
    write_wrapped_file(tmp_path, "2026-05-08", [SAMPLE_ENTRY], old_digest)

    run_cli(["docstracker", "--config", config_path, "backfill-digests", "--force"])

    from docstracker_framework.analysis_store import AnalysisStore
    _, digest = AnalysisStore(str(tmp_path / "analyses")).read_run("2026-05-08")
    assert digest == SAMPLE_DIGEST


def test_backfill_synthesizes_digest_for_file_missing_one(tmp_path, capsys):
    config_path = make_config_yaml(tmp_path)
    write_flat_file(tmp_path, "2026-05-08", [SAMPLE_ENTRY])

    run_cli(["docstracker", "--config", config_path, "backfill-digests"])

    from docstracker_framework.analysis_store import AnalysisStore
    _, digest = AnalysisStore(str(tmp_path / "analyses")).read_run("2026-05-08")
    assert digest == SAMPLE_DIGEST
    captured = capsys.readouterr()
    assert "done" in captured.out.lower()


def test_write_digest_on_wrapped_file_overwrites_digest_preserves_entries(tmp_path):
    from docstracker_framework.analysis_store import AnalysisStore
    old_digest = [{"rel": "low", "text": "Viejo."}]
    write_wrapped_file(tmp_path, "2026-05-08", [SAMPLE_ENTRY], old_digest)

    store = AnalysisStore(str(tmp_path / "analyses"))
    store.write_digest("2026-05-08", SAMPLE_DIGEST)

    entries, digest = store.read_run("2026-05-08")
    assert entries == [SAMPLE_ENTRY]
    assert digest == SAMPLE_DIGEST


# --- cmd_backfill_digests CLI ---

def test_backfill_skips_files_that_already_have_digest(tmp_path, capsys):
    config_path = make_config_yaml(tmp_path)
    write_wrapped_file(tmp_path, "2026-05-08", [SAMPLE_ENTRY], SAMPLE_DIGEST)

    run_cli(["docstracker", "--config", config_path, "backfill-digests"])

    captured = capsys.readouterr()
    assert "nothing to backfill" in captured.out.lower()
    # digest unchanged
    from docstracker_framework.analysis_store import AnalysisStore
    _, digest = AnalysisStore(str(tmp_path / "analyses")).read_run("2026-05-08")
    assert digest == SAMPLE_DIGEST


def test_backfill_limit_processes_only_most_recent(tmp_path):
    config_path = make_config_yaml(tmp_path)
    for date in ["2026-05-01", "2026-05-02", "2026-05-03"]:
        write_flat_file(tmp_path, date, [SAMPLE_ENTRY])

    run_cli(["docstracker", "--config", config_path, "backfill-digests", "--limit", "2"])

    from docstracker_framework.analysis_store import AnalysisStore
    store = AnalysisStore(str(tmp_path / "analyses"))
    _, d01 = store.read_run("2026-05-01")
    _, d02 = store.read_run("2026-05-02")
    _, d03 = store.read_run("2026-05-03")
    assert d01 is None           # oldest — excluded by limit
    assert d02 == SAMPLE_DIGEST  # within limit
    assert d03 == SAMPLE_DIGEST  # most recent


def test_write_digest_on_flat_file_wraps_and_preserves_entries(tmp_path):
    from docstracker_framework.analysis_store import AnalysisStore
    write_flat_file(tmp_path, "2026-05-08", [SAMPLE_ENTRY])

    store = AnalysisStore(str(tmp_path / "analyses"))
    store.write_digest("2026-05-08", SAMPLE_DIGEST)

    entries, digest = store.read_run("2026-05-08")
    assert entries == [SAMPLE_ENTRY]
    assert digest == SAMPLE_DIGEST
