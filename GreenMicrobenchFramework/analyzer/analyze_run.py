import json, math, base64, io
from pathlib import Path
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt


# -------------------------
# Technology stack services
# -------------------------
TECH_STACK = {
    "cadvisor",
    "jaeger",
    "jaeger-query",
    "otel-collector",
    "otel-collector-contrib",
    "prometheus",
    "node-exporter",
}


# -------------------------
# Helpers
# -------------------------
def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return [] if path else []


def _png_bytes_to_data_uri(buf):
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _drop_others(d):
    return {k: v for k, v in (d or {}).items() if k != "others"}


def _last_values(series, label_key):
    out = {}
    for s in series or []:
        labels = s.get("metric", {})
        key = labels.get(label_key)
        if not key or key == "others":
            continue
        vals = s.get("values") or s.get("value")
        if isinstance(vals, list) and vals:
            out[key] = float(vals[-1][1])
        elif isinstance(vals, (tuple, list)) and len(vals) == 2:
            out[key] = float(vals[1])
    return out


def _summarize_jaeger(jaeger_json):
    out = {}
    try:
        samples = jaeger_json.get("samples", {})
        for svc, payload in samples.items():
            if svc == "others":
                continue
            traces = payload.get("data", []) if isinstance(payload, dict) else []
            if not traces:
                continue
            span_counts = [len(t.get("spans", [])) for t in traces]
            out[svc] = {
                "traces": len(traces),
                "avg_spans": sum(span_counts) / len(span_counts) if span_counts else 0.0,
            }
    except Exception:
        pass
    return out


def _infer_requests_from_locust(locust_stats_csv, service_prefix_map):
    try:
        df = pd.read_csv(locust_stats_csv)
    except Exception:
        return {}

    req_col = None
    for c in df.columns:
        if str(c).strip().lower() in (
            "requests", "request count", "request_count", "num_requests"
        ):
            req_col = c
            break

    name_col = "Name" if "Name" in df.columns else None
    if req_col is None or name_col is None:
        return {}

    df = df[[name_col, req_col]].copy()
    df[name_col] = df[name_col].astype(str)

    out = {svc: 0.0 for svc in service_prefix_map}
    for svc, prefixes in service_prefix_map.items():
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        mask = False
        for p in prefixes:
            mask = mask | df[name_col].str.startswith(p)
        out[svc] = float(df.loc[mask, req_col].fillna(0).sum())

    return out


# -------------------------
# Main analysis
# -------------------------
def analyze_run(run_dir: str, service_prefix_map=None):
    run_dir = Path(run_dir)

    manifest = json.loads((run_dir / "manifest.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())

    prom_requests = _read_json(manifest["files"].get("prom_requests"))
    prom_p95 = _read_json(manifest["files"].get("prom_p95"))
    prom_cpu = _read_json(manifest["files"].get("prom_cpu"))
    jaeger_sample = _read_json(manifest["files"].get("jaeger_sample"))

    energy_by_service = _drop_others(summary.get("energy_by_service_wh", {}))
    cpu_fraction = _drop_others(summary.get("cpu_fraction", {}))
    total_wh = float(summary.get("total_energy_wh", 0.0))

    # ---- Requests per service
    req_by_service = _last_values(prom_requests, "service_name")
    req_source = "prometheus_server(service_name)"

    if not req_by_service:
        req_by_service = _last_values(prom_requests, "job")
        req_source = "prometheus_server(job)"

    if not req_by_service:
        req_by_service = _last_values(prom_requests, "net_peer_name")
        req_source = "prometheus_client(net_peer_name)"

    if not req_by_service:
        if service_prefix_map is None:
            service_prefix_map = {
                "api-gateway": ["/"],
                "booking": ["/booking"],
                "search": ["/search"],
                "apartment": ["/apartment"],
            }
        locust_stats = manifest["files"].get("locust_stats")
        req_by_service = (
            _infer_requests_from_locust(locust_stats, service_prefix_map)
            if locust_stats
            else {}
        )
        req_source = "locust(heuristic_prefix)"

    req_by_service = _drop_others(req_by_service)

    p95_by_service = (
        _last_values(prom_p95, "service_name")
        or _last_values(prom_p95, "job")
        or _last_values(prom_p95, "net_peer_name")
    )
    p95_by_service = _drop_others(p95_by_service)

    # ---- DataFrame
    services = sorted(
        set(
            list(energy_by_service.keys())
            + list(cpu_fraction.keys())
            + list(req_by_service.keys())
        )
    )

    df = pd.DataFrame({"service": services})
    df["energy_Wh"] = df["service"].map(lambda s: float(energy_by_service.get(s, 0.0)))
    df["cpu_fraction"] = df["service"].map(lambda s: float(cpu_fraction.get(s, 0.0)))
    df["requests"] = df["service"].map(
        lambda s: float(req_by_service.get(s, math.nan))
    )
    df["p95_latency"] = df["service"].map(
        lambda s: float(p95_by_service.get(s, math.nan))
    )

    df["mWh_per_req"] = df.apply(
        lambda r: (1000.0 * r["energy_Wh"] / r["requests"])
        if r["requests"] and r["requests"] > 0
        else math.nan,
        axis=1,
    )

    tot_e = df["energy_Wh"].sum() or 1.0
    df["energy_share_%"] = 100.0 * df["energy_Wh"] / tot_e

    # ---- Classification
    df["category"] = df["service"].apply(
        lambda s: "technology_stack" if s in TECH_STACK else "application"
    )

    app_df = df[df["category"] == "application"]
    tech_df = df[df["category"] == "technology_stack"]

    # ---- Highlights (applications only)
    top_energy_service = (
        app_df.sort_values("energy_Wh", ascending=False).iloc[0]["service"]
        if len(app_df)
        else None
    )

    least_eff_service = (
        app_df.sort_values("mWh_per_req", ascending=False)
        .dropna(subset=["mWh_per_req"])
        .iloc[0]["service"]
        if app_df["mWh_per_req"].notna().any()
        else None
    )

    # ---- Charts
    def _bar(x, y, title, ylabel, highlight=None):
        fig, ax = plt.subplots(figsize=(7, 4))
        colors = ["#ff6f69" if v == highlight else "#88d8b0" for v in x]
        ax.bar(x, y, color=colors)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_xticklabels(x, rotation=30, ha="right")
        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format="png")
        plt.close(fig)
        return _png_bytes_to_data_uri(buf)

    figs = {
        "energy": _bar(
            app_df["service"],
            app_df["energy_Wh"],
            "Energy by service (applications)",
            "Wh",
            highlight=top_energy_service,
        ),
        "cpu": _bar(
            app_df["service"],
            app_df["cpu_fraction"],
            "CPU fraction by service (applications)",
            "fraction",
        ),
    }

    if app_df["p95_latency"].notna().any():
        figs["p95"] = _bar(
            app_df["service"],
            app_df["p95_latency"],
            "p95 latency (applications)",
            "seconds",
        )

    if app_df["mWh_per_req"].notna().any():
        figs["mwhreq"] = _bar(
            app_df["service"],
            app_df["mWh_per_req"],
            "Energy per request (applications)",
            "mWh/req",
            highlight=least_eff_service,
        )

    # ---- Jaeger summary
    jaeger_info = _summarize_jaeger(jaeger_sample) if jaeger_sample else {}

    # ---- HTML
    app_table_html = app_df.round(4).to_html(index=False)
    tech_table_html = (
        tech_df[["service", "energy_Wh", "cpu_fraction", "energy_share_%"]]
        .round(4)
        .to_html(index=False)
    )

    insights = []
    if top_energy_service:
        share = float(
            app_df.loc[app_df["service"] == top_energy_service, "energy_share_%"].values[0]
        )
        insights.append(
            f"<li><b>{top_energy_service}</b> is the most energy-consuming application ({share:.1f}% of app energy).</li>"
        )

    if least_eff_service:
        v = float(
            app_df.loc[app_df["service"] == least_eff_service, "mWh_per_req"].values[0]
        )
        insights.append(
            f"<li><b>{least_eff_service}</b> has the worst energy efficiency ({v:.3f} mWh/req).</li>"
        )

    if not insights:
        insights.append("<li>Metrics incomplete for efficiency analysis.</li>")

    jaeger_html = (
        "<ul>"
        + "".join(
            f"<li>{svc}: {v['traces']} traces, avg {v['avg_spans']:.1f} spans/trace</li>"
            for svc, v in jaeger_info.items()
        )
        + "</ul>"
        if jaeger_info
        else "<p>No Jaeger sample available.</p>"
    )

    html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>GreenMicrobench Report</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 32px; }}
.card {{ border:1px solid #ddd; border-radius:12px; padding:16px; margin:16px 0; }}
.badge {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#eef; }}
</style>
</head>
<body>

<h1>Experiment Analysis Report</h1>

<div class="card">
<b>Scenario</b> <span class="badge">{summary.get('scenario')}</span><br/>
<b>Window</b> <span class="badge">{summary.get('start_iso')} → {summary.get('end_iso')}</span><br/>
<b>Total energy</b> <span class="badge">{total_wh:.3f} Wh</span><br/>
<b>Requests source</b> <span class="badge">{req_source}</span>
</div>

<h2>Highlights</h2>
<ul>{''.join(insights)}</ul>

<div class="card">
<h2>Applications – Energy</h2>
<img src="{figs['energy']}" width="640"/>
</div>

<div class="card">
<h2>Applications – CPU</h2>
<img src="{figs['cpu']}" width="640"/>
</div>

<div class="card">
<h2>Applications – Latency</h2>
{f"<img src='{figs['p95']}' width='640'/>" if "p95" in figs else "<p>No p95 data.</p>"}
</div>

<div class="card">
<h2>Applications – Energy per request</h2>
{f"<img src='{figs['mwhreq']}' width='640'/>" if "mwhreq" in figs else "<p>No request counts.</p>"}
</div>

<div class="card">
<h2>Applications – Table</h2>
{app_table_html}
</div>

<div class="card">
<h2>Technology Stack (observability & monitoring)</h2>
<p>Reported separately from application workloads.</p>
{tech_table_html}
</div>

<div class="card">
<h2>Jaeger sample (quick)</h2>
{jaeger_html}
</div>

<p style="color:#888">Generated at {datetime.utcnow().isoformat()}Z</p>

</body>
</html>
"""

    (run_dir / "experiment_report.html").write_text(html, encoding="utf-8")

    analysis = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "total_energy_wh": total_wh,
        "applications": app_df.to_dict(orient="records"),
        "technology_stack": tech_df.to_dict(orient="records"),
    }

    (run_dir / "analysis_summary.json").write_text(
        json.dumps(analysis, indent=2), encoding="utf-8"
    )

    print(f"[OK] Report: {run_dir/'experiment_report.html'}")
    print(f"[OK] Summary: {run_dir/'analysis_summary.json'}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--service-map", default=None)
    args = ap.parse_args()

    smap = json.loads(args.service_map) if args.service_map else None
    analyze_run(args.run, service_prefix_map=smap)
