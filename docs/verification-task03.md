# Task 03 - Massa volumosa: verificação

Data: 09/11/2026 (UTC nos relatórios). Fluxo READ → PLAN → APPLY → VERIFY. Nenhum commit ou push. Metodologia em [bulk-load.md](bulk-load.md); relatórios JSON brutos em `data/bulk/reports/`.

## Ambiente medido

| Item | Valor observado |
| --- | --- |
| Host | Windows 11 Home 10.0.26200, Intel Core Ultra 7 155H, 15,4 GiB de RAM; 179 GB livres em C: |
| Docker | Docker Desktop, Engine 29.4.3, VM WSL 2 com 7,44 GiB e 22 vCPUs |
| Cassandra | 5.0.9, 1 nó, RF=1, `mem_limit` 5 GiB, heap 2 GiB (G1), `commitlog_sync: periodic` 10 s, `concurrent_writes: 32`; configuração da Task 01 sem alteração |
| PostgreSQL | 17.11, `mem_limit` 2 GiB, `shared_buffers=512MB`, `synchronous_commit=on`, `work_mem` 4MB, `max_wal_size` 1GB; sem alteração |
| API | binário **debug** da Task 02 em `rust:1.99.1-slim-bookworm`, mesma rede Compose; pool PostgreSQL de 5 conexões |
| Cliente | Python 3.13.6, biblioteca padrão + `psutil`; 16 workers keep-alive, 2 chunks em voo |

A RAM livre do host Windows era 0,87 GB no início e teve mínimo de 211 MiB durante a carga de 1 M (outros processos do Windows somados à VM). A VM Docker permaneceu estável.

## READ: riscos avaliados antes da carga

| Risco | Evidência | Decisão |
| --- | --- | --- |
| A. Cassandra N+1 | `query` lê `events_by_id` **sequencialmente** para cada candidato: até 101 SELECTs por página de 100 | Manter a modelagem nesta tarefa; medir o efeito funcional (abaixo) e tratar na Task 04 |
| B. Hot partitions | Distribuição exata calculada pelo manifesto antes da carga e depois medida | Sem bucket/shard: máximo de 11 822 linhas por partição em 1 M |
| C. Amplificação de escrita | CREATE Cassandra = 2 LWT + logged batch de 2–3 projeções + 2 leituras; PostgreSQL = 1 transação | Carga pela API para preservar o contrato; concorrência limitada; medir CPU |
| D. Recursos locais | VM com 7,44 GiB; limites de 5 + 2 GiB; host com pouca RAM livre | Etapas de 10 mil → 100 mil → 1 M com amostragem de recursos a cada 10 s; parar se houvesse falha persistente |

## APPLY

| Arquivo | Conteúdo |
| --- | --- |
| `scripts/generation/bulk_events.py` | Gerador determinístico (SHA-256 em modo contador e pesos inteiros), cenários e campanhas |
| `scripts/generation/generate_bulk.py` | Manifesto reproduzível + relatório de tempo |
| `data/bulk/cyberguard-bulk-v1.manifest.json` | Seed, algoritmos, mundo, 1000 hashes de chunk e estatísticas/partições de 10 mil/100 mil/1 M |
| `scripts/loading/bulk_runtime.py` | Cliente HTTP keep-alive, Docker/psql sem segredos, `docker stats`, escrita atômica |
| `scripts/loading/load_bulk.py` | Carga via API com checkpoint, retry/backoff, idempotência e registro de IDs incertos |
| `scripts/validation/check_bulk.py` | Validação integral (exportações em pipe), projeções, partições, API, Q1–Q3, tamanhos e planos |
| `scripts/validation/test_bulk_generator.py` | 5 testes offline do gerador |
| `scripts/validation/check_foundation.py` | Agora confere também que `data/bulk/` é versionável |
| Documentação | `docs/bulk-load.md` (novo), este relatório; README, arquitetura, modelo de dados, consistência e READMEs de scripts/data/ingestion atualizados |

Backend, esquemas SQL/CQL, Compose, frontend e configurações dos bancos **não foram alterados**.

## VERIFY

### Resumo por volume

| Volume | PostgreSQL | Cassandra | Integridade | Tempo real de carga |
| --- | --- | --- | --- | --- |
| 10 mil | 10 000 eventos do dataset (`events` = 10 024 com a amostra) | 10 000 ativos; 30 826 linhas vivas = 3N+A | 22/22 checks; controle negativo falhou como esperado; reenvio integral: 0 criados / 10 000 reutilizados por banco | PG 17,5 s (572 ev/s); Cassandra 17,3 s (577 ev/s) |
| 100 mil | 100 000 (+56 000 após interrupção: 55 591 criados, 409 reutilizados) | 100 000 ativos; 308 237 linhas vivas (+54 000: 53 305 criados, 695 reutilizados) | 22/22 checks após morte forçada do carregador e retomada nos dois bancos; 0 pendentes | PG 62,8 s* até o kill + 103,5 s na retomada; Cassandra 52,0 s* + 75,5 s |
| 1 milhão | **1 000 000** (+900 000 criados, 0 retries); `events` = 1 000 024 | **1 000 000** ativos; **3 082 443** linhas vivas = 3N+A | **22/22 checks**: conteúdo integral, IDs, projeções, partições, 500 READs, Q1–Q3; 0 pendentes/duplicados | PG 1 716,6 s (524 ev/s); Cassandra 1 516,4 s (594 ev/s) |

\* Execução morta à força: o tempo vem do log por chunk (do primeiro ao último chunk confirmado) e exclui o início e a cauda em voo. Tempo acumulado até 1 M, somando todas as execuções: PG ≈ 1 900 s (31,7 min); Cassandra ≈ 1 661 s (27,7 min). São tempos de **carga inicial via API**, não benchmark (ver [bulk-load.md](bulk-load.md)).

### Comandos executados

| Comando | Resultado real |
| --- | --- |
| `python scripts/generation/generate_bulk.py --count 1000000` (2×) | Manifesto escrito e depois reproduzido idêntico; 32,9 s e 33,0 s para gerar 1 M (CPU, sem I/O de banco); 82 443 alertas |
| `python scripts/validation/test_bulk_generator.py` | 5 testes OK |
| `load_bulk.py --source {postgresql,cassandra} --target 10000` | 10 000 criados por banco, 0 retries |
| `load_bulk.py ... --target 10000 --ignore-checkpoint` | 0 criados / 10 000 reutilizados por banco (idempotência) |
| `check_bulk.py --target 9000` com 10 mil carregados | **Falhou em 10 checks**, como esperado (controle negativo); relatório descartado |
| `check_bulk.py --target 10000` / `100000` / `1000000` | 22/22 em cada; 23,6 s / 37,6 s / 205,5 s |
| `load_bulk.py ... --target 100000`, processo morto à força (`Stop-Process -Force`) em 44 000 (PG) e 46 000 (Cassandra), depois retomado | Retomada sem duplicação; os eventos dos chunks interrompidos voltaram como `reused` |
| `load_bulk.py ... --target 1000000` | 900 000 criados por banco; 0 retries, 0 incertos |
| `check_sample.py --docker-config tmp/docker` | Amostra intacta: 24 IDs/conteúdos, Q1=15, Q2=12, Q3=6, 81 linhas Cassandra |
| `test_integration.py` (com 1 M carregado) | 7 testes OK; IDs próprios do ano 2001, excluídos pela API |
| `check_api.py`, `check_foundation.py` | Ambos up e CORS restrito; 38/38 checks de fundação |
| `python -m compileall -q scripts`, `docker compose config --quiet`, `git diff --check` | Passaram |

Não executados por falta de mudança no código correspondente: `cargo fmt/test/build` (backend inalterado), `npm run build` (frontend inalterado) e `test_recovery.py` (persistência inalterada; o estado pending continua coberto por ele na Task 02).

**Teste bloqueado:** matar o contêiner da API durante a carga Cassandra, para deixar reservas `pending` reais, foi negado pela política de permissões do ambiente e **não foi executado**. Por isso, a queda do escritor no meio do fluxo LWT/batch não foi demonstrada com volume. Ficou demonstrada a queda do cliente carregador; a recuperação de `pending` é coberta pela injeção controlada da Task 02. Com autorização, o procedimento é: `docker kill` da API com carga em andamento → o carregador registra incertos e para → reiniciar a API → repetir o comando de carga → `check_bulk.py` deve mostrar 0 `pending`.

### Contagens físicas em 1 M

| Banco / tabela | Linhas | Observação |
| --- | --- | --- |
| PostgreSQL `events` | 1 000 024 | 1 000 000 do dataset + 24 da amostra |
| PostgreSQL `event_registry` | 1 000 148 | inclui 124 UUIDs excluídos reservados pelos testes |
| PostgreSQL `devices` | 405 | 393 do dataset + identidades da amostra e dos testes |
| Cassandra `events_by_id` | 1 000 152 | 1 000 000 ativos do dataset, 24 da amostra, 128 marcadores `deleted` |
| Cassandra `events_by_device_day` / `events_by_ip_day` | 1 000 024 cada | 1 000 000 na janela do dataset + 24 da amostra |
| Cassandra `alerts_by_severity_day` | 82 452 | 82 443 + 9 da amostra |

### Armazenamento em 1 M (após `nodetool flush`)

| Item | Bytes medidos |
| --- | --- |
| Cassandra `events_by_id` (live, LZ4 0,366) | 260,5 MB |
| Cassandra `events_by_device_day` / `events_by_ip_day` / `alerts_by_severity_day` | 29,5 MB / 36,6 MB / 2,4 MB |
| Cassandra keyspace `cyberguard` (`du`) | 329,1 MB |
| Cassandra `system.paxos` (estado das LWT) | 97,7 MB (1 005 508 partições) |
| Cassandra commitlog (segmentos alocados) | 671,1 MB |
| PostgreSQL `events` total | 651,7 MB = heap 460,9 MB + índices 190,6 MB (PK 39,7; device 74,7; IP 70,9; alertas parcial 5,3) |
| PostgreSQL `event_registry` | 91,9 MB |
| PostgreSQL banco inteiro | 751,7 MB |

Tamanhos dependem de compressão, fillfactor, ordem de inserção (UUID v4 aleatório no PostgreSQL) e compactação; não são comparação de eficiência.

### Partições Cassandra em 1 M (exportação integral = manifesto)

| Projeção | Partições | p50 | p99 | Máximo (linhas) | Maior partição (histograma) |
| --- | --- | --- | --- | --- | --- |
| `events_by_device_day` | 10 811 | 9 | 1 867 | 11 822 (`ids-sensor-06`, 27/10) | ≤ 454 826 B |
| `events_by_ip_day` | 183 130 | 2 | 63 | 11 517 (`2001:db8:bad:4::6`, 27/10) | ≤ 454 826 B |
| `alerts_by_severity_day` | 140 | 576 | 1 268 | 1 320 (severidade 3, 14/10) | ≤ 42 510 B |

O Risco B não se materializou nesta distribuição: a maior partição tem ~0,43 MiB, contra um limiar de revisão de 50 MiB/100 mil chaves.

### Recursos durante as cargas (`docker stats` a cada 10 s; 100% = 1 vCPU)

| Carga | API CPU média/máx | PostgreSQL CPU média / memória máx | Cassandra CPU média/máx / memória máx | RAM livre mínima do host |
| --- | --- | --- | --- | --- |
| PG 10 mil | 145% / 148% | 97% / 67 MiB | 2% / 2,9 GiB (ociosa) | 1 123 MiB |
| Cassandra 10 mil | 296% / 351% | 0% | 955% / 1 309% / 3,0 GiB | 680 MiB |
| PG 1 M (900 mil novos) | 162% / 187% | 75% / 648 MiB | 5% / 3,1 GiB (ociosa) | 228 MiB |
| Cassandra 1 M (900 mil novos) | 361% / 398% | 3% | 633% / 912% / 3,19 GiB de 5 GiB | 211 MiB |

Para ritmos de ingestão semelhantes (~520–600 ev/s), o fluxo Cassandra consumiu de 6 a 10 vCPUs, contra ~1 vCPU no PostgreSQL. Os contadores locais confirmam a amplificação: `events_by_id` com 2 000 576 escritas e 4 073 691 leituras locais, `system.paxos` com 6 023 174 escritas e `system.batches` com 2 000 601 escritas para 1 M de CREATEs. Não houve WARN/ERROR no log do Cassandra durante as cargas, nem retries ou respostas incertas. Heap observado em 100 mil: 1,08/2 GiB.

### Q1–Q3 em 1 M (via API, `page_size=100`, uma execução cada, caches quentes)

| Filtro | Janela | Itens esperados | Comparados | PG | Cassandra |
| --- | --- | --- | --- | --- | --- |
| Q1 `ids-sensor-06` | 24–31/10 | 13 478 | 10 000 (limite de 100 páginas) | 1,56 s | 8,16 s |
| Q1 `ws-hr-0050` | 12–19/10 | 54 | 54 | 0,015 s | 0,049 s |
| Q2 `2001:db8:bad:4::6` | 24–31/10 | 11 522 | 10 000 (limite) | 1,00 s | 7,89 s |
| Q2 `203.0.113.173` | 08/10 | 8 816 | 8 816 | 1,43 s | 6,59 s |
| Q3 severidade 3 | 13–15/10 | 2 476 | 2 476 | 0,38 s | 1,89 s |
| Q3 severidade 5 | 17–24/10 | 1 494 | 1 494 | 0,23 s | 1,16 s |

Os resultados foram idênticos entre os bancos e iguais ao esperado em todas as páginas comparadas. O PostgreSQL usou *Index Only Scan* nos três índices previstos (execução da primeira página entre 0,17 e 0,36 ms no `EXPLAIN ANALYZE`). As durações são observações funcionais únicas, com API debug e cliente Python, **não benchmark**. Ainda assim, mostram o efeito do Risco A: 74–82 ms por página de 100 no Cassandra, coerente com 101 leituras canônicas sequenciais, contra ~10–16 ms no PostgreSQL.

### Preservação

| Volume | CreatedAt antes e depois |
| --- | --- |
| `cyberguard_cassandra_data` | `2026-11-09T05:06:41Z` |
| `cyberguard_postgresql_data` | `2026-11-09T05:06:41Z` |

Não foram executados DROP, TRUNCATE, remoção de volumes, recriação ou reinício de serviços. PDFs e `.env` não foram tocados nem exibidos. Os DELETEs vieram apenas dos testes de integração, sobre IDs próprios.

## RISKS

- **N+1 Cassandra (A):** cada página faz até 101 leituras canônicas sequenciais. Em partições densas, a paginação ficou 4,6–7,9× mais lenta que a do PostgreSQL nesta observação única. Leituras canônicas concorrentes limitadas, ou a desnormalização de campos imutáveis nas projeções, são opções para avaliar e medir na Task 04, com ganhos e custos registrados.
- **Amplificação de escrita (C):** 2 LWT por CREATE dominam a CPU do Cassandra (6–10 vCPUs) e geram ~98 MB de `system.paxos` em 1 M. Um caminho de bulk loading sem LWT exigiria outra garantia de unicidade/estado, e por isso não foi adotado.
- **Durabilidade assimétrica:** commitlog periódico (10 s) com RF=1 no Cassandra contra fsync por commit no PostgreSQL. Os tempos de carga não são comparáveis como desempenho.
- **Recursos locais (D):** a RAM livre do host chegou a 211 MiB. 5 M (recomendação condicional) exigiria liberar memória do host, estimar ~5× o disco (~6–7 GB nos dois bancos, sem contar o commitlog) e ~2,5 h por banco nesta taxa. Isso não foi tentado.
- Um único nó Cassandra não demonstra tolerância a falhas nem escalabilidade horizontal. A API debug adiciona CPU (até ~4 vCPUs na carga Cassandra).
- A queda do escritor (API) no meio do fluxo Cassandra não foi testada com volume: ação bloqueada por permissão.
- A paginação de Q1/Q2 quentes foi comparada até 10 000 itens (limite configurável `--max-pages`); os demais filtros foram comparados por completo. O conteúdo de todos os eventos foi comparado pelas exportações integrais.

## NEXT - Task 04

- Massa de 1 M já carregada e verificada nos dois bancos, com manifesto/seed reproduzíveis e validador rápido (~3,5 min).
- Os filtros quentes/frios de Q1–Q3 e as janelas do relatório servem de ponto de partida para cenários de benchmark.
- Protocolo pendente: build **release** da API, ≥10 execuções por operação, aquecimento/cache declarados (frio após reinício vs. quente), coleta de versões e recursos, e medição separada de banco (driver) e de API (HTTP).
- Avaliar, medindo antes e depois, a mitigação do N+1 Cassandra sem alterar a semântica, e documentar o custo de LWT/batch no fluxo de escrita. Não remover índices PostgreSQL nem relaxar durabilidade para favorecer um dos lados.
