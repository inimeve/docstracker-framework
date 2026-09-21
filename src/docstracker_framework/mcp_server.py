import os
import re

from docstracker_framework.config_loader import load_config
from docstracker_framework.snapshot_store import SnapshotStore
from docstracker_framework.navigation_store import NavigationSnapshotStore

from mcp.server.fastmcp import FastMCP


def _snapshots_dir_from_config(config_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "snapshots")


def _target_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _collect_nav_urls(nodes) -> set:
    urls = set()
    for node in nodes:
        if node.url:
            urls.add(node.url)
        urls |= _collect_nav_urls(node.children)
    return urls


def _build_hierarchy_node(node, tracked: set) -> "dict | None":
    is_tracked = node.url is not None and node.url in tracked
    children = [_build_hierarchy_node(c, tracked) for c in node.children]
    children = [c for c in children if c is not None]
    if is_tracked or children:
        return {"title": node.title, "url": node.url, "children": children}
    return None


def _build_hierarchy(nav_nodes, tracked_urls: list) -> dict:
    tracked = set(tracked_urls)
    all_nav_urls = _collect_nav_urls(nav_nodes)
    sections = [_build_hierarchy_node(n, tracked) for n in nav_nodes]
    sections = [s for s in sections if s is not None]
    ungrouped = [url for url in tracked_urls if url not in all_nav_urls]
    return {"sections": sections, "ungrouped": ungrouped}


def make_handlers(config_path: str, snapshots_dir: str) -> dict:
    config = load_config(config_path)

    def list_targets() -> list[str]:
        return [t.name for t in config.targets]

    def list_pages(target: str, hierarchical: bool = False) -> "list[str] | dict":
        matched = [t for t in config.targets if t.name == target]
        if not matched:
            raise ValueError(f"Watch Target '{target}' not found")
        store = SnapshotStore.for_target(snapshots_dir, matched[0])
        urls = store.tracked_page_urls()
        if not hierarchical:
            return urls
        nav_store = NavigationSnapshotStore.for_target(snapshots_dir, matched[0])
        snapshot = nav_store.read()
        nav_nodes = snapshot.nodes if snapshot is not None else []
        return _build_hierarchy(nav_nodes, urls)

    def read_page(url: str) -> str:
        for target in config.targets:
            store = SnapshotStore.for_target(snapshots_dir, target)
            page = store.read(url)
            if page is not None:
                parts = []
                for section in page.sections:
                    parts.append(f"## {section.heading}")
                    if section.body:
                        parts.append(section.body)
                return "\n\n".join(parts)
        raise ValueError(f"URL '{url}' is not tracked in any Watch Target")

    def read_overview(target: str) -> str:
        matched = [t for t in config.targets if t.name == target]
        if not matched:
            raise ValueError(f"Watch Target '{target}' not found")
        slug = _target_slug(target)
        overview_path = os.path.join(snapshots_dir, slug, "OVERVIEW.md")
        if os.path.exists(overview_path):
            with open(overview_path) as f:
                return f.read()
        return f"Target Overview for '{target}' not yet generated. Run: docstracker overview --target \"{target}\""

    def read_navigation(target: str) -> dict | str:
        matched = [t for t in config.targets if t.name == target]
        if not matched:
            raise ValueError(f"Watch Target '{target}' not found")
        store = NavigationSnapshotStore.for_target(snapshots_dir, matched[0])
        snapshot = store.read()
        if snapshot is None:
            return f"Navigation snapshot for '{target}' not yet captured. Run a crawl first."

        def node_to_dict(node):
            return {
                "title": node.title,
                "url": node.url,
                "children": [node_to_dict(c) for c in node.children],
            }

        return {"nodes": [node_to_dict(n) for n in snapshot.nodes]}

    return {
        "list_targets": list_targets,
        "list_pages": list_pages,
        "read_page": read_page,
        "read_overview": read_overview,
        "read_navigation": read_navigation,
    }


def _make_server(config_path: str) -> FastMCP:
    snapshots_dir = _snapshots_dir_from_config(config_path)
    handlers = make_handlers(config_path, snapshots_dir)

    mcp = FastMCP("docstracker")

    @mcp.tool()
    def list_targets() -> list[str]:
        """List all configured Watch Target names."""
        return handlers["list_targets"]()

    @mcp.tool()
    def list_pages(target: str, hierarchical: bool = False) -> "list[str] | dict":
        """List tracked page URLs for a Watch Target.

        When hierarchical=False (default) returns a flat list of URLs.
        When hierarchical=True returns a dict with two keys:
          - sections: tracked pages nested according to the Navigation Snapshot tree
          - ungrouped: tracked pages not present in the Navigation Snapshot
        If no Navigation Snapshot has been captured yet, sections is empty and all
        pages appear in ungrouped.
        """
        return handlers["list_pages"](target, hierarchical=hierarchical)

    @mcp.tool()
    def read_page(url: str) -> str:
        """Return the current Snapshot content (Markdown) for a tracked page URL."""
        return handlers["read_page"](url)

    @mcp.tool()
    def read_overview(target: str) -> str:
        """Return the Target Overview Markdown for a Watch Target, or a message if not generated."""
        return handlers["read_overview"](target)

    @mcp.tool()
    def read_navigation(target: str) -> dict | str:
        """Return the Navigation Snapshot (TOC tree) for a Watch Target, or a message if not yet captured."""
        return handlers["read_navigation"](target)

    return mcp


def main():
    import sys
    config_path = os.environ.get("DOCSTRACKER_CONFIG", "config.yaml")
    mcp = _make_server(config_path)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
