import json
import os
import sys
import httpx
import pytest
import yaml


def make_config_yaml(tmp_path, synthesizer=True):
    config = {
        "email": "test@example.com",
        "targets": [
            {"name": "My Docs", "url": "https://docs.example.com/"},
            {"name": "Other Docs", "url": "https://other.example.com/"},
        ],
    }
    if synthesizer:
        config["synthesizer"] = {"endpoint": "http://localhost:11434/v1", "model": "gemma3:27b"}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(config))
    return str(path)


def make_snapshot(tmp_path, target_name, url, content="## Intro\n\nSome content."):
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", target_name.lower()).strip("-")
    import hashlib
    filename = hashlib.sha1(url.encode()).hexdigest() + ".txt"
    target_dir = tmp_path / "snapshots" / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / filename).write_text(f"url: {url}\n\n{content}")
    manifest = target_dir / "manifest.json"
    data = json.loads(manifest.read_text()) if manifest.exists() else {}
    data[url] = filename
    manifest.write_text(json.dumps(data))


def make_mock_transport(text: str = "# Overview\n\n## Scope\n\nContent."):
    content = json.dumps({"choices": [{"message": {"content": text}}]})

    def handler(request):
        return httpx.Response(200, content=content.encode())

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def patch_synthesizer_client(monkeypatch, tmp_path):
    import docstracker_framework.synthesizer as synth_mod

    original_init = synth_mod.Synthesizer.__init__

    def patched_init(self, config, client=None):
        original_init(self, config, client=httpx.Client(
            transport=make_mock_transport(),
            base_url=config.endpoint,
        ))

    monkeypatch.setattr(synth_mod.Synthesizer, "__init__", patched_init)


def run_cli(argv):
    import docstracker_framework.cli as cli
    sys.argv = argv
    cli.main()


def test_overview_writes_overview_md_for_all_targets(tmp_path):
    config_path = make_config_yaml(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/page1")
    make_snapshot(tmp_path, "Other Docs", "https://other.example.com/page1")

    run_cli(["docstracker", "--config", config_path, "overview"])

    import re
    for name in ["My Docs", "Other Docs"]:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        overview = tmp_path / "snapshots" / slug / "OVERVIEW.md"
        assert overview.exists(), f"OVERVIEW.md not found for {name}"
        assert "# Overview" in overview.read_text()


def test_overview_target_flag_limits_to_one_target(tmp_path):
    config_path = make_config_yaml(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/page1")
    make_snapshot(tmp_path, "Other Docs", "https://other.example.com/page1")

    run_cli(["docstracker", "--config", config_path, "overview", "--target", "My Docs"])

    import re
    slug_a = re.sub(r"[^a-z0-9]+", "-", "My Docs".lower()).strip("-")
    slug_b = re.sub(r"[^a-z0-9]+", "-", "Other Docs".lower()).strip("-")
    assert (tmp_path / "snapshots" / slug_a / "OVERVIEW.md").exists()
    assert not (tmp_path / "snapshots" / slug_b / "OVERVIEW.md").exists()


def test_overview_errors_without_synthesizer(tmp_path, capsys):
    config_path = make_config_yaml(tmp_path, synthesizer=False)

    with pytest.raises(SystemExit) as exc:
        run_cli(["docstracker", "--config", config_path, "overview"])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "synthesizer" in captured.err.lower()


def test_overview_overwrites_existing_file(tmp_path):
    import re
    config_path = make_config_yaml(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/page1")
    slug = re.sub(r"[^a-z0-9]+", "-", "My Docs".lower()).strip("-")
    overview_path = tmp_path / "snapshots" / slug / "OVERVIEW.md"
    overview_path.parent.mkdir(parents=True, exist_ok=True)
    overview_path.write_text("old content")

    run_cli(["docstracker", "--config", config_path, "overview", "--target", "My Docs"])

    assert overview_path.read_text() != "old content"
    assert "# Overview" in overview_path.read_text()


def test_overview_limits_snapshot_corpus_sent_to_synthesizer(tmp_path, monkeypatch):
    import docstracker_framework.cli as cli
    import docstracker_framework.synthesizer as synth_mod

    config_path = make_config_yaml(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/page1", content="## Intro\n" + "A" * 1000)
    captured = {}

    monkeypatch.setattr(cli, "_OVERVIEW_CORPUS_MAX_CHARS", 100)

    def fake_generate_overview(self, target_name, corpus):
        captured["corpus"] = corpus
        return "# Overview"

    monkeypatch.setattr(synth_mod.Synthesizer, "generate_overview", fake_generate_overview)

    run_cli(["docstracker", "--config", config_path, "overview", "--target", "My Docs"])

    assert len(captured["corpus"]) < 200
    assert "Corpus truncated" in captured["corpus"]


def test_overview_generation_failure_does_not_exit(tmp_path, monkeypatch, capsys):
    import docstracker_framework.synthesizer as synth_mod

    config_path = make_config_yaml(tmp_path)
    make_snapshot(tmp_path, "My Docs", "https://docs.example.com/page1")

    def fake_generate_overview(self, target_name, corpus):
        raise httpx.HTTPStatusError(
            "Client error '400 Bad Request'",
            request=httpx.Request("POST", "http://localhost/chat/completions"),
            response=httpx.Response(400),
        )

    monkeypatch.setattr(synth_mod.Synthesizer, "generate_overview", fake_generate_overview)

    run_cli(["docstracker", "--config", config_path, "overview", "--target", "My Docs"])

    captured = capsys.readouterr()
    assert "Skipped: overview generation failed" in captured.err
