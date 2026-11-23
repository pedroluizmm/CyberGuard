"""Write docs/apresentacao/dados-escala.js from the measured evidence (no number is typed by hand).

Sources (all versioned):
  * benchmarks/results/summary.json            campaigns.escala (medians per operation and size, E5, E6)
  * data/bulk/reports/load-*.json              incremental loads via API (release build)
  * data/bulk/reports/validate-*.json          integrity checks per milestone
  * data/bulk/reports/rollup-check-*.json      rollup == canonical truth == PostgreSQL

    python docs/apresentacao/dados_slides.py   (build_pdf.py runs it before printing)
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUMMARY = ROOT / "benchmarks/results/summary.json"
REPORTS = ROOT / "data/bulk/reports"
OUTPUT = HERE / "dados-escala.js"
SHORT = {
    "e1_read_by_id": "READ por UUID",
    "q1_device_hot_page": "Q1 dispositivo, página 100",
    "q1_device_hot_10pages": "Q1 10 páginas (1.000)",
    "q1_device_cold_page": "Q1 dispositivo pouco ativo",
    "q2_ip_hot_page": "Q2 IP de campanha",
    "q3_alerts_page": "Q3 alertas severidade 3",
    "overview_7d": "Painel 7 dias",
    "overview_1d": "Painel 1 dia",
    "overview_7d_alerts": "Painel 7 dias, só alertas",
}


def latest(pattern: str) -> dict[int, dict]:
    """Newest report per target size for a file pattern."""
    out: dict[int, dict] = {}
    for path in sorted(REPORTS.glob(pattern)):
        report = json.loads(path.read_text(encoding="utf-8"))
        report["_file"] = path.name
        target = report.get("target_events")
        if target:
            out[target] = report
    return out


def build() -> dict:
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    campaign = (summary.get("campaigns") or {}).get("escala")
    if not campaign:
        raise SystemExit("FAIL: summary.json has no 'escala' campaign")
    scale = campaign["scale"]
    sizes = scale["sizes"]
    ops = []
    for op in scale["operations"]:
        ops.append({
            "id": op["id"], "exp": op["experiment"], "label": SHORT.get(op["id"], op["title"]), "class": op["class"],
            "points": [{"n": p["logical_events"], "pg": p["postgresql"]["http"]["median"],
                        "cs": p["cassandra"]["http"]["median"], "pg_db": p["postgresql"]["db_median"],
                        "cs_db": p["cassandra"]["db_median"], "faster": p.get("faster"), "ratio": p.get("ratio"),
                        "covered": p.get("covered_events"), "equivalent": p["equivalent"],
                        "replicates": p.get("replicates", [])} for p in op["points"]],
        })
    storage, power, cache = [], [], []
    for entry in campaign["sizes"]:
        env = entry["main"]["environment"]
        pg, cs = env.get("postgresql") or {}, env.get("cassandra") or {}
        storage.append({"n": entry["logical_events"], "pg_database_bytes": pg.get("database_bytes"),
                        "pg_events_bytes": pg.get("events_total_bytes"),
                        "cs_keyspace_bytes": (cs.get("du_bytes") or {}).get("/var/lib/cassandra/data/cyberguard")})
        # Power is recorded per run; a main run that predates the field uses the E6 run of the same size.
        p = (env.get("host") or {}).get("power") or \
            (((entry.get("durability") or {}).get("environment") or {}).get("host") or {}).get("power") or {}
        power.append({"n": entry["logical_events"], "on_ac_power": p.get("on_ac_power"), "battery": p.get("battery_percent")})
        phase = (entry["main"].get("cache") or {}).get("read_phase") or {}
        cache.append({"n": entry["logical_events"],
                      "pg": (phase.get("postgresql_shared_buffers") or {}).get("hit_ratio"),
                      "cs": (phase.get("cassandra_key_cache") or {}).get("hit_ratio"),
                      "disk_read_bytes": phase.get("disk_read_bytes")})
    loads = []
    for path in sorted(REPORTS.glob("load-*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        # Initial 1M load (Task 03, debug build, one database at a time) and the release-build increments.
        if r.get("target_events", 0) >= 1_000_000 and r.get("created"):
            loads.append({"source": r["source"], "target": r["target_events"], "created": r["created"],
                          "reused": r["reused"], "seconds": r["wall_seconds"], "rate": r["events_per_second"],
                          "build": r.get("api_build"), "stopped": r.get("stopped"), "file": path.name})
    validations = {n: {"passed": sum(c["pass"] for c in r["checks"]), "total": len(r["checks"]), "file": r["_file"],
                       "seconds": r.get("wall_seconds")}
                   for n, r in latest("validate-*.json").items()}
    rollups = []
    for path in sorted(REPORTS.glob("rollup-check-*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        rollups.append({"events": r["truth_events"], "cells": r["truth_cells"], "deltas": r["delta_events"],
                        "pg_equal": r["postgresql_equal_to_cassandra_truth"], "file": path.name})
    return {"generated_from": ["benchmarks/results/summary.json", "data/bulk/reports"], "sizes": sizes, "ops": ops,
            "control": scale["control"], "writes": scale["writes"], "storage": storage, "power": power, "cache": cache,
            "loads": loads, "validations": validations, "rollups": rollups,
            "runs": {str(e["logical_events"]): {"main": e["main"]["run_id"],
                                                "durability": (e.get("durability") or {}).get("run_id")}
                     for e in campaign["sizes"]}}


def main() -> None:
    data = build()
    OUTPUT.write_text("// Gerado por docs/apresentacao/dados_slides.py a partir das evidências; não editar à mão.\n"
                      f"window.ESCALA = {json.dumps(data, ensure_ascii=False, indent=1)};\n", encoding="utf-8")
    print(f"PASS: wrote {OUTPUT.relative_to(ROOT)} (sizes {data['sizes']}, {len(data['loads'])} load reports)")


if __name__ == "__main__":
    main()
