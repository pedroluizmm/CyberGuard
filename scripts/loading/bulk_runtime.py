"""Shared helpers for bulk loading/validation: API client, Docker, resources, files.

Nothing here prints .env values, connection options or raw driver errors.
"""
from __future__ import annotations

from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "data/generated"
REPORT_DIR = ROOT / "data/bulk/reports"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def atomic_write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".partial")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=1)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def append_line(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, separators=(",", ":")) + "\n")


def docker(config: str | None) -> list[str]:
    return ["docker"] + (["--config", config] if config else [])


def compose_exec(config: str | None, service: str, *command: str) -> list[str]:
    return docker(config) + ["compose", "exec", "-T", service, *command]


def psql(config: str | None, sql: str) -> list[str]:
    # Credentials stay inside the container environment; nothing is interpolated here.
    return compose_exec(config, "postgresql", "sh", "-c",
                        'exec psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" -X -At -v ON_ERROR_STOP=1 -c "$0"',
                        sql)


def cqlsh(config: str | None, *args: str) -> list[str]:
    return compose_exec(config, "cassandra", "cqlsh", "127.0.0.1", "9042", *args)


def stream_csv(command: list[str], **fmt):
    """Yield CSV rows from a streamed export (psql/cqlsh COPY ... TO STDOUT); nothing is stored."""
    import csv
    import io
    csv.field_size_limit(1 << 24)
    proc = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    yield from csv.reader(io.TextIOWrapper(proc.stdout, encoding="utf-8", newline=""), **fmt)
    stderr = proc.stderr.read()
    if proc.wait() != 0 or any(t in stderr for t in (b"Exception", b"Error", b"Failed")):
        raise RuntimeError(f"export failed ({command[-1][:60]}...)")


def cql_copy(config: str | None, table: str, columns: str):
    return stream_csv(cqlsh(config, "--request-timeout=120", "-e",
                            f"COPY cyberguard.{table} ({columns}) TO STDOUT WITH HEADER=false AND PAGETIMEOUT=60"),
                      escapechar="\\", doublequote=False)


def run_text(command: list[str], timeout: int = 600) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({command[len(docker(None)):][:4]}...): exit {result.returncode}")
    return result.stdout.decode("utf-8", errors="replace")


class Api:
    """Thread-local persistent HTTP/1.1 connections (keep-alive) to the local API."""

    def __init__(self, base_url: str, timeout: float = 40.0):
        parts = urlsplit(base_url)
        if parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost"):
            raise SystemExit("--base-url must be a loopback http URL")
        self.host, self.port, self.timeout = parts.hostname, parts.port or 80, timeout
        self.local = threading.local()

    def _conn(self) -> http.client.HTTPConnection:
        conn = getattr(self.local, "conn", None)
        if conn is None:
            conn = self.local.conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        return conn

    def reset(self) -> None:
        conn = getattr(self.local, "conn", None)
        if conn is not None:
            conn.close()
        self.local.conn = None

    def request(self, method: str, path: str, body: bytes | None = None):
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn = self._conn()
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
        except (OSError, http.client.HTTPException):
            self.reset()
            raise
        if response.getheader("Connection", "").lower() == "close":
            self.reset()
        return response.status, (json.loads(raw) if raw else None)


_SIZE = re.compile(r"([\d.]+)\s*([KMGT]?i?B)", re.I)
_UNITS = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kib": 1024, "mib": 1024**2, "gib": 1024**3,
          "tib": 1024**4}


def parse_size(text: str) -> int:
    match = _SIZE.search(text)
    return int(float(match.group(1)) * _UNITS[match.group(2).lower()]) if match else 0


class ResourceSampler(threading.Thread):
    """Samples `docker stats` for the project containers and host free RAM."""

    def __init__(self, config: str | None, out: Path, interval: float = 10.0):
        super().__init__(daemon=True)
        self.config, self.out, self.interval = config, out, interval
        self.stop_event = threading.Event()
        self.samples = 0
        self.summary: dict = {}
        self.host_min_available = None

    def sample_once(self) -> dict:
        result = subprocess.run(docker(self.config) + ["stats", "--no-stream", "--format", "{{json .}}"],
                                cwd=ROOT, capture_output=True, timeout=60)
        containers = {}
        for line in result.stdout.decode("utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            name = row.get("Name", "")
            if not name.startswith("cyberguard"):
                continue
            used, _, limit = row.get("MemUsage", "").partition("/")
            containers[name] = {"cpu_percent": float(row.get("CPUPerc", "0%").rstrip("%") or 0),
                                "mem_bytes": parse_size(used), "mem_limit_bytes": parse_size(limit)}
        sample = {"t": utc_now(), "containers": containers}
        try:
            import psutil  # optional; already present on this machine
            vm = psutil.virtual_memory()
            sample["host_available_bytes"], sample["host_total_bytes"] = vm.available, vm.total
            sample["host_cpu_percent"] = psutil.cpu_percent(interval=None)
        except ImportError:
            pass
        return sample

    def record(self, sample: dict) -> None:
        self.samples += 1
        append_line(self.out, sample)
        for name, c in sample["containers"].items():
            s = self.summary.setdefault(name, {"max_cpu_percent": 0.0, "sum_cpu_percent": 0.0, "max_mem_bytes": 0,
                                                "mem_limit_bytes": c["mem_limit_bytes"], "n": 0})
            s["max_cpu_percent"] = max(s["max_cpu_percent"], c["cpu_percent"])
            s["sum_cpu_percent"] += c["cpu_percent"]
            s["max_mem_bytes"] = max(s["max_mem_bytes"], c["mem_bytes"])
            s["n"] += 1
        available = sample.get("host_available_bytes")
        if available is not None:
            self.host_min_available = available if self.host_min_available is None else min(self.host_min_available, available)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.record(self.sample_once())
            except (OSError, subprocess.SubprocessError):
                pass
            self.stop_event.wait(self.interval)

    def stop(self) -> dict:
        self.stop_event.set()
        self.join(timeout=70)
        containers = {name: {"max_cpu_percent": round(s["max_cpu_percent"], 1),
                             "avg_cpu_percent": round(s["sum_cpu_percent"] / max(1, s["n"]), 1),
                             "max_mem_mib": round(s["max_mem_bytes"] / 2**20, 1),
                             "mem_limit_mib": round(s["mem_limit_bytes"] / 2**20, 1)}
                      for name, s in self.summary.items()}
        return {"samples": self.samples, "interval_seconds": self.interval, "containers": containers,
                "host_min_available_mib": None if self.host_min_available is None
                else round(self.host_min_available / 2**20, 1),
                "note": "docker stats CPU% is relative to one vCPU (100% = one core)."}


class Timer:
    def __init__(self):
        self.started = time.perf_counter()

    def seconds(self) -> float:
        return time.perf_counter() - self.started
