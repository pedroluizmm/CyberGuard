"""Apply additive SQL/CQL files to the existing Compose services, preserving data.

Every `database/<engine>/NNN_*.{sql,cql}` file is applied in lexical order. All
files are written to be repeatable (IF NOT EXISTS); none drops or truncates.
"""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PSQL = ["postgresql", "sh", "-c", 'exec psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --set=ON_ERROR_STOP=1']
CQLSH = ["cassandra", "cqlsh", "127.0.0.1", "9042"]
ERRORS = ("SyntaxException", "InvalidRequest", "ConfigurationException", "Unauthorized", "Traceback", "Error")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-config", help="Optional Docker CLI config directory")
    args = parser.parse_args()
    docker = ["docker"]
    if args.docker_config:
        docker += ["--config", args.docker_config]
    jobs = [(path, PSQL) for path in sorted((ROOT / "database/postgresql").glob("[0-9][0-9][0-9]_*.sql"))]
    jobs += [(path, CQLSH) for path in sorted((ROOT / "database/cassandra").glob("[0-9][0-9][0-9]_*.cql"))]
    for path, command in jobs:
        filename = path.relative_to(ROOT).as_posix()
        result = subprocess.run(docker + ["compose", "exec", "-T"] + command,
                                input=path.read_bytes(), cwd=ROOT, capture_output=True)
        # cqlsh sometimes reports statement errors on stderr with zero exit status.
        errors = result.stderr.decode("utf-8", errors="replace")
        if result.returncode != 0 or any(word in errors for word in ERRORS):
            print(f"FAIL: {filename}; schema application did not complete")
            # No .env values or rendered Compose config are printed.
            print(errors)
            raise SystemExit(1)
        print(f"PASS: applied {filename} without replacing tables or volumes")


if __name__ == "__main__":
    main()
