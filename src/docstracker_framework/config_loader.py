import os
import yaml
from docstracker_framework.models import AnalyzerConfig, Config, WatchTarget
from docstracker_framework.watch_targets import DuplicateWatchTargetName


def load_config(path: str) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    targets = [
        WatchTarget(
            name=t["name"],
            url=t["url"],
            max_pages=t.get("max_pages", 500),
            topics=t.get("topics", []),
        )
        for t in data["targets"]
    ]
    seen: set[str] = set()
    for t in targets:
        if t.name in seen:
            raise DuplicateWatchTargetName(name=t.name)
        seen.add(t.name)
    analyzer = None
    if raw := data.get("analyzer"):
        analyzer = AnalyzerConfig(
            endpoint=raw["endpoint"],
            model=raw["model"],
            api_key=os.environ.get("OPENCODE_API_KEY", ""),
        )
    synthesizer = None
    if raw := data.get("synthesizer"):
        synthesizer = AnalyzerConfig(
            endpoint=raw["endpoint"],
            model=raw["model"],
            api_key=os.environ.get("OPENCODE_API_KEY", ""),
        )
    return Config(email=data["email"], targets=targets, analyzer=analyzer, synthesizer=synthesizer)
