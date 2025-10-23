#launch locust as a subprocess with provided parameters and returns path to the generated artifacts
import subprocess
from pathlib import Path
from typing import Dict, Iterable, Optional

class LocustAdapter:
    def run(
        self,
        *,
        locustfile: str,
        host: str,
        users: int,
        spawn_rate: int,
        run_time: str,
        out_dir: str,
        extra_args: Optional[Iterable[str]] = None
    ) -> Dict[str, str]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        cmd = [
            "locust",
            "-f", locustfile,
            "--headless",
            "--host", host,
            "-u", str(users),
            "-r", str(spawn_rate),
            "--run-time", run_time,
            "--csv", str(out / "locust"),
            "--csv-full-history",
            "--html", str(out / "report.html"),
        ]
        if extra_args:
            cmd += list(extra_args)
        subprocess.run(cmd, check=True)
        return {
            "stats_csv": str(out / "locust_stats.csv"),
            "stats_history_csv": str(out / "locust_stats_history.csv"),
            "failures_csv": str(out / "locust_failures.csv"),
            "report_html": str(out / "report.html"),
        }
