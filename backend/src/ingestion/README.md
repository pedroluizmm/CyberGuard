# Ingestão

Não há endpoint de ingestão em lote nem módulo Rust próprio. A carga volumosa da Task 03 (`scripts/loading/load_bulk.py`) usa o CREATE existente (`POST /api/{fonte}/events`), preservando validação, idempotência por UUID, transação PostgreSQL e o fluxo pending/active do Cassandra. Um caminho de bulk loading dedicado só deve ser criado se a Task 04 demonstrar necessidade, e deve manter registro canônico, projeções e equivalência com o PostgreSQL.
