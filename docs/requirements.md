# Requisitos acadêmicos - V3

## Fontes e interpretação

Leitura integral dos PDFs originais na raiz, preservados e ignorados no Git:

- `entregáveis.pdf`, página única: cronograma e penalidades por entregável.
- `Equipe - Página1.pdf`, página única: associação de equipes aos paradigmas; código 1 = orientado a colunas (wide-column). A tabela lista Paulo Henrico/Pedro Luiz, Kauê/João Guilherme e Raquel/João Igor no paradigma 1. Não inferir a identidade da equipe apenas pelo nome do usuário do sistema.
- `Projeto_3_NoSQL_Instrucoes_Atualizadas.pdf`, páginas 1 a 3: requisitos teóricos, práticos e avaliação. As datas antigas do documento 24.1 não são reutilizadas; adotar o cronograma do PDF de entregáveis fornecido.

Escolha definida para CyberGuard: cenário de eventos de cibersegurança; Cassandra (wide-column) e PostgreSQL. O PDF prevê validação da escolha de SGBD pelo professor; a aprovação específica não está comprovada pelos documentos.

## Cronograma

O PDF traz dia/mês sem ano. No planejamento atual, usar novembro/2026 (contexto desta tarefa), confirmando com a turma se necessário.

| Data | Exigência do PDF de entregáveis |
| --- | --- |
| 10/11 | Descrição e características do paradigma; tipos de aplicação; visão geral e arquitetura do SGBD; escalabilidade; aplicações reais no mercado |
| 17/11 | Principais vantagens e desvantagens; definição do problema e modelagem relacional e não relacional |
| 19/11 | Massa volumosa, carga e documentação dos dados |
| 24/11 | Experimentos válidos com vantagem NoSQL; dashboard funcional com consultas reais, filtros e comparação de tempos |

Cada entregável ausente implica penalidade de 1 ponto. Entregas progressivas têm apresentação de progresso por integrante. O projeto vale 40% da nota da disciplina e a apresentação final tem 20 minutos por equipe.

## Matriz de requisitos

| ID | Requisito | Fonte | Situação final (Task 04) e evidência |
| --- | --- | --- | --- |
| R01 | Paradigma, aplicações adequadas, arquitetura, organização, consultas, escalabilidade, exemplos de mercado, fornecedor/download e licença | Instruções p. 1, §3 | Atendido: [entregas/10-11-pesquisa-cassandra.md](entregas/10-11-pesquisa-cassandra.md) e slides |
| R02 | Comparar modelos, relações, SQL/CQL, consistência/transações, índices, escalabilidade e cenários; vantagens e limitações | Instruções p. 1, §3 | Atendido: [entregas/17-11-vantagens-problema-modelagem.md](entregas/17-11-vantagens-problema-modelagem.md) |
| R03 | Diagramas/modelos dos dois bancos, justificativa das diferenças, CRUD equivalente | Instruções pp. 1-2, §4 | Atendido: [data-model.md](data-model.md); CRUD testado em `test_integration.py` (10 testes) |
| R04 | Mesmo conjunto lógico, integridade e equivalência semântica | Instruções p. 2, §§4-5 | Atendido: `check_bulk.py` 22/22 em 1 M; rollup × agregação PostgreSQL iguais célula a célula; benchmarks com resposta idêntica em 9/9 operações |
| R05 | Instalação, geração/carga e execução automatizáveis | Instruções p. 2, §4 | Atendido: `setup_env.py`, Compose, `apply_schema.py`, `run_api.py`, `generate_bulk.py`, `load_bulk.py`, `reconcile_rollup.py` |
| R06 | Mínimo de 1.000.000 registros lógicos; 5.000.000+ recomendados quando houver recursos | Instruções p. 2, §5 | 1 M atendido nos dois bancos. 5 M não tentado por limite de RAM do host (justificado em [verification-task03.md](verification/verification-task03.md)) |
| R07 | Documentar significado de registro, origem/geração, quantidade, tamanho, esquema e tempo de carga | Instruções p. 2, §5 | Atendido: [bulk-load.md](bulk-load.md), [entregas/19-11-massa-carga-dados.md](entregas/19-11-massa-carga-dados.md), relatórios em `data/bulk/reports/` |
| R08 | Pelo menos três consultas/operações comparáveis, incluindo cenário realista favorável ao NoSQL | Instruções p. 2, §6 | Atendido com ressalva: E1–E6; E4 (painel) com rollup Cassandra de 7,1× a 21,9× mais rápido que a agregação na leitura do PostgreSQL, ganho da pré-agregação na escrita ([benchmark-methodology.md](benchmark-methodology.md)) |
| R09 | Cada operação ao menos dez vezes; tempos brutos e comparação de medianas | Instruções p. 2, §6 | Atendido: 30 medições + 5 aquecimentos por operação e banco; `raw.csv` por requisição |
| R10 | Hardware, versões, índices, massa, filtros, método de medição e cache/aquecimento | Instruções p. 2, §6 | Atendido: `environment.json` por execução e seção de ambiente da metodologia |
| R11 | Métricas lado a lado, explicação técnica, casos favoráveis ao relacional | Instruções p. 2, §6 | Atendido: E1–E3 e E6 com confirmação antes do fsync nos dois bancos favorecem o PostgreSQL; controle E5 (view materializada) documentado |
| R12 | Dashboard com dados reais, três ou mais indicadores/visualizações e dois ou mais filtros que executem novas consultas | Instruções p. 2, §7 | Atendido: 4 indicadores, série horária, severidade e categorias; filtros de período, categoria e severidade e consultas Q1–Q3 |
| R13 | Alternância relacional/NoSQL com equivalência, tempos em ms e visualização comparativa | Instruções p. 2, §7 | Atendido: seletor de fonte, tempo de banco e HTTP, comparação ao vivo com verificação de resultado idêntico, painel de benchmarks |
| R14 | Demonstrar ao vivo uma consulta do dashboard que evidencie o ganho NoSQL | Instruções pp. 2-3, §§7,10 | Atendido: "Comparação ao vivo · Painel agregado" ([apresentacao/roteiro-demo.md](apresentacao/roteiro-demo.md)) |
| R15 | Slides, código, README, modelos, scripts de criação/carga, consultas e índices, resultados brutos/planilha e evidência da massa | Instruções p. 3, §8 | Atendido: [apresentacao/CyberGuard_Apresentacao_Final.pdf](apresentacao/CyberGuard_Apresentacao_Final.pdf) (fonte: [slides.html](apresentacao/slides.html)), README, `database/`, `scripts/`, `benchmarks/results/`, `data/bulk/reports/` |

Explicar as consultas **SQL e CQL** usadas nos experimentos e no dashboard: parâmetros, índices/chaves, significado do resultado, consistência e justificativa da modelagem. Essa documentação concretiza a comparação de linguagens e a explicação técnica exigidas, não apenas a exposição dos tempos.

### Volume: escrito versus orientação oral

O documento escrito exige **no mínimo 1 milhão de registros lógicos** e recomenda **5 milhões ou mais quando houver recursos**. A orientação oral relatada pelo usuário dispensa perseguir obrigatoriamente 5 milhões; não dispensa automaticamente o mínimo escrito. Qualquer redução abaixo de 1 milhão exige aprovação prévia do professor, conforme §5. Não há evidência dessa aprovação nesta tarefa.

### Integridade experimental

Não fabricar medições, retirar índices arbitrariamente ou configurar mal o concorrente. Se não houver vantagem NoSQL, registrar o resultado, investigar e refinar justificadamente o cenário. Os limites de RAM diferentes solicitados nesta tarefa são configuração de partida e deverão constar do protocolo; não presumir igualdade de recursos ou neutralidade desse fator. Definir comparação com recursos controlados na etapa experimental.

## Avaliação

| Critério | Pontos |
| --- | ---: |
| Pesquisa | 1,0 |
| Comparação técnica | 1,5 |
| Modelagem, implementação e CRUD | 1,0 |
| Massa volumosa, carga e documentação | 1,0 |
| Experimentos válidos e vantagem NoSQL | 2,0 |
| Dashboard real, filtros e tempos | 2,5 |
| Apresentação, demonstração e justificativa | 1,0 |
| Total | 10,0 |

Sugestão do PDF para os 20 minutos finais: 8 minutos de conceitos/comparação, 8 de demonstração e 4 de conclusões/perguntas. A distribuição sugerida está em [apresentacao/roteiro-apresentacao.md](apresentacao/roteiro-apresentacao.md).
