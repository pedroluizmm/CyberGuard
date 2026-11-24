"""CyberGuard comparative benchmark: PostgreSQL vs Cassandra over the same logical dataset.

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
their own events afterwards through the API; the bulk dataset is never modified.
Outputs: benchmarks/results/<stamp>-<suite>/{raw.csv,raw_writes.csv,environment.json,run.json}
and benchmarks/results/summary.json (read by the dashboard).

Scale campaign (--campaign): the loaded dataset size is measured in both databases
(dashboard totals over the whole 28-day window must be equal) and recorded with
the run, together with workload controls (events covered by each query), cache
hit counters and pending compactions. summary.json keeps the historic 1M runs
(runs without a campaign) at the top level and adds one entry per measured size.
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
from bulk_runtime import atomic_write_json, cqlsh, docker, power_state, psql, run_text, stamp, utc_now  # noqa: E402

RESULTS = ROOT / "benchmarks/results"
SOURCES = ("postgresql", "cassandra")
WRITE_WINDOW = ("2002-01-07T00:00:00Z", "2002-01-14T00:00:00Z")
# How each operation's work relates to the dataset size (used by the scale comparison).
SCALE_CLASS = {
    "e1_read_by_id": "chave",              # one event by key: same work at any size
    "q1_device_hot_page": "pagina_fixa",   # first 100 of a growing key range
    "q1_device_hot_10pages": "pagina_fixa",
    "q2_ip_hot_page": "pagina_fixa",
    "q3_alerts_page": "pagina_fixa",
    "q1_device_cold_page": "resposta_crescente",  # every event of a sparse device (until the 100 cap)
    "overview_7d": "agregacao",            # PG aggregates every event; Cassandra reads fixed counter cells
    "overview_1d": "agregacao",
    "overview_7d_alerts": "agregacao",
}
WEEKS = [(f"{bulk.DATES[d]}T00:00:00Z",
          (datetime.fromisoformat(bulk.DATES[d]) + timedelta(days=7)).date().isoformat() + "T00:00:00Z")
         for d in range(0, bulk.WINDOW_DAYS, 7)]


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


# ------------------------------------------------------------------- dataset size
def measure_dataset(client: Client) -> dict:
    """Logical events loaded, measured in each database (sum of 4 weekly dashboards).

    The 28-day dataset window holds only bulk events (sample: November; tests: 2001/2002).
    PostgreSQL aggregates the rows; Cassandra reads its rollup. Both must agree.
    """
    totals = {}
    for source in SOURCES:
        total = 0
        for start, end in WEEKS:
            status, body = client.json(overview_path(source, **{"from": start, "to": end}))
            if status != 200:
                raise SystemExit(f"BLOCKED: dashboard total unavailable in {source} (HTTP {status})")
            total += body["total"]
        totals[source] = total
    n = totals["postgresql"]
    if totals["cassandra"] != n or n <= 0 or n % bulk.CHUNK_SIZE:
        raise SystemExit(f"BLOCKED: databases hold different dataset sizes {totals}; load/reconcile first")
    return {"logical_events": n, "by_source": totals,
            "method": "soma dos painéis semanais da janela 05/10–01/11 nos dois bancos (PG agrega, Cassandra lê o rollup)"}


# ------------------------------------------------------------------- operations
def sample_ids(count: int, n: int, salt: int = 0, exclude: frozenset = frozenset()) -> list[str]:
    """Deterministic distinct IDs over the loaded prefix [0, n); n=1M and salt=0 give the historic list.

    Pre-warm passes use another salt and never touch the IDs that are measured.
    """
    generator, out, k = bulk.BulkGenerator(bulk.DEFAULT_SEED), [], 0
    while len(out) < count:
        event_id = generator.event((k * 104_729 + 7_919 + salt) % n)["event_id"]
        k += 1
        if event_id not in exclude:
            out.append(event_id)
    return out


def query_path(source: str, kind: str, **params) -> str:
    return f"/api/{source}/queries/{kind}?" + urlencode(params)


def overview_path(source: str, **params) -> str:
    return f"/api/{source}/stats/overview?" + urlencode(params)


def operations(suite: str, total_iterations: int, n: int, prewarm: int = 0) -> list[dict]:
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
    ids = sample_ids(total_iterations, n)
    warm_ids = sample_ids(prewarm, n, salt=3_000_017, exclude=frozenset(ids)) if prewarm else []
    return [
        {"id": "e1_read_by_id", "experiment": "E1", "title": "READ por UUID (registro canônico / chave primária)",
         "params": {"ids": "amostra determinística distinta por iteração (mesma lista nos dois bancos)",
                    "sampled_from_events": n},
         "path": lambda s, i: f"/api/{s}/events/{ids[i]}",
         "prewarm_path": lambda s, i: f"/api/{s}/events/{warm_ids[i]}"},
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


def workload(args, ops: list[dict]) -> dict | None:
    """Control: events each read operation covers in PostgreSQL (does the extra data reach the query?)."""
    parts = []
    for op in ops:
        p = op["params"]
        if "from" not in p:
            continue
        cond = [f"occurred_at >= '{p['from']}'", f"occurred_at < '{p['to']}'"]
        if "device_id" in p:
            cond.append(f"device_id = '{p['device_id']}'")
        if "source_ip" in p:
            cond.append(f"source_ip = '{p['source_ip']}'::inet")
        if "severity" in p:
            cond.append(f"category = 'alert' AND severity = {int(p['severity'])}")
        if p.get("category"):
            cond.append(f"category = '{p['category']}'")
        parts.append(f"'{op['id']}', (SELECT count(*) FROM events WHERE {' AND '.join(cond)})")
    if not parts:
        return None
    raw = safe(psql(args.docker_config, "SELECT json_build_object(" + ", ".join(parts) + ")"), timeout=600)
    return json.loads(raw) if raw else None


def cache_snapshot(args) -> dict:
    """Counters read before/after the read phase: PG buffer hits, Cassandra caches, disk I/O, compactions."""
    snap = {"t": utc_now()}
    pg = safe(psql(args.docker_config, "SELECT json_build_object('blks_hit', blks_hit, 'blks_read', blks_read) "
                                       "FROM pg_stat_database WHERE datname = current_database()"))
    snap["postgresql"] = json.loads(pg) if pg else None
    cs = {}
    info = safe(docker(args.docker_config) + ["compose", "exec", "-T", "cassandra", "nodetool", "info"])
    for line in (info or "").splitlines():
        key, _, value = line.partition(":")
        key = key.strip()
        if key in ("Key Cache", "Chunk Cache", "Row Cache"):
            hits, requests = re.search(r"(\d+) hits", value), re.search(r"(\d+) requests", value)
            cs[key] = {"hits": int(hits.group(1)) if hits else None,
                       "requests": int(requests.group(1)) if requests else None}
        elif key.startswith("Heap Memory"):
            cs["heap_mb_used_total"] = value.strip()
    compaction = safe(docker(args.docker_config) + ["compose", "exec", "-T", "cassandra", "nodetool", "compactionstats"])
    match = re.search(r"pending tasks\s*:?\s*(\d+)", compaction or "", re.I)
    cs["pending_compactions"] = int(match.group(1)) if match else None
    snap["cassandra"] = cs
    io = safe(docker(args.docker_config) + ["stats", "--no-stream", "--format", "{{.Name}}|{{.BlockIO}}|{{.MemUsage}}"])
    snap["containers"] = {}
    for line in (io or "").splitlines():
        name, block, mem = (line.split("|") + ["", ""])[:3]
        if name.startswith("cyberguard"):
            read, _, written = block.partition("/")
            snap["containers"][name] = {"block_read_bytes": parse_size(read), "block_write_bytes": parse_size(written),
                                        "mem_usage": mem.strip()}
    return snap


def cache_delta(before: dict, after: dict) -> dict:
    out = {}
    try:
        hit = after["postgresql"]["blks_hit"] - before["postgresql"]["blks_hit"]
        read = after["postgresql"]["blks_read"] - before["postgresql"]["blks_read"]
        out["postgresql_shared_buffers"] = {"hits": hit, "reads": read,
                                            "hit_ratio": round(hit / (hit + read), 4) if hit + read else None}
    except (KeyError, TypeError):
        pass
    for cache in ("Key Cache", "Chunk Cache"):
        try:
            hits = after["cassandra"][cache]["hits"] - before["cassandra"][cache]["hits"]
            requests = after["cassandra"][cache]["requests"] - before["cassandra"][cache]["requests"]
            out["cassandra_" + cache.lower().replace(" ", "_")] = {
                "hits": hits, "requests": requests, "hit_ratio": round(hits / requests, 4) if requests else None}
        except (KeyError, TypeError):
            pass
    for name, b in before.get("containers", {}).items():
        a = after.get("containers", {}).get(name)
        if a:
            out.setdefault("disk_read_bytes", {})[name] = a["block_read_bytes"] - b["block_read_bytes"]
    return out


def parse_size(text: str) -> int:
    match = re.search(r"([\d.]+)\s*([kKMGT]?i?B)", text or "")
    units = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kib": 1024, "mib": 1024**2, "gib": 1024**3}
    return int(float(match.group(1)) * units.get(match.group(2).lower(), 1)) if match else 0


def environment(args, client: Client, dataset: dict, ops: list[dict]) -> dict:
    env = {"captured_at": utc_now(), "suite": args.suite, "campaign": args.campaign}
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
    env["host"]["power"] = power_state()
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
              "'events_index_bytes', pg_indexes_size('events'),"
              "'index_bytes', (SELECT json_object_agg(indexrelname, pg_relation_size(indexrelid)) "
              "FROM pg_stat_user_indexes WHERE relname = 'events'),"
              "'wal_bytes', (SELECT sum(size) FROM pg_ls_waldir()),"
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
    du = safe(docker(args.docker_config) + ["compose", "exec", "-T", "cassandra", "sh", "-c",
                                            "du -sb /var/lib/cassandra/data/cyberguard /var/lib/cassandra/data/system "
                                            "/var/lib/cassandra/commitlog 2>/dev/null"])
    if du:
        cs["du_bytes"] = {p: int(s) for s, p in (line.split("\t") for line in du.splitlines() if "\t" in line)}
    env["cassandra"] = cs
    n = dataset["logical_events"]
    try:
        profile = bulk.load_manifest(n)["profiles"].get(str(n))
    except SystemExit:
        profile = None
    env["dataset"] = {"name": bulk.DATASET, "logical_events": n, "measured": dataset,
                      "alerts": profile["alert_events"] if profile else None,
                      "manifest_profile": bool(profile), "window": [bulk.DATES[0], bulk.DATES[-1]]}
    env["workload"] = workload(args, ops)
    return env


# ------------------------------------------------------------------- read suite
def run_reads(args, client: Client, ops: list[dict]) -> list[dict]:
    rows = []
    total = args.warmup + args.runs
    if ops and args.prewarm:
        # JVM JIT and caches need far more than 5 requests after a restart; these passes are kept in
        # raw.csv as phase=prewarm and excluded from every statistic. E1 uses IDs that are never measured.
        print(f"prewarm: {args.prewarm} passes over {len(ops)} operations x 2 databases (phase=prewarm)", flush=True)
        for k in range(args.prewarm):
            for op in ops:
                warm_op = {**op, "path": op.get("prewarm_path", op["path"])}
                for position, source in enumerate(SOURCES if k % 2 == 0 else SOURCES[::-1]):
                    status, http_ms, db_ms, items, body = execute(client, warm_op, source, k)
                    rows.append({"operation": op["id"], "experiment": op["experiment"], "source": source,
                                 "phase": "prewarm", "iteration": k, "order": position, "status": status,
                                 "http_ms": round(http_ms, 3), "db_ms": round(db_ms, 3) if db_ms is not None else None,
                                 "items": items, "digest": body, "at": utc_now()})
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
def with_environment(path: Path, run: dict) -> dict:
    env_path = path.parent / "environment.json"
    if env_path.is_file():
        env = json.loads(env_path.read_text(encoding="utf-8"))
        pg, cs = env.get("postgresql") or {}, env.get("cassandra") or {}
        run["environment"] = {**run.get("environment", {}), "containers": env.get("containers"),
                              "api": env.get("api"), "git": env.get("git"),
                              "postgresql": {k: pg.get(k) for k in ("version", "settings", "indexes", "events_rows",
                                                                     "events_total_bytes", "events_heap_bytes",
                                                                     "events_index_bytes", "wal_bytes",
                                                                     "database_bytes") if k in pg},
                              "cassandra": {k: cs.get(k) for k in ("version", "settings", "compaction", "tables",
                                                                    "du_bytes") if k in cs}}
    return run


def median_of(stats_obj) -> float | None:
    return (stats_obj or {}).get("median")


def replicate_view(run: dict) -> dict:
    """Medians of another complete run at the same size: shows between-run variability."""
    return {"run_id": run["run_id"], "finished_at": run.get("finished_at"),
            "power": ((run.get("environment") or {}).get("host") or {}).get("power"),
            "operations": {o["id"]: {s: median_of(o["sources"][s]["http"]) for s in SOURCES}
                           | {"faster": o.get("faster"), "ratio": o.get("ratio")} for o in run["operations"]}}


def scale_view(sizes: list[dict]) -> dict:
    """Compact per-operation view across dataset sizes (medians, ratio, winner, covered events)."""
    operations_view, control, writes = {}, [], []
    for entry in sizes:
        n, main = entry["logical_events"], entry.get("main")
        if not main:
            continue
        covered = ((main.get("environment") or {}).get("workload") or {})
        for o in main["operations"]:
            row = operations_view.setdefault(o["id"], {"id": o["id"], "experiment": o["experiment"], "title": o["title"],
                                                       "class": SCALE_CLASS.get(o["id"]), "points": []})
            point = {"logical_events": n, "faster": o.get("faster"), "ratio": o.get("ratio"),
                     "equivalent": o["equivalent"], "iqr_separated": o.get("iqr_separated"),
                     "covered_events": covered.get(o["id"]),
                     "replicates": [{"run_id": r["run_id"], **r["operations"][o["id"]]}
                                    for r in entry.get("replicates", []) if o["id"] in r["operations"]]}
            for s in SOURCES:
                src = o["sources"][s]
                point[s] = {"http": {k: (src["http"] or {}).get(k) for k in ("median", "p25", "p75", "p95", "n")},
                            "db_median": median_of(src["db"]), "items": src["items"]}
            row["points"].append(point)
        pc = main.get("pg_control") or {}
        control.append({"logical_events": n, **{k: median_of((pc.get(k) or {}).get("stats"))
                                                 for k in ("pg_on_read_aggregate_7d", "pg_mv_read_7d",
                                                           "pg_mv_refresh_full")},
                        "cassandra_rollup_db_7d": next((median_of(o["sources"]["cassandra"]["db"])
                                                        for o in main["operations"] if o["id"] == "overview_7d"), None)})
        for label, run in (("padrao", entry.get("writes") or main), ("antes_do_fsync", entry.get("durability"))):
            w = (run or {}).get("writes")
            if not w or "ops" not in w:
                continue
            writes.append({"logical_events": n, "config": label, "run_id": run["run_id"],
                           **{op: {s: {"median_ms": median_of(w["ops"][op][s]["latency"]),
                                       "ops_s": median_of(w["ops"][op][s]["throughput_ops_s"])} for s in SOURCES}
                              for op in ("create", "update", "delete")}})
    return {"sizes": [e["logical_events"] for e in sizes], "operations": list(operations_view.values()),
            "control": control, "writes": writes}


def rebuild_summary(results: Path) -> None:
    """Historic runs (no campaign) stay at the top level; campaign runs are grouped by dataset size."""
    latest, campaigns = {}, {}
    # Runs measured under a documented invalid condition stay on disk but out of the summary.
    excluded_path = results / "excluded.json"
    excluded = json.loads(excluded_path.read_text(encoding="utf-8")) if excluded_path.is_file() else {}
    skipped = []
    for path in sorted(results.glob("*/run.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        if not run.get("complete"):
            continue
        if run["run_id"] in excluded:
            skipped.append({"run_id": run["run_id"], "reason": excluded[run["run_id"]]})
            continue
        run = with_environment(path, run)
        campaign = run.get("campaign")
        if not campaign:
            latest[run["suite"]] = run
            continue
        n = run.get("logical_events") or ((run.get("environment") or {}).get("dataset") or {}).get("logical_events")
        group = campaigns.setdefault(campaign, {}).setdefault(n, {"logical_events": n, "pilots": [], "replicates": []})
        if run["suite"] == "main" and not run["protocol"].get("prewarm_passes"):
            # Campaign protocol requires pre-warm passes; earlier runs stay on disk as documented pilots.
            group["pilots"].append(run["run_id"])
            continue
        if run["suite"] == "main":
            # The point of a size is its full E1-E6 run (the fixed sequence of run_scale_point.py);
            # every other complete main run at the same size is kept as a replicate (stability).
            current = group.get("main")
            if current is None or (bool(run.get("writes")) >= bool(current.get("writes"))):
                if current is not None:
                    group["replicates"].append(replicate_view(current))
                group["main"] = run
            else:
                group["replicates"].append(replicate_view(run))
            continue
        group[run["suite"]] = run
    if "main" not in latest:
        return
    summary = {"generated_at": utc_now(), "schema": 2,
               "main": latest["main"], "n1": latest.get("n1"),
               "writes": latest.get("writes"), "durability": latest.get("durability"), "campaigns": {}, "excluded_runs": skipped}
    for name, by_size in sorted(campaigns.items()):
        sizes = [by_size[n] for n in sorted(by_size) if "main" in by_size[n]]
        summary["campaigns"][name] = {"sizes": sizes, "scale": scale_view(sizes)}
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
    parser.add_argument("--prewarm", type=int, default=0,
                        help="untimed passes over all read operations before warm-up/measurement (phase=prewarm)")
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
    parser.add_argument("--campaign", help="tag of a measurement campaign (e.g. 'escala'); runs without a tag are "
                                           "the historic set shown at the top level of summary.json")
    parser.add_argument("--docker-config")
    args = parser.parse_args()
    if args.summarize_only:
        rebuild_summary(args.results_dir)
        return
    if args.runs < 10:
        raise SystemExit("FAIL: the protocol requires at least 10 measured runs per operation")
    if args.campaign is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", args.campaign):
        raise SystemExit("FAIL: --campaign must be 1-32 lowercase letters, digits or '-'")
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
    dataset = measure_dataset(client)
    n = dataset["logical_events"]
    run_id = f"{stamp()}-{args.suite}"
    out = args.results_dir / run_id
    out.mkdir(parents=True, exist_ok=False)
    print(f"run {run_id}: {n} logical events in both databases; capturing environment", flush=True)
    ops = [] if args.suite in ("writes", "durability") else operations(args.suite, args.warmup + args.runs, n,
                                                                        args.prewarm)
    env = environment(args, client, dataset, ops)
    atomic_write_json(out / "environment.json", env)
    run = {"run_id": run_id, "suite": args.suite, "started_at": utc_now(), "complete": False,
           "campaign": args.campaign, "logical_events": n,
           "protocol": {"warmup": args.warmup, "runs": args.runs, "prewarm_passes": args.prewarm,
                        "order": "pares intercalados, ordem alternada",
                        "cache": "quente (aquecimento descartado; 1ª observação registrada)",
                        "http_ms": "cliente Python, perf_counter, conexão keep-alive",
                        "db_ms": "Server-Timing da API: adaptador de armazenamento (driver + rede + banco + decodificação)",
                        "api_build": health.get("build"), "cassandra_read_concurrency": concurrency,
                        "postgres_synchronous_commit": sync, "postgres_pool_size": pool},
           "environment": {k: env.get(k) for k in ("host", "docker", "dataset", "workload")}}
    started = time.perf_counter()
    before = cache_snapshot(args) if ops else None
    rows = run_reads(args, client, ops)
    if ops:
        after = cache_snapshot(args)
        run["cache"] = {"before": before, "after": after, "read_phase": cache_delta(before, after)}
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
