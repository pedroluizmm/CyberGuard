# 24/11: experimentos, dashboard e resultados

A metodologia completa, as tabelas e as ameaças à validade estão em [../benchmark-methodology.md](../benchmark-methodology.md). Os dados brutos ficam em `benchmarks/results/`.

## Experimentos

São 6 experimentos, com **30 medições + 5 aquecimentos** por operação e por banco. As requisições são idênticas, em pares intercalados com ordem alternada, com cache quente e API em build release.

| Exp. | Operação | Mediana PostgreSQL | Mediana Cassandra | Resultado |
| --- | --- | --- | --- | --- |
| E1 | READ por UUID | 1,19 ms | 1,41 ms | PG 1,2× (30/30 pares) |
| E2 | Q1 dispositivo, página de 100 / 10 páginas / dispositivo pouco ativo | 3,9 / 34,2 / 2,7 ms | 7,3 / 85,6 / 10,8 ms | PG 1,9× / 2,5× / 4,0× |
| E3 | Q2 IP / Q3 alertas, página de 100 | 3,7 / 3,6 ms | 9,9 / 7,3 ms | PG 2,7× / 2,0× |
| **E4** | **Painel 7 dias / 1 dia / 7 dias só alertas** | 71,9 / 15,6 / 45,5 ms | **3,3 / 2,2 / 3,5 ms** | **Cassandra 21,9× / 7,1× / 12,9× (30/30)** |
| E5 | Controle: view materializada no PG (leitura / REFRESH) | 1,15 ms / 282 ms (psql) | rollup 1,79 ms (driver) | Pré-agregado, o PG lê na mesma ordem de grandeza, mas precisa de REFRESH completo |
| E6 | CRUD concorrente (8 clientes, pool PG 16, 2 rodadas de aquecimento), CREATE padrão / ambos confirmando antes do fsync | 13,2 / 5,8 ms | 10,8 / 9,5 ms | Inverte: a vantagem padrão do CS é explicada pela política de `fsync` |

Em todas as 9 operações de leitura, o corpo da resposta foi **idêntico nos dois bancos**, verificado por hash a cada par.

## Cenário favorável ao NoSQL (exigido)

**Painel do SOC: eventos por hora, categoria e severidade em um período.**

| | PostgreSQL | Cassandra |
| --- | --- | --- |
| Modelagem | Normalizado, agrega na leitura com índice de cobertura (*index-only scan*) | Tabela modelada para a consulta (`event_counts_by_day`), pré-agregada na escrita com contadores |
| Trabalho por leitura (7 dias) | Cerca de 245 mil entradas de índice | 7 partições com até 360 células cada |
| Crescimento do custo | Com o número de eventos do período | Com o número de dias |

O ganho se deve à modelagem orientada a consultas e à escrita barata que torna viável desnormalizar. Não houve índice removido nem concorrente mal configurado. A consulta SQL usada foi a mais rápida de três variantes medidas, e o PostgreSQL recebeu `VACUUM ANALYZE` e um índice novo adequado.

**Limite honesto (E5):** uma view materializada daria ao PostgreSQL leitura na mesma ordem de grandeza. O 21,9× mede a pré-agregação, não velocidade bruta do motor. O custo seria um dado desatualizado entre REFRESHes completos, de 282 ms cada, que crescem com a tabela. A alternativa por gatilho concentraria escritas na linha da hora corrente.

## Onde o relacional vence (e por quê)

- **E1–E3:** o índice B-tree devolve a página completa em uma consulta. No Cassandra, as projeções têm só chaves, e o conteúdo vem do registro canônico, que é 1 leitura por resultado. Essa escolha evita cópias divergentes em UPDATE.
- **A otimização do N+1** (leituras canônicas concorrentes) reduziu as páginas do Cassandra de 26–43 ms para 7–11 ms, sem mudar resultados. Ela não inverte o vencedor.
- **E6 com confirmação antes do fsync nos dois bancos** (janelas de perda diferentes: PG ≈ 0,6 s, CS ≈ 10 s): o CREATE Cassandra paga 2 LWT (Paxos), um batch e o contador do rollup pela garantia de UUID único e ciclo de vida; o PostgreSQL obtém o mesmo com PK e transação.

## Dashboard (requisitos do §7)

| Requisito | Implementação |
| --- | --- |
| Três ou mais indicadores/visualizações | Eventos no período (número de destaque), alertas, severidade crítica, tempo de resposta; série horária por categoria; distribuição por severidade; participação por categoria; tabela por dia |
| Dois ou mais filtros que executam novas consultas | Período (6 atalhos + data inicial + 1 a 7 dias), categoria, severidade; investigação Q1/Q2/Q3 por dispositivo, IP ou severidade, com paginação por cursor |
| Alternar relacional/NoSQL | Seletor PostgreSQL ou Cassandra, que refaz todas as consultas na fonte escolhida |
| Tempo em ms e comparação visual | Tempo no banco (`Server-Timing`) e HTTP (navegador) em cada consulta; "Comparação ao vivo" com N execuções intercaladas, barras, pontos por execução e verificação de resultado idêntico; aba Benchmarks com medianas, IQR, pares vencidos, N+1, E5 e E6 |
| Dados reais | Toda visualização vem de consulta à API. Os benchmarks vêm de `summary.json` medido. Sem dados fixos ou simulados |
| Estados | Carregando (mantém a tela anterior esmaecida), vazio, erro de filtro, banco indisponível (banner e indicador de saúde) e API inacessível, todos testados parando a API e cada banco |
| Demonstração do ganho NoSQL | "Comparação ao vivo · Painel agregado" com os filtros atuais |

## Limitações

- **Um nó Cassandra:** a escalabilidade horizontal e a tolerância a falhas não foram demonstradas.
- **Massa sintética** de 1 M de eventos (o recomendado era 5 M).
- **Somente cache quente.**
- **Recursos assimétricos e compartilhados** na mesma máquina.
- **Rollup baseado em contadores não idempotentes,** dependente de reconciliação após falhas parciais.

Detalhes em [../benchmark-methodology.md](../benchmark-methodology.md#limitações-e-ameaças-à-validade).

## Apresentação

Os slides estão em [../apresentacao/slides.html](../apresentacao/slides.html), o roteiro de 20 minutos em [../apresentacao/roteiro-apresentacao.md](../apresentacao/roteiro-apresentacao.md) e a demonstração ao vivo em [../apresentacao/roteiro-demo.md](../apresentacao/roteiro-demo.md).
