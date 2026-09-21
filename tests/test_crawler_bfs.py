from pytest_httpserver import HTTPServer
from docstracker_framework.models import WatchTarget
from docstracker_framework.crawler import Crawler
from docstracker_framework.extractor import Extractor


def test_crawler_implements_extractor_interface():
    assert isinstance(Crawler(), Extractor)

ROOT = """
<html><body>
  <h1>Root</h1>
  <a href="/docs/page-a">Page A</a>
  <a href="/docs/page-b">Page B</a>
  <a href="/other/outside">Outside</a>
</body></html>
"""

PAGE_A = """
<html><body>
  <h1>Page A</h1>
  <p>Content of A.</p>
  <a href="/docs/page-c">Page C</a>
</body></html>
"""

PAGE_B = """
<html><body>
  <h1>Page B</h1>
  <p>Content of B.</p>
</body></html>
"""

PAGE_C = """
<html><body>
  <h1>Page C</h1>
  <p>Content of C.</p>
</body></html>
"""

OUTSIDE = """
<html><body>
  <h1>Outside</h1>
  <p>Should not be crawled.</p>
</body></html>
"""


def setup_tree(httpserver: HTTPServer):
    httpserver.expect_request("/docs/").respond_with_data(ROOT, content_type="text/html")
    httpserver.expect_request("/docs/page-a").respond_with_data(PAGE_A, content_type="text/html")
    httpserver.expect_request("/docs/page-b").respond_with_data(PAGE_B, content_type="text/html")
    httpserver.expect_request("/docs/page-c").respond_with_data(PAGE_C, content_type="text/html")
    httpserver.expect_request("/other/outside").respond_with_data(OUTSIDE, content_type="text/html")


def test_crawl_returns_all_pages_under_prefix(httpserver: HTTPServer):
    setup_tree(httpserver)
    root_url = httpserver.url_for("/docs/")
    target = WatchTarget(name="Docs", url=root_url)
    pages = Crawler().crawl(target)
    urls = [p.url for p in pages]
    assert httpserver.url_for("/docs/") in urls
    assert httpserver.url_for("/docs/page-a") in urls
    assert httpserver.url_for("/docs/page-b") in urls
    assert httpserver.url_for("/docs/page-c") in urls


def test_crawl_does_not_follow_links_outside_prefix(httpserver: HTTPServer):
    setup_tree(httpserver)
    root_url = httpserver.url_for("/docs/")
    target = WatchTarget(name="Docs", url=root_url)
    pages = Crawler().crawl(target)
    urls = [p.url for p in pages]
    assert httpserver.url_for("/other/outside") not in urls


def test_crawl_stops_at_max_pages(httpserver: HTTPServer):
    setup_tree(httpserver)
    root_url = httpserver.url_for("/docs/")
    target = WatchTarget(name="Docs", url=root_url, max_pages=2)
    pages = Crawler().crawl(target)
    assert len(pages) == 2


def test_url_linked_from_multiple_pages_enqueued_once(httpserver: HTTPServer):
    # root → page-a and hub; page-a → hub
    # When hub is processed it should report 0 pages in queue (no duplicate hub entries)
    httpserver.expect_request("/docs/").respond_with_data(
        '<html><body><h1>Root</h1><a href="/docs/page-a">A</a><a href="/docs/hub">Hub</a></body></html>',
        content_type="text/html",
    )
    httpserver.expect_request("/docs/page-a").respond_with_data(
        '<html><body><h1>A</h1><a href="/docs/hub">Hub</a></body></html>',
        content_type="text/html",
    )
    httpserver.expect_request("/docs/hub").respond_with_data(
        '<html><body><h1>Hub</h1></body></html>',
        content_type="text/html",
    )
    root_url = httpserver.url_for("/docs/")
    target = WatchTarget(name="Docs", url=root_url)
    calls = []
    Crawler().crawl(target, on_page=lambda url, crawled, queued: calls.append((url, queued)))
    hub_url = httpserver.url_for("/docs/hub")
    hub_call = next(c for c in calls if c[0] == hub_url)
    assert hub_call[1] == 0, f"hub was enqueued multiple times (queue had {hub_call[1]} duplicates when hub was processed)"


def test_on_page_called_for_each_eligible_url_attempt(httpserver: HTTPServer):
    setup_tree(httpserver)
    root_url = httpserver.url_for("/docs/")
    target = WatchTarget(name="Docs", url=root_url)
    calls = []
    Crawler().crawl(target, on_page=lambda url, crawled, queued: calls.append(url))
    assert httpserver.url_for("/docs/") in calls
    assert httpserver.url_for("/docs/page-a") in calls
    assert httpserver.url_for("/docs/page-b") in calls
    assert httpserver.url_for("/docs/page-c") in calls


def test_crawl_filters_known_media_archive_and_font_urls(httpserver: HTTPServer):
    httpserver.expect_request("/docs/").respond_with_data(
        """
        <html><body>
          <h1>Root</h1>
          <a href="/docs/page">Page</a>
          <a href="/docs/image.png">Image</a>
          <a href="/docs/archive.zip">Archive</a>
          <a href="/docs/font.woff2">Font</a>
        </body></html>
        """,
        content_type="text/html",
    )
    httpserver.expect_request("/docs/page").respond_with_data(
        '<html><body><h1>Page</h1></body></html>',
        content_type="text/html",
    )
    root_url = httpserver.url_for("/docs/")
    target = WatchTarget(name="Docs", url=root_url)
    calls = []

    pages = Crawler().crawl(target, on_page=lambda url, crawled, queued: calls.append(url))

    assert [page.url for page in pages] == [root_url, httpserver.url_for("/docs/page")]
    assert httpserver.url_for("/docs/image.png") not in calls
    assert httpserver.url_for("/docs/archive.zip") not in calls
    assert httpserver.url_for("/docs/font.woff2") not in calls


def test_on_page_receives_correct_crawled_and_queue_counts(httpserver: HTTPServer):
    httpserver.expect_request("/docs/").respond_with_data(
        '<html><body><h1>Root</h1><a href="/docs/page-a">A</a></body></html>',
        content_type="text/html",
    )
    httpserver.expect_request("/docs/page-a").respond_with_data(
        '<html><body><h1>A</h1></body></html>',
        content_type="text/html",
    )
    root_url = httpserver.url_for("/docs/")
    target = WatchTarget(name="Docs", url=root_url)
    calls = []
    Crawler().crawl(target, on_page=lambda url, crawled, queued: calls.append((crawled, queued)))
    # First call: 0 pages done, queue had the root (now popped), page-a discovered after fetch
    assert calls[0] == (0, 0)
    # Second call: 1 page done, queue empty after popping page-a
    assert calls[1] == (1, 0)
