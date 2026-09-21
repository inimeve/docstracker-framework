import datetime
import json
import os

from docstracker_framework.models import NewPage, ModifiedPage, Page, Section, PageAnalysis, SectionDiff, NavNodeAdded, NavNodeRemoved, NavNodeRenamed


def _nav_change_to_dict(c) -> dict:
    if isinstance(c, NavNodeAdded):
        return {"type": "added", "title": c.title, "url": c.url, "parent_title": c.parent_title}
    if isinstance(c, NavNodeRemoved):
        return {"type": "removed", "title": c.title, "url": c.url, "parent_title": c.parent_title}
    if isinstance(c, NavNodeRenamed):
        return {"type": "renamed", "old_title": c.old_title, "new_title": c.new_title, "url": c.url, "parent_title": c.parent_title}
    raise TypeError(f"Unknown nav change type: {type(c).__name__}")


class RunAnalysisStore:
    def __init__(self, run_analyses_dir: str):
        self._dir = run_analyses_dir

    def write(
        self,
        changes_by_target: dict,
        analyses_by_target: dict[str, list[PageAnalysis]] | None = None,
        run_digest: list[dict] | None = None,
        nav_changes_by_target: dict | None = None,
        nav_analyses_by_target: dict[str, PageAnalysis] | None = None,
        date: str | None = None,
    ) -> None:
        if not changes_by_target:
            return
        if date is None:
            date = str(datetime.date.today())

        analyses_by_target = analyses_by_target or {}
        nav_changes_by_target = nav_changes_by_target or {}
        nav_analyses_by_target = nav_analyses_by_target or {}
        targets = []

        for target_name, changes in changes_by_target.items():
            analyses_index = {a.page_url: a for a in analyses_by_target.get(target_name, [])}
            pages = []
            for change in changes:
                if isinstance(change, NewPage):
                    entry: dict = {
                        "type": "new",
                        "url": change.page.url,
                        "sections": [
                            {"heading": s.heading, "body": s.body}
                            for s in change.page.sections
                        ],
                    }
                elif isinstance(change, ModifiedPage):
                    entry = {
                        "type": "modified",
                        "url": change.page.url,
                        "diffs": [
                            {"heading": d.heading, "added": d.added, "removed": d.removed}
                            for d in change.diffs
                        ],
                    }
                else:
                    continue

                analysis = analyses_index.get(change.page.url)
                if analysis is not None:
                    entry["analysis"] = {
                        "relevance": analysis.relevance,
                        "category": analysis.category,
                        "summary": analysis.summary,
                        "topics_matched": analysis.topics_matched,
                    }
                pages.append(entry)

            target_record: dict = {"target_name": target_name, "pages": pages}
            nav_changes = nav_changes_by_target.get(target_name)
            if nav_changes:
                target_record["nav_changes"] = [_nav_change_to_dict(c) for c in nav_changes]
            nav_analysis = nav_analyses_by_target.get(target_name)
            if nav_analysis is not None:
                target_record["nav_analysis"] = {
                    "relevance": nav_analysis.relevance,
                    "category": nav_analysis.category,
                    "summary": nav_analysis.summary,
                    "topics_matched": nav_analysis.topics_matched,
                }
            targets.append(target_record)

        record: dict = {"date": date, "targets": targets}
        if run_digest:
            record["run_digest"] = run_digest

        os.makedirs(self._dir, exist_ok=True)
        path = os.path.join(self._dir, f"{date}.json")
        with open(path, "w") as f:
            json.dump(record, f, indent=2)

    def load_for_notification(self, date: str):
        record = self.read(date)
        if record is None:
            return None

        changes_by_target: dict = {}
        analyses_by_target: dict = {}

        for target in record.get("targets", []):
            target_name = target["target_name"]
            changes = []
            analyses = []
            for page_entry in target.get("pages", []):
                url = page_entry["url"]
                if page_entry["type"] == "modified":
                    page = Page(url=url, sections=[])
                    diffs = [
                        SectionDiff(heading=d["heading"], added=d["added"], removed=d["removed"])
                        for d in page_entry.get("diffs", [])
                    ]
                    changes.append(ModifiedPage(page=page, diffs=diffs))
                elif page_entry["type"] == "new":
                    sections = [Section(heading=s["heading"], body=s["body"]) for s in page_entry.get("sections", [])]
                    changes.append(NewPage(page=Page(url=url, sections=sections)))

                if "analysis" in page_entry:
                    a = page_entry["analysis"]
                    analyses.append(PageAnalysis(
                        page_url=url,
                        relevance=a["relevance"],
                        category=a["category"],
                        summary=a["summary"],
                        topics_matched=a.get("topics_matched", []),
                    ))

            if changes:
                changes_by_target[target_name] = changes
            if analyses:
                analyses_by_target[target_name] = analyses

        run_digest = record.get("run_digest")
        return changes_by_target, analyses_by_target or None, run_digest

    def read(self, date: str) -> dict | None:
        path = os.path.join(self._dir, f"{date}.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def write_record(self, date: str, record: dict) -> None:
        os.makedirs(self._dir, exist_ok=True)
        path = os.path.join(self._dir, f"{date}.json")
        with open(path, "w") as f:
            json.dump(record, f, indent=2)
