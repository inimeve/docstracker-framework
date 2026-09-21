import json
import sys
import pytest
from unittest.mock import patch
from docstracker_framework.models import Config, WatchTarget, NewPage, Page, Section, ModifiedPage, SectionDiff, PageAnalysis, NavNodeAdded
from docstracker_framework.orchestrator import RunResult
from docstracker_framework.snapshot_store import SnapshotStore


def make_config(targets=None):
    return Config(
        email="user@example.com",
        targets=targets or [WatchTarget(name="My Docs", url="http://example.com/docs/")],
    )


def make_new_page(url="http://example.com/docs/page"):
    return NewPage(page=Page(url=url, sections=[Section(heading="Intro", body="Hello")]))


# ── issue #05: baseline run ────────────────────────────────────────────────────

def test_run_prints_changes(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config()) as _, \
         patch("docstracker_framework.cli.run", return_value=RunResult(changes_by_target={"My Docs": [make_new_page()]}, total_pages=5)) as mock_run, \
         patch("docstracker_framework.cli.EmailNotifier") as mock_notifier:
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run"]
        main()

    out = capsys.readouterr().out
    assert "My Docs" in out
    assert "1 change" in out
    mock_notifier.return_value.send.assert_not_called()


def test_run_prints_no_changes(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", return_value=RunResult()), \
         patch("docstracker_framework.cli.EmailNotifier"):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run"]
        main()

    out = capsys.readouterr().out
    assert "no changes detected" in out


def test_run_prints_crawl_failures(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    failure = {"url": "https://example.com/docs/", "reason": "certificate verify failed"}

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", return_value=RunResult(total_pages=0, crawl_failures=[failure])), \
         patch("docstracker_framework.cli.EmailNotifier"):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run"]
        main()

    captured = capsys.readouterr()
    assert "1 crawl failure" in captured.out
    assert "no changes detected" not in captured.out
    assert "certificate verify failed" in captured.err


def test_run_resolves_snapshots_relative_to_config(tmp_path, capsys):
    config_path = tmp_path / "subdir" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text("email: u@e.com\ntargets:\n  - name: X\n    url: http://x.com/\n")

    captured_snapshots_dir = {}

    def fake_run(config, snapshots_dir, on_progress=None, **kwargs):
        captured_snapshots_dir["value"] = snapshots_dir
        return RunResult()

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", side_effect=fake_run), \
         patch("docstracker_framework.cli.EmailNotifier"):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run"]
        main()

    assert captured_snapshots_dir["value"] == str(tmp_path / "subdir" / "snapshots")


def test_run_nav_changes_alone_are_not_suppressed(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    nav_change = NavNodeAdded(title="Best practices", url="http://x.com/best-practices")

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", return_value=RunResult(
             nav_changes_by_target={"My Docs": [nav_change]}, total_pages=5
         )), \
         patch("docstracker_framework.cli.EmailNotifier"):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run"]
        main()

    out = capsys.readouterr().out
    assert "no changes detected" not in out


# ── issue #06: --notify and --target ──────────────────────────────────────────

def test_run_notify_sends_email(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", return_value=RunResult(changes_by_target={"My Docs": [make_new_page()]}, total_pages=5)), \
         patch("docstracker_framework.cli.EmailNotifier") as mock_notifier_cls:
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run", "--notify"]
        main()

    mock_notifier_cls.return_value.send.assert_called_once_with(
        {"My Docs": [make_new_page()]},
        recipient="user@example.com",
        analyses=None,
        digest=None,
    )


def test_run_without_notify_does_not_send_email(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", return_value=RunResult(changes_by_target={"My Docs": [make_new_page()]}, total_pages=5)), \
         patch("docstracker_framework.cli.EmailNotifier") as mock_notifier_cls:
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run"]
        main()

    mock_notifier_cls.return_value.send.assert_not_called()


def test_run_target_filters_to_one(tmp_path, capsys):
    targets = [
        WatchTarget(name="Docs A", url="http://a.com/"),
        WatchTarget(name="Docs B", url="http://b.com/"),
    ]
    config = make_config(targets=targets)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets: []\n")

    captured = {}

    def fake_run(cfg, snapshots_dir, on_progress=None, **kwargs):
        captured["targets"] = [t.name for t in cfg.targets]
        return RunResult()

    with patch("docstracker_framework.cli.load_config", return_value=config), \
         patch("docstracker_framework.cli.run", side_effect=fake_run), \
         patch("docstracker_framework.cli.EmailNotifier"):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run", "--target", "Docs A"]
        main()

    assert captured["targets"] == ["Docs A"]


def test_run_unknown_target_exits_with_error(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", return_value=RunResult()), \
         patch("docstracker_framework.cli.EmailNotifier"), \
         pytest.raises(SystemExit) as exc_info:
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run", "--target", "Unknown"]
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Unknown" in err
    assert "My Docs" in err


# ── issue #07: list command ────────────────────────────────────────────────────

def _write_tracked_pages(snapshots_dir, target, urls):
    store = SnapshotStore.for_target(str(snapshots_dir), target)
    for url in urls:
        store.write(Page(url=url, sections=[Section(heading="Intro", body="Hello")]))


def test_list_tree_output(tmp_path, capsys):
    target = WatchTarget(name="My Docs", url="http://x.com/")
    _write_tracked_pages(tmp_path / "snapshots", target, [
        "https://docs.example.com/guide/intro",
        "https://docs.example.com/guide/setup",
    ])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config(targets=[target])):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "list"]
        main()

    out = capsys.readouterr().out
    assert "My Docs" in out
    assert "2 pages" in out
    assert "docs.example.com" in out
    assert "intro" in out
    assert "setup" in out


def test_list_flat_output(tmp_path, capsys):
    target = WatchTarget(name="My Docs", url="http://x.com/")
    urls = [
        "https://docs.example.com/guide/setup",
        "https://docs.example.com/guide/intro",
    ]
    _write_tracked_pages(tmp_path / "snapshots", target, urls)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config(targets=[target])):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "list", "--flat"]
        main()

    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if l.startswith("https://")]
    assert lines == sorted(urls)


def test_list_no_snapshots(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config()):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "list"]
        main()

    out = capsys.readouterr().out
    assert "no snapshots" in out


# ── issue #28: --summary-file ─────────────────────────────────────────────────

def test_run_summary_file_written_with_per_target_counts(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    summary_path = tmp_path / "summary.json"

    from docstracker_framework.models import ModifiedPage, SectionDiff
    modified = ModifiedPage(
        page=Page(url="http://x.com/page", sections=[]),
        diffs=[SectionDiff(heading="Intro", added=["new"], removed=[])],
    )

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", return_value=RunResult(
             changes_by_target={"My Docs": [make_new_page(), modified]},
             total_pages=5,
         )), \
         patch("docstracker_framework.cli.EmailNotifier"):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run",
                    "--summary-file", str(summary_path)]
        main()

    assert summary_path.exists()
    data = json.loads(summary_path.read_text())
    assert data == [{"name": "My Docs", "new": 1, "modified": 1}]


def test_run_summary_file_not_written_when_no_changes(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    summary_path = tmp_path / "summary.json"

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", return_value=RunResult()), \
         patch("docstracker_framework.cli.EmailNotifier"):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run",
                    "--summary-file", str(summary_path)]
        main()

    assert not summary_path.exists()


def test_analyze_save_writes_digest(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\nanalyzer:\n  endpoint: http://llm.local\n  model: analyzer\nsynthesizer:\n  endpoint: http://llm.local\n  model: synthesizer\n")
    modified = ModifiedPage(
        page=Page(url="http://x.com/page", sections=[]),
        diffs=[SectionDiff(heading="Intro", added=["new"], removed=["old"])],
    )
    analysis = PageAnalysis(
        page_url="http://x.com/page",
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )
    digest = [{"rel": "high", "text": "Cambio crítico."}]

    with patch("docstracker_framework.cli.replay_changes", return_value={"My Docs": [modified]}), \
         patch("docstracker_framework.cli.Analyzer") as analyzer_cls, \
         patch("docstracker_framework.cli.Synthesizer") as synthesizer_cls:
        analyzer_cls.return_value.analyze_page.return_value = analysis
        synthesizer_cls.return_value.synthesize_run_digest.return_value = digest
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "analyze", "--save"]
        main()

    written = json.loads(next((tmp_path / "analyses").glob("*.json")).read_text())
    assert written["digest"] == digest
    assert written["entries"][0]["summary"] == "Something broke."


def test_analyze_save_does_not_write_when_digest_fails(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\nanalyzer:\n  endpoint: http://llm.local\n  model: analyzer\nsynthesizer:\n  endpoint: http://llm.local\n  model: synthesizer\n")
    modified = ModifiedPage(
        page=Page(url="http://x.com/page", sections=[]),
        diffs=[SectionDiff(heading="Intro", added=["new"], removed=["old"])],
    )
    analysis = PageAnalysis(
        page_url="http://x.com/page",
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )

    with patch("docstracker_framework.cli.replay_changes", return_value={"My Docs": [modified]}), \
         patch("docstracker_framework.cli.Analyzer") as analyzer_cls, \
         patch("docstracker_framework.cli.Synthesizer") as synthesizer_cls, \
         pytest.raises(SystemExit) as exc:
        analyzer_cls.return_value.analyze_page.return_value = analysis
        synthesizer_cls.return_value.synthesize_run_digest.side_effect = TimeoutError("timeout")
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "analyze", "--save"]
        main()

    assert exc.value.code == 1
    assert not (tmp_path / "analyses").exists()
    assert "digest synthesis failed" in capsys.readouterr().err


# ── issue #29: export command ─────────────────────────────────────────────────

def test_export_outputs_h1_per_target_and_h2_per_page(tmp_path, capsys):
    target = WatchTarget(name="My Docs", url="http://x.com/")
    _write_tracked_pages(
        tmp_path / "snapshots", target,
        ["http://x.com/page-a", "http://x.com/page-b"],
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config(targets=[target])):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "export"]
        main()

    out = capsys.readouterr().out
    assert "# My Docs" in out
    assert "## http://x.com/page-a" in out
    assert "## http://x.com/page-b" in out


def test_export_out_writes_to_file(tmp_path, capsys):
    target = WatchTarget(name="My Docs", url="http://x.com/")
    _write_tracked_pages(tmp_path / "snapshots", target, ["http://x.com/page-a"])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    out_file = tmp_path / "export.md"

    with patch("docstracker_framework.cli.load_config", return_value=make_config(targets=[target])):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "export", "--out", str(out_file)]
        main()

    assert out_file.exists()
    content = out_file.read_text()
    assert "# My Docs" in content
    assert "## http://x.com/page-a" in content
    assert capsys.readouterr().out == ""


def test_export_target_filters_to_one(tmp_path, capsys):
    targets = [
        WatchTarget(name="Docs A", url="http://a.com/"),
        WatchTarget(name="Docs B", url="http://b.com/"),
    ]
    _write_tracked_pages(tmp_path / "snapshots", targets[0], ["http://a.com/page"])
    _write_tracked_pages(tmp_path / "snapshots", targets[1], ["http://b.com/page"])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets: []\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config(targets=targets)):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "export", "--target", "Docs A"]
        main()

    out = capsys.readouterr().out
    assert "# Docs A" in out
    assert "# Docs B" not in out


def test_export_includes_overview_before_pages(tmp_path, capsys):
    target = WatchTarget(name="My Docs", url="http://x.com/")
    _write_tracked_pages(tmp_path / "snapshots", target, ["http://x.com/page-a"])
    overview_dir = tmp_path / "snapshots" / "my-docs"
    overview_dir.mkdir(parents=True, exist_ok=True)
    (overview_dir / "OVERVIEW.md").write_text("This is the overview.\n")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config(targets=[target])):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "export"]
        main()

    out = capsys.readouterr().out
    assert "This is the overview." in out
    overview_pos = out.index("This is the overview.")
    page_pos = out.index("## http://x.com/page-a")
    assert overview_pos < page_pos


def test_export_no_snapshots_does_not_crash(tmp_path, capsys):
    target = WatchTarget(name="My Docs", url="http://x.com/")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config(targets=[target])):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "export"]
        main()

    out = capsys.readouterr().out
    assert "# My Docs" in out
    assert "##" not in out


# ── issue #81: reuse one run digest ───────────────────────────────────────────

def _make_analysis(url="http://x.com/page"):
    return PageAnalysis(
        page_url=url,
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )


def test_cmd_run_notify_uses_digest_from_orchestrator_not_fresh_synthesis(tmp_path, capsys):
    """Email digest must come from result.run_digest, not a second Synthesizer call."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n"
        "analyzer:\n  endpoint: http://llm.local\n  model: gpt\n"
    )
    digest = [{"rel": "high", "text": "Cambio crítico."}]
    analysis = _make_analysis()
    changes = {"My Docs": [make_new_page()]}

    with patch("docstracker_framework.cli.load_config", return_value=make_config()) as _, \
         patch("docstracker_framework.cli.run", return_value=RunResult(
             changes_by_target=changes,
             analyses_by_target={"My Docs": [analysis]},
             run_digest=digest,
         )) as mock_run, \
         patch("docstracker_framework.cli.Synthesizer") as mock_syn_cls, \
         patch("docstracker_framework.cli.EmailNotifier") as mock_notifier_cls:
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run", "--notify"]
        main()

    # CLI must NOT instantiate Synthesizer directly — orchestrator handles it
    mock_syn_cls.assert_not_called()
    # Email must receive the digest from the orchestrator result
    mock_notifier_cls.return_value.send.assert_called_once_with(
        changes,
        recipient="user@example.com",
        analyses={"My Docs": [analysis]},
        digest=digest,
    )


def test_cmd_run_passes_synthesizer_to_orchestrator(tmp_path, capsys):
    """cmd_run must pass a Synthesizer instance to orchestrator.run()."""
    from docstracker_framework.models import AnalyzerConfig
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n"
        "analyzer:\n  endpoint: http://llm.local\n  model: gpt\n"
    )
    analyzer_cfg = AnalyzerConfig(endpoint="http://llm.local", model="gpt")
    config_with_analyzer = Config(
        email="user@example.com",
        targets=[WatchTarget(name="My Docs", url="http://example.com/docs/")],
        analyzer=analyzer_cfg,
    )

    with patch("docstracker_framework.cli.load_config", return_value=config_with_analyzer), \
         patch("docstracker_framework.cli.run", return_value=RunResult()) as mock_run, \
         patch("docstracker_framework.cli.EmailNotifier"):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run"]
        main()

    call_kwargs = mock_run.call_args.kwargs
    assert "synthesizer" in call_kwargs or call_kwargs.get("synthesizer") is not None or \
           any(k == "synthesizer" for k in mock_run.call_args.kwargs)


def test_cmd_run_notify_no_synthesizer_when_no_analyses(tmp_path, capsys):
    """When orchestrator produces no analyses, email digest is None."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n"
    )
    changes = {"My Docs": [make_new_page()]}

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", return_value=RunResult(
             changes_by_target=changes,
             run_digest=[],
         )), \
         patch("docstracker_framework.cli.Synthesizer") as mock_syn_cls, \
         patch("docstracker_framework.cli.EmailNotifier") as mock_notifier_cls:
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run", "--notify"]
        main()

    mock_syn_cls.assert_not_called()
    call = mock_notifier_cls.return_value.send.call_args
    assert call.kwargs.get("digest") is None


# ── issue #83: resend command ─────────────────────────────────────────────────

def test_run_notify_persists_run_analysis_before_email(tmp_path, capsys):
    """RunAnalysis is written before email delivery during run --notify."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    changes = {"My Docs": [make_new_page()]}
    call_order = []

    def fake_run(*args, **kwargs):
        run_analysis_store = kwargs.get("run_analysis_store")
        if run_analysis_store:
            run_analysis_store.write(changes)
            call_order.append("persist")
        return RunResult(changes_by_target=changes)

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.run", side_effect=fake_run), \
         patch("docstracker_framework.cli.EmailNotifier") as mock_notifier_cls:
        def fake_send(*args, **kwargs):
            call_order.append("email")
        mock_notifier_cls.return_value.send.side_effect = fake_send
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "run", "--notify"]
        main()

    assert call_order == ["persist", "email"]


def test_resend_sends_email_from_persisted_run(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    changes = {"My Docs": [make_new_page()]}

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.RunAnalysisStore") as mock_store_cls, \
         patch("docstracker_framework.cli.EmailNotifier") as mock_notifier_cls:
        mock_store = mock_store_cls.return_value
        mock_store.load_for_notification.return_value = (changes, None, None)
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "resend", "2026-05-22"]
        main()

    mock_store.load_for_notification.assert_called_once_with("2026-05-22")
    mock_notifier_cls.return_value.send.assert_called_once()


def test_resend_fails_with_message_when_no_persisted_run(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.RunAnalysisStore") as mock_store_cls, \
         patch("docstracker_framework.cli.EmailNotifier") as mock_notifier_cls, \
         pytest.raises(SystemExit):
        mock_store_cls.return_value.load_for_notification.return_value = None
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "resend", "2026-05-22"]
        main()

    mock_notifier_cls.return_value.send.assert_not_called()
    err = capsys.readouterr().err
    assert "2026-05-22" in err


def test_resend_does_not_crawl_or_call_models(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    changes = {"My Docs": [make_new_page()]}

    with patch("docstracker_framework.cli.load_config", return_value=make_config()), \
         patch("docstracker_framework.cli.RunAnalysisStore") as mock_store_cls, \
         patch("docstracker_framework.cli.EmailNotifier"), \
         patch("docstracker_framework.cli.run") as mock_run, \
         patch("docstracker_framework.cli.Analyzer") as mock_analyzer, \
         patch("docstracker_framework.cli.Synthesizer") as mock_synthesizer:
        mock_store_cls.return_value.load_for_notification.return_value = (changes, None, None)
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "resend", "2026-05-22"]
        main()

    mock_run.assert_not_called()
    mock_analyzer.assert_not_called()
    mock_synthesizer.assert_not_called()
