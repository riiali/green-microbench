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
            "--html", str(out / "locust_report.html"),
            "--loglevel", "DEBUG",
        ]
        if extra_args:
            cmd += list(extra_args)
        # capture stdout/stderr so caller can decide how to handle failures
        try:
            completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            out = getattr(e, "stdout", "") or ""
            err = getattr(e, "stderr", "") or ""
            raise RuntimeError(f"Locust failed (returncode={e.returncode})\nstdout:\n{out}\nstderr:\n{err}") from e
        return {
            "stats_csv": str(out / "locust_stats.csv"),
            "stats_history_csv": str(out / "locust_stats_history.csv"),
            "failures_csv": str(out / "locust_failures.csv"),
            "report_html": str(out / "locust_report.html"),
        }
