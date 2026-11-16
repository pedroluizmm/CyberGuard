# Cassandra

- `001_events.cql` cria o keyspace e quatro tabelas. `events_by_id` guarda o envelope JSON, a revisão e o ciclo de vida. As três projeções armazenam chaves imutáveis por dispositivo/dia, IP/dia e severidade/dia.
- `002_rollup.cql` cria `event_counts_by_day`, a tabela do painel: partição por data UTC e um contador por (hora, categoria, severidade). A API a mantém nas transições LWT vencedoras; `scripts/loading/reconcile_rollup.py` faz o backfill e corrige desvios.

Modelo, partições, amplificação e recuperação estão em `docs/data-model.md` e `docs/consistency.md`. As consultas estão em `docs/query-patterns.md`.

Aplique da raiz com `python scripts/apply_schema.py`, que roda todos os arquivos `NNN_*.cql` em ordem, depois dos healthchecks. A imagem Cassandra não executa `/docker-entrypoint-initdb.d`. Reaplicar preserva os dados (`IF NOT EXISTS`); mudanças de esquema exigem um novo arquivo aditivo, nunca DROP.

Este é um laboratório: `NetworkTopologyStrategy` com `datacenter1:1`, `LOCAL_QUORUM` e `LOCAL_SERIAL` nas LWT. Um nó não oferece redundância.
