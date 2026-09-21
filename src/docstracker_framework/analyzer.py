import json
import uuid
import httpx
from docstracker_framework.models import AnalyzerConfig, SectionDiff, PageAnalysis, NavNodeAdded, NavNodeRemoved, NavNodeRenamed

_RELEVANCE_VALUES = {"high", "medium", "low"}
_CATEGORY_VALUES = {"breaking-change", "behavior-change", "new-feature", "limit-or-quota", "clarification", "new-example", "deprecation", "cosmetic"}

_NAV_PROMPT_TEMPLATE = """\
You are analyzing documentation navigation changes. Given the structural changes to the navigation tree below, return a JSON object with exactly these fields:
- relevance: one of "high", "medium", "low"
- category: one of "breaking-change", "behavior-change", "new-feature", "limit-or-quota", "clarification", "new-example", "deprecation", "cosmetic"
- summary: 1-2 sentences describing what changed and why it matters, written in the same language as the documentation

Target URL: {url}

Navigation changes:
{changes}
"""

_NAV_PROMPT_TEMPLATE_WITH_TOPICS = """\
You are analyzing documentation navigation changes. Given the structural changes to the navigation tree below, return a JSON object with exactly these fields:
- relevance: one of "high", "medium", "low"
- category: one of "breaking-change", "behavior-change", "new-feature", "limit-or-quota", "clarification", "new-example", "deprecation", "cosmetic"
- summary: 1-2 sentences describing what changed and why it matters, written in the same language as the documentation
- topics_matched: list of topic names from the configured topics that this change is relevant to (empty list if none match)

Configured topics: {topics}

Target URL: {url}

Navigation changes:
{changes}
"""


def _format_nav_changes(nav_changes: list) -> str:
    lines = []
    for c in nav_changes:
        if isinstance(c, NavNodeAdded):
            parent = f" (under {c.parent_title})" if c.parent_title else ""
            lines.append(f"+ Added: {c.title}{parent}")
        elif isinstance(c, NavNodeRemoved):
            parent = f" (from {c.parent_title})" if c.parent_title else ""
            lines.append(f"- Removed: {c.title}{parent}")
        elif isinstance(c, NavNodeRenamed):
            lines.append(f"~ Renamed: {c.old_title} → {c.new_title}")
    return "\n".join(lines)


_PROMPT_TEMPLATE = """\
You are analyzing documentation changes. Given the section diffs below, return a JSON object with exactly these fields:
- relevance: one of "high", "medium", "low"
- category: one of "breaking-change", "behavior-change", "new-feature", "limit-or-quota", "clarification", "new-example", "deprecation", "cosmetic"
- summary: 1-2 sentences describing what changed and why it matters, written in the same language as the documentation

Page URL: {url}

Section diffs:
{diffs}
"""

_PROMPT_TEMPLATE_WITH_TOPICS = """\
You are analyzing documentation changes. Given the section diffs below, return a JSON object with exactly these fields:
- relevance: one of "high", "medium", "low"
- category: one of "breaking-change", "behavior-change", "new-feature", "limit-or-quota", "clarification", "new-example", "deprecation", "cosmetic"
- summary: 1-2 sentences describing what changed and why it matters, written in the same language as the documentation
- topics_matched: list of topic names from the configured topics that this change is relevant to (empty list if none match)

Configured topics: {topics}

Page URL: {url}

Section diffs:
{diffs}
"""


class Analyzer:
    def __init__(self, config: AnalyzerConfig, client: httpx.Client | None = None):
        self._config = config
        self._client = client or httpx.Client(
            base_url=config.endpoint,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "x-opencode-session": f"docstracker-analyzer-{uuid.uuid4()}",
            } if config.api_key else {},
            timeout=120.0,
        )

    def analyze_page(self, url: str, diffs: list[SectionDiff], topics: list[str] | None = None) -> PageAnalysis:
        meaningful = [d for d in diffs if any(line.strip() for line in d.added + d.removed)]
        if not meaningful:
            raise ValueError("no meaningful diffs to analyze")

        diffs_text = "\n\n".join(
            f"## {d.heading}\n"
            + (("Added:\n" + "\n".join(f"+ {l}" for l in d.added)) if d.added else "")
            + (("\nRemoved:\n" + "\n".join(f"- {l}" for l in d.removed)) if d.removed else "")
            for d in meaningful
        )

        if topics:
            topics_str = ", ".join(f'"{t}"' for t in topics)
            prompt = _PROMPT_TEMPLATE_WITH_TOPICS.format(url=url, diffs=diffs_text, topics=topics_str)
        else:
            prompt = _PROMPT_TEMPLATE.format(url=url, diffs=diffs_text)
        response = self._client.post(
            "/chat/completions",
            json={
                "model": self._config.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(content)

        for field in ("relevance", "category", "summary"):
            if field not in data:
                raise ValueError(f"model response missing field: {field!r}")

        if data["relevance"] not in _RELEVANCE_VALUES:
            raise ValueError(f"invalid relevance value: {data['relevance']!r}")
        if data["category"] not in _CATEGORY_VALUES:
            raise ValueError(f"invalid category value: {data['category']!r}")

        return PageAnalysis(
            page_url=url,
            relevance=data["relevance"],
            category=data["category"],
            summary=data["summary"],
            topics_matched=data.get("topics_matched", []),
        )

    def analyze_nav_changes(self, target_url: str, nav_changes: list, topics: list[str] | None = None) -> PageAnalysis:
        changes_text = _format_nav_changes(nav_changes)
        if topics:
            topics_str = ", ".join(f'"{t}"' for t in topics)
            prompt = _NAV_PROMPT_TEMPLATE_WITH_TOPICS.format(url=target_url, changes=changes_text, topics=topics_str)
        else:
            prompt = _NAV_PROMPT_TEMPLATE.format(url=target_url, changes=changes_text)

        response = self._client.post(
            "/chat/completions",
            json={
                "model": self._config.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(content)

        for field in ("relevance", "category", "summary"):
            if field not in data:
                raise ValueError(f"model response missing field: {field!r}")

        if data["relevance"] not in _RELEVANCE_VALUES:
            raise ValueError(f"invalid relevance value: {data['relevance']!r}")
        if data["category"] not in _CATEGORY_VALUES:
            raise ValueError(f"invalid category value: {data['category']!r}")

        return PageAnalysis(
            page_url=target_url,
            relevance=data["relevance"],
            category=data["category"],
            summary=data["summary"],
            topics_matched=data.get("topics_matched", []),
        )
