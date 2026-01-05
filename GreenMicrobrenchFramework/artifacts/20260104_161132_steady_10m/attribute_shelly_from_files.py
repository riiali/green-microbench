#!/usr/bin/env python3

import sys
from pathlib import Path

# ---------------------------------------------------------------------
# Ensure project root is on PYTHONPATH
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

import json
import argparse
from typing import Dict, List

from GreenMicrobrenchFramework.analyzer.cpu_energy_attribution import (
    ShellyPowerAttributor
)

# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------

def load_shelly_jsonl(path: Path) -> List[dict]:
    """
    Loads Shelly JSONL file.
    Timestamps are assumed to be already UTC and correct.
    """
    samples = []

    with path.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue

            if "ts" not in rec or "power_w" not in rec:
                continue

            samples.append(rec)

    return samples


def load_cadvisor_json(path: Path) -> Dict[str, List[dict]]:
    """
    Loads cAdvisor per-service CPU time series JSON.
    """
    with path.open() as f:
        return json.load(f)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Attribute Shelly power to services using time-indexed model"
    )
    ap.add_argument("--cpu", required=True)
    ap.add_argument("--shelly", required=True)
    ap.add_argument("--out", default="cpu_timeseries_with_shelly_power.json")
    ap.add_argument("--max-skew", type=float, default=5.0)
    ap.add_argument("--cpu-epsilon", type=float, default=0.01)
    ap.add_argument("--host-cores", type=int, default=4)

    args = ap.parse_args()

    cpu_path = Path(args.cpu)
    shelly_path = Path(args.shelly)
    out_path = Path(args.out)

    if not cpu_path.exists():
        raise FileNotFoundError(cpu_path)
    if not shelly_path.exists():
        raise FileNotFoundError(shelly_path)

    print("[INFO] Loading cAdvisor CPU data...")
    cadvisor_by_service = load_cadvisor_json(cpu_path)

    print("[INFO] Loading Shelly power data...")
    shelly_samples = load_shelly_jsonl(shelly_path)

    print(f"[INFO] Services: {len(cadvisor_by_service)}")
    print(f"[INFO] Shelly samples: {len(shelly_samples)}")

    # -----------------------------------------------------------------
    # Time-centric attribution pipeline
    # -----------------------------------------------------------------

    attributor = ShellyPowerAttributor(
        host_cpu_cores=args.host_cores,
        max_time_skew_s=args.max_skew,
        cpu_epsilon_cores=args.cpu_epsilon,
    )

    print("[INFO] Building canonical timeline...")
    timeline = attributor.build_timeline(
        shelly_samples=shelly_samples,
        cadvisor_by_service=cadvisor_by_service,
    )

    print(f"[INFO] Timeline instants: {len(timeline)}")

    print("[INFO] Aligning timeline (nearest-neighbor)...")
    aligned = attributor.align_timeline(timeline)

    print(f"[INFO] Aligned instants: {len(aligned)}")

    print("[INFO] Attributing Shelly power...")
    attributed = attributor.attribute(aligned)

    print("[INFO] Exporting per-service view...")
    per_service = attributor.export_per_service(attributed)

    with out_path.open("w") as f:
        json.dump(per_service, f, indent=2)

    print(f"[INFO] Written {out_path}")

    # -----------------------------------------------------------------
    # Sanity summary
    # -----------------------------------------------------------------

    non_empty = {
        svc: len(samples)
        for svc, samples in per_service.items()
        if samples
    }

    print("[INFO] Non-empty services:")
    for svc, n in sorted(non_empty.items()):
        print(f"  - {svc}: {n} samples")

    if not non_empty:
        print("[WARN] All services empty → check timestamps or skew")


if __name__ == "__main__":
    main()
