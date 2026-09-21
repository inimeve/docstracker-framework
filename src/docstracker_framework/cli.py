import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

from docstracker_framework.analysis_store import AnalysisStore
from docstracker_framework.run_analysis_store import RunAnalysisStore
from docstracker_framework.site_generator import generate_site
from docstracker_framework.analyzer import Analyzer
from docstracker_framework.config_loader import load_config
from docstracker_framework.models import ModifiedPage, NewPage, PageAnalysis, SectionDiff
from docstracker_framework.notifier import EmailNotifier
from docstracker_framework.orchestrator import run
from docstracker_framework.replay import replay_changes
from docstracker_framework.snapshot_store import SnapshotStore
from docstracker_framework.synthesizer import Synthesizer
from docstracker_framework.watch_targets import select_target, UnknownWatchTarget, DuplicateWatchTargetName

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_OVERVIEW_CORPUS_MAX_CHARS = 120_000


def _make_progress_printer():
    state = {"tick": 0, "last_target": None, "last_len": 0}
    is_tty = sys.stdout.isatty()

    def on_progress(event):
        target = event["target_name"]
        url = event["url"]
        crawled = event.get("crawled")
        queued = event.get("queued")
        if state["last_target"] != target:
            if state["last_target"] is not None:
                print()
            state["last_target"] = target

        spin = _SPINNER[state["tick"] % len(_SPINNER)]
        state["tick"] += 1
        counts = f"[{crawled} crawled · {queued} queued]" if crawled is not None else ""
        line = f"{spin} [{target}]  {counts}  {url}" if counts else f"{spin} [{target}] {url}"

        if is_tty:
            cols = shutil.get_terminal_size((80, 20)).columns
            if len(line) > cols - 1:
                line = line[:cols - 4] + "..."
            state["last_len"] = len(line)
            print(f"\r{line:<{cols - 1}}", end="", flush=True)
        else:
            print(line, flush=True)

    def finish():
        if state["last_target"] is not None and is_tty:
            print()

    return on_progress, finish


def _snapshots_dir(config_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "snapshots")


def _analyses_dir(config_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "analyses")


def _run_analyses_dir(config_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "run_analyses")


def _run_digest_payload(analyses_by_target: dict[str, list]) -> list[dict]:
    relevance_order = {"high": 0, "medium": 1, "low": 2}
    all_analyses = [
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
    return sorted(all_analyses, key=lambda a: relevance_order.get(a["relevance"], 3))


def cmd_run(args):
    config = load_config(args.config)

    if args.target:
        try:
            config = select_target(config, args.target)
        except UnknownWatchTarget as e:
            print(f"Error: target '{e.requested_name}' not found. Available: {e.available_names}", file=sys.stderr)
            sys.exit(1)
        except DuplicateWatchTargetName as e:
            print(f"Error: duplicate Watch Target name '{e.name}' in config.", file=sys.stderr)
            sys.exit(1)

    if args.verbose:
        on_progress, finish_progress = _make_progress_printer()
    else:
        on_progress, finish_progress = None, lambda: None

    synthesizer_cfg = config.synthesizer
    synthesizer = Synthesizer(synthesizer_cfg) if synthesizer_cfg else None

    t0 = time.monotonic()
    result = run(
        config,
        snapshots_dir=_snapshots_dir(args.config),
        on_progress=on_progress,
        synthesizer=synthesizer,
        analysis_store=AnalysisStore(_analyses_dir(args.config)),
        run_analysis_store=RunAnalysisStore(_run_analyses_dir(args.config)),
    )
    finish_progress()
    elapsed = time.monotonic() - t0

    changes_by_target = result.changes_by_target
    nav_changes_by_target = result.nav_changes_by_target
    total_pages = result.total_pages
    crawl_failures = result.crawl_failures
    all_changes = [c for changes in changes_by_target.values() for c in changes]
    all_nav_changes = [c for changes in nav_changes_by_target.values() for c in changes]
    if total_pages == 0 and crawl_failures:
        change_summary = f"{len(crawl_failures)} crawl failure(s)"
    elif all_changes or all_nav_changes:
        parts = []
        if all_changes:
            parts.append(f"{len(all_changes)} page change(s)")
        if all_nav_changes:
            parts.append(f"{len(all_nav_changes)} navigation change(s)")
        change_summary = " · ".join(parts) + " detected"
    else:
        change_summary = "no changes detected"
    print(f"Checked {total_pages} page(s) in {elapsed:.1f}s — {change_summary}.")

    if crawl_failures:
        print(f"Warning: {len(crawl_failures)} crawl failure(s):", file=sys.stderr)
        for failure in crawl_failures[:5]:
            print(f"- {failure['url']}: {failure['reason']}", file=sys.stderr)
        if len(crawl_failures) > 5:
            print(f"- ... {len(crawl_failures) - 5} more", file=sys.stderr)

    if not all_changes and not all_nav_changes:
        return

    for target_name, changes in changes_by_target.items():
        print(f"{target_name}: {len(changes)} change(s)")

    if getattr(args, "summary_file", None):
        summary = [
            {
                "name": target_name,
                "new": sum(1 for c in changes if isinstance(c, NewPage)),
                "modified": sum(1 for c in changes if isinstance(c, ModifiedPage)),
            }
            for target_name, changes in changes_by_target.items()
        ]
        with open(args.summary_file, "w") as f:
            json.dump(summary, f)

    if args.notify:
        analyses_by_target = result.analyses_by_target or None
        digest = result.run_digest or None
        print(f"Sending email to {config.email} ...")
        EmailNotifier().send(
            changes_by_target,
            recipient=config.email,
            analyses=analyses_by_target,
            digest=digest,
        )
        print("Email sent.")


def _synthesize_digest_for_notification(config, analyses_by_target):
    if not analyses_by_target:
        return None
    if config.synthesizer is None:
        return None
    try:
        return Synthesizer(config.synthesizer).synthesize_run_digest(
            _run_digest_payload(analyses_by_target)
        )
    except Exception as exc:
        print(f"  warning: digest synthesis failed; email will omit summary: {exc}", file=sys.stderr)
        return None


def _build_url_tree(urls: list[str]) -> dict:
    tree = {}
    for url in urls:
        parsed = urlparse(url)
        parts = [parsed.netloc] + [p for p in parsed.path.split("/") if p]
        node = tree
        for part in parts:
            node = node.setdefault(part, {})
    return tree


def _print_tree(node: dict, prefix: str = ""):
    items = list(node.items())
    for i, (key, subtree) in enumerate(items):
        last = i == len(items) - 1
        connector = "└── " if last else "├── "
        print(f"{prefix}{connector}{key}")
        extension = "    " if last else "│   "
        _print_tree(subtree, prefix + extension)


def cmd_list(args):
    config = load_config(args.config)
    snapshots = _snapshots_dir(args.config)

    for target in config.targets:
        store = SnapshotStore.for_target(snapshots, target)
        urls = store.tracked_page_urls()

        if not urls:
            print(f"{target.name}: no snapshots yet\n")
            continue

        if args.flat:
            print(f"# {target.name} ({len(urls)} pages)")
            for url in sorted(urls):
                print(url)
        else:
            print(f"{target.name} ({len(urls)} pages)")
            _print_tree(_build_url_tree(urls))

        print()


def cmd_analyze(args):
    config = load_config(args.config)

    if config.analyzer is None:
        print("Error: no analyzer configured in config.yaml", file=sys.stderr)
        sys.exit(1)

    changes_by_target = replay_changes(
        config,
        snapshots_dir=_snapshots_dir(args.config),
        since=args.since or None,
    )

    if not changes_by_target:
        print("No changes found to analyze.")
        return

    analyzer = Analyzer(config.analyzer)
    analyses_by_target: dict[str, list] = {}

    for target_name, changes in changes_by_target.items():
        analyses = []
        for change in changes:
            if not isinstance(change, ModifiedPage):
                continue
            try:
                analysis = analyzer.analyze_page(change.page.url, change.diffs)
                analyses.append(analysis)
                print(f"[{target_name}] {change.page.url}")
                print(f"  relevance: {analysis.relevance}  category: {analysis.category}")
                print(f"  {analysis.summary}")
            except Exception as exc:
                print(f"  warning: analysis failed for {change.page.url}: {exc}", file=sys.stderr)
        if analyses:
            analyses_by_target[target_name] = analyses

    if not analyses_by_target:
        print("No analyses produced.")
        return

    digest = None
    if args.save:
        if config.synthesizer is None:
            print("Error: no synthesizer configured in config.yaml", file=sys.stderr)
            sys.exit(1)
        try:
            digest = Synthesizer(config.synthesizer).synthesize_run_digest(
                _run_digest_payload(analyses_by_target)
            )
        except Exception as exc:
            print(f"Error: digest synthesis failed; analysis not saved: {exc}", file=sys.stderr)
            sys.exit(1)
        AnalysisStore(_analyses_dir(args.config)).write(analyses_by_target, digest=digest)
        print("Saved to analyses/.")

    if args.notify:
        if digest is None:
            digest = _synthesize_digest_for_notification(config, analyses_by_target)
        print(f"Sending email to {config.email} ...")
        EmailNotifier().send(
            changes_by_target,
            recipient=config.email,
            analyses=analyses_by_target,
            digest=digest,
        )
        print("Email sent.")


def cmd_history(args):
    config = load_config(args.config)
    snapshots = _snapshots_dir(args.config)
    url = args.url

    matches: list[tuple[str, str]] = []
    for target in config.targets:
        store = SnapshotStore.for_target(snapshots, target)
        filename = store._manifest.get(url)
        if filename:
            filepath = os.path.join(store._base_dir, filename)
            matches.append((target.name, filepath))

    if not matches:
        print(f"Error: '{url}' is not tracked in any Watch Target.", file=sys.stderr)
        sys.exit(1)

    config_dir = os.path.dirname(os.path.abspath(args.config))
    git_root_result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
        cwd=config_dir,
    )
    git_root = git_root_result.stdout.strip() if git_root_result.returncode == 0 else None

    for target_name, filepath in matches:
        if len(matches) > 1:
            print(f"\n{target_name}:")

        rel_path = os.path.relpath(filepath, git_root) if git_root else filepath
        log_result = subprocess.run(
            ["git", "log", "--pretty=format:%ad %h", "--date=short", "--", rel_path],
            capture_output=True, text=True,
            cwd=git_root or config_dir,
        )
        lines = [l for l in log_result.stdout.splitlines() if l.strip()]
        if not lines:
            print("  (no git history found for this file)")
            continue

        for i, line in enumerate(lines):
            date, sha = line.rsplit(" ", 1)
            kind = "new page" if i == len(lines) - 1 else "modified"
            print(f"{date}  {sha}  {kind}")


def cmd_digest(args):
    config = load_config(args.config)

    if config.synthesizer is None:
        print("Error: no synthesizer configured in config.yaml", file=sys.stderr)
        sys.exit(1)

    since = (
        datetime.date.fromisoformat(args.since)
        if args.since
        else datetime.date.today() - datetime.timedelta(days=7)
    )

    store = AnalysisStore(_analyses_dir(args.config), run_analyses_dir=_run_analyses_dir(args.config))
    entries = store.read_since(since=since)

    if not entries:
        print("No analysis files found for the requested period.")
        return

    analyses_text = json.dumps(entries, indent=2)
    synthesizer = Synthesizer(config.synthesizer)
    print(f"Generating weekly digest from {len(entries)} analysis entries ...")
    digest_html = synthesizer.generate_digest(analyses_text)
    print(digest_html)

    if args.notify:
        print(f"Sending digest email to {config.email} ...")
        EmailNotifier().send_digest(digest_html, recipient=config.email)
        print("Email sent.")


def _build_export_markdown(targets, snapshots_dir: str) -> str:
    parts = []
    for target in targets:
        parts.append(f"# {target.name}\n")
        store = SnapshotStore.for_target(snapshots_dir, target)
        slug = re.sub(r"[^a-z0-9]+", "-", target.name.lower()).strip("-")
        overview_path = os.path.join(snapshots_dir, slug, "OVERVIEW.md")
        if os.path.exists(overview_path):
            with open(overview_path) as f:
                parts.append("\n" + f.read().rstrip() + "\n")
        for url in store.tracked_page_urls():
            parts.append(f"\n## {url}\n")
            page = store.read(url)
            if page:
                for section in page.sections:
                    parts.append(f"\n### {section.heading}\n")
                    if section.body:
                        parts.append(section.body + "\n")
        parts.append("\n")
    return "".join(parts)


def _append_limited(parts: list[str], text: str, remaining: int) -> int:
    if remaining <= 0:
        return 0
    parts.append(text[:remaining])
    return remaining - len(text[:remaining])


def _build_snapshot_corpus(store: SnapshotStore, max_chars: int | None = None) -> str:
    remaining = _OVERVIEW_CORPUS_MAX_CHARS if max_chars is None else max_chars
    parts = []
    for url in store.tracked_page_urls():
        if remaining <= 0:
            break
        page = store.read(url)
        if page:
            remaining = _append_limited(parts, f"## {url}\n", remaining)
            for section in page.sections:
                if remaining <= 0:
                    break
                remaining = _append_limited(parts, f"### {section.heading}\n", remaining)
                if section.body:
                    remaining = _append_limited(parts, section.body + "\n", remaining)
    if remaining <= 0:
        parts.append("\n\n[Corpus truncated for overview generation.]\n")
    return "\n".join(parts)


def cmd_overview(args):
    config = load_config(args.config)

    if config.synthesizer is None:
        print("Error: no synthesizer configured in config.yaml", file=sys.stderr)
        sys.exit(1)

    targets = config.targets
    if args.target:
        targets = [t for t in targets if t.name == args.target]
        if not targets:
            print(f"Error: target '{args.target}' not found.", file=sys.stderr)
            sys.exit(1)

    snapshots = _snapshots_dir(args.config)
    synthesizer = Synthesizer(config.synthesizer)

    for target in targets:
        store = SnapshotStore.for_target(snapshots, target)
        corpus = _build_snapshot_corpus(store)
        print(f"Generating overview for '{target.name}' ...")
        try:
            overview = synthesizer.generate_overview(target.name, corpus)
        except Exception as exc:
            print(f"  Skipped: overview generation failed for '{target.name}': {exc}", file=sys.stderr)
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", target.name.lower()).strip("-")
        target_dir = os.path.join(snapshots, slug)
        os.makedirs(target_dir, exist_ok=True)
        with open(os.path.join(target_dir, "OVERVIEW.md"), "w") as f:
            f.write(overview)
        print(f"  Written: snapshots/{slug}/OVERVIEW.md")


def cmd_export(args):
    config = load_config(args.config)
    targets = config.targets

    if args.target:
        targets = [t for t in targets if t.name == args.target]
        if not targets:
            print(f"Error: target '{args.target}' not found.", file=sys.stderr)
            sys.exit(1)

    output = _build_export_markdown(targets, _snapshots_dir(args.config))

    if args.out:
        with open(args.out, "w") as f:
            f.write(output)
    else:
        print(output, end="")


def _site_source_dir(config_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "site")


def _dist_dir(config_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "dist")


def _site_output_path(config_path: str) -> str:
    return os.path.join(_dist_dir(config_path), "index.html")


def cmd_backfill_digests(args):
    config = load_config(args.config)

    if config.synthesizer is None:
        print("Error: no synthesizer configured in config.yaml", file=sys.stderr)
        sys.exit(1)
    synthesizer_config = config.synthesizer

    store = AnalysisStore(_analyses_dir(args.config), run_analyses_dir=_run_analyses_dir(args.config))
    analyses_dir = _analyses_dir(args.config)

    if not os.path.isdir(analyses_dir):
        print("No analyses directory found.")
        return

    if args.date:
        filenames = [f"{args.date}.json"]
    else:
        all_filenames = sorted(
            (f for f in os.listdir(analyses_dir) if f.endswith(".json")),
            reverse=True,
        )
        filenames = all_filenames[:args.limit] if args.limit else all_filenames

    synthesizer = Synthesizer(synthesizer_config)

    to_process = []
    for filename in filenames:
        date = filename[:-5]
        try:
            entries, digest = store.read_run(date)
        except FileNotFoundError:
            continue
        if digest is not None and not args.force:
            continue
        to_process.append((date, entries))

    if not to_process:
        print("Nothing to backfill.")
        return

    print(f"Backfilling {len(to_process)} run(s)...", flush=True)
    for i, (date, entries) in enumerate(to_process, 1):
        print(f"[{i}/{len(to_process)}] {date}: synthesizing digest for {len(entries)} entries ...", flush=True)
        new_digest = synthesizer.synthesize_run_digest(entries)
        store.write_digest(date, new_digest)
        print(f"[{i}/{len(to_process)}] {date}: done.", flush=True)

    print("Backfill complete.", flush=True)


def cmd_backfill_analyses(args):
    config = load_config(args.config)

    if config.analyzer is None:
        print("Error: no analyzer configured in config.yaml", file=sys.stderr)
        sys.exit(1)

    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    if not dates:
        print("Error: --dates must list at least one YYYY-MM-DD date", file=sys.stderr)
        sys.exit(1)

    targets_by_name = {t.name: t for t in config.targets}
    store = RunAnalysisStore(_run_analyses_dir(args.config))
    analyzer = Analyzer(config.analyzer)
    synthesizer = Synthesizer(config.synthesizer) if config.synthesizer else None

    for date in dates:
        record = store.read(date)
        if record is None:
            print(f"{date}: no run_analyses file found, skipping.")
            continue

        analyses_by_target: dict[str, list[PageAnalysis]] = {}
        backfilled_any = False

        for target in record.get("targets", []):
            target_name = target["target_name"]
            topics = targets_by_name[target_name].topics if target_name in targets_by_name else None
            analyses: list[PageAnalysis] = []

            for page in target.get("pages", []):
                if page.get("analysis"):
                    a = page["analysis"]
                    analyses.append(PageAnalysis(
                        page_url=page["url"], relevance=a["relevance"], category=a["category"],
                        summary=a["summary"], topics_matched=a.get("topics_matched", []),
                    ))
                    continue
                if page.get("type") != "modified":
                    continue

                diffs = [
                    SectionDiff(heading=d["heading"], added=d["added"], removed=d["removed"])
                    for d in page.get("diffs", [])
                ]
                try:
                    analysis = analyzer.analyze_page(page["url"], diffs, topics=topics or None)
                except Exception as exc:
                    print(f"  warning: analysis failed for {page['url']}: {exc}", file=sys.stderr)
                    continue

                page["analysis"] = {
                    "relevance": analysis.relevance,
                    "category": analysis.category,
                    "summary": analysis.summary,
                    "topics_matched": analysis.topics_matched,
                }
                analyses.append(analysis)
                backfilled_any = True
                print(f"[{date}] [{target_name}] {page['url']}: {analysis.relevance}/{analysis.category}")

            if analyses:
                analyses_by_target[target_name] = analyses

        if not backfilled_any:
            print(f"{date}: nothing to backfill.")
            continue

        if synthesizer and analyses_by_target:
            record["run_digest"] = synthesizer.synthesize_run_digest(_run_digest_payload(analyses_by_target))

        store.write_record(date, record)
        print(f"{date}: backfilled and saved.")


def cmd_resend(args):
    config = load_config(args.config)
    store = RunAnalysisStore(_run_analyses_dir(args.config))
    result = store.load_for_notification(args.date)
    if result is None:
        print(f"Error: no persisted run found for {args.date}", file=sys.stderr)
        sys.exit(1)
    changes_by_target, analyses_by_target, run_digest = result
    print(f"Sending email to {config.email} ...")
    EmailNotifier().send(
        changes_by_target,
        recipient=config.email,
        analyses=analyses_by_target,
        digest=run_digest,
    )
    print("Email sent.")


def cmd_build_site(args):
    source_dir = _site_source_dir(args.config)
    dist_dir = _dist_dir(args.config)

    if os.path.isdir(dist_dir):
        shutil.rmtree(dist_dir)
    if os.path.isdir(source_dir):
        shutil.copytree(source_dir, dist_dir)
    else:
        os.makedirs(dist_dir, exist_ok=True)

    output_path = _site_output_path(args.config)
    generate_site(
        analyses_dir=_analyses_dir(args.config),
        config_path=args.config,
        output_path=output_path,
        snapshots_dir=_snapshots_dir(args.config),
        run_analyses_dir=_run_analyses_dir(args.config),
    )
    print(f"Built {dist_dir} (generated {output_path})")


def _default_site_dir(config_path: str) -> str:
    return _dist_dir(config_path)


def _deploy_site_cloudflare(deploy_dir: str) -> subprocess.CompletedProcess[str]:
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    project_name = os.environ.get("CLOUDFLARE_PAGES_PROJECT_NAME")

    if not api_token:
        print("Error: CLOUDFLARE_API_TOKEN environment variable is required.", file=sys.stderr)
        sys.exit(1)
    if not account_id:
        print("Error: CLOUDFLARE_ACCOUNT_ID environment variable is required.", file=sys.stderr)
        sys.exit(1)
    if not project_name:
        print("Error: CLOUDFLARE_PAGES_PROJECT_NAME environment variable is required.", file=sys.stderr)
        sys.exit(1)

    return subprocess.run(
        ["npx", "-y", "wrangler", "pages", "deploy", deploy_dir, "--project-name", project_name],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "CLOUDFLARE_API_TOKEN": api_token,
            "CLOUDFLARE_ACCOUNT_ID": account_id,
        },
    )


def cmd_deploy_site(args):
    deploy_dir = args.dir or _default_site_dir(args.config)
    result = _deploy_site_cloudflare(deploy_dir)

    if result.returncode != 0:
        print(f"Error: Cloudflare Pages deploy failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(result.returncode)
    print(result.stdout)


def main():
    parser = argparse.ArgumentParser(prog="docstracker")
    parser.add_argument("--config", default="config.yaml", metavar="PATH",
                        help="Path to config.yaml (default: ./config.yaml)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Crawl targets and detect changes")
    run_parser.add_argument("--notify", action="store_true",
                            help="Send email notification if changes are found")
    run_parser.add_argument("--target", metavar="NAME",
                            help="Run only this Watch Target")
    run_parser.add_argument("--verbose", "-v", action="store_true",
                            help="Show crawl progress in real time")
    run_parser.add_argument("--summary-file", metavar="PATH",
                            help="Write per-target change counts as JSON to this file")
    run_parser.set_defaults(func=cmd_run)

    list_parser = subparsers.add_parser("list", help="List tracked pages")
    list_parser.add_argument("--flat", action="store_true",
                             help="Print a flat list of URLs instead of a tree")
    list_parser.set_defaults(func=cmd_list)

    analyze_parser = subparsers.add_parser(
        "analyze", help="Re-run analysis on the last batch of snapshot changes"
    )
    analyze_parser.add_argument("--since", metavar="COMMIT",
                                help="Base commit for diff (default: last commit touching snapshots/)")
    analyze_parser.add_argument("--save", action="store_true",
                                help="Write results to analyses/YYYY-MM-DD.json")
    analyze_parser.add_argument("--notify", action="store_true",
                                help="Send Change Report email with analysis results")
    analyze_parser.set_defaults(func=cmd_analyze)

    history_parser = subparsers.add_parser("history", help="Show git history for a tracked page URL")
    history_parser.add_argument("url", help="URL of the tracked page")
    history_parser.set_defaults(func=cmd_history)

    export_parser = subparsers.add_parser("export", help="Dump snapshots to Markdown")
    export_parser.add_argument("--target", metavar="NAME",
                               help="Export only this Watch Target")
    export_parser.add_argument("--out", metavar="FILE",
                               help="Write output to this file instead of stdout")
    export_parser.set_defaults(func=cmd_export)

    overview_parser = subparsers.add_parser("overview", help="Generate Target Overview Markdown for Watch Targets")
    overview_parser.add_argument("--target", metavar="NAME",
                                 help="Generate overview only for this Watch Target")
    overview_parser.set_defaults(func=cmd_overview)

    digest_parser = subparsers.add_parser("digest", help="Generate and send a Weekly Digest email")
    digest_parser.add_argument("--notify", action="store_true",
                               help="Send the digest as an HTML email")
    digest_parser.add_argument("--since", metavar="YYYY-MM-DD",
                               help="Include analyses since this date (default: 7 days ago)")
    digest_parser.set_defaults(func=cmd_digest)

    backfill_parser = subparsers.add_parser(
        "backfill-digests", help="Generate AI digests for historical analysis runs that lack one"
    )
    backfill_parser.add_argument("--date", metavar="YYYY-MM-DD",
                                 help="Target a single run by date")
    backfill_parser.add_argument("--force", action="store_true",
                                 help="Overwrite existing digests")
    backfill_parser.add_argument("--limit", metavar="N", type=int, default=10,
                                 help="Max number of recent runs to backfill (default: 10; 0 = no limit)")
    backfill_parser.set_defaults(func=cmd_backfill_digests)

    backfill_analyses_parser = subparsers.add_parser(
        "backfill-analyses", help="Re-run the analyzer on historical run_analyses pages that lack an analysis"
    )
    backfill_analyses_parser.add_argument("--dates", required=True, metavar="YYYY-MM-DD[,YYYY-MM-DD...]",
                                          help="Comma-separated list of run_analyses dates to backfill")
    backfill_analyses_parser.set_defaults(func=cmd_backfill_analyses)

    build_site_parser = subparsers.add_parser("build-site", help="Generate static dashboard dist/index.html")
    build_site_parser.set_defaults(func=cmd_build_site)

    resend_parser = subparsers.add_parser("resend", help="Resend Change Report email for a persisted run")
    resend_parser.add_argument("date", help="Date of the run to resend (YYYY-MM-DD)")
    resend_parser.set_defaults(func=cmd_resend)

    deploy_site_parser = subparsers.add_parser("deploy-site", help="Deploy dist/ to Cloudflare Pages")
    deploy_site_parser.add_argument("--dir", default=None, metavar="DIR",
                                     help="Directory to deploy (default: dist/ next to config.yaml)")
    deploy_site_parser.add_argument("--provider", choices=["cloudflare"], default=None,
                                    help="Deployment provider; only cloudflare is supported")
    deploy_site_parser.set_defaults(func=cmd_deploy_site)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
