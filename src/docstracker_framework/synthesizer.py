import json
import uuid

import httpx
from docstracker_framework.models import AnalyzerConfig

_SYNTHESIZER_TIMEOUT = httpx.Timeout(connect=30.0, read=900.0, write=60.0, pool=30.0)

_DIGEST_PROMPT = """\
You are a technical documentation analyst. Given the PageAnalysis entries from the past week below, produce a coherent narrative email summarizing:
- What changed this week across all tracked documentation sources
- What matters most (prioritize high-relevance changes)
- Which Topics were touched

High-relevance changes and pages with matched Topics deserve special emphasis.

Analysis entries (JSON):
{analyses_json}

Return only the email body as HTML, starting with an <h2> heading. Write in a concise, professional tone.
"""

_RUN_DIGEST_PROMPT = """\
You are a technical documentation analyst. Given the list of page-level change analyses below from a single crawl run, produce a concise digest of 2-5 thematic bullet points that summarise what changed and what matters most.

Each bullet must have a relevance level ("high", "medium", or "low") and a short text (1-2 sentences, in Spanish).

Changes (JSON):
{changes_json}

Return a JSON object with a single key "bullets" containing an array of objects, each with "rel" and "text" fields. Example:
{{"bullets": [{{"rel": "high", "text": "Descripción del cambio más importante."}}]}}
"""

_OVERVIEW_PROMPT = """\
You are a technical documentation analyst. Given all current Snapshot content for the Watch Target below, produce a structured Markdown overview document describing:
- The scope and purpose of this documentation source
- The key topic areas covered
- The overall content structure

Watch Target: {target_name}

Snapshot content:
{corpus}

Return only valid Markdown with a meaningful title (# heading) and section headings (## for each area).
"""


class Synthesizer:
    def __init__(self, config: AnalyzerConfig, client: httpx.Client | None = None):
        self._config = config
        self._client = client or httpx.Client(
            base_url=config.endpoint,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "x-opencode-session": f"docstracker-synthesizer-{uuid.uuid4()}",
            } if config.api_key else {},
            timeout=_SYNTHESIZER_TIMEOUT,
        )

    def generate_digest(self, analyses_text: str) -> str:
        prompt = _DIGEST_PROMPT.format(analyses_json=analyses_text)
        response = self._client.post(
            "/chat/completions",
            json={
                "model": self._config.model,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def synthesize_run_digest(self, changes: list[dict]) -> list[dict]:
        prompt = _RUN_DIGEST_PROMPT.format(changes_json=json.dumps(changes, ensure_ascii=False))
        response = self._client.post(
            "/chat/completions",
            json={
                "model": self._config.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)["bullets"]

    def generate_overview(self, target_name: str, corpus: str) -> str:
        prompt = _OVERVIEW_PROMPT.format(target_name=target_name, corpus=corpus)
        response = self._client.post(
            "/chat/completions",
            json={
                "model": self._config.model,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
