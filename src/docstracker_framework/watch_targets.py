from dataclasses import dataclass

from docstracker_framework.models import Config, WatchTarget


@dataclass
class UnknownWatchTarget(Exception):
    requested_name: str
    available_names: list[str]


@dataclass
class DuplicateWatchTargetName(Exception):
    name: str


def select_target(config: Config, name: str) -> Config:
    names = [t.name for t in config.targets]
    seen = set()
    for n in names:
        if n in seen:
            raise DuplicateWatchTargetName(name=n)
        seen.add(n)

    matched = [t for t in config.targets if t.name == name]
    if not matched:
        raise UnknownWatchTarget(requested_name=name, available_names=names)
    return Config(email=config.email, targets=matched)
