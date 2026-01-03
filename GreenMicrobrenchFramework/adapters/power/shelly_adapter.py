import threading
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import requests
from datetime import datetime, timezone

class ShellyAdapter:
    def __init__(self, base_url: str, timeout: float = 3.0, switch_id: int = 0, auth: Optional[Tuple[str, str]] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.switch_id = switch_id
        self.auth = auth
        self._thr: Optional[threading.Thread] = None
        self._run = False
        self._out_path: Optional[Path] = None
        self._hz = 1.0

    def _read_once(self) -> Dict[str, Any]:
        r = requests.get(
            f"{self.base_url}/rpc/Switch.GetStatus",
            params={"id": self.switch_id},
            timeout=self.timeout,
            auth=self.auth,
        )
        r.raise_for_status()
        data = r.json()
        power_w = float(data.get("apower", 0.0))
        out = {"ts": datetime.now(timezone.utc).isoformat(), "power_w": power_w}
        if isinstance(data.get("aenergy"), dict) and "total" in data["aenergy"]:
            out["energy_total_Wh"] = float(data["aenergy"]["total"])
        return out

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
    
    #read all shelly data at oncem including voltage,current,power factor,temperature,energy        
    def _read_once_all_data(self) -> Dict[str, Any]:
        r = requests.post(
            f"{self.base_url}/rpc/Switch.GetStatus",
            json={"id": self.switch_id},
            timeout=self.timeout,
            auth=self.auth,
        )
        r.raise_for_status()
        data = r.json()

        out: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "id": self.switch_id,
            "output": data.get("output"),
            "source": data.get("source"),

            "apower_W": data.get("apower"),
            "voltage_V": data.get("voltage"),
            "current_A": data.get("current"),
            "pf": data.get("pf"),

            "temperature_C": data.get("temperature", {}).get("tC"),
            "temperature_F": data.get("temperature", {}).get("tF"),
        }

        aenergy = data.get("aenergy")
        if isinstance(aenergy, dict):
            out["energy_total_Wh"] = aenergy.get("total")
            out["energy_by_minute"] = aenergy.get("by_minute")
            out["energy_minute_ts"] = aenergy.get("minute_ts")

        if "errors" in data:
            out["errors"] = data["errors"]

        return out

