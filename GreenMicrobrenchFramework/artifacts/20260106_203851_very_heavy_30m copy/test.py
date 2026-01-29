#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from typing import List, Dict

from cpu_energy_attribution import ShellyPowerAttributor


# ---------------------------------------------------------------------------
# Utility loaders
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> List[dict]:
    """
    Loads a JSONL file (one JSON object per line).
    """
    samples = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return samples


def load_json(path: Path) -> Dict:
    """
    Loads a standard JSON file.
    """
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="CPU-based energy attribution using Shelly and cAdvisor data"
    )

    ap.add_argument(
        "--shelly",
        required=True,
        type=Path,
        help="Path to Shelly power JSONL file (power.jsonl)"
    )

    ap.add_argument(
        "--cadvisor",
        required=True,
        type=Path,
        help="Path to cAdvisor per-service CPU time series JSON file"
    )

    ap.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output JSON file for per-service attributed power time series"
    )

    ap.add_argument(
        "--cores",
        type=int,
        default=4,
        help="Number of CPU cores of the host (default: 4)"
    )

    ap.add_argument(
        "--max-skew",
        type=float,
        default=5.0,
        help="Maximum allowed time skew (seconds) for temporal alignment"
    )

    ap.add_argument(
        "--cpu-epsilon",
        type=float,
        default=0.01,
        help="Minimum total CPU (cores) required to perform attribution"
    )

    args = ap.parse_args()

    # -----------------------------------------------------------------------
    # Load inputs
    # -----------------------------------------------------------------------

    print("[INFO] Loading Shelly samples...")
    shelly_samples = load_jsonl(args.shelly)

    print("[INFO] Loading cAdvisor CPU time series...")
    cadvisor_by_service = load_json(args.cadvisor)

    # -----------------------------------------------------------------------
    # Run attribution
    # -----------------------------------------------------------------------

    print("[INFO] Running CPU energy attribution...")

    attributor = ShellyPowerAttributor(
        host_cpu_cores=args.cores,
        max_time_skew_s=args.max_skew,
        cpu_epsilon_cores=args.cpu_epsilon,
    )

    timeline = attributor.build_timeline(
        shelly_samples=shelly_samples,
        cadvisor_by_service=cadvisor_by_service,
    )

    aligned = attributor.align_timeline(timeline)
    attributed = attributor.attribute(aligned)
    per_service = attributor.export_per_service(attributed)

    # -----------------------------------------------------------------------
    # Write output
    # -----------------------------------------------------------------------

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(per_service, indent=2))

    print(f"[INFO] Attribution completed.")
    print(f"[INFO] Output written to: {args.out}")


if __name__ == "__main__":
    main()
