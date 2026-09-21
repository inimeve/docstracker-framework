from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Section:
    heading: str
    body: str


@dataclass
class Page:
    url: str
    sections: list[Section] = field(default_factory=list)


@dataclass
class NewPage:
    page: Page


@dataclass
class SectionDiff:
    heading: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


@dataclass
class ModifiedPage:
    page: Page
    diffs: list[SectionDiff] = field(default_factory=list)


@dataclass
class WatchTarget:
    name: str
    url: str
    max_pages: int = 500
    topics: list[str] = field(default_factory=list)


@dataclass
class PageAnalysis:
    page_url: str
    relevance: Literal["high", "medium", "low"]
    category: Literal["breaking-change", "behavior-change", "new-feature", "limit-or-quota", "clarification", "new-example", "deprecation", "cosmetic"]
    summary: str
    topics_matched: list[str] = field(default_factory=list)


@dataclass
class NavNode:
    title: str
    url: "str | None" = None
    children: "list[NavNode]" = field(default_factory=list)


@dataclass
class NavigationSnapshot:
    nodes: "list[NavNode]" = field(default_factory=list)


@dataclass
class NavNodeAdded:
    title: str
    url: "str | None" = None
    parent_title: "str | None" = None


@dataclass
class NavNodeRemoved:
    title: str
    url: "str | None" = None
    parent_title: "str | None" = None


@dataclass
class NavNodeRenamed:
    old_title: str
    new_title: str
    url: "str | None" = None
    parent_title: "str | None" = None


@dataclass
class AnalyzerConfig:
    endpoint: str
    model: str
    api_key: str = ""


@dataclass
class Config:
    email: str
    targets: list[WatchTarget]
    analyzer: "AnalyzerConfig | None" = None
    synthesizer: "AnalyzerConfig | None" = None
