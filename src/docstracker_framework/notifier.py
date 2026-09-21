import os
import smtplib
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from docstracker_framework.models import PageAnalysis
from docstracker_framework.change_report import build_change_report_html

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 465


class Notifier(ABC):
    """Delivers a Run Digest / Change Report to a Watch Target's Consumers.

    `EmailNotifier` is the only implementation today. Other delivery
    adapters (Slack, webhook, ...) are expected as a follow-up; adding one
    means a new Notifier implementation, not a change to callers.
    """

    @abstractmethod
    def send(
        self,
        changes_by_target: dict[str, list],
        recipient: str,
        analyses: dict[str, list[PageAnalysis]] | None = None,
        digest: list[dict] | None = None,
    ) -> None:
        ...

    @abstractmethod
    def send_digest(self, html_body: str, recipient: str) -> None:
        ...


def _default_smtp_factory(host, port):
    return smtplib.SMTP_SSL(host, port)


def _build_subject(changes_by_target: dict[str, list], analyses: dict[str, list[PageAnalysis]] | None) -> str:
    total = sum(len(v) for v in changes_by_target.values())
    high = 0
    if analyses:
        high = sum(1 for lst in analyses.values() for a in lst if a.relevance == "high")
    parts = [f"{total} change{'s' if total != 1 else ''}"]
    if high:
        parts.insert(0, f"{high} high")
    return "DocTracker · " + " · ".join(parts)


class EmailNotifier(Notifier):
    def __init__(self, smtp_factory=None):
        self._smtp_factory = smtp_factory or (lambda host, port: _default_smtp_factory(host, port))

    def send_digest(self, html_body: str, recipient: str) -> None:
        sender = os.environ.get("GMAIL_FROM")
        if not sender:
            raise RuntimeError("GMAIL_FROM environment variable is not set")
        password = os.environ.get("GMAIL_APP_PASSWORD")
        if not password:
            raise RuntimeError("GMAIL_APP_PASSWORD environment variable is not set")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "DocTracker: Weekly Digest"
        msg["From"] = sender
        msg["To"] = recipient
        msg.attach(MIMEText(html_body, "html"))

        with self._smtp_factory(_SMTP_HOST, _SMTP_PORT) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, recipient, msg.as_string())

    def send(
        self,
        changes_by_target: dict[str, list],
        recipient: str,
        analyses: dict[str, list[PageAnalysis]] | None = None,
        digest: list[dict] | None = None,
    ) -> None:
        if not any(changes_by_target.values()):
            return

        sender = os.environ.get("GMAIL_FROM")
        if not sender:
            raise RuntimeError("GMAIL_FROM environment variable is not set")
        password = os.environ.get("GMAIL_APP_PASSWORD")
        if not password:
            raise RuntimeError("GMAIL_APP_PASSWORD environment variable is not set")

        html = build_change_report_html(changes_by_target, analyses=analyses, digest=digest)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = _build_subject(changes_by_target, analyses)
        msg["From"] = sender
        msg["To"] = recipient
        msg.attach(MIMEText(html, "html"))

        with self._smtp_factory(_SMTP_HOST, _SMTP_PORT) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, recipient, msg.as_string())
