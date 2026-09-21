from collections import deque
from dataclasses import dataclass
import os
import ssl
from urllib.parse import urljoin, urldefrag

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from docstracker_framework.extractor import Extractor
from docstracker_framework.models import Page, Section, WatchTarget

_HEADING_TAGS = {"h1", "h2", "h3"}
_BOILERPLATE_TAGS = {"nav", "footer", "aside"}
_MEDIA_EXTENSIONS = {
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".mp4", ".mp3", ".woff", ".woff2",
}


@dataclass
class _ParsedPage:
    page: Page
    links: list[str]


def _remove_boilerplate(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(_BOILERPLATE_TAGS):
        tag.decompose()
    for tag in soup.find_all(class_="sidebar"):
        tag.decompose()


def _extract_sections(soup: BeautifulSoup) -> list[Section]:
    sections = []
    for heading in soup.find_all(_HEADING_TAGS):
        heading_text = heading.get_text(strip=True)
        body_html = []
        for sibling in heading.find_next_siblings():
            if sibling.name in _HEADING_TAGS:
                break
            if sibling.name:
                body_html.append(str(sibling))
        body = md("".join(body_html)).strip()
        sections.append(Section(heading=heading_text, body=body))
    return sections


def _parse_page(url: str, html: str) -> _ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a_tag in soup.find_all("a", href=True):
        href = urljoin(url, a_tag["href"])
        href, _ = urldefrag(href)
        links.append(href)

    _remove_boilerplate(soup)
    sections = _extract_sections(soup)
    return _ParsedPage(page=Page(url=url, sections=sections), links=links)


def _http_verify() -> bool | ssl.SSLContext:
    cafile = (
        os.environ.get("SSL_CERT_FILE")
        or os.environ.get("REQUESTS_CA_BUNDLE")
        or os.environ.get("CURL_CA_BUNDLE")
    )
    return ssl.create_default_context(cafile=cafile) if cafile else True


class Crawler(Extractor):
    def crawl(self, target: WatchTarget, on_page=None) -> list[Page]:
        self.failures = []
        prefix = target.url
        queue: deque[str] = deque([prefix])
        seen: set[str] = {prefix}  # enqueued or already processed — prevents duplicate queue entries
        pages: list[Page] = []
        verify = _http_verify()

        while queue and len(pages) < target.max_pages:
            url = queue.popleft()
            url, _ = urldefrag(url)
            if not url.startswith(prefix):
                continue

            if on_page:
                on_page(url, len(pages), len(queue))

            try:
                response = httpx.get(url, follow_redirects=True, verify=verify)
                response.raise_for_status()
            except Exception as exc:
                self.failures.append({"url": url, "reason": str(exc)})
                continue

            parsed = _parse_page(url, response.text)
            pages.append(parsed.page)

            for href in parsed.links:
                ext = "." + href.rsplit(".", 1)[-1].lower() if "." in href.rsplit("/", 1)[-1] else ""
                if href.startswith(prefix) and href not in seen and ext not in _MEDIA_EXTENSIONS:
                    queue.append(href)
                    seen.add(href)

        return pages
