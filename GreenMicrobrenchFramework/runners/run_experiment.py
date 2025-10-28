import argparse, json, os, sys, time, datetime, pathlib, yaml
from GreenMicrobrenchFramework.adapters.load.locust_adapter import LocustAdapter
from GreenMicrobrenchFramework.adapters.power.shelly_adapter import ShellyAdapter
from GreenMicrobrenchFramework.adapters.metrics.prometheus_adapter import PrometheusAdapter
from GreenMicrobrenchFramework.adapters.resources.cadvisor_adapter import CAdvisorAdapter
from GreenMicrobrenchFramework.adapters.metrics.prometheus_export import export_core_series
from GreenMicrobrenchFramework.adapters.traces.jaeger_adapter import JaegerAdapter

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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--prom", default="http://localhost:9090")
    ap.add_argument("--jaeger", default="http://localhost:16686")
    ap.add_argument("--shelly", default=None)
    ap.add_argument("--hz", type=float, default=1.0)
    ap.add_argument("--out-root", default="GreenMicrobrenchFramework/artifacts")
    ap.add_argument("--services", nargs="*", default=["api-gateway","booking","search","apartment"])
    ap.add_argument("--step", default="5s")
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

    start_iso = iso_now()
    loc = LocustAdapter()
    artifacts = loc.run(
        locustfile=f"GreenMicrobrenchFramework/load/locust/{sc['locustfile']}",
        host=sc["host"],
        users=int(sc["users"]),
        spawn_rate=int(sc["spawn_rate"]),
        run_time=str(sc["run_time"]),
        out_dir=str(out_dir),
    )
    end_iso = iso_now()

    if shelly:
        time.sleep(1.0)
        shelly.stop()

    prom = PrometheusAdapter(args.prom)
    cadv = CAdvisorAdapter(prom)
    cpu_frac = cadv.cpu_fraction_over_period(start_iso, end_iso, step=args.step)

    total_wh = integrate_wh(str(shelly_file)) if args.shelly else 0.0
    energy_by_service = {k: total_wh * v for k, v in cpu_frac.items()}

    prom_files = {
        "requests": str(out_dir / "prom_requests_per_service.json"),
        "p95": str(out_dir / "prom_p95_latency_per_service.json"),
        "cpu": str(out_dir / "prom_cpu_by_service.json"),
    }
    export_core_series(prom, start_iso, end_iso, args.step, prom_files)

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

if __name__ == "__main__":
    sys.exit(main())
