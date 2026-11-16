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

    assert request("GET", path)[0] == 404, "Only inject faults into a fresh, never-seen test-owned ID"
    try:
        # Simulate a crash right after step 1 of CREATE: the canonical reservation is
        # durable as 'pending', no projection was written and the activation (which is
        # when the dashboard rollup counts the event) never happened. Repair must
        # finish the projections, activate and count it exactly once.
        payload = json.dumps({"data": event, "revision": 1}, separators=(",", ":")).replace("'", "''")
        cql(f"INSERT INTO cyberguard.events_by_id (event_id, payload, revision, lifecycle) "
            f"VALUES ({event_id}, '{payload}', 1, 'pending') IF NOT EXISTS;\n")
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
