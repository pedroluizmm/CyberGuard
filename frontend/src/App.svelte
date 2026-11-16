<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import BenchmarkPanel from './lib/BenchmarkPanel.svelte'
  import CategoryShare from './lib/CategoryShare.svelte'
  import EventExplorer from './lib/EventExplorer.svelte'
  import LiveCompare from './lib/LiveCompare.svelte'
  import SeverityBars from './lib/SeverityBars.svelte'
  import TimelineChart from './lib/TimelineChart.svelte'
  import {
    ApiError, CATEGORIES, CATEGORY_LABEL, describeProbe, getHealth, getOverview, getRuntime, getStorageHealth,
    SEVERITY_LABEL, SOURCE_KIND, SOURCE_LABEL, SOURCES,
    type Category, type Health, type Overview, type Runtime, type Source, type StorageHealth,
  } from './lib/api'
  import { fmtDay, fmtInt, fmtMs, fmtPct } from './lib/format'

  const views = [
    { id: 'overview', label: 'Visão geral', icon: '◫' },
    { id: 'investigate', label: 'Investigação', icon: '⌕' },
    { id: 'benchmarks', label: 'Benchmarks', icon: '▥' },
  ] as const
  type View = (typeof views)[number]['id']
  let view = $state<View>('overview')

  // ---- global filters (scope everything below the filter row) ----
  let source = $state<Source>('cassandra')
  const presets = [
    { label: '05–11/10', start: '2026-10-05', days: 7 },
    { label: '12–18/10', start: '2026-10-12', days: 7 },
    { label: '19–25/10', start: '2026-10-19', days: 7 },
    { label: '26/10–01/11', start: '2026-10-26', days: 7 },
    { label: 'Pico · 27/10', start: '2026-10-27', days: 1 },
    { label: 'Amostra · 06–08/11', start: '2026-11-06', days: 3 },
  ]
  let start = $state('2026-10-26')
  let days = $state(7)
  let category = $state<Category | ''>('')
  let severity = $state<number | ''>('')
  const from = $derived(`${start}T00:00:00Z`)
  const to = $derived(new Date(Date.parse(from) + days * 86_400_000).toISOString().replace('.000Z', 'Z'))

  // ---- health ----
  let health = $state<Health | null>(null)
  let storage = $state<StorageHealth | null>(null)
  let runtime = $state<Runtime | null>(null)
  let apiDown = $state(false)
  let checking = $state(true)
  async function checkHealth() {
    checking = true
    const [h, s, r] = await Promise.allSettled([getHealth(), getStorageHealth(), getRuntime()])
    health = h.status === 'fulfilled' ? h.value : null
    storage = s.status === 'fulfilled' ? s.value : null
    runtime = r.status === 'fulfilled' ? r.value : null
    apiDown = h.status === 'rejected'
    checking = false
  }

  // ---- overview (real query on the selected source) ----
  type OverviewState = { status: 'loading' | 'ready' | 'error'; data: Overview | null; timing: { http: number; db: number | null; source: Source } | null; error: ApiError | null }
  let ov = $state<OverviewState>({ status: 'loading', data: null, timing: null, error: null })
  let seq = 0
  async function loadOverview(src: Source, params: { from: string; to: string; category: string | null; severity: number | null }) {
    const mine = ++seq
    ov.status = 'loading'
    try {
      const r = await getOverview(src, params)
      if (mine !== seq) return
      ov = { status: 'ready', data: r.data, timing: { http: r.httpMs, db: r.dbMs, source: src }, error: null }
    } catch (e) {
      if (mine !== seq) return
      ov = { status: 'error', data: null, timing: null, error: e instanceof ApiError ? e : new ApiError('contract', 'unknown', 'Falha inesperada.') }
    }
  }
  $effect(() => {
    const params = { from, to, category: category || null, severity: severity === '' ? null : severity }
    const src = source
    untrack(() => loadOverview(src, params))
  })
  onMount(() => { void checkHealth() })

  const data = $derived(ov.data)
  const visible = $derived<Category[]>(category ? [category] : [...CATEGORIES])
  const sourceProbe = $derived(storage?.[source] ?? null)
  const perDay = $derived.by(() => {
    if (!data) return []
    const map = new Map<string, number[]>()
    for (const p of data.series) {
      const key = p.t.slice(0, 10)
      const row = map.get(key) ?? [0, 0, 0, 0]
      p.by_category.forEach((v, i) => (row[i] += v))
      row[3] += p.total
      map.set(key, row)
    }
    return [...map.entries()]
  })
  const peakHour = $derived(data ? data.series.reduce((best, p) => (p.total > best.total ? p : best), data.series[0]) : null)
  function errorText(e: ApiError | null): string {
    if (!e) return ''
    if (e.kind === 'network') return 'A API local não está acessível. Inicie-a com python scripts/run_api.py start.'
    if (e.kind === 'unavailable' || e.kind === 'timeout') return `${SOURCE_LABEL[source]} indisponível no momento (${e.code}). Nenhum dado é exibido no lugar da consulta.`
    if (e.kind === 'invalid') return `Filtro rejeitado pela API: ${e.message}`
    return e.message
  }
</script>

<svelte:head><title>{views.find((v) => v.id === view)?.label} · CyberGuard</title></svelte:head>

<div class="app">
  <aside class="sidebar">
    <div class="brand">
      <svg width="28" height="32" viewBox="0 0 32 36" fill="none" aria-hidden="true"><path d="M16 3 28 8v9c0 8-12 15-12 15S4 25 4 17V8L16 3Z" stroke="currentColor" stroke-width="1.8"/><path d="m10 17 4 4 8-9" stroke="currentColor" stroke-width="1.8"/></svg>
      <span>CYBER<b>GUARD</b><small>SOC · Cassandra × PostgreSQL</small></span>
    </div>
    <nav aria-label="Seções">
      {#each views as v}
        <button class:active={view === v.id} aria-current={view === v.id ? 'page' : undefined} onclick={() => (view = v.id)}><span aria-hidden="true">{v.icon}</span>{v.label}</button>
      {/each}
    </nav>
    <div class="health" aria-live="polite">
      <p class="eyebrow">SERVIÇOS</p>
      <p class="pill" class:up={!!health} class:down={apiDown}><i></i>API {health ? `v${health.version} · ${health.build ?? ''}` : checking ? 'verificando…' : 'indisponível'}</p>
      {#each SOURCES as s}
        {@const p = storage?.[s]}
        <p class="pill" class:up={p?.status === 'up'} class:down={p?.status === 'down'} class:unknown={!checking && !p}><i></i>{SOURCE_LABEL[s]} {checking ? 'verificando…' : !p ? 'não verificado' : p.status === 'up' ? 'conectado' : describeProbe(p.error)}</p>
      {/each}
      <button class="ghost small" onclick={checkHealth} disabled={checking}>{checking ? 'Verificando…' : 'Verificar novamente'}</button>
    </div>
    <footer>UNIFOR · Banco de Dados NoSQL · V3 2026<br />Dados sintéticos · horários em UTC</footer>
  </aside>

  <div class="main">
    <header class="topbar">
      <div>
        <p class="eyebrow">CENTRAL DE OPERAÇÕES DE SEGURANÇA</p>
        <h1>{views.find((v) => v.id === view)?.label}</h1>
      </div>
      <div class="source" role="radiogroup" aria-label="Fonte de dados consultada">
        {#each SOURCES as s}
          <button role="radio" aria-checked={source === s} class:on={source === s} onclick={() => (source = s)}>
            <i class={s}></i><span>{SOURCE_LABEL[s]}<small>{SOURCE_KIND[s]}</small></span>
          </button>
        {/each}
      </div>
    </header>

    {#if view !== 'benchmarks'}
      <section class="filters" aria-label="Filtros">
        <div class="presets" role="group" aria-label="Período (UTC)">
          {#each presets as p}
            <button class:on={start === p.start && days === p.days} onclick={() => { start = p.start; days = p.days }}>{p.label}</button>
          {/each}
        </div>
        <label>Início<input type="date" bind:value={start} min="2000-01-01" max="2099-12-25" required /></label>
        <label>Dias<select bind:value={days}>{#each [1, 2, 3, 4, 5, 6, 7] as d}<option value={d}>{d}</option>{/each}</select></label>
        {#if view === 'overview'}
          <label>Categoria<select bind:value={category}><option value="">Todas</option>{#each CATEGORIES as c}<option value={c}>{CATEGORY_LABEL[c]}</option>{/each}</select></label>
          <label>Severidade<select bind:value={severity}><option value="">Todas</option>{#each [1, 2, 3, 4, 5] as s}<option value={s}>{s} · {SEVERITY_LABEL[s - 1]}</option>{/each}</select></label>
        {/if}
      </section>
    {/if}

    <main>
      <div hidden={view !== 'overview'}>
        {#if sourceProbe?.status === 'down'}
          <p class="banner" role="alert">{SOURCE_LABEL[source]} está indisponível ({describeProbe(sourceProbe.error)}). As consultas a esta fonte falharão até que o serviço volte; troque a fonte ou reinicie o contêiner.</p>
        {/if}

        {#if ov.status === 'error'}
          <div class="panel state-panel" role="alert"><h2>Consulta não concluída</h2><p>{errorText(ov.error)}</p><button class="ghost" onclick={() => loadOverview(source, { from, to, category: category || null, severity: severity === '' ? null : severity })}>Tentar novamente</button></div>
        {:else if !data}
          <div class="panel state-panel" aria-busy="true"><p>Consultando {SOURCE_LABEL[source]}…</p></div>
        {:else}
          <div class:stale={ov.status === 'loading'} class="overview">
            <section class="kpis" aria-label="Indicadores do período">
              <article class="kpi hero">
                <span>Eventos no período</span>
                <strong>{fmtInt(data.total)}</strong>
                <small>{fmtDay(data.from)}{days > 1 ? ` a ${fmtDay(new Date(Date.parse(data.to) - 1).toISOString())}` : ''} · {days} {days === 1 ? 'dia' : 'dias'}{category ? ` · ${CATEGORY_LABEL[category]}` : ''}{severity !== '' ? ` · severidade ${severity}` : ''}</small>
              </article>
              <article class="kpi"><span>Alertas</span><strong>{fmtInt(data.alerts)}</strong><small>{fmtPct(data.alerts, data.total)} dos eventos filtrados</small></article>
              <article class="kpi"><span>Severidade crítica (5)</span><strong>{fmtInt(data.by_severity[4])}</strong><small>{fmtPct(data.by_severity[4], data.total)} · altas (4): {fmtInt(data.by_severity[3])}</small></article>
              <article class="kpi timing">
                <span>Tempo de resposta</span>
                <strong>{fmtMs(ov.timing?.db)}</strong>
                <small>no banco ({ov.timing ? SOURCE_LABEL[ov.timing.source] : '—'}) · HTTP {fmtMs(ov.timing?.http)}</small>
              </article>
            </section>

            {#if data.total === 0}
              <div class="panel state-panel"><h2>Nenhum evento no período</h2><p>A consulta foi executada em {SOURCE_LABEL[source]} e retornou zero eventos para estes filtros. A massa de 1 M cobre 05/10 a 01/11/2026; a amostra, 06 a 08/11/2026.</p></div>
            {:else}
              <div class="grid">
                <section class="panel wide">
                  <div class="panel-head"><h2>Eventos por hora (UTC)</h2>{#if peakHour}<span class="muted">pico: {fmtInt(peakHour.total)} eventos em {fmtDay(peakHour.t)} {peakHour.t.slice(11, 13)}h</span>{/if}</div>
                  <TimelineChart points={data.series} {visible} />
                  <details class="table-view">
                    <summary>Ver como tabela (por dia)</summary>
                    <table>
                      <thead><tr><th>Dia (UTC)</th>{#each CATEGORIES as c}<th>{CATEGORY_LABEL[c]}</th>{/each}<th>Total</th></tr></thead>
                      <tbody>{#each perDay as [day, row]}<tr><td>{day}</td>{#each row as v}<td class="num">{fmtInt(v)}</td>{/each}</tr>{/each}</tbody>
                    </table>
                  </details>
                </section>
                <section class="panel">
                  <div class="panel-head"><h2>Distribuição por severidade</h2></div>
                  <SeverityBars values={data.by_severity} selected={severity === '' ? null : severity} />
                </section>
                <section class="panel">
                  <div class="panel-head"><h2>Participação por categoria</h2></div>
                  <CategoryShare values={data.by_category} />
                </section>
              </div>
            {/if}
          </div>
        {/if}

        <section class="panel compare">
          <div class="panel-head"><h2>Comparação ao vivo · PostgreSQL × Cassandra</h2><span class="muted">consultas reais, executadas agora</span></div>
          <LiveCompare {from} {to} category={category || null} severity={severity === '' ? null : severity} />
        </section>
      </div>

      <div hidden={view !== 'investigate'}>
        <section class="panel">
          <div class="panel-head"><h2>Investigação de eventos</h2><span class="muted">padrões de acesso Q1, Q2 e Q3 · até 7 dias</span></div>
          <EventExplorer {source} {from} {to} />
        </section>
      </div>

      <div hidden={view !== 'benchmarks'}>
        <section class="panel">
          <div class="panel-head"><h2>Resultados medidos</h2><span class="muted">benchmarks/results · gerado por run_benchmarks.py</span></div>
          <BenchmarkPanel />
        </section>
      </div>
    </main>
    <footer class="main-footer">
      <span>Fonte selecionada: {SOURCE_LABEL[source]}{runtime ? ` · API ${runtime.build}` : ''}</span>
      <span>Tempos: “no banco” = Server-Timing da API (driver + banco); HTTP = medido no navegador.</span>
    </footer>
  </div>
</div>
