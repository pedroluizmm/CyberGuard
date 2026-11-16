# Task 01 - relatório de verificação

Data: 09/11/2026 (America/Fortaleza). Modo APPLY, sequência READ → PLAN → APPLY → VERIFY. Nenhum commit ou push foi realizado.

## READ

O workspace inicial continha somente os três PDFs do professor, sem repositório Git. Todos foram lidos por extração de texto com pypdf e inspeção das cinco páginas renderizadas com PyMuPDF. Poppler não estava instalado; nenhuma alteração foi feita nos originais.

| Ferramenta | Estado inicial |
| --- | --- |
| Git | 2.50.1.windows.1 |
| Docker CLI / Compose | 29.4.3 / v5.1.3; daemon inicialmente parado |
| Rust / Cargo no Windows | Ausentes do PATH e sem instalação em `.cargo/bin` |
| Node.js / npm | 22.17.1 / 10.9.2 |
| Python | 3.13.6, pypdf e PyMuPDF disponíveis |
| `py` launcher | Presente, mas não encontrava instalação; usado `python` diretamente |
| `pdftotext` / `pdftoppm` | Ausentes; renderização com PyMuPDF |

`npm.ps1` estava bloqueado pela política PowerShell. Foi usado `npm.cmd`, sem mudar ExecutionPolicy. O acesso inicial ao registro npm falhou com EACCES; a instalação local foi concluída com execução autorizada fora do isolamento. A leitura da configuração Docker do perfil foi evitada usando `docker --config .\tmp\docker`; comandos ao daemon exigiram execução autorizada por permissão do named pipe.

O `.git` inicialmente criado pelo executor isolado teve conflito de propriedade ao acessar pelo usuário Pedro. A tentativa de ajustar somente sua propriedade foi negada pelo Windows. Como o repositório estava vazio (sem refs/índice), o `.git` foi preservado em `tmp/git-bootstrap-backup` e inicializado novamente sob o usuário. Não houve alteração de configuração global de Git nem perda de histórico.

## PLAN

Monólito modular Rust com interface Svelte 5 separada; PostgreSQL e Cassandra únicos serviços permanentes do Compose; Python para preparação e futura engenharia de dados. Módulos futuros possuem documentação mínima, sem código fictício. Sem motor de ingestão, schemas de eventos, consultas de negócio ou massa definitiva.

Adaptações justificadas:

- Vite 6.4.5 para compatibilidade com Node 22.17.1, sem atualização global.
- Rede bridge dedicada com portas loopback. `internal: true` foi testado e removido porque o Engine disponível deixava as portas sem publicação no host, embora os healthchecks internos passassem. A correção foi confirmada por sockets reais no Windows. Contêineres/rede foram recriados sem remover volumes.
- Toolchain Rust em contêiner temporário para viabilizar compilação sem instalar Rust/Cargo no Windows. Imagem `rust:1.99.1-slim-bookworm`, rustc 1.99.1; digest observado `sha256:f2c004e3d2d8b547e8cf7ffbc29205385f4e71d23e53e4e383065db5e9f822cd`. rustfmt foi adicionado somente ao contêiner efêmero.

## APPLY

- `.gitignore`, `.env.example`, `.env` local com senha aleatória e script idempotente de geração.
- Compose com Cassandra 5.0.9 (5 GiB, heap inicial/máximo 2 GiB, G1) e PostgreSQL 17.11 (2 GiB, shared_buffers 512 MB), volumes e healthchecks.
- Backend Axum/Tokio com health básico, probes SQLx/Scylla, timeouts independentes, códigos de erro sanitizados, logs JSON e CORS local explícito.
- Frontend Svelte 5.57.3 / TypeScript 5.9.3 / Vite 6.4.5, navegação inicial, responsividade, estados de loading/erro/ausência de dados e botão de nova verificação.
- Pastas de domínio, ingestão, analytics, benchmark, modelos, scripts e dados documentadas; README, arquitetura, requisitos, entregas e AGENTS.md.
- Lockfiles npm e Cargo gerados pelas ferramentas reais.

## VERIFY

| Comando / inspeção | Resultado |
| --- | --- |
| `git status --short`, `git check-ignore -v` nos nomes reais dos PDFs | Somente arquivos do projeto versionáveis; PDFs e `.env` ignorados |
| `python scripts/validation/check_foundation.py` | Todos os checks passaram: hashes, índice Git, exclusões e ausência da senha local entre arquivos versionáveis |
| `python scripts/setup_env.py` sobre `.env` existente + comparação de hash | Preservou as credenciais existentes |
| `python -m compileall -q scripts` | Passou |
| `docker --config .\tmp\docker compose config --quiet` | Passou sem imprimir credenciais |
| `docker ... compose up -d --wait --wait-timeout 720` | Ambos os bancos healthy |
| `docker ... compose ps` / `inspect` / sockets Windows | 9042 e 5432 publicados em 127.0.0.1 e acessíveis; sem publicação em interfaces públicas |
| `cqlsh ... SELECT cluster_name, release_version FROM system.local` | CyberGuardLocal, Cassandra 5.0.9, uma linha real |
| `psql ... SELECT version()` e `SHOW shared_buffers` | PostgreSQL 17.11, shared_buffers 512MB |
| Argumentos JVM em `/proc/1/cmdline` | `-Xms2G`, `-Xmx2G`, `-XX:+UseG1GC` confirmados |
| Memória via Docker inspect | Cassandra 5.368.709.120 bytes; PostgreSQL 2.147.483.648 bytes |
| `npm.cmd --prefix frontend run build` | Passou: svelte-check sem erros/avisos, TypeScript e bundle Vite concluídos |
| Navegador 1440×1080 e 390×844 | Navegação das quatro áreas, estados vazios e ausência de overflow horizontal confirmados; navegação mobile quebra linha |
| Frontend com API desligada | Mostrou API indisponível e bancos não verificados; respostas HTTP 500 do proxy eram esperadas nesse cenário |
| `python scripts/validation/check_api.py` antes de iniciar API | Falha explícita por API inacessível; não contabilizada como teste aprovado |
| `cargo fmt`, `cargo fmt --check` e `cargo test` no contêiner Rust | Formatação aprovada; três testes passaram: CORS local explícito, erro/timeout sem falso sucesso e liveness independente dos bancos |
| `cargo build` no contêiner Rust | Passou; binário Linux gerado. Não equivale a uma compilação nativa Windows/MSVC |
| API temporária com publicação `127.0.0.1:3000:3000` | Iniciou com logs JSON, usando os serviços reais da rede Compose |
| `python scripts/validation/check_api.py` com API e bancos ativos | Passou: liveness 200, CORS permitido para origem local e rejeitado para origem externa, probes individuais reais com status up |
| Primeiro probe completo observado | Cassandra 204 ms, PostgreSQL 88 ms; somente diagnóstico de conexão, não benchmark |
| PostgreSQL parado temporariamente + requisições reais | Health básico continuou 200; storage retornou 503/degraded, Cassandra up e PostgreSQL down |
| Navegador durante falha real de PostgreSQL | API conectada, Cassandra conectado, PostgreSQL indisponível; sem sucesso fictício |
| PostgreSQL reiniciado e nova verificação | Healthy e ambos os probes up novamente; frontend recuperou sem reiniciar API |
| Frontend → proxy Vite → Axum → bancos | Confirmado no navegador; duas fontes conectadas, ausência de aviso de indisponibilidade e sem erros de JavaScript no estado saudável |

Os tempos de probes são diagnóstico de conectividade, não resultados experimentais. Não foram gerados registros de segurança nem números de dashboard.

Dependências Rust resolvidas no lockfile: Axum 0.8.9, Tokio 1.54.1, SQLx 0.8.6 e Scylla 1.10.0. A API foi testada em Linux dentro do Docker; Rust/Cargo nativos permanecem ausentes no Windows. O contêiner de compilação é removido automaticamente ao terminar. A API de validação e o preview Vite foram encerrados após os checks; Cassandra e PostgreSQL permanecem ativos, com volumes preservados. Consulte o README para voltar a iniciar a aplicação ou parar os bancos sem remover dados.

## NEXT

1. Definir evento lógico canônico, IDs e timestamps UTC, atributos, padrões de consulta e critérios de equivalência.
2. Modelar SQL e CQL com índices/chaves adequados, particionamento temporal dimensionado e justificativas; implementar CRUD equivalente em pequena amostra.
3. Definir gerador determinístico e manifesto, carga em lotes e validação; só então planejar 1 milhão de eventos (5 milhões condicionados a recursos).
4. Desenhar três experimentos honestos, controlar cache/aquecimento e recursos e registrar ao menos dez execuções por operação.

Rust/Cargo nativos continuam ausentes; a alternativa Docker está documentada no README. Instalação nativa futura é opcional para usar o fluxo com contêiner, mas necessária para compilar binários Windows diretamente. A Task 01 não comprova requisitos acadêmicos de CRUD, massa volumosa ou vantagem NoSQL.
