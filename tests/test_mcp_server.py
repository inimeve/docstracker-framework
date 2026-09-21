import hashlib
import json
import os
import re
import pytest
import yaml
from docstracker_framework.models import NavNode


def make_config(tmp_path, targets=None):
    if targets is None:
        targets = [
            {"name": "My Docs", "url": "https://docs.example.com/"},
            {"name": "Other Docs", "url": "https://other.example.com/"},
        ]
    config = {"email": "test@example.com", "targets": targets}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(config))
    return str(path)


def make_snapshot(tmp_path, target_name, url, content="## Intro\n\nSome content."):
    slug = re.sub(r"[^a-z0-9]+", "-", target_name.lower()).strip("-")
    filename = hashlib.sha1(url.encode()).hexdigest() + ".txt"
    target_dir = tmp_path / "snapshots" / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / filename).write_text(f"url: {url}\n\n{content}")
    manifest = target_dir / "manifest.json"
    data = json.loads(manifest.read_text()) if manifest.exists() else {}
    data[url] = filename
    manifest.write_text(json.dumps(data))


def make_overview(tmp_path, target_name, content="# Overview\n\n## Scope\nAll about it."):
    slug = re.sub(r"[^a-z0-9]+", "-", target_name.lower()).strip("-")
    target_dir = tmp_path / "snapshots" / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "OVERVIEW.md").write_text(content)


def load_handlers(config_path, snapshots_dir):
    import docstracker_framework.mcp_server as mcp_server
    return mcp_server.make_handlers(config_path, snapshots_dir)


# --- list_targets ---

def test_list_targets_returns_all_configured_target_names(tmp_path):
    config_path = make_config(tmp_path)
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["list_targets"]()

    assert result == ["My Docs", "Other Docs"]


# --- list_pages ---

def test_list_pages_returns_tracked_urls_for_target(tmp_path):
    config_path = make_config(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/page1")
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/page2")
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["list_pages"]("My Docs")

    assert "https://docs.example.com/page1" in result
    assert "https://docs.example.com/page2" in result


def test_list_pages_raises_for_unknown_target(tmp_path):
    config_path = make_config(tmp_path)
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    with pytest.raises(ValueError, match="not found"):
        handlers["list_pages"]("Unknown Target")


# --- read_page ---

def test_read_page_returns_snapshot_markdown(tmp_path):
    config_path = make_config(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/page1")
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["read_page"]("https://docs.example.com/page1")

    assert "Intro" in result
    assert "Some content." in result


def test_read_page_raises_for_untracked_url(tmp_path):
    config_path = make_config(tmp_path)
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    with pytest.raises(ValueError, match="not tracked"):
        handlers["read_page"]("https://docs.example.com/unknown")


# --- read_overview ---

def test_read_overview_returns_overview_md_when_present(tmp_path):
    config_path = make_config(tmp_path)
    make_overview(tmp_path, "My Docs")
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["read_overview"]("My Docs")

    assert "# Overview" in result


def test_read_overview_returns_message_when_not_generated(tmp_path):
    config_path = make_config(tmp_path)
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["read_overview"]("My Docs")

    assert "not yet generated" in result.lower() or "not generated" in result.lower()


def test_read_overview_raises_for_unknown_target(tmp_path):
    config_path = make_config(tmp_path)
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    with pytest.raises(ValueError, match="not found"):
        handlers["read_overview"]("Unknown Target")


# --- read_navigation ---

def make_navigation(tmp_path, target_name, nodes=None):
    import re as _re
    from docstracker_framework.models import NavNode, NavigationSnapshot
    from docstracker_framework.navigation_store import NavigationSnapshotStore
    from docstracker_framework.models import WatchTarget

    if nodes is None:
        nodes = [NavNode(title="Overview", url="https://docs.example.com/overview")]
    target = WatchTarget(name=target_name, url="https://docs.example.com/")
    store = NavigationSnapshotStore.for_target(str(tmp_path / "snapshots"), target)
    store.write(NavigationSnapshot(nodes=nodes))


def test_read_navigation_returns_tree_for_known_target(tmp_path):
    config_path = make_config(tmp_path)
    make_navigation(tmp_path, "My Docs")
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["read_navigation"]("My Docs")

    assert result["nodes"][0]["title"] == "Overview"
    assert result["nodes"][0]["url"] == "https://docs.example.com/overview"


def test_read_navigation_raises_for_unknown_target(tmp_path):
    config_path = make_config(tmp_path)
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    with pytest.raises(ValueError, match="not found"):
        handlers["read_navigation"]("Unknown Target")


def test_read_navigation_returns_message_when_no_snapshot_yet(tmp_path):
    config_path = make_config(tmp_path)
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["read_navigation"]("My Docs")

    assert "not yet" in result.lower() or "no navigation" in result.lower()


# --- list_pages hierarchical ---

def test_list_pages_hierarchical_returns_dict_with_sections_and_ungrouped(tmp_path):
    config_path = make_config(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/overview")
    make_navigation(tmp_path, "My Docs", nodes=[
        NavNode(title="Overview", url="https://docs.example.com/overview"),
    ])
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["list_pages"]("My Docs", hierarchical=True)

    assert isinstance(result, dict)
    assert "sections" in result
    assert "ungrouped" in result


def test_list_pages_hierarchical_nests_tracked_pages_under_nav_sections(tmp_path):
    config_path = make_config(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/guide/intro")
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/guide/install")
    make_navigation(tmp_path, "My Docs", nodes=[
        NavNode(title="Guide", url=None, children=[
            NavNode(title="Intro", url="https://docs.example.com/guide/intro"),
            NavNode(title="Install", url="https://docs.example.com/guide/install"),
        ]),
    ])
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["list_pages"]("My Docs", hierarchical=True)

    assert len(result["sections"]) == 1
    guide = result["sections"][0]
    assert guide["title"] == "Guide"
    assert guide["url"] is None
    child_urls = [c["url"] for c in guide["children"]]
    assert "https://docs.example.com/guide/intro" in child_urls
    assert "https://docs.example.com/guide/install" in child_urls


def test_list_pages_hierarchical_puts_pages_absent_from_nav_in_ungrouped(tmp_path):
    config_path = make_config(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/in-nav")
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/orphan")
    make_navigation(tmp_path, "My Docs", nodes=[
        NavNode(title="In Nav", url="https://docs.example.com/in-nav"),
    ])
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["list_pages"]("My Docs", hierarchical=True)

    assert "https://docs.example.com/orphan" in result["ungrouped"]
    assert "https://docs.example.com/in-nav" not in result["ungrouped"]


def test_list_pages_hierarchical_with_no_nav_snapshot_returns_all_pages_ungrouped(tmp_path):
    config_path = make_config(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/page1")
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/page2")
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    result = handlers["list_pages"]("My Docs", hierarchical=True)

    assert result["sections"] == []
    assert "https://docs.example.com/page1" in result["ungrouped"]
    assert "https://docs.example.com/page2" in result["ungrouped"]


def test_list_pages_hierarchical_raises_for_unknown_target(tmp_path):
    config_path = make_config(tmp_path)
    handlers = load_handlers(config_path, str(tmp_path / "snapshots"))

    with pytest.raises(ValueError, match="not found"):
        handlers["list_pages"]("Unknown Target", hierarchical=True)
