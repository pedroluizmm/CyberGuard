"""Compute the deterministic manifest of the bulk dataset without writing the events.

Events are streamed from `bulk_events.BulkGenerator`; only counters, partition
statistics and SHA-256 digests are kept. Rerunning with the same parameters must
reproduce the manifest byte for byte; a different existing manifest is never
overwritten. Timing and interpreter details go to a separate run report.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bulk_events as bulk  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BULK_DIR = bulk.BULK_DIR


def distribution(counter: Counter, top: int = 3) -> dict:
    values = sorted(counter.values())
    if not values:
        return {"partitions": 0, "rows": 0}

    def pct(p):
        return values[min(len(values) - 1, (len(values) * p) // 100)]

    return {"partitions": len(values), "rows": sum(values), "min_rows": values[0], "p50_rows": pct(50),
            "p95_rows": pct(95), "p99_rows": pct(99), "max_rows": values[-1],
            "top": [{"key": list(k), "rows": v} for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]}


def snapshot(n, digest, counters) -> dict:
    alerts = counters["category"]["alert"]
    return {
        "logical_events": n, "sha256_canonical_ndjson": digest.copy().hexdigest(),
        "alert_events": alerts, "expected_cassandra_live_rows": 3 * n + alerts,
        "expected_postgresql_event_rows": n,
        "by_category": dict(sorted(counters["category"].items())),
        "by_event_type": dict(sorted(counters["event_type"].items())),
        "by_severity": {str(k): v for k, v in sorted(counters["severity"].items())},
        "alerts_by_severity": {str(k): v for k, v in sorted(counters["alert_severity"].items())},
        "by_outcome": dict(sorted(counters["outcome"].items())),
        "by_scenario": dict(sorted(counters["scenario"].items())),
        "ip_family": dict(sorted(counters["family"].items())),
        "distinct_devices": len(counters["devices"]), "distinct_source_ips": len(counters["ips"]),
        "events_per_date": {"min": min(counters["date"].values()), "max": max(counters["date"].values()),
                            "dates": len(counters["date"])},
        "partitions": {
            "events_by_device_day": distribution(counters["device_day"]),
            "events_by_ip_day": distribution(counters["ip_day"]),
            "alerts_by_severity_day": distribution(counters["severity_day"], top=5),
        },
    }


def build(seed: int, count: int) -> tuple[dict, float]:
    gen = bulk.BulkGenerator(seed)
    started = time.perf_counter()
    counters = {k: Counter() for k in ("category", "event_type", "severity", "alert_severity", "outcome", "scenario",
                                       "family", "date", "device_day", "ip_day", "severity_day")}
    counters["devices"], counters["ips"] = set(), set()
    digest, chunk_hashes, profiles, ids = hashlib.sha256(), [], {}, set()
    boundaries = sorted(set(p for p in bulk.PROFILES if p <= count) | {count})
    for chunk in range(count // bulk.CHUNK_SIZE):
        chunk_hash, events = gen.chunk_digest(chunk)
        chunk_hashes.append(chunk_hash)
        for e in events:
            digest.update(bulk.canonical_line(e))
            ids.add(e["event_id"])
            c = counters
            c["category"][e["category"]] += 1
            c["event_type"][f"{e['category']}/{e['event_type']}"] += 1
            c["severity"][e["severity"]] += 1
            c["outcome"][e["outcome"]] += 1
            c["scenario"][e["metadata"]["scenario"]] += 1
            c["family"]["ipv6" if ":" in e["source_ip"] else "ipv4"] += 1
            c["date"][e["event_date"]] += 1
            c["device_day"][(e["device_id"], e["event_date"])] += 1
            c["ip_day"][(e["source_ip"], e["event_date"])] += 1
            c["devices"].add(e["device_id"])
            c["ips"].add(e["source_ip"])
            if e["category"] == "alert":
                c["alert_severity"][e["severity"]] += 1
                c["severity_day"][(e["severity"], e["event_date"])] += 1
        done = (chunk + 1) * bulk.CHUNK_SIZE
        if done in boundaries:
            if len(ids) != done:
                raise SystemExit("FAIL: generated UUIDs are not unique")
            profiles[str(done)] = snapshot(done, digest, counters)
    manifest = {
        "dataset": bulk.DATASET, "generator_version": bulk.GENERATOR_VERSION, "seed": seed, "synthetic": True,
        "logical_events": count, "chunk_size": bulk.CHUNK_SIZE,
        "window": {"start": bulk.WINDOW_START.isoformat().replace("+00:00", "Z"),
                   "end_exclusive": bulk.WINDOW_END.isoformat().replace("+00:00", "Z"), "days": bulk.WINDOW_DAYS},
        "id_algorithm": bulk.ID_ALGORITHM, "rng_algorithm": bulk.RNG_ALGORITHM,
        "canonical_serialization": "json.dumps(event, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\\n'",
        "profiles_are_prefixes": "profile N contains exactly event indices [0, N)",
        "world": gen.describe_world(),
        "profiles": profiles,
        "chunk_sha256": chunk_hashes,
    }
    return manifest, time.perf_counter() - started


def check_prefix(manifest: dict) -> str:
    """A larger manifest must contain the original 1M manifest unchanged (profiles are prefixes)."""
    base_path = bulk.manifest_path(bulk.BASE_PROFILE)
    if manifest["logical_events"] <= bulk.BASE_PROFILE or not base_path.exists():
        return "not applicable"
    base = json.loads(base_path.read_text(encoding="utf-8"))
    chunks = bulk.BASE_PROFILE // bulk.CHUNK_SIZE
    same = (manifest["chunk_sha256"][:chunks] == base["chunk_sha256"]
            and all(manifest["profiles"][k] == v for k, v in base["profiles"].items())
            and manifest["world"] == base["world"] and manifest["seed"] == base["seed"])
    if not same:
        raise SystemExit(f"FAIL: the first {bulk.BASE_PROFILE} events differ from {base_path.name}")
    return f"first {bulk.BASE_PROFILE} events identical to {base_path.name} (chunks, profiles, world)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=bulk.BASE_PROFILE,
                        help="logical events (multiple of 1000, at most 5 000 000)")
    parser.add_argument("--seed", type=int, default=bulk.DEFAULT_SEED)
    args = parser.parse_args()
    if not (bulk.CHUNK_SIZE <= args.count <= bulk.MAX_EVENTS) or args.count % bulk.CHUNK_SIZE:
        raise SystemExit("--count must be a multiple of 1000 between 1000 and 5000000")
    manifest, seconds = build(args.seed, args.count)
    prefix = check_prefix(manifest)
    data = (json.dumps(manifest, indent=1, sort_keys=False) + "\n").encode("utf-8")
    BULK_DIR.mkdir(parents=True, exist_ok=True)
    target = bulk.manifest_path(args.count)
    if target.exists():
        existing = target.read_bytes()
        if existing != data:
            raise SystemExit(f"FAIL: {target.name} exists with different content; refusing to overwrite")
        status = "reproduced identical existing manifest"
    else:
        target.write_bytes(data)
        status = "wrote new manifest"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {"kind": "generation_manifest", "dataset": bulk.DATASET, "seed": args.seed, "logical_events": args.count,
              "status": status, "manifest": target.name, "prefix_check": prefix,
              "manifest_sha256": hashlib.sha256(data).hexdigest(),
              "generation_seconds": round(seconds, 3), "events_per_second": round(args.count / seconds, 1),
              "finished_at_utc": stamp, "python": platform.python_version(), "platform": platform.platform(),
              "note": "Generation time only (CPU, no I/O to databases); not a database measurement."}
    reports = BULK_DIR / "reports"
    reports.mkdir(exist_ok=True)
    (reports / f"generate-{args.count}-{stamp}.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    last = manifest["profiles"][str(args.count)]
    print(f"PASS: {status} ({target.name}); {args.count} events in {seconds:.1f}s; alerts={last['alert_events']}; "
          f"expected Cassandra live rows={last['expected_cassandra_live_rows']}; sha256={last['sha256_canonical_ndjson'][:16]}...")
    print(f"prefix check: {prefix}")


if __name__ == "__main__":
    main()
