# Experimentos comparativos: metodologia e resultados (Task 04)

Todos os números deste documento vêm dos arquivos em `benchmarks/results/`. A execução principal citada é `20261115T053008Z-main` (E1–E5). O E6 vem das execuções corrigidas `20261115T202129Z-writes` e `20261115T202202Z-durability` (ver [E6](#e6-escritas-crud-concorrentes)). A execução `20261115T052908Z-n1` é a variante do N+1. As execuções anteriores (`…052604Z-main`, `…052947Z-durability`, `…202031Z-writes`) ficam preservadas como réplica e como registro das correções do protocolo de escrita. Para reproduzir, veja [Reproduzir](#reproduzir).

## Pergunta e hipóteses

O mesmo conjunto lógico de **1 000 000 de eventos de segurança**, mais a amostra de 24, está carregado nos dois bancos e passou pela validação integral da Task 03. A pergunta é: **em quais consultas reais do SOC cada paradigma é mais rápido, e por qual característica técnica?**

- **H1 (relacional):** buscas por chave e páginas ordenadas por índice favorecem o PostgreSQL. Uma consulta indexada devolve linhas completas. No Cassandra, a modelagem escolhida faz uma leitura canônica por resultado.
- **H2 (wide-column):** o painel agregado favorece o Cassandra. A modelagem orientada a consultas permite pré-agregar no momento da escrita, de forma incremental e barata, e a leitura toca poucas partições pequenas. O PostgreSQL normalizado agrega na leitura.
- **H3 (escrita):** sob concorrência, a diferença de escrita depende sobretudo da política de durabilidade, e não apenas do modelo.

## Ambiente medido

| Item | Valor (capturado em `environment.json`) |
| --- | --- |
| Host | Windows 11 Home 10.0.26200, Intel Core Ultra 7 155H, 22 CPUs lógicas, 15,4 GiB de RAM; 1,2–1,6 GiB livres durante os testes |
| Docker | Docker Engine 29.4.3 (Docker Desktop), VM WSL 2 com 22 vCPU / 7,44 GiB |
| PostgreSQL | 17.11; `mem_limit` 2 GiB; `shared_buffers` 512MB; `work_mem` 4MB; `effective_cache_size` 4GB; `synchronous_commit` on; `max_parallel_workers_per_gather` 2; `jit` on |
| Cassandra | 5.0.9, 1 nó, RF=1; `mem_limit` 5 GiB, heap 2 GiB; `commitlog_sync` periodic (10 s); `concurrent_reads/writes` 32; key cache 100 MiB; row cache 0; STCS em todas as tabelas |
| API | Rust/Axum em build **release**, contêiner na mesma rede Compose; pool PostgreSQL de 5 conexões nas leituras (sequenciais, usam 1) e de 16 nas execuções E6 corrigidas; sessão Cassandra única com prepared statements |
| Cliente | Python 3.13.6, conexão HTTP/1.1 keep-alive, sequencial (exceto E6) |
| Massa | `events` (PG) com 1 000 024 linhas; Cassandra com 1 000 024 eventos ativos e rollup com 9 978 células |

A configuração dos bancos não foi alterada para os experimentos, com uma exceção documentada: a variante de durabilidade do E6, feita por variável de sessão da API (`synchronous_commit=off`). Antes das medições, o PostgreSQL recebeu manutenção; o Cassandra não recebeu nenhuma (nem compactação maior). No PostgreSQL rodou `VACUUM (ANALYZE)`, rotina recomendada após carga em massa: 52 mil inserções posteriores ao último autovacuum ainda não estavam marcadas como visíveis e forçavam 12 945 *heap fetches* no *index-only scan*. Nenhum índice foi removido ou degradado.

### Índices e modelagem envolvidos

| Consulta | PostgreSQL | Cassandra |
| --- | --- | --- |
| READ por ID | PK `events_pkey (event_id)` | `events_by_id` (partição = UUID) |
| Q1 dispositivo | `events_device_time_idx (device_id, occurred_at DESC, event_id DESC)` | `events_by_device_day` + leitura canônica |
| Q2 IP | `events_ip_time_idx (source_ip, occurred_at DESC, event_id DESC)` | `events_by_ip_day` + leitura canônica |
| Q3 alertas | `events_alert_severity_time_idx (severity, occurred_at DESC, event_id DESC) WHERE category='alert'` | `alerts_by_severity_day` + leitura canônica |
| Painel agregado | **novo** `events_time_cover_idx (occurred_at) INCLUDE (category, severity)` (índice de cobertura, *index-only scan*) | **nova** `event_counts_by_day ((event_date), hour, category, severity)` com contador |

O SQL do painel foi otimizado antes da medição. Três expressões de agrupamento foram testadas no PostgreSQL com `EXPLAIN ANALYZE` sobre 7 dias:

| Expressão | Tempo |
| --- | --- |
| `date_trunc(..., 'UTC')` | 226 ms |
| `date_trunc` com TimeZone UTC | 147 ms |
| `date_bin('1 hour', ...)` | 122 ms |

Forçar paralelismo deu 194 ms. A API usa `date_bin`, a variante mais rápida.

## Protocolo

- **Mesma requisição** HTTP à mesma API, com os mesmos parâmetros. Só muda `{source}` no caminho.
- **5 aquecimentos + 30 medições** por operação e banco (o mínimo exigido é 10). Os aquecimentos ficam registrados (`phase=warmup`) e são excluídos das estatísticas. A primeira observação de cada consulta aparece separada como "1ª observação".
- **Pares intercalados com ordem alternada** (PG→CS, CS→PG, …). Assim, deriva térmica, compactação e autovacuum afetam os dois lados igualmente. A comparação "pares vencidos" usa esses pares.
- **Cache quente.** A massa cabe no cache dos dois bancos e no *page cache* da VM. Não houve teste de cache frio, porque esvaziar o cache do SO da VM exigiria privilégios e um procedimento destrutivo para o ambiente.
- **Duas fronteiras de medição por requisição:**
  - `http_ms`: medido no cliente com `perf_counter`. Inclui HTTP, serialização JSON e a API.
  - `db_ms`: tempo do adaptador de armazenamento, devolvido no cabeçalho `Server-Timing: db;dur=…` e medido com relógio monotônico dentro da API. Inclui driver, rede até o contêiner, banco e decodificação das linhas, e exclui HTTP e serialização.
  - O controle E5 usa uma terceira fronteira: o `\timing` do `psql`.
- **Equivalência:** o corpo de cada resposta passa por hash após JSON canônico. Uma operação só é válida quando todos os pares devolvem o mesmo hash nos dois bancos. Esse critério foi atendido em 9/9 operações.
- **Estatística:** mediana como valor principal, com p25–p75, p95, mínimo/máximo, média e desvio. Uma diferença conta como robusta quando os intervalos interquartis não se sobrepõem. Isso ocorreu em todas as operações.

## Resultados: leituras (E1–E3) e painel (E4)

Mediana HTTP em ms, com p25–p75 entre colchetes. "Banco" é a mediana de `db_ms`. Todas as 9 operações retornaram resultado idêntico nos dois bancos.

| Exp. | Operação | PostgreSQL | Cassandra | Banco PG / CS | Mais rápido | Pares |
| --- | --- | --- | --- | --- | --- | --- |
| E1 | READ por UUID (30 IDs distintos) | 1,19 [1,11–1,29] | 1,41 [1,34–1,53] | 0,35 / 0,61 | PG 1,2× | 30/30 |
| E2 | Q1 dispositivo quente, 1ª página (100) | 3,91 [3,56–4,13] | 7,33 [6,90–7,84] | 1,69 / 4,99 | PG 1,9× | 30/30 |
| E2 | Q1 10 páginas por cursor (1 000 eventos) | 34,2 [32,7–36,1] | 85,6 [82,6–90,2] | 15,1 / 60,6 | PG 2,5× | 30/30 |
| E2 | Q1 dispositivo pouco ativo, 7 dias (54) | 2,70 [2,54–2,91] | 10,8 [10,5–11,2] | 1,10 / 8,92 | PG 4,0× | 30/30 |
| E3 | Q2 IP de campanha, 1ª página (100) | 3,73 [3,35–4,21] | 9,91 [9,41–10,35] | 1,66 / 7,49 | PG 2,7× | 30/30 |
| E3 | Q3 alertas severidade 3, 1ª página (100) | 3,59 [3,21–3,79] | 7,26 [7,10–7,64] | 1,53 / 5,10 | PG 2,0× | 30/30 |
| **E4** | **Painel 7 dias, todas as categorias (244 881 eventos)** | 71,9 [70,3–75,1] | **3,28** [2,80–3,56] | 70,2 / 1,79 | **CS 21,9×** | 30/30 |
| **E4** | **Painel 1 dia (48 193 eventos)** | 15,6 [15,1–16,2] | **2,19** [1,99–2,49] | 14,3 / 1,15 | **CS 7,1×** | 30/30 |
| **E4** | **Painel 7 dias, somente alertas (19 758)** | 45,5 [43,9–48,2] | **3,54** [3,01–3,85] | 43,5 / 1,80 | **CS 12,9×** | 30/30 |

**Réplica:** a execução `20261115T052604Z-main` reproduziu o vencedor de todas as operações, com razões entre 1,2× e 3,7× para o PostgreSQL nas leituras e de 5,8× a 18,5× para o Cassandra no painel. Os valores absolutos variam entre execuções. No painel de 7 dias, por exemplo, o PostgreSQL ficou em 53 ms em uma execução e 72 ms na outra. Por isso as conclusões usam razões e vencedores, não um valor absoluto isolado.

### Por que o PostgreSQL vence E1–E3

- O índice B-tree composto `(chave, occurred_at DESC, event_id DESC)` entrega as 100 linhas já ordenadas, com colunas completas, em **uma** consulta. O tempo no banco fica entre 1,1 e 1,7 ms.
- No Cassandra, as projeções guardam apenas chaves imutáveis. O conteúdo de cada resultado é lido do registro canônico `events_by_id`: 1 fatia de partição + até 101 leituras por página. Essa escolha da Task 02 evita copiar mensagem e metadados mutáveis em 3–4 tabelas e o risco de divergência entre elas. O custo aparece aqui. Q1 de dispositivo pouco ativo é o pior caso relativo: a janela de 7 dias consulta 7 partições diárias em sequência para obter só 54 eventos.
- Em um único nó com dados em memória, a vantagem de distribuição do Cassandra não entra em jogo.

### Por que o Cassandra vence E4: o cenário favorável ao wide-column

O painel pergunta: quantos eventos houve por hora, categoria e severidade em um período. Cada paradigma responde da sua forma idiomática:

- **PostgreSQL (normalizado):** agrega na leitura. Mesmo com índice de cobertura e *index-only scan*, precisa visitar uma entrada de índice por evento: cerca de 245 mil em 7 dias. O custo cresce linearmente com o volume do período (1 dia ≈ 14 ms, 7 dias ≈ 70 ms no banco).
- **Cassandra (orientado a consultas):** a tabela `event_counts_by_day` foi desenhada para essa pergunta. A partição é o dia e as células, hora × categoria × severidade, com no máximo 360 por dia. A API incrementa o contador na transição LWT `pending→active` e o decrementa em `deleting→deleted`. A leitura de 7 dias são 7 leituras de partição concorrentes (≈ 1,8 ms no banco), **independentes do número de eventos**.

**O que o 21,9× mede.** As duas consultas não fazem o mesmo trabalho: o Cassandra lê cerca de 2,5 mil contadores já somados; o PostgreSQL agrega cerca de 245 mil entradas de índice. O resultado quantifica o benefício da **pré-agregação na escrita**, não uma velocidade bruta maior do motor. Ele é atribuível ao paradigma na medida em que, no wide-column, modelar a resposta pronta é o padrão (orientação a consultas, sem agregação *ad hoc*), e a manutenção é barata: o contador é uma escrita no LSM, sem *lock* de linha, cujo custo aparece no CREATE do E6. Não houve concorrente mal configurado: o PostgreSQL manteve todos os seus índices, recebeu um índice novo adequado, teve as estatísticas atualizadas e usou a consulta mais rápida entre as testadas. O E5 abaixo mostra o que acontece quando o PostgreSQL também pré-agrega.

### E5: controle, e se o PostgreSQL também pré-agregasse?

Para não comparar maçãs com laranjas, uma view materializada com as mesmas células horárias foi medida no PostgreSQL (`benchmarks/sql/pg_rollup_control.sql`, schema `bench`, fora da aplicação). Medida com `psql \timing`, 30 leituras e 10 REFRESH:

| Medida (painel 7 dias) | Mediana | p95 |
| --- | --- | --- |
| PG agregação na leitura (mesma SQL da API) | 73,7 ms | 88,9 ms |
| PG leitura da view materializada | **1,15 ms** | 1,32 ms |
| PG `REFRESH MATERIALIZED VIEW` completo (1 M eventos) | 282 ms | 309 ms |
| Cassandra leitura do rollup (`db_ms`) | 1,79 ms | — |

**Leitura honesta:** pré-agregado, o PostgreSQL lê o painel na mesma ordem de grandeza do Cassandra (1,15 ms × 1,79 ms; as fronteiras são diferentes, `psql` sem driver × driver na API, então os valores não são diretamente comparáveis). A diferença está no custo e na atualidade da agregação:

- A view só reflete os dados do último REFRESH completo, que recalcula tudo e custa proporcionalmente à tabela inteira.
- Uma tabela-resumo mantida por gatilho seria incremental, mas concentraria escritas concorrentes na mesma linha "hora corrente", o que tende a serializar commits por *lock* de linha. **Hipótese não medida neste projeto.**
- No Cassandra, o rollup é incremental por natureza. Em compensação, os contadores **não são idempotentes**: uma falha entre a ativação e o incremento produz desvio. O desvio é detectado e corrigido por `reconcile_rollup.py` (ver [consistency.md](consistency.md)).

A conclusão para o E4: a vantagem do Cassandra é real e reproduzível **para a modelagem idiomática de cada paradigma** (rollup incremental × agregação na leitura). Não é uma impossibilidade do PostgreSQL, que com view materializada lê na mesma ordem de grandeza, ao preço de recalcular tudo a cada REFRESH e de servir dados desatualizados entre REFRESHes.

## Otimização do N+1 no Cassandra (antes e depois)

O adaptador lia `events_by_id` **sequencialmente** para cada candidato. A versão final faz as leituras canônicas com concorrência limitada (`CASSANDRA_READ_CONCURRENCY`, padrão 32) usando `futures::stream::buffered`. Esse mecanismo preserva a ordem dos candidatos, o filtro, o limite de varredura de 1 000 e o cursor. Com `CASSANDRA_READ_CONCURRENCY=1`, a API reproduz exatamente o comportamento antigo, que é a execução `n1`.

| Operação (Cassandra, HTTP) | Antes (sequencial) | Depois (concorrência 32) | Ganho |
| --- | --- | --- | --- |
| Q1 dispositivo quente, 1ª página | 39,3 ms | 7,33 ms | 5,4× |
| Q1 10 páginas (1 000 eventos) | 417 ms | 85,6 ms | 4,9× |
| Q1 dispositivo pouco ativo | 26,3 ms | 10,8 ms | 2,4× |
| Q2 IP de campanha | 42,1 ms | 9,91 ms | 4,2× |
| Q3 alertas | 43,0 ms | 7,26 ms | 5,9× |

Os resultados continuaram idênticos aos do PostgreSQL. O ganho, porém, não inverte E1–E3: a leitura por resultado continua existindo. Próximos passos possíveis, ainda não implementados:

- **Desnormalizar o conteúdo nas projeções.** O UPDATE passaria a escrever 3–4 linhas (amplificação de escrita) e exigiria uma estratégia de convergência.
- **Buscar em paralelo as partições diárias** de janelas esparsas.

## E6: escritas CRUD concorrentes

São 8 clientes concorrentes, 2 rodadas de aquecimento descartadas e 10 rodadas medidas × 100 eventos novos por banco, na janela reservada 07–14/01/2002. Cada evento passa por CREATE, depois UPDATE e depois DELETE pela API, com ordem dos bancos alternada por rodada. Ao final, o painel da janela volta a 0 nos dois bancos (`window_total_after_cleanup`), o que prova que os contadores acompanharam os ciclos de vida. O pool PostgreSQL da API tem 16 conexões, mais que os 8 clientes.

| Configuração | Operação | PG mediana [p25–p75] | PG ops/s | CS mediana [p25–p75] | CS ops/s |
| --- | --- | --- | --- | --- | --- |
| Padrão: PG `synchronous_commit=on` (fsync do WAL por commit) × CS commitlog periódico (fsync a cada 10 s) | CREATE | 13,2 [11,7–15,8] ms | 516 | **10,8** [9,5–12,7] ms | **641** |
| | UPDATE | 12,1 [10,9–14,1] ms | 587 | **5,76** [4,94–6,84] ms | **1 220** |
| | DELETE | 9,87 [8,34–11,7] ms | 739 | **8,61** [7,78–9,95] ms | **800** |
| Ambos confirmam antes do fsync: PG `synchronous_commit=off` | CREATE | **5,83** [5,11–7,04] ms | **1 174** | 9,47 [8,74–10,6] ms | 750 |
| | UPDATE | **4,81** [4,18–5,62] ms | **1 425** | 5,14 [4,50–6,08] ms | 1 298 |
| | DELETE | **3,47** [3,21–3,88] ms | **1 852** | 7,55 [7,12–8,12] ms | 932 |

Execuções `20261115T202129Z-writes` e `20261115T202202Z-durability`.

**Interpretação:**

- Na configuração padrão, o Cassandra escreve mais rápido. Porém o PostgreSQL só confirma depois do `fsync` do WAL, enquanto o Cassandra confirma antes do `fsync` periódico do commitlog. As garantias de durabilidade são diferentes.
- Quando os dois confirmam antes do `fsync`, o PostgreSQL vence as três operações (de 1,1× a 2,2×). As janelas de perda em uma queda do nó **não são iguais**: no PostgreSQL, até cerca de 3 × `wal_writer_delay` (≈ 0,6 s); no Cassandra, até o período do commitlog (≈ 10 s). Nenhum dos dois corrompe dados. A variante compara a mesma política de confirmação, não durabilidades idênticas.
- A vantagem padrão do Cassandra é, portanto, explicada pela política de durabilidade e não pelo modelo de dados. O CREATE Cassandra paga 2 LWT (Paxos), um *logged batch* de 2–3 projeções, 2 leituras e o incremento do contador do rollup (o custo de escrita do E4). Esses custos garantem a unicidade de UUID e o ciclo de vida, que o PostgreSQL obtém com PK e transação.
- Um caminho de ingestão sem LWT seria mais rápido, mas trocaria a garantia contra reutilização de UUID. Isso não foi feito.
- Em cluster, a durabilidade do Cassandra viria da replicação (RF ≥ 3), que um único nó não demonstra.

**Correções do protocolo de escrita (auditoria final).** As primeiras execuções do E6 (`…052604Z-main`, `…053008Z-main`, `…052947Z-durability`) tinham dois problemas:

1. O pool PostgreSQL da API era de **5 conexões para 8 clientes**, e as requisições excedentes esperavam conexão, enquanto o driver Cassandra multiplexa.
2. **Não havia aquecimento.**

Correções: o pool passou a ser configurável (`POSTGRES_POOL_SIZE`, padrão 16), o executor recusa rodar o E6 com pool menor que o número de clientes, e foram acrescentadas 2 rodadas de aquecimento. A execução `…202031Z-writes`, sem aquecimento e com o Cassandra recém-reiniciado, mostrou o efeito: CREATE do Cassandra caindo de 28,9 ms para 11,7 ms ao longo das rodadas, com o JIT da JVM aquecendo. Com o protocolo corrigido, a conclusão anterior se manteve; o pool de 5 conexões não era o fator dominante (PostgreSQL CREATE 12,4 ms com pool 5 × 13,2 ms com pool 16). Os valores absolutos mudaram, e as tabelas acima substituem as anteriores. Mesmo depois das 2 rodadas de aquecimento, as latências do Cassandra ainda caíram um pouco ao longo das rodadas medidas, o que favorece o PostgreSQL nessa comparação.

## Limitações e ameaças à validade

- **Um nó Cassandra.** Não mede escalabilidade horizontal, replicação, *quorum* real nem tolerância a falhas, que são as principais vantagens do paradigma em produção.
- **Recursos assimétricos e compartilhados:** 5 GiB para o Cassandra e 2 GiB para o PostgreSQL, sem limite de CPU, com os dois bancos ativos ao mesmo tempo e a API e o cliente na mesma máquina. Mesmo assim, a massa cabe em memória nos dois.
- **Somente cache quente.** Não há medição de cache frio nem de I/O de disco dominante.
- **Variação entre execuções:** valores absolutos variam de 10% a 35% entre execuções. Vencedores e ordens de grandeza se repetiram.
- **Fronteiras de medição diferentes.** `db_ms` inclui o driver de cada banco (SQLx × Scylla Rust Driver). O E5 usa `psql`, que não passa pela API.
- **Recorte da massa.** É sintética, e apenas uma janela de 7 dias foi usada no painel. Janelas maiores aumentariam o custo do PostgreSQL de forma linear e o do Cassandra só pelo número de dias.
- **Cliente sequencial** nas leituras. Não houve teste de throughput de leitura sob concorrência.
- **Aquecimento da JVM.** O Cassandra recém-reiniciado leva várias centenas de operações para estabilizar. As leituras usam 5 aquecimentos por operação; o E6, 2 rodadas.
- **Hipóteses não medidas:** contenção de uma tabela-resumo do PostgreSQL mantida por gatilho e `REFRESH MATERIALIZED VIEW CONCURRENTLY`.

## Reproduzir

Os experimentos não alteram a massa. As escritas usam UUIDs novos em janela reservada e são excluídas ao final.

```powershell
python scripts/run_api.py build                     # build release (contêiner Rust)
python scripts/run_api.py start
python benchmarks/run_benchmarks.py --suite main    # E1-E6, ~2 min
python scripts/run_api.py stop
python scripts/run_api.py start --read-concurrency 1
python benchmarks/run_benchmarks.py --suite n1      # "antes" do N+1
python scripts/run_api.py stop
python scripts/run_api.py start                     # pool PostgreSQL padrão 16 (>= 8 clientes)
python benchmarks/run_benchmarks.py --suite writes  # E6 com durabilidade padrão
python scripts/run_api.py stop
python scripts/run_api.py start --pg-synchronous-commit off
python benchmarks/run_benchmarks.py --suite durability
python scripts/run_api.py stop
python scripts/run_api.py start                     # volta à configuração padrão
```

Cada execução cria `benchmarks/results/<UTC>-<suite>/` com:

- `raw.csv`: uma linha por requisição, inclusive aquecimentos.
- `raw_writes.csv`: latência individual das escritas.
- `environment.json`: hardware, versões, configurações, índices e tamanhos.
- `run.json`: estatísticas por operação.

`summary.json` aponta para a última execução completa de cada suíte e é lido pelo dashboard em `/api/benchmarks/summary`.
