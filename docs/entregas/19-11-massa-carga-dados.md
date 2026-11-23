# 19/11: massa volumosa, carga e documentação dos dados

Este documento resume a entrega. A metodologia completa está em [../bulk-load.md](../bulk-load.md), e a verificação executada, com todos os números, em [../verification-task03.md](../verification/verification-task03.md). Os relatórios JSON brutos ficam em `data/bulk/reports/`.

## Significado de "registro"

Um **registro lógico é um evento de segurança** identificado por UUID v4, como definido em [../data-model.md](../data-model.md). A meta de **1 000 000** se refere a eventos lógicos, e não a linhas físicas:

| Banco | Representação física de N eventos (A alertas) | Em 1 M |
| --- | --- | --- |
| PostgreSQL | 1 linha em `events` + 1 reserva em `event_registry` (+ 393 dispositivos) | `events` com 1 000 024 linhas (1 M + 24 da amostra) |
| Cassandra | `3N + A` linhas: canônica, dispositivo, IP e alerta. O rollup do painel soma 9 978 contadores | 3 082 443 linhas vivas do dataset |

## Origem: geração sintética determinística

| Item | Valor |
| --- | --- |
| Dataset / seed | `cyberguard-bulk-v1`, seed `20261109`, gerador `1.0.0` |
| Método | `event(i)` é uma função pura de (dataset, seed, i), via SHA-256 em modo contador e pesos inteiros. Não depende de relógio, ordem ou versão do Python |
| Janela | 28 dias UTC (05/10 a 01/11/2026), disjunta da amostra (06–08/11) e dos testes (2001/2002) |
| Realismo | Perfil horário e de dias úteis; popularidade Zipf de dispositivos/IPs/contas; 393 dispositivos em 7 papéis; 20 campanhas de ataque (força bruta, varredura, *credential stuffing*, exfiltração, beaconing C2); cerca de 8,2% de alertas; IPv4 69% / IPv6 31% |
| Privacidade | Só endereços de documentação ou privados (RFC 1918/4193/5737/3849) e contas sintéticas. Nenhum dado pessoal real |
| Manifesto | `data/bulk/cyberguard-bulk-v1.manifest.json` (86 KB, versionado): seed, algoritmos, SHA-256 de cada lote de 1 000 eventos, contagens e distribuição de partições. Regerar reproduz o arquivo byte a byte |

Composição em 1 M (manifesto):

- categorias: 457 721 de autenticação, 459 836 de rede e 82 443 alertas;
- severidades de 1 a 5: 667 294, 170 309, 113 187, 37 434 e 11 776;
- 9 908 IPs de origem distintos.

## Carga

A carga passa pela **API real** (`POST /api/{fonte}/events`), um banco por vez, com 16 *workers* e checkpoint por lote. Ela tem retry com o mesmo UUID e aceita uma resposta só quando o envelope volta idêntico. Assim o PostgreSQL usa a mesma transação da aplicação e o Cassandra, o mesmo fluxo `pending → projeções → active` com LWT. Não houve `COPY` nem escrita direta que pulasse a validação.

| Volume | Tempo de carga PostgreSQL | Tempo de carga Cassandra | Validação |
| --- | --- | --- | --- |
| 10 mil | 17,5 s (572 ev/s) | 17,3 s (577 ev/s) | 22/22; o controle negativo falhou como esperado |
| 100 mil | retomada após *kill* forçado, sem duplicação | idem | 22/22 |
| 1 milhão | 1 716,6 s para 900 mil novos (524 ev/s) | 1 516,4 s (594 ev/s) | **22/22** |

Esses são tempos de **carga inicial via API em build debug**, com cliente Python. As durabilidades são diferentes (`fsync` por commit × commitlog periódico). **Não são benchmark.** A comparação controlada de escrita é o E6 em [24-11-experimentos-dashboard.md](24-11-experimentos-dashboard.md).

## Integridade e equivalência (evidências)

1. **`check_bulk.py --target 1000000`: 22/22 verificações** (`data/bulk/reports/validate-1000000-20261109T154628Z.json`):
   - a exportação integral dos dois bancos é comparada com o gerador, conteúdo completo e IDs;
   - as três projeções têm chaves exatas, sem duplicação nem estados `pending`/`deleting`;
   - `3N + A` confere;
   - a distribuição de partições é igual à do manifesto;
   - 500 READs amostrados são iguais nos dois bancos;
   - seis consultas Q1–Q3 são paginadas por completo, iguais entre os bancos e iguais ao esperado.
2. **Rollup do painel (Task 04):**
   - o backfill a partir de `events_by_id` gerou 1 000 024 eventos em 9 978 células;
   - a agregação independente do PostgreSQL ficou **idêntica célula a célula** (`rollup-reconcile-20261115T052013Z.json`).
3. **Testes:**
   - `test_integration.py`: 9 testes de CRUD, consultas e painel equivalentes;
   - `test_recovery.py`: recuperação de estados interrompidos;
   - `check_sample.py`: amostra intacta.

## Tamanho ocupado (1 M)

| Item | Tamanho |
| --- | --- |
| PostgreSQL `events` (heap + 5 índices) | 696 MB (heap 461 MB; índice de cobertura do painel 42 MB) |
| PostgreSQL banco inteiro | 797 MB |
| Cassandra `events_by_id` (LZ4) | 260,5 MB |
| Cassandra projeções (dispositivo / IP / alertas) | 29,5 / 36,6 / 2,4 MB |
| Cassandra `system.paxos` (estado das LWT) | 97,7 MB (medido na Task 03) |

Os tamanhos dependem de compressão, ordem de inserção e compactação, e não são uma comparação de eficiência.

## Esquemas e procedimento reproduzível

Esquemas: `database/postgresql/001_events.sql` e `002_dashboard.sql`; `database/cassandra/001_events.cql` e `002_rollup.cql`. Todos são aditivos e se aplicam com `python scripts/apply_schema.py`.

```powershell
python scripts/setup_env.py
docker compose up -d --wait --wait-timeout 720
python scripts/apply_schema.py
python scripts/run_api.py build ; python scripts/run_api.py start
python scripts/validation/test_bulk_generator.py
python scripts/generation/generate_bulk.py --count 1000000       # reproduz o manifesto
python scripts/loading/load_bulk.py --source postgresql --target 1000000
python scripts/loading/load_bulk.py --source cassandra  --target 1000000
python scripts/loading/reconcile_rollup.py --apply               # rollup do painel
python scripts/validation/check_bulk.py --target 1000000
```

A carga é retomável e idempotente: repetir o comando continua do checkpoint. Para recomeçar em outro ambiente, use bancos novos. Nunca apague volumes ou tabelas existentes.

## Ampliação para 2 M (23/11)

A massa cresceu acrescentando os índices `[1 M, 2 M)` ao mesmo gerador (manifesto `cyberguard-bulk-v1.manifest-5000000.json`, cujo prefixo de 1 M é idêntico ao manifesto original). Carga pela API **release**, com os dois bancos em paralelo, retomando dos checkpoints de 1 M:

| Incremento | PostgreSQL | Cassandra | Validação |
| --- | --- | --- | --- |
| 1 M → 2 M | 1 617,6 s (618 ev/s), 0 reenvios | 1 318,8 s (758 ev/s), 0 reenvios | **22/22** (`validate-2000000-20261123T201732Z.json`); rollup com 2 000 024 eventos em 10 092 células, igual ao PostgreSQL |

Em 2 M: banco PostgreSQL de 1,59 GB e keyspace Cassandra de 0,66 GB (os dois dobraram); 6 164 298 linhas vivas no Cassandra (3N + A). A ampliação até 5 M parou em 2 M porque o notebook ficou na bateria (watchdog com limite de 22%); RAM, disco e CPU tinham margem ([../verification/verification-task06.md](../verification/verification-task06.md)).

**Histórico (Task 03), volume recomendado de 5 M:** não foi tentado naquela tarefa. Durante a carga de 1 M, a RAM livre do host chegou a 211 MiB. A projeção para 5 M é de cerca de 6–7 GB em disco nos dois bancos e de cerca de 2,5 h por banco ([../verification-task03.md](../verification/verification-task03.md)). O mínimo exigido, 1 M, está atendido.
