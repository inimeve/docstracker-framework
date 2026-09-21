import json
import os
import re

from docstracker_framework.models import NavNode, NavigationSnapshot, WatchTarget


def _node_to_dict(node: NavNode) -> dict:
    return {
        "title": node.title,
        "url": node.url,
        "children": [_node_to_dict(c) for c in node.children],
    }


def _node_from_dict(d: dict) -> NavNode:
    return NavNode(
        title=d["title"],
        url=d.get("url"),
        children=[_node_from_dict(c) for c in d.get("children", [])],
    )


class NavigationSnapshotStore:
    @classmethod
    def for_target(cls, snapshots_dir: str, target: WatchTarget) -> "NavigationSnapshotStore":
        slug = re.sub(r"[^a-z0-9]+", "-", target.name.lower()).strip("-")
        return cls(base_dir=os.path.join(snapshots_dir, slug))

    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        self._path = os.path.join(base_dir, "navigation.json")

    def write(self, snapshot: NavigationSnapshot) -> None:
        os.makedirs(self._base_dir, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump([_node_to_dict(n) for n in snapshot.nodes], f, indent=2)

    def read(self) -> NavigationSnapshot | None:
        if not os.path.exists(self._path):
            return None
        with open(self._path) as f:
            data = json.load(f)
        return NavigationSnapshot(nodes=[_node_from_dict(d) for d in data])
