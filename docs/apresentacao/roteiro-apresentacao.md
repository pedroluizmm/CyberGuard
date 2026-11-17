# Roteiro da apresentação final (20 minutos)

- **Slides:** [CyberGuard_Apresentacao_Final.pdf](CyberGuard_Apresentacao_Final.pdf), 16 slides em 16:9. A fonte editável é [slides.html](slides.html): abra no navegador e use ← →; `F11` deixa em tela cheia.
- **Gerar o PDF de novo** depois de editar o HTML: `python docs/apresentacao/build_pdf.py`. O script usa Chrome ou Edge em modo headless e confere 16 páginas de 960 × 540 pt.
- **Tempo:** a divisão segue a sugestão do PDF do professor: cerca de 8 min de conceitos e comparação, 8 min de resultados e demonstração e 4 min de conclusões e perguntas.
- **Quem fala:** a divisão entre Pedro Luiz e Paulo Henrico é só uma sugestão; ajustem como preferirem. Cada integrante deve conseguir responder sobre qualquer parte.

## Linha do tempo

| Tempo | Slide | Quem (sugestão) |
| --- | --- | --- |
| 0:00–0:30 | 1 · Capa | Pedro |
| 0:30–1:20 | 2 · Introdução | Pedro |
| 1:20–2:20 | 3 · Problema | Pedro |
| 2:20–3:20 | 4 · Wide-column | Pedro |
| 3:20–4:20 | 5 · Arquitetura do Cassandra | Pedro |
| 4:20–5:00 | 6 · Escala, mercado e licença | Pedro |
| 5:00–6:00 | 7 · Cassandra × PostgreSQL | Paulo |
| 6:00–6:40 | 8 · Arquitetura do CyberGuard | Paulo |
| 6:40–7:40 | 9 · Modelagem | Paulo |
| 7:40–8:20 | 10 · Massa de dados | Paulo |
| 8:20–9:00 | 11 · Metodologia | Paulo |
| 9:00–10:00 | 12 · Resultados | Pedro |
| 10:00–11:00 | 13 · Análise crítica | Pedro |
| 11:00–17:00 | 14 · Dashboard e **demonstração ao vivo** ([roteiro-demo.md](roteiro-demo.md)) | Paulo (Pedro conduz o computador) |
| 17:00–18:30 | 15 · Conclusões | Pedro e Paulo |
| 18:30–20:00 | 16 · Encerramento e perguntas | Pedro e Paulo |

Se faltar tempo, encurte os slides 6, 8 e 11 e a investigação na demonstração. **Nunca corte** a comparação ao vivo do painel agregado: ela é o requisito R14.

## O que dizer em cada slide

**1 · Capa.** Apresente a equipe, o paradigma sorteado (orientado a colunas), o SGBD escolhido (Cassandra 5) e o relacional de comparação (PostgreSQL 17). Mesmo cenário, mesma massa, nos dois bancos.

**2 · Introdução.** O objetivo não é provar que "NoSQL é mais rápido", e sim descobrir **em quais consultas** cada paradigma vence e **por quê**. Os quatro blocos são o caminho da apresentação: pesquisa, implementação, experimentos e dashboard.

**3 · Problema.**
- Um SOC (centro de operações de segurança) recebe eventos o tempo todo e precisa investigá-los rapidamente.
- Q1, Q2 e Q3 são as perguntas de investigação; o painel é a visão agregada.
- **"Registro" é um evento lógico:** no Cassandra ele ocupa várias linhas físicas, mas conta como um.
- O cenário combina com wide-column porque é uma série temporal de escrita intensa, lida por chave e por janela de tempo.

**4 · Wide-column.**
- Explique com o exemplo: a partição é "dispositivo + dia". Dentro dela, as linhas já estão ordenadas por horário, e uma consulta lê uma fatia contígua.
- O exemplo é **ilustrativo**.
- Diga onde o modelo não serve: joins, consultas ad hoc e transações entre entidades.

**5 · Arquitetura do Cassandra.**
- Não existe nó mestre: qualquer nó coordena a requisição, e o hash da chave de partição decide quais nós guardam o dado.
- Com R + W > RF, a leitura enxerga a última escrita confirmada.
- No caminho de escrita, o dado vai para o commit log e para a memória e a resposta sai sem ler o dado anterior. Por isso a escrita é barata, e é o que torna a desnormalização viável.

**6 · Escala, mercado e licença.**
- Escalar é acrescentar nós.
- Os exemplos de mercado vêm de relatos públicos de engenharia, sem verificação independente do porte.
- A licença é Apache 2.0.
- **Deixe claro:** o projeto usa um único nó, então não demonstra escala nem tolerância a falhas.

**7 · Cassandra × PostgreSQL.** Percorra a tabela linha por linha, sem pressa nas três que mais importam para os resultados:
- **Transações:** ACID no PostgreSQL × LWT por partição no Cassandra.
- **Índices:** B-tree × chave primária como único índice.
- **Escrita:** fsync por commit × fsync periódico.

**8 · Arquitetura do CyberGuard.**
- Dashboard e scripts usam a **mesma API** em Rust.
- A fonte é escolhida no caminho (`/api/postgresql` ou `/api/cassandra`). Assim, a comparação usa o mesmo contrato e a mesma validação.
- A API mede o tempo do banco e o devolve no cabeçalho `Server-Timing`.

**9 · Modelagem.**
- **PostgreSQL:** uma tabela de eventos e um índice para cada pergunta, inclusive um índice de cobertura para o painel.
- **Cassandra:** uma tabela por pergunta, mais o registro canônico e a tabela de contadores do painel.
- **Decisão importante:** as projeções guardam só chaves, para que um UPDATE escreva uma única linha sem cópias divergentes. O custo dessa escolha aparece nos resultados de E1–E3.
- **CRUD:** transação no PostgreSQL e ciclo de vida com LWT no Cassandra.

**10 · Massa de dados.**
- A massa é gerada de forma determinística, com seed fixa, e sem arquivo intermediário.
- A validação integral compara conteúdo e IDs com o gerador, nos dois bancos.
- 3N + A: cada evento ocupa 3 linhas no Cassandra (canônico, dispositivo e IP), e cada alerta, uma quarta.
- A carga passou pela API em build de depuração, por isso **não é benchmark**.
- 5 M de eventos não foram tentados por falta de RAM; o mínimo escrito, 1 M, foi cumprido.

**11 · Metodologia.**
- **Medições:** 30 por operação (o PDF pede 10), com 5 aquecimentos descartados e pares intercalados, para que variações do ambiente afetem os dois bancos igualmente.
- **Resposta idêntica:** um resultado só é válido se a resposta for idêntica.
- **Nada contra o PostgreSQL:** nenhum índice foi removido, ele recebeu um índice novo e a SQL mais rápida entre três variantes.

**12 · Resultados.**
- Barras à esquerda: o PostgreSQL venceu as buscas por chave, de 1,2× a 4,0×.
- Barras à direita: o Cassandra venceu o painel, de 7,1× a 21,9×.
- Os números à direita são as medianas em ms.
- O mesmo vencedor aparece em 30 de 30 pares, em todas as operações.

**13 · Análise crítica.**
- **O 21,9× compara trabalhos diferentes:** o Cassandra lê cerca de 2,5 mil contadores prontos e o PostgreSQL agrega cerca de 245 mil entradas de índice. O ganho é da pré-agregação na escrita, que é idiomática no wide-column, e **não** da velocidade bruta do motor.
- **Controle E5:** com view materializada, o PostgreSQL lê em 1,15 ms, mas precisa de REFRESH completo.
- **Escritas:** a vantagem do Cassandra na configuração padrão vem do fsync periódico.

**14 · Dashboard.** Apresente as quatro seções em uma frase e passe para o navegador. Siga [roteiro-demo.md](roteiro-demo.md).

**15 · Conclusões.** Leia as quatro conclusões e feche com a frase final: escolher o banco pelo padrão de acesso, pela consistência e pelo crescimento, e não por "NoSQL é mais rápido".

**16 · Encerramento.** Agradeça e abra para perguntas. Lembre que código, modelos, scripts, resultados brutos e evidências da massa estão no repositório.

## Perguntas prováveis e respostas curtas

- **"O PostgreSQL não poderia pré-agregar também?"**
  - Sim, e isso foi medido no E5: a view materializada lê em 1,15 ms (psql), mas fica desatualizada, e cada REFRESH recalcula 1 M de eventos (282 ms).
  - O 21,9× mede a pré-agregação, não a velocidade bruta do motor.
  - Uma tabela-resumo mantida por gatilho seria incremental, mas tenderia a serializar escritas na linha da hora corrente. É uma **hipótese não medida**.
  - No Cassandra, a desnormalização na escrita é o modelo padrão e é barata.
- **"Por que o Cassandra perdeu nas consultas por chave?"**
  - A equipe escolheu não copiar o conteúdo mutável nas projeções, para evitar divergência em UPDATE. Isso custa uma leitura canônica por resultado.
  - Desnormalizar resolveria a leitura, mas multiplicaria o custo das escritas.
  - A otimização do N+1 deixou essas consultas de 4× a 6× mais rápidas, sem inverter o vencedor.
- **"A vantagem de escrita do Cassandra não é real?"**
  - Na configuração padrão ela existe: CREATE de 10,8 ms no Cassandra × 13,2 ms no PostgreSQL. Ela vem de confirmar antes do fsync (commitlog periódico).
  - Quando o PostgreSQL também confirma antes do fsync, ele vence: 5,8 ms × 9,5 ms. As janelas de perda continuam diferentes (≈ 0,6 s × ≈ 10 s).
  - O CREATE do Cassandra paga 2 LWT para garantir UUID único.
- **"E a escalabilidade?"** Não foi medida, porque o ambiente tem um nó. É a principal vantagem do Cassandra em produção e foi apresentada apenas na teoria.
- **"Os dados são iguais nos dois bancos?"**
  - Sim. A validação integral passou em 22/22 verificações (reexecutada em 17/11/2026).
  - O rollup é idêntico à agregação SQL, célula a célula.
  - Cada medição do benchmark compara o hash das respostas.
- **"O tempo mostrado no dashboard é o mesmo do benchmark?"**
  - Não. O dashboard mostra uma observação ao vivo no navegador (passando pelo proxy do Vite).
  - Os números oficiais estão nos arquivos de `benchmarks/results/`, medidos com o protocolo do slide 11.
  - O vencedor é o mesmo; a razão exata varia.
