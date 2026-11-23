<script lang="ts">
  import BenchmarkChart from './BenchmarkChart.svelte'
  import Icon from './Icon.svelte'
  import { SOURCE_LABEL, SOURCES, type ControlEntry, type Operation, type RunSet, type Writes } from './api'
  import { fmtBytes, fmtEvents, fmtInt, fmtMs, fmtRatio, fmtShare, fmtUtc } from './format'

  // One recorded scenario (historic 1M or one size of the scale campaign). Every value comes from
  // benchmarks/results/summary.json, served read-only by the API; nothing here is measured live.
  let { set }: { set: RunSet } = $props()

  const summary = $derived(set)
  const main = $derived(set.main)
  const env = $derived((main?.environment ?? {}) as Record<string, any>)
  const size = $derived(Number(env.dataset?.logical_events ?? main?.logical_events ?? 0))
  const reads = $derived(main?.operations ?? [])
  const n1 = $derived(summary?.n1 ? summary.n1.operations : [])
  const cache = $derived((main?.cache?.read_phase ?? null) as Record<string, any> | null)
  const diskRead = $derived(cache?.disk_read_bytes ? Object.values(cache.disk_read_bytes as Record<string, number>).reduce((a, b) => a + b, 0) : null)
  const power = $derived((env.host?.power ?? null) as { on_ac_power?: boolean; battery_percent?: number; power_plan?: string } | null)
  const control = $derived((main?.pg_control ?? {}) as Record<string, ControlEntry>)
  const rollup = $derived(reads.find((o) => o.id === 'overview_7d'))
  const pgWins = $derived(reads.filter((o) => o.faster === 'postgresql'))
  const csWins = $derived(reads.filter((o) => o.faster === 'cassandra'))
  const equivalent = $derived(reads.filter((o) => o.equivalent).length)
  const range = (ops: Operation[]) => {
    const r = ops.map((o) => o.ratio ?? 0).filter((v) => v > 0)
    return r.length ? `${fmtRatio(Math.min(...r)).replace('×', '')}–${fmtRatio(Math.max(...r))}` : '—'
  }
  // The dedicated `writes`/`durability` suites (pool >= clients, warm-up rounds) supersede E6 inside `main`.
  const writeSets = $derived([
    { label: 'Configuração padrão', run: summary?.writes ?? main,
      note: 'PostgreSQL synchronous_commit=on (fsync do WAL a cada commit) × Cassandra commitlog periódico (fsync a cada 10 s).' },
    { label: 'Confirmação antes do fsync nos dois bancos', run: summary?.durability,
      note: 'PostgreSQL synchronous_commit=off. Janela de perda em uma queda: PostgreSQL ≈ 3 × wal_writer_delay (~0,6 s), Cassandra até ~10 s; nenhum dos dois corrompe dados.' },
  ].map((x) => ({ ...x, w: x.run?.writes })).filter((x): x is typeof x & { w: Writes } => !!x.w))
  const createMedian = (w: Writes, s: 'postgresql' | 'cassandra') => w.ops.create[s].latency?.median
  const iqr = (o: Operation, s: 'postgresql' | 'cassandra') => {
    const h = o.sources[s].http
    return h ? `${fmtMs(h.p25)} – ${fmtMs(h.p75)}` : '—'
  }
</script>

{#if main}
  <section class="highlights" aria-label="Destaques dos resultados">
    {#if rollup?.faster}
      <article class="card hl nosql">
        <p class="hl-kicker"><Icon name="layers" size={15} />Cenário favorável ao NoSQL · E4</p>
        <p class="hl-value">{fmtRatio(rollup.ratio)}<small>{SOURCE_LABEL[rollup.faster]}</small></p>
        <p class="hl-text">Painel de 7 dias ({fmtInt(rollup.sources.postgresql.items ?? 0)} eventos): {fmtMs(rollup.sources.cassandra.http?.median)} × {fmtMs(rollup.sources.postgresql.http?.median)}.</p>
        <p class="hl-caveat">Rollup pré-agregado na escrita × agregação na leitura. Mede a pré-agregação, não a velocidade bruta do motor.</p>
      </article>
    {/if}
    {#if pgWins.length}
      <article class="card hl">
        <p class="hl-kicker"><Icon name="search" size={15} />Buscas por chave · E1–E3</p>
        <p class="hl-value">{range(pgWins)}<small>PostgreSQL</small></p>
        <p class="hl-text">Mais rápido em {pgWins.length} de {reads.length} leituras: o índice B-tree devolve a página completa em uma consulta.</p>
        <p class="hl-caveat">No Cassandra, cada resultado exige uma leitura do registro canônico.</p>
      </article>
    {/if}
    {#if control.pg_mv_read_7d?.stats}
      <article class="card hl">
        <p class="hl-kicker"><Icon name="flask" size={15} />Controle · E5</p>
        <p class="hl-value">{fmtMs(control.pg_mv_read_7d.stats.median)}</p>
        <p class="hl-text">PostgreSQL lendo uma view materializada: mesma ordem de grandeza do rollup (fronteiras de medição diferentes).</p>
        <p class="hl-caveat">Custo: REFRESH completo de {fmtMs(control.pg_mv_refresh_full?.stats?.median)} e dados desatualizados entre REFRESHes.</p>
      </article>
    {/if}
    {#if writeSets.length === 2}
      <article class="card hl">
        <p class="hl-kicker"><Icon name="zap" size={15} />Escritas concorrentes · E6</p>
        <p class="hl-value small">Depende do fsync</p>
        <p class="hl-text">CREATE padrão: Cassandra {fmtMs(createMedian(writeSets[0].w, 'cassandra'))} × PostgreSQL {fmtMs(createMedian(writeSets[0].w, 'postgresql'))}.
          Com os dois confirmando antes do fsync: PostgreSQL {fmtMs(createMedian(writeSets[1].w, 'postgresql'))} × Cassandra {fmtMs(createMedian(writeSets[1].w, 'cassandra'))}.</p>
        <p class="hl-caveat">A vantagem padrão do Cassandra vem da política de durabilidade, não do modelo.</p>
      </article>
    {/if}
  </section>

  <section class="card">
    <div class="card-head">
      <div><h2>Protocolo e ambiente</h2><p>Registrados em environment.json e run.json de cada execução</p></div>
      <div class="aside">
        <span class="badge {equivalent === reads.length ? 'ok' : 'bad'}"><Icon name={equivalent === reads.length ? 'check' : 'x'} size={13} />{equivalent}/{reads.length} operações com resposta idêntica</span>
        <span class="badge">{csWins.length} favoráveis ao Cassandra · {pgWins.length} ao PostgreSQL</span>
      </div>
    </div>
    <dl class="protocol">
      <div><dt>Execução</dt><dd class="mono">{main.run_id}</dd><dd class="sub">{fmtUtc(main.finished_at)} UTC · {main.complete ? 'completa' : 'incompleta'}</dd></div>
      <div><dt>Protocolo</dt><dd>{main.protocol.runs} medições + {main.protocol.warmup} aquecimentos</dd><dd class="sub">por operação e banco · pares intercalados, ordem alternada · cache quente{Number(main.protocol.prewarm_passes) ? ` · ${main.protocol.prewarm_passes} passadas de pré-aquecimento descartadas` : ''}</dd></div>
      <div><dt>Hardware</dt><dd>{env.host?.cpu_model ?? env.host?.processor ?? '—'}</dd><dd class="sub">{env.host?.logical_cpus} CPUs lógicas · {env.host?.ram_total_gib} GiB · VM Docker {env.docker?.vm_cpus} vCPU / {env.docker?.vm_memory_gib} GiB{power ? ` · ${power.on_ac_power ? 'na tomada' : `na bateria (${power.battery_percent}%)`}, plano ${power.power_plan ?? '—'}` : ''}</dd></div>
      <div><dt>Versões</dt><dd>PostgreSQL {(env.postgresql?.version ?? '').split(' ')[1] ?? '—'} · Cassandra {env.cassandra?.version ?? '—'}</dd><dd class="sub">API {main.protocol.api_build} · leituras canônicas concorrentes = {main.protocol.cassandra_read_concurrency} · 1 nó Cassandra (RF=1)</dd></div>
      <div><dt>Massa</dt><dd>{fmtInt(size)} eventos lógicos</dd><dd class="sub">{fmtInt(Number(env.postgresql?.events_rows ?? 0))} linhas em events (PG){env.postgresql?.database_bytes ? ` · banco PG ${fmtBytes(Number(env.postgresql.database_bytes))}` : ''}{env.cassandra?.du_bytes?.['/var/lib/cassandra/data/cyberguard'] ? ` · keyspace Cassandra ${fmtBytes(Number(env.cassandra.du_bytes['/var/lib/cassandra/data/cyberguard']))}` : ''}</dd></div>
      {#if cache}
        <div><dt>Cache na fase de leitura</dt><dd>PG {fmtShare(cache.postgresql_shared_buffers?.hit_ratio)} · Cassandra {fmtShare(cache.cassandra_key_cache?.hit_ratio)}</dd><dd class="sub">acertos em shared_buffers (PG) e no key cache (Cassandra){diskRead !== null ? ` · leitura de disco dos contêineres: ${fmtBytes(diskRead)}` : ''}</dd></div>
      {/if}
    </dl>
  </section>

  <section class="card">
    <div class="card-head">
      <div><h2>Leituras e painel · mediana HTTP</h2><p>Escala logarítmica · 30 execuções por banco · razão = mediana do mais lento ÷ mediana do mais rápido</p></div>
    </div>
    <BenchmarkChart operations={reads} />
    <details class="table-view" open>
      <summary>Tabela completa (HTTP no cliente e tempo de banco via Server-Timing)</summary>
      <div class="table-wrap">
        <table class="table wide">
          <thead><tr><th>Operação</th><th class="num">PG mediana</th><th class="num">PG p25–p75</th><th class="num">CS mediana</th><th class="num">CS p25–p75</th><th class="num">Banco PG / CS</th><th>Mais rápido</th><th class="num">Pares</th><th>Resultado</th></tr></thead>
          <tbody>
            {#each reads as o (o.id)}
              <tr class:nosql={o.faster === 'cassandra'}>
                <td><span class="exp">{o.experiment}</span> {o.title}</td>
                <td class="num">{fmtMs(o.sources.postgresql.http?.median)}</td><td class="num muted">{iqr(o, 'postgresql')}</td>
                <td class="num">{fmtMs(o.sources.cassandra.http?.median)}</td><td class="num muted">{iqr(o, 'cassandra')}</td>
                <td class="num muted">{fmtMs(o.sources.postgresql.db?.median)} / {fmtMs(o.sources.cassandra.db?.median)}</td>
                <td>{o.faster ? SOURCE_LABEL[o.faster] : '—'} <strong>{fmtRatio(o.ratio)}</strong></td>
                <td class="num">{o.faster ? `${o.paired_wins[o.faster]}/${o.sources.postgresql.http?.n}` : '—'}</td>
                <td>{#if o.equivalent}<span class="ok-text"><Icon name="check" size={13} />idêntico</span>{:else}<span class="bad-text">diverge</span>{/if}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </details>
  </section>

  <div class="two">
    {#if control.pg_mv_read_7d}
      <section class="card">
        <div class="card-head"><div><h2>Controle E5 · PostgreSQL também pré-agregado</h2><p>Painel 7 dias · {String(control.level ?? 'psql \\timing')}</p></div></div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Medida</th><th class="num">Mediana</th><th class="num">p95</th><th>Fronteira</th></tr></thead>
            <tbody>
              <tr><td>PG · agregação na leitura</td><td class="num">{fmtMs(control.pg_on_read_aggregate_7d?.stats?.median)}</td><td class="num">{fmtMs(control.pg_on_read_aggregate_7d?.stats?.p95)}</td><td class="muted">psql</td></tr>
              <tr><td>PG · view materializada</td><td class="num"><strong>{fmtMs(control.pg_mv_read_7d?.stats?.median)}</strong></td><td class="num">{fmtMs(control.pg_mv_read_7d?.stats?.p95)}</td><td class="muted">psql</td></tr>
              <tr><td>PG · REFRESH completo ({fmtEvents(size)})</td><td class="num">{fmtMs(control.pg_mv_refresh_full?.stats?.median)}</td><td class="num">{fmtMs(control.pg_mv_refresh_full?.stats?.p95)}</td><td class="muted">psql</td></tr>
              <tr><td>Cassandra · rollup</td><td class="num"><strong>{fmtMs(rollup?.sources.cassandra.db?.median)}</strong></td><td class="num">{fmtMs(rollup?.sources.cassandra.db?.p95)}</td><td class="muted">Server-Timing</td></tr>
            </tbody>
          </table>
        </div>
        <p class="note">Com view materializada, o PostgreSQL lê na mesma ordem de grandeza, mas o resultado fica desatualizado até o próximo REFRESH completo. O rollup Cassandra é incremental (contadores não idempotentes, corrigidos por reconciliação) e seu custo aparece no CREATE do E6.</p>
      </section>
    {/if}
    {#if n1.length}
      <section class="card">
        <div class="card-head"><div><h2>Otimização do N+1 no Cassandra</h2><p>Mesma API e mesmo resultado · mediana HTTP</p></div></div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Operação</th><th class="num">Sequencial</th><th class="num">Concorrência {main.protocol.cassandra_read_concurrency}</th><th class="num">Ganho</th><th class="num">PG</th></tr></thead>
            <tbody>
              {#each n1 as before (before.id)}
                {@const after = reads.find((o) => o.id === before.id)}
                {@const b = before.sources.cassandra.http?.median}
                {@const a = after?.sources.cassandra.http?.median}
                <tr><td><span class="exp">{before.experiment}</span> {before.title.split(' (')[0]}</td><td class="num">{fmtMs(b)}</td><td class="num">{fmtMs(a)}</td><td class="num"><strong>{b && a ? fmtRatio(b / a) : '—'}</strong></td><td class="num muted">{fmtMs(after?.sources.postgresql.http?.median)}</td></tr>
              {/each}
            </tbody>
          </table>
        </div>
        <p class="note">O ganho é grande, mas não inverte E1–E3: a leitura canônica por resultado continua existindo.</p>
      </section>
    {/if}
  </div>

  {#if writeSets.length}
    <section class="card">
      <div class="card-head">
        <div><h2>Escritas CRUD concorrentes (E6)</h2><p>{writeSets[0].w.concurrency} clientes · {writeSets[0].w.runs} rodadas × {writeSets[0].w.events_per_run} eventos{writeSets[0].w.warmup_runs ? ` + ${writeSets[0].w.warmup_runs} de aquecimento` : ''} · mediana de latência e vazão</p></div>
      </div>
      <div class="two">
        {#each writeSets as set (set.label)}
          <div class="write-set">
            <h3>{set.label}</h3>
            <p class="note">{set.note} <span class="mono">{set.run?.run_id} · pool PG {set.run?.protocol.postgres_pool_size ?? 5}</span></p>
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>Operação</th>{#each SOURCES as s (s)}<th class="num">{SOURCE_LABEL[s]}</th><th class="num">ops/s</th>{/each}</tr></thead>
                <tbody>
                  {#each (['create', 'update', 'delete'] as const) as op (op)}
                    {@const pg = set.w.ops[op].postgresql.latency?.median ?? Infinity}
                    {@const cs = set.w.ops[op].cassandra.latency?.median ?? Infinity}
                    <tr><td>{op.toUpperCase()}</td>
                      {#each SOURCES as s (s)}
                        <td class="num">{#if (s === 'postgresql' ? pg < cs : cs < pg)}<strong>{fmtMs(set.w.ops[op][s].latency?.median)}</strong>{:else}{fmtMs(set.w.ops[op][s].latency?.median)}{/if}</td>
                        <td class="num muted">{fmtInt(Math.round(set.w.ops[op][s].throughput_ops_s?.median ?? 0))}</td>
                      {/each}
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </div>
        {/each}
      </div>
      <p class="note">Em negrito, a menor mediana de cada linha. O CREATE Cassandra inclui 2 LWT (Paxos), logged batch das projeções e o contador do rollup. Pool PostgreSQL ≥ número de clientes{summary.n1 ? '; uma execução anterior com pool 5 fica registrada em benchmarks/results' : ''}.</p>
    </section>
  {/if}

  <section class="card limits">
    <div class="card-head"><div><h2>Limitações declaradas</h2><p>O que estes números não demonstram</p></div></div>
    <ul>
      <li><strong>Um nó Cassandra (RF=1):</strong> não mede escalabilidade horizontal, replicação nem tolerância a falhas.</li>
      <li><strong>Cache quente</strong> e recursos compartilhados e assimétricos (5 GiB × 2 GiB), na mesma máquina.</li>
      <li><strong>Massa sintética</strong> de {fmtEvents(size)}; valores absolutos variam entre execuções e com o estado do host (energia, processos), os vencedores se repetem.</li>
    </ul>
  </section>
{/if}

<style>
  .highlights { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
  .hl { display: flex; flex-direction: column; gap: 8px; }
  .hl.nosql { background: var(--hero); border-color: var(--hero-line); }
  .hl-kicker { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-2); font-weight: 550; }
  .hl.nosql .hl-kicker { color: #c3cde0; }
  .hl-value { font-size: 34px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.05; margin-top: 4px; }
  .hl-value.small { font-size: 22px; letter-spacing: -0.02em; }
  .hl-value small { font-size: 13px; font-weight: 550; color: var(--text-2); margin-left: 8px; letter-spacing: 0; }
  .hl.nosql .hl-value small { color: #c3cde0; }
  .hl-text { font-size: 12.5px; color: var(--text-2); line-height: 1.55; }
  .hl.nosql .hl-text { color: #d5ddeb; }
  .hl-caveat { margin-top: auto; padding-top: 10px; border-top: 1px solid var(--line-soft); font-size: 11.5px; color: var(--muted); line-height: 1.5; }
  .hl.nosql .hl-caveat { border-color: var(--hero-line); color: #c3cde0; }

  .protocol { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 1px; background: var(--line-soft); border: 1px solid var(--line-soft); border-radius: 12px; overflow: hidden; }
  .protocol > div { background: var(--card); padding: 13px 15px; display: grid; gap: 3px; align-content: start; }
  .protocol > div:last-child { grid-column-end: -1; }
  .protocol dt { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }
  .protocol dd { font-size: 13px; color: var(--text); font-weight: 550; }
  .protocol dd.mono { font-size: 12px; }
  .protocol dd.sub { font-size: 11.5px; color: var(--text-2); font-weight: 400; line-height: 1.45; }

  .two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
  .write-set { display: grid; gap: 10px; align-content: start; }
  .write-set h3 { font-size: 13.5px; font-weight: 600; }
  .wide { min-width: 860px; }
  .table { min-width: 460px; }
  .exp { font-family: var(--mono); font-size: 11px; color: var(--muted); margin-right: 4px; }
  tr.nosql td:first-child { box-shadow: inset 3px 0 0 var(--steel); }
  .ok-text { display: inline-flex; align-items: center; gap: 5px; color: var(--good); }
  .bad-text { color: var(--critical-text); }
  .note { margin-top: 12px; }
  .write-set .note { margin-top: 0; }
  .limits ul { margin: 0; padding-left: 18px; display: grid; gap: 6px; }
  .limits li { font-size: 13px; color: var(--text-2); line-height: 1.55; }
  .limits li::marker { color: var(--steel); }
  .limits strong { color: var(--text); font-weight: 600; }

  @media (max-width: 1360px) { .highlights { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 1100px) { .two { grid-template-columns: 1fr; } }
  @media (max-width: 560px) { .highlights { grid-template-columns: 1fr; } }
</style>
