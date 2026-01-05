from datetime import datetime, timezone
from typing import Dict, List, Optional



def normalize_ts(ts: str) -> str:
    """
    Normalizes any ISO-8601 timestamp to:
    - UTC
    - second precision
    - ISO-8601 string

    This function MUST be applied exactly once per data source.
    """
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt.replace(microsecond=0).isoformat()


def ts_to_epoch(ts: str) -> float:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def nearest_by_time(
    candidates: Dict[str, dict],
    target_epoch: float,
    max_skew_s: float,
) -> Optional[dict]:
    """
    Finds nearest candidate (by timestamp) within max_skew_s.
    """
    best = None
    best_delta = None

    for ts, obj in candidates.items():
        delta = abs(ts_to_epoch(ts) - target_epoch)
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best = obj

    if best_delta is not None and best_delta <= max_skew_s:
        return best

    return None


class ShellyPowerAttributor:
    """
    Time-indexed power attribution engine.

    Core principle:
    - Time is the primary key
    - Services are attributes of time
    - Attribution is performed AFTER temporal alignment
    """

    def __init__(
        self,
        *,
        host_cpu_cores: int = 4,
        max_time_skew_s: float = 5.0,
        cpu_epsilon_cores: float = 0.01,
    ):
        self.host_cpu_cores = host_cpu_cores
        self.max_time_skew_s = max_time_skew_s
        self.cpu_epsilon_cores = cpu_epsilon_cores

    def build_timeline(
        self,
        shelly_samples: List[dict],
        cadvisor_by_service: Dict[str, List[dict]],
    ) -> Dict[str, dict]:
        """
        Builds a time-indexed structure:

        timeline[t] = {
          "shelly": {...},
          "services": {
            service_name: {...}
          }
        }
        """

        timeline: Dict[str, dict] = {}

        # --- Shelly ----------------------------------------------------

        for s in shelly_samples:
            if "ts" not in s or "power_w" not in s:
                continue

            ts = normalize_ts(s["ts"])
            timeline.setdefault(ts, {})["shelly"] = {
                "power_w": float(s["power_w"]),
                "voltage_V": s.get("voltage_V"),
            }

        # --- cAdvisor --------------------------------------------------

        for service, samples in cadvisor_by_service.items():
            for s in samples:
                if "ts" not in s or "cpu_cores_used" not in s:
                    continue

                ts = normalize_ts(s["ts"])
                timeline.setdefault(ts, {}).setdefault("services", {})[service] = {
                    "cpu_cores_used": float(s["cpu_cores_used"]),
                    "cpu_percent_host": float(
                        s.get(
                            "cpu_percent_host",
                            (float(s["cpu_cores_used"]) / self.host_cpu_cores) * 100,
                        )
                    ),
                }

        return timeline


    def align_timeline(self, timeline: Dict[str, dict]) -> Dict[str, dict]:
        """
        Aligns Shelly and service data per timestamp using nearest-neighbor logic.
        """

        aligned: Dict[str, dict] = {}

        shelly_only = {
            ts: data["shelly"]
            for ts, data in timeline.items()
            if "shelly" in data
        }

        service_only = {
            ts: data["services"]
            for ts, data in timeline.items()
            if "services" in data
        }

        for ts, services in service_only.items():
            ts_epoch = ts_to_epoch(ts)

            shelly_match = nearest_by_time(
                shelly_only,
                ts_epoch,
                self.max_time_skew_s,
            )

            if shelly_match is None:
                continue

            aligned[ts] = {
                "shelly": shelly_match,
                "services": services,
            }

        return aligned


    def attribute(self, aligned_timeline: Dict[str, dict]) -> Dict[str, dict]:
        """
        Attributes Shelly power proportionally to CPU usage.
        """

        for ts, data in aligned_timeline.items():
            services = data["services"]
            shelly_power = data["shelly"]["power_w"]

            cpu_total = sum(
                s["cpu_cores_used"] for s in services.values()
            )

            if cpu_total < self.cpu_epsilon_cores:
                for s in services.values():
                    s["estimated_power_from_shelly_watt"] = 0.0
                continue

            for s in services.values():
                frac = s["cpu_cores_used"] / cpu_total
                s["estimated_power_from_shelly_watt"] = frac * shelly_power

        return aligned_timeline


    def export_per_service(
        self,
        attributed_timeline: Dict[str, dict],
    ) -> Dict[str, List[dict]]:
        """
        Converts time-indexed data into per-service time series.
        """

        out: Dict[str, List[dict]] = {}

        for ts, data in attributed_timeline.items():
            for service, s in data["services"].items():
                out.setdefault(service, []).append({
                    "ts": ts,
                    **s,
                })

        return out
