# Roteiro da demonstração ao vivo (cerca de 6 min)

## Antes da aula (10 a 15 min antes)

Use PowerShell na raiz do repositório e feche programas pesados: a máquina tem 16 GB e o Cassandra usa cerca de 3 GB.

```powershell
docker compose up -d --wait --wait-timeout 720      # bancos (Cassandra pode levar 1-3 min)
python scripts/run_api.py start                     # API release em 127.0.0.1:3000
python scripts/validation/check_api.py              # deve mostrar "both databases answered real queries"
npm.cmd --prefix frontend run dev                   # deixar este terminal aberto
```

Abra `http://localhost:5173` e confira:

- no bloco **Serviços** da barra lateral, API, PostgreSQL e Cassandra com marcador verde;
- a **Visão geral** carregada no período "26/10–01/11";
- a fonte **Cassandra** selecionada no canto superior direito.

**Aquecimento.**
- Abra a seção **Comparação** e clique uma vez em **Executar nos dois bancos**. A primeira consulta de cada fonte abre conexões e prepara instruções.
- Depois de reiniciar o computador ou os contêineres, faça 2 ou 3 execuções: o cache do PostgreSQL e a JVM do Cassandra demoram para aquecer. Logo depois de um reinício, a primeira consulta do painel no PostgreSQL pode levar alguns segundos (cache frio).

Se `scripts/run_api.py start` disser que falta o binário, rode antes `python scripts/run_api.py build` (cerca de 5 min na primeira vez).

## Passo a passo

1. **Visão geral no Cassandra (cerca de 1 min).**
   - Indicadores: 244 881 eventos, 19 758 alertas e 2 741 críticos.
   - **Tempo de resposta** no banco: de 2 a 8 ms.
   - Em **Eventos por hora**, passe o mouse no pico de **27/10 às 09h** (14 288 eventos na hora, a maior parte de rede): é uma campanha de varredura da massa sintética.
   - Mostre o **Volume diário** (27/10 em destaque), a severidade, as categorias e o card **Atividade**.
2. **Trocar para PostgreSQL** no seletor do topo (cerca de 40 s).
   - Os números são **exatamente os mesmos**; o tempo no banco fica entre 50 e 90 ms.
   - Explique: o PostgreSQL agrega cerca de 245 mil entradas de índice, e o Cassandra lê 7 partições pré-agregadas.
3. **Filtros** na barra de filtros (cerca de 40 s).
   - Categoria **Alerta** e severidade **5**: 1 842 eventos nas duas fontes.
   - Atalho **Pico · 27/10**: o gráfico de volume passa a mostrar as horas do dia.
   - Volte para "Todas" e "26/10–01/11".
4. **Comparação · Painel agregado (cerca de 1 min). Este é o ganho do NoSQL (R14).**
   - Pelo menu **Comparação** ou pelo botão ↗ do card "Tempo de resposta", deixe 10 repetições e clique em **Executar nos dois bancos**.
   - Resultado esperado: o card central mostra o Cassandra mais rápido na mediana HTTP do navegador, tipicamente de 4× a 20×, com o selo **"Resultado idêntico nos dois bancos"**. O proxy do Vite e o aquecimento reduzem a razão observada no navegador. Em 17/11/2026 o resultado foi 11,7×.
   - O primeiro par é aquecimento e é descartado automaticamente. "Ver tempos de cada par" mostra cada execução.
5. **Comparação · Q1 dispositivo (cerca de 40 s).** Agora o **PostgreSQL vence**, e o resultado também é idêntico. Mostre que o trabalho não esconde o caso favorável ao relacional.
6. **Investigação (cerca de 1 min).**
   - Escolha **Q2 · IP de origem** e clique no exemplo `2001:db8:bad:4::6`.
   - Mostre a página de eventos, os tempos (HTTP e banco) e **Próxima**, que pagina por cursor.
   - Clique no horário de um evento para abrir o **detalhe** e use **READ por ID**: a leitura pelo UUID retorna o mesmo conteúdo da página.
   - Troque a fonte no topo: a consulta é refeita no outro banco, com os mesmos eventos.
7. **Benchmarks (cerca de 1 min).**
   - Os quatro destaques: E4 (21,9×, com a ressalva da pré-agregação), E1–E3 (PostgreSQL de 1,2× a 4,0×), E5 e E6.
   - No gráfico de medianas em escala log, o círculo é o PostgreSQL e o losango, o Cassandra.
   - Mostre a tabela completa, o controle E5, o N+1 e as escritas E6.

## Plano B

| Problema | Ação |
| --- | --- |
| Cassandra demora a ficar *healthy* | `docker compose ps` e aguardar. O dashboard mostra "Cassandra indisponível", sem dados falsos. Demonstre com o PostgreSQL e use a seção Benchmarks |
| API não sobe (porta ocupada) | `python scripts/run_api.py stop`, depois `start`; ou `python scripts/run_api.py logs` |
| Dashboard em branco ou "A API local não está acessível" | Confira o terminal do Vite e a API (`python scripts/run_api.py status`) e reabra `http://localhost:5173` |
| Tempo de resposta pior que o normal | Feche o navegador extra e o IDE e repita a comparação (o primeiro clique aquece) |
| Sem rede/internet | Nada depende de internet depois do build; tudo roda em loopback |

## Depois

```powershell
python scripts/run_api.py stop
docker compose stop          # preserva os volumes; NUNCA usar "down -v"
```
