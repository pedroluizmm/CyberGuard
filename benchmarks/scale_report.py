"""Print the consolidated scale comparison (Markdown) from benchmarks/results/summary.json.

    python benchmarks/scale_report.py                 # smallest vs largest size of the 'escala' campaign
    python benchmarks/scale_report.py --all-sizes     # one column pair per measured size

Numbers are read from the recorded runs only; nothing is measured here. Used to write the
tables of docs/benchmark-methodology.md and the final report, so they match the evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "benchmarks/results/summary.json"
CLASS = {"chave": "chave (1 evento)", "pagina_fixa": "página fixa", "resposta_crescente": "resposta cresce",
         "agregacao": "agregação"}
WHO = {"postgresql": "PG", "cassandra": "CS"}


def num(value, digits=None) -> str:
    if value is None:
        return "—"
    if digits is None:
        digits = 2 if value < 10 else 1 if value < 100 else 0
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def millions(n: int) -> str:
    return f"{n / 1e6:g} M".replace(".", ",")


def delta(a, b) -> str:
    if not a or b is None:
        return "—"
    pct = 100 * (b - a) / a
    return f"{'+' if pct >= 0 else '−'}{num(abs(pct), 1 if abs(pct) < 10 else 0)}%"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--campaign", default="escala")
    parser.add_argument("--all-sizes", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    campaign = (summary.get("campaigns") or {}).get(args.campaign)
    if not campaign:
        raise SystemExit(f"FAIL: no campaign '{args.campaign}' in summary.json")
    scale = campaign["scale"]
    sizes = scale["sizes"]
    lo, hi = sizes[0], sizes[-1]
    shown = sizes if args.all_sizes else [lo, hi]
    print(f"Campanha '{args.campaign}': volumes {', '.join(millions(n) for n in sizes)}; "
          f"execuções main: {', '.join(e['main']['run_id'] for e in campaign['sizes'])}\n")
    head = ["Operação", "Classe", "Eventos cobertos"] + [f"{db} {millions(n)}" for n in shown for db in ("PG", "CS")] \
        + [f"Δ PG {millions(lo)}→{millions(hi)}", f"Δ CS {millions(lo)}→{millions(hi)}", "Vencedor (razão)"]
    print("| " + " | ".join(head) + " |")
    print("|" + " --- |" * len(head))
    for op in scale["operations"]:
        pts = {p["logical_events"]: p for p in op["points"]}
        a, b = pts.get(lo), pts.get(hi)
        covered = f"{num(a['covered_events'], 0)} → {num(b['covered_events'], 0)}" if a and b and a["covered_events"] else "—"
        cells = []
        for n in shown:
            p = pts.get(n)
            cells += [num(p["postgresql"]["http"]["median"]) if p else "—", num(p["cassandra"]["http"]["median"]) if p else "—"]
        winners = " → ".join(f"{WHO.get(pts[n].get('faster'), '?')} {num(pts[n].get('ratio'), 1)}×" for n in shown if n in pts)
        print(f"| {op['experiment']} {op['title']} | {CLASS.get(op['class'], '—')} | {covered} | " + " | ".join(cells)
              + f" | {delta(a and a['postgresql']['http']['median'], b and b['postgresql']['http']['median'])}"
              + f" | {delta(a and a['cassandra']['http']['median'], b and b['cassandra']['http']['median'])} | {winners} |")
    print("\nE5 (medianas, ms)\n")
    print("| Volume | PG agregação (psql) | PG view materializada | PG REFRESH completo | Cassandra rollup (db) |")
    print("| --- | --- | --- | --- | --- |")
    for c in scale["control"]:
        print(f"| {millions(c['logical_events'])} | {num(c['pg_on_read_aggregate_7d'])} | {num(c['pg_mv_read_7d'])} | "
              f"{num(c['pg_mv_refresh_full'])} | {num(c['cassandra_rollup_db_7d'])} |")
    print("\nE6 (mediana de latência, ms, PG / CS)\n")
    print("| Volume | Política | CREATE | UPDATE | DELETE |")
    print("| --- | --- | --- | --- | --- |")
    for w in scale["writes"]:
        label = "padrão" if w["config"] == "padrao" else "antes do fsync"
        print(f"| {millions(w['logical_events'])} | {label} | " + " | ".join(
            f"{num(w[op]['postgresql']['median_ms'])} / {num(w[op]['cassandra']['median_ms'])}"
            for op in ("create", "update", "delete")) + " |")
    print("\nAmbiente por volume\n")
    print("| Volume | Banco PG | Keyspace Cassandra | Cache PG (shared_buffers) | Key cache Cassandra | Disco lido nas leituras | Energia |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for entry in campaign["sizes"]:
        env, cache = entry["main"]["environment"], (entry["main"].get("cache") or {}).get("read_phase") or {}
        pg, cs = env.get("postgresql") or {}, env.get("cassandra") or {}
        durability_env = (entry.get("durability") or {}).get("environment") or {}
        power = (env.get("host") or {}).get("power") or (durability_env.get("host") or {}).get("power") or {}
        disk = sum((cache.get("disk_read_bytes") or {}).values()) if cache.get("disk_read_bytes") else None
        share = lambda d: f"{num(100 * d['hit_ratio'], 2)}%" if d and d.get("hit_ratio") is not None else "—"  # noqa: E731
        print(f"| {millions(entry['logical_events'])} | {num((pg.get('database_bytes') or 0) / 1e9, 2)} GB | "
              f"{num(((cs.get('du_bytes') or {}).get('/var/lib/cassandra/data/cyberguard') or 0) / 1e9, 2)} GB | "
              f"{share(cache.get('postgresql_shared_buffers'))} | {share(cache.get('cassandra_key_cache'))} | "
              f"{num((disk or 0) / 1e6, 1) + ' MB' if disk is not None else '—'} | "
              f"{'tomada' if power.get('on_ac_power') else ('bateria ' + str(power.get('battery_percent')) + '%') if power else 'não registrado'} |")


if __name__ == "__main__":
    main()
