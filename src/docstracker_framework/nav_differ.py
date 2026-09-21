from docstracker_framework.models import NavigationSnapshot, NavNode, NavNodeAdded, NavNodeRemoved, NavNodeRenamed


def _flatten(nodes: list[NavNode], parent_title: str | None = None) -> dict:
    result = {}
    for node in nodes:
        key = node.url if node.url else node.title
        result[key] = (node.title, node.url, parent_title)
        result.update(_flatten(node.children, parent_title=node.title))
    return result


class NavDiffer:
    def diff(self, previous: NavigationSnapshot, current: NavigationSnapshot) -> list:
        prev_map = _flatten(previous.nodes)
        curr_map = _flatten(current.nodes)
        changes = []

        for key, (title, url, parent) in curr_map.items():
            if key not in prev_map:
                changes.append(NavNodeAdded(title=title, url=url, parent_title=parent))
            else:
                prev_title, _, _ = prev_map[key]
                if prev_title != title:
                    changes.append(NavNodeRenamed(old_title=prev_title, new_title=title, url=url, parent_title=parent))

        for key, (title, url, parent) in prev_map.items():
            if key not in curr_map:
                changes.append(NavNodeRemoved(title=title, url=url, parent_title=parent))

        return changes
