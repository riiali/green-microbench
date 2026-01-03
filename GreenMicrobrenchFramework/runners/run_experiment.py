import subprocess as sp
import argparse, json, os, sys, time, datetime, pathlib, yaml
from GreenMicrobrenchFramework.adapters.load.locust_adapter import LocustAdapter
from GreenMicrobrenchFramework.adapters.power.shelly_adapter import ShellyAdapter
from GreenMicrobrenchFramework.adapters.metrics.prometheus_adapter import PrometheusAdapter
from GreenMicrobrenchFramework.adapters.resources.cadvisor_adapter import CAdvisorAdapter
from GreenMicrobrenchFramework.adapters.metrics.prometheus_export import export_core_series
from GreenMicrobrenchFramework.adapters.traces.jaeger_adapter import JaegerAdapter
from GreenMicrobrenchFramework.analyzer.analyze_run import analyze_run

def iso_now():
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()

def integrate_wh(jsonl_path: str) -> float:
    p = pathlib.Path(jsonl_path)
    if not p.exists(): return 0.0
    rows = []
    with p.open() as f:
        for line in f:
            try:
                o = json.loads(line)
                if "power_w" in o:
                    rows.append((datetime.datetime.fromisoformat(o["ts"]), float(o["power_w"])))
            except Exception:
                pass
    rows.sort(key=lambda x: x[0])
    if len(rows) < 2: return 0.0
    wh = 0.0
    for (t0, w0), (t1, w1) in zip(rows[:-1], rows[1:]):
        dt_h = (t1 - t0).total_seconds() / 3600.0
        wh += ((w0 + w1) / 2.0) * dt_h
    return wh

#Helpers to get container runtime info via SSH

def get_container_runtime_info(host: str) -> dict:
    """
    Returns:
    {
      service_name: {
        container_id,
        container_id_short,
        pid
      }
    }
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
        name, cid, pid = line.strip().split()
        service = name.lstrip("/")  # "/booking" -> "booking"

        info[service] = {
            "container_id": cid,
            "container_id_short": cid[:12],
            "pid": int(pid),
        }

    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--prom", default="http://192.168.1.237:9090")
    ap.add_argument("--jaeger", default="http://192.168.1.237:16686") #change this!!!!
    ap.add_argument("--shelly", default=None)
    ap.add_argument("--hz", type=float, default=1.0)
    ap.add_argument("--out-root", default="GreenMicrobrenchFramework/artifacts")
    ap.add_argument("--services", nargs="*", default=["api-gateway","booking","search","apartment"])
    ap.add_argument("--step", default="5s")
    ap.add_argument("--window", default="1m")
    args = ap.parse_args()

    with open(args.scenario) as f:
        sc = yaml.safe_load(f)

    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    name = sc.get("name") or pathlib.Path(args.scenario).stem
    out_dir = pathlib.Path(args.out_root) / f"{ts}_{name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    shelly_file = out_dir / "power.jsonl"
    shelly = None
    if args.shelly:
        shelly = ShellyAdapter(args.shelly)
        shelly.start(out_path=str(shelly_file), hz=args.hz)
    
    # Get container PIDs on Raspberry
    RASPBERRY_HOST = "ali@192.168.1.237"
    print("[INFO] Querying Raspberry for Docker runtime info...")
    SERVICE_RUNTIME_MAP = get_container_runtime_info(RASPBERRY_HOST)
    print(json.dumps(SERVICE_RUNTIME_MAP, indent=2))

    # Duration in seconds (from YAML scenario)
    run_time = sc["run_time"]  # "5m", "300s", etc.

    def parse_duration(rt: str) -> int:
        """Converts '5m', '300s', '1h' into seconds."""
        if rt.endswith("s"):
            return int(rt[:-1])
        if rt.endswith("m"):
            return int(rt[:-1]) * 60
        if rt.endswith("h"):
            return int(rt[:-1]) * 3600
        raise ValueError(f"Unknown duration format: {rt}")

    duration_sec = parse_duration(run_time)

    # Output dir on Raspberry
    remote_out = f"/home/ali/Desktop/power_logs/{ts}_{name}"#TODO: da passare direttamente quando si lancia il programma

    # Build SSH command
    pid_values = " ".join(
        str(v["pid"]) for v in SERVICE_RUNTIME_MAP.values()
    )

    ssh_cmd = [
        "ssh",
        RASPBERRY_HOST,
        f"chmod +x ~/Desktop/pj_run.sh && "
        f"~/Desktop/start_powerjoular_pids.sh {duration_sec} {remote_out} {pid_values}"
    ]

    print("[INFO] Starting PowerJoular on Raspberry via SSH...")
    pj_proc = sp.Popen(ssh_cmd, shell=True)


    start_iso = iso_now()
    loc = LocustAdapter()
    artifacts = None
    loc_error = None
    try:
        artifacts = loc.run(
            locustfile=f"GreenMicrobrenchFramework/load/locust/{sc['locustfile']}",
            host=sc["host"],
            users=int(sc["users"]),
            spawn_rate=int(sc["spawn_rate"]),
            run_time=str(sc["run_time"]),
            out_dir=str(out_dir),
        )
    except Exception as e:
        # record the error but continue with the rest of the experiment
        loc_error = str(e)
        artifacts = {"error": loc_error}
        print(f"[ERROR] Locust run failed: {loc_error}")
    finally:
        end_iso = iso_now()
        if shelly:
            time.sleep(1.0)
            try:
                shelly.stop()
            except Exception as e:
                print(f"[WARN] Shelly stop failed: {e}")

    prom = PrometheusAdapter(args.prom)
    cadv = CAdvisorAdapter(prom)
    cpu_frac = cadv.cpu_map_fraction_over_period(
        start_iso,
        end_iso,
        step=args.step,
        service_runtime_map=SERVICE_RUNTIME_MAP
    )

    total_wh = integrate_wh(str(shelly_file)) if args.shelly else 0.0
    energy_by_service = {k: total_wh * v for k, v in cpu_frac.items()}


    prom_files = {
        "requests": str(out_dir / "prom_requests_per_service.json"),
        "p95": str(out_dir / "prom_p95_latency_per_service.json"),
        "cpu": str(out_dir / "prom_cpu_by_service.json"),
    }

    export_core_series(prom, start_iso, end_iso, args.step, prom_files, args.window)
    with open(prom_files["cpu"], "w") as f: json.dump(cpu_frac, f)

    ja = JaegerAdapter(args.jaeger)
    traces_sample = ja.sample_traces(args.services, start_iso, end_iso, limit_per_service=20)
    with (out_dir / "jaeger_traces_sample.json").open("w") as f:
        json.dump(traces_sample, f)

    summary = {
        "scenario": name,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "locust": artifacts,
        "shelly_jsonl": str(shelly_file) if args.shelly else None,
        "total_energy_wh": total_wh,
        "cpu_fraction": cpu_frac,
        "energy_by_service_wh": energy_by_service,
    }
    with (out_dir / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2)

    manifest = {
        "root": str(out_dir),
        "files": {
            "locust_stats": artifacts.get("stats_csv"),
            "locust_history": artifacts.get("stats_history_csv"),
            "locust_failures": artifacts.get("failures_csv"),
            "locust_report": artifacts.get("report_html"),
            "shelly_jsonl": str(shelly_file) if args.shelly else None,
            "prom_requests": prom_files["requests"],
            "prom_p95": prom_files["p95"],
            "prom_cpu": prom_files["cpu"],
            "jaeger_sample": str(out_dir / "jaeger_traces_sample.json"),
            "summary": str(out_dir / "summary.json"),
        }
    }
    with (out_dir / "manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2)

    print(json.dumps(summary, indent=2))

    try:
        analyze_run(str(out_dir))
    except Exception as e:
        print(f"[WARN] analysis failed: {e}")

if __name__ == "__main__":
    sys.exit(main())
