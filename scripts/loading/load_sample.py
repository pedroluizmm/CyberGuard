"""Load the same small fixture through the real API; never overwrite conflicts."""
import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--source", choices=["both", "postgresql", "cassandra"], default="both")
    args = parser.parse_args()
    sample = json.loads((ROOT / "data/samples/events.json").read_text(encoding="utf-8"))
    if not 1 <= len(sample) <= 1000:
        raise SystemExit("This loader is restricted to small fixtures (1..1000 events)")
    sources = ["postgresql", "cassandra"] if args.source == "both" else [args.source]
    for source in sources:
        created = reused = 0
        for event in sample:
            req = urllib.request.Request(f"{args.base_url}/api/{source}/events", data=json.dumps(event).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=35) as response:
                    actual = json.load(response)
                    if actual != {"data": event, "revision": 1}:
                        raise SystemExit(f"FAIL: {source} returned different event content")
                    created += response.status == 201
                    reused += response.status == 200
            except urllib.error.HTTPError as error:
                raise SystemExit(f"FAIL: {source} HTTP {error.code}; existing data was not overwritten") from None
            except (urllib.error.URLError, TimeoutError):
                raise SystemExit(f"FAIL: API unavailable while loading {source}; safely retry the same sample") from None
        print(f"PASS: {source}: {created} created, {reused} identical events reused")


if __name__ == "__main__":
    main()
