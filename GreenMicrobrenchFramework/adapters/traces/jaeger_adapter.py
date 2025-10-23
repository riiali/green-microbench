import requests
from datetime import datetime, timezone
from typing import List, Dict, Any

def _to_epoch_us(iso_ts: str) -> int:
    dt = datetime.fromisoformat(iso_ts.replace("Z","+00:00"))
    return int(dt.timestamp() * 1_000_000)

class JaegerAdapter:
    def __init__(self, base_url: str = "http://localhost:16686"):
        self.base = base_url.rstrip("/")

    def sample_traces(self, services: List[str], start_iso: str, end_iso: str, limit_per_service: int = 20) -> Dict[str, Any]:
        start_us = _to_epoch_us(start_iso)
        end_us = _to_epoch_us(end_iso)
        out: Dict[str, Any] = {"window": {"start": start_iso, "end": end_iso}, "samples": {}}
        for svc in services:
            params = {
                "service": svc,
                "start": start_us,
                "end": end_us,
                "limit": limit_per_service,
                "lookback": "custom",
            }
            r = requests.get(f"{self.base}/api/traces", params=params, timeout=20)
            r.raise_for_status()
            out["samples"][svc] = r.json()
        return out
