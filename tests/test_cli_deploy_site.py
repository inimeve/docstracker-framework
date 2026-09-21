import subprocess
import sys
from unittest.mock import patch

import pytest


def test_deploy_site_fails_when_cloudflare_api_token_missing(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.setenv("CLOUDFLARE_PAGES_PROJECT_NAME", "docstracker")

    from docstracker_framework.cli import main
    sys.argv = ["docstracker", "--config", str(config_path), "deploy-site"]
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    err = capsys.readouterr().err
    assert "CLOUDFLARE_API_TOKEN" in err


def test_deploy_site_fails_when_cloudflare_account_id_missing(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token123")
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("CLOUDFLARE_PAGES_PROJECT_NAME", "docstracker")

    from docstracker_framework.cli import main
    sys.argv = ["docstracker", "--config", str(config_path), "deploy-site"]
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    err = capsys.readouterr().err
    assert "CLOUDFLARE_ACCOUNT_ID" in err


def test_deploy_site_runs_cloudflare_deploy_with_npx_and_prints_url(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text("<html></html>")

    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token123")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.setenv("CLOUDFLARE_PAGES_PROJECT_NAME", "docstracker")

    with patch("docstracker_framework.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://docstracker_framework.pages.dev\n"
        )
        from docstracker_framework.cli import main
        sys.argv = [
            "docstracker", "--config", str(config_path),
            "deploy-site", "--dir", str(site_dir),
        ]
        main()

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[:5] == ["npx", "-y", "wrangler", "pages", "deploy"]
    assert str(site_dir) in args
    assert "--project-name" in args
    assert "docstracker" in args
    out = capsys.readouterr().out
    assert "https://docstracker_framework.pages.dev" in out


def test_deploy_site_propagates_cloudflare_error(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text("<html></html>")

    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token123")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.setenv("CLOUDFLARE_PAGES_PROJECT_NAME", "docstracker")

    with patch("docstracker_framework.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stderr="Authentication failed\n"
        )
        from docstracker_framework.cli import main
        sys.argv = [
            "docstracker", "--config", str(config_path),
            "deploy-site", "--dir", str(site_dir),
        ]
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Authentication failed" in err


def test_deploy_site_defaults_to_site_dir_next_to_config(tmp_path, monkeypatch, capsys):
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    config_path = subdir / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    dist_dir = subdir / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html></html>")

    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token123")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.setenv("CLOUDFLARE_PAGES_PROJECT_NAME", "docstracker")

    with patch("docstracker_framework.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://docstracker_framework.pages.dev\n"
        )
        from docstracker_framework.cli import main
        sys.argv = ["docstracker", "--config", str(config_path), "deploy-site"]
        main()

    args = mock_run.call_args[0][0]
    assert str(dist_dir) in args


def test_deploy_site_accepts_cloudflare_provider_for_existing_commands(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text("<html></html>")

    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token123")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.setenv("CLOUDFLARE_PAGES_PROJECT_NAME", "docstracker")

    with patch("docstracker_framework.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://docstracker_framework.pages.dev\n"
        )
        from docstracker_framework.cli import main
        sys.argv = [
            "docstracker", "--config", str(config_path),
            "deploy-site", "--provider", "cloudflare", "--dir", str(site_dir),
        ]
        main()

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[:5] == ["npx", "-y", "wrangler", "pages", "deploy"]
    assert str(site_dir) in args
    assert "--project-name" in args
    assert "docstracker" in args
    out = capsys.readouterr().out
    assert "https://docstracker_framework.pages.dev" in out


def test_deploy_site_fails_when_cloudflare_project_name_missing(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("email: u@e.com\ntargets:\n  - name: My Docs\n    url: http://x.com/\n")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token123")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.delenv("CLOUDFLARE_PAGES_PROJECT_NAME", raising=False)

    from docstracker_framework.cli import main
    sys.argv = ["docstracker", "--config", str(config_path), "deploy-site", "--provider", "cloudflare"]
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    err = capsys.readouterr().err
    assert "CLOUDFLARE_PAGES_PROJECT_NAME" in err

