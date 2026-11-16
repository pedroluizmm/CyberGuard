# Task 02 - Modelagem SQL/CQL e CRUD equivalente

Data: 09/11/2026, America/Fortaleza. Fluxo READ → PLAN → APPLY → VERIFY. Nenhum commit ou push.

## READ

Foram revisados README, AGENTS, arquitetura, requisitos, relatório da Task 01, implementação Rust e arquivos de infraestrutura/banco. Os três PDFs não precisaram ser reextraídos: a matriz acadêmica já estava documentada, e sua integridade foi reconfirmada por SHA-256. Não foram modificados.

Estado inicial: monólito com dois healthchecks, frontend Svelte de conectividade, bancos Docker saudáveis e volumes existentes. PostgreSQL não tinha tabelas de aplicação; Cassandra não tinha o keyspace cyberguard. Rust/Cargo continuavam ausentes no Windows; a toolchain oficial Rust 1.99.1 via Docker foi reutilizada. Node/npm/Python existentes foram preservados. O repositório estava sem commits, com arquivos ainda não rastreados, conforme a Task 01.

`.env`, PDFs da raiz, `tmp/` e `.playwright-mcp/` foram conferidos como ignorados. A verificação de fundação também conferiu ausência da senha local entre arquivos versionáveis. Conteúdo bruto de `.env` não foi exibido.

A documentação da Task 01 dizia corretamente que CRUD e modelagem eram futuros; os documentos atuais e READMEs das áreas implementadas foram atualizados. O relatório histórico da Task 01 foi preservado.

## PLAN

- Contrato próprio inspirado em OCSF 1.3.0, sem alegar compatibilidade integral. Eventos de autenticação, rede e alertas; UUID v4, UTC em milissegundos, data de partição coerente, IP normalizado, enums e JSON limitado.
- Q1 dispositivo, Q2 IP e Q3 alertas com severidade exata; intervalo semiaberto, até sete datas UTC, page_size 1..100 e ordenação por timestamp/UUID descendentes.
- PostgreSQL: colunas tipadas, devices, reserva de UUID, PKs/FKs/CHECKs e três índices adequados; transações para mutações.
- Cassandra: conteúdo canônico por ID e três projeções de chaves imutáveis por dia. LWT para revisão/ciclo de vida, logged batches pequenos para projeções e recovery por ID. Mensagem/metadados não são duplicados entre projeções.
- Campos de roteamento imutáveis; outcome/message/metadata mutáveis com revisão esperada. UUID excluído não pode ser reutilizado.

## APPLY

| Área | Entrega |
| --- | --- |
| Modelagem | `docs/data-model.md`, diagramas Mermaid locais, contrato e exemplo; `docs/query-patterns.md`, SQL/CQL comentados e paginação; `docs/consistency.md`, estados e recuperação |
| SQL/CQL | `database/postgresql/001_events.sql` e `database/cassandra/001_events.cql`, aplicação aditiva/repetível via `scripts/apply_schema.py` |
| Domínio | `backend/src/domain/mod.rs`: validação, identidade, envelope/revisão e mutação idempotente |
| API | `backend/src/api/events.rs`: CREATE/READ/UPDATE/DELETE, consultas e repair; erros estruturados, deadline e limite de corpo |
| Persistência | `storage/postgresql.rs`, `storage/cassandra.rs`, `storage/repository.rs`: adaptadores separados, pool/sessão, prepared statements e concorrência |
| Consultas | `backend/src/analytics/mod.rs`: filtros, datas, cursor vinculado à consulta e paginação keyset |
| Amostra | `generate_sample.py`, `events.json`, manifesto e `load_sample.py`: 24 eventos determinísticos carregados igualmente |
| Verificação | `test_integration.py`, `test_recovery.py`, `check_sample.py`; regressão da fundação e dos healthchecks |
| Orientação | README, AGENTS, arquitetura, requisitos e READMEs dos módulos atualizados; Cargo.lock atualizado por Cargo |

Frontend, Compose, imagens/configurações dos bancos e `.env` foram preservados. Não foram adicionados serviços permanentes, autenticação fictícia, detecção avançada ou benchmarks.

## VERIFY

| Comando / cenário executado | Resultado real |
| --- | --- |
| `python scripts/apply_schema.py --docker-config tmp/docker` | SQL e CQL aplicados com sucesso nos volumes existentes |
| Repetição do comando de schemas | Passou; tabelas/dados preservados, sem recriação |
| Rust em `rust:1.99.1-slim-bookworm`: `cargo fmt --check` | Passou |
| `cargo test --locked --offline` na compilação final | **8 testes unitários passaram**, incluindo precisão temporal, segundos intercalares, IP/UUID, metadados, filtros/cursor, health, timeout e CORS |
| `cargo build --locked --offline` | Passou; binário Linux gerado e executado no contêiner de validação |
| `python scripts/validation/test_integration.py` na compilação final | **7 testes de integração HTTP passaram**, com seus subcasos em ambos os bancos |
| `python scripts/validation/test_recovery.py --docker-config tmp/docker` | CREATE pendente/projeção ausente recuperados; DELETE interrompido concluído; conteúdo, visibilidade e proibição de reutilizar UUID confirmados |
| `python scripts/generation/generate_sample.py`, repetido | Mesmos 24 eventos e manifesto; não sobrescreveu arquivos diferentes |
| `python scripts/loading/load_sample.py` | 24 eventos criados em cada banco |
| Repetição da carga da amostra | 0 novos / 24 idênticos reutilizados em cada banco |
| `python scripts/validation/check_sample.py --docker-config tmp/docker` | 24 IDs e conteúdos iguais ao arquivo em ambos; Q1=15, Q2=12 e Q3=6 resultados equivalentes nas consultas escolhidas |
| Projeções físicas da amostra, por IDs/partições limitados | **81 linhas ativas Cassandra**: 24 canônicas + 24 por dispositivo + 24 por IP + 9 alertas |
| `python scripts/validation/check_api.py` | Health básico 200, ambos os probes up e CORS local preservado |
| Preflight OPTIONS para PUT/Content-Type | Origem local permitida e métodos CRUD autorizados; a restrição de origem permanece |
| `npm.cmd --prefix frontend run build` | Passou, Svelte/TypeScript com zero erros/avisos; interface não remodelada |
| `python -m compileall -q scripts` | Passou |
| `python scripts/validation/check_foundation.py` | Todos os checks passaram: PDFs intactos/ignorados, segredos fora do Git, temporários e artefatos ignorados |
| `docker ... compose config --quiet` / `compose ps` | Configuração válida; Cassandra e PostgreSQL continuam healthy e publicados somente em localhost |
| Identidade dos volumes antes/depois | Preservada, conforme tabela abaixo |
| `git status --short` / `git diff --check` | Sem commits/push e sem erros reportados; PDFs e `.env` não aparecem entre os arquivos versionáveis |

Cobertura dos sete testes HTTP: leitura integral, CREATE idempotente/conflitante, Q1/Q2/Q3, IPv4/IPv6, paginação por vários dias, empates de timestamp, limites inclusivo/exclusivo, páginas vazias, IDs inexistentes, entrada inválida, cursor incompatível, PUT/retry/revisão antiga, rejeição de alteração de chave, DELETE/retry/não ressurreição, atualização visível nas três consultas e duas escritas simultâneas com uma vencedora. Os IDs temporários são excluídos individualmente pela API com verificação de propriedade; não há limpeza de tabelas.

Uma execução inicial do runner de integração revelou colisão do atributo auxiliar `run` com `unittest.TestCase.run`. Foi corrigido para `run_id`. Os 24 IDs sintéticos por banco daquela execução interrompida foram identificados pelo marcador exato da execução e excluídos individualmente pela API. A suíte passou a verificar previamente a janela reservada; a versão corrigida e a compilação final passaram integralmente. Essa falha inicial não foi contabilizada como teste aprovado.

Os cenários de recovery são injeções controladas de estado em um UUID novo, não testes de queda física, falha de disco ou cluster distribuído. As contagens acima são resultados de correção, não medições de desempenho.

### Volumes preservados

| Volume | CreatedAt observado antes e depois | Mountpoint |
| --- | --- | --- |
| `cyberguard_cassandra_data` | `2026-11-09T05:06:41Z` | `/var/lib/docker/volumes/cyberguard_cassandra_data/_data` |
| `cyberguard_postgresql_data` | `2026-11-09T05:06:41Z` | `/var/lib/docker/volumes/cyberguard_postgresql_data/_data` |

Não foram executados DROP, TRUNCATE, remoção de volumes, recriação dos bancos ou limpeza destrutiva. DELETEs dos testes atingiram somente eventos sintéticos próprios. A amostra versionada permanece ativa. Reservas de UUIDs excluídos e identidades de dispositivos de teste podem permanecer, conforme o contrato; não são contadas como eventos ativos.

## RISKS

- PostgreSQL tem transações; Cassandra não oferece a mesma atomicidade/isolamento entre suas tabelas. Estados duráveis e repair tornam falhas recuperáveis por ID, mas não existe reconciliador global automático.
- Payload canônico Cassandra exige leitura adicional para cada candidato. LWT, logged batches, registro de IDs e locks têm custo; não foi demonstrada vantagem de desempenho.
- Severidade/dia pode concentrar alertas em hot partitions. Dispositivo/IP muito ativo também exige monitoramento. Buckets/shards ficam condicionados a evidências da carga progressiva.
- UUIDs excluídos permanecem reservados; há crescimento de marcadores e tombstones. Campos de roteamento/severidade são imutáveis nesta versão.
- Paginação não é snapshot entre requisições. Múltiplas instâncias de escrita e writers diretos externos não foram certificados. O cenário validado é laboratório com uma instância de API e um nó Cassandra.
- Compilação/testes foram executados em Linux via Docker. Rust/Cargo nativos continuam ausentes; não foi executada compilação MSVC/Windows.

## NEXT - Task 03

1. Gerador em streaming, com seed/versionamento, manifesto de IDs/hashes, distribuições temporais e cenários realistas; reutilizar este contrato.
2. Carga progressiva em degraus, por exemplo 1 mil → 10 mil → 100 mil → 1 milhão, observando recursos antes de avançar. Cinco milhões continuam condicionados aos recursos; reduzir o mínimo escrito exige aprovação do professor.
3. Checkpoints, retries com os mesmos UUIDs, revisão de throughput/concorrência e reconciliação por ID de respostas incertas. Comparar contagens lógicas e amostras/hashes de conteúdo, não somente quantidade de linhas físicas.
4. Medir tamanho por partição Cassandra, índices/tabelas PostgreSQL, tempo de carga e uso de RAM/disco; avaliar bucket/shard/retention antes de volumes críticos.
5. Manter CRUD/consultas/recovery regressivamente testados; preparar protocolo honesto de três experimentos sem fabricar vantagem ou confundir carga/health com benchmark.

Instruções para iniciar a API nativa ou em contêiner estão no README. A API temporária de validação é encerrada ao finalizar esta tarefa; os bancos e a amostra permanecem ativos, com volumes intactos.
