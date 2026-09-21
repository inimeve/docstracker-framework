import datetime
import json
import os

from docstracker_framework.models import PageAnalysis


class AnalysisStore:
    def __init__(self, analyses_dir: str, run_analyses_dir: str | None = None):
        self._analyses_dir = analyses_dir
        self._run_analyses_dir = run_analyses_dir

    def _read_since_dir(self, directory: str, since: datetime.date, normalize) -> list[dict]:
        if not os.path.isdir(directory):
            return []
        entries = []
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".json"):
                continue
            date_str = filename[:-5]
            try:
                file_date = datetime.date.fromisoformat(date_str)
            except ValueError:
                continue
            if file_date >= since:
                with open(os.path.join(directory, filename)) as f:
                    raw = json.load(f)
                entries.extend(normalize(raw))
        return entries

    @staticmethod
    def _normalize_legacy(raw) -> list[dict]:
        return raw if isinstance(raw, list) else raw.get("entries", [])

    @staticmethod
    def _normalize_run_analysis(raw) -> list[dict]:
        if not isinstance(raw, dict) or "targets" not in raw:
            return []
        entries = []
        for target in raw["targets"]:
            target_name = target["target_name"]
            for page in target.get("pages", []):
                analysis = page.get("analysis")
                if analysis is None:
                    continue
                entries.append({
                    "page_url": page["url"],
                    "target_name": target_name,
                    "relevance": analysis["relevance"],
                    "category": analysis["category"],
                    "summary": analysis["summary"],
                    "topics_matched": analysis.get("topics_matched", []),
                })
        return entries

    def read_since(self, since: datetime.date) -> list[dict]:
        entries = self._read_since_dir(self._analyses_dir, since, self._normalize_legacy)
        if self._run_analyses_dir:
            entries.extend(self._read_since_dir(self._run_analyses_dir, since, self._normalize_run_analysis))
        return entries

    def read_run(self, date: str) -> tuple[list[dict], list[dict] | None]:
        if self._run_analyses_dir:
            run_path = os.path.join(self._run_analyses_dir, f"{date}.json")
            if os.path.exists(run_path):
                with open(run_path) as f:
                    raw = json.load(f)
                return self._normalize_run_analysis(raw), raw.get("run_digest") or None

        path = os.path.join(self._analyses_dir, f"{date}.json")
        with open(path) as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return raw, None
        return raw.get("entries", []), raw.get("digest") or None

    def write_digest(self, date: str, digest: list[dict]) -> None:
        entries, _ = self.read_run(date)
        path = os.path.join(self._analyses_dir, f"{date}.json")
        with open(path, "w") as f:
            json.dump({"entries": entries, "digest": digest}, f, indent=2)

    def write(self, analyses_by_target: dict[str, list[PageAnalysis]], date: str | None = None, digest: list[dict] | None = None) -> None:
        if not analyses_by_target:
            return
        if date is None:
            date = str(datetime.date.today())
        entries = [
            {
                "page_url": analysis.page_url,
                "target_name": target_name,
                "relevance": analysis.relevance,
                "category": analysis.category,
                "summary": analysis.summary,
                "topics_matched": analysis.topics_matched,
            }
            for target_name, analyses in analyses_by_target.items()
            for analysis in analyses
        ]
        os.makedirs(self._analyses_dir, exist_ok=True)
        path = os.path.join(self._analyses_dir, f"{date}.json")
        with open(path, "w") as f:
            if digest is not None:
                json.dump({"entries": entries, "digest": digest}, f, indent=2)
            else:
                json.dump(entries, f, indent=2)
