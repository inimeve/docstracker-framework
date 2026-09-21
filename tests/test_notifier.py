import email as email_lib
from unittest.mock import MagicMock, patch
from docstracker_framework.models import ModifiedPage, Page, PageAnalysis, Section, NewPage, SectionDiff
from docstracker_framework.notifier import EmailNotifier, Notifier


def make_new_page(url="http://example.com/page"):
    return NewPage(page=Page(url=url, sections=[Section(heading="Intro", body="Hello")]))


def make_smtp_factory():
    smtp_instance = MagicMock()
    smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
    smtp_instance.__exit__ = MagicMock(return_value=False)
    factory = MagicMock(return_value=smtp_instance)
    return factory, smtp_instance


def test_email_notifier_implements_notifier_interface():
    assert isinstance(EmailNotifier(), Notifier)


def test_smtp_called_when_changes_present(monkeypatch):
    monkeypatch.setenv("GMAIL_FROM", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    factory, smtp = make_smtp_factory()
    notifier = EmailNotifier(smtp_factory=factory)
    notifier.send({"My Docs": [make_new_page()]}, recipient="recipient@gmail.com")
    factory.assert_called_once()
    smtp.sendmail.assert_called_once()


def test_no_smtp_connection_when_no_changes(monkeypatch):
    monkeypatch.setenv("GMAIL_FROM", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    factory, _ = make_smtp_factory()
    notifier = EmailNotifier(smtp_factory=factory)
    notifier.send({}, recipient="recipient@gmail.com")
    factory.assert_not_called()


def test_missing_gmail_from_raises_error(monkeypatch):
    monkeypatch.delenv("GMAIL_FROM", raising=False)
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    factory, _ = make_smtp_factory()
    notifier = EmailNotifier(smtp_factory=factory)
    try:
        notifier.send({"My Docs": [make_new_page()]}, recipient="r@gmail.com")
        assert False, "Expected RuntimeError"
    except RuntimeError as e:
        assert "GMAIL_FROM" in str(e)


def test_missing_gmail_password_raises_error(monkeypatch):
    monkeypatch.setenv("GMAIL_FROM", "sender@gmail.com")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    factory, _ = make_smtp_factory()
    notifier = EmailNotifier(smtp_factory=factory)
    try:
        notifier.send({"My Docs": [make_new_page()]}, recipient="r@gmail.com")
        assert False, "Expected RuntimeError"
    except RuntimeError as e:
        assert "GMAIL_APP_PASSWORD" in str(e)


def test_analyses_included_in_email_body(monkeypatch):
    monkeypatch.setenv("GMAIL_FROM", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    factory, smtp = make_smtp_factory()
    page = Page(url="http://docs.example.com/api", sections=[])
    analysis = PageAnalysis(
        page_url=page.url, relevance="high", category="breaking-change", summary="Auth endpoint changed."
    )
    notifier = EmailNotifier(smtp_factory=factory)
    notifier.send(
        {"Docs": [ModifiedPage(page=page, diffs=[SectionDiff(heading="Auth", added=[], removed=[])])]},
        recipient="r@gmail.com",
        analyses={"Docs": [analysis]},
    )
    raw = smtp.sendmail.call_args[0][2]
    msg = email_lib.message_from_string(raw)
    html = next(p for p in msg.walk() if p.get_content_type() == "text/html").get_payload(decode=True).decode()
    assert "Auth endpoint changed." in html
    assert "breaking-change" in html


def test_email_attaches_change_report_html(monkeypatch):
    monkeypatch.setenv("GMAIL_FROM", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    factory, smtp = make_smtp_factory()
    notifier = EmailNotifier(smtp_factory=factory)
    notifier.send({"My Docs": [make_new_page("http://docs.example.com/intro")]}, recipient="recipient@gmail.com")
    raw = smtp.sendmail.call_args[0][2]
    msg = email_lib.message_from_string(raw)
    html_parts = [part for part in msg.walk() if part.get_content_type() == "text/html"]
    assert len(html_parts) == 1
    assert html_parts[0].get_payload(decode=True).decode().startswith("<!DOCTYPE html>")
