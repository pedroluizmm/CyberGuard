<script lang="ts">
  import Icon from './Icon.svelte'
  import {
    ApiError, canonicalJson, CATEGORY_LABEL, getOverview, getPage, queryPath, SOURCE_ICON, SOURCE_KIND, SOURCE_LABEL, SOURCES,
    type Category, type Source, type Timed,
  } from './api'
  import { fmtMs, fmtPeriod, fmtRatio, median } from './format'

  let { from, to, days, category, severity }: { from: string; to: string; days: number; category: Category | null; severity: number | null } = $props()

  type Mode = 'overview' | 'device' | 'alerts'
  const modes: { id: Mode; label: string; exp: string; hint: string }[] = [
    { id: 'overview', label: 'Painel agregado', exp: 'E4', hint: 'Totais por hora, categoria e severidade com os filtros atuais. Cassandra lê o rollup pré-agregado na escrita; PostgreSQL agrega na leitura.' },
    { id: 'device', label: 'Q1 · dispositivo', exp: 'E2', hint: 'Primeira página (100 eventos) da linha do tempo de ids-sensor-06. Busca por chave com paginação.' },
    { id: 'alerts', label: 'Q3 · alertas', exp: 'E3', hint: 'Primeira página (100 eventos) de alertas de severidade 3. Busca por chave com paginação.' },
  ]
  let mode = $state<Mode>('overview')
  let repetitions = $state(10)
  let running = $state(false)
  let progress = $state(0)
  let error = $state<string | null>(null)
  type Acc = { http: number[]; db: number[]; body: string | null }
  type Result = { mode: Mode; scope: string; acc: Record<Source, Acc>; warm: Record<Source, number | null>; equal: boolean }
  let result = $state<Result | null>(null)
  const total = $derived((repetitions + 1) * 2)

  const scopeText = () => mode === 'overview'
    ? `${fmtPeriod(from, to)} · ${category ? CATEGORY_LABEL[category] : 'todas as categorias'}${severity ? ` · severidade ${severity}` : ''}`
    : `${fmtPeriod(from, to)} · ${mode === 'device' ? 'device_id = ids-sensor-06' : 'severity = 3'} · página de 100`

  function execute(source: Source): Promise<Timed<unknown>> {
    if (mode === 'overview') return getOverview(source, { from, to, category, severity })
    if (mode === 'device') return getPage(queryPath(source, 'device', 'ids-sensor-06', from, to, 100))
    return getPage(queryPath(source, 'alerts', '3', from, to, 100))
  }

  async function run() {
    running = true
    error = null
    progress = 0
    const acc: Record<Source, Acc> = { postgresql: { http: [], db: [], body: null }, cassandra: { http: [], db: [], body: null } }
    const warm: Record<Source, number | null> = { postgresql: null, cassandra: null }
    const scope = scopeText()
    const runMode = mode
    try {
      // Pair 0 is a discarded warm-up (connections, prepared statements, caches),
      // as in the benchmark protocol; then interleaved pairs with alternating order.
      for (let i = 0; i <= repetitions; i++) {
        for (const source of i % 2 ? SOURCES : [...SOURCES].reverse()) {
          const r = await execute(source)
          acc[source].body ??= canonicalJson(r.raw)
          progress++
          if (i === 0) { warm[source] = r.httpMs; continue }
          acc[source].http.push(r.httpMs)
          if (r.dbMs !== null) acc[source].db.push(r.dbMs)
        }
      }
      result = { mode: runMode, scope, acc, warm, equal: acc.postgresql.body === acc.cassandra.body }
    } catch (e) {
      error = e instanceof ApiError ? `${e.message} (${e.code})` : 'Falha inesperada na comparação.'
    } finally {
      running = false
    }
  }

  const summary = $derived(result ? SOURCES.map((s) => ({
    s, http: median(result!.acc[s].http)!, db: median(result!.acc[s].db), raw: result!.acc[s].http,
    min: Math.min(...result!.acc[s].http), max: Math.max(...result!.acc[s].http),
  })) : [])
  // Scale from the medians so a single slow run cannot flatten both strips;
  // runs beyond the scale are pinned to the end of the track (value on hover).
  const scale = $derived(Math.max(0.001, ...summary.map((r) => r.http)) * 1.6)
  const pos = (v: number) => Math.min(100, (v / scale) * 100)
  const fastest = $derived(summary.length ? [...summary].sort((a, b) => a.http - b.http)[0] : null)
  const slowest = $derived(summary.length ? [...summary].sort((a, b) => b.http - a.http)[0] : null)
  const resultMode = $derived(result ? modes.find((m) => m.id === result!.mode)! : null)
</script>

<section class="card">
  <div class="card-head">
    <div><h2>Comparação ao vivo</h2><p>Mesma requisição HTTP, mesmos parâmetros e ordem alternada. O primeiro par é aquecimento e é descartado.</p></div>
  </div>
  <div class="controls">
    <div class="segmented" role="radiogroup" aria-label="Consulta a comparar">
      {#each modes as m (m.id)}
        <button role="radio" aria-checked={mode === m.id} class:on={mode === m.id} disabled={running} onclick={() => (mode = m.id)}>{m.label}<span class="exp">{m.exp}</span></button>
      {/each}
    </div>
    <label class="reps">Repetições
      <select bind:value={repetitions} disabled={running}><option value={5}>5</option><option value={10}>10</option><option value={20}>20</option></select>
    </label>
    <button class="btn primary" onclick={run} disabled={running}>
      {#if running}<span class="spinner"></span>Executando {progress}/{total}{:else}<Icon name="play" size={14} />Executar nos dois bancos{/if}
    </button>
  </div>
  <p class="hint"><Icon name="info" size={14} /><span>{modes.find((m) => m.id === mode)?.hint} <span class="scope">Escopo: {scopeText()}.</span></span></p>
  {#if running}
    <div class="progress" role="progressbar" aria-label="Progresso da comparação" aria-valuemin={0} aria-valuemax={total} aria-valuenow={progress}><span style:width={`${(progress / total) * 100}%`}></span></div>
  {/if}
</section>

{#if error}
  <div class="card state error" role="alert">
    <h2><span class="icon-wrap"><Icon name="alert" size={17} /></span>Comparação interrompida</h2>
    <p>{error}. Nenhum tempo parcial é exibido.</p>
    <button class="btn" onclick={run}><Icon name="refresh" size={15} />Executar novamente</button>
  </div>
{:else if !result}
  <div class="card state">
    <h2><span class="icon-wrap"><Icon name="compare" size={17} /></span>{running ? 'Executando as consultas…' : 'Nenhuma comparação executada nesta sessão'}</h2>
    <p>Os tempos aparecem aqui depois da execução real nos dois bancos. Nada é pré-carregado ou estimado: cada repetição é uma requisição à API.</p>
  </div>
{:else if fastest && slowest && resultMode}
  <div class="duel" class:stale={running} aria-live="polite">
    {#each summary as row (row.s)}
      <article class="card db" class:winner={fastest.s === row.s && fastest.s !== slowest.s} style:order={row.s === 'postgresql' ? 0 : 2}>
        <header>
          <span class="db-icon {row.s}"><Icon name={SOURCE_ICON[row.s]} size={18} /></span>
          <span class="db-name">{SOURCE_LABEL[row.s]}<small>{SOURCE_KIND[row.s]}</small></span>
          {#if fastest.s === row.s && fastest.s !== slowest.s}<span class="badge accent"><Icon name="zap" size={12} />mais rápido</span>{/if}
        </header>
        <p class="big">{fmtMs(row.http).replace(/\s?ms$/, '')}<small>ms</small></p>
        <p class="sub">mediana HTTP · banco {fmtMs(row.db)}</p>
        <div class="strip" aria-hidden="true">
          <span class="median {row.s}" style:left={`${pos(row.http)}%`}></span>
          {#each row.raw as v, i (i)}<span class="run {row.s}" class:pinned={v > scale} style:left={`${pos(v)}%`} title={`${fmtMs(v)}${v > scale ? ' (fora da escala)' : ''}`}></span>{/each}
        </div>
        <p class="range">{row.raw.length} execuções · mín. {fmtMs(row.min)} · máx. {fmtMs(row.max)}</p>
      </article>
    {/each}
    <article class="card verdict" style:order={1}>
      {#if fastest.s !== slowest.s}
        <p class="ratio">{fmtRatio(slowest.http / fastest.http)}</p>
        <p class="who"><strong>{SOURCE_LABEL[fastest.s]}</strong> mais rápido</p>
      {:else}
        <p class="who">Empate nas medianas</p>
      {/if}
      <p class="what">{resultMode.label} ({resultMode.exp})</p>
      <span class="badge {result.equal ? 'ok' : 'bad'}"><Icon name={result.equal ? 'check' : 'x'} size={13} />{result.equal ? 'Resultado idêntico nos dois bancos' : 'Resultados diferentes'}</span>
    </article>
  </div>

  <section class="card">
    <div class="card-head">
      <div><h2>Cada execução</h2><p>{result.scope}</p></div>
      <div class="aside legend">
        <span><i class="shape postgresql"></i>PostgreSQL</span><span><i class="shape cassandra"></i>Cassandra</span>
      </div>
    </div>
    <div class="rows">
      {#each summary as row (row.s)}
        <div class="row">
          <span class="name"><i class="shape {row.s}"></i>{SOURCE_LABEL[row.s]}</span>
          <span class="track">
            <span class="bar {row.s}" style:width={`${pos(row.http)}%`}></span>
            {#each row.raw as v, i (i)}<span class="dot {row.s}" class:pinned={v > scale} style:left={`${pos(v)}%`} title={`${fmtMs(v)}${v > scale ? ' (fora da escala)' : ''}`}></span>{/each}
          </span>
          <span class="value"><strong>{fmtMs(row.http)}</strong><small>banco {fmtMs(row.db)}</small></span>
        </div>
      {/each}
    </div>
    <details class="table-view">
      <summary>Ver tempos de cada par (ms)</summary>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Par</th><th>Ordem</th><th class="num">PostgreSQL HTTP</th><th class="num">Cassandra HTTP</th><th class="num">PostgreSQL banco</th><th class="num">Cassandra banco</th></tr></thead>
          <tbody>
            {#each result.acc.postgresql.http as pg, i (i)}
              <tr><td>{i + 1}</td><td class="muted">{(i + 1) % 2 ? 'PG → CS' : 'CS → PG'}</td><td class="num">{fmtMs(pg)}</td><td class="num">{fmtMs(result.acc.cassandra.http[i])}</td>
                <td class="num muted">{fmtMs(result.acc.postgresql.db[i])}</td><td class="num muted">{fmtMs(result.acc.cassandra.db[i])}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    </details>
    <p class="note">Barra = mediana HTTP medida no navegador; marcas = cada execução (contorno = acima da escala); “banco” = Server-Timing da API (driver + banco).
      Aquecimento descartado: PG {fmtMs(result.warm.postgresql)}, CS {fmtMs(result.warm.cassandra)}. Observação ao vivo, sujeita ao proxy do Vite e ao navegador; não substitui o protocolo de benchmark.</p>
  </section>
{/if}

<style>
  .controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
  .exp { font-size: 10.5px; color: var(--muted); font-family: var(--mono); margin-left: 2px; }
  .reps { display: inline-flex; gap: 8px; align-items: center; font-size: 12.5px; color: var(--text-2); }
  .controls .btn.primary { margin-left: auto; }
  .hint { display: flex; gap: 8px; align-items: flex-start; color: var(--text-2); font-size: 12.5px; margin-top: 14px; line-height: 1.55; }
  .hint :global(.icon) { margin-top: 2px; color: var(--muted); }
  .scope { color: var(--muted); }
  .progress { height: 4px; border-radius: 2px; background: var(--card-3); margin-top: 14px; overflow: hidden; }
  .progress span { display: block; height: 100%; background: var(--accent); transition: width 0.2s; }

  .duel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(200px, 0.75fr) minmax(0, 1fr); gap: 16px; transition: opacity 0.2s; }
  .duel.stale { opacity: 0.5; }
  .db { display: grid; gap: 8px; align-content: start; }
  .db.winner { border-color: var(--accent-line); }
  .db header { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
  .db header .badge { margin-left: auto; }
  .db-icon { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: var(--card-2); border: 1px solid var(--line-soft); }
  .db-icon.postgresql { color: var(--db-pg); }
  .db-icon.cassandra { color: var(--db-cs); }
  .db-name { font-weight: 600; font-size: 14px; display: grid; line-height: 1.25; }
  .db-name small { font-size: 11.5px; color: var(--muted); font-weight: 450; }
  .big { font-size: 38px; font-weight: 650; letter-spacing: -0.03em; line-height: 1.05; }
  .big small { font-size: 15px; color: var(--text-2); font-weight: 500; margin-left: 4px; letter-spacing: 0; }
  .sub, .range { font-size: 12px; color: var(--muted); }
  .strip { position: relative; height: 22px; margin: 8px 0 2px; border-bottom: 1px solid var(--axis); }

  .verdict { display: grid; place-content: center; justify-items: center; text-align: center; gap: 6px; background: var(--hero); border-color: var(--hero-line); }
  .ratio { font-size: 46px; font-weight: 700; letter-spacing: -0.03em; line-height: 1; }
  .who { font-size: 14px; color: #c3cde0; }
  .who strong { color: var(--text); }
  .what { font-size: 12px; color: #c3cde0; margin-bottom: 8px; }

  .legend { gap: 14px; }
  .legend span { display: inline-flex; align-items: center; gap: 7px; }
  /* Secondary encoding for the database pair (deutan ΔE 7.8): circle = PostgreSQL, diamond = Cassandra. */
  .shape { display: inline-block; width: 9px; height: 9px; flex-shrink: 0; }
  .shape.postgresql, .dot.postgresql, .run.postgresql, .median.postgresql { background: var(--db-pg); border-radius: 50%; }
  .shape.cassandra, .dot.cassandra, .run.cassandra, .median.cassandra { background: var(--db-cs); border-radius: 1px; transform: rotate(45deg); }

  .run { position: absolute; bottom: 6px; width: 7px; height: 7px; margin-left: -3.5px; opacity: 0.55; }
  .run.cassandra { transform: rotate(45deg); }
  .run.pinned { margin-left: -7px; outline: 1px solid var(--text-2); }
  .median { position: absolute; bottom: -1px; width: 3px !important; height: 20px; margin-left: -1.5px; border-radius: 2px !important; transform: none !important; }

  .rows { display: grid; gap: 16px; }
  .row { display: grid; grid-template-columns: 130px 1fr 130px; gap: 14px; align-items: center; }
  .name { display: flex; align-items: center; gap: 9px; font-size: 13px; color: var(--text-2); }
  .track { position: relative; height: 22px; display: flex; align-items: center; background: var(--card-2); border-radius: 6px; }
  .bar { height: 10px; border-radius: 0 4px 4px 0; min-width: 2px; opacity: 0.85; }
  .bar.postgresql { background: var(--db-pg); }
  .bar.cassandra { background: var(--db-cs); }
  .dot { position: absolute; width: 8px; height: 8px; margin-left: -4px; top: 7px; box-shadow: 0 0 0 2px var(--card-2); }
  .dot.pinned { margin-left: -9px; outline: 1px solid var(--text-2); }
  .value { display: grid; text-align: right; font-variant-numeric: tabular-nums; }
  .value strong { font-size: 14px; color: var(--text); }
  .value small { font-size: 11.5px; color: var(--muted); }
  .note { margin-top: 14px; }

  @media (max-width: 980px) {
    .duel { grid-template-columns: 1fr 1fr; }
    .verdict { grid-column: 1 / -1; order: -1 !important; }
  }
  @media (max-width: 640px) {
    .duel { grid-template-columns: 1fr; }
    .controls .btn.primary { margin-left: 0; flex: 1 1 100%; }
    .segmented { width: 100%; }
    .segmented button { flex: 1 1 auto; justify-content: center; }
    .row { grid-template-columns: 1fr; gap: 6px; }
    .value { text-align: left; }
  }
</style>
