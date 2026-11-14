"""Evidence-backed HTML report + GeoJSON export for a published finding.

The report shows the five score concepts *separately* and states plainly that
the detection confidence is a heuristic ranking score, never a probability.
"""
from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional

from app.core.geo import bbox_to_polygon

DISCLAIMER = (
    "TerraTrace AI reports candidate changes derived from real satellite "
    "observations. Detection confidence is a heuristic ranking score (0–1), not a "
    "probability that the interpretation is correct. Evidence completeness, data "
    "quality and severity are separate concepts and must not be combined into a "
    "single accuracy figure. Field or independent-source verification is required "
    "before acting on a candidate finding."
)

_CSS = """
:root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --bg:#f8fafc; --card:#fff;
        --accent:#0f766e; --warn:#b45309; --bad:#b91c1c; }
* { box-sizing:border-box; }
body { font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       color:var(--ink); background:var(--bg); margin:0; padding:32px; }
.wrap { max-width:960px; margin:0 auto; }
header { border-bottom:3px solid var(--accent); padding-bottom:16px; margin-bottom:24px; }
h1 { font-size:26px; margin:0 0 6px; } h2 { font-size:17px; margin:28px 0 10px;
       text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }
.sub { color:var(--muted); font-size:14px; }
.badge { display:inline-block; padding:3px 10px; border-radius:999px; font-size:12px;
       font-weight:600; background:#ecfdf5; color:#065f46; border:1px solid #a7f3d0; }
.badge.warn { background:#fffbeb; color:#92400e; border-color:#fde68a; }
.badge.bad { background:#fef2f2; color:#991b1b; border-color:#fecaca; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.metric b { font-size:22px; display:block; margin-top:4px; }
.bar { height:7px; background:#e2e8f0; border-radius:99px; overflow:hidden; margin-top:8px; }
.bar i { display:block; height:100%; background:var(--accent); }
ul { margin:8px 0; padding-left:20px; } li { margin:4px 0; font-size:14px; }
table { width:100%; border-collapse:collapse; font-size:14px; background:var(--card); }
td, th { border:1px solid var(--line); padding:7px 10px; text-align:left; }
th { background:#f1f5f9; font-weight:600; }
.imgs { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }
.imgs figure { margin:0; } .imgs img { width:100%; border:1px solid var(--line);
       border-radius:8px; background:#0b1220; } .imgs figcaption { font-size:12px;
       color:var(--muted); margin-top:5px; }
.note { background:#fffbeb; border:1px solid #fde68a; color:#78350f; padding:12px 14px;
       border-radius:8px; font-size:13px; line-height:1.55; }
.kv { font-size:14px; } .kv div { display:flex; justify-content:space-between;
       padding:6px 0; border-bottom:1px dashed var(--line); }
footer { margin-top:36px; padding-top:16px; border-top:1px solid var(--line);
       color:var(--muted); font-size:12px; line-height:1.6; }
code { background:#f1f5f9; padding:1px 5px; border-radius:4px; font-size:12px; }
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _bar(label: str, value: Any, hint: str) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    pct = max(0.0, min(100.0, v * 100.0))
    return (
        f'<div class="card metric"><span class="sub">{_esc(label)}</span>'
        f'<b>{v:.2f}</b><div class="bar"><i style="width:{pct:.0f}%"></i></div>'
        f'<span class="sub">{_esc(hint)}</span></div>'
    )


def _badge(status: str) -> str:
    cls = ""
    if status in ("requires_verification", "under_investigation"):
        cls = " warn"
    elif status in ("insufficient_data", "rejected_poor_quality"):
        cls = " bad"
    return f'<span class="badge{cls}">{_esc(status)}</span>'


def render_report(
    finding: Dict[str, Any],
    evidence: Optional[Dict[str, Any]] = None,
    *,
    agent: Optional[Dict[str, Any]] = None,
    job: Optional[Dict[str, Any]] = None,
    observations: Optional[List[Dict[str, Any]]] = None,
    base_url: str = "",
) -> str:
    """Render a self-contained HTML report for one finding."""
    evidence = evidence or {}
    measurements = evidence.get("measurements") or {}
    supporting = evidence.get("supporting") or []
    conflicting = evidence.get("conflicting") or []
    limitations = evidence.get("limitations") or []
    persistence = evidence.get("persistence") or {}
    context = evidence.get("context_datasets") or []
    assets = finding.get("assets") or {}
    location = finding.get("location") or {}

    score_row = (
        _bar("Detection confidence (heuristic)", finding.get("detection_confidence"),
             "signal ranking 0–1, not a probability")
        + _bar("Evidence completeness", finding.get("evidence_completeness"),
               "how much expected evidence is present")
        + _bar("Data quality", finding.get("data_quality"), "input raster quality for this run")
        + _bar("Severity", {"low": 0.25, "moderate": 0.5, "high": 0.9}.get(
            finding.get("severity"), 0.0), f"class: {_esc(finding.get('severity'))}")
    )

    measure_rows = "".join(
        f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>"
        for k, v in measurements.items()
    ) or "<tr><td colspan='2' class='sub'>No measurements recorded.</td></tr>"

    support_items = "".join(f"<li>{_esc(s)}</li>" for s in supporting) or "<li class='sub'>None.</li>"
    conflict_items = "".join(f"<li>{_esc(s)}</li>" for s in conflicting) or "<li class='sub'>None recorded.</li>"
    limit_items = "".join(f"<li>{_esc(s)}</li>" for s in limitations) or "<li class='sub'>None.</li>"

    dataset_items = "".join(
        f"<li><code>{_esc(d.get('id'))}</code> — {_esc(d.get('status'))}: {_esc(d.get('note'))}</li>"
        for d in context
    ) or "<li class='sub'>No contextual dataset attached.</li>"

    img_blocks = []
    for key, caption in (("before_png", "Before observation (SAR backscatter)"),
                         ("after_png", "After observation (SAR backscatter)"),
                         ("change_png", "Derived change mask (amber = flagged)")):
        url = assets.get(key)
        if url:
            img_blocks.append(
                f'<figure><img src="{_esc(base_url + url)}" alt="{_esc(caption)}" loading="lazy">'
                f"<figcaption>{_esc(caption)}</figcaption></figure>"
            )
    imgs = f'<div class="imgs">{"".join(img_blocks)}</div>' if img_blocks else ""

    sources = finding.get("sources") or []
    source_rows = "".join(
        f"<tr><td>{_esc(s.get('mission'))}</td><td>{_esc(s.get('product_type'))}</td>"
        f"<td>{_esc(s.get('source'))}</td><td><code>{_esc(s.get('provider_id'))}</code></td></tr>"
        for s in sources
    ) or "<tr><td colspan='4' class='sub'>No source recorded.</td></tr>"

    dates = finding.get("observation_dates") or []
    date_list = "".join(f"<li>{_esc(d)}</li>" for d in dates) or "<li class='sub'>None.</li>"

    geojson_link = f'{base_url}/api/findings/{finding.get("id")}/export.geojson'
    obs_rows = "".join(
        f"<tr><td>{_esc(o.get('mission'))}</td><td>{_esc(o.get('product_type'))}</td>"
        f"<td>{_esc((o.get('datetime') or '')[:19])}</td>"
        f"<td>{'credentials required' if o.get('requires_credentials') else 'anonymous'}</td></tr>"
        for o in (observations or [])
    ) or "<tr><td colspan='4' class='sub'>Observations are attached to the analysis job.</td></tr>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TerraTrace report — {_esc(finding.get('title'))}</title>
<style>{_CSS}</style></head><body><div class="wrap">
<header>
  <div class="sub">TerraTrace AI · evidence report · {_esc(finding.get('id'))}</div>
  <h1>{_esc(finding.get('title'))}</h1>
  <div class="sub">
    {_badge(finding.get('verification_status'))}
    <span class="badge">{_esc(finding.get('category'))}</span>
    <span class="badge">{_esc(finding.get('agent_id'))}</span>
    <span>created {_esc(finding.get('created_at'))}</span>
  </div>
</header>

<h2>The five score concepts, kept separate</h2>
<div class="grid">{score_row}</div>

<h2>What was observed</h2>
<div class="card kv">
  <div><span>Location</span><span>{_esc(location.get('name')) or 'bbox ' + _esc(location.get('bbox'))}</span></div>
  <div><span>Centroid</span><span>{_esc(location.get('centroid'))}</span></div>
  <div><span>Mapped area</span><span>{_esc(finding.get('area_km2'))} km²</span></div>
  <div><span>First observed</span><span>{_esc(finding.get('first_observed'))}</span></div>
  <div><span>Persistence</span><span>{_esc(persistence.get('days_between'))} days between
      {'dates' if persistence.get('persistent') else 'the supporting dates'}</span></div>
  <div><span>Method</span><span>{_esc(finding.get('method'))} · {_esc(finding.get('model_version'))}</span></div>
</div>
<p class="note">{_esc(evidence.get('summary'))}</p>

<h2>Explanation</h2>
<div class="card"><p style="font-size:14px;line-height:1.6;margin:0">{_esc(finding.get('explanation'))}</p></div>

<h2>Quantitative measurements</h2>
<table><tbody>{measure_rows}</tbody></table>

<h2>Supporting evidence</h2>
<ul>{support_items}</ul>

<h2>Conflicting evidence / caveats</h2>
<ul>{conflict_items}</ul>

<h2>Uncertainty</h2>
<div class="card"><p style="font-size:14px;line-height:1.6;margin:0">{_esc(evidence.get('uncertainty'))}</p></div>

<h2>Known limitations</h2>
<ul>{limit_items}</ul>

<h2>Observation dates</h2>
<ul>{date_list}</ul>

<h2>Source observations</h2>
<table><thead><tr><th>Mission</th><th>Product</th><th>Source</th><th>Provider id</th></tr></thead>
<tbody>{source_rows}</tbody></table>
<table style="margin-top:12px"><thead><tr><th>Mission</th><th>Product</th><th>Acquired</th><th>Access</th></tr></thead>
<tbody>{obs_rows}</tbody></table>

<h2>Context datasets</h2>
<ul>{dataset_items}</ul>

<h2>Derived imagery</h2>
{imgs or '<p class="sub">No imagery artifacts were written for this run.</p>'}

<h2>Provenance</h2>
<div class="card kv">
  <div><span>Finding id</span><span><code>{_esc(finding.get('id'))}</code></span></div>
  <div><span>Agent</span><span>{_esc((agent or {}).get('name'))} ({_esc(finding.get('agent_id'))})</span></div>
  <div><span>Agent status</span><span>{_esc((agent or {}).get('status'))}</span></div>
  <div><span>Job</span><span><code>{_esc((job or {}).get('id'))}</code>
      ({_esc((job or {}).get('status'))})</span></div>
  <div><span>GeoJSON</span><span><a href="{_esc(geojson_link)}">{_esc(geojson_link)}</a></span></div>
</div>

<footer>{_esc(DISCLAIMER)}</footer>
</div></body></html>"""


def finding_geojson(finding: Dict[str, Any], evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """GeoJSON Feature (or FeatureCollection) for one finding."""
    evidence = evidence or {}
    geom = finding.get("geometry")
    if not geom:
        bbox = finding.get("bbox") or []
        geom = bbox_to_polygon(bbox) if len(bbox) == 4 else None
    props = {
        "id": finding.get("id"),
        "title": finding.get("title"),
        "category": finding.get("category"),
        "agent_id": finding.get("agent_id"),
        "job_id": finding.get("job_id"),
        "verification_status": finding.get("verification_status"),
        "severity": finding.get("severity"),
        "detection_confidence_heuristic": finding.get("detection_confidence"),
        "evidence_completeness": finding.get("evidence_completeness"),
        "data_quality": finding.get("data_quality"),
        "area_km2": finding.get("area_km2"),
        "observation_dates": finding.get("observation_dates"),
        "sources": finding.get("sources"),
        "method": finding.get("method"),
        "model_version": finding.get("model_version"),
        "first_observed": finding.get("first_observed"),
        "created_at": finding.get("created_at"),
        "explanation": finding.get("explanation"),
        "evidence_summary": evidence.get("summary"),
        "measurements": evidence.get("measurements"),
        "supporting": evidence.get("supporting"),
        "conflicting": evidence.get("conflicting"),
        "limitations": evidence.get("limitations"),
        "uncertainty": evidence.get("uncertainty"),
        "persistence": evidence.get("persistence"),
        "crs": "EPSG:4326",
        "note": "detection_confidence_heuristic is a 0-1 ranking score, not a probability",
    }
    return {
        "type": "Feature",
        "id": finding.get("id"),
        "properties": props,
        "geometry": geom,
    }
