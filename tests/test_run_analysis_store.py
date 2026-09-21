import json
import os
import pytest
from docstracker_framework.models import Page, Section, NewPage, ModifiedPage, SectionDiff, PageAnalysis, NavNodeAdded, NavNodeRemoved, NavNodeRenamed
from docstracker_framework.run_analysis_store import RunAnalysisStore


def modified_page(url="https://example.com/docs/", heading="Guide", added=None, removed=None):
    page = Page(url=url, sections=[Section(heading=heading, body="body")])
    diffs = [SectionDiff(heading=heading, added=added or ["new line"], removed=removed or ["old line"])]
    return ModifiedPage(page=page, diffs=diffs)


def new_page(url="https://example.com/docs/new", heading="New Guide", body="New content."):
    page = Page(url=url, sections=[Section(heading=heading, body=body)])
    return NewPage(page=page)


# ---------------------------------------------------------------------------
# Tracer bullet
# ---------------------------------------------------------------------------

def test_write_creates_run_analysis_file_for_crawl_with_changes(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    changes = {"My Docs": [modified_page()]}

    store.write(changes, date="2026-05-22")

    assert os.path.exists(os.path.join(str(tmp_path), "2026-05-22.json"))


# ---------------------------------------------------------------------------
# Modified Page
# ---------------------------------------------------------------------------

def test_modified_page_entry_includes_section_diffs(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    changes = {"My Docs": [modified_page(added=["new line"], removed=["old line"])]}

    store.write(changes, date="2026-05-22")

    record = json.loads(open(os.path.join(str(tmp_path), "2026-05-22.json")).read())
    page_entry = record["targets"][0]["pages"][0]
    assert page_entry["type"] == "modified"
    assert page_entry["diffs"][0]["added"] == ["new line"]
    assert page_entry["diffs"][0]["removed"] == ["old line"]


# ---------------------------------------------------------------------------
# New Page
# ---------------------------------------------------------------------------

def test_new_page_entry_includes_section_metadata(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    changes = {"My Docs": [new_page(heading="New Guide", body="New content.")]}

    store.write(changes, date="2026-05-22")

    record = json.loads(open(os.path.join(str(tmp_path), "2026-05-22.json")).read())
    page_entry = record["targets"][0]["pages"][0]
    assert page_entry["type"] == "new"
    assert page_entry["sections"][0]["heading"] == "New Guide"
    assert page_entry["sections"][0]["body"] == "New content."


# ---------------------------------------------------------------------------
# PageAnalysis association
# ---------------------------------------------------------------------------

def test_page_analysis_associated_when_available(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    url = "https://example.com/docs/"
    changes = {"My Docs": [modified_page(url=url)]}
    analysis = PageAnalysis(
        page_url=url,
        relevance="high",
        category="breaking-change",
        summary="Auth changed.",
        topics_matched=["security"],
    )

    store.write(changes, analyses_by_target={"My Docs": [analysis]}, date="2026-05-22")

    record = json.loads(open(os.path.join(str(tmp_path), "2026-05-22.json")).read())
    page_entry = record["targets"][0]["pages"][0]
    assert page_entry["analysis"]["relevance"] == "high"
    assert page_entry["analysis"]["category"] == "breaking-change"
    assert page_entry["analysis"]["summary"] == "Auth changed."
    assert page_entry["analysis"]["topics_matched"] == ["security"]


def test_page_without_analysis_has_no_analysis_key(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    changes = {"My Docs": [modified_page()]}

    store.write(changes, date="2026-05-22")

    record = json.loads(open(os.path.join(str(tmp_path), "2026-05-22.json")).read())
    page_entry = record["targets"][0]["pages"][0]
    assert "analysis" not in page_entry


# ---------------------------------------------------------------------------
# No Changes — no record written
# ---------------------------------------------------------------------------

def test_write_noop_when_no_changes(tmp_path):
    store = RunAnalysisStore(str(tmp_path))

    store.write({}, date="2026-05-22")

    assert not os.path.exists(os.path.join(str(tmp_path), "2026-05-22.json"))


# ---------------------------------------------------------------------------
# Run Digest
# ---------------------------------------------------------------------------

def test_run_digest_included_when_provided(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    changes = {"My Docs": [modified_page()]}
    digest = [{"rel": "high", "text": "Breaking change detected."}]

    store.write(changes, run_digest=digest, date="2026-05-22")

    record = json.loads(open(os.path.join(str(tmp_path), "2026-05-22.json")).read())
    assert record["run_digest"] == digest


def test_run_digest_absent_when_not_provided(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    changes = {"My Docs": [modified_page()]}

    store.write(changes, date="2026-05-22")

    record = json.loads(open(os.path.join(str(tmp_path), "2026-05-22.json")).read())
    assert "run_digest" not in record


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------

def test_orchestrator_writes_run_analysis_when_changes_detected(tmp_path):
    from unittest.mock import MagicMock, patch
    from docstracker_framework.orchestrator import run, CrawlTransaction
    from docstracker_framework.models import WatchTarget, Config, NewPage, Page, Section

    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@example.com", targets=[target])
    np = NewPage(page=Page(url="https://example.com/docs/", sections=[Section(heading="Guide", body="body")]))

    fake_result = MagicMock()
    fake_result.target_name = "My Docs"
    fake_result.checked_pages = 1
    fake_result.changes = [np]
    fake_result.crawl_failures = []

    run_analysis_store = MagicMock()

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_cls:
        mock_cls.return_value.run.return_value = fake_result
        run(config, snapshots_dir=str(tmp_path), run_analysis_store=run_analysis_store)

    run_analysis_store.write.assert_called_once()
    call_kwargs = run_analysis_store.write.call_args
    assert "My Docs" in (call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs["changes_by_target"])


# ---------------------------------------------------------------------------
# load_for_notification
# ---------------------------------------------------------------------------

def test_load_for_notification_returns_none_when_no_file(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    assert store.load_for_notification("2026-05-22") is None


def test_load_for_notification_reconstructs_analyses_and_digest(tmp_path):
    from docstracker_framework.models import PageAnalysis
    store = RunAnalysisStore(str(tmp_path))
    url = "https://example.com/docs/"
    analysis = PageAnalysis(page_url=url, relevance="high", category="breaking-change", summary="Auth changed.", topics_matched=["security"])
    digest = [{"rel": "high", "text": "Breaking change."}]
    store.write({"My Docs": [modified_page(url=url)]}, analyses_by_target={"My Docs": [analysis]}, run_digest=digest, date="2026-05-22")

    _, analyses_by_target, run_digest = store.load_for_notification("2026-05-22")

    assert analyses_by_target is not None
    a = analyses_by_target["My Docs"][0]
    assert isinstance(a, PageAnalysis)
    assert a.relevance == "high"
    assert a.summary == "Auth changed."
    assert run_digest == digest


def test_load_for_notification_reconstructs_modified_page(tmp_path):
    from docstracker_framework.models import ModifiedPage
    store = RunAnalysisStore(str(tmp_path))
    url = "https://example.com/docs/"
    store.write({"My Docs": [modified_page(url=url)]}, date="2026-05-22")

    result = store.load_for_notification("2026-05-22")

    assert result is not None
    changes_by_target, analyses_by_target, run_digest = result
    assert "My Docs" in changes_by_target
    change = changes_by_target["My Docs"][0]
    assert isinstance(change, ModifiedPage)
    assert change.page.url == url


def test_orchestrator_does_not_write_run_analysis_when_no_changes(tmp_path):
    from unittest.mock import MagicMock, patch
    from docstracker_framework.orchestrator import run
    from docstracker_framework.models import WatchTarget, Config

    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@example.com", targets=[target])

    fake_result = MagicMock()
    fake_result.target_name = "My Docs"
    fake_result.checked_pages = 0
    fake_result.changes = []
    fake_result.nav_changes = []
    fake_result.crawl_failures = []

    run_analysis_store = MagicMock()

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_cls:
        mock_cls.return_value.run.return_value = fake_result
        run(config, snapshots_dir=str(tmp_path), run_analysis_store=run_analysis_store)

    run_analysis_store.write.assert_not_called()


def test_write_persists_nav_analysis_in_target_record(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    nav_analysis = PageAnalysis(
        page_url="https://docs.example.com/",
        relevance="high",
        category="new-feature",
        summary="New top-level section 'Best practices' added.",
    )
    store.write(
        {"My Docs": [modified_page()]},
        nav_analyses_by_target={"My Docs": nav_analysis},
        date="2026-06-09",
    )

    record = json.loads(open(os.path.join(str(tmp_path), "2026-06-09.json")).read())
    nav_anal = record["targets"][0]["nav_analysis"]
    assert nav_anal["relevance"] == "high"
    assert nav_anal["category"] == "new-feature"
    assert nav_anal["summary"] == "New top-level section 'Best practices' added."


def test_write_omits_nav_analysis_key_when_none(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    store.write({"My Docs": [modified_page()]}, date="2026-06-09")

    record = json.loads(open(os.path.join(str(tmp_path), "2026-06-09.json")).read())
    assert "nav_analysis" not in record["targets"][0]


def test_write_persists_nav_changes_in_target_record(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    nav_changes = [
        NavNodeAdded(title="Best practices", url="https://docs.example.com/best-practices"),
        NavNodeRemoved(title="Legacy guide", url="https://docs.example.com/legacy"),
        NavNodeRenamed(old_title="API reference", new_title="Reference", url="https://docs.example.com/ref"),
    ]
    store.write(
        {"My Docs": [modified_page()]},
        nav_changes_by_target={"My Docs": nav_changes},
        date="2026-06-09",
    )

    record = json.loads(open(os.path.join(str(tmp_path), "2026-06-09.json")).read())
    nav = record["targets"][0]["nav_changes"]
    assert len(nav) == 3
    assert nav[0] == {"type": "added", "title": "Best practices", "url": "https://docs.example.com/best-practices", "parent_title": None}
    assert nav[1] == {"type": "removed", "title": "Legacy guide", "url": "https://docs.example.com/legacy", "parent_title": None}
    assert nav[2] == {"type": "renamed", "old_title": "API reference", "new_title": "Reference", "url": "https://docs.example.com/ref", "parent_title": None}


def test_write_omits_nav_changes_key_when_none(tmp_path):
    store = RunAnalysisStore(str(tmp_path))
    store.write({"My Docs": [modified_page()]}, date="2026-06-09")

    record = json.loads(open(os.path.join(str(tmp_path), "2026-06-09.json")).read())
    assert "nav_changes" not in record["targets"][0]
