"""Tests that enforce the analyzer/synthesizer role boundary (issue #82)."""
import sys
import pytest
from unittest.mock import patch, MagicMock

from docstracker_framework.models import Config, WatchTarget, AnalyzerConfig, NewPage, Page, Section, PageAnalysis
from docstracker_framework.orchestrator import RunResult


def make_analyzer_config():
    return AnalyzerConfig(endpoint="http://analyzer.local/v1", model="analyzer-model", api_key=None)


def make_synthesizer_config():
    return AnalyzerConfig(endpoint="http://synthesizer.local/v1", model="synthesizer-model", api_key=None)


def make_config(analyzer=None, synthesizer=None):
    return Config(
        email="user@example.com",
        targets=[WatchTarget(name="My Docs", url="http://example.com/docs/")],
        analyzer=analyzer,
        synthesizer=synthesizer,
    )


def make_new_page(url="http://example.com/docs/page"):
    return NewPage(page=Page(url=url, sections=[Section(heading="Intro", body="Hello")]))


def make_run_result_with_changes():
    return RunResult(
        changes_by_target={"My Docs": [make_new_page()]},
        total_pages=5,
        run_digest=[],
    )


# ── Tracer bullet: cmd_run does not fall back to analyzer as synthesizer ──────


def test_cmd_run_with_analyzer_only_does_not_call_synthesize_run_digest(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    config = make_config(analyzer=make_analyzer_config())
    run_result = make_run_result_with_changes()

    synthesize_calls = []

    class FakeSynthesizer:
        def synthesize_run_digest(self, *args, **kwargs):
            synthesize_calls.append(args)
            return []

    with patch("docstracker_framework.cli.load_config", return_value=config), \
         patch("docstracker_framework.cli.run", return_value=run_result), \
         patch("docstracker_framework.cli.EmailNotifier"), \
         patch("docstracker_framework.cli.Synthesizer", return_value=FakeSynthesizer()) as mock_synth_cls:
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run"]
        main()

    mock_synth_cls.assert_not_called()
    assert synthesize_calls == []


# ── _synthesize_digest_for_notification: no analyzer fallback ────────────────


def test_synthesize_digest_for_notification_returns_none_without_synthesizer():
    from docstracker_framework.cli import _synthesize_digest_for_notification

    config = make_config(analyzer=make_analyzer_config(), synthesizer=None)
    analyses_by_target = {"My Docs": [
        PageAnalysis(page_url="http://x.com/p", relevance="high", category="new-feature", summary="s")
    ]}

    result = _synthesize_digest_for_notification(config, analyses_by_target)

    assert result is None


def test_synthesize_digest_for_notification_uses_synthesizer_when_configured():
    from docstracker_framework.cli import _synthesize_digest_for_notification

    config = make_config(
        analyzer=make_analyzer_config(),
        synthesizer=make_synthesizer_config(),
    )
    analyses_by_target = {"My Docs": [
        PageAnalysis(page_url="http://x.com/p", relevance="high", category="new-feature", summary="s")
    ]}

    expected_digest = [{"rel": "high", "text": "Something changed."}]

    with patch("docstracker_framework.cli.Synthesizer") as mock_synth_cls:
        instance = MagicMock()
        instance.synthesize_run_digest.return_value = expected_digest
        mock_synth_cls.return_value = instance

        result = _synthesize_digest_for_notification(config, analyses_by_target)

    mock_synth_cls.assert_called_once_with(config.synthesizer)
    assert result == expected_digest


# ── cmd_analyze --save: no analyzer fallback ─────────────────────────────────


def test_cmd_analyze_save_errors_when_only_analyzer_configured(tmp_path, capsys):
    """analyze --save must not use analyzer as fallback synthesizer."""
    import yaml
    config_data = {
        "email": "test@example.com",
        "targets": [{"name": "My Docs", "url": "https://docs.example.com/"}],
        "analyzer": {"endpoint": "http://analyzer.local/v1", "model": "analyzer-model"},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config_data))

    from docstracker_framework.models import ModifiedPage, Page, Section, SectionDiff, PageAnalysis
    mod_page = ModifiedPage(
        page=Page(url="http://x.com/p", sections=[Section(heading="H", body="new")]),
        diffs=[SectionDiff(heading="H", added=["new line"], removed=[])],
    )
    analysis = PageAnalysis(page_url="http://x.com/p", relevance="high", category="new-feature", summary="s")

    with patch("docstracker_framework.cli.replay_changes", return_value={"My Docs": [mod_page]}), \
         patch("docstracker_framework.cli.Analyzer") as mock_analyzer_cls, \
         patch("docstracker_framework.cli.Synthesizer") as mock_synth_cls:
        mock_analyzer_cls.return_value.analyze_page.return_value = analysis
        mock_synth_cls.return_value.synthesize_run_digest.side_effect = RuntimeError("should not be called")

        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "analyze", "--save"]
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "synthesizer" in err.lower()


# ── cmd_backfill_digests: no analyzer fallback ───────────────────────────────


def test_cmd_backfill_digests_errors_when_only_analyzer_configured(tmp_path, capsys):
    import yaml
    config_data = {
        "email": "test@example.com",
        "targets": [{"name": "My Docs", "url": "https://docs.example.com/"}],
        "analyzer": {"endpoint": "http://analyzer.local/v1", "model": "analyzer-model"},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config_data))

    from docstracker_framework.cli import main
    sys.argv = ["docstracker", "--config", str(config_path), "backfill-digests"]
    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "synthesizer" in err.lower()


# ── orchestrator.run: Run Analysis persisted even without synthesizer ─────────


def test_run_persists_run_analysis_without_synthesizer():
    from docstracker_framework.orchestrator import run as orchestrator_run
    from docstracker_framework.models import ModifiedPage, SectionDiff

    config = make_config(analyzer=make_analyzer_config(), synthesizer=None)

    mod_page = ModifiedPage(
        page=Page(url="http://x.com/p", sections=[Section(heading="H", body="new")]),
        diffs=[SectionDiff(heading="H", added=["new line"], removed=[])],
    )

    fake_crawl_result = MagicMock()
    fake_crawl_result.target_name = "My Docs"
    fake_crawl_result.checked_pages = 1
    fake_crawl_result.changes = [mod_page]
    fake_crawl_result.crawl_failures = []

    mock_run_analysis_store = MagicMock()

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_txn_cls, \
         patch("docstracker_framework.orchestrator.SnapshotStore"):
        mock_txn_cls.return_value.run.return_value = fake_crawl_result
        orchestrator_run(
            config,
            run_analysis_store=mock_run_analysis_store,
        )

    mock_run_analysis_store.write.assert_called_once()
    call_kwargs = mock_run_analysis_store.write.call_args
    assert "My Docs" in call_kwargs.args[0]
