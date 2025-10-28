import json
from typing import Dict, List, Any
from .prometheus_adapter import PrometheusAdapter

def _first_non_empty(prom: PrometheusAdapter, queries: List[str], start: str, end: str, step: str) -> Any:
    for q in queries:
        data = prom.range(q, start, end, step)
        if isinstance(data, list) and len(data) > 0:
            return data
    return []

def export_core_series(prom: PrometheusAdapter, start_iso: str, end_iso: str, step: str, out_paths: Dict[str, str]) -> None:
    req_candidates = [
        'sum by (service_name) (rate(http_server_request_duration_count[1m]))',
        'sum by (service_name) (rate(http_server_request_duration_seconds_count[1m]))',
        'sum by (service_name) (rate(otel_http_server_duration_count[1m]))',
        'sum by (service_name) (rate(flask_http_request_duration_seconds_count[1m]))',
        'sum by (net_peer_name) (rate(otel_http_client_duration_milliseconds_count[1m]))',
        'sum by (exported_job) (rate(otel_http_client_duration_milliseconds_count[1m]))',
    ]
    p95_candidates = [
        'histogram_quantile(0.95, sum by (le, service_name) (rate(http_server_request_duration_bucket[5m])))',
        'histogram_quantile(0.95, sum by (le, service_name) (rate(http_server_request_duration_seconds_bucket[5m])))',
        'histogram_quantile(0.95, sum by (le, service_name) (rate(otel_http_server_duration_bucket[5m])))',
        'histogram_quantile(0.95, sum by (le, service_name) (rate(flask_http_request_duration_seconds_bucket[5m])))',
        'histogram_quantile(0.95, sum by (le, net_peer_name) (rate(otel_http_client_duration_milliseconds_bucket[5m])))',
        'histogram_quantile(0.95, sum by (le, exported_job) (rate(otel_http_client_duration_milliseconds_bucket[5m])))',
    ]
    cpu_candidates = [
        'sum by (container_label_com_docker_compose_service) (rate(container_cpu_usage_seconds_total[1m]))',
        'sum by (container, image, name) (rate(container_cpu_usage_seconds_total[1m]))',
    ]

    req_series = _first_non_empty(prom, req_candidates, start_iso, end_iso, step)
    p95_series = _first_non_empty(prom, p95_candidates, start_iso, end_iso, step)
    cpu_series = _first_non_empty(prom, cpu_candidates, start_iso, end_iso, step)

    with open(out_paths["requests"], "w") as f: json.dump(req_series, f)
    with open(out_paths["p95"], "w") as f: json.dump(p95_series, f)
    with open(out_paths["cpu"], "w") as f: json.dump(cpu_series, f)
