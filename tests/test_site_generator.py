"""Tests for build-site CLI command and site_generator module."""
import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import docstracker_framework.site_generator as site_generator


def _write_analyses(analyses_dir: Path, date: str, entries: list[dict]) -> None:
    analyses_dir.mkdir(parents=True, exist_ok=True)
    (analyses_dir / f"{date}.json").write_text(json.dumps(entries))


def _make_entry(
    page_url="https://example.com/docs/page",
    target_name="My Docs",
    relevance="high",
    category="new-feature",
    summary="Added new feature X.",
) -> dict:
    return {
        "page_url": page_url,
        "target_name": target_name,
        "relevance": relevance,
        "category": category,
        "summary": summary,
    }


# ── Cycle 1: CLI wiring ────────────────────────────────────────────────────────

def test_build_site_cli_calls_generate_site_with_correct_paths(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    called_with = {}

    def fake_generate(analyses_dir, config_path, output_path, snapshots_dir=None, run_analyses_dir=None):
        called_with["analyses_dir"] = analyses_dir
        called_with["config_path"] = config_path
        called_with["output_path"] = output_path
        called_with["snapshots_dir"] = snapshots_dir

    with patch("docstracker_framework.cli.generate_site", side_effect=fake_generate):
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "build-site"]
        main()

    assert called_with["analyses_dir"] == str(tmp_path / "analyses")
    assert called_with["config_path"] == str(config_path)
    assert called_with["output_path"] == str(tmp_path / "dist" / "index.html")


# ── Cycle 2: generate_site emits HTML with all analyses data ──────────────────

def test_generate_site_creates_index_html_with_all_analyses(tmp_path):
    analyses_dir = tmp_path / "analyses"
    _write_analyses(analyses_dir, "2026-05-08", [
        _make_entry(page_url="https://example.com/page-a", target_name="Docs A"),
    ])
    _write_analyses(analyses_dir, "2026-05-09", [
        _make_entry(page_url="https://example.com/page-b", target_name="Docs B"),
    ])
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "email: u@e.com\ntargets:\n"
        "  - name: Docs A\n    url: http://a.com/\n"
        "  - name: Docs B\n    url: http://b.com/\n"
    )

    with patch.object(site_generator, "_repo_from_git", return_value="owner/repo"), \
         patch.object(site_generator, "_commits_by_date", return_value={}):
        site_generator.generate_site(
            analyses_dir=str(analyses_dir),
            config_path=str(config_path),
            output_path=str(tmp_path / "site" / "index.html"),
        )

    html = (tmp_path / "site" / "index.html").read_text()
    assert "https://example.com/page-a" in html
    assert "https://example.com/page-b" in html
    assert "Docs A" in html
    assert "Docs B" in html
    assert '<link rel="icon" href="/favicon.svg" type="image/svg+xml">' in html
    assert '<script src="/favicon.js" defer></script>' in html


# ── Cycle 3: diff URL formula against known values ────────────────────────────

def test_diff_url_formula_matches_snapshot_store_naming(tmp_path):
    import hashlib
    page_url = "https://example.com/docs/page"
    target_slug = "my-docs"
    sha = "abc123"
    repo = "owner/repo"

    url_hash = hashlib.sha1(page_url.encode()).hexdigest()
    expected_filepath = f"snapshots/{target_slug}/{url_hash}.txt"
    expected_anchor = "diff-" + hashlib.sha256(expected_filepath.encode()).hexdigest()
    expected_diff_url = f"https://github.com/{repo}/commit/{sha}#{expected_anchor}"

    analyses_dir = tmp_path / "analyses"
    _write_analyses(analyses_dir, "2026-05-08", [_make_entry(page_url=page_url, target_name="My Docs")])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    data = site_generator._build_data(
        str(analyses_dir), str(config_path),
        commits={"2026-05-08": sha}, repo=repo,
    )

    change = data["runs"][0]["changes"][0]
    assert change["diffUrl"] == expected_diff_url


# ── Cycle 4: no commit SHA → row appears, no diff link ────────────────────────

def test_no_sha_for_date_produces_no_diff_url(tmp_path):
    analyses_dir = tmp_path / "analyses"
    _write_analyses(analyses_dir, "2026-05-08", [_make_entry()])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch.object(site_generator, "_repo_from_git", return_value="owner/repo"), \
         patch.object(site_generator, "_commits_by_date", return_value={}):
        site_generator.generate_site(
            analyses_dir=str(analyses_dir),
            config_path=str(config_path),
            output_path=str(tmp_path / "site" / "index.html"),
        )

    html = (tmp_path / "site" / "index.html").read_text()
    # Extract the embedded JSON payload and verify diffUrl is null (no commit SHA)
    import re
    m = re.search(r'<script id="docstracker-data"[^>]*>(.*?)</script>', html, re.DOTALL)
    payload = json.loads(m.group(1))
    change = payload["runs"][0]["changes"][0]
    assert change["page_url"] == "https://example.com/docs/page"
    assert change["diffUrl"] is None


# ── Cycle 5: self-contained — no external resource requests ───────────────────

def test_generated_html_has_no_external_resource_urls(tmp_path):
    analyses_dir = tmp_path / "analyses"
    _write_analyses(analyses_dir, "2026-05-08", [_make_entry()])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch.object(site_generator, "_repo_from_git", return_value="owner/repo"), \
         patch.object(site_generator, "_commits_by_date", return_value={"2026-05-08": "sha1234"}):
        site_generator.generate_site(
            analyses_dir=str(analyses_dir),
            config_path=str(config_path),
            output_path=str(tmp_path / "site" / "index.html"),
        )

    html = (tmp_path / "site" / "index.html").read_text()
    import re
    # Strip the embedded JSON data block to avoid false positives from page/diff URLs
    html_no_data = re.sub(
        r'<script id="docstracker-data"[^>]*>.*?</script>', "", html, flags=re.DOTALL
    )
    external_resource_patterns = [
        r'<link[^>]+href=["\']https?://',
        r'<script[^>]+src=["\']https?://',
        r'<img[^>]+src=["\']https?://',
        r'@import\s+["\']https?://',
        r'url\(\s*["\']?https?://',
    ]
    for pattern in external_resource_patterns:
        assert not re.search(pattern, html_no_data, re.IGNORECASE), \
            f"Found external resource matching: {pattern}"


# ── Cycle 6: runs ordered oldest-first in JSON payload ────────────────────────

def test_runs_are_ordered_oldest_first_in_payload(tmp_path):
    analyses_dir = tmp_path / "analyses"
    _write_analyses(analyses_dir, "2026-05-08", [_make_entry()])
    _write_analyses(analyses_dir, "2026-05-14", [_make_entry()])
    _write_analyses(analyses_dir, "2026-05-10", [_make_entry()])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    data = site_generator._build_data(
        str(analyses_dir), str(config_path), commits={}, repo="owner/repo"
    )

    dates = [r["date"] for r in data["runs"]]
    assert dates == sorted(dates)  # internal order is ascending; timeline buckets sort for display


# ── Cycle 7: digest field in run data ─────────────────────────────────────────

def _write_analyses_with_digest(analyses_dir: Path, date: str, entries: list[dict], digest: list[dict]) -> None:
    analyses_dir.mkdir(parents=True, exist_ok=True)
    (analyses_dir / f"{date}.json").write_text(json.dumps({"entries": entries, "digest": digest}))


def test_build_data_includes_digest_when_present_in_json(tmp_path):
    analyses_dir = tmp_path / "analyses"
    bullets = [{"rel": "high", "text": "Cambio crítico en RBAC."}]
    _write_analyses_with_digest(analyses_dir, "2026-05-15", [_make_entry()], bullets)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    data = site_generator._build_data(
        str(analyses_dir), str(config_path), commits={}, repo="owner/repo"
    )

    assert data["runs"][0]["digest"] == bullets


def test_build_data_digest_is_none_for_legacy_flat_list_json(tmp_path):
    analyses_dir = tmp_path / "analyses"
    _write_analyses(analyses_dir, "2026-05-15", [_make_entry()])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    data = site_generator._build_data(
        str(analyses_dir), str(config_path), commits={}, repo="owner/repo"
    )

    assert data["runs"][0]["digest"] is None


def test_generate_site_embeds_digest_bullets_in_json_data(tmp_path):
    analyses_dir = tmp_path / "analyses"
    bullets = [
        {"rel": "high", "text": "Cambio crítico en RBAC."},
        {"rel": "medium", "text": "Actualizar scripts de despliegue."},
    ]
    _write_analyses_with_digest(analyses_dir, "2026-05-15", [_make_entry()], bullets)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch.object(site_generator, "_repo_from_git", return_value="owner/repo"), \
         patch.object(site_generator, "_commits_by_date", return_value={}):
        site_generator.generate_site(
            analyses_dir=str(analyses_dir),
            config_path=str(config_path),
            output_path=str(tmp_path / "site" / "index.html"),
        )

    html = (tmp_path / "site" / "index.html").read_text()
    m = re.search(r'<script id="docstracker-data"[^>]*>(.*?)</script>', html, re.DOTALL)
    payload = json.loads(m.group(1))
    assert payload["runs"][0]["digest"] == bullets


def test_generate_site_embeds_null_digest_when_no_digest(tmp_path):
    analyses_dir = tmp_path / "analyses"
    _write_analyses(analyses_dir, "2026-05-15", [_make_entry(summary="Feature added.")])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch.object(site_generator, "_repo_from_git", return_value="owner/repo"), \
         patch.object(site_generator, "_commits_by_date", return_value={}):
        site_generator.generate_site(
            analyses_dir=str(analyses_dir),
            config_path=str(config_path),
            output_path=str(tmp_path / "site" / "index.html"),
        )

    html = (tmp_path / "site" / "index.html").read_text()
    m = re.search(r'<script id="docstracker-data"[^>]*>(.*?)</script>', html, re.DOTALL)
    payload = json.loads(m.group(1))
    assert payload["runs"][0]["digest"] is None


# ── Cycle 8: Run Analysis without analysis → changes appear with null fields ───

def _write_run_analysis(run_analyses_dir: Path, date: str, targets: list[dict], run_digest=None) -> None:
    run_analyses_dir.mkdir(parents=True, exist_ok=True)
    record: dict = {"date": date, "targets": targets}
    if run_digest:
        record["run_digest"] = run_digest
    (run_analyses_dir / f"{date}.json").write_text(json.dumps(record))


def test_build_data_includes_run_analysis_changes_without_page_analysis(tmp_path):
    run_analyses_dir = tmp_path / "run_analyses"
    _write_run_analysis(run_analyses_dir, "2026-05-20", [
        {"target_name": "My Docs", "pages": [
            {"type": "new", "url": "https://example.com/new-page"},
            {"type": "modified", "url": "https://example.com/mod-page", "diffs": []},
        ]}
    ])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    data = site_generator._build_data(
        str(tmp_path / "analyses"), str(config_path), commits={}, repo="owner/repo",
        run_analyses_dir=str(run_analyses_dir),
    )

    assert len(data["runs"]) == 1
    run = data["runs"][0]
    assert run["date"] == "2026-05-20"
    urls = {c["page_url"] for c in run["changes"]}
    assert "https://example.com/new-page" in urls
    assert "https://example.com/mod-page" in urls
    for change in run["changes"]:
        assert change["relevance"] is None
        assert change["category"] is None
        assert change["summary"] is None


# ── Cycle 9: Run Analysis with no changes → absent from runs ──────────────────

def test_build_data_excludes_run_analysis_with_no_changes(tmp_path):
    run_analyses_dir = tmp_path / "run_analyses"
    _write_run_analysis(run_analyses_dir, "2026-05-20", [
        {"target_name": "My Docs", "pages": []}
    ])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    data = site_generator._build_data(
        str(tmp_path / "analyses"), str(config_path), commits={}, repo="owner/repo",
        run_analyses_dir=str(run_analyses_dir),
    )

    assert data["runs"] == []


# ── Cycle 10: Run Analysis with analysis → fields populated ───────────────────

def test_build_data_populates_analysis_fields_when_present_in_run_analysis(tmp_path):
    run_analyses_dir = tmp_path / "run_analyses"
    _write_run_analysis(run_analyses_dir, "2026-05-20", [
        {"target_name": "My Docs", "pages": [
            {
                "type": "new", "url": "https://example.com/page",
                "analysis": {
                    "relevance": "high",
                    "category": "new-feature",
                    "summary": "A new API endpoint.",
                    "topics_matched": [],
                },
            }
        ]}
    ])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    data = site_generator._build_data(
        str(tmp_path / "analyses"), str(config_path), commits={}, repo="owner/repo",
        run_analyses_dir=str(run_analyses_dir),
    )

    change = data["runs"][0]["changes"][0]
    assert change["relevance"] == "high"
    assert change["category"] == "new-feature"
    assert change["summary"] == "A new API endpoint."


def test_build_data_prefers_run_analysis_over_legacy_analysis_for_same_date(tmp_path):
    analyses_dir = tmp_path / "analyses"
    _write_analyses(analyses_dir, "2026-05-20", [
        _make_entry(page_url="https://example.com/legacy-page")
    ])
    run_analyses_dir = tmp_path / "run_analyses"
    _write_run_analysis(run_analyses_dir, "2026-05-20", [
        {"target_name": "My Docs", "pages": [
            {"type": "modified", "url": "https://example.com/canonical-page", "diffs": []},
        ]}
    ])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    data = site_generator._build_data(
        str(analyses_dir), str(config_path), commits={}, repo="owner/repo",
        run_analyses_dir=str(run_analyses_dir),
    )

    assert len(data["runs"]) == 1
    assert data["runs"][0]["changes"][0]["page_url"] == "https://example.com/canonical-page"


# ── Cycle 11: generate_site HTML includes URLs from no-analysis Run Analysis ──

# ── Cycle: Timeline Window + Grouping Interval (#86) ─────────────────────────

def _run(ts: str, changes=None):
    """Test factory for a run dict shaped like _build_data output."""
    return {"timestamp": ts, "date": ts[:10], "changes": changes or [], "digest": None, "commitSha": None}


def test_bucket_runs_default_window_and_interval_orders_newest_first():
    runs = [
        _run("2026-05-22T09:00:00"),
        _run("2026-05-22T15:00:00"),
        _run("2026-05-21T10:00:00"),
        _run("2026-05-01T10:00:00"),
    ]
    buckets = site_generator._bucket_runs(runs, window_days=30, interval_hours=24)

    timestamps_per_bucket = [[r["timestamp"] for r in b["runs"]] for b in buckets]
    assert timestamps_per_bucket == [
        ["2026-05-22T15:00:00", "2026-05-22T09:00:00"],
        ["2026-05-21T10:00:00"],
        ["2026-05-01T10:00:00"],
    ]


def test_bucket_runs_window_7_excludes_runs_older_than_seven_days():
    runs = [
        _run("2026-05-22T10:00:00"),
        _run("2026-05-16T10:00:00"),  # 6 days before → inside
        _run("2026-05-15T09:00:00"),  # >7 days before → outside
        _run("2026-04-22T10:00:00"),  # way outside
    ]
    buckets = site_generator._bucket_runs(runs, window_days=7, interval_hours=24)
    included = {r["timestamp"] for b in buckets for r in b["runs"]}
    assert included == {"2026-05-22T10:00:00", "2026-05-16T10:00:00"}


def test_bucket_runs_interval_6h_splits_same_day_runs_into_separate_buckets():
    runs = [
        _run("2026-05-22T18:00:00"),  # anchor
        _run("2026-05-22T05:00:00"),  # 13h before anchor → different 6h bucket
    ]
    buckets = site_generator._bucket_runs(runs, window_days=7, interval_hours=6)
    assert len(buckets) == 2
    assert [len(b["runs"]) for b in buckets] == [1, 1]


def test_bucket_runs_interval_6h_colocates_runs_within_same_bucket():
    runs = [
        _run("2026-05-22T18:00:00"),  # anchor
        _run("2026-05-22T16:00:00"),  # 2h earlier → same 6h bucket
    ]
    buckets = site_generator._bucket_runs(runs, window_days=7, interval_hours=6)
    assert len(buckets) == 1
    assert {r["timestamp"] for r in buckets[0]["runs"]} == {
        "2026-05-22T18:00:00",
        "2026-05-22T16:00:00",
    }


def test_bucket_runs_changing_interval_keeps_same_set_of_runs():
    runs = [_run(f"2026-05-{d:02d}T{h:02d}:00:00") for d in (20, 21, 22) for h in (3, 9, 15, 21)]
    same_set = lambda buckets: sorted(r["timestamp"] for b in buckets for r in b["runs"])
    by_day  = same_set(site_generator._bucket_runs(runs, window_days=30, interval_hours=24))
    by_12h  = same_set(site_generator._bucket_runs(runs, window_days=30, interval_hours=12))
    by_6h   = same_set(site_generator._bucket_runs(runs, window_days=30, interval_hours=6))
    assert by_day == by_12h == by_6h


def test_build_data_adds_timestamp_defaulting_to_midnight_of_date(tmp_path):
    analyses_dir = tmp_path / "analyses"
    _write_analyses(analyses_dir, "2026-05-08", [_make_entry()])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    data = site_generator._build_data(
        str(analyses_dir), str(config_path), commits={}, repo="owner/repo"
    )

    assert data["runs"][0]["timestamp"] == "2026-05-08T00:00:00"


def test_generate_site_exposes_window_and_interval_defaults_and_controls(tmp_path):
    analyses_dir = tmp_path / "analyses"
    _write_analyses(analyses_dir, "2026-05-08", [_make_entry()])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch.object(site_generator, "_repo_from_git", return_value="owner/repo"), \
         patch.object(site_generator, "_commits_by_date", return_value={}):
        site_generator.generate_site(
            analyses_dir=str(analyses_dir),
            config_path=str(config_path),
            output_path=str(tmp_path / "dist" / "index.html"),
        )

    html = (tmp_path / "dist" / "index.html").read_text()
    m = re.search(r'<script id="docstracker-data"[^>]*>(.*?)</script>', html, re.DOTALL)
    payload = json.loads(m.group(1))
    assert payload["defaults"] == {"windowDays": 30, "intervalHours": 24}

    # Segmented controls present in the markup
    assert 'data-control="window"' in html
    assert 'data-control="interval"' in html
    for w in ("7", "30", "90"):
        assert f'data-window="{w}"' in html
    for i in ("24", "12", "6"):
        assert f'data-interval="{i}"' in html


def test_generate_site_includes_urls_from_run_analysis_without_page_analysis(tmp_path):
    run_analyses_dir = tmp_path / "run_analyses"
    _write_run_analysis(run_analyses_dir, "2026-05-20", [
        {"target_name": "My Docs", "pages": [
            {"type": "new", "url": "https://example.com/no-analysis-page"},
        ]}
    ])
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")

    with patch.object(site_generator, "_repo_from_git", return_value="owner/repo"), \
         patch.object(site_generator, "_commits_by_date", return_value={}):
        site_generator.generate_site(
            analyses_dir=str(tmp_path / "analyses"),
            config_path=str(config_path),
            output_path=str(tmp_path / "dist" / "index.html"),
            run_analyses_dir=str(run_analyses_dir),
        )

    html = (tmp_path / "dist" / "index.html").read_text()
    assert "https://example.com/no-analysis-page" in html
