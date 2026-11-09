"""Load the deterministic bulk dataset through the real CRUD API, resumably.

Each event is POSTed to /api/{source}/events, so PostgreSQL transactions and the
Cassandra pending -> projections -> active workflow (LWT + logged batch) are the
same code paths validated in Task 02. Nothing is written directly to tables.

* Chunks of 1000 events are regenerated on the fly and checked against the
  manifest SHA-256 before sending; no large event files are written.
* A chunk is checkpointed only after every event returned 201/200 with exactly
  the expected envelope. Retries reuse the same UUID (idempotent CREATE).
* 409 / unexpected 4xx / content mismatch abort the run without overwriting.
  Persistent 503 or connection errors abort after bounded retries; uncertain IDs
  are recorded and the chunk is resent on the next run (reconciliation by ID).

This measures an initial load via API. It is not a benchmark and must not be
read as proof that one database is superior.
"""
import argparse
from collections import deque
import concurrent.futures as cf
import json
from pathlib import Path
import random
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "generation"))
import bulk_events as bulk  # noqa: E402
from bulk_runtime import (REPORT_DIR, STATE_DIR, Api, ResourceSampler, Timer, append_line,  # noqa: E402
                          atomic_write_json, stamp, utc_now)

MANIFEST = HERE.parents[1] / "data/bulk" / f"{bulk.DATASET}.manifest.json"
RETRYABLE = {502, 503, 504}


class Fatal(Exception):
    pass


class Uncertain(Exception):
    pass


def ranges(chunks):
    out = []
    for c in sorted(chunks):
        if out and c == out[-1][1] + 1:
            out[-1][1] = c
        else:
            out.append([c, c])
    return out


def expand(pairs):
    return {c for a, b in pairs for c in range(a, b + 1)}


class Checkpoint:
    def __init__(self, source: str, seed: int):
        self.path = STATE_DIR / bulk.DATASET / f"checkpoint-{source}.json"
        self.meta = {"dataset": bulk.DATASET, "seed": seed, "chunk_size": bulk.CHUNK_SIZE, "source": source}
        self.done = set()
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if {k: data.get(k) for k in self.meta} != self.meta:
                raise SystemExit(f"FAIL: checkpoint {self.path.name} belongs to different parameters")
            self.done = expand(data["completed_chunks"])
        self.lock = threading.Lock()

    def mark(self, chunk: int) -> None:
        with self.lock:
            self.done.add(chunk)
            atomic_write_json(self.path, {**self.meta, "completed_chunks": ranges(self.done),
                                          "completed_events": len(self.done) * bulk.CHUNK_SIZE,
                                          "updated_at_utc": utc_now()})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["postgresql", "cassandra"], required=True)
    parser.add_argument("--target", type=int, required=True, help="load event indices [0, target)")
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--depth", type=int, default=2, help="chunks in flight")
    parser.add_argument("--max-attempts", type=int, default=6)
    parser.add_argument("--max-seconds", type=float, help="stop cleanly at a chunk boundary after this budget")
    parser.add_argument("--ignore-checkpoint", action="store_true",
                        help="resend completed chunks too (idempotency check); checkpoint is not reduced")
    parser.add_argument("--api-build", default="unspecified", help="label recorded in the report (debug/release)")
    parser.add_argument("--docker-config")
    parser.add_argument("--sample-interval", type=float, default=10.0)
    args = parser.parse_args()
    if not 1 <= args.workers <= 64 or not 1 <= args.depth <= 4:
        raise SystemExit("--workers must be 1..64 and --depth 1..4")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if args.target % bulk.CHUNK_SIZE or not 0 < args.target <= manifest["logical_events"]:
        raise SystemExit(f"--target must be a multiple of {bulk.CHUNK_SIZE} within the manifest count")
    seed = manifest["seed"]
    gen = bulk.BulkGenerator(seed)
    checkpoint = Checkpoint(args.source, seed)
    total_chunks = args.target // bulk.CHUNK_SIZE
    todo = [c for c in range(total_chunks) if args.ignore_checkpoint or c not in checkpoint.done]
    skipped = total_chunks - len(todo)
    run_id = stamp()
    state = STATE_DIR / bulk.DATASET
    log_path = state / f"load-{args.source}.ndjson"
    uncertain_path = state / f"uncertain-{args.source}.ndjson"
    api = Api(args.base_url)
    stop = threading.Event()
    stats_lock = threading.Lock()
    totals = {"created": 0, "reused": 0, "retried_events": 0, "extra_attempts": 0, "uncertain": 0}
    reasons = []

    def send(event: dict) -> str:
        if stop.is_set():
            return "skipped"
        body = json.dumps(event, separators=(",", ":")).encode()
        expected = {"data": event, "revision": 1}
        for attempt in range(1, args.max_attempts + 1):
            status = payload = None
            try:
                status, payload = api.request("POST", f"/api/{args.source}/events", body)
            except (OSError, ValueError):
                status = None  # connection reset / timeout: outcome uncertain, retry same UUID
            if status in (200, 201):
                if payload != expected:
                    raise Fatal(f"content mismatch for {event['event_id']}")
                with stats_lock:
                    totals["created" if status == 201 else "reused"] += 1
                    if attempt > 1:
                        totals["retried_events"] += 1
                        totals["extra_attempts"] += attempt - 1
                return "ok"
            if status == 409:
                raise Fatal(f"409 conflict for {event['event_id']}; existing data was not overwritten")
            if status is not None and status not in RETRYABLE:
                code = (payload or {}).get("error", {}).get("code") if isinstance(payload, dict) else None
                raise Fatal(f"HTTP {status} {code} for {event['event_id']}")
            if stop.is_set():
                break
            time.sleep(min(8.0, 0.25 * 2 ** (attempt - 1)) * (0.5 + random.random()))
        with stats_lock:
            totals["uncertain"] += 1
        append_line(uncertain_path, {"run": run_id, "event_id": event["event_id"], "seq": event["metadata"]["seq"],
                                     "last_status": status, "t": utc_now()})
        raise Uncertain(event["event_id"])

    sampler = ResourceSampler(args.docker_config, state / f"resources-{args.source}-{run_id}.ndjson",
                              args.sample_interval)
    sampler.start()
    timer = Timer()
    completed_now = 0
    interrupted = False
    pending = deque()

    def finish(chunk, futures, started):
        nonlocal completed_now
        outcomes = []
        for future in futures:
            while True:
                try:
                    outcomes.append(future.result(timeout=0.5))
                    break
                except cf.TimeoutError:
                    continue
                except (Fatal, Uncertain) as error:
                    outcomes.append("failed")
                    if not stop.is_set():
                        reasons.append(f"{type(error).__name__}: {error}")
                    stop.set()
                    break
        if all(o == "ok" for o in outcomes):
            if not args.ignore_checkpoint or chunk not in checkpoint.done:
                checkpoint.mark(chunk)
            completed_now += 1
            append_line(log_path, {"run": run_id, "chunk": chunk, "events": len(futures),
                                   "seconds": round(time.perf_counter() - started, 3), "t": utc_now()})
            done_events = completed_now * bulk.CHUNK_SIZE
            if completed_now % max(1, len(todo) // 10) == 0:
                print(f"  {args.source}: {done_events}/{len(todo) * bulk.CHUNK_SIZE} events this run, "
                      f"{done_events / timer.seconds():.0f} ev/s", flush=True)

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        try:
            for chunk in todo:
                if stop.is_set():
                    break
                if args.max_seconds and timer.seconds() >= args.max_seconds:
                    reasons.append("time budget reached; stopped cleanly at a chunk boundary")
                    interrupted = True
                    break
                digest, events = gen.chunk_digest(chunk)
                if digest != manifest["chunk_sha256"][chunk]:
                    reasons.append(f"generator output differs from manifest at chunk {chunk}")
                    stop.set()
                    break
                pending.append((chunk, [pool.submit(send, e) for e in events], time.perf_counter()))
                while len(pending) >= args.depth:
                    finish(*pending.popleft())
            while pending:
                finish(*pending.popleft())
        except KeyboardInterrupt:
            interrupted = True
            reasons.append("interrupted by user; completed chunks were checkpointed")
            stop.set()
            while pending:
                finish(*pending.popleft())
    seconds = timer.seconds()
    resources = sampler.stop()
    sent = totals["created"] + totals["reused"]
    report = {
        "kind": "initial_load_via_api", "dataset": bulk.DATASET, "seed": seed, "source": args.source,
        "target_events": args.target, "run_id": run_id, "finished_at_utc": utc_now(),
        "chunks_in_target": total_chunks, "chunks_skipped_from_checkpoint": skipped,
        "chunks_completed_this_run": completed_now, "checkpoint_completed_events": len(checkpoint.done) * bulk.CHUNK_SIZE,
        "events_acknowledged_this_run": sent, **totals,
        "wall_seconds": round(seconds, 2), "events_per_second": round(sent / seconds, 1) if seconds else None,
        "workers": args.workers, "chunks_in_flight": args.depth, "max_attempts": args.max_attempts,
        "ignore_checkpoint": args.ignore_checkpoint, "api_build": args.api_build, "resources": resources,
        "stopped": bool(reasons), "interrupted": interrupted, "reasons": reasons,
        "notes": ["Includes HTTP, validation, PostgreSQL transaction or Cassandra LWT+batch+reads per event.",
                  "Durability differs: PostgreSQL synchronous_commit=on; Cassandra commitlog_sync=periodic (10s).",
                  "Initial load via API, not a comparative benchmark."],
    }
    atomic_write_json(REPORT_DIR / f"load-{args.source}-{args.target}-{run_id}.json", report)
    verdict = "PASS" if not reasons else ("STOPPED" if interrupted else "FAIL")
    print(f"{verdict}: {args.source} target={args.target} created={totals['created']} reused={totals['reused']} "
          f"retried={totals['retried_events']} uncertain={totals['uncertain']} in {seconds:.1f}s "
          f"({report['events_per_second']} ev/s); checkpoint={report['checkpoint_completed_events']}")
    for reason in reasons[:3]:
        print("  reason:", reason)
    if reasons and not interrupted:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
