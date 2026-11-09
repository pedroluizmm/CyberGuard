# CyberGuard - instruções do repositório

## Escopo e stack

Projeto acadêmico UNIFOR V3: comparar eventos de cibersegurança equivalentes em Apache Cassandra (wide-column) e PostgreSQL. Svelte 5 + TypeScript + Vite, sem SvelteKit; Rust + Axum + Tokio; SQLx e Scylla Rust Driver; scripts Python; Docker Compose local em Windows/WSL 2 com 16 GB de RAM.

## Fluxo e arquitetura

- Seguir READ → PLAN → APPLY → VERIFY; ler `docs/requirements.md` e `docs/architecture.md` antes de ampliar funcionalidades.
- Backend é monólito modular: API, domínio, storage, ingestão, analytics e benchmark. Não criar serviços ou bibliotecas visuais sem necessidade concreta.
- Manter consultas de negócio separadas do executor experimental. Conexões de saúde não são medições de benchmark.
- Áreas futuras têm documentação curta, não módulos fictícios. Fazer alterações incrementais e verificáveis.
- Svelte usa runes e eventos Svelte 5; TypeScript estrito. A interface deve distinguir carregamento, erro, não verificado e ausência de dados.
- Python deve trabalhar em streaming, com seed e manifesto explícitos na futura geração. Não gerar milhões de registros automaticamente.
- Task 02: ler também `docs/data-model.md`, `docs/query-patterns.md` e `docs/consistency.md`. UUID v4, timestamps UTC em milissegundos, campos de roteamento imutáveis e PUT com revisão esperada. Consultas tocam no máximo sete datas e páginas de até 100 eventos.
- Cassandra tem registro canônico por ID e projeções de chaves, sem `ALLOW FILTERING`. Respeitar estados pending/active/deleting/deleted e recuperação por ID; logged batch não equivale a transação SQL. Não reutilizar IDs excluídos.

## Preservação e verdade dos dados

- Não editar, mover ou excluir PDFs originais. Manter PDFs da raiz ignorados no Git; se rastreados, retirar somente do índice quando autorizado pela tarefa.
- Nunca fabricar métricas, eventos apresentados como reais ou conectividade positiva sem consulta bem-sucedida.
- Proibido manipular benchmarks por remoção arbitrária de índices, configurações inadequadas ou ocultação de resultados desfavoráveis. Registrar tempos brutos, no mínimo dez execuções por operação, cache/aquecimento, recursos e versões.
- Preservar o mínimo escrito de 1 milhão de eventos lógicos até aprovação explícita do professor para reduzir. A recomendação de 5 milhões é condicionada aos recursos.
- Um nó Cassandra não demonstra tolerância a falhas nem escalabilidade horizontal.

## Segurança e limites

- Trabalhar neste repositório. Sem mudanças globais no SO, commits ou push automáticos.
- Não imprimir `.env`, opções de conexão ou erros brutos que possam conter senha. Não versionar credenciais. Nunca expor segredos em `VITE_*`.
- Serviços locais em loopback; CORS em origem local explícita. Cassandra sem autenticação é exceção documentada apenas para laboratório.
- Não usar `docker compose down -v`, `volume rm`, `prune` ou comandos que removam dados. Não apagar volumes para resolver problemas de senha.
- Não ignorar genericamente JSON/SQL/CQL/CSV. Versionar modelos, amostras pequenas, resultados brutos pequenos e lockfiles reais.

## Verificação

- Rodar checks proporcionais: `cargo fmt --manifest-path backend/Cargo.toml --check`, `cargo test --manifest-path backend/Cargo.toml`, `cargo build --manifest-path backend/Cargo.toml`, `npm.cmd --prefix frontend run build`.
- Validar Compose com `docker compose config --quiet`, sem expor credenciais. Com daemon disponível, verificar ambos os healthchecks e endpoints reais.
- Rodar `python scripts/validation/check_foundation.py` e, com serviços ativos, `python scripts/validation/check_api.py`.
- Conferir frontend no navegador, estados de falha e responsividade quando houver preview disponível.
- Informar exatamente o que foi executado, o que falhou e o que ficou bloqueado. Não tratar revisão estática como compilação ou teste aprovado.
- Usar `npm.cmd` no PowerShell quando `.ps1` estiver bloqueado. Não mudar ExecutionPolicy global.
- Aplicar schemas com `python scripts/apply_schema.py`, sem DROP/TRUNCATE/recriação. Rodar `test_integration.py`, `test_recovery.py` e `check_sample.py` em `scripts/validation` quando mudar persistência/consultas. Os testes só podem atualizar/excluir IDs sintéticos próprios; preservar a amostra e os volumes.
