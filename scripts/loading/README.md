# Carregamento equivalente

`load_sample.py` envia a amostra de 24 eventos para cada fonte via CRUD real. `--source both` é padrão; `postgresql`/`cassandra` permitem execução separada. Repetição idêntica é idempotente; conflitos e erros interrompem a carga, sem sobrescrever conteúdo nem gerar novos UUIDs como retry. É restrito a amostras de até 1000 eventos.

`load_bulk.py --source <postgresql|cassandra> --target N` carrega os índices `[0, N)` do dataset `cyberguard-bulk-v1` pela API real (mesma validação, transação PostgreSQL e fluxo LWT/batch Cassandra). Regenera cada chunk de 1000, confere o SHA-256 do manifesto, usa 16 workers keep-alive, retry limitado com o mesmo UUID e checkpoint atômico por chunk em `data/generated/cyberguard-bulk-v1/`. Repetir o comando retoma; `--ignore-checkpoint` testa idempotência; `--max-seconds` para em fronteira de chunk. Relatório pequeno em `data/bulk/reports/`.

`bulk_runtime.py`: cliente HTTP keep-alive, comandos Docker/psql sem expor credenciais, amostragem de `docker stats` e escrita atômica.

Tempos de carga são carga inicial via API, não benchmark. Ver `docs/bulk-load.md`.
