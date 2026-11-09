"""Validate the loaded bulk dataset in PostgreSQL and Cassandra against the generator.

Run after loading exactly `--target` events into both databases. Checks:
 1. logical event counts; 2. identifier correspondence; 3. full content equality
 (streamed COPY exports) plus a deterministic API READ sample; 4. Cassandra
 projection integrity (exact key multisets); 5. physical rows per table;
 6. partition distribution and on-disk sizes; 7. no duplicated logical events;
 8. no pending/deleting Cassandra records; 9. Q1-Q3 paginated through the API,
 equal between databases and equal to the generator's expectation.

Exports are streamed through `docker compose exec` (COPY ... TO STDOUT), never
stored. Comparisons use order-independent multiset hashes (sum of SHA-256
prefixes mod 2^128) plus counts, so memory stays bounded. Only reads and a
non-destructive `nodetool flush` are executed. Durations recorded here are
functional observations, not benchmarks.
"""
import argparse
import csv
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "loading"))
sys.path.insert(0, str(HERE.parent / "generation"))
csv.field_size_limit(1 << 24)
import bulk_events as bulk  # noqa: E402
from bulk_runtime import REPORT_DIR, ROOT, Api, atomic_write_json, compose_exec, psql, run_text, stamp, utc_now  # noqa: E402

MANIFEST = ROOT / "data/bulk" / f"{bulk.DATASET}.manifest.json"
DATES = set(bulk.DATES)
MOD = 1 << 128


def h(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:16], "big")


class Multiset:
    __slots__ = ("count", "acc")

    def __init__(self):
        self.count, self.acc = 0, 0

    def add(self, text: str) -> None:
        self.count += 1
        self.acc = (self.acc + h(text)) % MOD

    def __eq__(self, other):
        return (self.count, self.acc) == (other.count, other.acc)

    def view(self):
        return {"rows": self.count, "digest": f"{self.acc:032x}"}


def ts_key(occurred_at: str) -> str:
    """RFC3339 '...T12:00:00.000Z' -> '2026-10-05 12:00:00.000' (cqlsh layout)."""
    return occurred_at[:10] + " " + occurred_at[11:23]


def content_key(data: dict) -> str:
    return bulk.canonical_line(data).decode()


def stream_csv(command, **fmt):
    proc = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    reader = csv.reader(io.TextIOWrapper(proc.stdout, encoding="utf-8", newline=""), **fmt)
    yield from reader
    stderr = proc.stderr.read()
    if proc.wait() != 0 or any(t in stderr for t in (b"Exception", b"Error", b"Failed")):
        raise RuntimeError(f"export failed ({command[-1][:60]}...)")


def distribution(counts: dict) -> dict:
    values = sorted(counts.values())
    if not values:
        return {"partitions": 0, "rows": 0}
    pick = lambda p: values[min(len(values) - 1, (len(values) * p) // 100)]  # noqa: E731
    top = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    return {"partitions": len(values), "rows": sum(values), "p50_rows": pick(50), "p99_rows": pick(99),
            "max_rows": values[-1], "max_key": list(top[0])}


class Validation:
    def __init__(self, args):
        self.args = args
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.n = args.target
        self.gen = bulk.BulkGenerator(self.manifest["seed"])
        self.api = Api(args.base_url)
        self.checks, self.report = [], {}

    def check(self, name: str, ok: bool, detail=None) -> None:
        self.checks.append({"check": name, "pass": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" -> {detail}" if detail is not None and not ok else ""),
              flush=True)

    # ---------- expected state from the deterministic generator ----------
    def expected(self):
        t = time.perf_counter()
        exp = {k: Multiset() for k in ("content", "device", "ip", "alert")}
        self.queries = self.plan_queries()
        expected_items = {q["name"]: [] for q in self.queries}
        for chunk in range(self.n // bulk.CHUNK_SIZE):
            digest, events = self.gen.chunk_digest(chunk)
            if digest != self.manifest["chunk_sha256"][chunk]:
                raise SystemExit(f"FAIL: generator differs from manifest at chunk {chunk}")
            for e in events:
                exp["content"].add(content_key(e))
                tk, i = ts_key(e["occurred_at"]), e["event_id"]
                exp["device"].add(f"{e['device_id']}|{e['event_date']}|{tk}|{i}")
                exp["ip"].add(f"{e['source_ip']}|{e['event_date']}|{tk}|{i}")
                if e["category"] == "alert":
                    exp["alert"].add(f"{e['severity']}|{e['event_date']}|{tk}|{i}")
                for q in self.queries:
                    if q["match"](e):
                        expected_items[q["name"]].append(e)
        for q in self.queries:
            items = expected_items[q["name"]]
            items.sort(key=lambda e: (e["occurred_at"], e["event_id"]), reverse=True)
            q["expected"] = [{"data": e, "revision": 1} for e in items]
        self.exp = exp
        self.report["expected_seconds"] = round(time.perf_counter() - t, 2)

    def plan_queries(self):
        profile = self.manifest["profiles"].get(str(self.n))
        parts = profile["partitions"] if profile else None
        first, last = date.fromisoformat(bulk.DATES[0]), date.fromisoformat(bulk.DATES[-1])

        def window(center: str, days: int):
            start = max(first, date.fromisoformat(center) - timedelta(days=days // 2))
            start = min(start, last - timedelta(days=days - 1))
            return start.isoformat() + "T00:00:00Z", (start + timedelta(days=days)).isoformat() + "T00:00:00Z"

        hot_device = parts["events_by_device_day"]["top"][0]["key"] if parts else ["ids-sensor-06", "2026-10-27"]
        hot_ip = parts["events_by_ip_day"]["top"][0]["key"] if parts else ["2001:db8:bad:4::6", "2026-10-27"]
        ipv4 = parts["events_by_ip_day"]["top"][1]["key"] if parts else ["203.0.113.173", "2026-10-08"]
        hot_sev = parts["alerts_by_severity_day"]["top"][0]["key"] if parts else [3, "2026-10-14"]
        specs = [("q1_hot_device_7d", "device", "device_id", hot_device[0], window(hot_device[1], 7)),
                 ("q1_cold_device_7d", "device", "device_id", "ws-hr-0050", window("2026-10-15", 7)),
                 ("q2_hot_ipv6_7d", "ip", "source_ip", hot_ip[0], window(hot_ip[1], 7)),
                 ("q2_ipv4_1d", "ip", "source_ip", ipv4[0], window(ipv4[1], 1)),
                 ("q3_hot_severity_2d", "alerts", "severity", hot_sev[0], window(hot_sev[1], 2)),
                 ("q3_severity5_7d", "alerts", "severity", 5, window("2026-10-20", 7))]
        queries = []
        for name, kind, field, value, (lo, hi) in specs:
            def match(e, field=field, value=value, lo=lo, hi=hi, kind=kind):
                return (e[field] == value and lo <= e["occurred_at"] < hi
                        and (kind != "alerts" or e["category"] == "alert"))
            queries.append({"name": name, "kind": kind, "field": field, "value": value, "from": lo, "to": hi,
                            "match": match})
        return queries

    # ---------- PostgreSQL ----------
    def postgresql(self):
        t = time.perf_counter()
        sql = ("COPY (SELECT event_id, to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"'), "
               "event_date, device_id, host(source_ip), category, event_type, severity, outcome, message, "
               "metadata::text, revision FROM events) TO STDOUT WITH (FORMAT csv)")
        content, seen, other, beyond, dup, bad_rev = Multiset(), bytearray(self.n), 0, 0, 0, 0
        for r in stream_csv(psql(self.args.docker_config, sql)):
            meta = json.loads(r[10])
            if meta.get("dataset") != bulk.DATASET:
                other += 1
                continue
            seq = meta["seq"]
            if seq >= self.n:
                beyond += 1
                continue
            dup += seen[seq]
            seen[seq] = 1
            bad_rev += r[11] != "1"
            content.add(content_key({"event_id": r[0], "occurred_at": r[1], "event_date": r[2], "device_id": r[3],
                                     "source_ip": r[4], "category": r[5], "event_type": r[6], "severity": int(r[7]),
                                     "outcome": r[8], "message": r[9], "metadata": meta}))
        counts = run_text(psql(self.args.docker_config,
                               "SELECT (SELECT count(*) FROM events), (SELECT count(*) FROM event_registry), "
                               "(SELECT count(*) FROM event_registry WHERE deleted), (SELECT count(*) FROM devices), "
                               "(SELECT count(*) FROM event_registry r LEFT JOIN events e USING (event_id) "
                               "WHERE e.event_id IS NULL AND NOT r.deleted)")).strip().split("|")
        events, registry, deleted, devices, orphans = map(int, counts)
        self.check("postgresql: logical events == target", content.count == self.n, content.count)
        self.check("postgresql: IDs and full content equal generator", content == self.exp["content"])
        self.check("postgresql: no duplicated logical event (seq)", dup == 0 and beyond == 0, {"dup": dup, "beyond": beyond})
        self.check("postgresql: all revisions == 1", bad_rev == 0, bad_rev)
        self.check("postgresql: no active reservation without event", orphans == 0, orphans)
        self.report["postgresql"] = {"export_seconds": round(time.perf_counter() - t, 1), "events_table_rows": events,
                                     "dataset_events": content.count, "other_events": other,
                                     "event_registry_rows": registry, "event_registry_deleted": deleted,
                                     "devices_rows": devices, "content": content.view()}

    # ---------- Cassandra ----------
    def cql_copy(self, table: str, columns: str):
        command = compose_exec(self.args.docker_config, "cassandra", "cqlsh", "127.0.0.1", "9042",
                               "--request-timeout=120", "-e",
                               f"COPY cyberguard.{table} ({columns}) TO STDOUT WITH HEADER=false AND PAGETIMEOUT=60")
        return stream_csv(command, escapechar="\\", doublequote=False)

    def cassandra(self):
        t = time.perf_counter()
        content, seen, dup, beyond, bad_rev = Multiset(), bytearray(self.n), 0, 0, 0
        lifecycle = {"dataset": {}, "other": {}}
        for event_id, state, revision, payload in self.cql_copy("events_by_id", "event_id,lifecycle,revision,payload"):
            group = "other"
            if payload:
                envelope = json.loads(payload)
                data = envelope["data"]
                if data["metadata"].get("dataset") == bulk.DATASET:
                    group = "dataset"
                    seq = data["metadata"]["seq"]
                    if seq >= self.n:
                        beyond += 1
                    else:
                        dup += seen[seq]
                        seen[seq] = 1
                        bad_rev += revision != "1" or envelope["revision"] != 1 or data["event_id"] != event_id
                        if state == "active":
                            content.add(content_key(data))
            lifecycle[group][state] = lifecycle[group].get(state, 0) + 1
        canonical_seconds = time.perf_counter() - t
        projections, partitions = {}, {}
        for table, key, name in (("events_by_device_day", "device_id", "device"),
                                 ("events_by_ip_day", "source_ip", "ip"),
                                 ("alerts_by_severity_day", "severity", "alert")):
            ms, outside, per_partition, bad_tz = Multiset(), 0, {}, 0
            for k, day, occurred, event_id in self.cql_copy(table, f"{key},event_date,occurred_at,event_id"):
                if day not in DATES:
                    outside += 1
                    continue
                bad_tz += not occurred.endswith("+0000")
                ms.add(f"{k}|{day}|{occurred[:23]}|{event_id}")
                per_partition[(k, day)] = per_partition.get((k, day), 0) + 1
            projections[table] = {"rows_in_dataset_window": ms.count, "rows_outside_window": outside, **ms.view()}
            partitions[table] = distribution(per_partition)
            self.check(f"cassandra: {table} keys equal generator", ms == self.exp[name] and bad_tz == 0,
                       {"rows": ms.count, "expected": self.exp[name].count})
        active = lifecycle["dataset"].get("active", 0)
        unfinished = {s: c for g in lifecycle.values() for s, c in g.items() if s in ("pending", "deleting")}
        self.check("cassandra: logical (active) events == target", active == self.n, active)
        self.check("cassandra: IDs and full canonical content equal generator", content == self.exp["content"])
        self.check("cassandra: no duplicated logical event (seq)", dup == 0 and beyond == 0, {"dup": dup, "beyond": beyond})
        self.check("cassandra: revisions == 1 and payload ID == key", bad_rev == 0, bad_rev)
        self.check("cassandra: no pending/deleting records", not unfinished, unfinished)
        live = active + sum(p["rows_in_dataset_window"] for p in projections.values())
        expected_live = 3 * self.n + self.exp["alert"].count
        self.check("cassandra: live physical rows == 3N + A", live == expected_live, {"live": live, "expected": expected_live})
        self.report["cassandra"] = {"export_seconds": round(time.perf_counter() - t, 1),
                                    "canonical_export_seconds": round(canonical_seconds, 1),
                                    "events_by_id_lifecycle": lifecycle, "projections": projections,
                                    "dataset_live_rows": live, "expected_live_rows": expected_live,
                                    "partitions_measured": partitions, "content": content.view()}
        profile = self.manifest["profiles"].get(str(self.n))
        if profile:
            same = all(partitions[t]["max_rows"] == profile["partitions"][t]["max_rows"]
                       and partitions[t]["partitions"] == profile["partitions"][t]["partitions"] for t in partitions)
            self.check("cassandra: measured partition distribution == manifest", same)

    # ---------- API: sampled READ and Q1-Q3 ----------
    def api_checks(self):
        indices = sorted({int.from_bytes(hashlib.sha256(f"sample|{k}".encode()).digest()[:8], "big") % self.n
                          for k in range(self.args.sample)})
        bad = {"postgresql": 0, "cassandra": 0}
        for index in indices:
            event = self.gen.event(index)
            for source in bad:
                status, body = self.api.request("GET", f"/api/{source}/events/{event['event_id']}")
                bad[source] += (status, body) != (200, {"data": event, "revision": 1})
        self.check(f"api: deterministic sample of {len(indices)} READs equal in both databases",
                   not any(bad.values()), bad)
        results = []
        for q in self.queries:
            row = {k: q[k] for k in ("name", "kind", "value", "from", "to")}
            row["expected_items"] = len(q["expected"])
            pages_cap = self.args.max_pages
            outputs = {}
            for source in ("postgresql", "cassandra"):
                params = {q["field"]: q["value"], "from": q["from"], "to": q["to"], "page_size": 100}
                items, pages, cursor, started, statuses = [], 0, None, time.perf_counter(), set()
                while pages < pages_cap:
                    query = dict(params, **({"cursor": cursor} if cursor else {}))
                    status, body = self.api.request("GET", f"/api/{source}/queries/{q['kind']}?{urlencode(query)}")
                    statuses.add(status)
                    if status != 200:
                        break
                    pages += 1
                    items.extend(body["items"])
                    cursor = body["next_cursor"]
                    if not cursor:
                        break
                outputs[source] = items
                row[source] = {"pages": pages, "items": len(items), "statuses": sorted(statuses),
                               "complete": cursor is None and statuses == {200},
                               "seconds": round(time.perf_counter() - started, 3)}
            compared = len(outputs["postgresql"])
            complete = row["postgresql"]["complete"] and row["cassandra"]["complete"]
            capped = not complete and compared == pages_cap * 100  # page cap reached: compare the prefix
            ok = (row["postgresql"]["statuses"] == [200] and row["cassandra"]["statuses"] == [200]
                  and outputs["postgresql"] == outputs["cassandra"]
                  and ((complete and outputs["postgresql"] == q["expected"])
                       or (capped and outputs["postgresql"] == q["expected"][:compared])))
            row["compared_prefix_only"] = capped
            row["equal"] = ok
            self.check(f"api: {q['name']} ({compared}/{len(q['expected'])} items) equal and expected", ok)
            results.append(row)
        self.report["queries"] = results
        self.report["api_sample_size"] = len(indices)

    # ---------- storage metrics ----------
    def storage(self):
        c = self.args.docker_config
        if not self.args.no_flush:
            run_text(compose_exec(c, "cassandra", "nodetool", "flush", "cyberguard"), timeout=300)
        stats = {}
        for keyspace_table in ("cyberguard.events_by_id", "cyberguard.events_by_device_day",
                               "cyberguard.events_by_ip_day", "cyberguard.alerts_by_severity_day",
                               "system.paxos", "system.batches"):
            text = run_text(compose_exec(c, "cassandra", "nodetool", "tablestats", keyspace_table))
            wanted = ("SSTable count", "Space used (live)", "Space used (total)", "SSTable Compression Ratio",
                      "Number of partitions (estimate)", "Memtable data size", "Compacted partition minimum bytes",
                      "Compacted partition maximum bytes", "Compacted partition mean bytes", "Local read count",
                      "Local write count", "Bloom filter space used", "Index summary off heap memory used")
            stats[keyspace_table] = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip()
                                     for line in text.splitlines()
                                     if ":" in line and line.split(":", 1)[0].strip() in wanted}
        hist = {}
        for table in ("events_by_device_day", "events_by_ip_day", "alerts_by_severity_day"):
            text = run_text(compose_exec(c, "cassandra", "nodetool", "tablehistograms", "cyberguard", table))
            hist[table] = [" ".join(line.split()) for line in text.splitlines()
                           if line.strip().startswith(("Percentile", "50%", "95%", "99%", "Max"))]
        du = run_text(compose_exec(c, "cassandra", "sh", "-c",
                                   "du -sb /var/lib/cassandra/data/cyberguard /var/lib/cassandra/data/system "
                                   "/var/lib/cassandra/commitlog 2>/dev/null"))
        self.report["cassandra_storage"] = {"tablestats": stats, "tablehistograms": hist,
                                            "du_bytes": {p: int(s) for s, p in (l.split("\t") for l in du.splitlines())},
                                            "flushed_before_measure": not self.args.no_flush}
        sizes = run_text(psql(c, "SELECT json_agg(t) FROM (SELECT c.relname, pg_relation_size(c.oid) AS heap_bytes, "
                                 "pg_indexes_size(c.oid) AS index_bytes, pg_total_relation_size(c.oid) AS total_bytes, "
                                 "s.n_live_tup, s.n_dead_tup, s.last_autovacuum, s.last_autoanalyze "
                                 "FROM pg_class c JOIN pg_stat_user_tables s ON s.relid = c.oid "
                                 "WHERE c.relname IN ('events','event_registry','devices') ORDER BY 1) t"))
        indexes = run_text(psql(c, "SELECT json_object_agg(indexrelname, pg_relation_size(indexrelid)) "
                                   "FROM pg_stat_user_indexes WHERE relname IN ('events','event_registry','devices')"))
        db = run_text(psql(c, "SELECT pg_database_size(current_database())"))
        self.report["postgresql_storage"] = {"tables": json.loads(sizes), "index_bytes": json.loads(indexes),
                                             "database_bytes": int(db.strip()), "first_page_plans": self.plans()}

    def plans(self):
        """Read-only EXPLAIN ANALYZE of the API's first-page SQL; evidence of index use, not a benchmark."""
        filters = {"device": "device_id = '{v}'", "ip": "source_ip = '{v}'::inet",
                   "alerts": "category = 'alert' AND severity = {v}"}
        plans = {}
        for q in self.queries:
            value = str(q["value"]).replace("'", "''")
            sql = (f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT event_id FROM events WHERE "
                   f"{filters[q['kind']].format(v=value)} AND occurred_at >= '{q['from']}' AND occurred_at < '{q['to']}' "
                   f"ORDER BY occurred_at DESC, event_id DESC LIMIT 101")
            plan = json.loads(run_text(psql(self.args.docker_config, sql)))[0]
            nodes, stack = [], [plan["Plan"]]
            while stack:
                node = stack.pop()
                nodes.append({k: node.get(k) for k in ("Node Type", "Index Name", "Actual Rows",
                                                       "Shared Hit Blocks", "Shared Read Blocks") if k in node})
                stack.extend(node.get("Plans", []))
            plans[q["name"]] = {"nodes": nodes, "execution_ms": plan.get("Execution Time")}
        return plans

    def run(self):
        started = time.perf_counter()
        self.expected()
        print(f"expected state regenerated for {self.n} events in {self.report['expected_seconds']}s", flush=True)
        self.postgresql()
        self.cassandra()
        self.api_checks()
        self.storage()
        self.report.update({"kind": "bulk_validation", "dataset": bulk.DATASET, "seed": self.manifest["seed"],
                            "target_events": self.n, "finished_at_utc": utc_now(),
                            "wall_seconds": round(time.perf_counter() - started, 1),
                            "expected": {k: v.view() for k, v in self.exp.items()}, "checks": self.checks,
                            "passed": all(c["pass"] for c in self.checks),
                            "note": "Functional validation; durations are observations, not benchmarks."})
        for q in self.queries:
            q.pop("match", None)
            q.pop("expected", None)
        path = REPORT_DIR / f"validate-{self.n}-{stamp()}.json"
        atomic_write_json(path, self.report)
        failed = [c["check"] for c in self.checks if not c["pass"]]
        print(f"{'PASS' if not failed else 'FAIL'}: {len(self.checks) - len(failed)}/{len(self.checks)} checks; "
              f"report {path.relative_to(ROOT)}")
        if failed:
            raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--docker-config")
    parser.add_argument("--sample", type=int, default=500, help="deterministic API READ sample size")
    parser.add_argument("--max-pages", type=int, default=100, help="page cap per Q1-Q3 check and source")
    parser.add_argument("--no-flush", action="store_true", help="skip the non-destructive nodetool flush")
    args = parser.parse_args()
    if args.target % bulk.CHUNK_SIZE or args.target <= 0:
        raise SystemExit("--target must be a positive multiple of 1000")
    Validation(args).run()


if __name__ == "__main__":
    main()
