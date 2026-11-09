"""Apply additive SQL/CQL files to the existing Compose services, preserving data."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-config", help="Optional Docker CLI config directory")
    args = parser.parse_args()
    docker = ["docker"]
    if args.docker_config:
        docker += ["--config", args.docker_config]
    jobs = [
        ("database/postgresql/001_events.sql", ["postgresql", "sh", "-c", 'exec psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --set=ON_ERROR_STOP=1']),
        ("database/cassandra/001_events.cql", ["cassandra", "cqlsh", "127.0.0.1", "9042"]),
    ]
    for filename, command in jobs:
        source = (ROOT / filename).read_bytes()
        result = subprocess.run(docker + ["compose", "exec", "-T"] + command,
                                input=source, cwd=ROOT, capture_output=True)
        # cqlsh sometimes reports statement errors on stderr with zero exit status.
        errors = result.stderr.decode("utf-8", errors="replace")
        failed = result.returncode != 0 or any(word in errors for word in (
            "SyntaxException", "InvalidRequest", "ConfigurationException", "Unauthorized", "Traceback", "Error"))
        if failed:
            print(f"FAIL: {filename}; schema application did not complete")
            # No .env values or rendered Compose config are printed.
            print(errors)
            raise SystemExit(1)
        print(f"PASS: applied {filename} without replacing tables or volumes")


if __name__ == "__main__":
    main()
