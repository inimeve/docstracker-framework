import pytest
from docstracker_framework.models import NavNode, NavigationSnapshot, NavNodeAdded, NavNodeRemoved, NavNodeRenamed
from docstracker_framework.nav_differ import NavDiffer


def snap(*nodes):
    return NavigationSnapshot(nodes=list(nodes))


def node(title, url=None, *children):
    return NavNode(title=title, url=url, children=list(children))


def test_identical_snapshots_produce_no_changes():
    s = snap(node("Overview", "https://docs.example.com/overview"))
    assert NavDiffer().diff(s, s) == []


def test_nested_node_added_carries_parent_title():
    previous = snap(node("Getting started", "https://docs.example.com/start"))
    current = snap(
        node(
            "Getting started",
            "https://docs.example.com/start",
            node("Quickstart", "https://docs.example.com/start/quick"),
        )
    )
    changes = NavDiffer().diff(previous, current)
    assert len(changes) == 1
    assert isinstance(changes[0], NavNodeAdded)
    assert changes[0].title == "Quickstart"
    assert changes[0].parent_title == "Getting started"


def test_same_url_different_title_detected_as_renamed():
    url = "https://docs.example.com/ref"
    previous = snap(node("API reference", url))
    current = snap(node("Reference", url))
    changes = NavDiffer().diff(previous, current)
    assert len(changes) == 1
    assert isinstance(changes[0], NavNodeRenamed)
    assert changes[0].old_title == "API reference"
    assert changes[0].new_title == "Reference"
    assert changes[0].url == url
    assert changes[0].parent_title is None


def test_missing_node_detected_as_removed():
    previous = snap(
        node("Overview", "https://docs.example.com/overview"),
        node("Legacy guide", "https://docs.example.com/legacy"),
    )
    current = snap(node("Overview", "https://docs.example.com/overview"))
    changes = NavDiffer().diff(previous, current)
    assert len(changes) == 1
    assert isinstance(changes[0], NavNodeRemoved)
    assert changes[0].title == "Legacy guide"
    assert changes[0].url == "https://docs.example.com/legacy"
    assert changes[0].parent_title is None


def test_new_top_level_node_detected_as_added():
    previous = snap(node("Overview", "https://docs.example.com/overview"))
    current = snap(
        node("Overview", "https://docs.example.com/overview"),
        node("Best practices", "https://docs.example.com/best-practices"),
    )
    changes = NavDiffer().diff(previous, current)
    assert len(changes) == 1
    assert isinstance(changes[0], NavNodeAdded)
    assert changes[0].title == "Best practices"
    assert changes[0].url == "https://docs.example.com/best-practices"
    assert changes[0].parent_title is None
