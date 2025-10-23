#define minimal contracts for run load, read power and query metrics

from typing import Protocol, Dict, Any, Iterable, Optional

class LoadAdapter(Protocol):
    def run(self, *, locustfile: str, host: str, users: int, spawn_rate: int,
            run_time: str, out_dir: str, extra_args: Optional[Iterable[str]] = None) -> Dict[str, str]:
        ...

class PowerAdapter(Protocol):
    def start(self, *, out_path: str, hz: float = 1.0) -> None:
        ...
    def stop(self) -> None:
        ...

class MetricsAdapter(Protocol):
    def instant(self, query: str) -> Any:
        ...
    def range(self, query: str, start: str, end: str, step: str = "5s") -> Any:
        ...
