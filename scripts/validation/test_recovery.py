"""Inject interrupted states only for a fresh, owned synthetic ID in Cassandra."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import urllib.parse
import uuid
from test_integration import request

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-config")
    args = parser.parse_args()
    command = ["docker"] + (["--config", args.docker_config] if args.docker_config else [])
    command += ["compose", "exec", "-T", "cassandra", "cqlsh", "127.0.0.1", "9042"]
    event = copy.deepcopy(json.loads((ROOT / "data/samples/events.json").read_text(encoding="utf-8"))[5])
    event["event_id"] = str(uuid.uuid4())
    event["device_id"] = "recovery-" + event["event_id"][:8]
    event["metadata"]["recovery_test"] = event["event_id"]
    event_id = event["event_id"]
    path = f"/api/cassandra/events/{event_id}"
    query_path = "/api/cassandra/queries/device?" + urllib.parse.urlencode({
        "device_id":event["device_id"],"from":"2026-11-06T00:00:00Z","to":"2026-11-07T00:00:00Z"})

    def cql(source):
        result = subprocess.run(command, input=source.encode(), cwd=ROOT, capture_output=True)
        if result.returncode or any(token in result.stderr for token in (b"Exception", b"InvalidRequest", b"Error")):
            raise AssertionError("CQL fault injection failed")

    status, _ = request("POST", "/api/cassandra/events", event)
    assert status == 201, "Only inject faults into a newly created test-owned ID"
    try:
        # Simulate a crash after canonical reservation but before index acknowledgement.
        cql(f"UPDATE cyberguard.events_by_id SET lifecycle='pending' WHERE event_id={event_id};\n"
            f"DELETE FROM cyberguard.events_by_device_day WHERE device_id='{event['device_id']}' AND event_date='{event['event_date']}' AND occurred_at='{event['occurred_at']}' AND event_id={event_id};\n")
        assert request("GET", path)[0] == 503
        assert request("GET", query_path) == (200, {"items":[],"next_cursor":None})
        assert request("POST", path + "/repair") == (200, {"state": "active"})
        assert request("GET", path) == (200, {"data": event, "revision": 1})
        assert request("GET", query_path) == (200, {"items":[{"data":event,"revision":1}],"next_cursor":None})
        print("PASS: interrupted CREATE repaired by ID without a table scan")

        # An obsolete projection must never expose a logically deleted event.
        cql(f"UPDATE cyberguard.events_by_id SET lifecycle='deleting' WHERE event_id={event_id};\n")
        assert request("GET", path)[0] == 503
        assert request("GET", query_path) == (200, {"items":[],"next_cursor":None})
        assert request("POST", path + "/repair") == (200, {"state": "deleted"})
        assert request("GET", path)[0] == 404
        assert request("POST", path + "/repair") == (200, {"state": "deleted"})
        assert request("POST", "/api/cassandra/events", event)[0] == 409
        print("PASS: interrupted DELETE repaired; deleted UUID cannot be reused")
    finally:
        # Targeted cleanup: only this fresh test UUID. Never remove tables or volumes.
        status, body = request("GET", path)
        if status == 503:
            request("POST", path + "/repair")
            status, body = request("GET", path)
        if status == 200:
            assert body["data"]["metadata"].get("recovery_test") == event_id
            assert request("DELETE", path + f"?expected_revision={body['revision']}")[0] == 204


if __name__ == "__main__":
    main()
