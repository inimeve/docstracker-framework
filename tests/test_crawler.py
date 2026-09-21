from docstracker_framework.crawler import _http_verify, _parse_page

SIMPLE_PAGE = """
<html>
<body>
  <h1>Title</h1>
  <p>Intro paragraph.</p>
  <h2>Section One</h2>
  <p>First section body.</p>
  <h3>Subsection</h3>
  <p>Subsection body.</p>
</body>
</html>
"""

PAGE_WITH_BOILERPLATE = """
<html>
<body>
  <nav>Navigation links go here <a href="/docs/nav-page#top">Nav page</a></nav>
  <aside class="sidebar">Sidebar content</aside>
  <h1>Main Title</h1>
  <p>Real content here.</p>
  <footer>Footer content</footer>
</body>
</html>
"""


def test_parse_page_extracts_sections_from_headings():
    url = "https://example.com/docs/page"
    page = _parse_page(url, SIMPLE_PAGE).page

    assert page.url == url
    headings = [s.heading for s in page.sections]
    assert "Title" in headings
    assert "Section One" in headings
    assert "Subsection" in headings


PAGE_WITH_LINKS = """
<html>
<body>
  <h1>Links</h1>
  <a href="/docs/relative#intro">Relative</a>
  <a href="https://external.example/docs/page#section">External</a>
</body>
</html>
"""


def test_parse_page_section_body_contains_paragraph_text():
    page = _parse_page("https://example.com/docs/page", SIMPLE_PAGE).page

    intro = next(s for s in page.sections if s.heading == "Title")
    assert "Intro paragraph" in intro.body


def test_parse_page_excludes_boilerplate_from_section_content():
    page = _parse_page("https://example.com/docs/page", PAGE_WITH_BOILERPLATE).page

    full_text = " ".join(s.body for s in page.sections)
    assert "Navigation links" not in full_text
    assert "Sidebar content" not in full_text
    assert "Footer content" not in full_text
    assert "Real content here" in full_text


def test_parse_page_returns_normalized_absolute_links_without_fragments():
    parsed = _parse_page("https://example.com/docs/page", PAGE_WITH_LINKS)

    assert parsed.links == [
        "https://example.com/docs/relative",
        "https://external.example/docs/page",
    ]


def test_parse_page_returns_links_from_boilerplate_html():
    parsed = _parse_page("https://example.com/docs/page", PAGE_WITH_BOILERPLATE)

    assert "https://example.com/docs/nav-page" in parsed.links


PAGE_WITH_CODE_BLOCK = """
<html><body>
  <h1>Installation</h1>
  <pre><code>pip install docstracker</code></pre>
</body></html>
"""


def test_parse_page_section_body_includes_code_block():
    page = _parse_page("https://example.com/docs/", PAGE_WITH_CODE_BLOCK).page

    installation = next(s for s in page.sections if s.heading == "Installation")
    assert "pip install docstracker" in installation.body


PAGE_WITH_TABLE = """
<html><body>
  <h1>Limits</h1>
  <table>
    <tr><th>Plan</th><th>Pages</th></tr>
    <tr><td>Free</td><td>100</td></tr>
  </table>
</body></html>
"""


def test_parse_page_section_body_includes_table_content():
    page = _parse_page("https://example.com/docs/", PAGE_WITH_TABLE).page

    limits = next(s for s in page.sections if s.heading == "Limits")
    assert "Free" in limits.body
    assert "100" in limits.body


PAGE_WITH_LIST = """
<html><body>
  <h1>Features</h1>
  <ul>
    <li>Change detection</li>
    <li>Email notifications</li>
  </ul>
</body></html>
"""


def test_parse_page_section_body_includes_list_items():
    page = _parse_page("https://example.com/docs/", PAGE_WITH_LIST).page

    features = next(s for s in page.sections if s.heading == "Features")
    assert "Change detection" in features.body
    assert "Email notifications" in features.body


def test_http_verify_uses_requests_ca_bundle_when_ssl_cert_file_absent(monkeypatch):
    captured = {}
    context = object()

    def fake_context(*, cafile):
        captured["cafile"] = cafile
        return context

    monkeypatch.setattr("docstracker_framework.crawler.ssl.create_default_context", fake_context)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/custom/ca.pem")

    assert _http_verify() is context
    assert captured["cafile"] == "/custom/ca.pem"
