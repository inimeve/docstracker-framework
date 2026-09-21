from abc import ABC, abstractmethod

from docstracker_framework.models import Page, WatchTarget


class Extractor(ABC):
    """Discovers and fetches Pages for a Watch Target during a Crawl.

    `Crawler` (BFS-prefix HTML crawl) is today's only implementation. Other
    discovery strategies (e.g. feed- or listing-based, for non-reference-doc
    sources) are anticipated but not yet built; adding one means a new
    Extractor implementation, not a change to Differ, Analyzer, Synthesizer,
    or the Stores. See ADR-0009 in the docstracker repo.

    Fetching a NavigationSnapshot (see nav_fetcher.fetch_nav) is a related,
    optional capability: it is not part of this interface because it isn't
    tied to a specific Extractor implementation today, and is only used when
    a caller supplies a nav fetcher alongside an Extractor.
    """

    def __init__(self):
        self.failures: list[dict] = []

    @abstractmethod
    def crawl(self, target: WatchTarget, on_page=None) -> list[Page]:
        ...
