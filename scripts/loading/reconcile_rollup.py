"""Backfill / reconcile the Cassandra dashboard rollup `event_counts_by_day`.

Truth is derived from the database itself, never from the generator:
  * Cassandra: full streamed export of `events_by_id`; every record whose
    lifecycle is `active` or `deleting` counts once (the API increments at
    pending->active and decrements at deleting->deleted).
  * The current counters are exported and only the *difference* is written,
    so the script is safe to re-run: a second run applies 0 deltas, and an
    interrupted run is completed by running it again.
  * PostgreSQL is aggregated independently (GROUP BY on `events`) and compared
    with the Cassandra truth as an equivalence check of the two databases.

Run with the API idle (no concurrent CREATE/DELETE), otherwise in-flight
operations may be counted twice or missed; the final verification would show it.
Default is a dry run (a rollup-check-*.json report is still written);
pass --apply to write the deltas (rollup-reconcile-*.json).
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bulk_runtime import REPORT_DIR, ROOT, atomic_write_json, cql_copy, cqlsh, psql, stamp, stream_csv, utc_now  # noqa: E402

CATEGORIES = {"authentication", "network", "alert"}


def cassandra_truth(config):
    truth, states = {}, {}
    for _event_id, lifecycle, payload in cql_copy(config, "events_by_id", "event_id,lifecycle,payload"):
        states[lifecycle] = states.get(lifecycle, 0) + 1
        if lifecycle not in ("active", "deleting"):
            continue
        data = json.loads(payload)["data"]
        key = (data["event_date"], int(data["occurred_at"][11:13]), data["category"], int(data["severity"]))
        truth[key] = truth.get(key, 0) + 1
    return truth, states


def cassandra_counters(config):
    current = {}
    for day, hour, category, severity, events in cql_copy(config, "event_counts_by_day",
                                                         "event_date,hour,category,severity,events"):
        current[(day, int(hour), category, int(severity))] = int(events or 0)
    return current


def postgresql_truth(config):
    sql = ("COPY (SELECT event_date, extract(hour FROM occurred_at AT TIME ZONE 'UTC')::int, category, severity, "
           "count(*) FROM events GROUP BY 1, 2, 3, 4) TO STDOUT WITH (FORMAT csv)")
    return {(d, int(h), c, int(s)): int(n) for d, h, c, s, n in stream_csv(psql(config, sql))}


def apply(config, deltas):
    lines = []
    for (day, hour, category, severity), delta in sorted(deltas.items()):
        if category not in CATEGORIES or not (0 <= hour < 24) or not (1 <= severity <= 5) or len(day) != 10:
            raise SystemExit(f"FAIL: refusing unexpected rollup key {(day, hour, category, severity)}")
        op = f"+ {delta}" if delta > 0 else f"- {-delta}"
        lines.append(f"UPDATE cyberguard.event_counts_by_day SET events = events {op} "
                     f"WHERE event_date='{day}' AND hour={hour} AND category='{category}' AND severity={severity};")
    for start in range(0, len(lines), 2000):
        chunk = "\n".join(lines[start:start + 2000]) + "\n"
        result = subprocess.run(cqlsh(config), input=chunk.encode(), cwd=ROOT, capture_output=True, timeout=900)
        if result.returncode != 0 or any(t in result.stderr for t in (b"Exception", b"InvalidRequest", b"Error")):
            raise SystemExit("FAIL: writing rollup deltas did not complete; re-run to resume (deltas are recomputed)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the computed deltas (default: dry run)")
    parser.add_argument("--docker-config", help="optional Docker CLI config directory")
    args = parser.parse_args()
    started, report = time.perf_counter(), {"started_at": utc_now(), "apply": args.apply}

    t = time.perf_counter()
    truth, states = cassandra_truth(args.docker_config)
    report["cassandra_canonical_export_seconds"] = round(time.perf_counter() - t, 1)
    report["cassandra_lifecycle_counts"] = states
    t = time.perf_counter()
    pg = postgresql_truth(args.docker_config)
    report["postgresql_aggregate_seconds"] = round(time.perf_counter() - t, 1)
    current = cassandra_counters(args.docker_config)
    deltas = {k: truth.get(k, 0) - current.get(k, 0) for k in set(truth) | set(current)}
    deltas = {k: v for k, v in deltas.items() if v}
    report.update({
        "truth_cells": len(truth), "truth_events": sum(truth.values()),
        "counter_cells_before": len(current), "counter_events_before": sum(current.values()),
        "delta_cells": len(deltas), "delta_events": sum(deltas.values()),
        "postgresql_events": sum(pg.values()),
        "postgresql_equal_to_cassandra_truth": pg == truth,
    })
    print(f"cassandra truth: {report['truth_events']} events in {len(truth)} cells; "
          f"counters before: {report['counter_events_before']}; deltas: {len(deltas)} cells / {report['delta_events']} events")
    print(f"{'PASS' if pg == truth else 'FAIL'}: PostgreSQL aggregate equals Cassandra canonical truth "
          f"({report['postgresql_events']} vs {report['truth_events']} events)")
    ok = pg == truth
    if args.apply and deltas:
        t = time.perf_counter()
        apply(args.docker_config, deltas)
        report["apply_seconds"] = round(time.perf_counter() - t, 1)
    after = cassandra_counters(args.docker_config) if args.apply else current
    after = {k: v for k, v in after.items() if v}
    equal = after == truth
    report["counters_equal_truth_after"] = equal
    report["counter_events_after"] = sum(after.values())
    label = "PASS" if equal else ("FAIL" if args.apply else "DRIFT (dry run; re-run with --apply)")
    print(f"{label}: counters equal canonical truth")
    ok = ok and (equal or not args.apply)
    report["seconds"] = round(time.perf_counter() - started, 1)
    # Dry runs are recorded too (evidence per dataset size); only --apply writes to the database.
    out = REPORT_DIR / f"rollup-{'reconcile' if args.apply else 'check'}-{stamp()}.json"
    atomic_write_json(out, report)
    print(f"report: {out.relative_to(ROOT).as_posix()}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
