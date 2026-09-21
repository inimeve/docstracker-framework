import pytest
from docstracker_framework.models import NavNode, NavigationSnapshot, WatchTarget
from docstracker_framework.navigation_store import NavigationSnapshotStore


def make_snapshot():
    return NavigationSnapshot(nodes=[
        NavNode(title="Overview", url="https://docs.example.com/overview", children=[]),
        NavNode(
            title="Quickstarts",
            url=None,
            children=[
                NavNode(title="Create", url="https://docs.example.com/create", children=[]),
            ],
        ),
    ])


def test_write_and_read_roundtrip(tmp_path):
    store = NavigationSnapshotStore(base_dir=str(tmp_path))
    snapshot = make_snapshot()

    store.write(snapshot)
    result = store.read()

    assert result == snapshot


def test_read_returns_none_when_no_file_exists(tmp_path):
    store = NavigationSnapshotStore(base_dir=str(tmp_path / "nonexistent"))

    assert store.read() is None


def test_write_creates_navigation_json_file(tmp_path):
    store = NavigationSnapshotStore(base_dir=str(tmp_path))

    store.write(make_snapshot())

    assert (tmp_path / "navigation.json").exists()


def test_for_target_uses_same_slug_as_snapshot_store(tmp_path):
    from docstracker_framework.snapshot_store import SnapshotStore
    import re

    target = WatchTarget(name="Azure Foundry", url="https://docs.example.com/")
    nav_store = NavigationSnapshotStore.for_target(str(tmp_path), target)
    snap_store = SnapshotStore.for_target(str(tmp_path), target)

    expected_slug = re.sub(r"[^a-z0-9]+", "-", target.name.lower()).strip("-")
    assert nav_store._base_dir == snap_store._base_dir
    assert expected_slug in nav_store._base_dir
