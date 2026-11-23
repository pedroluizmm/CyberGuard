# Experimentos comparativos: metodologia e resultados (Task 04)

> **Duas campanhas, sem mistura de números.** As seções abaixo descrevem a campanha **histórica** de 1 M (15/11, Task 04), preservada sem alteração. A **campanha de escala** (23/11, Task 06) mediu 1 M de novo e depois volumes maiores com o mesmo código e o mesmo protocolo (mais um pré-aquecimento): veja [Campanha de escala](#campanha-de-escala-1-m--massa-ampliada). Os valores absolutos de 1 M diferem entre as duas campanhas porque o estado do host mudou (por exemplo, notebook na bateria em 23/11); compare volumes **dentro** da mesma campanha.

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

## Campanha de escala: 1 M × massa ampliada

**Pergunta (23/11):** como a comparação acima muda quando a massa cresce, sem mudar mais nada?

### Desenho

- **Mesma máquina e mesma configuração** em todos os volumes: limites de 5 GiB (Cassandra) e 2 GiB (PostgreSQL), as mesmas imagens, o mesmo binário release da API (pool 16, concorrência de leitura 32) e o mesmo código do executor. A configuração dos bancos **não** foi ajustada ao volume, para isolar o efeito da massa.
- **Baseline de 1 M medido antes de qualquer ampliação** (`20261123T193439Z-main` e `20261123T193718Z-durability`). Depois que a massa cresce, uma consulta restrita aos eventos antigos **não** substitui esse baseline.
- **Mesmos parâmetros:** os mesmos dispositivos, IPs, severidades e janelas fixas do histórico. No E1, os UUIDs são amostrados de todo o prefixo carregado `[0, N)` pela mesma fórmula (em 1 M, a lista é exatamente a do histórico).
- **Mesmo protocolo:** 5 aquecimentos + 30 medições por operação e banco, pares intercalados com ordem alternada, resposta idêntica exigida, mais **30 passadas de pré-aquecimento** descartadas (ver abaixo). Antes de cada volume: `check_bulk.py`, `reconcile_rollup.py`, `VACUUM (ANALYZE)` e 0 compactações pendentes no Cassandra (sem compactação forçada). Tudo isso é a sequência de `benchmarks/run_scale_point.py`.
- **O E6 da campanha** roda dentro da suíte `main` (pool 16 ≥ 8 clientes, 2 rodadas de aquecimento) e, com a API reiniciada com `synchronous_commit=off`, na suíte `durability`.

**Controles gravados em cada execução**, para que a variação possa ser atribuída:

| Controle | Para quê |
| --- | --- |
| Volume medido nos dois bancos (soma dos painéis semanais) | O executor recusa medir se os totais forem diferentes |
| Eventos cobertos por consulta (`workload`, contagem no PostgreSQL) | Mostra que os eventos novos entram no trabalho medido: o painel de 7 dias cobre 244 881 eventos em 1 M |
| Acertos de cache e bytes lidos do disco na fase de leitura | Separa efeito de volume de efeito de cache (PG `shared_buffers`, *key cache* do Cassandra, `BlockIO` dos contêineres) |
| Compactações pendentes, energia do notebook, RAM do host | Condições do host que mudam valores absolutos |

**Três tipos de operação:**

1. **Período fixo e resposta de tamanho controlado:** E1 (1 evento por chave) e as páginas de E2/E3 (100 ou 1 000 eventos). O intervalo indexado cresce; a resposta, não.
2. **Trabalho que cresce com a massa:** o painel E4 no PostgreSQL agrega todos os eventos do período; o E5 "agregação na leitura" e o REFRESH da view crescem com a tabela; o "Q1 dispositivo pouco ativo" devolve mais eventos (54 em 1 M) até o limite de 100 por página.
3. **Pré-agregação que evita o crescimento na leitura:** o rollup do Cassandra (E4) lê no máximo 7 × 360 células; a view materializada do E5 lê as mesmas células horárias.

### Mudança de protocolo: pré-aquecimento

A primeira execução de 1 M (`20261123T193215Z-main`, preservada como **piloto**) rodou 12 minutos depois de o Docker ser reiniciado. Dentro dela, o painel de 7 dias no Cassandra caiu de 10,8 ms (mediana do 1º terço) para 8,4 ms (último terço): a JVM ainda aquecia. Medir 1 M com a JVM fria e os volumes maiores com a JVM aquecida por horas de carga favoreceria artificialmente o Cassandra na comparação. Por isso, **todas** as execuções oficiais da campanha fazem 30 passadas completas de pré-aquecimento antes dos 5 aquecimentos, gravadas em `raw.csv` como `phase=prewarm` e excluídas das estatísticas. No E1, essas passadas usam UUIDs que nunca são medidos. O `summary.json` ignora execuções `main` de campanha sem pré-aquecimento e lista o piloto em `pilots`.

### Volumes medidos

| Volume | Validação | Rollup | Execuções | Energia |
| --- | --- | --- | --- | --- |
| 1 M | 22/22 (`validate-1000000-20261123T192730Z.json`) | 0 diferenças, 9 978 células (`rollup-check-20261123T192828Z.json`) | `20261123T193439Z-main`, `…193718Z-durability` (piloto `…193215Z-main`) | bateria 62% |
| 2 M | 22/22 (`validate-2000000-20261123T201732Z.json`) | 0 diferenças, 10 092 células, 2 000 024 eventos (`rollup-check-20261123T201826Z.json`) | `20261123T201831Z-main`, `…202000Z-durability`, réplica `…202101Z-main` (só leituras e E5) | bateria 26% (réplica 23%) |

**2 M é o maior volume carregado e validado.** A ampliação parou por **energia**, não por limite de hardware: o notebook ficou na bateria a tarde toda (62% → 21%), e o watchdog impediu novas cargas abaixo de 22%. Com a massa de 2 M, a VM manteve ≥ 2,78 GiB livres, swap ≤ 28 MiB, disco ≥ 157 GiB livres e nenhum contêiner perto de OOM (detalhes em [verification-task06.md](verification/verification-task06.md)). As duas execuções oficiais rodaram na bateria, acima dos 20% em que o Windows ativa a economia de energia, com o mesmo plano ("Equilibrado").

### Resultados: mediana HTTP (ms), 30 execuções por banco e volume

| Operação | Classe | Eventos cobertos 1 M → 2 M | PG 1 M | CS 1 M | PG 2 M | CS 2 M | Δ PG | Δ CS | Vencedor 1 M → 2 M |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1 READ por UUID | chave | 1 evento | 1,64 | 1,76 | 1,67 | 2,38 | +2,1% | +35% | PG 1,1× → PG 1,4× |
| E2 Q1 dispositivo quente, 1ª página | página fixa | 13 478 → 27 136 | 3,88 | 8,53 | 4,15 | 8,21 | +7,0% | −3,8% | PG 2,2× → PG 2,0× |
| E2 Q1 10 páginas (1 000 eventos) | página fixa | 13 478 → 27 136 | 32,3 | 95,0 | 31,7 | 90,4 | −1,7% | −4,8% | PG 2,9× → PG 2,9× |
| E2 Q1 dispositivo pouco ativo | resposta cresce | 54 → 113 | 3,08 | 11,3 | 3,70 | 13,0 | +20% | +15% | PG 3,7× → PG 3,5× |
| E3 Q2 IP de campanha, 1ª página | página fixa | 11 522 → 23 124 | 4,85 | 11,6 | 3,97 | 10,6 | −18% | −9,1% | PG 2,4× → PG 2,7× |
| E3 Q3 alertas severidade 3, 1ª página | página fixa | 2 476 → 4 929 | 3,93 | 7,97 | 4,01 | 7,72 | +1,9% | −3,2% | PG 2,0× → PG 1,9× |
| **E4 Painel 7 dias** | agregação | **244 881 → 489 346** | 90,8 | 6,12 | **173** | 7,93 | **+91%** | +30% | **CS 14,8× → CS 21,9×** |
| **E4 Painel 1 dia** | agregação | 48 193 → 96 707 | 17,5 | 2,88 | 42,9 | 4,39 | +145% | +52% | CS 6,1× → CS 9,8× |
| **E4 Painel 7 dias, só alertas** | agregação | 19 758 → 39 265 | 53,4 | 5,91 | 90,4 | 5,88 | +69% | −0,5% | CS 9,1× → CS 15,4× |

Resposta idêntica nos dois bancos em todas as operações dos dois volumes; o vencedor de cada operação venceu de 26 a 30 dos 30 pares. Gerado por `python benchmarks/scale_report.py`.

**Tempo dentro do banco (`Server-Timing`, mediana)**, que exclui HTTP e serialização:

| Operação | PG 1 M | PG 2 M (réplica) | CS 1 M | CS 2 M (réplica) |
| --- | --- | --- | --- | --- |
| E4 Painel 7 dias | 88,1 ms | 170,7 ms (195,0) | 3,14 ms | 3,64 ms (2,84) |
| E1 READ por UUID | 0,53 ms | 0,53 ms (0,59) | 0,73 ms | 1,08 ms (0,97) |

**Estabilidade entre execuções.** A réplica de 2 M, rodada 3 minutos depois com o mesmo protocolo, variou de −30% a +40% em relação à execução principal em várias operações (por exemplo, painel 7 dias no Cassandra 7,93 × 5,52 ms; READ no PostgreSQL 1,67 × 2,35 ms). Por isso, **variações de até ±40% nas medianas HTTP não são atribuídas ao volume.** O que excede esse ruído, nas duas execuções de 2 M, é o crescimento da agregação no PostgreSQL.

**E5 (psql) e rollup (Server-Timing), painel 7 dias, mediana:**

| Volume | PG agregação na leitura | PG view materializada | PG REFRESH completo | Cassandra rollup |
| --- | --- | --- | --- | --- |
| 1 M | 82,6 ms | 1,54 ms | 360 ms | 3,14 ms |
| 2 M | 160 ms | 1,09 ms | 640 ms | 3,63 ms |

**E6 (8 clientes, mediana de latência, PG / CS):**

| Volume | Política | CREATE | UPDATE | DELETE |
| --- | --- | --- | --- | --- |
| 1 M | padrão | 10,7 / **8,79** | 9,38 / **4,63** | 7,22 / **6,92** |
| 1 M | antes do fsync | **4,55** / 8,17 | **3,75** / 4,67 | **3,08** / 6,63 |
| 2 M | padrão | 10,3 / **7,98** | 9,87 / **4,50** | 8,78 / **6,49** |
| 2 M | antes do fsync | **4,60** / 7,85 | **3,85** / 4,48 | **3,13** / 6,42 |

**Ambiente por volume:** banco PostgreSQL 0,80 → 1,59 GB e keyspace Cassandra 0,33 → 0,66 GB (os dois ×2,0); acertos em `shared_buffers` 100% nos dois volumes; *key cache* do Cassandra 98,9% → 97,1%, com 0 → 10 MB lidos do disco pelo contêiner do Cassandra na fase de leitura.

### Interpretação (o que foi medido × o que é hipótese)

- **Agregação (E4): a diferença aumentou.** O PostgreSQL agrega na leitura uma entrada do índice de cobertura por evento do período; com o dobro de eventos na janela, o tempo no banco quase dobrou (88 → 171 ms; réplica 195 ms). O Cassandra lê as mesmas ≤ 7 × 360 células de contador (a tabela `event_counts_by_day` tinha 1 SSTable e ~372 células por partição em 2 M); seu tempo no banco ficou em 2,8–3,6 ms. A razão do painel de 7 dias foi de 14,8× para 21,9× (réplica 35,8×). No painel de 1 dia, o tempo no banco do Cassandra foi de 1,5 para 1,9–2,2 ms lendo as mesmas células: diferença de menos de 1 ms, dentro do ruído e não atribuída ao volume. Continua sendo o ganho da **pré-agregação na escrita**, não de um motor mais rápido.
- **E5: o PostgreSQL pré-agregado também não cresce na leitura** (view materializada 1,5 → 1,1 ms), mas o REFRESH completo cresceu junto com a tabela (360 → 640 ms). No Cassandra o custo está no incremento a cada CREATE, que não mudou de forma mensurável no E6.
- **Chave e página fixa (E1–E3): o PostgreSQL continuou vencendo todas.** B-tree e partição + clustering localizam a chave sem varrer a massa: o PostgreSQL ficou estável (E1 no banco 0,53 ms nos dois volumes) e as páginas Q1–Q3 do Cassandra também (−9% a −4%). O E1 no Cassandra subiu (0,73 → 1,08 ms no banco), **coincidindo** com a queda de acertos no *key cache* (o E1 lê UUIDs nunca lidos antes, por desenho) e com 10 MB lidos do disco; o *key cache* não estava cheio (≈ 70 mil entradas, 5,9 de 100 MiB). A causa exata (índices de partição de SSTables recém-compactadas fora do cache de páginas, por exemplo) **não foi isolada**.
- **Resposta que cresce:** o "Q1 dispositivo pouco ativo" passou de 54 para 113 eventos na janela, e a primeira página de 54 para 100 itens; os dois bancos ficaram mais lentos (+20% e +15%), e o Cassandra fez 100 leituras canônicas em vez de 54.
- **Escritas (E6): sem efeito mensurável do volume em 2 M** (todas as variações dentro do ruído). A política de durabilidade continua pesando mais: CREATE no PostgreSQL com 10,3 ms (fsync por commit) × 4,6 ms (confirmação antes do fsync). As janelas de perda continuam diferentes (~0,6 s × até 10 s).
- **Cache:** com 2 M, os dados quentes ainda cabem nos limites de memória (PG 100% de acertos; banco de 1,59 GB para 2 GiB de contêiner). Em volumes maiores, o PostgreSQL ultrapassaria os 2 GiB antes do Cassandra (5 GiB): essa assimetria de configuração é uma **ameaça à validade** para extrapolar estes resultados, e por isso nenhuma tendência foi extrapolada além de 2 M.
- **Um nó:** crescer a massa em uma máquina mostra como cada modelagem reage ao volume. Não demonstra escalabilidade horizontal, replicação nem tolerância a falhas.

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
