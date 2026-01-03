import json
from typing import Dict, List, Any
from .prometheus_adapter import PrometheusAdapter

def _first_non_empty(prom: PrometheusAdapter, queries: List[str], start: str, end: str, step: str) -> Any:
    for q in queries:
        data = prom.range(q, start, end, step)
        if isinstance(data, list) and len(data) > 0:
            return data
    return []

def export_core_series(prom: PrometheusAdapter, start_iso: str, end_iso: str, step: str, out_paths: Dict[str, str], window: str) -> None:
    req_candidates = [
        f'sum by (exported_job) (rate(otel_http_client_duration_milliseconds_count[{window}]))',
    ]
    p95_candidates = [
        f'histogram_quantile(0.95, sum by (le, exported_job) (rate(otel_http_client_duration_milliseconds_bucket[{window}])))',
    ]


    try:
        req_series = _first_non_empty(prom, req_candidates, start_iso, end_iso, step)
    except Exception as e:
        req_series = []
        print(f"[WARN] Prometheus requests query failed: {e}")

    try:
        p95_series = _first_non_empty(prom, p95_candidates, start_iso, end_iso, step)
    except Exception as e:
        p95_series = []
        print(f"[WARN] Prometheus p95 query failed: {e}")

    with open(out_paths["requests"], "w") as f: json.dump(req_series, f)
    with open(out_paths["p95"], "w") as f: json.dump(p95_series, f)
