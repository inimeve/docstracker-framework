from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import yaml


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _bucket_runs(runs: list[dict], window_days: int, interval_hours: int) -> list[dict]:
    if not runs:
        return []
    parsed = sorted(((_parse_ts(r["timestamp"]), r) for r in runs), key=lambda x: x[0])
    anchor = parsed[-1][0]
    cutoff = anchor - timedelta(days=window_days)
    visible = [(ts, r) for ts, r in parsed if ts >= cutoff]
    interval = timedelta(hours=interval_hours)
    buckets: dict[int, dict] = {}
    for ts, r in reversed(visible):
        idx = int((anchor - ts).total_seconds() // (interval_hours * 3600))
        end = anchor - idx * interval
        start = end - interval
        b = buckets.setdefault(idx, {"bucket_start": start.isoformat(), "bucket_end": end.isoformat(), "runs": []})
        b["runs"].append(r)
    return [buckets[k] for k in sorted(buckets.keys())]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def _file_anchor(path: str) -> str:
    return "diff-" + hashlib.sha256(path.encode()).hexdigest()


def _repo_from_git(cwd: str) -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return ""
    url = result.stdout.strip()
    m = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def _commits_by_date(cwd: str) -> dict[str, str]:
    result = subprocess.run(
        ["git", "log", "--format=%H|%cs", "--", "snapshots/"],
        cwd=cwd, capture_output=True, text=True,
    )
    by_date: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "|" not in line:
            continue
        sha, date = line.split("|", 1)
        by_date.setdefault(date, sha)
    return by_date


def _count_snapshots(snapshots_dir: str | None, target_slugs: dict[str, str]) -> int:
    if not snapshots_dir:
        return 0
    total = 0
    for slug in target_slugs.values():
        manifest_path = Path(snapshots_dir) / slug / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            total += len(manifest)
    return total


def _build_data(analyses_dir: str, config_path: str, commits: dict[str, str], repo: str, snapshots_dir: str | None = None, run_analyses_dir: str | None = None) -> dict:
    cfg = yaml.safe_load(Path(config_path).read_text())
    targets = cfg.get("targets", [])
    target_slugs = {t["name"]: _slug(t["name"]) for t in targets}

    runs = []
    run_analysis_runs = []
    page_history: dict[str, list[dict]] = {}

    if run_analyses_dir:
        ra_path = Path(run_analyses_dir)
        for f in sorted(ra_path.glob("*.json")):
            date = f.stem
            sha = commits.get(date)
            raw = json.loads(f.read_text())
            if not isinstance(raw, dict) or "targets" not in raw:
                continue
            enriched = []
            for target in raw["targets"]:
                target_name = target["target_name"]
                tslug = target_slugs.get(target_name) or _slug(target_name)
                for page in target.get("pages", []):
                    url = page["url"]
                    analysis = page.get("analysis")
                    file_path = f"snapshots/{tslug}/{_url_hash(url)}.txt"
                    diff_url = (
                        f"https://github.com/{repo}/commit/{sha}#{_file_anchor(file_path)}"
                        if sha else None
                    )
                    enriched.append({
                        "page_url": url,
                        "target_name": target_name,
                        "relevance": analysis["relevance"] if analysis else None,
                        "category": analysis["category"] if analysis else None,
                        "summary": analysis["summary"] if analysis else None,
                        "changeType": page["type"],
                        "filePath": file_path,
                        "diffUrl": diff_url,
                    })
                    if analysis:
                        entry = page_history.setdefault(url, [])
                        entry.append({
                            "date": date, "relevance": analysis["relevance"],
                            "category": analysis["category"], "summary": analysis["summary"],
                            "target": target_name,
                        })
            if enriched:
                digest = raw.get("run_digest") or None
                ts = raw.get("timestamp") or f"{date}T00:00:00"
                run_analysis_runs.append({"date": date, "timestamp": ts, "changes": enriched, "commitSha": sha, "digest": digest})

    run_analysis_dates = {r["date"] for r in run_analysis_runs}

    for f in sorted(Path(analyses_dir).glob("*.json")):
        date = f.stem
        if date in run_analysis_dates:
            continue
        sha = commits.get(date)
        raw = json.loads(f.read_text())
        if isinstance(raw, list):
            entries_raw, digest = raw, None
        else:
            entries_raw, digest = raw.get("entries", []), raw.get("digest")
        enriched = []
        for c in entries_raw:
            tslug = target_slugs.get(c["target_name"]) or _slug(c["target_name"])
            file_path = f"snapshots/{tslug}/{_url_hash(c['page_url'])}.txt"
            diff_url = (
                f"https://github.com/{repo}/commit/{sha}#{_file_anchor(file_path)}"
                if sha else None
            )
            enriched.append({**c, "filePath": file_path, "diffUrl": diff_url})
            entry = page_history.setdefault(c["page_url"], [])
            entry.append({
                "date": date, "relevance": c["relevance"],
                "category": c["category"], "summary": c["summary"],
                "target": c["target_name"],
            })
        runs.append({"date": date, "timestamp": f"{date}T00:00:00", "changes": enriched, "commitSha": sha, "digest": digest})

    runs.extend(run_analysis_runs)

    runs.sort(key=lambda r: r["date"])
    total_tracked = _count_snapshots(snapshots_dir, target_slugs)
    return {
        "targets": targets, "runs": runs, "pageHistory": page_history,
        "repo": repo, "totalTrackedPages": total_tracked,
        "defaults": {"windowDays": 30, "intervalHours": 24},
    }


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es" data-theme="light">
<head>
<meta charset="UTF-8">
<title>DocTracker · Dashboard</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<script src="/favicon.js" defer></script>
<style>
/* S3 Terminal Mono */
*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; padding: 0; min-height: 100%; }
:root {
  --font: "JetBrains Mono","SF Mono","Fira Code",Menlo,Consolas,ui-monospace,monospace;
  --row-py: 9px;
  --row-px: 14px;
}
[data-theme="light"] {
  --bg: #f5f7f4; --bg-surface: #ffffff; --bg-elev: #ffffff;
  --bg-hover: #ebf2eb; --bg-strip: #e8ede6;
  --fg: #16201a; --fg-muted: #5a635f; --fg-subtle: #94a39c;
  --border: #c8d2c8; --border-strong: #94a39c;
  --accent: #047857; --link: #047857; --warn: #b91c1c;
}
[data-theme="dark"] {
  --bg: #0d1117; --bg-surface: #161b22; --bg-elev: #1c2128;
  --bg-hover: #21262d; --bg-strip: #1c2128;
  --fg: #c9d1d9; --fg-muted: #8b949e; --fg-subtle: #6e7681;
  --border: #30363d; --border-strong: #484f58;
  --accent: #3fb950; --link: #58a6ff; --warn: #f85149;
}
body { font-family: var(--font); color: var(--fg); background: var(--bg); line-height: 1.5; transition: background 200ms, color 200ms; }
a { color: inherit; }

header.app {
  padding: 10px 28px; background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: baseline;
}
header.app .brand { display: flex; align-items: center; gap: 10px; }
header.app strong { font-size: 15px; font-weight: 600; }
header.app .meta { font-size: 12px; color: var(--fg-muted); display: flex; align-items: center; gap: 12px; }
header.app .help-icon {
  width: 22px; height: 22px; border: 1px solid var(--border-strong);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 11px; color: var(--fg-muted); text-decoration: none;
  font-weight: 700; cursor: pointer; position: relative;
}
header.app .help-icon:hover { color: var(--accent); border-color: var(--accent); }
header.app .help-icon::after {
  content: "Cómo funciona DocTracker"; position: absolute; top: calc(100% + 6px); right: 0;
  background: var(--fg); color: var(--bg); padding: 4px 8px;
  font-size: 10px; white-space: nowrap; opacity: 0; pointer-events: none;
  transition: opacity 120ms; letter-spacing: .04em;
}
header.app .help-icon:hover::after { opacity: 1; }
#theme-toggle {
  background: none; border: 1px solid var(--border); padding: 2px 8px;
  font: 11px var(--font); color: var(--fg-muted); cursor: pointer;
}
#theme-toggle:hover { background: var(--bg-hover); }

main { padding: 20px 28px 40px; }

footer.app {
  padding: 14px 28px 40px; font-size: 11px; color: var(--fg-subtle);
  display: flex; justify-content: space-between; border-top: 1px solid var(--border);
  margin: 0 28px;
}
footer.app a { color: var(--accent); text-decoration: none; font-weight: 600; }
footer.app a:hover { text-decoration: underline; }

.kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 20px; }
.kpi { background: var(--bg-surface); border: 1px solid var(--border); padding: 12px 14px; }
.kpi .label { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: var(--fg-muted); }
.kpi .value { font-size: 22px; font-weight: 700; margin-top: 2px; line-height: 1.1; }
.kpi .value.warn { color: var(--warn); }
.kpi .sub { font-size: 10px; color: var(--fg-subtle); margin-top: 2px; }

.va { display: grid; grid-template-columns: 220px 1fr; gap: 20px; align-items: start; }
aside {
  background: var(--bg-surface); border: 1px solid var(--border);
  padding: 16px; position: sticky; top: 16px;
}
aside h3 { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: var(--fg-muted); margin: 0 0 8px; font-weight: 600; }
aside .group { margin-bottom: 16px; }
aside .group:last-child { margin-bottom: 0; }
aside label { display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 2px 0; cursor: pointer; }
aside label input { accent-color: var(--accent); }
aside .count { color: var(--fg-subtle); font-size: 11px; margin-left: auto; }

.tl-controls {
  display: flex; gap: 24px; align-items: center;
  padding: 10px 14px; margin-bottom: 12px;
  background: var(--bg-surface); border: 1px solid var(--border);
}
.tl-group { display: flex; align-items: center; gap: 8px; }
.tl-label { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: var(--fg-muted); font-weight: 600; }
.seg { display: inline-flex; border: 1px solid var(--border-strong); }
.seg button {
  font-family: var(--font); background: var(--bg-surface); border: 0;
  border-right: 1px solid var(--border-strong); padding: 5px 12px;
  font-size: 12px; cursor: pointer; color: var(--fg);
}
.seg button:last-child { border-right: 0; }
.seg button.on { background: var(--accent); color: #fff; }
.tl-summary { margin-left: auto; font-size: 11px; color: var(--fg-muted); }

.timeline { background: var(--bg-surface); border: 1px solid var(--border); overflow: hidden; }
.day-block + .day-block > summary { border-top: 1px solid var(--border); }
summary.day-header {
  padding: 10px 16px; background: var(--bg-strip);
  font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .08em;
  list-style: none; cursor: pointer; user-select: none;
  display: flex; align-items: center; gap: 10px;
  transition: background 120ms;
}
summary.day-header::-webkit-details-marker { display: none; }
summary.day-header::marker { content: ""; }
summary.day-header:hover { background: var(--bg-hover); }
.day-block[open] > summary.day-header { border-bottom: 1px solid var(--border); }
summary.day-header::before {
  content: "[+]"; font-weight: 700; color: var(--accent); font-size: 12px;
}
.day-block[open] > summary.day-header::before { content: "[-]"; }
.day-count { color: var(--fg-muted); font-weight: 400; font-size: 11px; }
.rel-summary { display: inline-flex; gap: 6px; margin-left: auto; align-items: center; }

.pill { display: inline-flex; align-items: center; padding: 1px 4px; background: transparent; border: 0; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .03em; }
.pill::before { content: "["; }
.pill::after  { content: "]"; }
[data-theme="light"] .pill-high   { color: #b91c1c; }
[data-theme="light"] .pill-medium { color: #92400e; }
[data-theme="light"] .pill-low    { color: #4b5563; }
[data-theme="dark"]  .pill-high   { color: #f87171; }
[data-theme="dark"]  .pill-medium { color: #fbbf24; }
[data-theme="dark"]  .pill-low    { color: #94a3b8; }

.cat { display: inline-flex; padding: 0; background: transparent; font-size: 11px; font-family: var(--font); }
.cat::before { content: "<"; }
.cat::after  { content: ">"; }
[data-theme="light"] .cat-breaking-change { color: #b91c1c; }
[data-theme="light"] .cat-deprecation     { color: #c2410c; }
[data-theme="light"] .cat-behavior-change { color: #6d28d9; }
[data-theme="light"] .cat-new-feature     { color: #047857; }
[data-theme="light"] .cat-clarification   { color: #0369a1; }
[data-theme="light"] .cat-limit-or-quota  { color: #0e7490; }
[data-theme="light"] .cat-new-example     { color: #0f766e; }
[data-theme="light"] .cat-cosmetic        { color: #4b5563; }
[data-theme="dark"]  .cat-breaking-change { color: #fca5a5; }
[data-theme="dark"]  .cat-deprecation     { color: #fdba74; }
[data-theme="dark"]  .cat-behavior-change { color: #c4b5fd; }
[data-theme="dark"]  .cat-new-feature     { color: #6ee7b7; }
[data-theme="dark"]  .cat-clarification   { color: #7dd3fc; }
[data-theme="dark"]  .cat-limit-or-quota  { color: #67e8f9; }
[data-theme="dark"]  .cat-new-example     { color: #5eead4; }
[data-theme="dark"]  .cat-cosmetic        { color: #cbd5e1; }
.pill-none { color: var(--fg-subtle); }
.cat-none  { color: var(--fg-subtle); font-style: italic; }
.summary.no-analysis { color: var(--fg-subtle); font-style: italic; }

.change {
  display: grid; grid-template-columns: 70px 160px 1fr; gap: 12px;
  padding: var(--row-py) var(--row-px);
  border-bottom: 1px solid var(--border); align-items: start; font-size: 12px;
}
.change:last-child { border-bottom: 0; }
.change:hover { background: var(--bg-hover); }
.change .target-tag { font-size: 11px; color: var(--fg-subtle); margin-top: 4px; }
.change .url { font-size: 12px; color: var(--link); text-decoration: none; word-break: break-all; }
.change .url:hover { text-decoration: underline; }
.change .summary { font-size: 12px; color: var(--fg); margin-top: 6px; line-height: 1.55; }
.diff-inline {
  display: inline-flex; align-items: center; gap: 4px;
  margin-top: 8px; font-size: 11px; color: var(--link); text-decoration: none; font-weight: 500;
}
.diff-inline::before { content: "›\00a0"; }
.diff-inline:hover { text-decoration: underline; }

.empty { padding: 32px; text-align: center; color: var(--fg-subtle); font-size: 12px; }

.sf-digest {
  padding: 12px 16px; border-bottom: 1px solid var(--border);
  background: var(--bg-surface); display: flex; gap: 20px; align-items: flex-start;
}
.sf-stats {
  display: flex; flex-direction: column; gap: 5px;
  flex-shrink: 0; min-width: 100px; padding-top: 2px;
}
.sf-stat-row { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.sf-bar { display: flex; height: 5px; border-radius: 3px; overflow: hidden; width: 64px; background: var(--border); margin-bottom: 6px; }
.sf-bar .bar-h { background: #b91c1c; }
.sf-bar .bar-m { background: #d97706; }
.sf-bar .bar-l { background: #9ca3af; }
.sf-bullets { flex: 1; min-width: 0; }
.sf-bullet {
  font-size: 12px; padding: 3px 0; color: var(--fg);
  display: flex; align-items: baseline; gap: 8px;
  border-bottom: 1px solid var(--border); line-height: 1.45;
}
.sf-bullet:last-child { border-bottom: none; }
.sf-bullet .sf-marker { flex-shrink: 0; font-size: 10px; }
.sf-bullet.rel-high .sf-marker { color: var(--warn); }
.sf-bullet.rel-medium .sf-marker { color: var(--fg-muted); }
.sf-bullet.rel-low .sf-marker { color: var(--fg-subtle); }
.sf-bullet .sf-text { flex: 1; min-width: 0; }
.digest-label { font-size: 10px; color: var(--fg-subtle); margin-top: 4px; letter-spacing: .04em; display: block; }
.sf-more-btn {
  background: transparent; border: 0; border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  color: var(--fg-muted); font-family: var(--font); font-size: 11px;
  padding: 7px 16px; cursor: pointer; display: flex; width: 100%;
  text-align: left; transition: background 120ms; align-items: center; gap: 6px;
}
.sf-more-btn:hover { background: var(--bg-hover); color: var(--fg); }
.sf-more-btn .sf-btn-icon { color: var(--accent); font-weight: 700; }
.sf-changes { display: none; }
.sf-changes.open { display: block; }

</style>
</head>
<body>

<header class="app">
  <div class="brand">
    <strong>DocTracker</strong>
    <button id="theme-toggle" aria-label="Toggle theme">☀</button>
  </div>
  <div class="meta">
    <span id="header-meta"></span>
    <a href="architecture.html" class="help-icon" data-theme-link aria-label="Cómo funciona DocTracker">?</a>
  </div>
</header>

<main>
  <div id="kpis" class="kpis"></div>
  <div class="va">
    <aside id="filters"></aside>
    <div>
      <div class="tl-controls">
        <div class="tl-group">
          <span class="tl-label">Window</span>
          <div class="seg" data-control="window">
            <button data-window="7">7d</button>
            <button data-window="30">30d</button>
            <button data-window="90">90d</button>
          </div>
        </div>
        <div class="tl-group">
          <span class="tl-label">Group by</span>
          <div class="seg" data-control="interval">
            <button data-interval="24">1d</button>
            <button data-interval="12">12h</button>
            <button data-interval="6">6h</button>
          </div>
        </div>
      </div>
      <div class="timeline" id="timeline"></div>
    </div>
  </div>
</main>

<footer class="app">
  <span id="footer-meta"></span>
  <a href="architecture.html" data-theme-link>¿cómo funciona esto? →</a>
</footer>

<script id="docstracker-data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("docstracker-data").textContent);

function fmtDate(iso) {
  const [y,m,d] = iso.split("-").map(Number);
  return new Date(y,m-1,d).toLocaleDateString("es-ES",{day:"numeric",month:"short"});
}
function fmtLong(iso) {
  const [y,m,d] = iso.split("-").map(Number);
  return new Date(y,m-1,d).toLocaleDateString("es-ES",{weekday:"long",day:"numeric",month:"long"});
}
function shortUrl(url) {
  try {
    const u = new URL(url);
    const parts = u.pathname.split("/").filter(Boolean);
    return parts.slice(-3).join("/") || u.hostname;
  } catch { return url; }
}
function pill(r) { return r ? `<span class="pill pill-${r}">${r}</span>` : `<span class="pill pill-none">–</span>`; }
function cat(c) { return c ? `<span class="cat cat-${c}">${c}</span>` : `<span class="cat cat-none">sin análisis</span>`; }
function esc(s) { return String(s).replace(/[&<>"]/g,x=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[x])); }

const runs = [...DATA.runs]
  .map(r => ({...r, timestamp: r.timestamp || (r.date + "T00:00:00")}))
  .sort((a,b)=>a.timestamp.localeCompare(b.timestamp));
const runsDesc = [...runs].reverse();
const latest = runsDesc[0] || {changes:[],date:"",timestamp:""};

const tlState = {
  windowDays: DATA.defaults?.windowDays ?? 30,
  intervalHours: DATA.defaults?.intervalHours ?? 24,
};

function bucketRuns(allRuns, windowDays, intervalHours) {
  if (!allRuns.length) return [];
  const sorted = [...allRuns].sort((a,b)=>a.timestamp.localeCompare(b.timestamp));
  const anchor = new Date(sorted[sorted.length-1].timestamp).getTime();
  const cutoff = anchor - windowDays * 86400000;
  const intervalMs = intervalHours * 3600000;
  const buckets = new Map();
  for (const r of [...sorted].reverse()) {
    const ts = new Date(r.timestamp).getTime();
    if (ts < cutoff) continue;
    const idx = Math.floor((anchor - ts) / intervalMs);
    const end = anchor - idx * intervalMs;
    const start = end - intervalMs;
    if (!buckets.has(idx)) buckets.set(idx, {idx, start, end, runs: []});
    buckets.get(idx).runs.push(r);
  }
  return [...buckets.values()].sort((a,b)=>a.idx - b.idx);
}
const allChanges = runs.flatMap(r=>r.changes.map(c=>({...c,date:r.date})));
const last7 = runs.slice(-7);
const totalLast7 = last7.reduce((s,r)=>s+r.changes.length,0);
const highLatest = latest.changes.filter(c=>c.relevance==="high").length;
const trackedPages = DATA.totalTrackedPages || Object.keys(DATA.pageHistory).length;
const pagesWithChanges = Object.keys(DATA.pageHistory).length;

document.getElementById("header-meta").innerHTML =
  latest.date ? `Último crawl: <strong>${fmtLong(latest.date)}</strong> · ${latest.changes.length} cambios` : "";

document.getElementById("footer-meta").textContent =
  `DocTracker · ${DATA.targets.length} watch targets · ${trackedPages} tracked pages`;

document.getElementById("kpis").innerHTML = `
  <div class="kpi"><div class="label">Último crawl</div><div class="value">${latest.date?fmtDate(latest.date):"—"}</div><div class="sub">${latest.changes.length} cambios</div></div>
  <div class="kpi"><div class="label">Cambios 7 días</div><div class="value">${totalLast7}</div><div class="sub">en ${last7.length} crawls</div></div>
  <div class="kpi"><div class="label">High (último crawl)</div><div class="value warn">${highLatest}</div><div class="sub">en el último crawl</div></div>
  <div class="kpi"><div class="label">Tracked pages</div><div class="value">${trackedPages}</div><div class="sub">${pagesWithChanges} con cambios</div></div>
  <div class="kpi"><div class="label">Watch Targets</div><div class="value">${DATA.targets.length}</div><div class="sub">activos</div></div>
`;

const tgtCounts={}, relCounts={high:0,medium:0,low:0,none:0}, catCounts={};
for (const c of allChanges) {
  tgtCounts[c.target_name]=(tgtCounts[c.target_name]||0)+1;
  const rk = c.relevance ?? "none";
  relCounts[rk]=(relCounts[rk]||0)+1;
  const ck = c.category ?? "none";
  catCounts[ck]=(catCounts[ck]||0)+1;
}

document.getElementById("filters").innerHTML = `
  <div class="group"><h3>Watch Target</h3>
    ${Object.entries(tgtCounts).map(([t,n])=>
      `<label><input type="checkbox" checked data-filter="target" value="${esc(t)}"> ${esc(t)}<span class="count">${n}</span></label>`).join("")}
  </div>
  <div class="group"><h3>Relevance</h3>
    ${["high","medium","low"].filter(r=>relCounts[r]>0).map(r=>
      `<label><input type="checkbox" checked data-filter="rel" value="${r}"> ${pill(r)}<span class="count">${relCounts[r]}</span></label>`).join("")}
    ${relCounts.none>0?`<label><input type="checkbox" checked data-filter="rel" value="none"> ${pill(null)}<span class="count">${relCounts.none}</span></label>`:""}
  </div>
  <div class="group"><h3>Category</h3>
    ${Object.entries(catCounts).filter(([c])=>c!=="none").sort((a,b)=>b[1]-a[1]).map(([c,n])=>
      `<label><input type="checkbox" checked data-filter="cat" value="${c}"> ${cat(c)}<span class="count">${n}</span></label>`).join("")}
    ${catCounts.none>0?`<label><input type="checkbox" checked data-filter="cat" value="none"> ${cat(null)}<span class="count">${catCounts.none}</span></label>`:""}
  </div>
`;

const active = {target:new Set(),rel:new Set(),cat:new Set()};
function syncFilters() {
  for (const k of Object.keys(active)) active[k].clear();
  document.querySelectorAll("input[data-filter]:checked").forEach(i=>active[i.dataset.filter].add(i.value));
}
syncFilters();
document.querySelectorAll("input[data-filter]").forEach(inp=>inp.addEventListener("change",()=>{syncFilters();renderTimeline();}));
function matches(c) {
  return active.target.has(c.target_name) && active.rel.has(c.relevance ?? "none") && active.cat.has(c.category ?? "none");
}

const GH_ICON = '<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>';
function renderRow(c) {
  const diff = c.diffUrl
    ? `<a class="diff-inline" href="${c.diffUrl}" target="_blank" rel="noopener">${GH_ICON} Ver diff en GitHub</a>`
    : "";
  return `<div class="change">
    <div>${pill(c.relevance)}</div>
    <div>${cat(c.category)}<div class="target-tag">${esc(c.target_name)}</div></div>
    <div>
      <a class="url" href="${c.page_url}" target="_blank" rel="noopener">${shortUrl(c.page_url)}</a>
      <div class="summary${c.summary==null?" no-analysis":""}">${c.summary!=null?esc(c.summary):'<em>análisis no disponible</em>'}</div>
      ${diff}
    </div>
  </div>`;
}

let sfSeq = 0;
function renderDigestBlock(digest, visible) {
  const rc = {high:0,medium:0,low:0};
  for (const c of visible) rc[c.relevance]++;
  const total = visible.length;
  const barH = Math.round(rc.high/total*100);
  const barM = Math.round(rc.medium/total*100);
  const barL = 100-barH-barM;
  const bullets = digest.map(b =>
    `<div class="sf-bullet rel-${b.rel}"><span class="sf-marker">${b.rel==="high"?"▸":"·"}</span><span class="sf-text">${esc(b.text)}</span></div>`
  ).join("");
  const id = "sfx-"+(++sfSeq);
  const moreLabel = `Ver ${visible.length} cambio${visible.length===1?"":"s"} completos`;
  return `<div class="sf-digest">
      <div class="sf-stats">
        <div class="sf-bar"><div class="bar-h" style="width:${barH}%"></div><div class="bar-m" style="width:${barM}%"></div><div class="bar-l" style="width:${barL}%"></div></div>
        ${rc.high>0?`<div class="sf-stat-row">${pill("high")} ${rc.high}</div>`:""}
        ${rc.medium>0?`<div class="sf-stat-row">${pill("medium")} ${rc.medium}</div>`:""}
        ${rc.low>0?`<div class="sf-stat-row">${pill("low")} ${rc.low}</div>`:""}
      </div>
      <div class="sf-bullets">${bullets}<span class="digest-label">✦ síntesis IA</span></div>
    </div>
    <button class="sf-more-btn" data-target="${id}" data-label="${moreLabel}" onclick="toggleSf(this)"><span class="sf-btn-icon">[+]</span> ${moreLabel}</button>
    <div class="sf-changes" id="${id}">${visible.map(renderRow).join("")}</div>`;
}
function toggleSf(btn) {
  const el = document.getElementById(btn.dataset.target);
  const open = el.classList.toggle("open");
  btn.querySelector(".sf-btn-icon").textContent = open ? "[-]" : "[+]";
  btn.querySelector(".sf-btn-icon").nextSibling.textContent = open ? " Colapsar cambios" : " "+btn.dataset.label;
}

function fmtBucketLabel(b, intervalHours) {
  const end = new Date(b.end);
  if (intervalHours >= 24) {
    return end.toLocaleDateString("es-ES",{weekday:"long",day:"numeric",month:"long"});
  }
  const start = new Date(b.start);
  const dateStr = end.toLocaleDateString("es-ES",{weekday:"short",day:"numeric",month:"short"});
  const sh = String(start.getHours()).padStart(2,"0");
  const eh = String(end.getHours()).padStart(2,"0");
  return `${dateStr} · ${sh}:00–${eh}:00`;
}

function renderTimeline() {
  sfSeq = 0;
  const buckets = bucketRuns(runs, tlState.windowDays, tlState.intervalHours);
  let firstSeen = false;
  const blocks = buckets.map(b => {
    const allVisible = b.runs.flatMap(r => r.changes.filter(matches));
    if (!allVisible.length) return "";
    const counts = {high:0,medium:0,low:0,none:0};
    for (const c of allVisible) counts[c.relevance ?? "none"]++;
    const labels = {high:"HIGH",medium:"MED",low:"LOW"};
    const relSum = ["high","medium","low"].filter(rk=>counts[rk]>0)
      .map(rk=>`<span class="pill pill-${rk}">${labels[rk]} ${counts[rk]}</span>`).join(" ");
    const totalChanges = b.runs.reduce((s,r)=>s+r.changes.length,0);
    const counter = allVisible.length===totalChanges
      ? `${allVisible.length} cambios` : `${allVisible.length} de ${totalChanges}`;
    const runsLine = b.runs.length > 1 ? ` · ${b.runs.length} runs` : "";
    const open = firstSeen ? "" : "open";
    firstSeen = true;
    const inner = b.runs.map(r => {
      const visible = r.changes.filter(matches);
      if (!visible.length) return "";
      return (r.digest && r.digest.length)
        ? renderDigestBlock(r.digest, visible)
        : visible.map(renderRow).join("");
    }).join("");
    return `<details class="day-block" ${open}>
      <summary class="day-header">
        <span>${fmtBucketLabel(b, tlState.intervalHours)}</span>
        <span class="day-count">· ${counter}${runsLine}</span>
        <span class="rel-summary">${relSum}</span>
      </summary>
      ${inner}
    </details>`;
  }).join("");
  document.getElementById("timeline").innerHTML =
    blocks || `<div class="empty">Sin cambios que coincidan con los filtros.</div>`;
}

function syncTlButtons() {
  document.querySelectorAll('[data-control="window"] button').forEach(btn => {
    btn.classList.toggle("on", +btn.dataset.window === tlState.windowDays);
  });
  document.querySelectorAll('[data-control="interval"] button').forEach(btn => {
    btn.classList.toggle("on", +btn.dataset.interval === tlState.intervalHours);
  });
}
document.querySelectorAll('[data-control="window"] button').forEach(btn => {
  btn.addEventListener("click", () => {
    tlState.windowDays = +btn.dataset.window;
    syncTlButtons(); renderTimeline();
  });
});
document.querySelectorAll('[data-control="interval"] button').forEach(btn => {
  btn.addEventListener("click", () => {
    tlState.intervalHours = +btn.dataset.interval;
    syncTlButtons(); renderTimeline();
  });
});
syncTlButtons();
renderTimeline();

// Theme
const url = new URL(window.location.href);
let theme = url.searchParams.get("theme");
if (theme !== "light" && theme !== "dark")
  theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
function themeHref(href, t) {
  const u = new URL(href, window.location.href);
  u.searchParams.set("theme", t);
  const file = u.pathname.slice(u.pathname.lastIndexOf("/") + 1) || u.pathname;
  return file + u.search + u.hash;
}
function syncThemeLinks(t) {
  document.querySelectorAll("[data-theme-link]").forEach(a => {
    a.setAttribute("href", themeHref(a.getAttribute("href"), t));
  });
}
function applyTheme(t) {
  theme = t;
  document.documentElement.setAttribute("data-theme", t);
  document.getElementById("theme-toggle").textContent = t === "dark" ? "☀" : "☾";
  syncThemeLinks(t);
  const u = new URL(window.location.href);
  u.searchParams.set("theme", t);
  window.history.replaceState({}, "", u);
}
document.getElementById("theme-toggle").addEventListener("click", ()=>applyTheme(theme==="dark"?"light":"dark"));
applyTheme(theme);
</script>
</body>
</html>"""


def _render_html(data: dict) -> str:
    safe_json = json.dumps(data).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", safe_json)


def generate_site(analyses_dir: str, config_path: str, output_path: str, snapshots_dir: str | None = None, run_analyses_dir: str | None = None) -> None:
    config_dir = os.path.dirname(os.path.abspath(config_path))
    repo = _repo_from_git(config_dir)
    commits = _commits_by_date(config_dir)
    data = _build_data(analyses_dir, config_path, commits, repo, snapshots_dir=snapshots_dir, run_analyses_dir=run_analyses_dir)
    html = _render_html(data)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
