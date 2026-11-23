"""Measure one dataset size of the scale campaign, always with the same sequence.

    python benchmarks/run_scale_point.py --target 2000000

With the bulk load finished and the API idle (release build, default configuration):
  1. scripts/validation/check_bulk.py --target N    full integrity check (includes nodetool flush)
  2. scripts/loading/reconcile_rollup.py            dry run: rollup == canonical truth == PostgreSQL
  3. VACUUM (ANALYZE) in PostgreSQL                 same maintenance as the 1M baseline
  4. wait until Cassandra has 0 pending compactions (no major compaction is forced)
  5. run_benchmarks.py --suite main --campaign escala --prewarm 30
  6. API restarted with POSTGRES_SYNCHRONOUS_COMMIT=off -> --suite durability --campaign escala
  7. API restarted with the default configuration (also on failure)

Any failed step stops the sequence (nothing is measured on an unvalidated dataset).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def step(title: str, command: list[str], timeout: int = 7200) -> None:
    print(f"\n=== {title}\n$ {' '.join(command)}", flush=True)
    started = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, timeout=timeout)
    print(f"--- {title}: exit {result.returncode} in {time.perf_counter() - started:.0f}s", flush=True)
    if result.returncode != 0:
        raise SystemExit(f"STOPPED at '{title}'")


def pending_compactions() -> int | None:
    result = subprocess.run(["docker", "compose", "exec", "-T", "cassandra", "nodetool", "compactionstats"],
                            cwd=ROOT, capture_output=True, timeout=120)
    match = re.search(r"pending tasks\s*:?\s*(\d+)", result.stdout.decode("utf-8", errors="replace"), re.I)
    return int(match.group(1)) if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--campaign", default="escala")
    parser.add_argument("--prewarm", type=int, default=30)
    parser.add_argument("--skip-validation", action="store_true", help="only if check_bulk already passed at this size")
    parser.add_argument("--max-wait-compactions", type=int, default=1800, help="seconds")
    args = parser.parse_args()
    if not args.skip_validation:
        step("integridade", [PY, "scripts/validation/check_bulk.py", "--target", str(args.target)])
        step("rollup (simulação)", [PY, "scripts/loading/reconcile_rollup.py"])
    step("VACUUM (ANALYZE)", ["docker", "compose", "exec", "-T", "postgresql", "sh", "-c",
                              'exec psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" -X -v ON_ERROR_STOP=1 '
                              '-c "VACUUM (ANALYZE);"'], timeout=3600)
    deadline = time.monotonic() + args.max_wait_compactions
    while (pending := pending_compactions()) not in (0, None) and time.monotonic() < deadline:
        print(f"waiting: {pending} pending Cassandra compactions", flush=True)
        time.sleep(20)
    if pending not in (0, None):
        raise SystemExit(f"STOPPED: {pending} compactions still pending")
    print("Cassandra: 0 pending compactions", flush=True)
    try:
        step("benchmark main", [PY, "benchmarks/run_benchmarks.py", "--suite", "main", "--campaign", args.campaign,
                                "--prewarm", str(args.prewarm)])
        step("API com synchronous_commit=off", [PY, "scripts/run_api.py", "stop"])
        step("API com synchronous_commit=off", [PY, "scripts/run_api.py", "start", "--pg-synchronous-commit", "off"])
        step("benchmark durability", [PY, "benchmarks/run_benchmarks.py", "--suite", "durability",
                                      "--campaign", args.campaign])
    finally:
        subprocess.run([PY, "scripts/run_api.py", "stop"], cwd=ROOT)
        subprocess.run([PY, "scripts/run_api.py", "start"], cwd=ROOT)
    print(f"\nPASS: scale point {args.target} measured (campaign '{args.campaign}')")


if __name__ == "__main__":
    main()
