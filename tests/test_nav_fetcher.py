import json
import pytest
from docstracker_framework.models import WatchTarget
from docstracker_framework.nav_fetcher import fetch_toc_json


TOC_FLAT = {
    "items": [
        {"name": "Overview", "href": "overview"},
        {"name": "Quickstart", "href": "quickstart"},
    ]
}


TOC_NESTED = {
    "items": [
        {
            "name": "Quickstarts",
            "items": [
                {"name": "Create a project", "href": "quickstart-create"},
                {"name": "Deploy a model", "href": "quickstart-deploy"},
            ],
        }
    ]
}


def test_flat_toc_produces_navigation_snapshot_with_correct_nodes(httpx_mock):
    target = WatchTarget(name="My Docs", url="https://docs.example.com/")
    httpx_mock.add_response(
        url="https://docs.example.com/toc.json",
        json=TOC_FLAT,
    )

    snapshot = fetch_toc_json(target)

    assert len(snapshot.nodes) == 2
    assert snapshot.nodes[0].title == "Overview"
    assert snapshot.nodes[0].url == "https://docs.example.com/overview"
    assert snapshot.nodes[1].title == "Quickstart"
    assert snapshot.nodes[1].url == "https://docs.example.com/quickstart"


def test_nested_toc_produces_tree_with_children(httpx_mock):
    target = WatchTarget(name="My Docs", url="https://docs.example.com/")
    httpx_mock.add_response(
        url="https://docs.example.com/toc.json",
        json=TOC_NESTED,
    )

    snapshot = fetch_toc_json(target)

    assert len(snapshot.nodes) == 1
    section = snapshot.nodes[0]
    assert section.title == "Quickstarts"
    assert section.url is None
    assert len(section.children) == 2
    assert section.children[0].title == "Create a project"
    assert section.children[0].url == "https://docs.example.com/quickstart-create"
    assert section.children[1].title == "Deploy a model"


def test_fetch_returns_none_when_toc_json_not_found(httpx_mock):
    target = WatchTarget(name="My Docs", url="https://docs.example.com/")
    httpx_mock.add_response(url="https://docs.example.com/toc.json", status_code=404)

    snapshot = fetch_toc_json(target)

    assert snapshot is None


# ---------------------------------------------------------------------------
# parse_nav_html
# ---------------------------------------------------------------------------

from docstracker_framework.nav_fetcher import parse_nav_html


NAV_FLAT = """
<html><body>
<nav>
  <a href="/intro">Introduction</a>
  <a href="/guide">Guide</a>
</nav>
</body></html>
"""


def test_flat_nav_links_produce_navigation_snapshot():
    snapshot = parse_nav_html(NAV_FLAT, "https://docs.example.com/")

    assert snapshot is not None
    assert len(snapshot.nodes) == 2
    assert snapshot.nodes[0].title == "Introduction"
    assert snapshot.nodes[0].url == "https://docs.example.com/intro"
    assert snapshot.nodes[1].title == "Guide"
    assert snapshot.nodes[1].url == "https://docs.example.com/guide"


NAV_NESTED = """
<html><body>
<nav>
  <ul>
    <li><a href="/intro">Introduction</a></li>
    <li>
      <span>Guides</span>
      <ul>
        <li><a href="/guide1">Guide One</a></li>
        <li><a href="/guide2">Guide Two</a></li>
      </ul>
    </li>
  </ul>
</nav>
</body></html>
"""


def test_nested_ul_li_nav_produces_hierarchical_tree():
    snapshot = parse_nav_html(NAV_NESTED, "https://docs.example.com/")

    assert snapshot is not None
    assert len(snapshot.nodes) == 2

    intro = snapshot.nodes[0]
    assert intro.title == "Introduction"
    assert intro.url == "https://docs.example.com/intro"
    assert intro.children == []

    guides = snapshot.nodes[1]
    assert guides.title == "Guides"
    assert guides.url is None
    assert len(guides.children) == 2
    assert guides.children[0].title == "Guide One"
    assert guides.children[0].url == "https://docs.example.com/guide1"
    assert guides.children[1].title == "Guide Two"


NAV_SIDEBAR = """
<html><body>
<div class="sidebar">
  <a href="/reference">Reference</a>
  <a href="/faq">FAQ</a>
</div>
</body></html>
"""


def test_sidebar_class_element_is_parsed_like_nav():
    snapshot = parse_nav_html(NAV_SIDEBAR, "https://docs.example.com/")

    assert snapshot is not None
    assert len(snapshot.nodes) == 2
    assert snapshot.nodes[0].title == "Reference"
    assert snapshot.nodes[1].title == "FAQ"


def test_page_without_nav_or_sidebar_returns_none():
    html = "<html><body><main><p>No navigation here.</p></main></body></html>"

    snapshot = parse_nav_html(html, "https://docs.example.com/")

    assert snapshot is None


# ---------------------------------------------------------------------------
# fetch_nav
# ---------------------------------------------------------------------------

from docstracker_framework.nav_fetcher import fetch_nav


def test_fetch_nav_uses_toc_json_when_available(httpx_mock):
    target = WatchTarget(name="My Docs", url="https://docs.example.com/")
    httpx_mock.add_response(url="https://docs.example.com/toc.json", json=TOC_FLAT)

    snapshot = fetch_nav(target)

    assert snapshot is not None
    assert len(snapshot.nodes) == 2
    assert snapshot.nodes[0].title == "Overview"
    # Root page was never requested
    assert len([r for r in httpx_mock.get_requests() if r.url == "https://docs.example.com/"]) == 0


def test_fetch_nav_falls_back_to_nav_html_when_no_toc_json(httpx_mock):
    target = WatchTarget(name="My Docs", url="https://docs.example.com/")
    httpx_mock.add_response(url="https://docs.example.com/toc.json", status_code=404)
    httpx_mock.add_response(url="https://docs.example.com/", text=NAV_FLAT)

    snapshot = fetch_nav(target)

    assert snapshot is not None
    assert len(snapshot.nodes) == 2
    assert snapshot.nodes[0].title == "Introduction"


def test_fetch_nav_returns_none_when_no_toc_json_and_no_nav_in_page(httpx_mock):
    target = WatchTarget(name="My Docs", url="https://docs.example.com/")
    httpx_mock.add_response(url="https://docs.example.com/toc.json", status_code=404)
    httpx_mock.add_response(
        url="https://docs.example.com/",
        text="<html><body><main><p>Content only.</p></main></body></html>",
    )

    snapshot = fetch_nav(target)

    assert snapshot is None
