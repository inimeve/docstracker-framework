import hashlib
import json
import os
import re
from docstracker_framework.models import Page, Section, WatchTarget

_SECTION_SEP = "\n\n## "
_MANIFEST = "manifest.json"


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def _serialize(page: Page) -> str:
    parts = [f"url: {page.url}"]
    for section in page.sections:
        chunk = f"## {section.heading}"
        if section.body:
            chunk += f"\n{section.body}"
        parts.append(chunk)
    return "\n\n".join(parts)


def _deserialize(text: str, url: str) -> Page:
    lines = text.splitlines()
    sections = []
    current_heading: str | None = None
    current_body_lines: list[str] = []
    in_code_fence = False

    for line in lines[1:]:  # skip url: line
        if line.startswith("```") or line.startswith("~~~"):
            in_code_fence = not in_code_fence
        if not in_code_fence and line.startswith("## "):
            if current_heading is not None:
                sections.append(Section(heading=current_heading, body="\n".join(current_body_lines).strip()))
            current_heading = line[3:]
            current_body_lines = []
        elif current_heading is not None:
            current_body_lines.append(line)

    if current_heading is not None:
        sections.append(Section(heading=current_heading, body="\n".join(current_body_lines).strip()))

    return Page(url=url, sections=sections)


class SnapshotStore:
    @classmethod
    def for_target(cls, snapshots_dir: str, target: WatchTarget) -> "SnapshotStore":
        slug = re.sub(r"[^a-z0-9]+", "-", target.name.lower()).strip("-")
        return cls(base_dir=os.path.join(snapshots_dir, slug))

    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        self._manifest_path = os.path.join(base_dir, _MANIFEST)
        if os.path.exists(self._manifest_path):
            with open(self._manifest_path) as f:
                self._manifest: dict[str, str] = json.load(f)
        else:
            self._manifest = {}

    def write(self, page: Page) -> None:
        os.makedirs(self._base_dir, exist_ok=True)
        filename = _url_hash(page.url) + ".txt"
        filepath = os.path.join(self._base_dir, filename)
        with open(filepath, "w") as f:
            f.write(_serialize(page))
        self._manifest[page.url] = filename
        with open(self._manifest_path, "w") as f:
            json.dump(self._manifest, f)

    def read(self, url: str) -> Page | None:
        filename = self._manifest.get(url)
        if filename is None:
            return None
        filepath = os.path.join(self._base_dir, filename)
        if not os.path.exists(filepath):
            return None
        with open(filepath) as f:
            return _deserialize(f.read(), url)

    def tracked_page_urls(self) -> list[str]:
        return list(self._manifest.keys())
