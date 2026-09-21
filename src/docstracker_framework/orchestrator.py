import logging
from dataclasses import dataclass, field

from docstracker_framework.models import Config, WatchTarget, PageAnalysis, ModifiedPage
from docstracker_framework.crawler import Crawler
from docstracker_framework.snapshot_store import SnapshotStore
from docstracker_framework.navigation_store import NavigationSnapshotStore
from docstracker_framework.nav_fetcher import fetch_nav
from docstracker_framework.nav_differ import NavDiffer
from docstracker_framework.differ import Differ
from docstracker_framework.analyzer import Analyzer
from docstracker_framework.synthesizer import Synthesizer

logger = logging.getLogger(__name__)
_RELEVANCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def _has_meaningful_diffs(diffs) -> bool:
    return any(line.strip() for diff in diffs for line in diff.added + diff.removed)


def _run_digest_payload(analyses_by_target: dict[str, list[PageAnalysis]]) -> list[dict]:
    all_analyses = [
        {"page_url": a.page_url, "target_name": tn, "relevance": a.relevance,
         "category": a.category, "summary": a.summary, "topics_matched": a.topics_matched}
        for tn, analyses in analyses_by_target.items()
        for a in analyses
    ]
    return sorted(
        all_analyses,
        key=lambda a: _RELEVANCE_ORDER.get(a["relevance"], 3),
    )


@dataclass
class CrawlResult:
    target_name: str
    checked_pages: int
    changes: list = field(default_factory=list)
    crawl_failures: list = field(default_factory=list)
    nav_changes: list = field(default_factory=list)


class CrawlTransaction:
    def __init__(self, crawler=None, snapshot_store=None, nav_store=None, nav_fetcher=None):
        self._crawler = crawler or Crawler()
        self._snapshot_store = snapshot_store
        self._differ = Differ()
        self._nav_store = nav_store
        self._nav_fetcher = nav_fetcher or fetch_nav

    def run(self, target: WatchTarget, on_progress=None) -> CrawlResult:
        on_page = None
        if on_progress:
            def on_page(url, crawled=None, queued=None):
                on_progress({
                    "type": "page-check-started",
                    "target_name": target.name,
                    "url": url,
                    "crawled": crawled,
                    "queued": queued,
                })

        pages = self._crawler.crawl(target, on_page=on_page)
        changes = []

        for page in pages:
            previous = self._snapshot_store.read(page.url)
            change = self._differ.diff(current=page, previous=previous)
            if change is not None:
                changes.append(change)
            self._snapshot_store.write(page)

        nav_changes = []
        if self._nav_store is not None:
            nav_snapshot = self._nav_fetcher(target)
            if nav_snapshot is not None:
                previous_nav = self._nav_store.read()
                if previous_nav is not None:
                    nav_changes = NavDiffer().diff(previous_nav, nav_snapshot)
                self._nav_store.write(nav_snapshot)

        return CrawlResult(
            target_name=target.name,
            checked_pages=len(pages),
            changes=changes,
            crawl_failures=list(getattr(self._crawler, "failures", [])),
            nav_changes=nav_changes,
        )


@dataclass
class RunResult:
    changes_by_target: dict[str, list] = field(default_factory=dict)
    analyses_by_target: dict[str, list[PageAnalysis]] = field(default_factory=dict)
    run_digest: list[dict] = field(default_factory=list)
    total_pages: int = 0
    crawl_failures: list[dict] = field(default_factory=list)
    nav_changes_by_target: dict[str, list] = field(default_factory=dict)


def run(config: Config, snapshots_dir: str = "snapshots", on_progress=None, analyzer=None, synthesizer=None, analysis_store=None, run_analysis_store=None, extractor_factory=Crawler) -> RunResult:
    if analyzer is None and config.analyzer is not None:
        analyzer = Analyzer(config.analyzer)
    if synthesizer is None and config.synthesizer is not None:
        synthesizer = Synthesizer(config.synthesizer)
    changes_by_target: dict[str, list] = {}
    nav_changes_by_target: dict[str, list] = {}
    analyses_by_target: dict[str, list[PageAnalysis]] = {}
    nav_analyses_by_target: dict[str, PageAnalysis] = {}
    total_pages = 0
    crawl_failures = []

    for target in config.targets:
        store = SnapshotStore.for_target(snapshots_dir, target)
        nav_store = NavigationSnapshotStore.for_target(snapshots_dir, target)
        crawl_result = CrawlTransaction(crawler=extractor_factory(), snapshot_store=store, nav_store=nav_store).run(target, on_progress=on_progress)
        total_pages += crawl_result.checked_pages
        crawl_failures.extend(crawl_result.crawl_failures)

        if crawl_result.changes:
            changes_by_target[crawl_result.target_name] = crawl_result.changes

        if crawl_result.nav_changes:
            nav_changes_by_target[crawl_result.target_name] = crawl_result.nav_changes

        if analyzer and crawl_result.changes:
            analyses = []
            for change in crawl_result.changes:
                if not isinstance(change, ModifiedPage):
                    continue
                if not _has_meaningful_diffs(change.diffs):
                    logger.info("skipping analysis for %s: no meaningful diffs", change.page.url)
                    continue
                try:
                    analysis = analyzer.analyze_page(change.page.url, change.diffs, topics=target.topics or None)
                    analyses.append(analysis)
                except Exception:
                    logger.warning("analysis failed for %s", change.page.url, exc_info=True)
            if analyses:
                analyses_by_target[crawl_result.target_name] = analyses

        if analyzer and crawl_result.nav_changes:
            try:
                nav_analysis = analyzer.analyze_nav_changes(
                    target.url, crawl_result.nav_changes, topics=target.topics or None
                )
                analyses_by_target.setdefault(crawl_result.target_name, []).append(nav_analysis)
                nav_analyses_by_target[crawl_result.target_name] = nav_analysis
            except Exception:
                logger.warning("nav analysis failed for %s", target.url, exc_info=True)

    run_digest: list[dict] = []
    if synthesizer and analyses_by_target:
        all_analyses = _run_digest_payload(analyses_by_target)
        run_digest = synthesizer.synthesize_run_digest(all_analyses)

    if analysis_store and analyses_by_target:
        analysis_store.write(analyses_by_target, digest=run_digest or None)

    if run_analysis_store and (changes_by_target or nav_changes_by_target):
        run_analysis_store.write(
            changes_by_target,
            analyses_by_target=analyses_by_target or None,
            run_digest=run_digest or None,
            nav_changes_by_target=nav_changes_by_target or None,
            nav_analyses_by_target=nav_analyses_by_target or None,
        )

    return RunResult(
        changes_by_target=changes_by_target,
        analyses_by_target=analyses_by_target,
        run_digest=run_digest,
        total_pages=total_pages,
        crawl_failures=crawl_failures,
        nav_changes_by_target=nav_changes_by_target,
    )
