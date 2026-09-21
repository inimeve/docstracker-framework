from docstracker_framework.models import Page, Section, WatchTarget
from docstracker_framework.snapshot_store import SnapshotStore


def make_page(url="http://example.com/docs/page"):
    return Page(url=url, sections=[
        Section(heading="Overview", body="First line\nSecond line"),
        Section(heading="Details", body="More info here"),
    ])


def test_write_and_read_roundtrip(tmp_path):
    store = SnapshotStore(base_dir=str(tmp_path))
    page = make_page()
    store.write(page)
    retrieved = store.read(page.url)
    assert retrieved == page


def test_read_nonexistent_returns_none(tmp_path):
    store = SnapshotStore(base_dir=str(tmp_path))
    result = store.read("http://example.com/does-not-exist")
    assert result is None


def test_roundtrip_with_empty_section_body(tmp_path):
    store = SnapshotStore(base_dir=str(tmp_path))
    page = Page(url="http://example.com/page", sections=[
        Section(heading="Empty Section", body=""),
        Section(heading="Normal", body="Has content"),
    ])
    store.write(page)
    assert store.read(page.url) == page


def test_manifest_updated_after_write(tmp_path):
    store = SnapshotStore(base_dir=str(tmp_path))
    page = make_page()
    store.write(page)
    retrieved = store.read(page.url)
    assert retrieved is not None


def test_for_target_isolates_watch_target_snapshots(tmp_path):
    docs_a = WatchTarget(name="Docs A", url="http://a.example.com/docs/")
    docs_b = WatchTarget(name="Docs B", url="http://b.example.com/docs/")
    page = make_page("http://example.com/docs/shared")

    SnapshotStore.for_target(str(tmp_path), docs_a).write(page)

    assert SnapshotStore.for_target(str(tmp_path), docs_a).read(page.url) == page
    assert SnapshotStore.for_target(str(tmp_path), docs_b).read(page.url) is None


def test_tracked_page_urls_returns_written_page_urls(tmp_path):
    store = SnapshotStore(base_dir=str(tmp_path))
    page = make_page("http://example.com/docs/tracked")

    store.write(page)

    assert store.tracked_page_urls() == [page.url]


def test_roundtrip_preserves_section_headings_inside_code_fences(tmp_path):
    store = SnapshotStore(base_dir=str(tmp_path))
    body_with_fence = (
        "Intro text.\n\n"
        "```\n"
        "## Heading Inside Fence\n"
        "Some code here.\n"
        "```\n\n"
        "Trailing text."
    )
    page = Page(url="http://example.com/page", sections=[
        Section(heading="Outer Section", body=body_with_fence),
        Section(heading="Real Next Section", body="Real content."),
    ])
    store.write(page)
    assert store.read(page.url) == page


def test_roundtrip_preserves_double_newlines_in_section_body(tmp_path):
    store = SnapshotStore(base_dir=str(tmp_path))
    page = Page(url="http://example.com/page", sections=[
        Section(heading="With Paragraphs", body="First paragraph.\n\nSecond paragraph.\n\nThird paragraph."),
        Section(heading="Normal", body="Single line."),
    ])
    store.write(page)
    assert store.read(page.url) == page


def test_read_only_operations_do_not_create_snapshot_directories(tmp_path):
    target = WatchTarget(name="My Docs", url="http://example.com/docs/")
    snapshots_dir = tmp_path / "snapshots"

    store = SnapshotStore.for_target(str(snapshots_dir), target)

    assert store.read("http://example.com/docs/missing") is None
    assert store.tracked_page_urls() == []
    assert not snapshots_dir.exists()
