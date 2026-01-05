import subprocess as sp
import argparse
import json
import os
import sys
import time
import datetime
import pathlib
import yaml
import csv
from datetime import datetime, timezone, timedelta
from GreenMicrobrenchFramework.adapters.load.locust_adapter import LocustAdapter
from GreenMicrobrenchFramework.adapters.power.shelly_adapter import ShellyAdapter
from GreenMicrobrenchFramework.adapters.metrics.prometheus_adapter import PrometheusAdapter
from GreenMicrobrenchFramework.adapters.resources.cadvisor_adapter import CAdvisorAdapter
from GreenMicrobrenchFramework.adapters.metrics.prometheus_export import export_core_series
from GreenMicrobrenchFramework.adapters.traces.jaeger_adapter import JaegerAdapter
from GreenMicrobrenchFramework.analyzer.analyze_run import analyze_run
from GreenMicrobrenchFramework.analyzer.cpu_energy_attribution import attribute_shelly_power_to_services


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def iso_now() -> str:
    return (
        datetime
        .now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )

def parse_duration(rt: str) -> int:
    """
    Converts duration strings (e.g. '10s', '5m', '1h') into seconds.
    """
    if rt.endswith("s"):
        return int(rt[:-1])
    if rt.endswith("m"):
        return int(rt[:-1]) * 60
    if rt.endswith("h"):
        return int(rt[:-1]) * 3600
    raise ValueError(f"Unknown duration format: {rt}")


def get_container_runtime_info(host: str) -> dict:
    """
    Queries the remote Docker host (Raspberry Pi) to retrieve runtime
    information for each container.

    The returned structure maps:
        service_name -> { container_id, container_id_short, pid }

    This mapping is fundamental to correlate:
    - PowerJoular (PID-level)
    - cAdvisor (container-level)
    - Service-level energy attribution
    """
    cmd = (
        "docker inspect --format "
        "'{{ index .Config.Labels \"com.docker.compose.service\" }} {{.Id}} {{.State.Pid}}' "
        "$(docker ps -q)"
    )

    try:
        output = sp.check_output(
            ["ssh", host, cmd],
            universal_newlines=True
        )
    except Exception as e:
        print(f"[ERROR] Cannot query Docker runtime info: {e}")
        return {}

    info = {}
    for line in output.splitlines():
        service, cid, pid = line.strip().split()
        info[service] = {
            "container_id": cid,
            "container_id_short": cid[:12],
            "pid": int(pid),
        }

    return info


import csv
import pathlib
from datetime import datetime

def parse_powerjoular_csv(
    csv_path: pathlib.Path,
    host_cpu_cores: int = 4,
):
    """
    Parses a PowerJoular per-process CSV file.

    Output format:
    [
      {
        "ts": "...",
        "cpu_cores_used": float,
        "cpu_percent_host": float,
        "cpu_power_watt": float
      }
    ]
    """

    rows = []

    with csv_path.open() as f:
        reader = csv.DictReader(f)

        for r in reader:
            ts = (
                datetime
                .fromisoformat(r["Date"])
                .replace(microsecond=0)
                .isoformat()
            )

            cpu_cores = float(r["CPU Utilization"])
            cpu_percent_host = (cpu_cores / host_cpu_cores) * 100

            rows.append({
                "ts": ts,
                "cpu_cores_used": cpu_cores,
                "cpu_percent_host": cpu_percent_host,
                "cpu_power_watt": float(r["CPU Power"]),
            })

    return rows



# ---------------------------------------------------------------------------
# Main experiment runner
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--prom", default="http://192.168.1.237:9090")
    ap.add_argument("--jaeger", default="http://192.168.1.237:16686")
    ap.add_argument("--shelly", default=None)
    ap.add_argument("--hz", type=float, default=1.0)
    ap.add_argument("--out-root", default="GreenMicrobrenchFramework/artifacts")
    ap.add_argument("--services", nargs="*", default=[])
    ap.add_argument("--step", default="5s")
    ap.add_argument("--window", default="1m")
    args = ap.parse_args()

    # -----------------------------------------------------------------------
    # Scenario loading and output directory
    # -----------------------------------------------------------------------

    with open(args.scenario) as f:
        scenario = yaml.safe_load(f)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = scenario.get("name") or pathlib.Path(args.scenario).stem
    out_dir = pathlib.Path(args.out_root) / f"{ts}_{name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Shelly power meter
    # -----------------------------------------------------------------------
    # Design choice:
    # Shelly starts 3 seconds BEFORE the workload and stops 3 seconds AFTER.
    # This guarantees:
    # - sensor warm-up
    # - capture of startup / teardown energy
    # - improved temporal robustness

    shelly = None
    shelly_file = out_dir / "power.jsonl"

    if args.shelly:
        shelly = ShellyAdapter(args.shelly)
        shelly.start(out_path=str(shelly_file), hz=args.hz)
        print("[INFO] Shelly warm-up (3s before experiment)")
        time.sleep(3)

    # -----------------------------------------------------------------------
    # Docker runtime info (PID mapping)
    # -----------------------------------------------------------------------

    RASPBERRY_HOST = "ali@192.168.1.237"
    SERVICE_RUNTIME_MAP = get_container_runtime_info(RASPBERRY_HOST)

    # -----------------------------------------------------------------------
    # PowerJoular startup on Raspberry Pi
    # -----------------------------------------------------------------------

    duration_sec = parse_duration(scenario["run_time"])
    remote_power_dir = f"/home/ali/Desktop/power_logs/{ts}_{name}"

    pid_list = " ".join(str(v["pid"]) for v in SERVICE_RUNTIME_MAP.values())

    ssh_cmd = [
        "ssh",
        RASPBERRY_HOST,
        f"~/Desktop/start_powerjoular_pids.sh "
        f"{duration_sec} {remote_power_dir} {pid_list}"
    ]

    print("[INFO] Starting PowerJoular on Raspberry Pi")
    sp.Popen(ssh_cmd)

    # -----------------------------------------------------------------------
    # Workload execution (Locust)
    # -----------------------------------------------------------------------

    start_iso = iso_now()
    locust = LocustAdapter()

    try:
        locust_artifacts = locust.run(
            locustfile=f"GreenMicrobrenchFramework/load/locust/{scenario['locustfile']}",
            host=scenario["host"],
            users=int(scenario["users"]),
            spawn_rate=int(scenario["spawn_rate"]),
            run_time=str(scenario["run_time"]),
            out_dir=str(out_dir),
        )
    except Exception as e:
        locust_artifacts = {"error": str(e)}

    end_iso = iso_now()

    # -----------------------------------------------------------------------
    # Shelly cooldown (post-experiment)
    # -----------------------------------------------------------------------

    if shelly:
        print("[INFO] Shelly cool-down (3s after experiment)")
        time.sleep(3)
        shelly.stop()

    # -----------------------------------------------------------------------
    # Retrieve and parse PowerJoular per-PID data
    # -----------------------------------------------------------------------
    # Design choice:
    # PowerJoular CSVs are converted into a structured JSON format
    # to simplify:
    # - aggregation
    # - alignment with Shelly
    # - service-level attribution

    powerjoular_data = {}
    local_pj_dir = out_dir / "power_joular_data"
    local_pj_dir.mkdir(exist_ok=True)

    for service, info in SERVICE_RUNTIME_MAP.items():
        pid = info["pid"]
        remote_file = f"{remote_power_dir}/consumption-{pid}.csv"
        local_file = local_pj_dir / f"consumption-{pid}.csv"

        try:
            sp.check_call([
                "scp",
                f"{RASPBERRY_HOST}:{remote_file}",
                str(local_file)
            ])
            powerjoular_data[service] = parse_powerjoular_csv(local_file)
        except Exception as e:
            print(f"[WARN] PowerJoular data missing for {service}: {e}")

    pj_json = out_dir / "power_joular_data.json"
    with pj_json.open("w") as f:
        json.dump(powerjoular_data, f, indent=2)

    # -----------------------------------------------------------------------
    # Prometheus, Jaeger and analysis (unchanged logic)
    # -----------------------------------------------------------------------

    prom = PrometheusAdapter(args.prom)
    cadv = CAdvisorAdapter(prom)

    # -----------------------------------------------------------------------
    # CPU fraction over the entire experiment period (via cAdvisor/Prometheus)
    # -----------------------------------------------------------------------
    cpu_frac = cadv.cpu_map_fraction_over_period(
        start_iso,
        end_iso,
        step=args.step,
        service_runtime_map=SERVICE_RUNTIME_MAP
    )
    cpu_frac_file = out_dir / "prom_cpu_by_service.json"
    with cpu_frac_file.open("w") as f:
        json.dump(cpu_frac, f, indent=2)
    
    # -----------------------------------------------------------------------
    # CPU % timeseries per container on Raspberry Pi (via cAdvisor/Prometheus)
    # -----------------------------------------------------------------------
    # Design choice:
    # We export a per-service CPU% time series to:
    # - correlate workload phases with CPU usage
    # - enable per-service energy attribution (CPU fraction over time)
    # - debug anomalies (e.g., "unknown"/"localhost" labels)
    #
    # This artifact is independent from PowerJoular 

    cpu_ts = cadv.cpu_usage_raspberry_per_service_timeseries(
        start_iso=start_iso,
        end_iso=end_iso,
        service_runtime_map=SERVICE_RUNTIME_MAP,
    )

    cpu_ts_file = out_dir / "cpu_percent_raspberry_per_service_timeseries.json"
    with cpu_ts_file.open("w") as f:
        json.dump(cpu_ts, f, indent=2)

    print(f"[INFO] Written {cpu_ts_file}")
    

    
    # -----------------------------------------------------------------------
    # Prometheus core metrics export
    # -----------------------------------------------------------------------
    prom_files = {
        "requests": str(out_dir / "prom_requests_per_service.json"),
        "p95": str(out_dir / "prom_p95_latency_per_service.json"),
        "cpu": str(out_dir / "prom_cpu_by_service.json"),
        "cpu_percent_raspberry_per_service_timeseries": str(cpu_ts_file),
    }

    export_core_series(prom, start_iso, end_iso, args.step, prom_files, args.window)

    jaeger = JaegerAdapter(args.jaeger)
    traces = jaeger.sample_traces(args.services, start_iso, end_iso)

    with (out_dir / "jaeger_traces_sample.json").open("w") as f:
        json.dump(traces, f, indent=2)


    # -----------------------------------------------------------------------
    # Summary file (high-level experiment overview)
    # -----------------------------------------------------------------------
    # This file is meant for human inspection and quick debugging.
    # It is NOT directly consumed by analyze_run, but is referenced
    # in the manifest.

    summary = {
        "scenario": name,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "locust": locust_artifacts,
        "shelly_jsonl": str(shelly_file) if shelly else None,
        "cpu_fraction": cpu_frac,
        "cpu_percent_raspberry_per_service_timeseries": str(cpu_ts_file),
        "power_joular_data_json": str(pj_json),
    }

    summary_file = out_dir / "summary.json"
    with summary_file.open("w") as f:
        json.dump(summary, f, indent=2)

  # -----------------------------------------------------------------------
    # Parse Shelly JSONL samples
    # -----------------------------------------------------------------------

    def normalize_shelly_timestamp(ts: str) -> str:
        """
        Shelly RPC timestamps are reported in UTC but are actually
        local time without DST handling.
        A +1h correction is applied to align them with system UTC.
        """
        dt = datetime.fromisoformat(ts)
        dt = dt + timedelta(hours=1)
        return dt.replace(microsecond=0, tzinfo=timezone.utc).isoformat()


    shelly_samples = []

    if shelly and shelly_file.exists():
        with shelly_file.open() as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue

                if "power_w" not in rec or "ts" not in rec:
                    continue

                # Apply timezone correction (Shelly is 1h behind)
                rec["ts"] = normalize_shelly_timestamp(rec["ts"])

                shelly_samples.append(rec)
    # -----------------------------------------------------------------------
    # Attribute Shelly power to services (PowerJoular-like model)
    # -----------------------------------------------------------------------
    # Design choice:
    # The total electrical power measured by the Shelly device is attributed
    # to individual services proportionally to their CPU usage, as reported
    # by cAdvisor. This follows the same proportional attribution model
    # adopted by PowerJoular for per-process power estimation.
    #
    # The result is a per-service time series enriched with an additional
    # field:
    #   - estimated_power_from_shelly_watt
    #
    # This artifact enables:
    # - service-level energy analysis
    # - comparison with PowerJoular
    # - validation of the attribution model

    shelly_attributed_cpu_ts = None

    if shelly and shelly_samples:
        shelly_attributed_cpu_ts = attribute_shelly_power_to_services(
            cadvisor_by_service=cpu_ts,
            shelly_samples=shelly_samples,
            max_time_skew_s=2.0,
        )

        shelly_attributed_file = (
            out_dir / "cpu_timeseries_with_shelly_power_per_service.json"
        )

        with shelly_attributed_file.open("w") as f:
            json.dump(shelly_attributed_cpu_ts, f, indent=2)

        print(f"[INFO] Written {shelly_attributed_file}")
    else:
        print("[WARN] Shelly data not available, skipping power attribution")


    
    # -----------------------------------------------------------------------
    # Manifest file (REQUIRED by analyze_run)
    # -----------------------------------------------------------------------
    # The manifest is the formal contract between:
    # - the experiment runner (this script)
    # - the analysis pipeline (analyze_run)
    #
    # If this file is missing or incomplete, analyze_run WILL fail.

    manifest = {
        "root": str(out_dir),
        "files": {
            "locust_stats": locust_artifacts.get("stats_csv"),
            "locust_history": locust_artifacts.get("stats_history_csv"),
            "locust_failures": locust_artifacts.get("failures_csv"),
            "locust_report": locust_artifacts.get("report_html"),

            "shelly_jsonl": str(shelly_file) if shelly else None,

            "prom_requests": prom_files["requests"],
            "prom_p95": prom_files["p95"],
            "prom_cpu": prom_files["cpu"],
            "prom_cpu_timeseries": str(cpu_ts_file),

            "power_joular_data": str(pj_json),
            "summary": str(summary_file),
            "jaeger_sample": str(out_dir / "jaeger_traces_sample.json"),
        }
    }

    with (out_dir / "manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2)

    # -----------------------------------------------------------------------
    # Run analysis phase
    # -----------------------------------------------------------------------
    # analyze_run will:
    # - read manifest.json
    # - compute derived metrics
    # - write analysis_summary.json

    #analyze_run(str(out_dir))


if __name__ == "__main__":
    sys.exit(main())
# ---------------------------------------------------------------------------