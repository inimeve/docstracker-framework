import pytest
from unittest.mock import patch, MagicMock
from docstracker_framework.orchestrator import CrawlTransaction, run, RunResult, _run_digest_payload
from docstracker_framework.extractor import Extractor
from docstracker_framework.models import WatchTarget, Config, Page, Section, PageAnalysis, SectionDiff, AnalyzerConfig, ModifiedPage, NavigationSnapshot, NavNode, NavNodeAdded, NavNodeRemoved
from docstracker_framework.snapshot_store import SnapshotStore
from docstracker_framework.navigation_store import NavigationSnapshotStore


def page(url="https://example.com/docs/", body="Original content."):
    return Page(url=url, sections=[Section(heading="Guide", body=body)])


class FakeExtractor(Extractor):
    def __init__(self, pages, failures=None):
        super().__init__()
        self.pages = pages
        self.failures = failures or []

    def crawl(self, target, on_page=None):
        if on_page:
            for page in self.pages:
                on_page(page.url, 0, 0)
        return self.pages


class LoggingSnapshotStore:
    def __init__(self, previous):
        self.previous = previous
        self.operations = []

    def read(self, url):
        self.operations.append(("read", url))
        return self.previous

    def write(self, page):
        self.operations.append(("write", page.url))


class FailingWriteSnapshotStore(LoggingSnapshotStore):
    def write(self, page):
        raise OSError("cannot write snapshot")


class FakeAnalyzer:
    def __init__(self, analysis):
        self.calls = []
        self._analysis = analysis

    def analyze_page(self, url, diffs, topics=None):
        self.calls.append((url, diffs))
        return self._analysis


class FailingAnalyzer:
    def analyze_page(self, url, diffs, topics=None):
        raise RuntimeError("model unavailable")


class FakeCrawlTransactionResult:
    def __init__(self, changes, crawl_failures=None, nav_changes=None):
        self.target_name = "My Docs"
        self.checked_pages = 1
        self.changes = changes
        self.crawl_failures = crawl_failures or []
        self.nav_changes = nav_changes or []


def test_crawl_transaction_diffs_modified_page_before_writing_snapshot():
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    current = page(body="Updated content.")
    store = LoggingSnapshotStore(previous=page(body="Original content."))

    result = CrawlTransaction(crawler=FakeExtractor([current]), snapshot_store=store).run(target)

    assert result.target_name == "My Docs"
    assert result.checked_pages == 1
    assert len(result.changes) == 1
    assert store.operations == [
        ("read", current.url),
        ("write", current.url),
    ]


def test_run_persists_snapshots_for_watch_target(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    result = run(
        config,
        snapshots_dir=str(tmp_path),
        extractor_factory=lambda: FakeExtractor([page(url=target.url)]),
    )

    saved = SnapshotStore.for_target(str(tmp_path), target).read(target.url)

    assert saved is not None
    assert saved.url == target.url
    assert result.total_pages == 1


def test_crawl_transaction_reports_page_check_started_progress():
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    events = []

    CrawlTransaction(
        crawler=FakeExtractor([page()]),
        snapshot_store=LoggingSnapshotStore(previous=None),
    ).run(target, on_progress=events.append)

    assert events == [{
        "type": "page-check-started",
        "target_name": "My Docs",
        "url": "https://example.com/docs/",
        "crawled": 0,
        "queued": 0,
    }]


def test_crawl_transaction_returns_non_fatal_crawl_failures_and_processes_pages():
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    failure = {"url": "https://example.com/docs/broken", "reason": "fetch failed"}

    result = CrawlTransaction(
        crawler=FakeExtractor([page()], failures=[failure]),
        snapshot_store=LoggingSnapshotStore(previous=None),
    ).run(target)

    assert result.checked_pages == 1
    assert result.crawl_failures == [failure]


def test_crawl_transaction_does_not_hide_snapshot_write_failure():
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")

    with pytest.raises(OSError, match="cannot write snapshot"):
        CrawlTransaction(
            crawler=FakeExtractor([page()]),
            snapshot_store=FailingWriteSnapshotStore(previous=None),
        ).run(target)


def test_second_run_detects_modified_page(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    result = run(
        config,
        snapshots_dir=str(tmp_path),
        extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
    )

    assert "My Docs" in result.changes_by_target
    assert len(result.changes_by_target["My Docs"]) == 1


def test_run_with_analyzer_skips_new_pages(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])

    analysis = PageAnalysis(
        page_url=target.url,
        relevance="high",
        category="new-feature",
        summary="Brand new page.",
    )
    analyzer = FakeAnalyzer(analysis)
    result = run(
        config,
        snapshots_dir=str(tmp_path),
        analyzer=analyzer,
        extractor_factory=lambda: FakeExtractor([page(url=target.url)]),
    )

    assert result.changes_by_target.get("My Docs")
    assert result.analyses_by_target == {}
    assert analyzer.calls == []


def test_run_builds_analyzer_from_config(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(
        email="user@gmail.com",
        targets=[target],
        analyzer=AnalyzerConfig(endpoint="http://llm.local", model="gpt-4o"),
    )
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    fake_analysis = PageAnalysis(
        page_url=target.url,
        relevance="medium",
        category="clarification",
        summary="Minor clarification.",
    )
    mock_analyzer = MagicMock()
    mock_analyzer.analyze_page.return_value = fake_analysis

    with patch("docstracker_framework.orchestrator.Analyzer", return_value=mock_analyzer) as mock_cls:
        result = run(
            config,
            snapshots_dir=str(tmp_path),
            extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
        )

    mock_cls.assert_called_once_with(config.analyzer)
    assert result.analyses_by_target["My Docs"] == [fake_analysis]


def test_run_analyzer_partial_failure_still_returns_successful_analyses(tmp_path):
    url_a = "https://example.com/docs/a"
    url_b = "https://example.com/docs/b"
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    run(
        config,
        snapshots_dir=str(tmp_path),
        extractor_factory=lambda: FakeExtractor([page(url=url_a), page(url=url_b)]),
    )

    good_analysis = PageAnalysis(page_url=url_b, relevance="low", category="cosmetic", summary="Minor.")
    calls = []

    class PartialFailAnalyzer:
        def analyze_page(self, url, diffs, topics=None):
            calls.append(url)
            if url == url_a:
                raise RuntimeError("timeout")
            return good_analysis

    result = run(
        config,
        snapshots_dir=str(tmp_path),
        analyzer=PartialFailAnalyzer(),
        extractor_factory=lambda: FakeExtractor([
            page(url=url_a, body="Updated content."),
            page(url=url_b, body="Updated content."),
        ]),
    )

    assert url_a in calls
    assert url_b in calls
    assert result.analyses_by_target["My Docs"] == [good_analysis]


def test_run_skips_analyzer_for_non_meaningful_diffs(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    change = ModifiedPage(
        page=page(),
        diffs=[SectionDiff(heading="Guide", added=["   "], removed=[""])],
    )
    analyzer = MagicMock()

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_transaction_cls:
        mock_transaction_cls.return_value.run.return_value = FakeCrawlTransactionResult([change])
        result = run(config, snapshots_dir=str(tmp_path), analyzer=analyzer)

    assert result.changes_by_target["My Docs"] == [change]
    assert result.analyses_by_target == {}
    analyzer.analyze_page.assert_not_called()


def test_run_returns_crawl_failures(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    failure = {"url": target.url, "reason": "certificate verify failed"}

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_transaction_cls:
        mock_transaction_cls.return_value.run.return_value = FakeCrawlTransactionResult([], [failure])
        result = run(config, snapshots_dir=str(tmp_path))

    assert result.crawl_failures == [failure]


def test_run_with_failing_analyzer_logs_error_and_continues(tmp_path, caplog):
    import logging
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    with caplog.at_level(logging.WARNING, logger="orchestrator"):
        result = run(
            config,
            snapshots_dir=str(tmp_path),
            analyzer=FailingAnalyzer(),
            extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
        )

    assert result.analyses_by_target == {}
    assert "My Docs" in result.changes_by_target
    assert any("model unavailable" in r.message or target.url in r.message
               for r in caplog.records)


def test_run_without_analyzer_returns_empty_analyses(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    result = run(
        config,
        snapshots_dir=str(tmp_path),
        extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
    )

    assert result.analyses_by_target == {}
    assert "My Docs" in result.changes_by_target


def test_run_with_analyzer_returns_analyses_for_modified_pages(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    analysis = PageAnalysis(
        page_url=target.url,
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )
    analyzer = FakeAnalyzer(analysis)
    result = run(
        config,
        snapshots_dir=str(tmp_path),
        analyzer=analyzer,
        extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
    )

    assert isinstance(result, RunResult)
    assert "My Docs" in result.analyses_by_target
    assert result.analyses_by_target["My Docs"] == [analysis]
    assert len(analyzer.calls) == 1
    assert analyzer.calls[0][0] == target.url


class FakeAnalysisStore:
    def __init__(self):
        self.calls = []

    def write(self, analyses_by_target, date=None, digest=None):
        self.calls.append((analyses_by_target, date, digest))


def test_run_writes_analyses_to_store_when_analyses_produced(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    analysis = PageAnalysis(
        page_url=target.url,
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )
    analysis_store = FakeAnalysisStore()
    run(
        config,
        snapshots_dir=str(tmp_path),
        analyzer=FakeAnalyzer(analysis),
        analysis_store=analysis_store,
        extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
    )

    assert len(analysis_store.calls) == 1
    written = analysis_store.calls[0][0]
    assert "My Docs" in written
    assert written["My Docs"] == [analysis]
    assert analysis_store.calls[0][2] is None


def test_run_does_not_write_to_store_when_no_analyses(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    analysis_store = FakeAnalysisStore()

    run(
        config,
        snapshots_dir=str(tmp_path),
        analysis_store=analysis_store,
        extractor_factory=lambda: FakeExtractor([page(url=target.url)]),
    )

    assert analysis_store.calls == []


def test_run_passes_target_topics_to_analyzer(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/", topics=["networking"])
    config = Config(email="user@gmail.com", targets=[target])
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    analysis = PageAnalysis(
        page_url=target.url,
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )
    captured = {}

    class CapturingAnalyzer:
        def analyze_page(self, url, diffs, topics=None):
            captured["topics"] = topics
            return analysis

    run(
        config,
        snapshots_dir=str(tmp_path),
        analyzer=CapturingAnalyzer(),
        extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
    )

    assert captured["topics"] == ["networking"]


class FakeSynthesizer:
    def __init__(self, bullets):
        self.calls = []
        self._bullets = bullets

    def synthesize_run_digest(self, changes):
        self.calls.append(changes)
        return self._bullets


class FailingSynthesizer:
    def synthesize_run_digest(self, changes):
        raise TimeoutError("digest timed out")


def test_run_with_synthesizer_populates_run_digest(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    analysis = PageAnalysis(
        page_url=target.url,
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )
    bullets = [{"rel": "high", "text": "Cambio crítico detectado."}]
    synthesizer = FakeSynthesizer(bullets)
    result = run(
        config,
        snapshots_dir=str(tmp_path),
        analyzer=FakeAnalyzer(analysis),
        synthesizer=synthesizer,
        extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
    )

    assert result.run_digest == bullets
    assert len(synthesizer.calls) == 1


def test_run_synthesizer_receives_all_analyses_as_dicts(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    analysis = PageAnalysis(
        page_url=target.url,
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )
    synthesizer = FakeSynthesizer([])
    run(
        config,
        snapshots_dir=str(tmp_path),
        analyzer=FakeAnalyzer(analysis),
        synthesizer=synthesizer,
        extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
    )

    assert len(synthesizer.calls) == 1
    passed = synthesizer.calls[0]
    assert isinstance(passed, list)
    assert passed[0]["page_url"] == target.url
    assert passed[0]["relevance"] == "high"
    assert passed[0]["summary"] == "Something broke."


def test_run_digest_payload_includes_all_analyses_and_prioritizes_relevance():
    analyses = {
        "My Docs": [
            PageAnalysis(
                page_url=f"https://example.com/low-{i}",
                relevance="low",
                category="cosmetic",
                summary="Low priority.",
            )
            for i in range(30)
        ] + [
            PageAnalysis(
                page_url="https://example.com/high",
                relevance="high",
                category="breaking-change",
                summary="High priority.",
            )
        ]
    }

    payload = _run_digest_payload(analyses)

    assert len(payload) == 31
    assert payload[0]["page_url"] == "https://example.com/high"
    assert any(item["page_url"] == "https://example.com/low-29" for item in payload)


def test_run_synthesizer_failure_fails_run(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    analysis = PageAnalysis(
        page_url=target.url,
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )

    with pytest.raises(TimeoutError):
        run(
            config,
            snapshots_dir=str(tmp_path),
            analyzer=FakeAnalyzer(analysis),
            synthesizer=FailingSynthesizer(),
            extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
        )


def test_run_without_synthesizer_has_empty_run_digest(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    analysis = PageAnalysis(
        page_url=target.url,
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )
    result = run(
        config,
        snapshots_dir=str(tmp_path),
        analyzer=FakeAnalyzer(analysis),
        extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
    )

    assert result.run_digest == []


def test_run_builds_synthesizer_from_config(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(
        email="user@gmail.com",
        targets=[target],
        synthesizer=AnalyzerConfig(endpoint="http://llm.local", model="digest-model"),
    )
    run(config, snapshots_dir=str(tmp_path), extractor_factory=lambda: FakeExtractor([page(url=target.url)]))

    analysis = PageAnalysis(
        page_url=target.url,
        relevance="high",
        category="breaking-change",
        summary="Something broke.",
    )
    bullets = [{"rel": "high", "text": "Cambio crítico."}]
    mock_synthesizer = MagicMock()
    mock_synthesizer.synthesize_run_digest.return_value = bullets

    with patch("docstracker_framework.orchestrator.Synthesizer", return_value=mock_synthesizer) as mock_cls:
        result = run(
            config,
            snapshots_dir=str(tmp_path),
            analyzer=FakeAnalyzer(analysis),
            extractor_factory=lambda: FakeExtractor([page(url=target.url, body="Updated content.")]),
        )

    mock_cls.assert_called_once_with(config.synthesizer)
    assert result.run_digest == bullets


# --- Navigation snapshot integration ---

class FakeNavStore:
    def __init__(self):
        self.written = None

    def write(self, snapshot):
        self.written = snapshot

    def read(self):
        return self.written


def test_crawl_transaction_persists_navigation_snapshot(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    snapshot = NavigationSnapshot(nodes=[NavNode(title="Overview", url="https://example.com/docs/overview")])
    nav_store = FakeNavStore()

    CrawlTransaction(
        crawler=FakeExtractor([]),
        snapshot_store=LoggingSnapshotStore(previous=None),
        nav_store=nav_store,
        nav_fetcher=lambda t: snapshot,
    ).run(target)

    assert nav_store.written == snapshot


def test_crawl_transaction_skips_nav_write_when_fetcher_returns_none():
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    nav_store = FakeNavStore()

    CrawlTransaction(
        crawler=FakeExtractor([]),
        snapshot_store=LoggingSnapshotStore(previous=None),
        nav_store=nav_store,
        nav_fetcher=lambda t: None,
    ).run(target)

    assert nav_store.written is None


def test_crawl_transaction_returns_nav_changes_when_snapshot_differs():
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    previous = NavigationSnapshot(nodes=[NavNode(title="Overview", url="https://example.com/docs/overview")])
    current = NavigationSnapshot(nodes=[
        NavNode(title="Overview", url="https://example.com/docs/overview"),
        NavNode(title="Best practices", url="https://example.com/docs/best-practices"),
    ])

    class NavStoreWithPrevious:
        def __init__(self):
            self.written = None
        def read(self):
            return previous
        def write(self, snapshot):
            self.written = snapshot

    result = CrawlTransaction(
        crawler=FakeExtractor([]),
        snapshot_store=LoggingSnapshotStore(previous=None),
        nav_store=NavStoreWithPrevious(),
        nav_fetcher=lambda t: current,
    ).run(target)

    assert len(result.nav_changes) == 1
    assert isinstance(result.nav_changes[0], NavNodeAdded)
    assert result.nav_changes[0].title == "Best practices"


def test_crawl_transaction_returns_empty_nav_changes_when_no_previous_snapshot():
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    current = NavigationSnapshot(nodes=[NavNode(title="Overview", url="https://example.com/docs/overview")])

    class EmptyNavStore:
        def read(self):
            return None
        def write(self, snapshot):
            pass

    result = CrawlTransaction(
        crawler=FakeExtractor([]),
        snapshot_store=LoggingSnapshotStore(previous=None),
        nav_store=EmptyNavStore(),
        nav_fetcher=lambda t: current,
    ).run(target)

    assert result.nav_changes == []


def test_run_calls_analyze_nav_changes_when_analyzer_configured(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    nav_change = NavNodeAdded(title="Best practices", url="https://example.com/docs/best-practices")
    analyzer = MagicMock()
    analysis = PageAnalysis(
        page_url="https://example.com/docs/",
        relevance="high",
        category="new-feature",
        summary="New section added.",
    )
    analyzer.analyze_nav_changes.return_value = analysis

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_cls:
        mock_cls.return_value.run.return_value = FakeCrawlTransactionResult([], nav_changes=[nav_change])
        result = run(config, snapshots_dir=str(tmp_path), analyzer=analyzer)

    analyzer.analyze_nav_changes.assert_called_once_with(
        target.url, [nav_change], topics=None
    )
    assert result.analyses_by_target == {"My Docs": [analysis]}


def test_run_nav_analysis_failure_degrades_silently(tmp_path, caplog):
    import logging
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    nav_change = NavNodeAdded(title="Best practices", url="https://example.com/docs/best-practices")

    class FailingNavAnalyzer:
        def analyze_page(self, *a, **kw):
            return MagicMock()
        def analyze_nav_changes(self, *a, **kw):
            raise RuntimeError("model unavailable")

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_cls:
        mock_cls.return_value.run.return_value = FakeCrawlTransactionResult([], nav_changes=[nav_change])
        with caplog.at_level(logging.WARNING):
            result = run(config, snapshots_dir=str(tmp_path), analyzer=FailingNavAnalyzer())

    assert result.analyses_by_target == {}
    assert any("nav analysis failed" in r.message for r in caplog.records)


def test_run_skips_nav_analysis_when_no_analyzer(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    nav_change = NavNodeAdded(title="Best practices", url="https://example.com/docs/best-practices")

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_cls:
        mock_cls.return_value.run.return_value = FakeCrawlTransactionResult([], nav_changes=[nav_change])
        result = run(config, snapshots_dir=str(tmp_path))

    assert result.analyses_by_target == {}
    assert result.nav_changes_by_target == {"My Docs": [nav_change]}


def test_run_persists_nav_analysis_via_run_analysis_store(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    nav_change = NavNodeAdded(title="Best practices", url="https://example.com/docs/best-practices")
    page_change = ModifiedPage(
        page=page(), diffs=[SectionDiff(heading="Guide", added=["new"], removed=["old"])]
    )
    nav_analysis = PageAnalysis(
        page_url="https://example.com/docs/",
        relevance="high",
        category="new-feature",
        summary="New section added.",
    )
    analyzer = MagicMock()
    analyzer.analyze_page.return_value = PageAnalysis(
        page_url=page().url, relevance="low", category="cosmetic", summary="Minor."
    )
    analyzer.analyze_nav_changes.return_value = nav_analysis
    mock_store = MagicMock()

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_cls:
        mock_cls.return_value.run.return_value = FakeCrawlTransactionResult(
            [page_change], nav_changes=[nav_change]
        )
        run(config, snapshots_dir=str(tmp_path), analyzer=analyzer, run_analysis_store=mock_store)

    call_kwargs = mock_store.write.call_args.kwargs
    assert call_kwargs["nav_analyses_by_target"] == {"My Docs": nav_analysis}


def test_run_persists_nav_changes_via_run_analysis_store(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    nav_change = NavNodeAdded(title="Best practices", url="https://example.com/docs/best-practices")
    page_change = ModifiedPage(
        page=page(), diffs=[SectionDiff(heading="Guide", added=["new"], removed=["old"])]
    )
    mock_store = MagicMock()

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_cls:
        mock_cls.return_value.run.return_value = FakeCrawlTransactionResult(
            [page_change], nav_changes=[nav_change]
        )
        run(config, snapshots_dir=str(tmp_path), run_analysis_store=mock_store)

    mock_store.write.assert_called_once()
    call_kwargs = mock_store.write.call_args.kwargs
    assert call_kwargs["nav_changes_by_target"] == {"My Docs": [nav_change]}


def test_run_collects_nav_changes_by_target(tmp_path):
    target = WatchTarget(name="My Docs", url="https://example.com/docs/")
    config = Config(email="user@gmail.com", targets=[target])
    nav_change = NavNodeAdded(title="Best practices", url="https://example.com/docs/best-practices")

    with patch("docstracker_framework.orchestrator.CrawlTransaction") as mock_cls:
        mock_cls.return_value.run.return_value = FakeCrawlTransactionResult([], nav_changes=[nav_change])
        result = run(config, snapshots_dir=str(tmp_path))

    assert result.nav_changes_by_target == {"My Docs": [nav_change]}
