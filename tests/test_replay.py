import os
import pytest
from unittest.mock import patch, MagicMock
from docstracker_framework.models import Config, WatchTarget, ModifiedPage, Page, Section
from docstracker_framework.snapshot_store import SnapshotStore
from docstracker_framework.replay import replay_changes, find_last_snapshot_commit


def make_config(targets=None):
    return Config(
        email="user@example.com",
        targets=targets or [WatchTarget(name="My Docs", url="http://example.com/docs/")],
    )


def test_find_last_snapshot_commit_returns_sha():
    mock = MagicMock()
    mock.stdout = "abc1234"
    with patch("subprocess.run", return_value=mock):
        result = find_last_snapshot_commit("snapshots")
    assert result == "abc1234"


def test_find_last_snapshot_commit_returns_none_when_no_history():
    mock = MagicMock()
    mock.stdout = ""
    with patch("subprocess.run", return_value=mock):
        result = find_last_snapshot_commit("snapshots")
    assert result is None


def test_replay_changes_returns_empty_when_no_snapshot_commit(tmp_path):
    config = make_config()
    with patch("docstracker_framework.replay._git_root", return_value=str(tmp_path)), \
         patch("docstracker_framework.replay.find_last_snapshot_commit", return_value=None):
        result = replay_changes(config, str(tmp_path / "snapshots"))
    assert result == {}


def test_replay_changes_returns_modified_pages(tmp_path):
    target = WatchTarget(name="My Docs", url="http://example.com/")
    config = make_config(targets=[target])
    snapshots_dir = tmp_path / "snapshots"

    store = SnapshotStore.for_target(str(snapshots_dir), target)
    page = Page(url="http://example.com/page", sections=[Section(heading="Intro", body="new content")])
    store.write(page)

    filename = store._manifest["http://example.com/page"]
    old_text = "url: http://example.com/page\n\n## Intro\nold content"
    filepath = f"snapshots/my-docs/{filename}"

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if "diff" in cmd:
            result.stdout = f"{filepath}\n"
        elif "show" in cmd:
            result.stdout = old_text
        return result

    with patch("docstracker_framework.replay._git_root", return_value=str(tmp_path)), \
         patch("subprocess.run", side_effect=mock_run):
        result = replay_changes(config, str(snapshots_dir), since="abc1234")

    assert "My Docs" in result
    assert len(result["My Docs"]) == 1
    change = result["My Docs"][0]
    assert isinstance(change, ModifiedPage)
    assert change.page.url == "http://example.com/page"
    assert any(d.heading == "Intro" for d in change.diffs)


def test_replay_changes_skips_new_files(tmp_path):
    target = WatchTarget(name="My Docs", url="http://example.com/")
    config = make_config(targets=[target])
    snapshots_dir = tmp_path / "snapshots"

    store = SnapshotStore.for_target(str(snapshots_dir), target)
    page = Page(url="http://example.com/page", sections=[Section(heading="Intro", body="content")])
    store.write(page)

    filename = store._manifest["http://example.com/page"]
    filepath = f"snapshots/my-docs/{filename}"

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        if "diff" in cmd:
            result.returncode = 0
            result.stdout = f"{filepath}\n"
        elif "show" in cmd:
            result.returncode = 128  # file didn't exist at since-commit
            result.stdout = ""
        return result

    with patch("docstracker_framework.replay._git_root", return_value=str(tmp_path)), \
         patch("subprocess.run", side_effect=mock_run):
        result = replay_changes(config, str(snapshots_dir), since="abc1234")

    assert result == {}


def test_replay_changes_skips_unknown_filenames(tmp_path):
    target = WatchTarget(name="My Docs", url="http://example.com/")
    config = make_config(targets=[target])
    snapshots_dir = tmp_path / "snapshots"
    SnapshotStore.for_target(str(snapshots_dir), target)  # create empty store

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if "diff" in cmd:
            result.stdout = "snapshots/my-docs/deadbeef.txt\n"
        return result

    with patch("docstracker_framework.replay._git_root", return_value=str(tmp_path)), \
         patch("subprocess.run", side_effect=mock_run):
        result = replay_changes(config, str(snapshots_dir), since="abc1234")

    assert result == {}


def test_replay_changes_auto_detects_last_snapshot_commit(tmp_path):
    target = WatchTarget(name="My Docs", url="http://example.com/")
    config = make_config(targets=[target])
    snapshots_dir = tmp_path / "snapshots"

    store = SnapshotStore.for_target(str(snapshots_dir), target)
    page = Page(url="http://example.com/page", sections=[Section(heading="Intro", body="new content")])
    store.write(page)

    filename = store._manifest["http://example.com/page"]
    old_text = "url: http://example.com/page\n\n## Intro\nold content"
    filepath = f"snapshots/my-docs/{filename}"

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if "log" in cmd:
            result.stdout = "deadc0de"
        elif "diff" in cmd and "--name-only" in cmd:
            # auto-detect uses deadc0de^ vs deadc0de
            assert "deadc0de^" in cmd and "deadc0de" in cmd
            result.stdout = f"{filepath}\n"
        elif "show" in cmd:
            if "deadc0de^" in cmd[2]:
                result.stdout = old_text
            else:
                result.stdout = f"url: http://example.com/page\n\n## Intro\nnew content"
        return result

    with patch("docstracker_framework.replay._git_root", return_value=str(tmp_path)), \
         patch("subprocess.run", side_effect=mock_run):
        result = replay_changes(config, str(snapshots_dir))

    assert "My Docs" in result
    assert len(result["My Docs"]) == 1


def test_replay_changes_returns_empty_when_no_diff(tmp_path):
    target = WatchTarget(name="My Docs", url="http://example.com/")
    config = make_config(targets=[target])
    snapshots_dir = tmp_path / "snapshots"
    SnapshotStore.for_target(str(snapshots_dir), target)

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        return result

    with patch("docstracker_framework.replay._git_root", return_value=str(tmp_path)), \
         patch("subprocess.run", side_effect=mock_run):
        result = replay_changes(config, str(snapshots_dir), since="abc1234")

    assert result == {}
