#!/usr/bin/env python3
"""
shelly_power_analyzer.py

Generate a rich HTML report from a JSON file shaped like:
{
  "<service_name>": [
    {"ts": "...", "cpu_cores_used": 0.12, "cpu_percent_host": 3.4, "estimated_power_from_shelly_watt": 1.2},
    ...
  ],
  ...
}

The report is meant to be:
- callable from other Python code (e.g., run_experiment)
- runnable from terminal for testing
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


# -----------------------------
# Configuration
# -----------------------------

DEFAULT_TECH_STACK_PATTERNS: Tuple[str, ...] = (
    r"^cadvisor$",
    r"^prometheus$",
    r"^grafana$",
    r"^alertmanager$",
    r"^node[-_]?exporter$",
    r"^otel[-_]?collector$",
    r"^opentelemetry[-_]?collector$",
    r"^jaeger.*",
    r"^tempo$",
    r"^loki$",
    r"^kibana$",
    r"^elasticsearch$",
    r"^logstash$",
    r"^zipkin$",
    r"^redis$",
    r"^rabbitmq$",
    r"^kafka$",
    r"^zookeeper$",
    r"^postgres.*",
    r"^mysql.*",
    r"^mongo.*",
)


# -----------------------------
# Data structures
# -----------------------------

@dataclass(frozen=True)
class ServiceStats:
    name: str
    n_samples: int
    first_ts: pd.Timestamp
    last_ts: pd.Timestamp
    duration_s: float
    avg_power_w: float
    p95_power_w: float
    max_power_w: float
    energy_wh: float
    avg_cpu_cores: float
    p95_cpu_cores: float
    max_cpu_cores: float


# -----------------------------
# Utilities
# -----------------------------

def _parse_ts(series: pd.Series) -> pd.Series:
    # Pandas handles ISO 8601 with timezone offsets well.
    # We keep it timezone-aware to avoid subtle alignment bugs.
    return pd.to_datetime(series, utc=True, errors="coerce")


def _safe_float(x: object) -> float:
    try:
        if x is None:
            return float("nan")
        return float(x)
    except Exception:
        return float("nan")


def _median_dt_seconds(ts: pd.Series) -> float:
    """Median sampling interval, in seconds."""
    if len(ts) < 3:
        return float("nan")
    d = ts.sort_values().diff().dt.total_seconds().dropna()
    if d.empty:
        return float("nan")
    return float(d.median())


def _integrate_energy_wh(df: pd.DataFrame, power_col: str) -> float:
    """
    Approximate energy (Wh) by integrating power over time:
      Wh = Σ (P_i * Δt_i_hours)

    For the last sample, we use the median Δt of the series (or 0 if unknown).
    """
    if df.empty:
        return 0.0

    df = df.sort_values("ts").reset_index(drop=True)
    ts = df["ts"]
    p = df[power_col].astype(float)

    dts = ts.diff().dt.total_seconds().fillna(0.0)
    median_dt = _median_dt_seconds(ts)
    if math.isnan(median_dt) or median_dt <= 0:
        median_dt = 0.0

    # Replace last delta (0) with median for a better tail approximation.
    if len(dts) >= 2:
        dts.iloc[-1] = median_dt

    wh = float((p * (dts / 3600.0)).sum(skipna=True))
    return max(0.0, wh)


def _human_duration(seconds: float) -> str:
    if seconds <= 0:
        return "0s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s and not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


def _is_tech_stack(name: str, patterns: Sequence[str]) -> bool:
    return any(re.search(p, name, flags=re.IGNORECASE) for p in patterns)


def _to_json(o: object) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


# -----------------------------
# Loading and preparation
# -----------------------------

def load_shelly_attributed_timeseries(path: Path) -> Dict[str, pd.DataFrame]:
    """
    Load the JSON file into a dict of DataFrames keyed by service name.
    Expected schema per row:
      ts, cpu_cores_used, cpu_percent_host, estimated_power_from_shelly_watt
    """
    raw = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise ValueError("Input JSON must be an object (dict) keyed by microservice name.")

    out: Dict[str, pd.DataFrame] = {}
    for svc, rows in raw.items():
        if not isinstance(rows, list):
            continue

        df = pd.DataFrame(rows)
        if df.empty:
            continue

        # Normalize columns, tolerate missing fields.
        if "ts" not in df.columns:
            continue

        df["ts"] = _parse_ts(df["ts"])
        df = df.dropna(subset=["ts"])

        for col in ("cpu_cores_used", "cpu_percent_host", "estimated_power_from_shelly_watt"):
            if col not in df.columns:
                df[col] = float("nan")
            df[col] = df[col].map(_safe_float).astype(float)

        df = df.sort_values("ts").drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)
        out[str(svc)] = df

    if not out:
        raise ValueError("No valid services found in the input JSON.")
    return out


def compute_service_stats(services: Dict[str, pd.DataFrame]) -> List[ServiceStats]:
    stats: List[ServiceStats] = []
    for name, df in services.items():
        if df.empty:
            continue
        first_ts = df["ts"].iloc[0]
        last_ts = df["ts"].iloc[-1]
        duration_s = float((last_ts - first_ts).total_seconds())

        p = df["estimated_power_from_shelly_watt"].astype(float)
        c = df["cpu_cores_used"].astype(float)

        energy_wh = _integrate_energy_wh(df, "estimated_power_from_shelly_watt")

        stats.append(
            ServiceStats(
                name=name,
                n_samples=int(len(df)),
                first_ts=first_ts,
                last_ts=last_ts,
                duration_s=duration_s,
                avg_power_w=float(p.mean(skipna=True)) if len(p) else 0.0,
                p95_power_w=float(p.quantile(0.95)) if len(p) else 0.0,
                max_power_w=float(p.max(skipna=True)) if len(p) else 0.0,
                energy_wh=float(energy_wh),
                avg_cpu_cores=float(c.mean(skipna=True)) if len(c) else 0.0,
                p95_cpu_cores=float(c.quantile(0.95)) if len(c) else 0.0,
                max_cpu_cores=float(c.max(skipna=True)) if len(c) else 0.0,
            )
        )
    stats.sort(key=lambda s: s.energy_wh, reverse=True)
    return stats


def resample_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """
    Hourly summary (UTC):
      - mean_power_w
      - mean_cpu_cores
      - energy_wh (hourly, integrated)
    """
    if df.empty:
        return df.copy()

    d = df.set_index("ts").sort_index()
    hourly = pd.DataFrame(
        {
            "mean_power_w": d["estimated_power_from_shelly_watt"].resample("1h").mean(),
            "mean_cpu_cores": d["cpu_cores_used"].resample("1h").mean(),
        }
    ).dropna(how="all")

    # Hourly energy: integrate within each hour bucket.
    # We do it by computing dt per sample, then summing within each resampled hour.
    d2 = d[["estimated_power_from_shelly_watt"]].copy()
    d2["dt_s"] = d2.index.to_series().diff().dt.total_seconds().fillna(0.0)
    median_dt = _median_dt_seconds(d2.index.to_series())
    if not math.isnan(median_dt) and median_dt > 0 and len(d2) >= 2:
        d2.iloc[-1, d2.columns.get_loc("dt_s")] = median_dt
    d2["wh"] = d2["estimated_power_from_shelly_watt"] * (d2["dt_s"] / 3600.0)
    hourly["energy_wh"] = d2["wh"].resample("1h").sum().reindex(hourly.index)
    hourly = hourly.reset_index().rename(columns={"ts": "hour"})
    hourly["hour"] = hourly["hour"].dt.tz_convert("UTC")
    return hourly


# -----------------------------
# HTML generation (Plotly)
# -----------------------------

def _plotly_div(div_id: str) -> str:
    return f'<div id="{div_id}" class="plotly-chart"></div>'


def _plotly_script(div_id: str, fig: dict) -> str:
    # We keep figures as plain dicts so Plotly can render them client-side.
    return f"""
<script>
(function() {{
  const fig = {_to_json(fig)};
  Plotly.newPlot("{div_id}", fig.data, fig.layout, {{responsive:true, displaylogo:false}});
}})();
</script>
""".strip()


def _line_fig(
    x: List[str],
    y: List[float],
    name: str,
    y_title: str,
    title: str,
) -> dict:
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "x": x,
                "y": y,
                "name": name,
                "hovertemplate": "%{x}<br>%{y:.4f}<extra></extra>",
            }
        ],
        "layout": {
            "title": {"text": title, "x": 0.01, "xanchor": "left"},
            "margin": {"l": 55, "r": 18, "t": 45, "b": 45},
            "xaxis": {"title": "Time (UTC)", "type": "date", "showgrid": True, "zeroline": False},
            "yaxis": {"title": y_title, "showgrid": True, "zeroline": False},
            "hovermode": "x unified",
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
        },
    }


def _bar_fig(
    x: List[str],
    y: List[float],
    y_title: str,
    title: str,
    horizontal: bool = True,
) -> dict:
    if horizontal:
        return {
            "data": [
                {"type": "bar", "x": y, "y": x, "orientation": "h", "hovertemplate": "%{y}<br>%{x:.4f}<extra></extra>"}
            ],
            "layout": {
                "title": {"text": title, "x": 0.01, "xanchor": "left"},
                "margin": {"l": 160, "r": 18, "t": 45, "b": 45},
                "xaxis": {"title": y_title, "showgrid": True, "zeroline": False},
                "yaxis": {"title": "", "showgrid": False, "zeroline": False},
                "paper_bgcolor": "rgba(0,0,0,0)",
                "plot_bgcolor": "rgba(0,0,0,0)",
            },
        }

    return {
        "data": [{"type": "bar", "x": x, "y": y, "hovertemplate": "%{x}<br>%{y:.4f}<extra></extra>"}],
        "layout": {
            "title": {"text": title, "x": 0.01, "xanchor": "left"},
            "margin": {"l": 55, "r": 18, "t": 45, "b": 45},
            "xaxis": {"title": "", "showgrid": False, "zeroline": False},
            "yaxis": {"title": y_title, "showgrid": True, "zeroline": False},
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
        },
    }


def _scatter_fig(x: List[float], y: List[float], title: str) -> dict:
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "x": x,
                "y": y,
                "hovertemplate": "cpu_cores=%{x:.4f}<br>power_w=%{y:.4f}<extra></extra>",
            }
        ],
        "layout": {
            "title": {"text": title, "x": 0.01, "xanchor": "left"},
            "margin": {"l": 55, "r": 18, "t": 45, "b": 45},
            "xaxis": {"title": "cpu_cores_used", "showgrid": True, "zeroline": False},
            "yaxis": {"title": "estimated_power_from_shelly_watt (W)", "showgrid": True, "zeroline": False},
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
        },
    }


def _stacked_area_fig(series_by_service: Dict[str, pd.Series], title: str) -> dict:
    data = []
    for svc, s in series_by_service.items():
        data.append(
            {
                "type": "scatter",
                "mode": "lines",
                "x": [t.isoformat() for t in s.index],
                "y": [float(v) if v == v else None for v in s.values],
                "name": svc,
               # "stackgroup": "one",
                "hovertemplate": "%{x}<br>%{y:.4f}<extra></extra>",
            }
        )
    return {
        "data": data,
        "layout": {
            "title": {"text": title, "x": 0.01, "xanchor": "left"},
            "margin": {"l": 55, "r": 18, "t": 45, "b": 45},
            "xaxis": {"title": "Time (UTC)", "type": "date", "showgrid": True, "zeroline": False},
            "yaxis": {"title": "estimated_power_from_shelly_watt (W)", "showgrid": True, "zeroline": False},
            "hovermode": "x unified",
            "legend": {"orientation": "h"},
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
        },
    }


def build_html_report(
    services: Dict[str, pd.DataFrame],
    *,
    input_path: Path,
    tech_stack_patterns: Sequence[str],
    title: str = "Shelly power attribution report",
    top_n: int = 8,
) -> str:
    stats = compute_service_stats(services)

    # Identify most impactful non-tech microservice.
    non_tech = [s for s in stats if not _is_tech_stack(s.name, tech_stack_patterns)]
    most_impactful = non_tech[0] if non_tech else (stats[0] if stats else None)

    # Global time window.
    global_first = min(s.first_ts for s in stats)
    global_last = max(s.last_ts for s in stats)
    global_duration = _human_duration(float((global_last - global_first).total_seconds()))

    # Summary charts (energy and avg power).
    names = [s.name for s in stats]
    energy = [s.energy_wh for s in stats]
    avg_power = [s.avg_power_w for s in stats]

    # Stacked area for top services by energy (hourly mean power).

    #Uncomment to show all services in stacked area chart
    #top_services = [s.name for s in stats[:top_n]] 
    top_services = [
        s.name
        for s in stats
        if not _is_tech_stack(s.name, tech_stack_patterns)
    ][:top_n]
    

    # Global experiment time axis (real experiment duration)
    global_start = min(df["ts"].min() for df in services.values())
    global_end = max(df["ts"].max() for df in services.values())

    # Build a global timeline using all timestamps observed
    global_time_index = (
        pd.Index(
            sorted(
                set().union(
                    *[services[svc]["ts"].tolist() for svc in top_services if svc in services]
                )
            )
        )
        .tz_convert("UTC")
    )

    hourly_series: Dict[str, pd.Series] = {}

    for svc in top_services:
        df = services[svc]
        if df.empty:
            continue

        # Power time series aligned to the global experiment timeline
        series = (
            df.set_index("ts")["estimated_power_from_shelly_watt"]
            .reindex(global_time_index, fill_value=0.0)
        )

        hourly_series[svc] = series


    # Scatter (global) cpu vs power.
    all_cpu = []
    all_pow = []
    for df in services.values():
        d = df[["cpu_cores_used", "estimated_power_from_shelly_watt"]].dropna()
        all_cpu.extend(d["cpu_cores_used"].astype(float).tolist())
        all_pow.extend(d["estimated_power_from_shelly_watt"].astype(float).tolist())

    figs: Dict[str, dict] = {}

    figs["bar_energy"] = _bar_fig(
        x=names[:40],
        y=energy[:40],
        y_title="Energy (Wh)",
        title="Total energy by microservice (top 40)",
        horizontal=True,
    )
    figs["bar_avg_power"] = _bar_fig(
        x=names[:40],
        y=avg_power[:40],
        y_title="Average power (W)",
        title="Average power by microservice (top 40)",
        horizontal=True,
    )
    if hourly_series:
        figs["stacked_top"] = _stacked_area_fig(hourly_series, f"Stacked estimated power over experiment duration (top services)")

    if all_cpu and all_pow:
        figs["scatter_cpu_pow"] = _scatter_fig(all_cpu, all_pow, "CPU cores vs estimated power (all samples)")

    # Service-specific figures.
    service_sections: List[str] = []
    for s in stats:
        df = services[s.name]
        x = [t.isoformat() for t in df["ts"].tolist()]
        y_pow = [float(v) if v == v else None for v in df["estimated_power_from_shelly_watt"].tolist()]
        y_cpu = [float(v) if v == v else None for v in df["cpu_cores_used"].tolist()]

        div_pow = f"svc_pow_{re.sub(r'[^a-zA-Z0-9_]', '_', s.name)}"
        div_cpu = f"svc_cpu_{re.sub(r'[^a-zA-Z0-9_]', '_', s.name)}"

        pow_fig = _line_fig(
            x=x,
            y=y_pow,
            name="estimated_power_from_shelly_watt",
            y_title="Estimated power (W)",
            title=f"{s.name} — estimated power over time",
        )
        cpu_fig = _line_fig(
            x=x,
            y=y_cpu,
            name="cpu_cores_used",
            y_title="CPU cores used",
            title=f"{s.name} — CPU cores used over time",
        )

        badge = "TECH STACK" if _is_tech_stack(s.name, tech_stack_patterns) else "SUT"
        service_sections.append(
            f"""
<section class="card service-card" data-service="{s.name.lower()}" data-badge="{badge}">
  <div class="card-header">
    <div class="card-title-row">
      <h3 class="card-title">{s.name}</h3>
      <span class="badge {'badge-stack' if badge=='TECH STACK' else 'badge-sut'}">{badge}</span>
    </div>
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">Energy</div><div class="kpi-value">{s.energy_wh:.3f} Wh</div></div>
      <div class="kpi"><div class="kpi-label">Avg power</div><div class="kpi-value">{s.avg_power_w:.3f} W</div></div>
      <div class="kpi"><div class="kpi-label">P95 power</div><div class="kpi-value">{s.p95_power_w:.3f} W</div></div>
      <div class="kpi"><div class="kpi-label">Max power</div><div class="kpi-value">{s.max_power_w:.3f} W</div></div>
      <div class="kpi"><div class="kpi-label">Avg CPU</div><div class="kpi-value">{s.avg_cpu_cores:.3f} cores</div></div>
      <div class="kpi"><div class="kpi-label">P95 CPU</div><div class="kpi-value">{s.p95_cpu_cores:.3f} cores</div></div>
      <div class="kpi"><div class="kpi-label">Max CPU</div><div class="kpi-value">{s.max_cpu_cores:.3f} cores</div></div>
      <div class="kpi"><div class="kpi-label">Samples</div><div class="kpi-value">{s.n_samples}</div></div>
    </div>
  </div>

  <div class="card-body">
    <div class="chart-wrap">
      {_plotly_div(div_pow)}
    </div>

    <div style="height: 16px;"></div>
    
    <div class="chart-wrap">
      {_plotly_div(div_cpu)}
    </div>
  </div>
</section>
""".strip()
            )

        figs[div_pow] = pow_fig
        figs[div_cpu] = cpu_fig

    # “Most impactful” analysis section.
    impactful_html = ""
    if most_impactful is not None:
        svc = most_impactful.name
        df = services[svc]
        hourly = resample_hourly(df)
        top_hour = None
        if not hourly.empty and "energy_wh" in hourly.columns:
            hh = hourly.sort_values("energy_wh", ascending=False).head(1)
            if not hh.empty:
                top_hour = (hh.iloc[0]["hour"], float(hh.iloc[0]["energy_wh"]))

        impactful_html = f"""
<section class="card">
  <div class="card-header">
    <h2 class="card-title">Most impactful microservice (excluding technology stack)</h2>
    <p class="muted">
      Selected as the highest total energy consumer among services not matching the tech-stack patterns.
    </p>
  </div>

  <div class="card-body">
    <div class="hero">
      <div>
        <div class="hero-title">{svc}</div>
        <div class="hero-subtitle">Energy: <b>{most_impactful.energy_wh:.3f} Wh</b> · Avg power: <b>{most_impactful.avg_power_w:.3f} W</b> · Avg CPU: <b>{most_impactful.avg_cpu_cores:.3f} cores</b></div>
      </div>
      <div class="hero-meta">
        <div><span class="muted">Samples</span> <b>{most_impactful.n_samples}</b></div>
        <div><span class="muted">Window</span> <b>{most_impactful.first_ts.isoformat()} → {most_impactful.last_ts.isoformat()}</b></div>
      </div>
    </div>

    <div class="callouts grid-3">
      <div class="callout">
        <div class="callout-title">Interpretation</div>
        <div class="callout-body">
          This service is the best candidate for optimization because it contributes the largest share of the
          estimated energy attributed from the Shelly measurements.
        </div>
      </div>
      <div class="callout">
        <div class="callout-title">Peak behavior</div>
        <div class="callout-body">
          P95 power: <b>{most_impactful.p95_power_w:.3f} W</b> · Max power: <b>{most_impactful.max_power_w:.3f} W</b><br/>
          P95 CPU: <b>{most_impactful.p95_cpu_cores:.3f} cores</b> · Max CPU: <b>{most_impactful.max_cpu_cores:.3f} cores</b>
        </div>
      </div>
      <div class="callout">
        <div class="callout-title">Highest-energy hour</div>
        <div class="callout-body">
          {("Hour starting at <b>%s</b>: <b>%.3f Wh</b> (integrated)" % (top_hour[0].isoformat(), top_hour[1])) if top_hour else "Not enough data to compute hourly energy."}
        </div>
      </div>
    </div>
  </div>
</section>
""".strip()

    # HTML skeleton.
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title}</title>

  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>

  <style>
    :root {{
      --bg: #0b1020;
      --card: rgba(255,255,255,0.06);
      --card2: rgba(255,255,255,0.08);
      --text: rgba(255,255,255,0.92);
      --muted: rgba(255,255,255,0.65);
      --border: rgba(255,255,255,0.10);
      --shadow: 0 10px 30px rgba(0,0,0,0.35);
      --radius: 18px;
    }}

    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; }}
    body {{
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(1000px 700px at 15% 10%, rgba(124, 58, 237, 0.18), transparent 60%),
        radial-gradient(900px 700px at 80% 25%, rgba(59, 130, 246, 0.16), transparent 60%),
        radial-gradient(900px 700px at 55% 90%, rgba(34, 197, 94, 0.10), transparent 60%),
        var(--bg);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
      line-height: 1.45;
    }}

    a {{ color: inherit; }}

    .container {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 28px 18px 80px 18px;
    }}

    .title {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 16px;
    }}

    .title h1 {{
      margin: 0;
      font-size: 28px;
      letter-spacing: 0.2px;
    }}

    .subtitle {{
      margin: 6px 0 0 0;
      color: var(--muted);
      font-size: 14px;
    }}

    .topbar {{
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 10px;
      align-items: center;
      margin: 18px 0 26px 0;
    }}

    .search {{
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(0,0,0,0.20);
      color: var(--text);
      outline: none;
    }}

    .toggle {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(0,0,0,0.20);
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }}

    .toggle input {{
      accent-color: #a78bfa;
    }}

    .btn {{
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.08);
      color: var(--text);
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }}

    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
      margin: 14px 0;
    }}

    .card-header {{
      padding: 16px 16px 10px 16px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      background: linear-gradient(180deg, rgba(255,255,255,0.05), transparent);
    }}

    .card-title {{
      margin: 0;
      font-size: 18px;
    }}

    .card-body {{
      padding: 14px 16px 16px 16px;
    }}

    .muted {{ color: var(--muted); }}

    .grid-2 {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }}
    @media (min-width: 980px) {{
      .grid-2 {{ grid-template-columns: 1fr 1fr; }}
    }}

    .grid-3 {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }}
    @media (min-width: 980px) {{
      .grid-3 {{ grid-template-columns: 1fr 1fr 1fr; }}
    }}

    .plotly-chart {{
      width: 100%;
      min-height: 360px;
    }}

    .chart-wrap {{
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 16px;
      background: rgba(0,0,0,0.18);
      overflow-x: auto; /* allow lateral scroll if plots get too wide */
      padding: 10px;
    }}

    .kpi-row {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }}
    @media (min-width: 980px) {{
      .kpi-row {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    }}

    .kpi {{
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(0,0,0,0.14);
    }}
    .kpi-label {{
      color: var(--muted);
      font-size: 12px;
    }}
    .kpi-value {{
      font-size: 16px;
      margin-top: 2px;
    }}

    .card-title-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }}

    .badge {{
      font-size: 12px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.16);
    }}
    .badge-sut {{ background: rgba(34, 197, 94, 0.14); }}
    .badge-stack {{ background: rgba(59, 130, 246, 0.14); }}

    .hero {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      padding: 14px 14px;
      border-radius: 16px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(0,0,0,0.16);
    }}
    .hero-title {{
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0.2px;
    }}
    .hero-subtitle {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 13px;
    }}
    .hero-meta {{
      display: grid;
      gap: 6px;
      font-size: 13px;
    }}

    .callout {{
      padding: 12px 12px;
      border-radius: 16px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(0,0,0,0.14);
    }}
    .callout-title {{
      font-weight: 600;
      margin-bottom: 6px;
    }}
    .callout-body {{
      color: var(--muted);
      font-size: 13px;
    }}

    .service-card {{
      scroll-margin-top: 12px;
    }}

    .footer {{
      margin-top: 26px;
      color: var(--muted);
      font-size: 12px;
      text-align: center;
    }}

    .small {{
      font-size: 12px;
      color: var(--muted);
    }}
  </style>
</head>

<body>
  <div class="container">
    <div class="title">
      <div>
        <h1>{title}</h1>
        <div class="subtitle">
          Input: <span class="small">{input_path}</span><br/>
          Window (UTC): <b>{global_first.isoformat()}</b> → <b>{global_last.isoformat()}</b> · Duration: <b>{global_duration}</b> · Services: <b>{len(stats)}</b>
        </div>
      </div>
      <button class="btn" id="btnExpandAll">Expand charts</button>
    </div>

    <div class="topbar">
      <input class="search" id="svcSearch" placeholder="Filter microservices (type to search)…"/>
      <label class="toggle">
        <input type="checkbox" id="toggleTech" checked/>
        Show technology stack
      </label>
      <button class="btn" id="btnTop">Jump to top</button>
    </div>

    {impactful_html}

    <section class="card">
      <div class="card-header">
        <h2 class="card-title">Global overview</h2>
        <p class="muted">Rankings are based on integrated energy (Wh) from <code>estimated_power_from_shelly_watt</code>.</p>
      </div>
      <div class="card-body grid-2">
        <div class="chart-wrap">
          {_plotly_div("bar_energy")}
        </div>
        <div class="chart-wrap">
          {_plotly_div("bar_avg_power")}
        </div>
        {"<div class='chart-wrap' style='grid-column: 1 / -1;'>" + _plotly_div("stacked_top") + "</div>" if "stacked_top" in figs else ""}
        {"<div class='chart-wrap' style='grid-column: 1 / -1;'>" + _plotly_div("scatter_cpu_pow") + "</div>" if "scatter_cpu_pow" in figs else ""}
      </div>
    </section>

    <section class="card">
      <div class="card-header">
        <h2 class="card-title">Microservices</h2>
        <p class="muted">
          Each microservice includes two time-series charts:
          <b>estimated power</b> (from Shelly attribution) and <b>cpu_cores_used</b>.
          Horizontal scroll is enabled for very wide plots.
        </p>
      </div>
      <div class="card-body">
        {''.join(service_sections)}
      </div>
    </section>

    <div class="footer">
      Generated at {datetime.now(timezone.utc).isoformat()} (UTC)
    </div>
  </div>

  <script>
    // Render Plotly figures.
    (function() {{
      const figs = {_to_json(figs)};
      for (const [divId, fig] of Object.entries(figs)) {{
        try {{
          Plotly.newPlot(divId, fig.data, fig.layout, {{responsive:true, displaylogo:false}});
        }} catch (e) {{
          console.error("Plotly render failed for", divId, e);
        }}
      }}
    }})();

    // UI: filter services by name + toggle tech-stack.
    (function() {{
      const search = document.getElementById("svcSearch");
      const toggleTech = document.getElementById("toggleTech");

      function applyFilter() {{
        const q = (search.value || "").trim().toLowerCase();
        const showTech = !!toggleTech.checked;

        document.querySelectorAll(".service-card").forEach(card => {{
          const name = (card.getAttribute("data-service") || "");
          const badge = (card.getAttribute("data-badge") || "");
          const matchName = !q || name.includes(q);
          const matchTech = showTech || badge !== "TECH STACK";
          card.style.display = (matchName && matchTech) ? "" : "none";
        }});
      }}

      search.addEventListener("input", applyFilter);
      toggleTech.addEventListener("change", applyFilter);
      applyFilter();
    }})();

    // Buttons.
    document.getElementById("btnTop").addEventListener("click", () => window.scrollTo({{top: 0, behavior: "smooth"}}));

    document.getElementById("btnExpandAll").addEventListener("click", () => {{
      document.querySelectorAll(".plotly-chart").forEach(div => {{
        div.style.minHeight = "480px";
      }});
      window.dispatchEvent(new Event("resize"));
    }});
  </script>
</body>
</html>
"""
    return html


# -----------------------------
# Public API
# -----------------------------

def generate_shelly_power_html_report(
    input_json_path: str | Path,
    output_html_path: Optional[str | Path] = None,
    *,
    title: str = "Shelly power attribution report",
    tech_stack_patterns: Optional[Sequence[str]] = None,
) -> Path:
    """
    Main entrypoint to generate the report.

    Args:
        input_json_path: path to the JSON file.
        output_html_path: if None, defaults to "<input>.shelly_report.html" next to the input file.
        title: report title.
        tech_stack_patterns: regex list used to tag technology stack services and to exclude them
            for the "most impactful microservice" section.

    Returns:
        Path to the generated HTML.
    """
    in_path = Path(input_json_path).expanduser().resolve()
    if output_html_path is None:
        out_path = in_path.with_suffix(in_path.suffix + ".shelly_report.html")
    else:
        out_path = Path(output_html_path).expanduser().resolve()

    patterns = tuple(tech_stack_patterns) if tech_stack_patterns else DEFAULT_TECH_STACK_PATTERNS

    services = load_shelly_attributed_timeseries(in_path)
    html = build_html_report(services, input_path=in_path, tech_stack_patterns=patterns, title=title)
    out_path.write_text(html, encoding="utf-8")
    return out_path


# -----------------------------
# CLI (for test-only usage)
# -----------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shelly_power_analyzer",
        description="Generate an HTML report from Shelly-attributed microservice timeseries JSON.",
    )
    p.add_argument("input", type=str, help="Path to cpu_timeseries_with_shelly_power.json")
    p.add_argument("-o", "--output", type=str, default=None, help="Output HTML path (optional)")
    p.add_argument("--title", type=str, default="Shelly power attribution report", help="Report title")
    p.add_argument(
        "--tech-stack-pattern",
        action="append",
        default=None,
        help="Regex used to mark services as technology stack (can be repeated).",
    )
    p.add_argument(
        "--no-default-tech-stack",
        action="store_true",
        help="If set, do not use built-in tech-stack patterns (only those passed via --tech-stack-pattern).",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    patterns: List[str] = []
    if not args.no_default_tech_stack:
        patterns.extend(DEFAULT_TECH_STACK_PATTERNS)
    if args.tech_stack_pattern:
        patterns.extend(args.tech_stack_pattern)

    out = generate_shelly_power_html_report(
        args.input,
        args.output,
        title=args.title,
        tech_stack_patterns=patterns if patterns else DEFAULT_TECH_STACK_PATTERNS,
    )
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
