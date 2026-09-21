import os
import re
import subprocess
from docstracker_framework.models import Config, ModifiedPage, WatchTarget
from docstracker_framework.snapshot_store import SnapshotStore, _deserialize
from docstracker_framework.differ import Differ


def _git_root() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _target_slug(target: WatchTarget) -> str:
    return re.sub(r"[^a-z0-9]+", "-", target.name.lower()).strip("-")


def find_last_snapshot_commit(snapshots_rel: str) -> str | None:
    result = subprocess.run(
        ["git", "log", "-1", "--pretty=format:%H", "--", snapshots_rel],
        capture_output=True, text=True,
    )
    sha = result.stdout.strip()
    return sha if sha else None


def replay_changes(
    config: Config,
    snapshots_dir: str,
    since: str | None = None,
) -> dict[str, list[ModifiedPage]]:
    git_root = _git_root()
    snapshots_rel = os.path.relpath(snapshots_dir, git_root)

    if since is not None:
        # User-provided base: diff from since to HEAD, read new content from filesystem.
        base = since
        end_ref = None
    else:
        # Auto-detect: find the last snapshot commit and diff it against its parent.
        last = find_last_snapshot_commit(snapshots_rel)
        if last is None:
            return {}
        base = f"{last}^"
        end_ref = last

    diff_target = end_ref if end_ref else "HEAD"
    differ = Differ()
    changes_by_target: dict[str, list[ModifiedPage]] = {}

    for target in config.targets:
        slug = _target_slug(target)
        target_rel = os.path.join(snapshots_rel, slug)

        diff_result = subprocess.run(
            ["git", "diff", "--name-only", base, diff_target, "--", f"{target_rel}/*.txt"],
            capture_output=True, text=True,
            cwd=git_root,
        )
        if diff_result.returncode != 0:
            continue

        changed_files = [
            f.strip() for f in diff_result.stdout.splitlines() if f.strip().endswith(".txt")
        ]
        if not changed_files:
            continue

        store = SnapshotStore.for_target(snapshots_dir, target)
        filename_to_url = {v: k for k, v in store._manifest.items()}

        changes = []
        for filepath in changed_files:
            filename = os.path.basename(filepath)
            url = filename_to_url.get(filename)
            if url is None:
                continue  # new page not yet in manifest - skip

            old_result = subprocess.run(
                ["git", "show", f"{base}:{filepath}"],
                capture_output=True, text=True,
                cwd=git_root,
            )
            if old_result.returncode != 0:
                continue  # file didn't exist at base commit - skip

            if end_ref is not None:
                new_result = subprocess.run(
                    ["git", "show", f"{end_ref}:{filepath}"],
                    capture_output=True, text=True,
                    cwd=git_root,
                )
                if new_result.returncode != 0:
                    continue
                new_text = new_result.stdout
            else:
                abs_path = os.path.join(git_root, filepath)
                if not os.path.exists(abs_path):
                    continue  # file deleted in current state - skip
                with open(abs_path) as f:
                    new_text = f.read()

            old_page = _deserialize(old_result.stdout, url)
            new_page = _deserialize(new_text, url)

            change = differ.diff(current=new_page, previous=old_page)
            if isinstance(change, ModifiedPage):
                changes.append(change)

        if changes:
            changes_by_target[target.name] = changes

    return changes_by_target
