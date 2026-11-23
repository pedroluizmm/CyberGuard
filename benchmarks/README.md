# Benchmarks

Experimentos comparativos PostgreSQL × Cassandra sobre o mesmo conjunto lógico de eventos: o histórico de 1 M (15/11) e a campanha de escala (23/11), que mede o mesmo protocolo em volumes crescentes. A metodologia, os resultados e a interpretação estão em [docs/benchmark-methodology.md](../docs/benchmark-methodology.md).

| Arquivo | Conteúdo |
| --- | --- |
| `run_benchmarks.py` | Executor (suítes `main`, `n1`, `writes`, `durability`). Exige a API em build release e confere a configuração dela em `/api/runtime` antes de medir, inclusive pool PostgreSQL ≥ número de clientes de escrita |
| `sql/pg_rollup_control.sql` | Controle E5: view materializada no schema `bench`. É aditiva e não faz parte da aplicação |
| `results/<UTC>-<suite>/raw.csv` | Uma linha por requisição de leitura: fase (`prewarm`, `warmup`, `measure`), iteração, ordem no par, status, `http_ms`, `db_ms`, itens e hash do corpo |
| `results/<UTC>-<suite>/raw_writes.csv` | Latência de cada CREATE/UPDATE/DELETE do E6, com a fase (`warmup`/`measure`) |
| `results/<UTC>-<suite>/environment.json` | Hardware, energia do notebook, Docker, imagens, limites, versões, configurações, índices, tamanhos, volume medido nos dois bancos, eventos cobertos por consulta, git e runtime da API |
| `results/<UTC>-<suite>/run.json` | Estatísticas por operação (mediana, p25/p75/p95, pares vencidos, equivalência), campanha, volume e contadores de cache/disco da fase de leitura |
| `results/summary.json` | Esquema 2: no topo, a última execução completa de cada suíte **sem campanha** (histórico de 1 M); em `campaigns.<nome>`, as execuções agrupadas por volume e a visão `scale` (medianas por operação e volume, E5 e E6). É servido ao dashboard por `GET /api/benchmarks/summary` |

## Executar

```powershell
python scripts/run_api.py build && python scripts/run_api.py start
python benchmarks/run_benchmarks.py --suite main          # E1-E6 (~2 min)
```

A suíte `writes` repete só o E6 com a configuração padrão. Para as variantes, reinicie a API com `--read-concurrency 1` (suíte `n1`) ou com `--pg-synchronous-commit off` (suíte `durability`). O E6 exige `POSTGRES_POOL_SIZE` ≥ `--write-concurrency` (padrões 16 e 8) e usa `--write-warmup` rodadas descartadas (padrão 2). Detalhes em `python benchmarks/run_benchmarks.py --help`.

- `--runs` (padrão 30, mínimo 10) e `--warmup` (padrão 5) controlam as repetições.
- `--results-dir` grava em outra pasta, útil para ensaios que não devem virar evidência.
- `--summarize-only` reconstrói `summary.json` a partir das execuções existentes.
- `--campaign <nome>` marca a execução como parte de uma campanha (ex.: `escala`). O volume é **medido** nos dois bancos (soma dos painéis semanais da janela do dataset) e precisa ser igual; caso contrário, nada é medido.
- `--prewarm K` faz K passadas completas pelas leituras antes dos aquecimentos, gravadas como `phase=prewarm` e excluídas das estatísticas; o E1 usa nelas UUIDs que nunca são medidos. A campanha de escala usa `--prewarm 30`; execuções `main` de campanha sem pré-aquecimento ficam no disco como piloto e não entram no resumo.

## Campanha de escala

Em cada volume (1 M antes da ampliação; depois cada marco validado), com a API ociosa:

```powershell
python scripts/validation/check_bulk.py --target <N>      # integridade (inclui nodetool flush)
python scripts/loading/reconcile_rollup.py              # rollup == verdade == PostgreSQL
# VACUUM (ANALYZE) no PostgreSQL e 0 compactações pendentes no Cassandra
python benchmarks/run_benchmarks.py --suite main --campaign escala --prewarm 30
python scripts/run_api.py stop; python scripts/run_api.py start --pg-synchronous-commit off
python benchmarks/run_benchmarks.py --suite durability --campaign escala
python scripts/run_api.py stop; python scripts/run_api.py start
```

## Regras

- Não usar a duração dos healthchecks como benchmark: ela inclui abertura de conexão e consultas diferentes.
- Não remover índices, não relaxar durabilidade sem declarar e não descartar amostras desfavoráveis. A variante `durability` existe justamente para expor a assimetria de `fsync`, e não para favorecer um lado.
- As escritas usam a janela reservada 07–14/01/2002. O executor recusa rodar se ela não estiver vazia e, ao final, exclui pela API apenas os UUIDs que criou.
- Execuções anteriores são evidência: não as apague. Uma nova execução cria uma pasta nova; o `summary.json` aponta para a última execução completa de cada suíte no seu grupo (histórico ou campanha + volume).
- Depois que a massa cresce, não existe mais "1 M": consultas restritas aos eventos antigos não substituem uma medição feita com a base de exatamente 1 M.
