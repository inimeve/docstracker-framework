from collections import Counter

from docstracker_framework.models import ModifiedPage, NewPage, PageAnalysis, NavNodeAdded, NavNodeRemoved, NavNodeRenamed


_STYLE = """
  body { margin: 0; padding: 24px 12px; background: #dfe5dc;
         font-family: "JetBrains Mono","SF Mono","Fira Code",Menlo,Consolas,ui-monospace,monospace;
         color: #16201a; font-size: 13px; line-height: 1.55; }
  .email-wrapper { max-width: 720px; margin: 0 auto; background: #ffffff;
                   border: 1px solid #c8d2c8; }
  .email-header { padding: 14px 18px; border-bottom: 1px solid #c8d2c8;
                  background: #ffffff; }
  .email-header-title { font-size: 14px; font-weight: 600; color: #16201a; }
  .email-header-sub { color: #5a635f; font-size: 11px; margin-top: 4px;
                      text-transform: uppercase; letter-spacing: .08em; }

  .dashboard table { width: 100%; border-collapse: collapse;
                     border-bottom: 1px solid #c8d2c8; }
  .dashboard td { padding: 14px 16px; border-right: 1px solid #c8d2c8;
                  vertical-align: top; width: 25%; background: #ffffff; }
  .dashboard td:last-child { border-right: 0; }
  .stat-label { font-size: 10px; color: #5a635f; text-transform: uppercase;
                letter-spacing: .08em; }
  .stat-value { font-size: 26px; font-weight: 700; color: #16201a;
                line-height: 1.05; margin-top: 4px; }
  .stat-value-new { color: #047857; }
  .stat-value-mod { color: #92400e; }
  .stat-value-high { color: #b91c1c; }
  .stat-sub { font-size: 11px; color: #94a39c; margin-top: 2px; }
  .cat-pills { padding: 10px 16px; background: #f5f7f4;
               border-bottom: 1px solid #c8d2c8; }
  .cat { font-size: 11px; font-family: inherit; margin-right: 8px;
         font-weight: 600; }
  .cat::before { content: "<"; }
  .cat::after { content: ">"; }
  .cat-breaking-change { color: #b91c1c; }
  .cat-deprecation { color: #c2410c; }
  .cat-cosmetic { color: #4b5563; }
  .cat-default { color: #0369a1; }

  .run-summary { padding: 14px 18px; border-bottom: 1px solid #c8d2c8;
                 background: #ffffff; }
  .run-summary h4 { margin: 0 0 8px; font-size: 10px; text-transform: uppercase;
                    letter-spacing: .08em; color: #5a635f; font-weight: 600; }
  .run-summary ul { margin: 0; padding: 0; list-style: none; }
  .run-summary li { padding: 4px 0; display: block; font-size: 13px;
                    color: #16201a; line-height: 1.55; }
  .run-summary li .pill { margin-right: 8px; }

  .spotlight { padding: 14px 18px; border-bottom: 1px solid #c8d2c8;
               background: #fdf2f2; }
  .spotlight-title { font-size: 10px; text-transform: uppercase;
                     letter-spacing: .08em; color: #b91c1c; font-weight: 700;
                     margin-bottom: 10px; }
  .highlight-item { background: #ffffff; border: 1px solid #fecaca;
                    border-left: 3px solid #b91c1c; padding: 8px 10px;
                    margin: 6px 0; }
  .highlight-url { font-size: 12px; color: #047857; word-break: break-word; }
  .highlight-summary { color: #16201a; font-size: 12px; margin-top: 4px; }

  .content { padding: 0; }
  .target { border-bottom: 1px solid #c8d2c8; }
  .target:last-child { border-bottom: 0; }
  .target-label { padding: 8px 18px; background: #e8ede6;
                  border-bottom: 1px solid #c8d2c8; font-size: 11px;
                  font-weight: 600; text-transform: uppercase;
                  letter-spacing: .08em; color: #16201a; }
  .target-label .n { color: #94a39c; font-weight: 400; margin-left: 6px; }
  .change-card { padding: 10px 18px; border-bottom: 1px solid #c8d2c8;
                 background: #ffffff; }
  .change-card:last-child { border-bottom: 0; }
  .badge-new { background: #047857; color: #fff; font-size: 10px;
               font-weight: 700; padding: 2px 6px; letter-spacing: .04em; }
  .badge-mod { background: #92400e; color: #fff; font-size: 10px;
               font-weight: 700; padding: 2px 6px; letter-spacing: .04em; }
  a { color: #047857; word-break: break-word; text-decoration: underline; }
  .card-summary { color: #16201a; font-size: 12px; margin-top: 6px; }
  .sections-count { color: #94a39c; font-size: 11px; margin-top: 4px; }

  .pill { font-size: 11px; font-weight: 700; letter-spacing: .04em;
          font-family: inherit; }
  .pill::before { content: "["; }
  .pill::after { content: "]"; }
  .rel-high { color: #b91c1c; }
  .rel-medium { color: #92400e; }
  .rel-low { color: #4b5563; }
  .topics-row { margin: 4px 0; }
  .topic-match { display: inline-block; color: #92400e;
                 border: 1px solid #c8d2c8; padding: 1px 5px;
                 font-size: 11px; margin-right: 4px; }
  .diff-heading { font-size: 12px; font-weight: 600; color: #5a635f;
                  margin: 10px 0 4px; }
  .diff { font-family: inherit; font-size: 12px; padding: 3px 8px;
          margin: 2px 0; }
  .added { border-left: 3px solid #047857; background: #f0fdf4;
           color: #16201a; }
  .removed { border-left: 3px solid #b91c1c; background: #fef2f2;
             color: #16201a; }
  .no-diff { color: #94a39c; font-size: 12px; }
  .email-footer { padding: 12px 18px; font-size: 11px; color: #94a39c;
                  background: #f5f7f4; border-top: 1px solid #c8d2c8; }
"""

_RELEVANCE_ORDER = {"high": 0, "medium": 1, "low": 2}

_CATEGORY_CSS = {
    "breaking-change": "cat-breaking-change",
    "deprecation": "cat-deprecation",
    "cosmetic": "cat-cosmetic",
}


def _cat_span(category: str) -> str:
    cls = _CATEGORY_CSS.get(category, "cat-default")
    return f"<span class='cat {cls}'>{category}</span>"


def _rel_span(relevance: str) -> str:
    cls = f"rel-{relevance}" if relevance in ("high", "medium", "low") else "rel-low"
    return f"<span class='pill {cls}'>{relevance}</span>"


def _analysis_block(analysis: PageAnalysis) -> str:
    topics_html = ""
    if analysis.topics_matched:
        badges = "".join(f"<span class='topic-match'>{t}</span>" for t in analysis.topics_matched)
        topics_html = f"<div class='topics-row'>{badges}</div>"
    return (
        f"<div class='card-analysis'>"
        f"{_cat_span(analysis.category)} {_rel_span(analysis.relevance)}"
        f"{topics_html}"
        f"<div class='card-summary'>{analysis.summary}</div>"
        f"</div>"
    )


def _section_diff_html(diff) -> str:
    lines = [f"<div class='diff-heading'>§ {diff.heading}</div>"]
    if not diff.added and not diff.removed:
        lines.append("<div class='no-diff'>No line-level changes.</div>")
        return "\n".join(lines)
    for line in diff.removed:
        lines.append(f"<div class='diff removed'>- {line}</div>")
    for line in diff.added:
        lines.append(f"<div class='diff added'>+ {line}</div>")
    return "\n".join(lines)


def _page_count_summary(changes: list) -> str:
    new_count = sum(1 for c in changes if isinstance(c, NewPage))
    mod_count = sum(1 for c in changes if isinstance(c, ModifiedPage))
    parts = []
    if new_count:
        parts.append(f"{new_count} new page{'s' if new_count > 1 else ''}")
    if mod_count:
        parts.append(f"{mod_count} modified page{'s' if mod_count > 1 else ''}")
    return " · ".join(parts)


def _dashboard_html(changes: list, analyses: dict[str, list[PageAnalysis]]) -> str:
    all_analyses = [a for lst in analyses.values() for a in lst]
    category_counts = Counter(a.category for a in all_analyses)
    high_count = sum(1 for a in all_analyses if a.relevance == "high")
    new_c = sum(1 for c in changes if isinstance(c, NewPage))
    mod_c = sum(1 for c in changes if isinstance(c, ModifiedPage))
    target_count = len(analyses) if analyses else 0

    cat_pills = "".join(
        f"<span class='cat {_CATEGORY_CSS.get(cat, 'cat-default')}'>{count} {cat}</span>"
        for cat, count in sorted(category_counts.items())
    )

    parts = [
        "<div class='dashboard'>",
        "<table role='presentation' cellspacing='0' cellpadding='0'><tr>",
        f"<td><div class='stat-label'>Cambios</div>"
        f"<div class='stat-value'>{len(changes)}</div>"
        f"<div class='stat-sub'>en {target_count} target(s)</div></td>",
        f"<td><div class='stat-label'>High</div>"
        f"<div class='stat-value stat-value-high'>{high_count}</div>"
        f"<div class='stat-sub'>acción prioritaria</div></td>",
        f"<td><div class='stat-label'>Nuevas</div>"
        f"<div class='stat-value stat-value-new'>{new_c}</div>"
        f"<div class='stat-sub'>páginas</div></td>",
        f"<td><div class='stat-label'>Modificadas</div>"
        f"<div class='stat-value stat-value-mod'>{mod_c}</div>"
        f"<div class='stat-sub'>páginas</div></td>",
        "</tr></table>",
        "</div>",
    ]
    if cat_pills:
        parts.append(f"<div class='cat-pills'>{cat_pills}</div>")
    return "\n".join(parts)


def _spotlight_html(analyses: dict[str, list[PageAnalysis]]) -> str:
    high_items = [a for lst in analyses.values() for a in lst if a.relevance == "high"]
    if not high_items:
        return ""
    parts = ["<div class='spotlight'><div class='spotlight-title'>Acción requerida</div>"]
    for a in high_items:
        cls = _CATEGORY_CSS.get(a.category, "cat-default")
        parts.append(
            f"<div class='highlight-item'>"
            f"<span class='cat {cls}'>{a.category}</span> "
            f"<a class='highlight-url' href='{a.page_url}'>{a.page_url}</a>"
            f"<div class='highlight-summary'>{a.summary}</div>"
            f"</div>"
        )
    parts.append("</div>")
    return "\n".join(parts)


def _digest_html(digest: list[dict]) -> str:
    if not digest:
        return ""
    parts = ["<div class='run-summary'><h4>Resumen del run</h4><ul>"]
    for bullet in digest:
        rel = bullet.get("rel", "low")
        text = bullet.get("text", "")
        parts.append(f"<li>{_rel_span(rel)}{text}</li>")
    parts.append("</ul></div>")
    return "\n".join(parts)


def _nav_change_item_html(change) -> str:
    if isinstance(change, NavNodeAdded):
        link = f" <a href='{change.url}'>{change.url}</a>" if change.url else ""
        parent = f" (under {change.parent_title})" if change.parent_title else ""
        return f"<div class='nav-change-item'><span class='badge-nav-added'>+</span> {change.title}{link}{parent}</div>"
    if isinstance(change, NavNodeRemoved):
        parent = f" (from {change.parent_title})" if change.parent_title else ""
        return f"<div class='nav-change-item'><span class='badge-nav-removed'>−</span> {change.title}{parent}</div>"
    if isinstance(change, NavNodeRenamed):
        link = f" <a href='{change.url}'>{change.url}</a>" if change.url else ""
        return f"<div class='nav-change-item'><span class='badge-nav-renamed'>↷</span> {change.old_title} → {change.new_title}{link}</div>"
    return ""


def build_change_report_html(
    changes_by_target: dict[str, list],
    analyses: dict[str, list[PageAnalysis]] | None = None,
    digest: list[dict] | None = None,
    nav_changes_by_target: dict[str, list] | None = None,
) -> str:
    all_changes = [c for lst in changes_by_target.values() for c in lst]

    parts = [
        "<!DOCTYPE html>",
        "<html lang='es'>",
        "<head>",
        "<meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<style>{_STYLE}</style>",
        "</head>",
        "<body>",
        "<div class='email-wrapper'>",
    ]
    parts.append(
        f"<div class='email-header'>"
        f"<div class='email-header-title'>DocTracker</div>"
        f"<div class='email-header-sub'>{_page_count_summary(all_changes)}</div>"
        f"</div>"
    )

    if analyses:
        parts.append(_dashboard_html(all_changes, analyses))

    if digest:
        parts.append(_digest_html(digest))

    if analyses:
        parts.append(_spotlight_html(analyses))

    parts.append("<div class='content'>")

    for target_name, target_changes in changes_by_target.items():
        target_analyses: dict[str, PageAnalysis] = {}
        if analyses:
            for a in analyses.get(target_name, []):
                target_analyses[a.page_url] = a

        def _sort_key(c):
            url = getattr(getattr(c, "page", None), "url", None)
            if url and url in target_analyses:
                return _RELEVANCE_ORDER.get(target_analyses[url].relevance, 3)
            return 3

        sorted_changes = sorted(target_changes, key=_sort_key)

        parts.append(
            f"<div class='target'>"
            f"<div class='target-label'>{target_name}"
            f"<span class='n'>{len(sorted_changes)} change{'s' if len(sorted_changes) != 1 else ''}</span>"
            f"</div>"
        )
        for change in sorted_changes:
            if not isinstance(change, (NewPage, ModifiedPage)):
                raise TypeError(f"Unsupported change type: {type(change).__name__}")
            analysis = target_analyses.get(change.page.url)
            parts.append("<div class='change-card'>")
            if isinstance(change, NewPage):
                parts.append(
                    f"<span class='badge-new'>NEW</span> "
                    f"<a href='{change.page.url}'>{change.page.url}</a>"
                )
                if analysis:
                    parts.append(_analysis_block(analysis))
                parts.append(f"<div class='sections-count'>{len(change.page.sections)} section(s) captured.</div>")
            elif isinstance(change, ModifiedPage):
                parts.append(
                    f"<span class='badge-mod'>MODIFIED</span> "
                    f"<a href='{change.page.url}'>{change.page.url}</a>"
                )
                if analysis:
                    parts.append(_analysis_block(analysis))
                for diff in change.diffs:
                    parts.append(_section_diff_html(diff))
            parts.append("</div>")
        parts.append("</div>")

    parts.append("</div>")

    if nav_changes_by_target:
        parts.append("<div class='content'>")
        for target_name, nav_changes in nav_changes_by_target.items():
            parts.append(
                f"<div class='target'>"
                f"<div class='target-label'>{target_name} — navigation"
                f"<span class='n'>{len(nav_changes)} structural change{'s' if len(nav_changes) != 1 else ''}</span>"
                f"</div>"
            )
            parts.append("<div class='change-card'>")
            for c in nav_changes:
                parts.append(_nav_change_item_html(c))
            parts.append("</div>")
            parts.append("</div>")
        parts.append("</div>")

    parts.append("<div class='email-footer'>Sent by DocTracker</div>")
    parts.append("</div></body></html>")
    return "\n".join(parts)
