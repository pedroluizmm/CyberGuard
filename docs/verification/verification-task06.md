# Task 06: ampliação da massa, benchmarks em escala, dashboard, PDF e publicação

Data: 23/11/2026 (horários locais, UTC−3; relatórios em UTC). Fluxo READ → PLAN → APPLY → VERIFY. Os números citados vêm dos arquivos indicados; nada foi digitado a partir de estimativa.

## 1. Auditoria e preservação (antes de qualquer alteração)

| Item | Resultado real |
| --- | --- |
| Documentos oficiais | `Projeto_3_NoSQL_Instrucoes_Atualizadas.pdf` (3 páginas), `entregáveis.pdf` e `Equipe - Página1.pdf` lidos de novo; nenhum foi alterado |
| Git | `main` = `origin/main` (`05aec92`), sem arquivos modificados; 4 itens locais não publicados em `docs/apresentacao/` (roteiro prático do E4 e três opções de demonstração), preservados |
| Docker | Docker Desktop estava desligado; iniciado. Engine 29.4.3, VM WSL 2 com 22 vCPU e 7,44 GiB. Cassandra e PostgreSQL voltaram *healthy* com os volumes originais (`CreatedAt` 2026-11-09T05:06:41Z nos dois) |
| API | Binário release de 15/11 mais novo que todo o código do backend; `check_api.py`: API e os dois bancos responderam a consultas reais, CORS restrito |
| Integridade em 1 M | `check_bulk.py --target 1000000`: **22/22** (`data/bulk/reports/validate-1000000-20261123T192730Z.json`, 185 s) |
| Rollup em 1 M | `reconcile_rollup.py` (simulação): 0 diferenças; PostgreSQL = verdade Cassandra = contadores, 1 000 024 eventos em 9 978 células (`rollup-check-20261123T192828Z.json`) |
| Host | Intel Core Ultra 7 155H (16 núcleos, 22 threads), 15,37 GiB de RAM com 1,3–2,5 GiB livres, 163 GiB livres em C: |
| Energia | **Notebook na bateria** (62% às 16:30, descarregando, plano "Equilibrado"). O usuário foi notificado para ligar o carregador; o estado de energia passou a ser gravado em cada execução |

Preservados: dados dos dois bancos e volumes, execuções E1–E6 de 15/11 (`benchmarks/results/20261115T*`), relatórios em `data/bulk/reports/`, manifesto de 1 M (reproduzido byte a byte), PDF e HTML anteriores (versionados no Git), checkpoints de 1 M (copiados para `data/generated/cyberguard-bulk-v1/backup-1m/`). Nenhum `DROP`, `TRUNCATE`, `down -v`, `git clean` ou `reset`.

## 2. Mudanças para medir em escala (antes do baseline)

| Arquivo | Mudança |
| --- | --- |
| `scripts/generation/bulk_events.py`, `generate_bulk.py` | Perfis de 2, 3, 4 e 5 M; manifesto por volume (`cyberguard-bulk-v1.manifest-5000000.json`); conferência de que os primeiros 1 M eventos são idênticos ao manifesto original |
| `scripts/loading/load_bulk.py`, `scripts/validation/check_bulk.py` | Usam o menor manifesto que cobre o alvo; `--stop-file` para parada limpa |
| `scripts/loading/watchdog.py` (novo) | Monitor de host, VM, energia, contêineres e Cassandra que cria o arquivo de parada |
| `scripts/loading/reconcile_rollup.py` | A simulação também grava relatório (`rollup-check-*.json`) |
| `benchmarks/run_benchmarks.py` | Volume medido nos dois bancos, `--campaign`, `--prewarm`, eventos cobertos por consulta, cache/disco antes e depois das leituras, compactações pendentes, energia; `summary.json` esquema 2 com histórico preservado no topo |
| `benchmarks/run_scale_point.py`, `benchmarks/scale_report.py` (novos) | Sequência fixa de cada marco; tabela consolidada a partir do resumo |

`summary.json` reconstruído com o código novo manteve as quatro execuções históricas idênticas (operações, escritas e controle E5).

## 3. Baseline de 1 M (antes da ampliação)

| Execução | Conteúdo |
| --- | --- |
| `20261123T193215Z-main` | **Piloto**, preservado: revelou aquecimento da JVM (Cassandra reiniciado havia 12 min): painel 7 dias no Cassandra 10,8 → 8,4 ms entre o primeiro e o último terço das 30 medições |
| `20261123T193439Z-main` | Baseline oficial: mesmo protocolo + **30 passadas de pré-aquecimento** descartadas (`phase=prewarm`). Resposta idêntica em 9/9; cache 100% em `shared_buffers`, 98,9% no *key cache*, 0 byte lido de disco nas leituras |
| `20261123T193718Z-durability` | E6 com PostgreSQL `synchronous_commit=off` |

As duas execuções oficiais rodaram **na bateria** (62%).

## 4. Ampliação 1 M → 2 M

Manifesto `cyberguard-bulk-v1.manifest-5000000.json` gerado em 229 s; a verificação de prefixo confirmou chunks, perfis e "mundo" idênticos ao manifesto de 1 M (que continua byte a byte igual). Cargas pela API release, **as duas em paralelo** (16 workers cada), com `--stop-file` e o watchdog ativos.

| Banco | Criados | Reenvios / incertos | Tempo | Taxa observada | Relatório |
| --- | --- | --- | --- | --- | --- |
| PostgreSQL | 1 000 000 | 0 / 0 | 1 617,6 s | 618 ev/s | `load-postgresql-2000000-20261123T194438Z.json` |
| Cassandra | 1 000 000 | 0 / 0 | 1 318,8 s | 758 ev/s | `load-cassandra-2000000-20261123T194438Z.json` |

Recursos (`docker stats` a cada 10 s; 100% = 1 vCPU): Cassandra com média de 5,5–6,7 vCPU (pico 11,4) e até 3,64 de 5 GiB; PostgreSQL com média de 1,5 vCPU (pico 2,3) e até 1,28 de 2 GiB; API com ~2 vCPU e 25 MiB. Watchdog (41 amostras até o fim da carga Cassandra): RAM livre mínima do host 214 MiB, VM com ≥ 2,78 GiB disponíveis, swap ≤ 28 MiB, heap do Cassandra ≤ 92% em picos isolados, ≤ 3 compactações pendentes, ≥ 157 GiB livres em disco, nenhum limite sustentado.

**Gargalo observado no PostgreSQL:** CPU de 62% durante a carga; o limite foi o `fsync` por commit (≈ 70 mil `wal_sync` para ~290 mil eventos, cerca de 4 eventos por *group commit*), disputando o disco com commitlog, flushes e compactações do Cassandra. A taxa subiu de ~450 para ~635 ev/s quando a carga do Cassandra terminou. É efeito da carga paralela, não do volume.

**Energia:** a bateria caiu de 59% para 36% durante a carga (≈ 1%/min no fim). Com 36%, o limite de 30% do watchdog pararia o PostgreSQL a ~3 min de completar o marco; o watchdog foi reiniciado com limite de **22%** (acima dos 20% em que o Windows ativa a economia de bateria), porque o risco de dados está só em desligamento abrupto, e o Windows hiberna com segurança no nível crítico. O usuário foi notificado de novo para ligar o carregador.

## 5. Marco de 2 M: validação e benchmarks

| Etapa | Resultado real |
| --- | --- |
| `check_bulk.py --target 2000000` | **22/22** em 346 s (`validate-2000000-20261123T201732Z.json`): conteúdo integral e IDs iguais ao gerador nos dois bancos, projeções exatas, 6 164 298 linhas vivas no Cassandra (3N + A), partições iguais ao manifesto, 500 READs e Q1–Q3 idênticos |
| `reconcile_rollup.py` (simulação) | 0 diferenças; 2 000 024 eventos em 10 092 células; PostgreSQL = verdade Cassandra = contadores (`rollup-check-20261123T201826Z.json`) |
| `run_scale_point.py --target 2000000` | `20261123T201831Z-main` (E1–E6, resposta idêntica 9/9) e `20261123T202000Z-durability`; bateria 26% |
| Réplica | `20261123T202101Z-main` (leituras + E5): variação de até 40% nas medianas HTTP em relação à principal |
| Diagnóstico | `event_counts_by_day` com 1 SSTable e 1 SSTable por leitura (hipótese de amplificação de leitura descartada); *key cache* com 70 mil entradas (5,9 de 100 MiB), não estava cheio |
| Parada da ampliação | Watchdog criou o arquivo de parada com a bateria em 21% (limite 22%); nenhuma carga estava em andamento. **2 M é o maior volume carregado e validado** |

Resultados e interpretação: [benchmark-methodology.md](../benchmark-methodology.md#campanha-de-escala-1-m--massa-ampliada).

## 6. Testes finais

| Comando ou cenário | Resultado real |
| --- | --- |
| `check_foundation.py` | 44/44 |
| `docker compose config --quiet`, `python -m compileall -q scripts benchmarks docs/apresentacao` | OK |
| `check_api.py` (2 M carregados) | API e os dois bancos responderam a consultas reais; CORS restrito |
| `test_integration.py` | **10/10** (CRUD, Q1–Q3, paginação, painel equivalente, rollup acompanhando o CRUD) |
| `test_recovery.py`, `check_sample.py`, `test_bulk_generator.py` | OK; amostra de 24 eventos intacta (Q1 = 15, Q2 = 12, Q3 = 6); 5/5 |
| `npm run build` (svelte-check + tsc + Vite) | 0 erros, 0 avisos (210 arquivos) |
| Navegador (Chrome, Vite) | Cenários "1 M · 15/11", "1 M · 23/11", "2 M · 23/11" e "1 M × 2 M" renderizados com os dados do resumo; **Conferir massa nos dois bancos**: PostgreSQL 2.000.000 = Cassandra 2.000.000; visão geral em 2 M com 489.346 eventos na semana 26/10–01/11 nas duas fontes; console sem erros |
| Responsividade (iframes 820, 390 e 360 px) | Sem rolagem horizontal depois da correção do selo da comparação (havia 20 px em 390 px) |
| Falhas corrigidas | Cartão da barra lateral cortado pelo botão da massa; limiar de "estável" (10%) menor que o ruído medido (40%); afirmação sem suporte sobre inserção em B-tree no E6; título do slide 14 e plural do slide 10 |
| PDF | 18 páginas de 960 × 540 pt, gerado por `build_pdf.py` a partir de `slides.html` + `dados-escala.js`; páginas renderizadas e inspecionadas |
| `cargo fmt --check`, `cargo test`, `cargo build` | **Não reexecutados nesta tarefa**: o backend não mudou (o binário release usado em todos os testes é de 15/11, mais novo que o código). Última execução: 10/10 em 17/11 ([verification-task05.md](verification-task05.md)) |

## 7. Limitações e pendências

- **Volume:** 2 M validados; 3 M a 5 M não foram carregados (energia). O gerador, o manifesto e a carga incremental estão prontos: `load_bulk.py --target 5000000` retoma do checkpoint de 2 M.
- **Energia:** todas as medições da campanha rodaram na bateria (62% em 1 M, 26% em 2 M). Os valores absolutos de 23/11 são mais altos que os de 15/11.
- **Ruído:** uma réplica em 2 M variou até 40%; só o crescimento da agregação do PostgreSQL excede esse ruído.
- **Um nó Cassandra**, recursos assimétricos (5 GiB × 2 GiB) e cache quente, como na campanha histórica.
