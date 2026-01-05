
from typing import Dict, Tuple, List
from statistics import mean
from datetime import datetime, timezone
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
         #print("SERVICE RUNTIME MAP:", service_runtime_map)
        #print("PER CONTAINER:", per_container)
        #print("TOTAL:", total)
        
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

    def cpu_percent_raspberry_per_service_timeseries(
        self,
        start_iso: str,
        end_iso: str,
        service_runtime_map: Dict[str, dict],
        window: str = "30s",
        raspberry_cores: int = 4,
    ) -> Dict[str, List[dict]]:
        """
        Returns CPU usage as percentage of the whole Raspberry Pi,
        sampled every second, ONLY for Docker containers, grouped by service name.

        Assumptions:
        - Running on Raspberry Pi 4 (4 CPU cores)
        - Prometheus scrapes cAdvisor at 1 Hz
        - CPU usage is averaged using a sliding window (smoothing)
        - Only Docker containers are considered (system cgroups are ignored)
        - Service names are resolved using service_runtime_map

        Output format:
        {
          service_name: [
            {"ts": ISO8601 (second precision), "cpu_percent_raspberry": float},
            ...
          ]
        }
        """

        # Build a reverse map: container_id_short -> service_name
        cid_to_service = {
            info["container_id"][:12]: service_name
            for service_name, info in service_runtime_map.items()
        }

        # PromQL query:
        # - rate(...) gives average CPU cores used
        # - normalized to Raspberry Pi CPU percentage
        query = (
            f"(100 / {raspberry_cores}) * "
            "sum by (id) ("
            f"rate(container_cpu_usage_seconds_total[{window}])"
            ")"
        )

        series = self.prom.range(
            query=query,
            start=start_iso,
            end=end_iso,
            step="1s",
        )

        out: Dict[str, List[dict]] = {}

        for s in series:
            cgroup_id = s.get("metric", {}).get("id", "")

            # Only consider Docker containers
            # Example cgroup:
            # /system.slice/docker-<container_id>.scope
            if "docker-" not in cgroup_id:
                continue

            # Extract container_id_short from cgroup path
            # docker-<64hex>.scope → <12hex>
            try:
                cid_short = cgroup_id.split("docker-")[1][:12]
            except Exception:
                continue

            service_name = cid_to_service.get(cid_short)
            if not service_name:
                continue  # container not part of the experiment

            for ts, val in s.get("values", []):
                if val is None:
                    continue

                # Normalize timestamp to SECOND precision (no microseconds)
                ts_norm = datetime.fromtimestamp(ts).replace(microsecond=0).isoformat()

                out.setdefault(service_name, []).append({
                    "ts": ts_norm,
                    "cpu_percent_raspberry": float(val),
                })

        return out
    
    def cpu_usage_raspberry_per_service_timeseries(
        self,
        start_iso: str,
        end_iso: str,
        service_runtime_map: Dict[str, dict],
        window: str = "5s",
        raspberry_cores: int = 4,
    ) -> Dict[str, List[dict]]:
        """
        Returns CPU usage per service as:
        - cpu_cores_used: average number of CPU cores used
        - cpu_percent_host: % of total Raspberry Pi CPU capacity
        """

        cid_to_service = {
            info["container_id"][:12]: service_name
            for service_name, info in service_runtime_map.items()
        }

        query = (
            "sum by (id) ("
            f"rate(container_cpu_usage_seconds_total[{window}])"
            ")"
        )

        series = self.prom.range(
            query=query,
            start=start_iso,
            end=end_iso,
            step="1s",
        )

        out: Dict[str, List[dict]] = {}

        for s in series:
            cgroup_id = s.get("metric", {}).get("id", "")

            if "docker-" not in cgroup_id:
                continue

            try:
                cid_short = cgroup_id.split("docker-")[1][:12]
            except Exception:
                continue

            service_name = cid_to_service.get(cid_short)
            if not service_name:
                continue

            for ts, val in s.get("values", []):
                if val is None:
                    continue

                cpu_cores = float(val)
                cpu_percent_host = (cpu_cores / raspberry_cores) * 100

                ts_norm = (
                    datetime
                    .fromtimestamp(ts, tz=timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                )

                out.setdefault(service_name, []).append({
                    "ts": ts_norm,
                    "cpu_cores_used": cpu_cores,
                    "cpu_percent_host": cpu_percent_host,
                })

        return out
