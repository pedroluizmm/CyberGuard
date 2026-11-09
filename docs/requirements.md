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

| ID | Requisito | Fonte | Situação após Task 02 |
| --- | --- | --- | --- |
| R01 | Paradigma, aplicações adequadas, arquitetura, organização, consultas, escalabilidade, exemplos de mercado, fornecedor/download e licença | Instruções p. 1, §3 | Pesquisa aprofundada pendente |
| R02 | Comparar modelos, relações, SQL/CQL, consistência/transações, índices, escalabilidade e cenários; vantagens e limitações | Instruções p. 1, §3 | Direção arquitetural definida; comparação pendente |
| R03 | Diagramas/modelos dos dois bancos, justificativa das diferenças, CRUD equivalente | Instruções pp. 1-2, §4 | Implementados na Task 02; modelos em data-model.md e testes reais de CRUD/consultas |
| R04 | Mesmo conjunto lógico, integridade e equivalência semântica, apesar de diferenças físicas | Instruções p. 2, §§4-5 | Comprovado na amostra de 24 eventos e em testes; validação volumosa pendente |
| R05 | Instalação, geração/carga e execução automatizáveis | Instruções p. 2, §4 | Bootstrap, schemas e geração/carga idempotente da amostra; bulk pendente |
| R06 | Mínimo de 1.000.000 registros lógicos; 5.000.000+ recomendados quando houver recursos | Instruções p. 2, §5 | Nenhuma massa definitiva gerada |
| R07 | Documentar significado de registro, origem/geração, quantidade, tamanho, esquema e tempo de carga | Instruções p. 2, §5 | Contrato, origem sintética, contagens e hash da amostra documentados; tamanho/tempo de carga volumosa pendentes |
| R08 | Pelo menos três consultas/operações comparáveis, incluindo cenário realista favorável ao NoSQL | Instruções p. 2, §6 | Não executado |
| R09 | Cada operação ao menos dez vezes; tempos brutos e comparação preferencial de medianas | Instruções p. 2, §6 | Não executado |
| R10 | Hardware, versões, índices, massa, filtros, método de medição e cache/aquecimento documentados | Instruções p. 2, §6 | Protocolo futuro obrigatório |
| R11 | Métricas lado a lado, explicação técnica e reconhecimento de casos favoráveis ao relacional | Instruções p. 2, §6 | Sem métricas nesta etapa |
| R12 | Dashboard consultando dados reais com pelo menos três indicadores/visualizações e dois filtros que executem novas consultas | Instruções p. 2, §7 | Apenas interface de fundação |
| R13 | Alternância relacional/NoSQL com equivalência de negócio, tempos em ms e visualização comparativa | Instruções p. 2, §7 | Pendente |
| R14 | Demonstrar ao vivo consulta do dashboard evidenciando ganho NoSQL identificado no experimento | Instruções pp. 2-3, §§7,10 | Pendente |
| R15 | Slides, código, README, modelos, scripts de criação/carga, consultas e índices, resultados brutos/planilha e evidência da massa | Instruções p. 3, §8 | Apenas fundação e documentação inicial |

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

Sugestão do PDF para os 20 minutos finais: 8 minutos de conceitos/comparação, 8 de demonstração e 4 de conclusões/perguntas. A Task 01 não deve ser apresentada como conclusão dos requisitos de CRUD, massa, experimentos ou dashboard definitivo.
