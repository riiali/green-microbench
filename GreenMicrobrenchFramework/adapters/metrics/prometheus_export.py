import json
from typing import Dict
from .prometheus_adapter import PrometheusAdapter

def export_core_series(prom: PrometheusAdapter, start_iso: str, end_iso: str, step: str, out_paths: Dict[str, str]) -> None:
    reqs_q = "sum by (service_name) (rate(otel_http_server_duration_count[1m]))"
    p95_q = "histogram_quantile(0.95, sum by (le, service_name) (rate(otel_http_server_duration_bucket[5m])))"
    cpu_q = "sum by (container_label_com_docker_compose_service) (rate(container_cpu_usage_seconds_total[1m]))"
    data = {
        "requests_per_service": prom.range(reqs_q, start_iso, end_iso, step),
        "p95_latency_per_service": prom.range(p95_q, start_iso, end_iso, step),
        "cpu_by_service": prom.range(cpu_q, start_iso, end_iso, step),
    }
    with open(out_paths["requests"], "w") as f: json.dump(data["requests_per_service"], f)
    with open(out_paths["p95"], "w") as f: json.dump(data["p95_latency_per_service"], f)
    with open(out_paths["cpu"], "w") as f: json.dump(data["cpu_by_service"], f)
