# Task 04: comparação final, benchmarks, dashboard e entregas

Data: 15/11/2026 (UTC nos relatórios). O fluxo seguiu READ → PLAN → APPLY → VERIFY. Não houve commit nem push. Os PDFs, o `.env` e os volumes foram preservados.

## READ: estado encontrado

| Área | Estado inicial | Problema priorizado |
| --- | --- | --- |
| Dados | PG `events` com 1 000 024 linhas; Cassandra com cerca de 1 M de partições canônicas; containers saudáveis | — |
| Backend | CRUD, Q1–Q3, repair; apenas build debug | **N+1 sequencial** no Cassandra (até 101 leituras por página, de 74 a 82 ms na observação da Task 03); nenhuma consulta agregada para o painel; nenhum tempo de banco exposto |
| Cassandra | Nenhuma tabela capaz de responder "eventos por período" sem varredura | O painel exigia uma modelagem nova |
| PostgreSQL | Sem índice temporal; 52 mil linhas sem visibilidade marcada após o último autovacuum | 12 945 *heap fetches* em *index-only scan* |
| Frontend | Tela de conectividade da Task 01 | Dashboard inexistente |
| Benchmarks | Nenhum | Requisitos R08–R14 pendentes |
| Entregas | `docs/entregas/README.md` apagado (não versionado no índice de trabalho) | Restaurado com `git restore` e ampliado |
| Ambiente | Rust ausente no Windows; 1,2–1,6 GiB de RAM livre no host | Builds e API executados no contêiner `rust:1.99.1-slim-bookworm` |

## PLAN

1. Otimizar o N+1 sem mudar a semântica, com um parâmetro para reproduzir o comportamento antigo.
2. Expor `Server-Timing`, `/api/runtime` e `/api/benchmarks/summary`.
3. Criar o painel agregado: rollup de contadores no Cassandra e índice de cobertura no PostgreSQL, com resposta idêntica.
4. Fazer o backfill e a reconciliação do rollup sem varrer a aplicação.
5. Criar o executor de benchmark com protocolo controlado e variantes N+1 e durabilidade.
6. Construir o dashboard SOC.
7. Escrever documentação, entregas e apresentação.
8. Limpar o repositório e retestar tudo.

## APPLY

| Arquivo | Mudança |
| --- | --- |
| `backend/src/storage/cassandra.rs` | Leituras canônicas com `futures::stream::buffered` (ordem preservada); contador do rollup só na LWT vencedora; `overview()` lê até 7 partições em paralelo |
| `backend/src/storage/postgresql.rs` | `overview()`: `date_bin` + `GROUP BY` com fragmentos fixos e parâmetros vinculados |
| `backend/src/analytics/mod.rs` | `OverviewQuery`/`Overview`: horas inteiras, 7 datas, filtros, série completa; 2 testes novos |
| `backend/src/api/*.rs`, `config.rs`, `repository.rs` | `Server-Timing`, rotas novas, `CASSANDRA_READ_CONCURRENCY`, `POSTGRES_SYNCHRONOUS_COMMIT`, `BENCHMARK_SUMMARY`, build no health |
| `database/cassandra/002_rollup.cql`, `database/postgresql/002_dashboard.sql` | Tabela `event_counts_by_day` e índice `events_time_cover_idx`, ambos aditivos |
| `scripts/apply_schema.py` | Aplica todos os `NNN_*` em ordem |
| `scripts/run_api.py` | Build, start, stop, status e logs da API em contêiner, sem imprimir `.env` |
| `scripts/loading/reconcile_rollup.py`, `bulk_runtime.py` | Backfill e reconciliação por diferença; exportações em streaming compartilhadas |
| `scripts/validation/test_integration.py` | `test_08` (painel equivalente; rollup segue o CRUD) e `test_09` (validação) |
| `scripts/validation/test_recovery.py` | Injeção fiel do CREATE interrompido (ver VERIFY) |
| `scripts/validation/check_bulk.py`, `check_foundation.py` | Reuso dos helpers; novas verificações de caminhos versionáveis |
| `benchmarks/run_benchmarks.py`, `benchmarks/sql/pg_rollup_control.sql` | Executor E1–E6 e controle E5 |
| `frontend/src/**` | Dashboard SOC (7 componentes novos, `api.ts`, `format.ts`, `app.css`); `StatusBadge.svelte` removido por não ser usado |
| `docs/**`, `README.md`, `AGENTS.md` | Metodologia, entregas de 10/11 a 24/11, apresentação, atualização dos documentos técnicos |

Manutenção de banco executada: `VACUUM (ANALYZE) events` e `VACUUM (ANALYZE) event_registry`, rotina não destrutiva recomendada após carga em massa. A configuração do Compose e dos bancos não mudou.

## VERIFY

| Comando ou cenário | Resultado real |
| --- | --- |
| `cargo fmt --check` (contêiner) | Passou |
| `cargo test --locked` | **10/10** (8 anteriores + 2 do painel) |
| `cargo build --locked` e `cargo build --release --locked` | Passaram, sem warnings |
| `npm.cmd --prefix frontend run build` | svelte-check: **0 erros, 0 avisos** (203 arquivos); Vite build OK |
| `docker compose config --quiet`; `docker compose ps` | Válido; os dois serviços *healthy* |
| `python scripts/apply_schema.py` | 4 arquivos aplicados (2 novos) sem recriar nada; índice de 42 MB criado em segundos |
| `python scripts/loading/reconcile_rollup.py --apply` (backfill) | 1 000 024 eventos em 9 978 células; **PostgreSQL igual célula a célula**; 57 s |
| `python scripts/validation/check_api.py` | API release; os dois bancos up; CORS restrito |
| `python scripts/validation/test_integration.py` | **9/9** testes, executado 3 vezes ao longo da tarefa |
| `python scripts/validation/test_recovery.py` | Passou (versão corrigida) |
| `python scripts/validation/check_sample.py` | 24 IDs e conteúdos; Q1 = 15, Q2 = 12, Q3 = 6; 81 linhas Cassandra |
| `python scripts/validation/test_bulk_generator.py` | 5/5 |
| `python scripts/validation/check_foundation.py` | 44/44 (PDFs intactos, segredos fora do Git, novas evidências versionáveis) |
| Exemplo de CRUD do README (PowerShell), nos dois bancos | CREATE rev 1 → READ → PUT rev 2 → DELETE → READ 404 |
| `python benchmarks/run_benchmarks.py --suite main` (2 execuções), `--suite n1`, `--suite durability` | Todas completas; 9/9 operações com resposta idêntica; 30/30 pares para o mesmo vencedor em cada operação ([benchmark-methodology.md](../benchmark-methodology.md)) |
| `reconcile_rollup.py` (simulação) depois de todos os testes, benchmarks e reinício do Cassandra | **0 diferenças**; PostgreSQL igual à verdade do Cassandra |
| `check_bulk.py --target 1000000` (final, depois de todas as mudanças, testes e benchmarks) | **22/22**: conteúdo integral e IDs iguais ao gerador nos dois bancos, projeções exatas, `3N + A`, partições iguais ao manifesto, 500 READs e Q1–Q3 iguais (`data/bulk/reports/validate-1000000-20261115T152638Z.json`) |
| Navegador (Vite dev, `localhost:5173`) | Visão geral, tooltip, comparação ao vivo, investigação Q1 e aba Benchmarks verificadas; 390 px sem rolagem horizontal nas 3 vistas |
| API parada | Indicadores "API indisponível"; painel com "A API local não está acessível"; Benchmarks com erro explícito |
| `docker compose stop postgresql`, depois `start` | PG retorna 503 `storage_unavailable`, Cassandra continua 200; o dashboard mostra banner e erro sem dados; o pool reconectou sem reiniciar a API |
| `docker compose stop cassandra`, depois `start` | Cassandra retorna 503, PG continua 200; o driver reconectou em cerca de 5 s depois de *healthy* |
| Volumes (`docker volume inspect … CreatedAt`) | `2026-11-09T05:06:41Z` nos dois, inalterados |

### Falhas encontradas e corrigidas

- **HRTB no `buffered` (compilação):** o stream recebia referências. Passou a receber UUIDs por valor.
- **Desvio no rollup provocado por `test_recovery.py`:** a versão anterior reescrevia para `pending` um evento já ativo, que já tinha sido contado. A ativação no repair contava esse evento de novo (+1). A reconciliação detectou exatamente 1 célula com −1, corrigiu e registrou o relatório (`rollup-reconcile-20261115T052502Z.json`). O teste passou a simular a queda real: reserva `pending` sem projeções e ainda não contada.
- **Rótulo ambíguo no modo de simulação do reconciliador:** agora mostra "DRIFT" quando há diferença.
- **Configurações do PostgreSQL no `environment.json`:** a concatenação `setting||unit` estava errada (por exemplo, 655368kB). Corrigido para `current_setting()`. A primeira execução `main` tem o valor mal formatado no arquivo, sem efeito nas medições.
- **Frontend com a API fora do ar:** o proxy do Vite responde 500 sem corpo, e a interface culpava o banco. Agora reporta "A API local não respondeu".
- **Aviso de acessibilidade no gráfico navegável por teclado:** passou a usar `role="slider"` com `aria-valuetext`.

### Bloqueios e o que não foi executado

- **Capturas de tela no navegador:** depois das primeiras imagens, a ferramenta passou a esgotar o tempo (a janela estava oculta ou maximizada). A responsividade a 390 px e a existência dos estados foram verificadas por asserções no DOM, inclusive em um iframe de 390 px. Não há captura móvel.
- **Cache frio:** não foi medido, porque exigiria esvaziar o cache do SO da VM.
- **5 M eventos:** não tentado (RAM do host).
- **Múltiplos nós Cassandra:** fora do escopo do hardware.

## Limpeza (Stage 7)

| Item | Ação | Justificativa |
| --- | --- | --- |
| `.playwright-mcp/` | Removido | Dump de console e página de uma ferramenta de navegador da Task 01; ignorado e sem referência |
| `scripts/**/__pycache__/` | Removido | Bytecode regenerável |
| `tmp/integration-*.json` (5) | Removidos | Manifestos de posse de execuções de teste; os 240 IDs listados foram conferidos e retornam 404 nos dois bancos |
| `tmp/frontend-desktop.png`, `tmp/frontend-mobile.png` | Removidos | Capturas da interface da Task 01, que foi substituída; sem referência |
| `frontend/src/lib/StatusBadge.svelte` | Removido | Componente sem uso |
| Funções `stream_csv`/`cql_copy` duplicadas em `check_bulk.py` | Removidas (reuso de `bulk_runtime.py`) | Duplicação |
| `.gitignore` | `*.partial` acrescentado | Temporários de escrita atômica |
| Mantidos | `tmp/cargo` (cache de build offline), `tmp/docker` (citado como `--docker-config`), `tmp/git-bootstrap-backup` (documentado na Task 01, sem histórico), `tmp/*.log` (logs das cargas da Task 03), `tmp/pdfs`, `tmp/npm-cache`, `data/generated/*` (checkpoints), PDFs, `.env`, volumes e todos os relatórios | Evidência, cache necessário ou dado pessoal |

## RISKS

- O rollup depende de contadores não idempotentes. Falhas parciais exigem `reconcile_rollup.py` com a API ociosa, e não há reconciliador automático contínuo.
- As vantagens medidas valem para um nó, cache quente e esta massa sintética. Valores absolutos variam de 10% a 35% entre execuções; os vencedores se mantiveram.
- A API em contêiner depende de `backend/target/release/cyberguard-api` (Linux). Em uma máquina nova, rode `python scripts/run_api.py build` antes, com cerca de 5 min e rede para baixar crates na primeira vez.

## Auditoria final pré-entrega

Fluxo READ → PLAN → APPLY → VERIFY sobre o estado local. Não houve commit nem push. As correções abaixo foram feitas apenas onde havia problema comprovado.

### Achados e correções

| # | Achado (evidência) | Severidade | Correção |
| --- | --- | --- | --- |
| A1 | **E6 confundido pelo pool:** a API tinha pool PostgreSQL fixo de 5 conexões para 8 clientes concorrentes; o driver Cassandra multiplexa sem esse teto (`repository.rs`: `max_connections(5)`) | Alta (validade) | `POSTGRES_POOL_SIZE` configurável (padrão 16), exposto em `/api/runtime`. O executor recusa o E6 com pool < clientes (`BLOCKED`, testado com 32 clientes) |
| A2 | **E6 sem aquecimento:** a execução `…202031Z-writes`, com o Cassandra recém-reiniciado, mostrou CREATE caindo de 28,9 para 11,7 ms ao longo das rodadas (JIT da JVM) | Alta (validade) | `--write-warmup` (padrão 2 rodadas descartadas, `phase` no `raw_writes.csv`). Nova suíte `writes`. E6 re-medido: `…202129Z-writes` e `…202202Z-durability`. Execuções antigas preservadas |
| A3 | "Durabilidade equiparada" impreciso: as janelas de perda diferem (PG ≈ 3 × `wal_writer_delay` ≈ 0,6 s; Cassandra ≈ 10 s) | Média | Redação: "ambos confirmam antes do fsync", com as janelas explícitas, em todos os documentos, slides e dashboard |
| A4 | O 21,9× do E4 aparecia sem qualificação em README, slides e dashboard; a legenda do E5 dizia "tão rápido quanto" comparando `psql` (1,15 ms) com driver (1,79 ms) | Média | Qualificado como "rollup pré-agregado × agregação na leitura; mede a pré-agregação, não velocidade bruta do motor"; E5 descrito como "mesma ordem de grandeza, fronteiras diferentes"; a hipótese do gatilho foi marcada como não medida |
| A5 | Metodologia afirmava que "os dois bancos receberam manutenção" (só o PostgreSQL teve `VACUUM`) e chamava o Engine 29.4.3 de "Docker Desktop" | Baixa | Corrigido |
| A6 | Dashboard, comparação ao vivo: uma execução fria definia a escala e achatava as barras | Média (demonstração) | 1 par de aquecimento descartado (valores exibidos), escala pelas medianas, valores fora da escala presos ao fim com contorno |
| A7 | Selos de severidade 3–5 com texto branco sobre azul claro: contraste 2,99 / 2,11 / 1,54:1 | Média (acessibilidade) | Texto escuro: 6,36 / 9,00 / 12,36:1 |
| A8 | "Não verificado" exibido em vermelho, igual a "indisponível" (AGENTS.md exige distinguir) | Baixa | Estado neutro (cinza, marcador vazado) |
| A9 | Em 390 px, rótulos de data encostados no gráfico horário; eixo sobreposto e títulos cortados no gráfico de benchmark | Baixa | Rótulos espaçados automaticamente (≥ 52 px); eixo só com décadas e títulos com reticências (texto completo no hover) |
| A10 | Texto "27/10 a 27/10" para 1 dia | Baixa | "27/10 · 1 dia" |
| A11 | 503 em leitura dizia "a write may have completed" | Baixa | Mensagem distingue escrita |
| A12 | Sem teste para `Server-Timing`, `/api/runtime` e `/api/benchmarks/summary` | Baixa | `test_10` em `test_integration.py` |
| A13 | Slides: navegação por `#n` só funcionava no carregamento; diagrama de partição sem aviso de ilustrativo; espaço vazio no slide 7 | Baixa | `hashchange`, legenda "exemplo ilustrativo", layout ajustado |
| A14 | Documentação de CQL com `events + -1` (o código usa `+ ?` com `Counter(-1)`) | Baixa | `events - 1` |

### Validade dos benchmarks (conclusão da auditoria)

- **Dados brutos conferidos de forma independente:**
  - recalculei a partir dos CSVs as contagens (30 + 5 por operação e banco), os status (todos 200), as medianas e a equivalência de cada par, e tudo coincidiu com o `run.json` de todas as execuções;
  - as escritas tiveram 0 status inesperados e limpeza total da janela.
- **E1–E3 e N+1:** são válidos. Leituras sequenciais usam 1 conexão, então o pool não interfere.
- **E4:** é válido como comparação entre **modelagens idiomáticas** (rollup incremental × agregação na leitura com índice de cobertura e SQL otimizada). Não é válido como prova de que o motor Cassandra lê mais rápido: o E5 mostra que o PostgreSQL pré-agregado fica na mesma ordem de grandeza. A documentação agora diz isso em todos os lugares.
- **E6:** a conclusão original se manteve depois da correção do pool e do aquecimento: o pool não era o fator dominante (PostgreSQL CREATE 12,4 ms com pool 5 × 13,2 ms com pool 16). As tabelas do E6 foram substituídas pelas execuções corrigidas.
- **Não medido e declarado:** cache frio, tabela-resumo por gatilho no PostgreSQL, `REFRESH CONCURRENTLY` e escala horizontal.

### Verificação executada após as correções

| Comando | Resultado |
| --- | --- |
| `cargo fmt --check`, `cargo test --locked`, `cargo build --locked`, `cargo build --release --locked` (contêiner) | OK; 10/10; sem warnings |
| `npm.cmd --prefix frontend run build` | 0 erros, 0 avisos |
| `docker compose config --quiet`, `docker compose ps` | Válido; os dois serviços *healthy* |
| `check_foundation.py` | 44/44 |
| `check_api.py` | OK (API release, pool 16) |
| `test_integration.py` | **10/10** |
| `test_recovery.py`, `check_sample.py`, `test_bulk_generator.py`, `compileall` | OK |
| `run_benchmarks.py --suite writes` / `--suite durability` (re-medição justificada por A1/A2) | Completas; limpeza 0/0 |
| `run_benchmarks.py --suite main` reduzido, em pasta temporária fora do repositório | Completo (verifica o caminho do código); não é evidência |
| `run_benchmarks.py --suite writes --write-concurrency 32` | `BLOCKED` (pool 16 < 32), sem criar pasta |
| `reconcile_rollup.py` (simulação) após todas as escritas | **0 diferenças**; PostgreSQL igual à verdade do Cassandra |
| `check_bulk.py --target 1000000` | **22/22** (`data/bulk/reports/validate-1000000-20261115T204441Z.json`) |
| Navegador (capturas reais) | Desktop: visão geral, filtros, troca de fonte, comparação ao vivo, investigação com paginação, benchmarks. Viewport de 390 px renderizado em iframe de mesma origem: visão geral, gráficos, comparação, benchmarks. Estados: API parada, PostgreSQL parado (e recuperação), "não verificado". Slides: 15/15 revisados |

### Pendências reais

- Nomes da equipe no slide 1 e na capa: não preenchidos (não foram inferidos do usuário do sistema).
- Validação formal do SGBD pelo professor (exigida no PDF): sem evidência no repositório.
- O redimensionamento real da janela do navegador não teve efeito (janela maximizada pelo SO). O teste móvel usou iframe de 390 px, que aplica as media queries, mas não emula toque nem densidade de pixels.
