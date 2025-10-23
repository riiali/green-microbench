#sample real power from shellt plug to correlate with software metrics collected during load tests
import threading
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any
import requests
from datetime import datetime, timezone

class ShellyAdapter:
    def __init__(self, base_url: str, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._thr: Optional[threading.Thread] = None
        self._run = False
        self._out_path: Optional[Path] = None
        self._hz = 1.0

    def _read_once(self) -> Dict[str, Any]:
        r = requests.get(f"{self.base_url}/status", timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if "meters" in data and data["meters"]:
            power_w = float(data["meters"][0].get("power", 0.0))
        elif "emeter" in data:
            power_w = float(data["emeter"].get("power", 0.0))
        else:
            power_w = 0.0
        return {"ts": datetime.now(timezone.utc).isoformat(), "power_w": power_w}

    def _loop(self) -> None:
        period = 1.0 / self._hz if self._hz > 0 else 1.0
        assert self._out_path is not None
        self._out_path.parent.mkdir(parents=True, exist_ok=True)
        with self._out_path.open("a", encoding="utf-8") as f:
            while self._run:
                try:
                    rec = self._read_once()
                except Exception as e:
                    rec = {"ts": datetime.now(timezone.utc).isoformat(), "error": str(e)}
                f.write(json.dumps(rec) + "\n")
                f.flush()
                time.sleep(period)

    def start(self, *, out_path: str, hz: float = 1.0) -> None:
        if self._run:
            return
        self._hz = hz
        self._out_path = Path(out_path)
        self._run = True
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop(self) -> None:
        if not self._run:
            return
        self._run = False
        if self._thr:
            self._thr.join(timeout=5.0)
            self._thr = None
