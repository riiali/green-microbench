
from typing import Dict, Tuple
from statistics import mean
from datetime import datetime
from GreenMicrobrenchFramework.adapters.metrics.prometheus_adapter import PrometheusAdapter

class CAdvisorAdapter:
    def __init__(self, prom: PrometheusAdapter):
        self.prom = prom

    def cpu_share_over_period(self, start_iso: str, end_iso: str, step: str = "5s") -> Tuple[Dict[str, float], float]:
        q = (
            "sum by (id) "
            f"(rate(container_cpu_usage_seconds_total[{step}]))"
        )
        series = self.prom.range(q, start_iso, end_iso, step)
        per_service: Dict[str, float] = {}
        for s in series:
            lbl = s.get("metric", {}).get("id", "unknown")
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
    
    def cpu_map_fraction_over_period(
        self,
        start_iso: str,
        end_iso: str,
        step: str = "5s",
        service_runtime_map: dict = None
    ) -> Dict[str, float]:

        per_container, total = self.cpu_share_over_period(start_iso, end_iso, "1m")
        #print (per_container, total)
        print("SERVICE RUNTIME MAP:", service_runtime_map)
        print("PER CONTAINER:", per_container)
        print("TOTAL:", total)
        
        if service_runtime_map is None:
            # default: return per container id
            return {k: v / total for k, v in per_container.items()}

        out = {}
        others = 0.0

        for cid, cpu in per_container.items():
            matched = False
            for service_name, info in service_runtime_map.items():
                if info["container_id"] in cid:
                    out[service_name] = out.get(service_name, 0.0) + (cpu / total)
                    matched = True
                    break
            if not matched:
                others += cpu / total

        if others > 0:
            out["others"] = others

        return out