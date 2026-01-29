#handle prometheus
from typing import Any, Dict, List
import requests

class PrometheusAdapter:
    def __init__(self, base_url: str = "http://localhost:9090", timeout: float = 20.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def instant(self, query: str) -> Any:
        r = requests.get(f"{self.base}/api/v1/query", params={"query": query}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["data"]["result"]

    def range(self, query: str, start: str, end: str, step: str = "5s") -> Any:
        r = requests.get(
            f"{self.base}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()["data"]["result"]

    def reqs_per_service(self, window: str = "1m") -> List[Dict]:
        q = f"sum by (service_name) (rate(otel_http_server_duration_milliseconds_count[{window}]))"
        return self.instant(q)

    def p95_latency_per_service(self, window: str = "1m") -> List[Dict]:
        q = (
            "histogram_quantile(0.95, "
            f"sum by (le, exported_job) (rate(otel_http_server_duration_milliseconds_bucket[{window}])))"
        )
        return self.instant(q)

    def cpu_by_service(self, window: str = "1m") -> List[Dict]:
        q = (
            "sum by (id) "
            f"(rate(container_cpu_usage_seconds_total[{window}]))"
        )
        return self.instant(q)
