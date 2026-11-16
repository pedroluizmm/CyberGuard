# Benchmarks

Experimentos comparativos PostgreSQL × Cassandra sobre a mesma massa de 1 M de eventos. A metodologia, os resultados e a interpretação estão em [docs/benchmark-methodology.md](../docs/benchmark-methodology.md).

| Arquivo | Conteúdo |
| --- | --- |
| `run_benchmarks.py` | Executor (suítes `main`, `n1`, `writes`, `durability`). Exige a API em build release e confere a configuração dela em `/api/runtime` antes de medir, inclusive pool PostgreSQL ≥ número de clientes de escrita |
| `sql/pg_rollup_control.sql` | Controle E5: view materializada no schema `bench`. É aditiva e não faz parte da aplicação |
| `results/<UTC>-<suite>/raw.csv` | Uma linha por requisição de leitura: fase, iteração, ordem no par, status, `http_ms`, `db_ms`, itens e hash do corpo |
| `results/<UTC>-<suite>/raw_writes.csv` | Latência de cada CREATE/UPDATE/DELETE do E6, com a fase (`warmup`/`measure`) |
| `results/<UTC>-<suite>/environment.json` | Hardware, Docker, imagens, limites, versões, configurações, índices, tamanhos, git e runtime da API |
| `results/<UTC>-<suite>/run.json` | Estatísticas por operação (mediana, p25/p75/p95, pares vencidos, equivalência) |
| `results/summary.json` | Última execução completa de cada suíte. É servido ao dashboard por `GET /api/benchmarks/summary` |

## Executar

```powershell
python scripts/run_api.py build && python scripts/run_api.py start
python benchmarks/run_benchmarks.py --suite main          # E1-E6 (~2 min)
```

A suíte `writes` repete só o E6 com a configuração padrão. Para as variantes, reinicie a API com `--read-concurrency 1` (suíte `n1`) ou com `--pg-synchronous-commit off` (suíte `durability`). O E6 exige `POSTGRES_POOL_SIZE` ≥ `--write-concurrency` (padrões 16 e 8) e usa `--write-warmup` rodadas descartadas (padrão 2). Detalhes em `python benchmarks/run_benchmarks.py --help`.

- `--runs` (padrão 30, mínimo 10) e `--warmup` (padrão 5) controlam as repetições.
- `--results-dir` grava em outra pasta, útil para ensaios que não devem virar evidência.
- `--summarize-only` reconstrói `summary.json` a partir das execuções existentes.

## Regras

- Não usar a duração dos healthchecks como benchmark: ela inclui abertura de conexão e consultas diferentes.
- Não remover índices, não relaxar durabilidade sem declarar e não descartar amostras desfavoráveis. A variante `durability` existe justamente para expor a assimetria de `fsync`, e não para favorecer um lado.
- As escritas usam a janela reservada 07–14/01/2002. O executor recusa rodar se ela não estiver vazia e, ao final, exclui pela API apenas os UUIDs que criou.
- Execuções anteriores são evidência: não as apague. Uma nova execução cria uma pasta nova e o `summary.json` passa a apontar para ela.
