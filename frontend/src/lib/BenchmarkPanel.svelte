<script lang="ts">
  import { onMount } from 'svelte'
  import BenchmarkChart from './BenchmarkChart.svelte'
  import { ApiError, getBenchmarks, SOURCE_LABEL, SOURCES, type BenchmarkSummary, type ControlEntry, type Operation, type Writes } from './api'
  import { fmtInt, fmtMs, fmtRatio, fmtUtc } from './format'

  let status = $state<'loading' | 'ready' | 'missing' | 'error'>('loading')
  let summary = $state<BenchmarkSummary | null>(null)
  let message = $state('')

  async function load() {
    status = 'loading'
    try {
      summary = (await getBenchmarks()).data
      status = 'ready'
    } catch (e) {
      const err = e instanceof ApiError ? e : null
      status = err?.kind === 'not_found' ? 'missing' : 'error'
      message = err?.message ?? 'Falha inesperada.'
    }
  }
  onMount(load)

  const main = $derived(summary?.main ?? null)
  const env = $derived((main?.environment ?? {}) as Record<string, any>)
  const reads = $derived(main?.operations ?? [])
  const n1 = $derived(summary?.n1 ? summary.n1.operations : [])
  const control = $derived((main?.pg_control ?? {}) as Record<string, ControlEntry>)
  const rollup = $derived(reads.find((o) => o.id === 'overview_7d'))
  // The dedicated `writes`/`durability` suites (pool >= clients, warm-up rounds) supersede E6 inside `main`.
  const writeSets = $derived([
    { label: 'Configuração padrão', run: summary?.writes ?? main,
      note: 'PostgreSQL synchronous_commit=on (fsync do WAL a cada commit) × Cassandra commitlog periódico (fsync a cada 10 s)' },
    { label: 'Confirmação antes do fsync nos dois bancos', run: summary?.durability,
      note: 'PostgreSQL synchronous_commit=off. Janela de perda em uma queda: PostgreSQL ≈ 3 × wal_writer_delay (~0,6 s), Cassandra até ~10 s; nenhum dos dois corrompe dados' },
  ].map((x) => ({ ...x, w: x.run?.writes })).filter((x): x is typeof x & { w: Writes } => !!x.w))
  const iqr = (o: Operation, s: 'postgresql' | 'cassandra') => {
    const h = o.sources[s].http
    return h ? `${fmtMs(h.p25)} – ${fmtMs(h.p75)}` : '—'
  }
</script>

{#if status === 'loading'}
  <p class="state">Carregando resultados medidos…</p>
{:else if status === 'missing'}
  <div class="state"><strong>Nenhum benchmark executado.</strong> Rode <code>python benchmarks/run_benchmarks.py</code> com a API em build release. Nada é exibido sem medição real.</div>
{:else if status === 'error'}
  <div class="state error" role="alert">Não foi possível carregar os resultados: {message} <button class="ghost" onclick={load}>Tentar novamente</button></div>
{:else if main}
  <div class="protocol">
    <div><span>Execução</span><strong class="mono">{main.run_id}</strong><small>{fmtUtc(main.finished_at)} UTC · {main.complete ? 'completa' : 'incompleta'}</small></div>
    <div><span>Protocolo</span><strong>{main.protocol.runs} medições + {main.protocol.warmup} aquecimentos</strong><small>por operação e banco · pares intercalados, ordem alternada · cache quente</small></div>
    <div><span>Hardware</span><strong>{env.host?.cpu_model ?? env.host?.processor ?? '—'}</strong><small>{env.host?.logical_cpus} CPUs lógicas · {env.host?.ram_total_gib} GiB RAM · VM Docker {env.docker?.vm_cpus} vCPU / {env.docker?.vm_memory_gib} GiB</small></div>
    <div><span>Versões</span><strong>PostgreSQL {(env.postgresql?.version ?? '').split(' ')[1] ?? '—'} · Cassandra {env.cassandra?.version ?? '—'}</strong><small>API {main.protocol.api_build} · leituras canônicas concorrentes = {main.protocol.cassandra_read_concurrency}</small></div>
    <div><span>Massa</span><strong>{fmtInt(Number(env.dataset?.logical_events ?? 0))} eventos lógicos</strong><small>{fmtInt(Number(env.postgresql?.events_rows ?? 0))} linhas em events (PG) · mesma massa nos dois bancos</small></div>
  </div>

  <h3>Leituras e painel · mediana HTTP (escala log)</h3>
  <BenchmarkChart operations={reads} />

  <details class="table-view" open>
    <summary>Tabela completa (HTTP no cliente e tempo de banco via Server-Timing)</summary>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Operação</th><th>PG mediana</th><th>PG p25–p75</th><th>CS mediana</th><th>CS p25–p75</th><th>Banco PG / CS</th><th>Mais rápido</th><th>Pares vencidos</th><th>Resultado igual</th></tr></thead>
        <tbody>
          {#each reads as o (o.id)}
            <tr>
              <td>{o.experiment} · {o.title}</td>
              <td class="num">{fmtMs(o.sources.postgresql.http?.median)}</td><td class="num muted">{iqr(o, 'postgresql')}</td>
              <td class="num">{fmtMs(o.sources.cassandra.http?.median)}</td><td class="num muted">{iqr(o, 'cassandra')}</td>
              <td class="num muted">{fmtMs(o.sources.postgresql.db?.median)} / {fmtMs(o.sources.cassandra.db?.median)}</td>
              <td>{o.faster ? SOURCE_LABEL[o.faster] : '—'} <strong>{fmtRatio(o.ratio)}</strong></td>
              <td class="num">{o.faster ? `${o.paired_wins[o.faster]}/${o.sources.postgresql.http?.n}` : '—'}</td>
              <td>{o.equivalent ? '✓ idêntico' : '✗ diverge'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </details>

  <div class="insights">
    <article>
      <h4>Onde o Cassandra vence</h4>
      <p>Painel agregado (E4): a tabela <code>event_counts_by_day</code> foi modelada para a pergunta do painel e é mantida no momento da escrita (contadores). A consulta lê ≤ 7 partições pequenas; o PostgreSQL normalizado agrega ~245 mil entradas de índice a cada leitura. O ganho mede a <strong>pré-agregação</strong>, natural no modelo orientado a consultas: pré-agregado (E5), o PostgreSQL também lê na casa de 1 ms, mas depende de REFRESH completo.</p>
    </article>
    <article>
      <h4>Onde o PostgreSQL vence</h4>
      <p>Leituras por chave e páginas Q1–Q3 (E1–E3): um índice B-tree devolve a página com colunas completas em uma consulta. No Cassandra, cada projeção guarda só chaves imutáveis e o conteúdo vem do registro canônico (1 + até 101 leituras por página), escolha que evita divergência em UPDATE.</p>
    </article>
  </div>

  {#if n1.length}
    <h3>Otimização do N+1 no Cassandra (mesma API, mesmo resultado)</h3>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Operação</th><th>Antes: leituras sequenciais</th><th>Depois: concorrência {main.protocol.cassandra_read_concurrency}</th><th>Ganho</th><th>PostgreSQL (referência)</th></tr></thead>
        <tbody>
          {#each n1 as before (before.id)}
            {@const after = reads.find((o) => o.id === before.id)}
            {@const b = before.sources.cassandra.http?.median}
            {@const a = after?.sources.cassandra.http?.median}
            <tr><td>{before.title}</td><td class="num">{fmtMs(b)}</td><td class="num">{fmtMs(a)}</td><td class="num"><strong>{b && a ? fmtRatio(b / a) : '—'}</strong></td><td class="num muted">{fmtMs(after?.sources.postgresql.http?.median)}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}

  {#if control.pg_mv_read_7d}
    <h3>Controle E5 · e se o PostgreSQL também pré-agregasse?</h3>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Medida (painel 7 dias)</th><th>Mediana</th><th>p95</th><th>Nível de medição</th></tr></thead>
        <tbody>
          <tr><td>PostgreSQL · agregação na leitura (índice de cobertura)</td><td class="num">{fmtMs(control.pg_on_read_aggregate_7d?.stats?.median)}</td><td class="num">{fmtMs(control.pg_on_read_aggregate_7d?.stats?.p95)}</td><td class="muted">psql \timing</td></tr>
          <tr><td>PostgreSQL · leitura de view materializada</td><td class="num">{fmtMs(control.pg_mv_read_7d?.stats?.median)}</td><td class="num">{fmtMs(control.pg_mv_read_7d?.stats?.p95)}</td><td class="muted">psql \timing</td></tr>
          <tr><td>PostgreSQL · REFRESH completo da view (1 M eventos)</td><td class="num">{fmtMs(control.pg_mv_refresh_full?.stats?.median)}</td><td class="num">{fmtMs(control.pg_mv_refresh_full?.stats?.p95)}</td><td class="muted">psql \timing</td></tr>
          <tr><td>Cassandra · leitura do rollup</td><td class="num">{fmtMs(rollup?.sources.cassandra.db?.median)}</td><td class="num">{fmtMs(rollup?.sources.cassandra.db?.p95)}</td><td class="muted">Server-Timing (driver)</td></tr>
        </tbody>
      </table>
    </div>
    <p class="caption">Leitura honesta: com uma view materializada, o PostgreSQL lê o painel na mesma ordem de grandeza do rollup (fronteiras de medição diferentes: psql × driver), mas o resultado fica desatualizado até o próximo REFRESH completo, cujo custo cresce com a tabela. O rollup Cassandra é incremental a cada escrita (contadores não idempotentes, corrigidos por reconciliação) e seu custo aparece no CREATE do E6.</p>
  {/if}

  {#if writeSets.length}
    <h3>Escritas CRUD concorrentes (E6) · {writeSets[0].w.concurrency} clientes, {writeSets[0].w.runs} × {writeSets[0].w.events_per_run} eventos{writeSets[0].w.warmup_runs ? ` + ${writeSets[0].w.warmup_runs} rodadas de aquecimento` : ''}</h3>
    {#each writeSets as set}
      <p class="caption"><strong>{set.label}.</strong> {set.note}. <span class="mono muted">{set.run?.run_id} · pool PG {set.run?.protocol.postgres_pool_size ?? 5}</span></p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Operação</th>{#each SOURCES as s}<th>{SOURCE_LABEL[s]} mediana</th><th>{SOURCE_LABEL[s]} ops/s</th>{/each}</tr></thead>
          <tbody>
            {#each (['create', 'update', 'delete'] as const) as op}
              <tr><td>{op.toUpperCase()}</td>
                {#each SOURCES as s}
                  <td class="num">{fmtMs(set.w.ops[op][s].latency?.median)}</td>
                  <td class="num muted">{fmtInt(Math.round(set.w.ops[op][s].throughput_ops_s?.median ?? 0))}</td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/each}
    <p class="caption">O CREATE Cassandra inclui 2 LWT (Paxos), logged batch das projeções e o contador do rollup. A vantagem de escrita do Cassandra na configuração padrão desaparece quando os dois bancos confirmam antes do fsync do log: ela é explicada pela política de durabilidade, não pelo modelo de dados. Pool PostgreSQL ≥ número de clientes (uma execução anterior com pool 5 fica registrada em benchmarks/results).</p>
  {/if}
{/if}

<style>
  .protocol { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; margin-bottom: 22px; }
  .protocol > div { background: var(--surface-2); padding: 12px 14px; display: grid; gap: 3px; }
  .protocol span { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
  .protocol strong { font-size: 13px; color: var(--text); font-weight: 600; }
  .protocol small { font-size: 11.5px; color: var(--text-2); }
  h3 { font-size: 14px; font-weight: 600; margin: 26px 0 12px; color: var(--text); }
  .table-view { margin-top: 14px; }
  .table-view summary { cursor: pointer; font-size: 12px; color: var(--text-2); margin-bottom: 8px; }
  .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; min-width: 640px; }
  th { text-align: left; font-weight: 500; color: var(--muted); padding: 8px 10px; border-bottom: 1px solid var(--line); background: var(--surface-2); }
  td { padding: 8px 10px; border-bottom: 1px solid var(--grid); color: var(--text-2); }
  tr:last-child td { border-bottom: 0; }
  td strong { color: var(--text); }
  .num { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .muted { color: var(--muted); }
  .mono { font-family: var(--mono); font-size: 12px; }
  .insights { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-top: 18px; }
  .insights article { border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; background: var(--surface-2); }
  .insights h4 { margin: 0 0 6px; font-size: 13px; }
  .insights p { font-size: 12.5px; color: var(--text-2); line-height: 1.55; }
  .caption { font-size: 12px; color: var(--text-2); margin: 10px 0; line-height: 1.55; }
  .state { color: var(--muted); font-size: 13px; padding: 18px 0; line-height: 1.6; }
  .state.error { color: var(--critical-text); }
  code { font-family: var(--mono); font-size: 12px; background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
</style>
