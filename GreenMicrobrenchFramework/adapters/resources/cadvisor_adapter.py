#transform raw prometheus cAdvisor metrics into meaningful resource usage data
from typing import Dict, Tuple
from statistics import mean
from datetime import datetime
from GreenMicrobrenchFramework.adapters.metrics.prometheus_adapter import PrometheusAdapter

class CAdvisorAdapter:
    def __init__(self, prom: PrometheusAdapter):
        self.prom = prom

    def cpu_share_over_period(self, start_iso: str, end_iso: str, step: str = "5s") -> Tuple[Dict[str, float], float]:
        q = (
            "sum by (container_label_com_docker_compose_service) "
            f"(rate(container_cpu_usage_seconds_total[{step}]))"
        )
        series = self.prom.range(q, start_iso, end_iso, step)
        per_service: Dict[str, float] = {}
        for s in series:
            lbl = s.get("metric", {}).get("container_label_com_docker_compose_service", "unknown")
            vals = [float(v[1]) for v in s.get("values", []) if v[1] is not None]
            if not vals:
                continue
            per_service[lbl] = mean(vals)
        total = sum(per_service.values()) if per_service else 0.0
        return per_service, total

    def cpu_fraction_over_period(self, start_iso: str, end_iso: str, step: str = "5s") -> Dict[str, float]:
        per_service, total = self.cpu_share_over_period(start_iso, end_iso, step)
        if total <= 0.0:
            return {k: 0.0 for k in per_service}
        return {k: v / total for k, v in per_service.items()}
