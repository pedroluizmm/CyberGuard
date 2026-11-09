# PostgreSQL

`001_events.sql` cria devices, event_registry e events, com PKs/FKs/CHECKs e índices adequados a Q1/Q2/Q3. A tabela events é tipada; o registro de UUIDs evita reutilização após DELETE. Transações mantêm registro/evento consistentes. Justificativas em `docs/data-model.md` e consultas em `docs/query-patterns.md`.

Aplicar da raiz: `python scripts/apply_schema.py`. Isso funciona nos volumes existentes; não depende dos scripts de inicialização da imagem (executados só no primeiro boot de um volume novo). Reaplicar é aditivo; futuras alterações exigem migração explícita. O probe da Task 01 continua usando `SELECT 1`.
