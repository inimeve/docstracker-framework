import json
import os
import subprocess
import sys
import textwrap
import pytest

from docstracker_framework.cli import cmd_history


def write_config(path, targets):
    content = "email: user@gmail.com\ntargets:\n"
    for t in targets:
        content += f"  - name: {t['name']}\n    url: {t['url']}\n"
    with open(path, "w") as f:
        f.write(content)


def git(args, cwd):
    result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path):
    git(["init", "-b", "main"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)
    return tmp_path


def make_snapshot_file(snapshots_dir, target_slug, url, content, manifest_path=None):
    import hashlib, re
    target_dir = os.path.join(snapshots_dir, target_slug)
    os.makedirs(target_dir, exist_ok=True)
    filename = hashlib.sha1(url.encode()).hexdigest() + ".txt"
    filepath = os.path.join(target_dir, filename)
    with open(filepath, "w") as f:
        f.write(content)
    manifest = {}
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
    manifest[url] = filename
    mpath = manifest_path or os.path.join(target_dir, "manifest.json")
    with open(mpath, "w") as f:
        json.dump(manifest, f)
    return filepath, mpath


def test_history_exits_with_error_when_url_not_tracked(git_repo, capsys):
    config_path = str(git_repo / "config.yaml")
    snapshots_dir = str(git_repo / "snapshots")
    os.makedirs(snapshots_dir)
    write_config(config_path, [{"name": "Docs", "url": "https://example.com/docs/"}])

    target_dir = os.path.join(snapshots_dir, "docs")
    os.makedirs(target_dir)
    with open(os.path.join(target_dir, "manifest.json"), "w") as f:
        json.dump({}, f)

    class Args:
        config = config_path
        url = "https://example.com/docs/missing"

    with pytest.raises(SystemExit) as exc_info:
        cmd_history(Args())
    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "not tracked" in captured.err


def test_history_prints_timeline_for_tracked_url(git_repo, capsys):
    config_path = str(git_repo / "config.yaml")
    snapshots_dir = str(git_repo / "snapshots")
    url = "https://example.com/docs/guide"
    write_config(config_path, [{"name": "Docs", "url": "https://example.com/docs/"}])

    filepath, manifest_path = make_snapshot_file(
        snapshots_dir, "docs", url, "url: https://example.com/docs/guide\n\n## Guide\nOriginal.",
        manifest_path=os.path.join(snapshots_dir, "docs", "manifest.json"),
    )

    git(["add", "."], git_repo)
    git(["commit", "-m", "first snapshot"], git_repo)

    with open(filepath, "w") as f:
        f.write("url: https://example.com/docs/guide\n\n## Guide\nUpdated content.")
    git(["add", "."], git_repo)
    git(["commit", "-m", "update snapshot"], git_repo)

    _url = url

    class Args:
        config = config_path
        url = _url

    cmd_history(Args())

    output = capsys.readouterr().out
    lines = [l for l in output.strip().splitlines() if l.strip()]
    assert len(lines) == 2
    assert "new page" in lines[-1]
    assert "modified" in lines[0]


def test_history_shows_target_name_when_multiple_targets_match(git_repo, capsys):
    config_path = str(git_repo / "config.yaml")
    snapshots_dir = str(git_repo / "snapshots")
    url = "https://example.com/docs/shared"
    write_config(config_path, [
        {"name": "Target A", "url": "https://example.com/docs/"},
        {"name": "Target B", "url": "https://example.com/docs/"},
    ])

    make_snapshot_file(
        snapshots_dir, "target-a", url, "url: content\n\n## H\nBody.",
        manifest_path=os.path.join(snapshots_dir, "target-a", "manifest.json"),
    )
    make_snapshot_file(
        snapshots_dir, "target-b", url, "url: content\n\n## H\nBody.",
        manifest_path=os.path.join(snapshots_dir, "target-b", "manifest.json"),
    )
    git(["add", "."], git_repo)
    git(["commit", "-m", "initial"], git_repo)

    _url = url

    class Args:
        config = config_path
        url = _url

    cmd_history(Args())

    output = capsys.readouterr().out
    assert "Target A" in output
    assert "Target B" in output
