"""CyberGuard comparative benchmark: PostgreSQL vs Cassandra over the same 1M-event dataset.

Protocol (details in benchmarks/README.md and docs/benchmark-methodology.md):
  * Same API binary (release), same request, same parameters for both sources.
  * Per operation: W warm-up iterations then N measured iterations per source.
    Iterations are interleaved in pairs and the order alternates (PG,CS / CS,PG)
    to spread drift, background compaction/autovacuum and cache effects.
  * Two latencies per request: `http_ms` (client, monotonic perf_counter around
    the full keep-alive HTTP exchange) and `db_ms` (server `Server-Timing`: time
    inside the storage adapter = driver + network to the container + database +
    row decoding; HTTP and JSON serialization excluded).
  * Every response body is hashed; a pair only counts as equivalent if both
    databases returned byte-identical JSON (same business result).
  * Warm cache: warm-up runs are recorded (phase=warmup) but excluded from the
    statistics; the first warm-up observation is reported separately.

Suites:
  main  E1 READ por ID, E2 Q1 dispositivo, E3 Q2/Q3, E4 painel agregado,
        E5 controle PostgreSQL com view materializada, E6 escrita CRUD.
  n1    E2/E3 only, for an API started with CASSANDRA_READ_CONCURRENCY=1
        (original sequential N+1 behaviour) - the "before" of the optimisation.
  writes  E6 only, default durability (PostgreSQL synchronous_commit=on).
  durability  E6 only, for an API started with POSTGRES_SYNCHRONOUS_COMMIT=off:
        both databases then acknowledge commits before the log is fsynced
        (PostgreSQL may lose ~3 x wal_writer_delay ~ 600 ms, Cassandra up to the
        10 s commitlog period on a crash; neither corrupts data).
E6 requires the API's PostgreSQL pool (POSTGRES_POOL_SIZE) to be >= the number
of concurrent write clients; otherwise PostgreSQL requests would queue for a
connection while the Cassandra driver multiplexes, biasing the comparison.

Writes (E6) use fresh UUIDs in the reserved window 2002-01-07..14 and delete
their own events afterwards through the API; the 1M dataset is never modified.
Outputs: benchmarks/results/<stamp>-<suite>/{raw.csv,raw_writes.csv,environment.json,run.json}
and benchmarks/results/summary.json (latest run of each suite, read by the dashboard).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
import platform
import random
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/loading"))
sys.path.insert(0, str(ROOT / "scripts/generation"))
import bulk_events as bulk  # noqa: E402
from bulk_runtime import atomic_write_json, cqlsh, docker, psql, run_text, stamp, utc_now  # noqa: E402

RESULTS = ROOT / "benchmarks/results"
SOURCES = ("postgresql", "cassandra")
MANIFEST = ROOT / "data/bulk" / f"{bulk.DATASET}.manifest.json"
WRITE_WINDOW = ("2002-01-07T00:00:00Z", "2002-01-14T00:00:00Z")


# ----------------------------------------------------------------------------- HTTP
class Client:
    """One keep-alive HTTP/1.1 connection per thread; returns status, headers, raw body, ms."""

    def __init__(self, host: str = "127.0.0.1", port: int = 3000):
        self.host, self.port, self.local = host, port, threading.local()

    def _conn(self):
        if getattr(self.local, "conn", None) is None:
            self.local.conn = http.client.HTTPConnection(self.host, self.port, timeout=60)
        return self.local.conn

    def request(self, method: str, path: str, body: dict | None = None):
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        conn = self._conn()
        try:
            start = time.perf_counter_ns()
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            elapsed = (time.perf_counter_ns() - start) / 1e6
        except (OSError, http.client.HTTPException):
            conn.close()
            self.local.conn = None
            raise
        timing = response.getheader("Server-Timing", "")
        match = re.search(r"dur=([\d.]+)", timing)
        return response.status, raw, elapsed, (float(match.group(1)) if match else None)

    def json(self, path: str):
        status, raw, _, _ = self.request("GET", path)
        return status, (json.loads(raw) if raw else None)


def digest(raw: bytes) -> str:
    try:
        canonical = json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")).encode()
    except ValueError:
        canonical = raw
    return hashlib.sha256(canonical).hexdigest()[:16]


# ------------------------------------------------------------------- operations
def sample_ids(count: int) -> list[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    generator = bulk.BulkGenerator(manifest["seed"])
    n = manifest["profiles"]["1000000"]["logical_events"]
    return [generator.event((k * 104_729 + 7_919) % n)["event_id"] for k in range(count)]


def query_path(source: str, kind: str, **params) -> str:
    return f"/api/{source}/queries/{kind}?" + urlencode(params)


def overview_path(source: str, **params) -> str:
    return f"/api/{source}/stats/overview?" + urlencode(params)


def operations(suite: str, total_iterations: int) -> list[dict]:
    hot_device = {"device_id": "ids-sensor-06", "from": "2026-10-24T00:00:00Z", "to": "2026-10-31T00:00:00Z"}
    cold_device = {"device_id": "ws-hr-0050", "from": "2026-10-12T00:00:00Z", "to": "2026-10-19T00:00:00Z"}
    hot_ip = {"source_ip": "2001:db8:bad:4::6", "from": "2026-10-24T00:00:00Z", "to": "2026-10-31T00:00:00Z"}
    hot_alerts = {"severity": 3, "from": "2026-10-13T00:00:00Z", "to": "2026-10-15T00:00:00Z"}
    week = {"from": "2026-10-26T00:00:00Z", "to": "2026-11-02T00:00:00Z"}
    day = {"from": "2026-10-27T00:00:00Z", "to": "2026-10-28T00:00:00Z"}
    ops = [
        {"id": "q1_device_hot_page", "experiment": "E2", "title": "Q1 · linha do tempo de dispositivo quente (1ª página, 100)",
         "params": {**hot_device, "page_size": 100},
         "path": lambda s, i: query_path(s, "device", **hot_device, page_size=100)},
        {"id": "q1_device_hot_10pages", "experiment": "E2", "title": "Q1 · 10 páginas seguidas (1 000 eventos, cursor)",
         "params": {**hot_device, "page_size": 100, "pages": 10},
         "pages": 10, "path": lambda s, i: query_path(s, "device", **hot_device, page_size=100)},
        {"id": "q1_device_cold_page", "experiment": "E2", "title": "Q1 · dispositivo pouco ativo (janela 7 dias)",
         "params": {**cold_device, "page_size": 100},
         "path": lambda s, i: query_path(s, "device", **cold_device, page_size=100)},
        {"id": "q2_ip_hot_page", "experiment": "E3", "title": "Q2 · investigação de IP de campanha (1ª página, 100)",
         "params": {**hot_ip, "page_size": 100},
         "path": lambda s, i: query_path(s, "ip", **hot_ip, page_size=100)},
        {"id": "q3_alerts_page", "experiment": "E3", "title": "Q3 · alertas de severidade 3 (1ª página, 100)",
         "params": {**hot_alerts, "page_size": 100},
         "path": lambda s, i: query_path(s, "alerts", **hot_alerts, page_size=100)},
    ]
    if suite == "n1":
        return ops
    ids = sample_ids(total_iterations)
    return [
        {"id": "e1_read_by_id", "experiment": "E1", "title": "READ por UUID (registro canônico / chave primária)",
         "params": {"ids": "amostra determinística distinta por iteração (mesma lista nos dois bancos)"},
         "path": lambda s, i: f"/api/{s}/events/{ids[i]}"},
        *ops,
        {"id": "overview_7d", "experiment": "E4", "title": "Painel · 7 dias, todas as categorias (168 h)",
         "params": week, "path": lambda s, i: overview_path(s, **week)},
        {"id": "overview_1d", "experiment": "E4", "title": "Painel · 1 dia, todas as categorias (24 h)",
         "params": day, "path": lambda s, i: overview_path(s, **day)},
        {"id": "overview_7d_alerts", "experiment": "E4", "title": "Painel · 7 dias, somente alertas",
         "params": {**week, "category": "alert"}, "path": lambda s, i: overview_path(s, **week, category="alert")},
    ]


def execute(client: Client, op: dict, source: str, iteration: int):
    """Returns (status, http_ms, db_ms, items, digest). Multi-page ops follow the cursor."""
    path = op["path"](source, iteration)
    pages = op.get("pages", 1)
    total_http, total_db, items, hasher, status = 0.0, 0.0, 0, hashlib.sha256(), 0
    for _ in range(pages):
        status, raw, http_ms, db_ms = client.request("GET", path)
        total_http += http_ms
        total_db += db_ms or 0.0
        if status != 200:
            return status, total_http, None, items, None
        body = json.loads(raw)
        hasher.update(digest(raw).encode())
        if isinstance(body, dict) and "items" in body:
            items += len(body["items"])
            if not body.get("next_cursor"):
                break
            path = op["path"](source, iteration) + "&" + urlencode({"cursor": body["next_cursor"]})
        elif isinstance(body, dict) and "total" in body:
            items = body["total"]
    return status, total_http, total_db, items, hasher.hexdigest()[:16]


# ------------------------------------------------------------------- statistics
def stats(values: list[float]) -> dict | None:
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    q = statistics.quantiles(values, n=20, method="inclusive") if len(values) > 1 else [values[0]] * 19
    quart = statistics.quantiles(values, n=4, method="inclusive") if len(values) > 1 else [values[0]] * 3
    return {"n": len(values), "median": round(statistics.median(values), 3), "p25": round(quart[0], 3),
            "p75": round(quart[2], 3), "p95": round(q[18], 3), "min": round(values[0], 3),
            "max": round(values[-1], 3), "mean": round(statistics.fmean(values), 3),
            "stdev": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0}


def summarize_op(op: dict, rows: list[dict]) -> dict:
    measured = [r for r in rows if r["phase"] == "measure" and r["operation"] == op["id"]]
    warm = [r for r in rows if r["phase"] == "warmup" and r["operation"] == op["id"]]
    result = {"id": op["id"], "experiment": op["experiment"], "title": op["title"], "params": op["params"],
              "sources": {}}
    for source in SOURCES:
        mine = [r for r in measured if r["source"] == source]
        first = next((r for r in warm if r["source"] == source), None)
        result["sources"][source] = {
            "http": stats([r["http_ms"] for r in mine]), "db": stats([r["db_ms"] for r in mine]),
            "errors": sum(r["status"] != 200 for r in mine),
            "items": mine[0]["items"] if mine else None,
            "first_warmup_http_ms": first["http_ms"] if first else None,
            "raw_http": [r["http_ms"] for r in mine], "raw_db": [r["db_ms"] for r in mine]}
    by_iter = {}
    for r in measured:
        by_iter.setdefault(r["iteration"], {})[r["source"]] = r
    pairs = [p for p in by_iter.values() if len(p) == 2]
    result["equivalent"] = bool(pairs) and all(p["postgresql"]["digest"] == p["cassandra"]["digest"]
                                               and p["postgresql"]["digest"] for p in pairs)
    result["paired_wins"] = {
        "postgresql": sum(p["postgresql"]["http_ms"] < p["cassandra"]["http_ms"] for p in pairs),
        "cassandra": sum(p["cassandra"]["http_ms"] < p["postgresql"]["http_ms"] for p in pairs)}
    pg, cs = result["sources"]["postgresql"]["http"], result["sources"]["cassandra"]["http"]
    if pg and cs:
        faster = "cassandra" if cs["median"] < pg["median"] else "postgresql"
        slow, fast = (pg, cs) if faster == "cassandra" else (cs, pg)
        result["faster"] = faster
        result["ratio"] = round(slow["median"] / fast["median"], 2) if fast["median"] else None
        # Robust only if the interquartile ranges do not overlap.
        result["iqr_separated"] = fast["p75"] < slow["p25"]
    return result


# ------------------------------------------------------------------- environment
def safe(command, timeout=120):
    try:
        return run_text(command, timeout=timeout).strip()
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return None


def environment(args, client: Client) -> dict:
    env = {"captured_at": utc_now(), "suite": args.suite}
    try:
        import psutil
        vm = psutil.virtual_memory()
        env["host"] = {"os": platform.platform(), "processor": platform.processor(),
                       "logical_cpus": psutil.cpu_count(), "physical_cpus": psutil.cpu_count(logical=False),
                       "ram_total_gib": round(vm.total / 2**30, 2), "ram_available_gib": round(vm.available / 2**30, 2),
                       "python": platform.python_version()}
    except ImportError:
        env["host"] = {"os": platform.platform(), "python": platform.python_version()}
    cpu = safe(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
    if cpu:
        env["host"]["cpu_model"] = cpu
    env["git"] = {"commit": safe(["git", "rev-parse", "HEAD"]),
                  "dirty_files": len((safe(["git", "status", "--porcelain"]) or "").splitlines())}
    info = safe(docker(args.docker_config) + ["info", "--format", "{{json .}}"])
    if info:
        d = json.loads(info)
        env["docker"] = {"server_version": d.get("ServerVersion"), "vm_cpus": d.get("NCPU"),
                         "vm_memory_gib": round(d.get("MemTotal", 0) / 2**30, 2), "os": d.get("OperatingSystem")}
    containers = {}
    for name in ("cyberguard-postgresql-1", "cyberguard-cassandra-1", "cyberguard-api"):
        raw = safe(docker(args.docker_config) + ["inspect", "--format",
                                                  "{{.Config.Image}}|{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}", name])
        if raw:
            image, memory, cpus = raw.split("|")
            containers[name] = {"image": image, "mem_limit_gib": round(int(memory) / 2**30, 2) if int(memory) else None,
                                "cpu_limit": int(cpus) / 1e9 if int(cpus) else None}
    env["containers"] = containers
    stats_raw = safe(docker(args.docker_config) + ["stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"])
    env["container_usage_at_start"] = [line for line in (stats_raw or "").splitlines() if line.startswith("cyberguard")]
    _, runtime = client.json("/api/runtime")
    _, health = client.json("/api/health")
    env["api"] = {"health": health, "runtime": runtime}
    pg_sql = ("SELECT json_build_object("
              "'version', version(),"
              "'settings', (SELECT json_object_agg(name, current_setting(name)) FROM pg_settings WHERE name IN "
              "('shared_buffers','work_mem','effective_cache_size','synchronous_commit','max_parallel_workers_per_gather',"
              "'random_page_cost','jit','max_connections','fsync','wal_level','maintenance_work_mem')),"
              "'indexes', (SELECT json_agg(indexdef ORDER BY indexname) FROM pg_indexes WHERE tablename='events'),"
              "'events_rows', (SELECT count(*) FROM events),"
              "'events_total_bytes', pg_total_relation_size('events'),"
              "'events_heap_bytes', pg_relation_size('events'),"
              "'database_bytes', pg_database_size(current_database()),"
              "'last_vacuum', (SELECT greatest(last_vacuum, last_autovacuum) FROM pg_stat_user_tables WHERE relname='events'))")
    pg = safe(psql(args.docker_config, pg_sql))
    env["postgresql"] = json.loads(pg) if pg else None
    cs = {}
    version = safe(cqlsh(args.docker_config, "-e", "SELECT release_version FROM system.local"))
    if version:
        cs["version"] = next((l.strip() for l in version.splitlines() if re.match(r"^\s*\d+\.\d+", l)), None)
    settings = safe(cqlsh(args.docker_config, "-e",
                          "SELECT name, value FROM system_views.settings WHERE name IN ('commitlog_sync',"
                          "'commitlog_sync_period','concurrent_reads','concurrent_writes','key_cache_size',"
                          "'row_cache_size','default_compaction','memtable_heap_space','file_cache_size')"))
    if settings:
        cs["settings"] = {p[0].strip(): p[1].strip() for p in (l.split("|") for l in settings.splitlines())
                          if len(p) == 2 and p[0].strip() not in ("name", "")}
    strategy = safe(cqlsh(args.docker_config, "-e",
                          "SELECT table_name, compaction FROM system_schema.tables WHERE keyspace_name='cyberguard'"))
    if strategy:
        cs["compaction"] = {p[0].strip(): re.search(r"'class': '([^']+)'", p[1]).group(1)
                            for p in (l.split("|", 1) for l in strategy.splitlines())
                            if len(p) == 2 and "'class'" in p[1]}
    tablestats = safe(docker(args.docker_config) + ["compose", "exec", "-T", "cassandra", "nodetool", "tablestats",
                                                    "cyberguard"])
    if tablestats:
        tables, current = {}, None
        for line in tablestats.splitlines():
            line = line.strip()
            if line.startswith("Table:"):
                current = line.split(":", 1)[1].strip()
                tables[current] = {}
            elif current and ":" in line:
                key, value = (part.strip() for part in line.split(":", 1))
                if key in ("Space used (live)", "Number of partitions (estimate)", "SSTable count",
                           "Compacted partition maximum bytes"):
                    tables[current][key] = value
        cs["tables"] = tables
    env["cassandra"] = cs
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["profiles"]["1000000"]
    env["dataset"] = {"name": bulk.DATASET, "logical_events": manifest["logical_events"],
                      "alerts": manifest["alert_events"], "window": [bulk.DATES[0], bulk.DATES[-1]]}
    return env


# ------------------------------------------------------------------- read suite
def run_reads(args, client: Client, ops: list[dict]) -> list[dict]:
    rows = []
    total = args.warmup + args.runs
    for op in ops:
        print(f"[{op['experiment']}] {op['id']}: {args.warmup} warm-up + {args.runs} measured per source", flush=True)
        for iteration in range(total):
            phase = "warmup" if iteration < args.warmup else "measure"
            order = SOURCES if iteration % 2 == 0 else SOURCES[::-1]
            for position, source in enumerate(order):
                status, http_ms, db_ms, items, body = execute(client, op, source, iteration)
                rows.append({"operation": op["id"], "experiment": op["experiment"], "source": source,
                             "phase": phase, "iteration": iteration - (args.warmup if phase == "measure" else 0),
                             "order": position, "status": status, "http_ms": round(http_ms, 3),
                             "db_ms": round(db_ms, 3) if db_ms is not None else None, "items": items,
                             "digest": body, "at": utc_now()})
                if status != 200:
                    print(f"  FAIL {source} iteration {iteration}: HTTP {status}", flush=True)
            if args.pause:
                time.sleep(args.pause)
    return rows


# ------------------------------------------------------------------- E5 control
def run_pg_control(args) -> dict:
    """PostgreSQL pre-aggregation control: materialized view read vs refresh cost (psql \\timing)."""
    ddl = (ROOT / "benchmarks/sql/pg_rollup_control.sql").read_text(encoding="utf-8")
    week = "occurred_at >= '2026-10-26T00:00:00Z' AND occurred_at < '2026-11-02T00:00:00Z'"
    on_read = ("SELECT date_bin('1 hour', occurred_at, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS hour, category, "
               f"severity, count(*) AS n FROM events WHERE {week} GROUP BY 1, 2, 3;")
    mv_read = ("SELECT hour, category, severity, n FROM bench.overview_hourly "
               "WHERE hour >= '2026-10-26T00:00:00Z' AND hour < '2026-11-02T00:00:00Z';")
    refresh = "REFRESH MATERIALIZED VIEW bench.overview_hourly;"
    script = [ddl, "\\timing on", "\\o /dev/null"]
    plan = []
    for label, sql, count in (("pg_on_read_aggregate_7d", on_read, args.warmup + args.runs),
                              ("pg_mv_read_7d", mv_read, args.warmup + args.runs),
                              ("pg_mv_refresh_full", refresh, 1 + args.refresh_runs)):
        for _ in range(count):
            script.append(sql)
            plan.append(label)
    command = docker(args.docker_config) + ["compose", "exec", "-T", "postgresql", "sh", "-c",
                                            'exec psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" -X -v ON_ERROR_STOP=1']
    result = subprocess.run(command, input="\n".join(script).encode(), cwd=ROOT, capture_output=True, timeout=3600)
    if result.returncode != 0:
        print("  FAIL: PostgreSQL control script failed", flush=True)
        return {"error": "psql_failed"}
    times = [float(m) for m in re.findall(r"Time: ([\d.]+) ms", result.stdout.decode())]
    times = times[-len(plan):]  # DDL statements before \timing produce no Time lines
    out = {"level": "psql \\timing (servidor PostgreSQL + socket local no contêiner; sem HTTP/driver)"}
    for label in dict.fromkeys(plan):
        values = [t for t, p in zip(times, plan) if p == label]
        warm = 1 if label == "pg_mv_refresh_full" else args.warmup
        out[label] = {"first_ms": values[0] if values else None, "raw_ms": values[warm:], "stats": stats(values[warm:])}
    return out


# ------------------------------------------------------------------- E6 writes
def write_events(run_id: str, count: int, seed: int) -> list[dict]:
    rnd = random.Random(seed)
    start = datetime(2002, 1, 7, tzinfo=timezone.utc)
    kinds = [("authentication", "login", 2, "failure"), ("network", "connection", 1, "blocked"),
             ("network", "traffic_anomaly", 3, "unknown"), ("alert", "potential_threat", 4, "unknown")]
    events = []
    for k in range(count):
        when = start + timedelta(milliseconds=rnd.randrange(7 * 86_400_000))
        category, event_type, severity, outcome = kinds[k % len(kinds)]
        events.append({
            "event_id": str(uuid.UUID(int=rnd.getrandbits(128), version=4)),
            "occurred_at": when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z",
            "event_date": when.date().isoformat(), "device_id": f"bench-sensor-{k % 16:02d}",
            "source_ip": f"198.51.100.{1 + k % 250}", "category": category, "event_type": event_type,
            "severity": severity, "outcome": outcome, "message": "Synthetic benchmark event (E6)",
            "metadata": {"synthetic": True, "benchmark_run": run_id, "n": k}})
    return events


def window_total(client: Client, source: str) -> int | None:
    status, body = client.json(overview_path(source, **dict(zip(("from", "to"), WRITE_WINDOW))))
    return body["total"] if status == 200 else None


def run_writes(args, client: Client, run_id: str) -> tuple[list[dict], dict]:
    for source in SOURCES:
        if window_total(client, source) != 0:
            print(f"  BLOCKED: reserved write window {WRITE_WINDOW} is not empty in {source}; E6 skipped", flush=True)
            return [], {"skipped": "reserved window not empty"}
    rows, per_run = [], []
    print(f"[E6] CRUD de escrita: {args.write_warmup} aquecimento(s) + {args.write_runs} runs x "
          f"{args.write_events} eventos, concorrência {args.write_concurrency}", flush=True)
    for r in range(args.write_warmup + args.write_runs):
        phase = "warmup" if r < args.write_warmup else "measure"
        events = write_events(run_id, args.write_events,
                              seed=int(hashlib.sha256(f"{run_id}|{r}".encode()).hexdigest()[:8], 16))
        order = SOURCES if r % 2 == 0 else SOURCES[::-1]
        for source in order:
            phase_rows = {}
            for op in ("create", "update", "delete"):
                def call(event, op=op, source=source):
                    path = f"/api/{source}/events"
                    if op == "create":
                        return client.request("POST", path, event)
                    if op == "update":
                        return client.request("PUT", f"{path}/{event['event_id']}",
                                              {"expected_revision": 1, "outcome": "blocked",
                                               "message": "Reviewed benchmark event", "metadata": event["metadata"]})
                    return client.request("DELETE", f"{path}/{event['event_id']}?expected_revision=2")
                started = time.perf_counter()
                with ThreadPoolExecutor(args.write_concurrency) as pool:
                    results = list(pool.map(call, events))
                wall = time.perf_counter() - started
                expected = {"create": 201, "update": 200, "delete": 204}[op]
                errors = sum(status != expected for status, *_ in results)
                for (status, _, http_ms, _), event in zip(results, events):
                    rows.append({"run": r, "phase": phase, "source": source, "op": op, "status": status,
                                 "http_ms": round(http_ms, 3)})
                lat = [http_ms for _, _, http_ms, _ in results]
                phase_rows[op] = {"wall_s": round(wall, 3), "throughput_ops_s": round(len(events) / wall, 1),
                                  "median_ms": round(statistics.median(lat), 3), "errors": errors}
            per_run.append({"run": r, "phase": phase, "source": source, **phase_rows})
            print(f"  {phase} {r} {source}: " + ", ".join(f"{op} {v['throughput_ops_s']}/s med {v['median_ms']} ms"
                                                     + (f" ERR {v['errors']}" if v["errors"] else "")
                                                     for op, v in phase_rows.items()), flush=True)
    after = {source: window_total(client, source) for source in SOURCES}
    summary = {"window": WRITE_WINDOW, "runs": args.write_runs, "warmup_runs": args.write_warmup,
               "events_per_run": args.write_events, "concurrency": args.write_concurrency,
               "window_total_after_cleanup": after, "ops": {}}
    for op in ("create", "update", "delete"):
        summary["ops"][op] = {}
        for source in SOURCES:
            mine = [p[op] for p in per_run if p["source"] == source and p["phase"] == "measure"]
            summary["ops"][op][source] = {
                "latency": stats([row["http_ms"] for row in rows if row["source"] == source and row["op"] == op
                                  and row["phase"] == "measure"]),
                "throughput_ops_s": stats([m["throughput_ops_s"] for m in mine]),
                "errors": sum(m["errors"] for m in mine)}
    return rows, summary


# ------------------------------------------------------------------- summary
def rebuild_summary(results: Path) -> None:
    latest = {}
    for path in sorted(results.glob("*/run.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        if run.get("complete"):
            env_path = path.parent / "environment.json"
            if env_path.is_file():
                env = json.loads(env_path.read_text(encoding="utf-8"))
                pg, cs = env.get("postgresql") or {}, env.get("cassandra") or {}
                run["environment"] = {**run.get("environment", {}), "containers": env.get("containers"),
                                      "api": env.get("api"), "git": env.get("git"),
                                      "postgresql": {k: pg.get(k) for k in ("version", "settings", "indexes",
                                                                             "events_rows", "events_total_bytes",
                                                                             "database_bytes")},
                                      "cassandra": {k: cs.get(k) for k in ("version", "settings", "compaction", "tables")}}
            latest[run["suite"]] = run
    if "main" not in latest:
        return
    summary = {"generated_at": utc_now(), "main": latest["main"], "n1": latest.get("n1"),
               "writes": latest.get("writes"), "durability": latest.get("durability")}
    atomic_write_json(results / "summary.json", summary)
    print(f"summary: {results / 'summary.json'}")


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", choices=["main", "n1", "writes", "durability"], default="main")
    parser.add_argument("--runs", type=int, default=30, help="measured iterations per operation and source (>=10)")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--pause", type=float, default=0.0, help="seconds between iteration pairs")
    parser.add_argument("--refresh-runs", type=int, default=10)
    parser.add_argument("--write-runs", type=int, default=10)
    parser.add_argument("--write-warmup", type=int, default=2, help="discarded E6 rounds per database")
    parser.add_argument("--write-events", type=int, default=100)
    parser.add_argument("--write-concurrency", type=int, default=8)
    parser.add_argument("--skip-writes", action="store_true")
    parser.add_argument("--allow-debug", action="store_true", help="accept a debug API build (not comparable)")
    parser.add_argument("--results-dir", type=Path, default=RESULTS, help="output folder (default benchmarks/results)")
    parser.add_argument("--summarize-only", action="store_true", help="rebuild summary.json from existing runs")
    parser.add_argument("--docker-config")
    args = parser.parse_args()
    if args.summarize_only:
        rebuild_summary(args.results_dir)
        return
    if args.runs < 10:
        raise SystemExit("FAIL: the protocol requires at least 10 measured runs per operation")
    client = Client()
    try:
        status, health = client.json("/api/health")
        storage_status, storage = client.json("/api/health/storage")
        _, runtime = client.json("/api/runtime")
    except (OSError, http.client.HTTPException):
        raise SystemExit("BLOCKED: API not reachable on 127.0.0.1:3000 (python scripts/run_api.py start)")
    if status != 200 or storage_status != 200:
        raise SystemExit("BLOCKED: API or a database is unavailable; nothing was measured")
    if health.get("build") != "release" and not args.allow_debug:
        raise SystemExit("BLOCKED: API is a debug build; run 'python scripts/run_api.py build' and restart it")
    concurrency = runtime.get("cassandra_read_concurrency")
    sync = runtime.get("postgres_synchronous_commit")
    if (args.suite == "n1") != (concurrency == 1):
        raise SystemExit(f"BLOCKED: suite '{args.suite}' needs CASSANDRA_READ_CONCURRENCY "
                         f"{'=1' if args.suite == 'n1' else '>1'} (API reports {concurrency})")
    if (args.suite == "durability") != (sync == "off"):
        raise SystemExit(f"BLOCKED: suite '{args.suite}' needs POSTGRES_SYNCHRONOUS_COMMIT="
                         f"{'off' if args.suite == 'durability' else 'on'} (API reports {sync})")
    pool = runtime.get("postgres_pool_size")
    with_writes = args.suite in ("writes", "durability") or (args.suite == "main" and not args.skip_writes)
    if with_writes and (pool is None or pool < args.write_concurrency):
        raise SystemExit(f"BLOCKED: E6 uses {args.write_concurrency} concurrent clients but the PostgreSQL pool has "
                         f"{pool} connections; restart the API with --pg-pool-size >= {args.write_concurrency}")
    run_id = f"{stamp()}-{args.suite}"
    out = args.results_dir / run_id
    out.mkdir(parents=True, exist_ok=False)
    print(f"run {run_id}: capturing environment", flush=True)
    env = environment(args, client)
    atomic_write_json(out / "environment.json", env)
    run = {"run_id": run_id, "suite": args.suite, "started_at": utc_now(), "complete": False,
           "protocol": {"warmup": args.warmup, "runs": args.runs, "order": "pares intercalados, ordem alternada",
                        "cache": "quente (aquecimento descartado; 1ª observação registrada)",
                        "http_ms": "cliente Python, perf_counter, conexão keep-alive",
                        "db_ms": "Server-Timing da API: adaptador de armazenamento (driver + rede + banco + decodificação)",
                        "api_build": health.get("build"), "cassandra_read_concurrency": concurrency,
                        "postgres_synchronous_commit": sync, "postgres_pool_size": pool},
           "environment": {k: env.get(k) for k in ("host", "docker", "dataset")}}
    started = time.perf_counter()
    ops = [] if args.suite in ("writes", "durability") else operations(args.suite, args.warmup + args.runs)
    rows = run_reads(args, client, ops)
    write_csv(out / "raw.csv", rows)
    run["operations"] = [summarize_op(op, rows) for op in ops]
    if args.suite in ("writes", "durability"):
        write_rows, run["writes"] = run_writes(args, client, run_id)
        write_csv(out / "raw_writes.csv", write_rows)
    if args.suite == "main":
        print("[E5] controle PostgreSQL: view materializada (leitura e REFRESH)", flush=True)
        run["pg_control"] = run_pg_control(args)
        if not args.skip_writes:
            write_rows, run["writes"] = run_writes(args, client, run_id)
            write_csv(out / "raw_writes.csv", write_rows)
    run["seconds"] = round(time.perf_counter() - started, 1)
    run["finished_at"] = utc_now()
    write_errors = sum(v["errors"] for op in (run.get("writes") or {}).get("ops", {}).values() for v in op.values())
    run["complete"] = all(o["equivalent"] for o in run["operations"]) and not any(
        s["errors"] for o in run["operations"] for s in o["sources"].values()) and not write_errors \
        and "skipped" not in (run.get("writes") or {})
    atomic_write_json(out / "run.json", run)
    print(f"\n{'operation':28} {'PG med ms':>10} {'CS med ms':>10} {'faster':>11} {'ratio':>6} equiv")
    for o in run["operations"]:
        pg, cs = o["sources"]["postgresql"]["http"] or {}, o["sources"]["cassandra"]["http"] or {}
        print(f"{o['id']:28} {pg.get('median', '-'):>10} {cs.get('median', '-'):>10} {o.get('faster', '-'):>11} "
              f"{o.get('ratio', '-'):>6} {o['equivalent']}")
    print(f"\nresults: {out} ({'complete' if run['complete'] else 'INCOMPLETE: see run.json'})")
    rebuild_summary(args.results_dir)
    raise SystemExit(0 if run["complete"] else 1)


if __name__ == "__main__":
    main()
