"""Resource watchdog for long bulk loads: stops the loader cleanly before the host is at risk.

Every --interval seconds it samples, without touching any data:
  * host (Windows) available RAM and free disk on the drive that holds the Docker VM;
  * Docker VM memory and swap (/proc/meminfo seen from the Cassandra container);
  * container health, OOM-kill flag and restarts (docker inspect);
  * Cassandra heap use and pending compactions (nodetool info / compactionstats);
  * API storage probe (/api/health/storage).

When a limit is exceeded for --patience consecutive samples (or immediately for OOM,
unhealthy container or low disk), it creates the stop file. `load_bulk.py --stop-file`
checks that file at every chunk boundary and stops with its checkpoint intact, so the
load can resume later from the same point. Samples go to an NDJSON file (ignored by Git).

    python scripts/loading/watchdog.py --stop-file data/generated/cyberguard-bulk-v1/STOP
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bulk_runtime import ROOT, STATE_DIR, append_line, compose_exec, docker, power_state, stamp, utc_now  # noqa: E402

CONTAINERS = ("cyberguard-cassandra-1", "cyberguard-postgresql-1", "cyberguard-api")


def run(command: list[str], timeout: int = 60) -> str:
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=timeout)
        return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def sample(config: str | None) -> dict:
    out = {"t": utc_now()}
    try:
        import psutil
        out["host_available_mib"] = round(psutil.virtual_memory().available / 2**20)
        out["host_cpu_percent"] = psutil.cpu_percent(interval=None)
    except ImportError:
        pass
    out["disk_free_gib"] = round(shutil.disk_usage(ROOT.anchor).free / 2**30, 1)
    out["power"] = power_state()
    meminfo = run(compose_exec(config, "cassandra", "cat", "/proc/meminfo"))
    values = {k: int(v) for k, v in re.findall(r"^(\w+):\s+(\d+) kB", meminfo, re.M)}
    if values:
        out["vm_available_mib"] = values.get("MemAvailable", 0) // 1024
        out["vm_swap_used_mib"] = (values.get("SwapTotal", 0) - values.get("SwapFree", 0)) // 1024
    containers = {}
    for name in CONTAINERS:
        raw = run(docker(config) + ["inspect", "--format",
                                    "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|"
                                    "{{.State.OOMKilled}}|{{.RestartCount}}", name])
        if raw.strip():
            status, health, oom, restarts = raw.strip().split("|")
            containers[name] = {"status": status, "health": health or None, "oom_killed": oom == "true",
                                "restarts": int(restarts or 0)}
    out["containers"] = containers
    info = run(compose_exec(config, "cassandra", "nodetool", "info"))
    heap = re.search(r"Heap Memory \(MB\)\s*:\s*([\d.]+)\s*/\s*([\d.]+)", info)
    if heap:
        out["cassandra_heap_percent"] = round(100 * float(heap.group(1)) / float(heap.group(2)), 1)
    pending = re.search(r"pending tasks\s*:?\s*(\d+)", run(compose_exec(config, "cassandra", "nodetool",
                                                                          "compactionstats")), re.I)
    out["cassandra_pending_compactions"] = int(pending.group(1)) if pending else None
    try:
        with urllib.request.urlopen("http://127.0.0.1:3000/api/health/storage", timeout=10) as response:
            out["api_storage"] = response.status
    except urllib.error.HTTPError as error:
        out["api_storage"] = error.code
    except (urllib.error.URLError, OSError):
        out["api_storage"] = None
    return out


def problems(s: dict, args) -> tuple[list[str], list[str]]:
    """(immediate, sustained) problems for one sample."""
    immediate, sustained = [], []
    if s.get("disk_free_gib", 1e9) < args.min_disk_gib:
        immediate.append(f"free disk {s['disk_free_gib']} GiB < {args.min_disk_gib}")
    power = s.get("power") or {}
    if power.get("on_ac_power") is False and power.get("battery_percent", 100) < args.min_battery_percent:
        # A dead battery would kill the Docker VM; Cassandra acknowledges before its periodic commitlog fsync.
        immediate.append(f"on battery at {power['battery_percent']}% < {args.min_battery_percent}%")
    for name, c in s.get("containers", {}).items():
        if c["oom_killed"]:
            immediate.append(f"{name} was OOM-killed")
        if name != "cyberguard-api" and (c["status"] != "running" or c["health"] == "unhealthy"):
            immediate.append(f"{name} {c['status']}/{c['health']}")
    if s.get("host_available_mib", 1e9) < args.min_host_mib:
        sustained.append(f"host available RAM {s['host_available_mib']} MiB < {args.min_host_mib}")
    if s.get("vm_available_mib", 1e9) < args.min_vm_mib:
        sustained.append(f"Docker VM available RAM {s['vm_available_mib']} MiB < {args.min_vm_mib}")
    if s.get("vm_swap_used_mib", 0) > args.max_swap_mib:
        sustained.append(f"Docker VM swap {s['vm_swap_used_mib']} MiB > {args.max_swap_mib}")
    if s.get("cassandra_heap_percent", 0) > args.max_heap_percent:
        sustained.append(f"Cassandra heap {s['cassandra_heap_percent']}% > {args.max_heap_percent}%")
    if s.get("api_storage") not in (200, None):
        sustained.append(f"API storage probe HTTP {s['api_storage']}")
    return immediate, sustained


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument("--patience", type=int, default=4, help="consecutive bad samples before stopping")
    parser.add_argument("--min-host-mib", type=int, default=200)
    parser.add_argument("--min-vm-mib", type=int, default=150)
    parser.add_argument("--max-swap-mib", type=int, default=1536)
    parser.add_argument("--max-heap-percent", type=float, default=92.0)
    parser.add_argument("--min-disk-gib", type=float, default=40.0)
    parser.add_argument("--min-battery-percent", type=float, default=30.0,
                        help="stop when running on battery below this charge")
    parser.add_argument("--max-hours", type=float, default=8.0, help="exit after this long")
    parser.add_argument("--docker-config")
    args = parser.parse_args()
    log = STATE_DIR / "cyberguard-bulk-v1" / f"watchdog-{stamp()}.ndjson"
    print(f"watchdog: sampling every {args.interval:.0f}s -> {log.relative_to(ROOT)}; stop file {args.stop_file}",
          flush=True)
    streak, deadline = 0, time.monotonic() + args.max_hours * 3600
    while time.monotonic() < deadline:
        s = sample(args.docker_config)
        immediate, sustained = problems(s, args)
        streak = streak + 1 if sustained else 0
        s["problems"] = immediate + sustained
        append_line(log, s)
        if immediate or streak >= args.patience:
            reason = "; ".join(immediate + sustained)
            args.stop_file.parent.mkdir(parents=True, exist_ok=True)
            args.stop_file.write_text(json.dumps({"t": utc_now(), "reason": reason}) + "\n", encoding="utf-8")
            print(f"STOP requested: {reason}", flush=True)
            return
        if s["problems"]:
            print(f"warning ({streak}/{args.patience}): {'; '.join(s['problems'])}", flush=True)
        time.sleep(args.interval)
    print("watchdog: time limit reached without problems", flush=True)


if __name__ == "__main__":
    main()
