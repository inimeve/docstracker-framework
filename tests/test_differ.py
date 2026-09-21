from docstracker_framework.models import Page, Section, NewPage, ModifiedPage, SectionDiff
from docstracker_framework.differ import Differ


def make_page(url="http://example.com/page", sections=None):
    return Page(url=url, sections=sections or [])


def test_new_page_when_no_previous_snapshot():
    page = make_page(sections=[Section(heading="Intro", body="Hello world")])
    result = Differ().diff(current=page, previous=None)
    assert isinstance(result, NewPage)
    assert result.page == page


def test_no_diff_when_content_unchanged():
    sections = [Section(heading="Intro", body="Hello world")]
    page = make_page(sections=sections)
    previous = make_page(sections=sections)
    result = Differ().diff(current=page, previous=previous)
    assert result is None


def test_modified_page_when_section_body_changes():
    current = make_page(sections=[Section(heading="Intro", body="New content")])
    previous = make_page(sections=[Section(heading="Intro", body="Old content")])
    result = Differ().diff(current=current, previous=previous)
    assert isinstance(result, ModifiedPage)
    assert len(result.diffs) == 1
    diff = result.diffs[0]
    assert diff.heading == "Intro"
    assert "New content" in diff.added
    assert "Old content" in diff.removed


def test_new_section_appears_in_added():
    current = make_page(sections=[
        Section(heading="Intro", body="Hello"),
        Section(heading="New Section", body="Brand new"),
    ])
    previous = make_page(sections=[Section(heading="Intro", body="Hello")])
    result = Differ().diff(current=current, previous=previous)
    assert isinstance(result, ModifiedPage)
    headings = [d.heading for d in result.diffs]
    assert "New Section" in headings
    new_diff = next(d for d in result.diffs if d.heading == "New Section")
    assert "Brand new" in new_diff.added
    assert new_diff.removed == []


def test_removed_section_appears_in_removed():
    current = make_page(sections=[Section(heading="Intro", body="Hello")])
    previous = make_page(sections=[
        Section(heading="Intro", body="Hello"),
        Section(heading="Gone Section", body="Was here"),
    ])
    result = Differ().diff(current=current, previous=previous)
    assert isinstance(result, ModifiedPage)
    headings = [d.heading for d in result.diffs]
    assert "Gone Section" in headings
    gone_diff = next(d for d in result.diffs if d.heading == "Gone Section")
    assert "Was here" in gone_diff.removed
    assert gone_diff.added == []
