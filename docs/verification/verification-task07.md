# Task 07: ampliação de 2 M para 5 M de eventos

Data: 24/11/2026 (horários locais, UTC−3; relatórios em UTC). Sem commit nem push. Os documentos, a apresentação e o frontend existentes **não** foram alterados nesta tarefa; este relatório é o registro novo.

## 1. Verificação inicial

| Item | Resultado real |
| --- | --- |
| Energia | Notebook **na tomada** (79%), plano "Equilibrado" |
| Serviços | Docker 29.4.3; Cassandra e PostgreSQL *healthy*; API release; `check_api.py`: os dois bancos responderam |
| Massa | 2 000 000 eventos em cada banco (soma dos painéis semanais); checkpoints em 2 000 000 nos dois |
| Recursos | VM com 3,38 GiB disponíveis, swap 58 MiB, 171 GiB livres em disco, heap Cassandra 59%, 0 compactações pendentes; RAM disponível no Windows ~300 MiB (mesma faixa da carga anterior) |
| Arquivo `STOP` | Criado em 23/11 17:24 pelo watchdog, motivo `on battery at 21% < 22.0%`. Com a máquina na tomada, a causa não existe mais: o arquivo foi removido, com cópia em `data/generated/cyberguard-bulk-v1/backup-2m/STOP-20261123.json`; checkpoints de 2 M copiados para a mesma pasta |
| Watchdog | Religado com os **limites padrão** (bateria 30%, RAM do host 200 MiB, VM 150 MiB, swap 1,5 GiB, heap 92%, disco 40 GiB) |

## 2. Calibração de energia em 2 M

As execuções de 1 M e 2 M de 23/11 rodaram na bateria; as de 5 M rodam na tomada. Para separar efeito de volume de efeito de energia, foi medida, ainda com 2 M, uma réplica na tomada (`20261124T034929Z-main`, leituras + E5, mesmo protocolo com 30 passadas de pré-aquecimento). Ela entra no resumo como réplica de 2 M e não substitui a execução principal de 23/11.

## 3. Teste controlado (5 min)

Cargas em paralelo com alvo de 3 M e `--max-seconds 300`: PostgreSQL 193 000 eventos (639 ev/s) e Cassandra 185 000 (613 ev/s), 0 reenvios, 0 incertos, parada limpa em fronteira de chunk. Watchdog: 0 alertas; VM ≥ 2,74 GiB livres, swap ≤ 117 MiB, heap Cassandra ≤ 82,5%, disco 170,9 GiB; RAM do host ≥ 252 MiB. Decisão: prosseguir.

## 4. Marco de 3 M

| Banco | Criados (teste + retomada) | Reenvios / incertos | Tempo total | Taxa | Relatórios |
| --- | --- | --- | --- | --- | --- |
| PostgreSQL | 193 000 + 807 000 | 0 / 0 | 302 + 1 391 s = 1 693 s | 591 ev/s | `load-postgresql-3000000-20261124T035045Z.json`, `…035604Z.json` |
| Cassandra | 185 000 + 814 992 (+ 8 `reused`) | 8 / 0 | 302 + 1 306 s = 1 608 s | 622 ev/s | `load-cassandra-3000000-20261124T035045Z.json`, `…035604Z.json` |

Recursos (média/pico, 100% = 1 vCPU): Cassandra 7,3–8,2 / 12,6 vCPU e até 3,37 de 5 GiB; PostgreSQL 2,1–2,4 / 3,3 vCPU e até 1,15 de 2 GiB; API ~2,4 vCPU. RAM disponível mínima no host 252 MiB. Watchdog: um único pico de heap do Cassandra (93,6%), sem sequência sustentada.

- `check_bulk.py --target 3000000`: **22/22** (`validate-3000000-20261124T042806Z.json`).
- `reconcile_rollup.py` (simulação): eventos canônicos do Cassandra = agregação do PostgreSQL (3 000 024), mas **4 incrementos faltando** no rollup (3 000 020), em 4 células (`rollup-check-20261124T043009Z.json`). Causa compatível com os 8 reenvios: quando o *timeout* ocorre depois da transição LWT `pending→active` e antes do incremento, o reenvio devolve 200 `reused` e não incrementa (contador não idempotente, cenário previsto em `docs/consistency.md`). Correção prescrita pelo AGENTS.md, com a API ociosa: `reconcile_rollup.py --apply` gravou as 4 diferenças (`rollup-reconcile-20261124T043205Z.json`); nova simulação: 0 diferenças (`rollup-check-20261124T043342Z.json`).

## 5. Marco de 4 M

| Banco | Criados | Reenvios / incertos | Tempo | Taxa | Relatório |
| --- | --- | --- | --- | --- | --- |
| PostgreSQL | 1 000 000 | 0 / 0 | 1 877 s | 533 ev/s | `load-postgresql-4000000-20261124T043352Z.json` |
| Cassandra | 999 996 (+ 4 `reused`) | 5 / 0 | 1 663 s | 601 ev/s | `load-cassandra-4000000-20261124T043352Z.json` |

Recursos: Cassandra 6,8–7,5 / 11,4 vCPU e até 3,25 de 5 GiB; PostgreSQL 2,2 / 3,2 vCPU e até **1,45 de 2 GiB**; watchdog (70 amostras) sem alertas, swap da VM ≤ 437 MiB, VM ≥ 3,0 GiB livres, heap ≤ 81%, disco ≥ 156 GiB. A RAM disponível no Windows chegou a 122 MiB em uma amostra do carregador (o watchdog exige 4 amostras seguidas abaixo de 200 MiB para parar): menor margem até aqui.

- `check_bulk.py --target 4000000`: **22/22** (`validate-4000000-20261124T051654Z.json`).
- Rollup: mesma deriva de contador após reenvios (2 incrementos faltando; canônico = PostgreSQL = 4 000 024) em `rollup-check-20261124T051913Z.json`; corrigida com `--apply` (`rollup-reconcile-20261124T052132Z.json`) e reconferida com 0 diferenças (`rollup-check-20261124T052344Z.json`).

## 6. Carga 4 M → 5 M

| Banco | Criados | Reenvios / incertos | Tempo | Taxa | Relatório |
| --- | --- | --- | --- | --- | --- |
| PostgreSQL | 1 000 000 | 0 / 0 | 1 893 s | 528 ev/s | `load-postgresql-5000000-20261124T052354Z.json` |
| Cassandra | 1 000 000 | 0 / 0 | 1 659 s | 603 ev/s | `load-cassandra-5000000-20261124T052354Z.json` |

Recursos: Cassandra 6,9–7,8 / 10,8 vCPU e até 3,23 de 5 GiB; PostgreSQL 2,2 / 5,3 vCPU e até **1,68 de 2 GiB**; watchdog (72 amostras) sem alertas, swap da VM ≤ 456 MiB, VM ≥ 3,0 GiB livres, heap ≤ 84%, RAM do host ≥ 276 MiB, disco ≥ 156 GiB. Na sessão inteira (307 amostras), o watchdog registrou um único alerta isolado (pico de heap de 93,6% durante a carga de 3 M) e nunca criou o arquivo de parada. Espaço livre em C: caiu de 171,0 para 156,4 GiB.

### Total da carga adicional 2 M → 5 M (tempo de parede, cargas paralelas)

| Banco | Eventos novos | Soma dos tempos de carga | Taxa média |
| --- | --- | --- | --- |
| PostgreSQL | 3 000 000 | 302 + 1 391 + 1 877 + 1 893 = 5 463 s (91 min) | 549 ev/s |
| Cassandra | 3 000 000 | 302 + 1 306 + 1 663 + 1 659 = 4 930 s (82 min) | 609 ev/s |

## 7. Incidentes durante a validação de 5 M

- **Suspensão do notebook:** a validação começou às 02:55; o Windows suspendeu a máquina de 02:56 a 04:21 (85 min sem nenhuma amostra do watchdog; o processo de validação tinha 54 s de CPU depois de 85 min). Nada falhou: ao acordar, bancos *healthy* e a validação retomou. Para o resto da tarefa, um processo auxiliar pede ao Windows para manter o sistema acordado (`SetThreadExecutionState`, liberado quando o processo termina, limite de 3 h). Nenhuma configuração de energia do sistema foi alterada.
- **Memória do contêiner Cassandra na exportação:** o `cqlsh COPY` do validador roda dentro do contêiner do Cassandra, com 16 processos de ~155 MB que contam no limite de 5 GiB. Em 5 M, o contêiner ficou entre 4,88 e 4,97 GiB durante a exportação de `events_by_id`, sem OOM (o kernel recicla o cache de arquivos), e a exportação ficou mais lenta que em 4 M. Não houve escrita em andamento (a última carga terminou às 02:55), então não havia dado em risco.

## 8. Validação da massa final (5 M)

**Primeira tentativa (falhou, sem dano):** o `check_bulk.py` iniciado às 02:55 passou nas 5 verificações do PostgreSQL e parou na exportação do Cassandra, sem gravar relatório. A suspensão da máquina e o contêiner no limite de memória coincidiram com essa falha; o erro exato não foi capturado (a saída estava filtrada). O Cassandra não sofreu OOM nem reinício.

**Correção no validador** (`scripts/loading/bulk_runtime.py`, usado também pelo reconciliador):
- o stderr das exportações passou a ser drenado em paralelo. Antes, ele só era lido ao final; muitos avisos de reenvio do `cqlsh` poderiam encher o pipe e travar a exportação;
- `cqlsh COPY ... AND NUMPROCESSES=4` (configurável por `CYBERGUARD_CQLSH_PROCESSES`), em vez de um processo por CPU (até 16) dentro do contêiner de 5 GiB;
- a mensagem de falha passa a incluir o código de saída e o fim do stderr.

**Segunda tentativa:**

| Verificação | Resultado real |
| --- | --- |
| `check_bulk.py --target 5000000` | **22/22** (`validate-5000000-20261124T091629Z.json`): conteúdo integral e IDs iguais ao gerador nos dois bancos, sem duplicação, revisões 1, 0 registros `pending`/`deleting`, 3 projeções com chaves exatas, linhas vivas = 3N + A, partições iguais ao manifesto, 500 READs e 6 consultas Q1–Q3 iguais nos dois bancos e ao esperado |
| `reconcile_rollup.py` (simulação) | 0 diferenças; contadores = verdade canônica = agregação do PostgreSQL = **5 000 024** eventos em 10 101 células (`rollup-check-20261124T093254Z.json`) |

O host estava mais lento depois da suspensão: a regeneração do estado esperado levou 1 028 s, contra 172 s em 4 M. O gerador mediu 9,2 mil ev/s, contra 21,8 mil em 23/11, com VS Code e Microsoft PC Manager consumindo CPU no Windows.

## 9. Benchmarks em 5 M

| Execução | Situação |
| --- | --- |
| Primeira tentativa | Bloqueada pelo próprio executor: o painel semanal do PostgreSQL devolveu 503 ao medir o volume, porque passou do timeout de 5 s da API (`STORAGE_TIMEOUT_MS`) com cache frio logo após o `VACUUM` e a varredura completa da validação. Nada foi gravado. Com o cache aquecido, a mesma consulta responde em ~1 s |
| `20261124T093539Z-main`, `…094414Z-durability` | **Excluídas** (`benchmarks/results/excluded.json`, preservadas no disco): VM do Docker degradada após a suspensão. `/api/health` levava 5,2 ms; o READ ficou 4,8–6,8× mais lento dentro dos dois bancos, com 100% de acertos de cache e 0 byte lido do disco. O Docker Desktop foi reiniciado (só ele; o WSL do Ubuntu do usuário não foi tocado; volumes preservados) e o health voltou a 1,3 ms |
| `20261124T095108Z-main` + `…095354Z-durability` | **Execução oficial de 5 M** (E1–E6, resposta idêntica 9/9) |
| `20261124T095430Z-main` | Réplica (leituras + E5) |

**Energia:** o notebook ficou na tomada até 06:47 e na bateria depois disso. As execuções principais de 1 M (bateria 62%), 2 M (bateria 26%) e 5 M (bateria 77%) rodaram na mesma condição. A réplica de calibração de 2 M rodou na tomada e ficou na mesma faixa (painel 7 dias no PostgreSQL: 163 × 173 ms).

### Mediana HTTP (ms), 30 execuções por banco

| Operação | PG 1 M | CS 1 M | PG 2 M | CS 2 M | PG 5 M | CS 5 M | Vencedor 1 M → 2 M → 5 M |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E1 READ por UUID | 1,64 | 1,76 | 1,67 | 2,38 | 2,16 | 2,79 | PG 1,1× → 1,4× → 1,3× |
| E2 Q1 dispositivo, 1ª página | 3,88 | 8,53 | 4,15 | 8,21 | 3,74 | 8,73 | PG 2,2× → 2,0× → 2,3× |
| E2 Q1 10 páginas | 32,3 | 95,0 | 31,7 | 90,4 | 37,2 | 95,8 | PG 2,9× → 2,9× → 2,6× |
| E2 Q1 dispositivo pouco ativo | 3,08 | 11,3 | 3,70 | 13,0 | 4,62 | 11,3 | PG 3,7× → 3,5× → 2,4× |
| E3 Q2 IP de campanha | 4,85 | 11,6 | 3,97 | 10,6 | 5,31 | 13,0 | PG 2,4× → 2,7× → 2,5× |
| E3 Q3 alertas sev. 3 | 3,93 | 7,97 | 4,01 | 7,72 | 4,58 | 8,45 | PG 2,0× → 1,9× → 1,8× |
| **E4 Painel 7 dias** (244 881 → 489 346 → 1 224 610 eventos) | 90,8 | 6,12 | 173 | 7,93 | **453** | **8,41** | **CS 14,8× → 21,9× → 53,8×** |
| E4 Painel 1 dia | 17,5 | 2,88 | 42,9 | 4,39 | 88,6 | 3,98 | CS 6,1× → 9,8× → 22,3× |
| E4 Painel 7 dias, só alertas | 53,4 | 5,91 | 90,4 | 5,88 | 272 | 8,69 | CS 9,1× → 15,4× → 31,2× |

Tempo **no banco** (Server-Timing), painel 7 dias: PostgreSQL 88 → 171 → 450 ms (réplica 456 ms); Cassandra 3,1 → 3,6 → 4,4 ms (réplica 5,4 ms). Réplica de 5 M: painel 459 × 8,8 ms, consistente com a execução oficial.

| E5 (psql / Server-Timing) | 1 M | 2 M | 5 M |
| --- | --- | --- | --- |
| PG agregação na leitura | 82,6 ms | 160 ms | 420 ms |
| PG view materializada | 1,54 ms | 1,09 ms | 1,25 ms |
| PG REFRESH completo | 360 ms | 640 ms | 1 692 ms |
| Cassandra rollup | 3,14 ms | 3,63 ms | 4,44 ms |

| E6 CREATE (PG / CS) | 1 M | 2 M | 5 M |
| --- | --- | --- | --- |
| Padrão (PG fsync por commit) | 10,7 / 8,79 ms | 10,3 / 7,98 ms | 13,2 / 10,3 ms |
| Ambos antes do fsync | 4,55 / 8,17 ms | 4,60 / 7,85 ms | 5,38 / 8,34 ms |

Ambiente: banco PostgreSQL 0,80 → 1,59 → 4,06 GB; keyspace Cassandra 0,33 → 0,66 → 1,65 GB. Na fase de leitura, 100% de acertos em `shared_buffers` nos três volumes; *key cache* do Cassandra 98,9% → 97,1% → 94,7%; leitura de disco 0 → 10 → 104 MB.

### Interpretação

- **Agregação:** o tempo do PostgreSQL acompanha os eventos do período (×5 de massa → ×5,1 no banco). O rollup do Cassandra lê as mesmas ≤ 2 520 células e variou menos de 2 ms. A vantagem do Cassandra no painel **aumentou** de 14,8× para 53,8×. É o ganho da pré-agregação na escrita: com view materializada, o PostgreSQL também lê em ~1 ms, mas o REFRESH completo chegou a 1,7 s.
- **Chave e páginas:** o PostgreSQL venceu todas, nos três volumes. As variações ficaram dentro do ruído entre execuções (até 55% nas réplicas), com uma exceção: o "Q1 dispositivo pouco ativo", em que a resposta cresceu (54 → 317 eventos na janela; página cheia de 100) e a vantagem do PostgreSQL caiu de 3,7× para 2,4×.
- **Escritas:** o CREATE padrão subiu ~25% nos dois bancos de 2 M para 5 M. Isso está no limite do ruído e não é atribuído com segurança ao volume. A política de fsync continua pesando mais (PG 13,2 × 5,4 ms).
- **Limite de um nó:** crescer a massa em uma máquina não demonstra escalabilidade horizontal.

## 10. Testes finais e estado do sistema

| Verificação | Resultado |
| --- | --- |
| `check_api.py` | os dois bancos responderam |
| `test_integration.py` | **10/10** |
| `test_recovery.py`, `check_sample.py`, `test_bulk_generator.py` | OK (amostra de 24 eventos intacta) |
| `check_foundation.py` | 44/44 |
| Dashboard (Vite, capturas reais, sem alteração no frontend) | Comparação 1 M → 2 M → 5 M e cenário "5 M · 24/11" lidos do `summary.json`; visão geral com 1 224 610 eventos na semana 26/10–01/11 |

## 11. Riscos e pendências

- **Demonstração:** em 5 M, a primeira consulta do painel no PostgreSQL com cache frio pode passar do timeout de 5 s da API e devolver 503. O aquecimento do roteiro da demo é obrigatório. Aumentar `STORAGE_TIMEOUT_MS` seria uma mudança de configuração não feita nesta tarefa.
- **Rollup:** reenvios durante a carga deixaram 4 (3 M) e 2 (4 M) incrementos faltando, corrigidos com `reconcile_rollup.py --apply`. É a limitação conhecida dos contadores não idempotentes.
- **Documentação e apresentação:** README, metodologia, slides, PDF e `dados-escala.js` ainda citam 2 M como maior volume. Não foram alterados, conforme pedido. O dashboard já mostra 5 M porque lê o `summary.json`.
- **Host:** RAM disponível no Windows chegou a 122 MiB; o validador `check_bulk` em 5 M levou ~1 h com o host lento após a suspensão.
- Sem commit e sem push nesta tarefa.
