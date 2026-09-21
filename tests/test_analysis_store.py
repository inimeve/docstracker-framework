import json
import os
import pytest
from docstracker_framework.models import PageAnalysis
from docstracker_framework.analysis_store import AnalysisStore


def make_analysis(page_url, relevance="high", category="breaking-change", summary="Something changed."):
    return PageAnalysis(page_url=page_url, relevance=relevance, category=category, summary=summary)


def test_write_creates_json_file_with_entries_from_all_targets(tmp_path):
    store = AnalysisStore(str(tmp_path))
    analyses_by_target = {
        "service-a": [make_analysis("https://docs.example.com/a", relevance="high", category="breaking-change", summary="Auth changed.")],
        "service-b": [make_analysis("https://docs.example.com/b", relevance="low", category="cosmetic", summary="Wording updated.")],
    }

    store.write(analyses_by_target, date="2025-01-15")

    path = os.path.join(str(tmp_path), "2025-01-15.json")
    assert os.path.exists(path)
    entries = json.loads(open(path).read())
    assert len(entries) == 2
    assert {"page_url": "https://docs.example.com/a", "target_name": "service-a", "relevance": "high", "category": "breaking-change", "summary": "Auth changed.", "topics_matched": []} in entries
    assert {"page_url": "https://docs.example.com/b", "target_name": "service-b", "relevance": "low", "category": "cosmetic", "summary": "Wording updated.", "topics_matched": []} in entries


def test_write_noop_when_analyses_empty(tmp_path):
    store = AnalysisStore(str(tmp_path))
    store.write({}, date="2025-01-15")
    assert not os.path.exists(os.path.join(str(tmp_path), "2025-01-15.json"))


def test_write_overwrites_existing_file_for_same_date(tmp_path):
    store = AnalysisStore(str(tmp_path))
    first = {"service-a": [make_analysis("https://docs.example.com/a", summary="First run.")]}
    second = {"service-a": [make_analysis("https://docs.example.com/a", summary="Second run.")]}

    store.write(first, date="2025-01-15")
    store.write(second, date="2025-01-15")

    entries = json.loads(open(os.path.join(str(tmp_path), "2025-01-15.json")).read())
    assert len(entries) == 1
    assert entries[0]["summary"] == "Second run."


def test_write_persists_topics_matched(tmp_path):
    store = AnalysisStore(str(tmp_path))
    analysis = PageAnalysis(
        page_url="https://docs.example.com/net",
        relevance="high",
        category="new-feature",
        summary="VNet peering added.",
        topics_matched=["networking"],
    )
    store.write({"service-a": [analysis]}, date="2025-01-16")

    entries = json.loads(open(os.path.join(str(tmp_path), "2025-01-16.json")).read())
    assert entries[0]["topics_matched"] == ["networking"]


def test_write_persists_empty_topics_matched(tmp_path):
    store = AnalysisStore(str(tmp_path))
    analysis = PageAnalysis(
        page_url="https://docs.example.com/p",
        relevance="low",
        category="cosmetic",
        summary="Minor change.",
    )
    store.write({"service-a": [analysis]}, date="2025-01-17")

    entries = json.loads(open(os.path.join(str(tmp_path), "2025-01-17.json")).read())
    assert entries[0]["topics_matched"] == []


def test_write_with_digest_produces_object_format(tmp_path):
    store = AnalysisStore(str(tmp_path))
    analysis = make_analysis("https://docs.example.com/a")
    bullets = [{"rel": "high", "text": "Cambio crítico."}]

    store.write({"service-a": [analysis]}, date="2025-01-18", digest=bullets)

    raw = json.loads(open(os.path.join(str(tmp_path), "2025-01-18.json")).read())
    assert isinstance(raw, dict)
    assert raw["digest"] == bullets
    assert len(raw["entries"]) == 1
    assert raw["entries"][0]["page_url"] == "https://docs.example.com/a"


def test_write_without_digest_produces_flat_list(tmp_path):
    store = AnalysisStore(str(tmp_path))
    analysis = make_analysis("https://docs.example.com/a")

    store.write({"service-a": [analysis]}, date="2025-01-19")

    raw = json.loads(open(os.path.join(str(tmp_path), "2025-01-19.json")).read())
    assert isinstance(raw, list)


def test_read_since_handles_new_object_format(tmp_path):
    path = os.path.join(str(tmp_path), "2025-01-20.json")
    data = {
        "entries": [
            {"page_url": "https://docs.example.com/a", "target_name": "svc", "relevance": "high",
             "category": "breaking-change", "summary": "Changed.", "topics_matched": []}
        ],
        "digest": [{"rel": "high", "text": "Summary."}],
    }
    open(path, "w").write(json.dumps(data))

    store = AnalysisStore(str(tmp_path))
    import datetime
    entries = store.read_since(datetime.date(2025, 1, 20))

    assert len(entries) == 1
    assert entries[0]["page_url"] == "https://docs.example.com/a"


def test_read_since_handles_legacy_flat_list_format(tmp_path):
    path = os.path.join(str(tmp_path), "2025-01-21.json")
    data = [
        {"page_url": "https://docs.example.com/b", "target_name": "svc", "relevance": "low",
         "category": "cosmetic", "summary": "Minor.", "topics_matched": []}
    ]
    open(path, "w").write(json.dumps(data))

    store = AnalysisStore(str(tmp_path))
    import datetime
    entries = store.read_since(datetime.date(2025, 1, 21))

    assert len(entries) == 1
    assert entries[0]["page_url"] == "https://docs.example.com/b"


# --- Run Analysis integration ---

def _make_run_analysis_record(date: str, url: str, target: str = "svc") -> dict:
    return {
        "date": date,
        "targets": [
            {
                "target_name": target,
                "pages": [
                    {
                        "type": "modified",
                        "url": url,
                        "diffs": [{"heading": "H", "added": ["new"], "removed": ["old"]}],
                        "analysis": {
                            "relevance": "high",
                            "category": "breaking-change",
                            "summary": "Auth changed.",
                            "topics_matched": ["auth"],
                        },
                    }
                ],
            }
        ],
    }


def test_read_since_includes_run_analysis_entries(tmp_path):
    """Run Analysis records appear in read_since when run_analyses_dir is given."""
    import datetime
    legacy_dir = tmp_path / "analyses"
    run_dir = tmp_path / "run_analyses"
    run_dir.mkdir()

    record = _make_run_analysis_record("2025-02-01", "https://docs.example.com/x")
    (run_dir / "2025-02-01.json").write_text(json.dumps(record))

    store = AnalysisStore(str(legacy_dir), run_analyses_dir=str(run_dir))
    entries = store.read_since(datetime.date(2025, 2, 1))

    assert len(entries) == 1
    assert entries[0]["page_url"] == "https://docs.example.com/x"
    assert entries[0]["target_name"] == "svc"
    assert entries[0]["relevance"] == "high"


def test_read_since_merges_legacy_and_run_analysis(tmp_path):
    """Entries from legacy analyses and run_analyses are combined in read_since."""
    import datetime
    legacy_dir = tmp_path / "analyses"
    run_dir = tmp_path / "run_analyses"
    legacy_dir.mkdir()
    run_dir.mkdir()

    legacy_entry = {"page_url": "https://docs.example.com/legacy", "target_name": "svc",
                    "relevance": "low", "category": "cosmetic", "summary": "Old.", "topics_matched": []}
    (legacy_dir / "2025-02-01.json").write_text(json.dumps([legacy_entry]))

    run_record = _make_run_analysis_record("2025-02-01", "https://docs.example.com/new")
    (run_dir / "2025-02-01.json").write_text(json.dumps(run_record))

    store = AnalysisStore(str(legacy_dir), run_analyses_dir=str(run_dir))
    entries = store.read_since(datetime.date(2025, 2, 1))

    urls = {e["page_url"] for e in entries}
    assert "https://docs.example.com/legacy" in urls
    assert "https://docs.example.com/new" in urls


def test_read_run_reads_from_run_analyses_dir(tmp_path):
    """read_run returns normalized entries from a Run Analysis record."""
    import datetime
    legacy_dir = tmp_path / "analyses"
    run_dir = tmp_path / "run_analyses"
    run_dir.mkdir()

    run_record = _make_run_analysis_record("2025-03-01", "https://docs.example.com/r")
    run_record["run_digest"] = [{"rel": "high", "text": "Digest bullet."}]
    (run_dir / "2025-03-01.json").write_text(json.dumps(run_record))

    store = AnalysisStore(str(legacy_dir), run_analyses_dir=str(run_dir))
    entries, digest = store.read_run("2025-03-01")

    assert len(entries) == 1
    assert entries[0]["page_url"] == "https://docs.example.com/r"
    assert digest is not None
    assert digest[0]["text"] == "Digest bullet."


def test_read_run_falls_back_to_legacy_when_run_analysis_missing(tmp_path):
    """read_run falls back to the legacy analyses file when no run_analyses record exists."""
    legacy_dir = tmp_path / "analyses"
    run_dir = tmp_path / "run_analyses"
    legacy_dir.mkdir()
    run_dir.mkdir()

    legacy_data = {
        "entries": [{"page_url": "https://docs.example.com/old", "target_name": "svc",
                     "relevance": "low", "category": "cosmetic", "summary": "Old.", "topics_matched": []}],
        "digest": [{"rel": "low", "text": "Legacy digest."}],
    }
    (legacy_dir / "2025-04-01.json").write_text(json.dumps(legacy_data))

    store = AnalysisStore(str(legacy_dir), run_analyses_dir=str(run_dir))
    entries, digest = store.read_run("2025-04-01")

    assert len(entries) == 1
    assert entries[0]["page_url"] == "https://docs.example.com/old"
    assert digest is not None
    assert digest[0]["text"] == "Legacy digest."


def test_read_since_skips_run_analysis_pages_without_analysis(tmp_path):
    """Pages in Run Analysis records that have no 'analysis' field are excluded from entries."""
    import datetime
    run_dir = tmp_path / "run_analyses"
    run_dir.mkdir()

    record = {
        "date": "2025-05-01",
        "targets": [{"target_name": "svc", "pages": [
            {"type": "new", "url": "https://docs.example.com/no-analysis",
             "sections": [{"heading": "H", "body": "body"}]},
        ]}],
    }
    (run_dir / "2025-05-01.json").write_text(json.dumps(record))

    store = AnalysisStore(str(tmp_path / "analyses"), run_analyses_dir=str(run_dir))
    entries = store.read_since(datetime.date(2025, 5, 1))

    assert entries == []
