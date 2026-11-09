"""Probe the real API. Never substitute mocks for unavailable services."""
import json
import os
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:3000"


def request(path: str, origin: str | None = None) -> tuple[int, object, dict]:
    headers = {"Accept": "application/json"}
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(BASE + path, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=12)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response), dict(response.headers)


def main() -> None:
    try:
        status, body, headers = request("/api/health")
        assert status == 200 and body["status"] == "ok" and body["service"] == "cyberguard-api"
        assert headers.get("cache-control", headers.get("Cache-Control")) == "no-store"
        print("PASS: real API liveness")
        origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
        _, _, allowed = request("/api/health", origin)
        lowered = {key.lower(): value for key, value in allowed.items()}
        assert lowered.get("access-control-allow-origin") == origin
        _, _, denied = request("/api/health", "https://example.org")
        lowered = {key.lower(): value for key, value in denied.items()}
        assert lowered.get("access-control-allow-origin") not in ("https://example.org", "*")
        print("PASS: CORS restricted to configured local origin")
        status, body, _ = request("/api/health/storage")
        ready = True
        for name in ("cassandra", "postgresql"):
            probe = body[name]
            assert probe["status"] in ("up", "down")
            assert isinstance(probe["duration_ms"], (int, float)) and probe["duration_ms"] >= 0
            assert (probe["error"] is None) if probe["status"] == "up" else isinstance(probe["error"], str)
            ready = ready and probe["status"] == "up"
            print(f"REAL: {name} status={probe['status']} duration_ms={probe['duration_ms']} error={probe['error']}")
        assert status == (200 if ready else 503)
        assert body["status"] == ("ok" if ready else "degraded")
        if not ready:
            print("FAIL: at least one database is unavailable; readiness is not approved")
            raise SystemExit(1)
        print("PASS: both databases answered real queries")
    except (urllib.error.URLError, TimeoutError, OSError):
        print("BLOCKED: local API could not be reached; start the Rust backend")
        raise SystemExit(1) from None
    except (AssertionError, KeyError, TypeError, ValueError):
        print("FAIL: API contract differs from the expected health response")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
