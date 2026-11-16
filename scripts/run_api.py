"""Build and run the CyberGuard API inside the official Rust image (no Rust on the host).

    python scripts/run_api.py build            # cargo build --release (Linux binary)
    python scripts/run_api.py start            # container 'cyberguard-api' on 127.0.0.1:3000
    python scripts/run_api.py start --read-concurrency 1   # N+1 baseline (sequential reads)
    python scripts/run_api.py start --pg-synchronous-commit off   # durability-matched writes
    python scripts/run_api.py status | stop | logs

The container joins the Compose network, reads `.env` through `--env-file`
(values are never printed) and mounts the repository read-only. The databases
stay managed by Docker Compose; no volume is created or removed here. A native
`cargo run --release --manifest-path backend/Cargo.toml` is equivalent when Rust
is installed on the host.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "rust:1.99.1-slim-bookworm"
NAME = "cyberguard-api"
NETWORK = "cyberguard_storage"


def docker(config: str | None) -> list[str]:
    return ["docker"] + (["--config", config] if config else [])


def run(command: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=ROOT, **kwargs)
    if check and result.returncode != 0:
        raise SystemExit(f"FAIL: '{' '.join(command[:4])} ...' exited with {result.returncode}")
    return result


def health(timeout: float = 3.0):
    try:
        with urllib.request.urlopen("http://127.0.0.1:3000/api/health", timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def build(args) -> None:
    profile = [] if args.debug else ["--release"]
    offline = ["--offline"] if args.offline else []
    command = " ".join(["cargo", "build", "--locked", *offline, *profile, "-j", str(args.jobs)])
    run(docker(args.docker_config) + [
        "run", "--rm", "--name", "cyberguard-rust-build",
        "--mount", f"type=bind,source={ROOT},target=/workspace",
        "--workdir", "/workspace/backend", "--env", "CARGO_HOME=/workspace/tmp/cargo",
        IMAGE, "sh", "-c", command])
    print(f"PASS: built backend/target/{'debug' if args.debug else 'release'}/cyberguard-api")


def start(args) -> None:
    profile = "debug" if args.debug else "release"
    binary = ROOT / "backend/target" / profile / "cyberguard-api"
    if not binary.is_file():
        raise SystemExit(f"FAIL: {binary.relative_to(ROOT)} missing; run 'python scripts/run_api.py build' first")
    if not (ROOT / ".env").is_file():
        raise SystemExit("FAIL: .env missing; run 'python scripts/setup_env.py'")
    if health():
        raise SystemExit("FAIL: an API already answers on 127.0.0.1:3000; stop it first")
    env = ["--env", "API_BIND=0.0.0.0:3000", "--env", "POSTGRES_HOST=postgresql",
           "--env", "CASSANDRA_CONTACT_POINT=cassandra:9042"]
    if args.read_concurrency:
        env += ["--env", f"CASSANDRA_READ_CONCURRENCY={args.read_concurrency}"]
    if args.pg_synchronous_commit:
        env += ["--env", f"POSTGRES_SYNCHRONOUS_COMMIT={args.pg_synchronous_commit}"]
    if args.pg_pool_size:
        env += ["--env", f"POSTGRES_POOL_SIZE={args.pg_pool_size}"]
    run(docker(args.docker_config) + [
        "run", "--rm", "--detach", "--name", NAME, "--network", NETWORK,
        "--publish", "127.0.0.1:3000:3000",
        "--mount", f"type=bind,source={ROOT},target=/workspace,readonly",
        "--workdir", "/workspace", "--env-file", ".env", *env,
        IMAGE, f"/workspace/backend/target/{profile}/cyberguard-api"], stdout=subprocess.DEVNULL)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        body = health()
        if body:
            print(f"PASS: API {body.get('version')} ({body.get('build')}) on http://127.0.0.1:3000")
            return
        time.sleep(0.5)
    raise SystemExit("FAIL: API did not answer within 60 s; see 'python scripts/run_api.py logs'")


def stop(args) -> None:
    result = run(docker(args.docker_config) + ["stop", "--signal", "SIGINT", NAME], check=False,
                 capture_output=True)
    print("PASS: API container stopped" if result.returncode == 0 else "INFO: API container was not running")


def status(args) -> None:
    body = health()
    print(f"API: {json.dumps(body) if body else 'not reachable on 127.0.0.1:3000'}")


def logs(args) -> None:
    run(docker(args.docker_config) + ["logs", "--tail", "60", NAME], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["build", "start", "stop", "status", "logs"])
    parser.add_argument("--debug", action="store_true", help="use the debug profile (not for benchmarks)")
    parser.add_argument("--offline", action="store_true", help="build only from the local cargo cache")
    parser.add_argument("--jobs", type=int, default=8, help="parallel rustc jobs (limits memory use)")
    parser.add_argument("--read-concurrency", type=int, help="CASSANDRA_READ_CONCURRENCY (1..128)")
    parser.add_argument("--pg-synchronous-commit", choices=["on", "off"],
                        help="POSTGRES_SYNCHRONOUS_COMMIT for the durability-matched write experiment")
    parser.add_argument("--pg-pool-size", type=int, help="POSTGRES_POOL_SIZE (1..64, default 16)")
    parser.add_argument("--docker-config", help="optional Docker CLI config directory")
    args = parser.parse_args()
    {"build": build, "start": start, "stop": stop, "status": status, "logs": logs}[args.action](args)


if __name__ == "__main__":
    main()
