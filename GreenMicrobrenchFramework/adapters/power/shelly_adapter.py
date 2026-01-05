import threading
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import requests
from datetime import datetime, timezone


class ShellyAdapter:
    """
    Periodically samples electrical measurements from a Shelly device
    and stores them as JSON Lines.

    Primary metrics (used for analysis):
    - power_w        : real power (W)
    - voltage_V     : supply voltage (V)
    - energy_total_Wh: cumulative energy (Wh)

    Secondary metrics are available via the full read method.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 3.0,
        switch_id: int = 0,
        auth: Optional[Tuple[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.switch_id = switch_id
        self.auth = auth

        self._thr: Optional[threading.Thread] = None
        self._run = False
        self._out_path: Optional[Path] = None
        self._hz = 1.0

    # ------------------------------------------------------------------
    # Lightweight sampling (recommended for experiments)
    # ------------------------------------------------------------------

    def _read_once(self) -> Dict[str, Any]:
        """
        Reads the essential electrical metrics from Shelly.

        This method is intended for continuous sampling (1–10 Hz).
        """
        r = requests.get(
            f"{self.base_url}/rpc/Switch.GetStatus",
            params={"id": self.switch_id},
            timeout=self.timeout,
            auth=self.auth,
        )
        r.raise_for_status()
        data = r.json()

        out: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "power_w": float(data.get("apower", 0.0)),
            "voltage_V": data.get("voltage"),
        }

        aenergy = data.get("aenergy")
        if isinstance(aenergy, dict) and "total" in aenergy:
            out["energy_total_Wh"] = float(aenergy["total"])

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
                    rec = {
                        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        "error": str(e),
                    }

                f.write(json.dumps(rec) + "\n")
                f.flush()
                time.sleep(period)

    def start(self, *, out_path: str, hz: float = 1.0) -> None:
        """
        Starts background sampling.

        Args:
            out_path: JSONL output file
            hz: sampling frequency (default: 1 Hz)
        """
        if self._run:
            return

        self._hz = hz
        self._out_path = Path(out_path)
        self._run = True

        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop(self) -> None:
        """Stops background sampling."""
        if not self._run:
            return

        self._run = False
        if self._thr:
            self._thr.join(timeout=5.0)
            self._thr = None

    # ------------------------------------------------------------------
    # Full diagnostic read (NOT for continuous logging)
    # ------------------------------------------------------------------

    def read_once_all_data(self) -> Dict[str, Any]:
        """
        Reads the full set of metrics exposed by Shelly.

        Intended for debugging, calibration, or exploratory analysis.
        """
        r = requests.post(
            f"{self.base_url}/rpc/Switch.GetStatus",
            json={"id": self.switch_id},
            timeout=self.timeout,
            auth=self.auth,
        )
        r.raise_for_status()
        data = r.json()
        
        out: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "id": self.switch_id,
            "output": data.get("output"),
            "source": data.get("source"),

            "power_w": data.get("apower"),
            "voltage_V": data.get("voltage"),
            "current_A": data.get("current"),

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
