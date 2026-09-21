import pytest
from docstracker_framework.models import Config, WatchTarget
from docstracker_framework.watch_targets import select_target, UnknownWatchTarget, DuplicateWatchTargetName


def make_config(names=("Docs A", "Docs B"), email="user@example.com"):
    targets = [WatchTarget(name=n, url=f"http://{n.lower().replace(' ', '')}.com/") for n in names]
    return Config(email=email, targets=targets)


# ── select_target ─────────────────────────────────────────────────────────────

def test_select_returns_config_with_only_matching_target():
    config = make_config()
    result = select_target(config, "Docs A")
    assert [t.name for t in result.targets] == ["Docs A"]


def test_select_does_not_mutate_original_config():
    config = make_config()
    select_target(config, "Docs A")
    assert [t.name for t in config.targets] == ["Docs A", "Docs B"]


def test_select_preserves_email():
    config = make_config(email="owner@example.com")
    result = select_target(config, "Docs A")
    assert result.email == "owner@example.com"


def test_select_unknown_name_raises_unknown_watch_target():
    config = make_config()
    with pytest.raises(UnknownWatchTarget) as exc_info:
        select_target(config, "Nope")
    assert exc_info.value.requested_name == "Nope"


def test_select_unknown_name_includes_available_names_in_config_order():
    config = make_config(names=("Beta", "Alpha"))
    with pytest.raises(UnknownWatchTarget) as exc_info:
        select_target(config, "Nope")
    assert exc_info.value.available_names == ["Beta", "Alpha"]


# ── DuplicateWatchTargetName ──────────────────────────────────────────────────

def test_duplicate_names_raises_duplicate_watch_target_name():
    config = make_config(names=("Docs A", "Docs A"))
    with pytest.raises(DuplicateWatchTargetName) as exc_info:
        select_target(config, "Docs A")
    assert exc_info.value.name == "Docs A"
