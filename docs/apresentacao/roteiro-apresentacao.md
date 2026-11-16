# Roteiro da apresentação final (20 minutos)

Slides: [slides.html](slides.html). Abra no navegador e use ← → para navegar, `F11` para tela cheia, e `Ctrl+P` → "Salvar como PDF" para exportar, com margens "Nenhuma" e gráficos de fundo ativados. A divisão segue a sugestão do PDF: 8 min de conceitos, 8 min de demonstração e 4 min de conclusões e perguntas.

| Tempo | Slide | Fala principal (o que precisa ficar claro) |
| --- | --- | --- |
| 0:00–0:40 | 1 · Título | Paradigma sorteado (wide-column), o SGBD (Cassandra 5) e o relacional de comparação (PostgreSQL 17). Mesmo cenário, mesma massa |
| 0:40–2:00 | 2 · Problema | O SOC e as perguntas Q1/Q2/Q3 e o painel. "Registro" = evento lógico com UUID. Por que o cenário combina com wide-column: série temporal, escrita intensa, acesso por chave e janela de tempo |
| 2:00–3:20 | 3 · Paradigma | Partição + clustering: os dados ficam ordenados no disco por chave e tempo. Origem no Bigtable (modelo e LSM) e no Dynamo (anel e replicação). Onde serve e onde não serve |
| 3:20–4:40 | 4 · Arquitetura | Anel sem mestre, token por hash, replicação por keyspace, consistência ajustável (R + W > RF), LWT por partição. Caminho de escrita LSM: por que escrever é barato |
| 4:40–5:40 | 5 · Escala e mercado | Escala horizontal linear e multi-datacenter; usuários conhecidos; licença Apache 2.0. **Avisar que um nó não demonstra escala** |
| 5:40–6:50 | 6 · Comparação | Tabela relacional × wide-column: relações, linguagem, transações, índices, escrita, escala |
| 6:50–8:00 | 7 · Modelagem | Normalizado + índices × uma tabela por consulta + registro canônico + rollup. Por que as projeções só guardam chaves (UPDATE em 1 linha) |
| 8:00–8:40 | 8 · Massa | 1 M determinístico, 22/22 verificações, `3N + A`, rollup idêntico ao PostgreSQL. A carga via API não é benchmark |
| 8:40–9:20 | 9 · Metodologia | 30 medições + 5 aquecimentos, pares intercalados, duas fronteiras de tempo, resultado idêntico exigido, PostgreSQL bem configurado |
| 9:20–15:30 | 14 · **Demonstração ao vivo** | Seguir [roteiro-demo.md](roteiro-demo.md): visão geral, troca de fonte, filtros, comparação ao vivo do painel (ganho NoSQL), comparação Q1 (ganho relacional), investigação e aba Benchmarks |
| 15:30–16:20 | 10 · Leituras | O PostgreSQL vence buscas por chave (1,2× a 4×): B-tree com linha completa × leitura canônica por resultado |
| 16:20–17:10 | 11 · Cenário NoSQL | Painel de 7× a 22× mais rápido no Cassandra: pré-agregação na escrita × agregação na leitura. Deixar claro que mede a pré-agregação, não velocidade bruta. Nada foi feito para prejudicar o PostgreSQL |
| 17:10–17:50 | 12 · Limites | E5: com view materializada, o PostgreSQL lê na mesma ordem de grandeza, mas precisa de REFRESH. E6: a vantagem de escrita do Cassandra é explicada pela política de fsync |
| 17:50–18:20 | 13 · N+1 | Investigação: de 5× a 6× mais rápido sem mudar resultados, mas sem inverter o vencedor |
| 18:20–20:00 | 15 · Conclusões | Cada paradigma vence na pergunta para a qual foi modelado; limitações; perguntas |

Se a demonstração precisar ser encurtada, mantenha obrigatoriamente o passo "Comparação ao vivo · Painel agregado", que é o requisito R14.

## Perguntas prováveis e respostas curtas

- **"O PostgreSQL não poderia pré-agregar também?"** Sim, e medimos isso (E5): a view materializada lê em 1,15 ms (psql), mas fica desatualizada e cada REFRESH recalcula 1 M de eventos (282 ms). O 21,9× mede a pré-agregação, não velocidade bruta do motor. Uma tabela-resumo por gatilho seria incremental, mas tenderia a serializar escritas na linha da hora corrente (hipótese, não medida). No Cassandra, a desnormalização na escrita é o modelo padrão e é barata.
- **"Por que o Cassandra perdeu nas consultas por chave?"** Escolhemos não copiar o conteúdo mutável nas projeções, para evitar divergência em UPDATE. Isso custa uma leitura canônica por resultado. Desnormalizar resolveria a leitura, mas multiplicaria o custo das escritas.
- **"A vantagem de escrita do Cassandra não é real?"** Na configuração padrão ela existe (CREATE 10,8 × 13,2 ms), mas vem de confirmar antes do fsync (commitlog periódico). Quando o PostgreSQL também confirma antes do fsync, ele vence (5,8 × 9,5 ms); as janelas de perda continuam diferentes (≈ 0,6 s × ≈ 10 s). Nosso CREATE paga 2 LWT para garantir UUID único. Na auditoria, corrigimos o pool PostgreSQL (5 → 16 conexões para 8 clientes) e o aquecimento; a conclusão se manteve.
- **"E a escalabilidade?"** Não foi medida: temos um nó. É a principal vantagem do Cassandra em produção, e a apresentamos apenas na teoria.
- **"Os dados são iguais nos dois bancos?"** Sim: validação integral 22/22, rollup idêntico à agregação SQL célula a célula, e cada medição do benchmark compara o hash da resposta.
