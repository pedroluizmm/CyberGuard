# Por que o Cassandra respondeu mais rápido neste painel?

CyberGuard · UNIFOR V3 · roteiro de fala, cerca de 3 minutos

## 1. Abertura

“O CyberGuard é um projeto acadêmico para acompanhar eventos de cibersegurança, como logins bem-sucedidos, falhas de autenticação, conexões suspeitas e alertas. Entregamos um dashboard, consultas de investigação e benchmarks. Escolhemos Cassandra e PostgreSQL para comparar como dois modelos de dados respondem às mesmas perguntas sobre a mesma massa sintética.”

## 2. A pergunta vem antes da tabela

“Quantos eventos tivemos por hora em sete dias? No Cassandra, começamos por essa pergunta e desenhamos uma tabela para ela, a `event_counts_by_day`. Guardamos um contador para cada combinação de hora, categoria e severidade. Quando um evento é ativado, a API soma um. Quando a exclusão é concluída, subtrai um. Parte do cálculo acontece enquanto os dados mudam. Se uma falha deixar o contador fora de sincronia, o projeto tem uma rotina de reconciliação.”

## 3. Da tela até a partição

“O dashboard envia o período à API. No Cassandra, ela separa a janela em datas UTC e consulta em paralelo a partição de cada dia. Pense em sete gavetas, uma por data. `event_date` é a chave que agrupa os contadores do dia. O Cassandra calcula um token a partir dessa chave para localizar a partição. Lá dentro, a consulta limita as horas. A API aplica os filtros de categoria e severidade, se houver, soma os contadores e devolve a série ao dashboard.”

## 4. A mesma pergunta no PostgreSQL

“O PostgreSQL guarda os eventos em uma tabela relacional. No plano medido, o índice de cobertura localiza a faixa de tempo e fornece o instante do evento, a categoria e a severidade. O SQL aplica os filtros, agrupa por hora, categoria e severidade e conta os eventos naquele momento. No E4 de sete dias, isso envolveu cerca de 245 mil entradas de índice. O Cassandra leu sete partições de até 360 contadores cada. A mediana HTTP foi cerca de 22 vezes menor: 3,28 ms contra 71,94 ms, com respostas iguais nos 30 pares medidos.”

## 5. Onde cada desenho vale a pena

“O PostgreSQL venceu as buscas por ID e as páginas por dispositivo, IP e alertas. Nas consultas paginadas, o Cassandra ainda consulta o registro completo de cada resultado. O PostgreSQL também dá mais flexibilidade para perguntas novas, joins e transações. No controle E5, a leitura de uma view materializada no PostgreSQL ficou na mesma ordem de grandeza do rollup, com medições de escopos diferentes e dados atualizados no último refresh.”

“O Cassandra combina bem com consultas previsíveis por chave e pode atender a grandes volumes e escrita intensa em um cluster bem dimensionado. Perguntas ad hoc e cruzamentos entre tabelas tendem a exigir novas projeções ou processamento externo. O nosso laboratório usou um nó Cassandra, então a escala horizontal fica como característica da arquitetura.”

## 6. Encerramento

“Neste painel, o Cassandra respondeu mais rápido porque tínhamos previsto a pergunta, escolhido a chave para localizar os dias e adiantado a contagem para a escrita. Esse desenho vale quando a pergunta é conhecida e se repete.”

**Na tela.** Abra **Comparação → Painel agregado** e selecione **26/10 a 01/11/2026**, com todas as categorias e severidades. Aponte o resultado equivalente, depois mostre **Q1 dispositivo** como contraponto. Use os tempos registrados do E4 como referência.

**Fontes.** [Modelagem](../data-model.md) · [Consultas e código SQL/CQL](../query-patterns.md#painel-agregado-task-04) · [Metodologia E4/E5](../benchmark-methodology.md#resultados-leituras-e1e3-e-painel-e4) · [CSV bruto do E4](../../benchmarks/results/20261115T053008Z-main/raw.csv) · [Apache Cassandra](https://cassandra.apache.org/doc/stable/cassandra/architecture/dynamo) · [PostgreSQL 17](https://www.postgresql.org/docs/17/using-explain.html)
