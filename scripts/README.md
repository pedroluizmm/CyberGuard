# Scripts

Requer Python 3.11+, apenas com a biblioteca padrão; `psutil` é opcional e só serve para registrar a RAM do host. Execute tudo a partir da raiz do repositório.

| Etapa | Comando |
| --- | --- |
| Ambiente | `python scripts/setup_env.py` (gera `.env` com senha aleatória, sem sobrescrever) |
| Esquemas | `python scripts/apply_schema.py` (todos os `database/*/NNN_*`, aditivos) |
| API | `python scripts/run_api.py build \| start \| stop \| status \| logs` (Rust em contêiner) |
| Amostra | `generation/generate_sample.py`, `loading/load_sample.py`, `validation/check_sample.py` |
| Massa 1 M | `generation/generate_bulk.py --count 1000000`, `loading/load_bulk.py --source <banco> --target 1000000`, `validation/check_bulk.py --target 1000000` |
| Rollup do painel | `loading/reconcile_rollup.py` (simulação) / `--apply` (backfill ou correção) |
| Testes | `validation/check_foundation.py`, `validation/check_api.py`, `validation/test_integration.py`, `validation/test_recovery.py`, `validation/test_bulk_generator.py` |
| Benchmarks | `benchmarks/run_benchmarks.py` (ver `benchmarks/README.md`) |

`generation/`, `loading/` e `validation/` separam geração, carga e validação. Nenhum script mantém milhões de eventos em RAM ou grava a massa em arquivo. A massa é regenerada em streaming a partir da seed e do manifesto. Os scripts que usam Docker aceitam `--docker-config <dir>`. Nenhum script executa DROP, TRUNCATE ou remoção de volumes.


## Refer?ncia consolidada

### generation

# Geração determinística

`generate_sample.py` produz exatamente 24 eventos sintéticos estáveis e manifesto com SHA-256. Datas, conteúdo e IDs são fixados pela versão do dataset; arquivos existentes diferentes são preservados e causam erro. Não depende do relógio atual ou de bibliotecas externas.

`bulk_events.py` é o gerador volumoso (Task 03): `BulkGenerator(seed).event(i)` é função pura de dataset, seed e índice, baseada apenas em SHA-256 e pesos inteiros. Perfis crescentes são prefixos `[0, N)` do mesmo conjunto lógico. Os eventos são produzidos em streaming, nunca gravados em massa.

`generate_bulk.py --count 1000000` calcula o manifesto versionável `data/bulk/cyberguard-bulk-v1.manifest.json` (seed, algoritmos, hashes por chunk e por perfil, contagens e distribuição de partições) e recusa sobrescrever um manifesto diferente. Repetir o comando reproduz o arquivo byte a byte. Limite: 5 000 000 eventos; nada é gerado automaticamente. Ver `docs/bulk-load.md`.

### loading

# Carregamento equivalente

`load_sample.py` envia a amostra de 24 eventos para cada fonte via CRUD real. `--source both` é padrão; `postgresql`/`cassandra` permitem execução separada. Repetição idêntica é idempotente; conflitos e erros interrompem a carga, sem sobrescrever conteúdo nem gerar novos UUIDs como retry. É restrito a amostras de até 1000 eventos.

`load_bulk.py --source <postgresql|cassandra> --target N` carrega os índices `[0, N)` do dataset `cyberguard-bulk-v1` pela API real (mesma validação, transação PostgreSQL e fluxo LWT/batch Cassandra). Regenera cada chunk de 1000, confere o SHA-256 do manifesto, usa 16 workers keep-alive, retry limitado com o mesmo UUID e checkpoint atômico por chunk em `data/generated/cyberguard-bulk-v1/`. Repetir o comando retoma; `--ignore-checkpoint` testa idempotência; `--max-seconds` para em fronteira de chunk. Relatório pequeno em `data/bulk/reports/`.

`bulk_runtime.py`: cliente HTTP keep-alive, comandos Docker/psql/cqlsh sem expor credenciais, exportações `COPY ... TO STDOUT` em streaming, amostragem de `docker stats` e escrita atômica.

`reconcile_rollup.py` (Task 04) faz o backfill e a correção do rollup Cassandra do painel (`event_counts_by_day`):

1. Calcula a verdade a partir da exportação integral de `events_by_id`, contando os estados `active` e `deleting`.
2. Lê os contadores atuais e escreve apenas a diferença. Por isso é seguro repetir: uma segunda execução aplica 0.
3. Agrega o PostgreSQL de forma independente e compara célula a célula, o que serve também como prova de equivalência dos bancos.

Sem `--apply`, apenas simula. Rode com a API ociosa. O relatório vai para `data/bulk/reports/rollup-reconcile-*.json`.

Tempos de carga são carga inicial via API, não benchmark. Ver `docs/bulk-load.md`.

### validation

# Validação

`check_foundation.py`: integridade dos PDFs originais, exclusão de arquivos sensíveis pelo Git e preservação de amostras/manifestos versionáveis. Não depende de serviços externos.

`check_api.py`: verifica os contratos HTTP reais e CORS da API local. Exige API ativa; retorna falha se algum banco estiver indisponível. Não insere dados nem fabrica resultados.

Implementados na Task 02:

- `test_integration.py`: sete testes reais HTTP, cobrindo CREATE/READ/UPDATE/DELETE, retries, conflitos, três consultas, paginação, limites, dados inválidos, concorrência, health e repair. Só exclui UUIDs próprios com marcador de execução. Recusa alertas preexistentes na janela reservada de 06 a 09/11/2001.
- `test_recovery.py`: cria um UUID novo, injeta estados pending/deleting e uma projeção ausente; verifica recuperação por ID e conteúdo/visibilidade. Nunca toca IDs alheios.
- `check_sample.py`: exige a amostra carregada, compara 24 IDs/conteúdos e Q1/Q2/Q3 nas duas fontes, depois confere 81 linhas Cassandra por IDs e partições limitadas.

Implementados na Task 03 (massa volumosa, ver `docs/bulk-load.md`):

- `test_bulk_generator.py`: testes offline do gerador (contrato, determinismo, prefixos, disjunção da amostra, manifesto).
- `check_bulk.py --target N`: exige exatamente N eventos do dataset nos dois bancos. Compara exportações integrais (`COPY TO STDOUT`, em pipe) com o gerador por multiconjuntos com hash, verifica projeções, `3N + A`, duplicação, pendências, partições, READs amostrados e Q1–Q3 paginadas; registra tamanhos e planos em `data/bulk/reports/validate-N-*.json`. Só lê dados; executa `nodetool flush` (não destrutivo) salvo `--no-flush`.

Alterados na Task 04:

- `test_integration.py` agora tem dez testes. `test_08` verifica que o painel é byte a byte igual nas duas fontes para quatro combinações de filtro e que o rollup acompanha o CRUD: +1 na hora/categoria/severidade certa no CREATE, nenhuma contagem dupla no retry, retorno ao estado anterior no DELETE. `test_09` cobre a validação de janela e filtros do painel.
- `test_recovery.py` injeta o CREATE interrompido como uma queda real o deixaria: reserva `pending` sem projeções e ainda não contada. Antes, o teste reescrevia para `pending` um evento já ativo, estado impossível que contava o evento duas vezes no rollup.

Scripts com Docker aceitam `--docker-config tmp/docker`. Não há DROP, limpeza de tabelas ou remoção de volumes. Testes deixam reservas de IDs excluídos; isso é parte da semântica documentada. Resultados executados: `docs/verification/verification-task02.md` e `docs/verification/verification-task03.md`.
