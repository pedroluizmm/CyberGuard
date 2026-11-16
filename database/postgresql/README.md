# PostgreSQL

- `001_events.sql` cria `devices`, `event_registry` e `events`, com PKs, FKs, CHECKs e os índices de Q1/Q2/Q3. A tabela `events` é tipada, e o registro de UUIDs impede reutilizar um ID depois do DELETE.
- `002_dashboard.sql` cria o índice de cobertura `events_time_cover_idx (occurred_at) INCLUDE (category, severity)` para o painel agregado (*index-only scan*) e executa `ANALYZE`.

As justificativas estão em `docs/data-model.md`, as consultas em `docs/query-patterns.md` e o uso nos experimentos em `docs/benchmark-methodology.md`.

Aplique da raiz com `python scripts/apply_schema.py`, que roda todos os arquivos `NNN_*.sql` em ordem e funciona sobre os volumes existentes. Reaplicar é aditivo. Nenhum índice existente foi removido ou alterado para os experimentos.
