"""Verify original documents and Git hygiene without exposing local secrets."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ORIGINALS = {
    "entregáveis.pdf": "c286b3c4b3d030d52656d2f4c06f9bcb90cf8fad625149dc34ed9dd590506253",
    "Equipe - Página1.pdf": "02f0492221d9c3efca83790855dbf29931499e5c60df595bc0eb7ddac96ff6c8",
    "Projeto_3_NoSQL_Instrucoes_Atualizadas.pdf": "4953a7bce9b915cbb383f82eb867373e240fcd448cc5534aa350a2312e1639ce",
}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def main() -> None:
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        print(f"{'PASS' if condition else 'FAIL'}: {label}")
        if not condition:
            failures.append(label)

    check(git("rev-parse", "--is-inside-work-tree").returncode == 0, "Git repository exists")
    for name, digest in ORIGINALS.items():
        path = ROOT / name
        check(path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
              f"Original PDF preserved: {name}")
        check(git("check-ignore", "--quiet", "--", name).returncode == 0, f"PDF ignored: {name}")
        tracked = git("ls-files", "--", name)
        check(tracked.returncode == 0 and not tracked.stdout.strip(), f"PDF untracked: {name}")

    for path in [".env", ".env.local", "credentials.local.json", "private.key", "data/generated/check.csv", "frontend/node_modules/check", "frontend/dist/check", "backend/target/check", ".venv/check", "scripts/__pycache__/check.pyc", ".pytest_cache/check", "tmp/check.log", ".playwright-mcp/check.yaml"]:
        check(git("check-ignore", "--quiet", "--", path).returncode == 0, f"Ignored: {path}")
    for path in [".env.example", "data/samples/check.csv", "database/cassandra/schema.cql", "database/postgresql/schema.sql", "benchmarks/check.json", "data/generated/README.md", "data/bulk/check.manifest.json", "data/bulk/reports/check.json", "backend/Cargo.lock", "frontend/package-lock.json"]:
        check(git("check-ignore", "--quiet", "--", path).returncode == 1, f"Versionable: {path}")

    check((ROOT / ".env").is_file(), "Local .env exists")
    candidates = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    check(candidates.returncode == 0, "Versionable file enumeration succeeded")
    unsafe: list[str] = []
    password = None
    if (ROOT / ".env").is_file():
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("POSTGRES_PASSWORD="):
                password = line.split("=", 1)[1]
    check(bool(password) and password != "replace_with_generated_local_password", "Local password generated")
    for raw in candidates.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8")
        if relative == ".env" or (relative.startswith("data/generated/") and relative != "data/generated/README.md"):
            unsafe.append(relative)
        path = ROOT / relative
        if password and path.is_file() and password.encode() in path.read_bytes():
            unsafe.append(relative)
    check(not unsafe, "No local password or generated dataset among versionable files")
    manifest = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    check(manifest["private"] is True, "Frontend package is private")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
