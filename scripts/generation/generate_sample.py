"""Generate exactly 24 deterministic synthetic events; this is not a bulk generator."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]
DATASET = "cyberguard-task02-sample-v1"


def events() -> list[dict]:
    templates = [
        ("authentication", "login", 1, "success", "soc-sensor-01", "192.0.2.10", "00:00:00.000"),
        ("authentication", "login", 2, "failure", "soc-sensor-01", "192.0.2.11", "01:00:00.000"),
        ("authentication", "suspicious_access", 3, "unknown", "soc-sensor-02", "2001:db8::10", "02:00:00.123"),
        ("network", "connection", 4, "blocked", "soc-sensor-01", "192.0.2.10", "03:00:00.000"),
        ("network", "traffic_anomaly", 5, "unknown", "soc-sensor-02", "2001:db8::10", "04:00:00.000"),
        ("alert", "potential_threat", 4, "unknown", "soc-sensor-01", "192.0.2.10", "12:00:00.000"),
        ("alert", "potential_threat", 4, "unknown", "soc-sensor-01", "192.0.2.10", "12:00:00.000"),
        ("alert", "potential_threat", 5, "unknown", "soc-sensor-02", "2001:db8::10", "23:59:59.999"),
    ]
    result = []
    for day in range(3):
        date = (datetime(2026, 11, 6, tzinfo=timezone.utc) + timedelta(days=day)).date().isoformat()
        for category, kind, severity, outcome, device, ip, clock in templates:
            index = len(result)
            digest = hashlib.sha256(f"{DATASET}:{index}".encode()).digest()[:16]
            result.append({
                "event_id": str(uuid.UUID(bytes=digest, version=4)),
                "occurred_at": f"{date}T{clock}Z", "event_date": date,
                "device_id": device, "source_ip": ip, "category": category,
                "event_type": kind, "severity": severity, "outcome": outcome,
                "message": f"Synthetic {kind} event {index:02d}; no real security activity.",
                "metadata": {"dataset": DATASET, "synthetic": True, "sequence": index, "tags": ["academic", "validation"]},
            })
    return result


def main() -> None:
    sample = events()
    contents = (json.dumps(sample, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    alerts = sum(event["category"] == "alert" for event in sample)
    manifest = {"dataset": DATASET, "synthetic": True, "logical_events": len(sample),
                "alert_events": alerts, "expected_cassandra_live_rows": 3 * len(sample) + alerts,
                "id_algorithm": "first 16 bytes of SHA256(dataset + ':' + index), UUID v4 bits",
                "sha256": hashlib.sha256(contents).hexdigest()}
    outputs = {
        ROOT / "data/samples/events.json": contents,
        ROOT / "data/samples/events.manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
    }
    for path, data in outputs.items():
        if path.exists() and path.read_bytes() != data:
            raise SystemExit(f"Refusing to overwrite different existing file: {path.name}")
    for path, data in outputs.items():
        if not path.exists():
            path.write_bytes(data)
    print(f"PASS: {len(sample)} deterministic synthetic events, {alerts} alerts, {3 * len(sample) + alerts} live Cassandra rows")


if __name__ == "__main__":
    main()
