# Roteiro da demonstração ao vivo (cerca de 6 min)

Os números esperados abaixo foram observados no dashboard com a massa final carregada (2.000.000 eventos em cada banco) e podem variar alguns milissegundos; os **totais** devem ser exatamente os mesmos.

## Antes da aula (15 min antes)

**Ligue o notebook na tomada** (na bateria o Windows reduz o clock e os tempos sobem) e feche programas pesados: a máquina tem 16 GB e a VM do Docker usa até 7,4 GB. Use PowerShell na raiz do repositório:

```powershell
docker compose up -d --wait --wait-timeout 720      # bancos (o Cassandra pode levar 1-3 min)
python scripts/run_api.py start                     # API release em 127.0.0.1:3000
python scripts/validation/check_api.py              # deve terminar com "both databases answered real queries"
npm.cmd --prefix frontend run dev                   # deixar este terminal aberto
```

Abra `http://localhost:5173` e confira:

- no bloco **Serviços** da barra lateral, API, PostgreSQL e Cassandra com marcador verde;
- a **Visão geral** carregada no período "26/10–01/11" e a fonte **Cassandra** selecionada.

**Aquecimento (obrigatório depois de ligar o Docker).** A JVM do Cassandra e o cache do PostgreSQL começam frios: a primeira consulta do painel no PostgreSQL pode levar alguns segundos.
1. Clique em **Conferir massa nos dois bancos** (barra lateral).
2. Na seção **Comparação**, rode **Painel agregado** duas vezes e **Q1 dispositivo** uma vez.
3. Troque a fonte para PostgreSQL e volte para Cassandra na Visão geral.

Se `scripts/run_api.py start` disser que falta o binário, rode antes `python scripts/run_api.py build` (cerca de 5 min na primeira vez).

## Passo a passo

1. **Abrir o CyberGuard (20 s).** Mostre a barra lateral (Monitoramento × Análise), o bloco **Serviços** com os três componentes conectados e o seletor de fonte no topo.
2. **Confirmar a massa (30 s).** Na barra lateral, clique em **Conferir massa nos dois bancos**: as duas fontes devem mostrar **2.000.000** e o selo "Mesmo total nos dois bancos". O PostgreSQL soma as linhas; o Cassandra soma o rollup. É uma consulta ao vivo, não um número gravado.
3. **Visão geral no Cassandra e troca para PostgreSQL (1 min).**
   - Semana 26/10–01/11: **489.346** eventos, **39.265** alertas e **5.500** críticos; tempo no banco do Cassandra na casa de poucos ms. Em **Eventos por hora**, o pico é **27/10 às 09h** (28.636 eventos, a maior parte de rede): uma campanha de varredura da massa sintética.
   - Troque para **PostgreSQL**: os números são **exatamente os mesmos**; o tempo no banco sobe para algo entre 170 e 320 ms porque o PostgreSQL agrega 489.346 entradas de índice, enquanto o Cassandra lê 7 partições de contadores.
4. **Filtros (40 s).** Categoria **Alerta** e severidade **5**: **3.657** eventos nas duas fontes. Atalho **Pico · 27/10**: o gráfico passa a mostrar as horas do dia. Volte para "Todas" e "26/10–01/11".
5. **Investigação (1 min).** Escolha **Q2 · IP de origem** e o exemplo `2001:db8:bad:4::6`. Mostre a página de 100 eventos, os tempos, **Próxima** (cursor) e o detalhe de um evento com **READ por ID**. Troque a fonte: mesma página, outro banco.
6. **Comparação ao vivo · Painel agregado (1 min) — o ganho do NoSQL (R14).** Deixe 10 repetições e clique em **Executar nos dois bancos**. Esperado: Cassandra mais rápido na mediana do navegador e o selo **"Resultado idêntico nos dois bancos"**. O primeiro par é aquecimento e é descartado.
7. **Comparação ao vivo · Q1 dispositivo (30 s).** Agora o **PostgreSQL vence**, também com resultado idêntico: o trabalho não esconde o caso favorável ao relacional.
8. **Benchmarks · 1 M (40 s).** Em **Benchmarks**, cenário **Histórico · 1 M**: destaques (E4 21,9× com a ressalva da pré-agregação; E1–E3 PostgreSQL de 1,2× a 4,0×), o gráfico de medianas e o controle E5.
9. **Benchmarks · massa ampliada (1 min).** Cenário **Análise · 1 M × 2 M**: nos pequenos múltiplos, a linha do PostgreSQL no **Painel 7 dias** sobe com a massa (90,8 ms → 173 ms) e a do Cassandra fica plana (6,1 ms → 7,9 ms, dentro do ruído entre execuções); nas buscas por chave as duas ficam praticamente estáveis e o PostgreSQL continua vencendo. Abra o cenário **2 M** para mostrar a mesma tabela completa daquele volume.
10. **Explicação técnica e fechamento (40 s).** O Cassandra vence o painel porque a pergunta foi modelada na escrita: a API incrementa um contador por (dia, hora, categoria, severidade) quando o evento é ativado; a leitura de 7 dias lê no máximo 2 520 células, qualquer que seja o volume. O PostgreSQL normalizado agrega na leitura e seu custo acompanha a massa; com view materializada ele também lê rápido, mas paga um REFRESH completo que cresce com a tabela. Em troca, o PostgreSQL vence buscas por chave, oferece SQL ad hoc e transações, e o Cassandra paga LWT, contadores não idempotentes e reconciliação. Um nó não demonstra escala horizontal.

## Plano B

| Problema | Ação |
| --- | --- |
| Cassandra demora a ficar *healthy* | `docker compose ps` e aguardar. O dashboard mostra "Cassandra indisponível", sem dados falsos. Demonstre com o PostgreSQL e use a seção Benchmarks (resultados gravados) |
| Um banco caiu durante a aula | `docker compose start cassandra` (ou `postgresql`). O pool da API reconecta sozinho; clique no ↻ do bloco Serviços. Enquanto isso, mostre os Benchmarks gravados |
| API não sobe (porta ocupada) | `python scripts/run_api.py stop` e depois `start`; diagnóstico: `python scripts/run_api.py logs` |
| Dashboard em branco ou "A API local não está acessível" | Confira o terminal do Vite e a API (`python scripts/run_api.py status`) e reabra `http://localhost:5173` |
| Consulta lenta no PostgreSQL logo após ligar | É cache frio: repita uma vez. Não use janelas maiores que 7 dias (o próprio dashboard limita) |
| Nada funciona | Apresente pelo PDF: os slides 12–14 trazem os resultados medidos, e `benchmarks/results/` guarda os dados brutos |

Não rode durante a aula: carga de dados, `check_bulk.py`, `reconcile_rollup.py --apply` ou benchmarks completos. São operações longas e pesadas.

## Depois

```powershell
python scripts/run_api.py stop
docker compose stop          # preserva os volumes; NUNCA usar "down -v"
```
