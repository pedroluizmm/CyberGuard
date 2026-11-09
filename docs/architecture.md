# Arquitetura - Tasks 01 e 02

## Decisão

Monólito modular Rust/Axum/Tokio, frontend Svelte 5 independente e scripts Python de engenharia de dados. Dois bancos locais são fontes alternativas para o mesmo domínio, não serviços com modelos de negócio divergentes. A Task 01 implementou saúde/conectividade; a Task 02 acrescenta contrato canônico, esquemas, CRUD equivalente e três consultas limitadas.

| Módulo | Responsabilidade e estado |
| --- | --- |
| `backend/src/api` | Health, CRUD, Q1/Q2/Q3 e repair; limites de corpo/deadline, erros sanitizados e CORS |
| `backend/src/config.rs` | Variáveis de ambiente validadas, limites de timeout e credenciais não logadas |
| `backend/src/storage` | Health preservado; repositories comuns, adaptadores PostgreSQL/Cassandra, pool/sessão, transações/LWT |
| `backend/src/domain` | Evento canônico, validação, identidade imutável e atualização com revisão |
| `backend/src/ingestion` | Futuro fluxo de entrada idempotente, validação e coordenação das escritas |
| `backend/src/analytics` | Contrato Q1/Q2/Q3, janela UTC de sete datas, paginação keyset e cursores vinculados ao filtro |
| `backend/src/benchmark` | Futuro executor de experimentos com protocolo explícito |
| `scripts/generation` | Amostra determinística de 24 eventos e manifesto; massa volumosa futura |
| `scripts/loading` | Carga idempotente da amostra nos dois bancos via API; bulk futuro |
| `scripts/validation` | Fundação, health, CRUD/consultas reais, equivalência, concorrência, recovery e projeções da amostra |

Áreas futuras contêm README curto, sem módulos Rust fictícios, structs especulativas ou implementações vazias.

## Fluxo de dados

Saúde: navegador → Vite (proxy `/api`) → API → dois probes concorrentes. PostgreSQL executa `SELECT 1`; Cassandra executa `SELECT cluster_name FROM system.local` e valida uma linha. Um timeout engloba conexão e consulta de cada probe. O retorno agregado é degradado se qualquer fonte falhar; um erro não oculta o resultado da outra fonte. O health básico é independente dos bancos.

As conexões de health continuam efêmeras para permitir recuperação após os bancos iniciarem, sem impedir o boot da API. Seu custo **não pode ser usado como comparação SQL versus CQL**. Operações de eventos usam pool SQLx de cinco conexões e sessão Cassandra reutilizável criada sob demanda, com 32 prepared statements em cache. Locks locais limitados por faixa de UUID, transações PostgreSQL e LWT Cassandra coordenam mutações. Não há cache de resultados nem scheduler de reconciliação global.

Eventos: cliente/carregador → API `/api/{source}` → validação de domínio → repositório da fonte selecionada → banco. Cada chamada seleciona somente um banco. A amostra é enviada com os mesmos IDs e conteúdos para ambos; a equivalência é verificada após a carga. Cassandra mantém conteúdo por ID e projeções imutáveis; PostgreSQL mantém colunas tipadas, reserva de UUID, dispositivos e índices. Detalhes em `data-model.md`, `query-patterns.md` e `consistency.md`.

Task 03: gerador Python determinístico em streaming → manifesto (sem arquivo de eventos) → carregador com checkpoint via CREATE da API → representações físicas SQL/CQL → validação integral de cardinalidade, IDs, conteúdo e projeções ([bulk-load.md](bulk-load.md)). Futuro: benchmarks (Task 04) → dashboard. Não se contam projeções Cassandra ou marcadores de UUID excluído como eventos lógicos adicionais. A Task 02 já define esquema e IDs; Task 03 deve escalar a geração/carga e reconciliar respostas incertas por ID.

## Consultas de negócio e experimentos

`analytics` responderá perguntas de segurança. `benchmark` controlará repetições, parâmetros, aquecimento, cache, ordenação das execuções e persistência de tempos brutos. Ambos usarão contratos de domínio/persistência equivalentes, mas os tempos de renderização do navegador e os probes de saúde não substituirão a medição das operações.

Medir com relógio monotônico; registrar o limite medido (cliente, driver ou banco), hardware, versões, filtros, índices, volumes, consistência e concorrência. Preservar resultados negativos e cenários favoráveis ao relacional. Não desativar índices ou prejudicar um banco para obter vantagem. Não automatizar limpeza de caches/volumes destrutiva.

## Um nó Cassandra

Um nó economiza recursos no computador de 16 GB e permite avaliar modelo e consultas locais. Não demonstra escalabilidade horizontal, tolerância a falhas nem comportamento real de quorum distribuído. O modelo usa `NetworkTopologyStrategy` com `datacenter1: 1`, leituras/escritas `LOCAL_QUORUM` e condições `LOCAL_SERIAL`. Sem réplicas adicionais, não há redundância. A distribuição/replicação deve ser explicada teoricamente, sem extrapolar resultados de um único nó para um cluster.

## Limites locais

O Compose mantém apenas Cassandra e PostgreSQL em rede bridge dedicada, volumes persistentes e portas loopback. Não se usa `internal: true`: no Engine 29 disponível, isso suprimiu a publicação de portas e impediu a API do host de alcançar os bancos; o teste de sockets reais detectou o problema. A bridge dedicada mantém a separação entre redes Docker e permite saída; o acesso de entrada é restrito por `127.0.0.1` nas publicações.

Svelte e Rust normalmente rodam no host. Um contêiner temporário de toolchain pode compilar/testar Rust sem instalação global; também pode executar a API para validação, com `API_BIND=0.0.0.0:3000` dentro do contêiner e publicação `127.0.0.1:3000:3000`. Essa adaptação não adiciona serviço permanente ao Compose. PostgreSQL tem senha; Cassandra usa autenticação simplificada sem credenciais, somente local. Não há Kafka, Redis, Elasticsearch, Kubernetes ou publicação externa.
