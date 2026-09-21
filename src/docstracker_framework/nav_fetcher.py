from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from docstracker_framework.models import NavNode, NavigationSnapshot, WatchTarget


def _parse_items(items: list[dict], base_url: str) -> list[NavNode]:
    nodes = []
    for item in items:
        title = item.get("name", "")
        href = item.get("href")
        url = urljoin(base_url, href) if href else None
        children = _parse_items(item.get("items", []), base_url)
        nodes.append(NavNode(title=title, url=url, children=children))
    return nodes


def _parse_li(li: Tag, base_url: str) -> NavNode:
    a = li.find("a", href=True, recursive=False)
    sub_ul = li.find("ul", recursive=False)

    if a:
        title = a.get_text(strip=True)
        url = urljoin(base_url, a["href"])
    else:
        label = li.find(["span", "strong"], recursive=False)
        title = label.get_text(strip=True) if label else ""
        url = None

    children = _parse_ul(sub_ul, base_url) if sub_ul else []
    return NavNode(title=title, url=url, children=children)


def _parse_ul(ul: Tag, base_url: str) -> list[NavNode]:
    return [_parse_li(li, base_url) for li in ul.find_all("li", recursive=False)]


def _parse_nav_element(element: Tag, base_url: str) -> list[NavNode]:
    top_ul = element.find("ul", recursive=False)
    if top_ul:
        return _parse_ul(top_ul, base_url)
    # Flat nav: only direct <a> tags, no list structure
    return [
        NavNode(title=a.get_text(strip=True), url=urljoin(base_url, a["href"]))
        for a in element.find_all("a", href=True)
    ]


def parse_nav_html(html: str, base_url: str) -> NavigationSnapshot | None:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("nav") or soup.find(class_="sidebar")
    if container is None:
        return None
    nodes = _parse_nav_element(container, base_url)
    return NavigationSnapshot(nodes=nodes)


def fetch_toc_json(target: WatchTarget) -> NavigationSnapshot | None:
    toc_url = urljoin(target.url, "toc.json")
    try:
        response = httpx.get(toc_url, follow_redirects=True)
        response.raise_for_status()
    except Exception:
        return None
    data = response.json()
    nodes = _parse_items(data.get("items", []), target.url)
    return NavigationSnapshot(nodes=nodes)


def fetch_nav(target: WatchTarget) -> NavigationSnapshot | None:
    snapshot = fetch_toc_json(target)
    if snapshot is not None:
        return snapshot
    try:
        response = httpx.get(target.url, follow_redirects=True)
        response.raise_for_status()
    except Exception:
        return None
    return parse_nav_html(response.text, target.url)
