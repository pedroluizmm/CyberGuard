# CyberGuard

Plataforma acadêmica de monitoramento e investigação de **eventos de cibersegurança**, implementada em **Apache Cassandra** (wide-column) e **PostgreSQL** (relacional) com o mesmo conjunto lógico de **1 000 000 de eventos**. Inclui CRUD equivalente, consultas de investigação, um dashboard SOC que consulta os dois bancos ao vivo e benchmarks reprodutíveis. Projeto 3 de Banco de Dados NoSQL, UNIFOR (paradigma 1: orientado a colunas).

## Resultados em resumo

São 30 medições por operação e banco, em pares intercalados e com cache quente. Em todas as operações, os dois bancos devolveram resposta idêntica. Detalhes em [docs/benchmark-methodology.md](docs/benchmark-methodology.md).

| Experimento | PostgreSQL | Cassandra | Vencedor |
| --- | --- | --- | --- |
| E1 · READ por UUID | 1,19 ms | 1,41 ms | PostgreSQL 1,2× |
| E2/E3 · Q1/Q2/Q3, página de 100 eventos | 3,6–3,9 ms | 7,3–9,9 ms | PostgreSQL 1,9–2,7× |
| **E4 · Painel do SOC, 7 dias (244 881 eventos): rollup pré-agregado × agregação na leitura** | 71,9 ms | **3,3 ms** | **Cassandra 21,9×** |
| E4 · Painel, 1 dia | 15,6 ms | 2,2 ms | Cassandra 7,1× |
| E5 · Controle: PostgreSQL com view materializada | 1,15 ms leitura · 282 ms REFRESH | 1,79 ms (banco) | Leitura equivalente; trade-off de atualização |
| E6 · CREATE concorrente: durabilidade padrão / ambos confirmando antes do fsync | 13,2 / 5,8 ms | 10,8 / 9,5 ms | Depende da política de `fsync` |

**Conclusão:** o Cassandra vence onde a modelagem orientada a consultas permite pré-agregar na escrita (o painel). O 21,9× mede essa pré-agregação, não uma velocidade bruta maior do motor: com view materializada, o PostgreSQL lê o painel na mesma ordem de grandeza, mas depende de REFRESH completo. O PostgreSQL vence buscas por chave e escritas quando os dois bancos confirmam antes do fsync. A otimização do N+1 no Cassandra reduziu as páginas Q1–Q3 de 26–43 ms para 7–11 ms.

## Arquitetura e organização

```text
Navegador (Svelte 5) ──/api──► API Rust/Axum ──SQLx──────────► PostgreSQL 17 (normalizado + índices)
                                   │      └──Scylla driver──► Cassandra 5 (tabelas por consulta + rollup)
Scripts Python (carga, validação, benchmark) ──HTTP──┘
```

| Pasta | Conteúdo |
| --- | --- |
| `backend/` | API Rust (Axum/Tokio): domínio, CRUD, Q1–Q3, painel, `Server-Timing`, adaptadores dos dois bancos |
| `frontend/` | Dashboard SOC em Svelte 5 + TypeScript (Vite, sem SvelteKit) |
| `database/` | Esquemas aditivos: `postgresql/00{1,2}_*.sql`, `cassandra/00{1,2}_*.cql` |
| `scripts/` | Ambiente, esquemas, execução da API, geração/carga/validação da massa, reconciliação do rollup |
| `benchmarks/` | Executor dos experimentos e resultados brutos (`results/`) |
| `data/` | Amostra de 24 eventos, manifesto da massa de 1 M e relatórios de carga e validação |
| `docs/` | Requisitos, arquitetura, modelos, consultas, consistência, metodologia, verificações, entregas e apresentação |

## Pré-requisitos (Windows)

- Docker Desktop (contêineres Linux, WSL 2), Git, Python 3.11+ e Node.js 22.17+ com npm.
- **Rust não precisa estar instalado:** `scripts/run_api.py` compila e executa a API na imagem oficial `rust:1.99.1-slim-bookworm`. Com Rust local, `cargo run --release --manifest-path backend/Cargo.toml` é equivalente.
- Portas 3000, 5173, 5432 e 9042 livres. A máquina de referência tem 16 GB de RAM; os bancos usam até 5 GiB (Cassandra) + 2 GiB (PostgreSQL).

## Início rápido (ambiente já carregado)

No PowerShell, a partir da raiz:

```powershell
docker compose up -d --wait --wait-timeout 720   # PostgreSQL + Cassandra (volumes persistentes)
python scripts/run_api.py build                  # só na primeira vez (~5 min): binário release
python scripts/run_api.py start                  # API em http://127.0.0.1:3000
python scripts/validation/check_api.py           # confirma API e os dois bancos
npm.cmd --prefix frontend ci                     # só na primeira vez
npm.cmd --prefix frontend run dev                # dashboard em http://localhost:5173
```

`npm.cmd` evita o bloqueio de `npm.ps1` pela ExecutionPolicy. O roteiro da demonstração ao vivo está em [docs/apresentacao/roteiro-demo.md](docs/apresentacao/roteiro-demo.md).

Para parar, use `python scripts/run_api.py stop` e `docker compose stop`. Os volumes são preservados; **nunca** use `docker compose down -v`, `volume rm` ou `prune`.

## Instalação completa do zero

```powershell
python scripts/setup_env.py                      # gera .env com senha aleatória (não sobrescreve)
docker compose config --quiet
docker compose up -d --wait --wait-timeout 720
python scripts/apply_schema.py                   # aplica database/*/NNN_* (aditivo, repetível)
python scripts/run_api.py build
python scripts/run_api.py start
python scripts/generation/generate_sample.py ; python scripts/loading/load_sample.py
python scripts/generation/generate_bulk.py --count 1000000                 # reproduz o manifesto
python scripts/loading/load_bulk.py --source postgresql --target 1000000   # ~30 min, retomável
python scripts/loading/load_bulk.py --source cassandra  --target 1000000   # ~25 min, retomável
python scripts/loading/reconcile_rollup.py --apply                         # backfill do painel Cassandra
python scripts/validation/check_bulk.py --target 1000000                   # 22 verificações (~4 min)
```

A massa é gerada em streaming a partir de uma seed fixa, e nenhum arquivo de eventos é gravado. O significado de "registro", a origem, os volumes e os tempos estão em [docs/entregas/19-11-massa-carga-dados.md](docs/entregas/19-11-massa-carga-dados.md).

## Dashboard

Interface escura com barra lateral e quatro seções (o endereço guarda a seção, por exemplo `#comparacao`). A barra de filtros é comum a todas elas: período (atalhos ou data + 1 a 7 dias), categoria e severidade.

- **Visão geral:**
  - indicadores de eventos, alertas, críticos e tempo de resposta;
  - série horária por categoria, volume diário, severidade, categorias e indicadores de atividade (pico, média por hora, dia mais ativo);
  - seletor **PostgreSQL / Cassandra** no topo: todas as consultas são refeitas na fonte escolhida.
- **Investigação:** Q1 dispositivo, Q2 IP e Q3 alertas, com paginação por cursor, tempo por página e painel de detalhes do evento, com READ por UUID que confere o conteúdo.
- **Comparação:** executa a mesma consulta (painel, Q1 ou Q3) N vezes nos dois bancos e mostra medianas lado a lado, a razão, cada execução e se o resultado de negócio é idêntico.
- **Benchmarks:** resultados medidos (`benchmarks/results/summary.json`): destaques E4/E1–E3/E5/E6, protocolo e ambiente, medianas em escala log, N+1 antes e depois, controle E5, escritas E6 e limitações.
- **Estados:** carregando, vazio, filtro inválido, banco indisponível, "não verificado" e API inacessível. Nenhum dado é fixo ou simulado.
- **Acessibilidade:** responsivo de 390 px a desktop, navegação por teclado com foco visível, link para pular ao conteúdo. As cores dos gráficos foram validadas para daltonismo, e cada banco também se distingue pela forma: círculo para o PostgreSQL e losango para o Cassandra.

## API

| Endpoint | Descrição |
| --- | --- |
| `GET /api/health`, `/api/health/storage`, `/api/runtime` | Saúde da API, sondas dos bancos (503 se algum cair), build e configuração experimental |
| `POST /api/{source}/events` | CREATE (201 novo, 200 repetição idêntica, 409 conflito) |
| `GET/PUT/DELETE /api/{source}/events/{id}` | READ, UPDATE com `expected_revision`, DELETE `?expected_revision=N` |
| `POST /api/{source}/events/{id}/repair` | Conclui operações Cassandra interrompidas por ID |
| `GET /api/{source}/queries/{device\|ip\|alerts}` | Q1/Q2/Q3: `from`, `to` (≤ 7 datas UTC), `page_size` ≤ 100, `cursor` |
| `GET /api/{source}/stats/overview` | Painel: `from`/`to` em horas inteiras UTC, `category`, `severity` |
| `GET /api/benchmarks/summary` | Resultados medidos (404 se nenhum benchmark foi executado) |

`source` é `postgresql` ou `cassandra`. READ, consultas e painel devolvem `Server-Timing: db;dur=<ms>`. O contrato completo está em [docs/data-model.md](docs/data-model.md) e [docs/query-patterns.md](docs/query-patterns.md).

Exemplo de CRUD com um evento **novo**, sem tocar a massa nem a amostra. Repita com `cassandra` usando o mesmo corpo:

```powershell
$api = 'http://127.0.0.1:3000'; $source = 'postgresql'
$event = @{ event_id = [guid]::NewGuid().ToString(); occurred_at = '2026-11-09T10:00:00.000Z'; event_date = '2026-11-09'
  device_id = 'manual-sensor-01'; source_ip = '192.0.2.50'; category = 'authentication'; event_type = 'login'
  severity = 2; outcome = 'failure'; message = 'Synthetic login for CRUD validation'; metadata = @{ synthetic = $true } }
$created = Invoke-RestMethod -Method Post -Uri "$api/api/$source/events" -ContentType 'application/json' -Body ($event | ConvertTo-Json -Compress)
$id = $created.data.event_id
Invoke-RestMethod -Uri "$api/api/$source/events/$id"
$update = @{ expected_revision = 1; outcome = 'failure'; message = 'Reviewed'; metadata = @{ synthetic = $true; reviewed = $true } } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Put -Uri "$api/api/$source/events/$id" -ContentType 'application/json' -Body $update
Invoke-RestMethod -Method Delete -Uri "$api/api/$source/events/${id}?expected_revision=2"
```

Depois do DELETE, o READ retorna 404 e o UUID não pode ser reutilizado. As respostas 400, 404, 409 e 503 fazem parte do contrato; o PowerShell as lança como erro.

## Benchmarks

```powershell
python benchmarks/run_benchmarks.py --suite main      # E1-E6 (API release; ~2 min)
```

As variantes `n1` (N+1 sequencial) e `durability` (PostgreSQL `synchronous_commit=off`) exigem reiniciar a API com `--read-concurrency 1` ou `--pg-synchronous-commit off`. Veja [benchmarks/README.md](benchmarks/README.md). Cada execução grava `raw.csv`, `raw_writes.csv`, `environment.json` e `run.json` em `benchmarks/results/<UTC>-<suite>/`, sem alterar a massa de 1 M.

## Verificação

```powershell
docker compose config --quiet
python scripts/validation/check_foundation.py           # PDFs, .gitignore, segredos fora do Git
$p = (Get-Location).Path                                # Rust via contêiner (fmt, testes, build)
docker run --rm --mount "type=bind,source=$p,target=/workspace" --workdir /workspace/backend --env CARGO_HOME=/workspace/tmp/cargo rust:1.99.1-slim-bookworm sh -c "rustup component add rustfmt && cargo fmt --check && cargo test --locked && cargo build --locked"
npm.cmd --prefix frontend run build                     # svelte-check + TypeScript + Vite
# com bancos e API ativos:
python scripts/validation/check_api.py
python scripts/validation/test_integration.py           # 10 testes HTTP nos dois bancos
python scripts/validation/test_recovery.py
python scripts/validation/check_sample.py
python scripts/validation/test_bulk_generator.py
python scripts/loading/reconcile_rollup.py              # simulação: rollup == verdade == PostgreSQL
python scripts/validation/check_bulk.py --target 1000000
```

O que foi executado e com qual resultado está registrado em [docs/verification/verification-task05.md](docs/verification/verification-task05.md) (testes completos, redesign do frontend e PDF da apresentação) e [verification-task04.md](docs/verification/verification-task04.md), mais as tarefas [01](docs/verification/verification-task01.md), [02](docs/verification/verification-task02.md) e [03](docs/verification/verification-task03.md).

## Segurança e persistência

- Bancos, API e Vite escutam só em `127.0.0.1`. O CORS aceita uma única origem local (`FRONTEND_ORIGIN`). O frontend nunca recebe credenciais.
- O PostgreSQL usa senha aleatória (SCRAM) gerada em `.env`, que é ignorado pelo Git. O Cassandra roda sem autenticação, uma **exceção aceitável apenas neste laboratório local**. Não há TLS. Nada aqui é configuração de produção.
- Os esquemas são aditivos (`IF NOT EXISTS`). Os scripts não executam DROP, TRUNCATE nem remoção de volumes. Testes e benchmarks só criam, alteram e excluem UUIDs próprios, em janelas reservadas (2001 e 2002).
- Um único nó Cassandra (RF=1) não oferece redundância nem demonstra escalabilidade horizontal.

## Documentação

| Tema | Documento |
| --- | --- |
| Requisitos e rastreabilidade | [docs/requirements.md](docs/requirements.md) |
| Arquitetura | [docs/architecture.md](docs/architecture.md) |
| Modelos de dados (diagramas) | [docs/data-model.md](docs/data-model.md) |
| Consultas SQL/CQL e índices | [docs/query-patterns.md](docs/query-patterns.md) |
| Consistência, recuperação e rollup | [docs/consistency.md](docs/consistency.md) |
| Massa: geração, carga e validação | [docs/bulk-load.md](docs/bulk-load.md) |
| Metodologia e resultados experimentais | [docs/benchmark-methodology.md](docs/benchmark-methodology.md) |
| Entregas (10/11, 17/11, 19/11, 24/11) | [docs/entregas/](docs/entregas/README.md) |
| Apresentação final (PDF), fonte editável, roteiro e demonstração | [CyberGuard_Apresentacao_Final.pdf](docs/apresentacao/CyberGuard_Apresentacao_Final.pdf) · [slides.html](docs/apresentacao/slides.html) · [roteiro](docs/apresentacao/roteiro-apresentacao.md) · [demo](docs/apresentacao/roteiro-demo.md) |
