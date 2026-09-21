import pytest

from docstracker_framework.change_report import build_change_report_html
from docstracker_framework.models import ModifiedPage, NewPage, Page, PageAnalysis, Section, SectionDiff, NavNodeAdded, NavNodeRemoved, NavNodeRenamed


def test_change_report_groups_changes_by_watch_target():
    changes_by_target = {
        "Foundry Docs": [
            NewPage(page=Page(url="https://docs.example.com/intro", sections=[Section("Intro", "Hello")]))
        ],
        "Stripe Docs": [
            ModifiedPage(
                page=Page(url="https://stripe.example.com/guide", sections=[]),
                diffs=[SectionDiff(heading="Setup", added=["Install CLI"], removed=["Download zip"])],
            )
        ],
    }

    html = build_change_report_html(changes_by_target)

    assert "DocTracker" in html
    assert "1 new page" in html
    assert "1 modified page" in html
    assert "Foundry Docs" in html
    assert "1 change" in html
    assert "https://docs.example.com/intro" in html
    assert "1 section(s) captured" in html
    assert "Stripe Docs" in html
    assert "https://stripe.example.com/guide" in html
    assert "Setup" in html
    assert "+ Install CLI" in html
    assert "- Download zip" in html


def test_analysis_enrichment_shows_relevance_category_summary_above_diffs():
    page = Page(url="https://docs.example.com/api", sections=[])
    analysis = PageAnalysis(
        page_url="https://docs.example.com/api",
        relevance="high",
        category="breaking-change",
        summary="The auth endpoint now requires a header.",
    )
    changes_by_target = {
        "API Docs": [
            ModifiedPage(
                page=page,
                diffs=[SectionDiff(heading="Auth", added=["Requires X-Token header"], removed=[])],
            )
        ]
    }
    analyses = {"API Docs": [analysis]}

    html = build_change_report_html(changes_by_target, analyses=analyses)

    assert "high" in html
    assert "breaking-change" in html
    assert "The auth endpoint now requires a header." in html
    # summary appears before the diff heading
    assert html.index("The auth endpoint now requires a header.") < html.index("§ Auth")


def test_pages_ordered_high_medium_low_within_target():
    low_page = Page(url="https://docs.example.com/low", sections=[])
    medium_page = Page(url="https://docs.example.com/medium", sections=[])
    high_page = Page(url="https://docs.example.com/high", sections=[])
    analyses = {
        "Docs": [
            PageAnalysis(page_url=low_page.url, relevance="low", category="cosmetic", summary="Minor styling fix."),
            PageAnalysis(page_url=medium_page.url, relevance="medium", category="clarification", summary="Clarified wording."),
            PageAnalysis(page_url=high_page.url, relevance="high", category="breaking-change", summary="Breaking change!"),
        ]
    }
    changes_by_target = {
        "Docs": [
            ModifiedPage(page=low_page, diffs=[]),
            ModifiedPage(page=medium_page, diffs=[]),
            ModifiedPage(page=high_page, diffs=[]),
        ]
    }

    html = build_change_report_html(changes_by_target, analyses=analyses)

    assert html.index("high_page" if False else high_page.url) < html.index(medium_page.url) < html.index(low_page.url)


def test_category_badge_css_classes():
    def _html_for_category(category):
        page = Page(url="https://docs.example.com/p", sections=[])
        analysis = PageAnalysis(page_url=page.url, relevance="high", category=category, summary="s")
        return build_change_report_html(
            {"T": [ModifiedPage(page=page, diffs=[])]},
            analyses={"T": [analysis]},
        )

    assert "cat-breaking-change" in _html_for_category("breaking-change")
    assert "cat-deprecation" in _html_for_category("deprecation")
    assert "cat-cosmetic" in _html_for_category("cosmetic")
    # default class for other categories
    assert "cat-default" in _html_for_category("new-feature")


def test_change_report_rejects_unsupported_change_types():
    with pytest.raises(TypeError, match="Unsupported change type"):
        build_change_report_html({"My Docs": [object()]})


def test_change_report_renders_nav_changes_grouped_by_target():
    nav_changes = [
        NavNodeAdded(title="Best practices", url="https://docs.example.com/best-practices"),
        NavNodeRemoved(title="Legacy guide", url=None),
        NavNodeRenamed(old_title="API reference", new_title="Reference", url="https://docs.example.com/ref"),
    ]
    html = build_change_report_html(
        {},
        nav_changes_by_target={"My Docs": nav_changes},
    )
    assert "My Docs" in html
    assert "Best practices" in html
    assert "Legacy guide" in html
    assert "API reference" in html
    assert "Reference" in html


def test_change_report_highlights_topic_matched_pages():
    page = Page(url="https://docs.example.com/net", sections=[])
    analysis = PageAnalysis(
        page_url="https://docs.example.com/net",
        relevance="high",
        category="new-feature",
        summary="VNet peering added.",
        topics_matched=["networking"],
    )
    changes_by_target = {
        "Azure Docs": [
            ModifiedPage(page=page, diffs=[SectionDiff(heading="Network", added=["VNet peering"], removed=[])]),
        ]
    }
    analyses = {"Azure Docs": [analysis]}

    html = build_change_report_html(changes_by_target, analyses=analyses)

    assert "networking" in html
    assert "<div class='topics-row'>" in html


def test_executive_summary_shows_category_counts_and_high_relevance():
    pages = [
        Page(url="https://docs.example.com/a", sections=[]),
        Page(url="https://docs.example.com/b", sections=[]),
        Page(url="https://docs.example.com/c", sections=[]),
    ]
    analyses = {
        "Docs": [
            PageAnalysis(page_url=pages[0].url, relevance="high", category="breaking-change", summary="Auth endpoint changed."),
            PageAnalysis(page_url=pages[1].url, relevance="medium", category="breaking-change", summary="Rate limit lowered."),
            PageAnalysis(page_url=pages[2].url, relevance="low", category="cosmetic", summary="Minor styling."),
        ]
    }
    changes_by_target = {"Docs": [ModifiedPage(page=p, diffs=[]) for p in pages]}

    html = build_change_report_html(changes_by_target, analyses=analyses)

    assert "class='dashboard'" in html
    assert "2 breaking-change" in html
    assert "1 cosmetic" in html
    # only the high-relevance item appears in the spotlight
    assert "Auth endpoint changed." in html
    assert html.index("class='dashboard'") < html.index("class='target'")


def test_executive_summary_absent_without_analyses():
    page = Page(url="https://docs.example.com/x", sections=[])
    changes_by_target = {"Docs": [ModifiedPage(page=page, diffs=[])]}

    html = build_change_report_html(changes_by_target)

    assert "class='exec-summary'" not in html


def test_executive_summary_no_high_items_omits_highlights_section():
    page = Page(url="https://docs.example.com/x", sections=[])
    analyses = {"Docs": [PageAnalysis(page_url=page.url, relevance="low", category="cosmetic", summary="Minor.")]}
    changes_by_target = {"Docs": [ModifiedPage(page=page, diffs=[])]}

    html = build_change_report_html(changes_by_target, analyses=analyses)

    assert "class='dashboard'" in html
    assert "class='highlight-item'" not in html


def test_run_summary_renders_digest_bullets():
    page = Page(url="https://docs.example.com/x", sections=[])
    changes_by_target = {"Docs": [ModifiedPage(page=page, diffs=[])]}
    digest = [
        {"rel": "high", "text": "Cambio crítico en la API de auth."},
        {"rel": "low", "text": "Pequeño ajuste cosmético."},
    ]

    html = build_change_report_html(changes_by_target, digest=digest)

    assert "Resumen del run" in html
    assert "Cambio crítico en la API de auth." in html
    assert "Pequeño ajuste cosmético." in html
    # bullets appear before the per-target detail
    assert html.index("Cambio crítico") < html.index("class='target'")


def test_run_summary_omitted_without_digest():
    page = Page(url="https://docs.example.com/x", sections=[])
    changes_by_target = {"Docs": [ModifiedPage(page=page, diffs=[])]}

    html = build_change_report_html(changes_by_target)

    assert "Resumen del run" not in html


def test_change_report_no_topic_highlight_when_topics_matched_empty():
    page = Page(url="https://docs.example.com/p", sections=[])
    analysis = PageAnalysis(
        page_url="https://docs.example.com/p",
        relevance="low",
        category="cosmetic",
        summary="Minor change.",
        topics_matched=[],
    )
    changes_by_target = {
        "Docs": [ModifiedPage(page=page, diffs=[])]
    }
    analyses = {"Docs": [analysis]}

    html = build_change_report_html(changes_by_target, analyses=analyses)

    assert "<div class='topics-row'>" not in html
