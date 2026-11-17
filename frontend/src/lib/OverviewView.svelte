<script lang="ts">
  import { untrack } from 'svelte'
  import CategoryShare from './CategoryShare.svelte'
  import Icon from './Icon.svelte'
  import SeverityBars from './SeverityBars.svelte'
  import TimelineChart from './TimelineChart.svelte'
  import VolumeBars, { type BarItem } from './VolumeBars.svelte'
  import { ApiError, CATEGORIES, CATEGORY_LABEL, getOverview, SOURCE_LABEL, type Category, type Overview, type Source } from './api'
  import { fmtDate, fmtDay, fmtHour, fmtInt, fmtMs, fmtPct, fmtPeriod, fmtRatio, fmtWeekday } from './format'

  let { source, from, to, days, category, severity, oncompare }: {
    source: Source; from: string; to: string; days: number
    category: Category | null; severity: number | null; oncompare: () => void
  } = $props()

  // ---- the panel query (/stats/overview) on the selected source; nothing is cached or simulated ----
  type Params = { from: string; to: string; category: Category | null; severity: number | null }
  type Timing = { http: number; db: number | null; source: Source }
  type State = { status: 'loading' | 'ready' | 'error'; data: Overview | null; timing: Timing | null; error: ApiError | null }
  let ov = $state<State>({ status: 'loading', data: null, timing: null, error: null })
  let seq = 0
  async function load(src: Source, params: Params) {
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
  const params = $derived<Params>({ from, to, category, severity })
  $effect(() => {
    const p = params
    const src = source
    untrack(() => load(src, p))
  })

  // ---- indicators derived from the query result ----
  const data = $derived(ov.data)
  const visible = $derived<Category[]>(category ? [category] : [...CATEGORIES])
  const perDay = $derived.by(() => {
    if (!data) return [] as [string, number[]][]
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
  const hours = $derived(data?.series.length ?? 0)
  const peakHour = $derived(data && hours ? data.series.reduce((best, p) => (p.total > best.total ? p : best), data.series[0]) : null)
  const avgHour = $derived(data && hours ? data.total / hours : 0)
  const busiest = $derived(perDay.length ? perDay.reduce((a, b) => (b[1][3] > a[1][3] ? b : a)) : null)
  const bars = $derived<BarItem[]>(!data ? [] : days > 1
    ? perDay.map(([d, row]) => ({ key: d, label: fmtDay(d), value: row[3], detail: `${fmtDate(d)} (${fmtWeekday(d)})` }))
    : data.series.map((p) => ({ key: p.t, label: fmtHour(p.t), value: p.total, detail: `${fmtDate(p.t)} · ${fmtHour(p.t)} UTC` })))
  const filterText = $derived([category ? CATEGORY_LABEL[category] : 'Todas as categorias', severity ? `severidade ${severity}` : 'todas as severidades'].join(' · '))
  const share = (part: number, whole: number) => `${whole ? Math.min(100, (100 * part) / whole) : 0}%`
  const msValue = (v: number | null | undefined) => fmtMs(v).replace(/\s?ms$/, '')

  function errorText(e: ApiError | null): string {
    if (!e) return ''
    if (e.kind === 'network') return 'A API local não está acessível. Inicie-a com python scripts/run_api.py start.'
    if (e.kind === 'unavailable' || e.kind === 'timeout') return `${SOURCE_LABEL[source]} indisponível no momento (${e.code}). Nenhum dado é exibido no lugar da consulta.`
    if (e.kind === 'invalid') return `Filtro rejeitado pela API: ${e.message}`
    return e.message
  }
</script>

{#if ov.status === 'error'}
  <div class="card state error" role="alert">
    <h2><span class="icon-wrap"><Icon name="alert" size={17} /></span>Consulta não concluída</h2>
    <p>{errorText(ov.error)}</p>
    <button class="btn" onclick={() => load(source, params)}><Icon name="refresh" size={15} />Tentar novamente</button>
  </div>
{:else if !data}
  <p class="sr-only" role="status">Consultando {SOURCE_LABEL[source]}…</p>
  <div class="kpis" aria-hidden="true">
    {#each [0, 1, 2, 3] as i (i)}
      <div class="card kpi"><div class="skeleton" style="height:12px;width:45%"></div><div class="skeleton" style="height:34px;width:65%;margin-top:18px"></div><div class="skeleton" style="height:10px;width:55%;margin-top:16px"></div></div>
    {/each}
  </div>
  <div class="grid-main" aria-hidden="true">
    <div class="card"><div class="skeleton" style="height:300px"></div></div>
    <div class="card"><div class="skeleton" style="height:300px"></div></div>
  </div>
{:else}
  <div class="overview" class:stale={ov.status === 'loading'} aria-busy={ov.status === 'loading'}>
    <section class="kpis" aria-label="Indicadores do período">
      <article class="card kpi hero">
        <header><span class="kpi-icon"><Icon name="activity" size={16} /></span>Eventos no período{#if ov.status === 'loading'}<span class="spinner" role="status" aria-label="Atualizando"></span>{/if}</header>
        <strong class="value">{fmtInt(data.total)}</strong>
        <footer><span>{fmtPeriod(data.from, data.to)}</span><span>{filterText}</span></footer>
      </article>
      <article class="card kpi">
        <header><span class="kpi-icon"><Icon name="alert" size={16} /></span>Alertas</header>
        <strong class="value">{fmtInt(data.alerts)}</strong>
        <div class="meter" aria-hidden="true"><span style:width={share(data.alerts, data.total)}></span></div>
        <footer><span>{fmtPct(data.alerts, data.total)} dos eventos filtrados</span></footer>
      </article>
      <article class="card kpi">
        <header><span class="kpi-icon crit"><Icon name="critical" size={16} /></span>Eventos críticos</header>
        <strong class="value">{fmtInt(data.by_severity[4])}</strong>
        <div class="meter crit" aria-hidden="true"><span style:width={share(data.by_severity[4], data.total)}></span></div>
        <footer><span>{fmtPct(data.by_severity[4], data.total)} · severidade 5</span><span>Altos (4): {fmtInt(data.by_severity[3])}</span></footer>
      </article>
      <article class="card kpi">
        <header><span class="kpi-icon"><Icon name="clock" size={16} /></span>Tempo de resposta</header>
        <strong class="value">{msValue(ov.timing?.db)}<small>ms</small></strong>
        <footer><span>no banco · {ov.timing ? SOURCE_LABEL[ov.timing.source] : '—'}</span><span>HTTP {fmtMs(ov.timing?.http)}</span></footer>
        <button class="kpi-link" onclick={oncompare} aria-label="Comparar esta consulta nos dois bancos" title="Comparar nos dois bancos"><Icon name="arrowUpRight" size={15} /></button>
      </article>
    </section>

    {#if data.total === 0}
      <div class="card state">
        <h2><span class="icon-wrap"><Icon name="info" size={17} /></span>Nenhum evento no período</h2>
        <p>A consulta foi executada em {SOURCE_LABEL[source]} e retornou zero eventos para estes filtros. A massa de 1 M cobre 05/10 a 01/11/2026; a amostra, 06 a 08/11/2026.</p>
      </div>
    {:else}
      <div class="grid-main">
        <section class="card">
          <div class="card-head">
            <div><h2>Eventos por hora</h2><p>Evolução temporal por categoria · {hours} horas (UTC)</p></div>
            {#if peakHour}<div class="aside"><span class="badge steel"><Icon name="target" size={13} />Pico {fmtInt(peakHour.total)} · {fmtDay(peakHour.t)} {fmtHour(peakHour.t)}</span></div>{/if}
          </div>
          <TimelineChart points={data.series} {visible} />
          <details class="table-view">
            <summary>Ver como tabela (por dia)</summary>
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>Dia (UTC)</th>{#each CATEGORIES as c}<th class="num">{CATEGORY_LABEL[c]}</th>{/each}<th class="num">Total</th></tr></thead>
                <tbody>{#each perDay as [day, row] (day)}<tr><td>{fmtDate(day)} · {fmtWeekday(day)}</td>{#each row as v, i (i)}<td class="num">{#if i === 3}<strong>{fmtInt(v)}</strong>{:else}{fmtInt(v)}{/if}</td>{/each}</tr>{/each}</tbody>
              </table>
            </div>
          </details>
        </section>
        <section class="card">
          <div class="card-head">
            <div><h2>{days > 1 ? 'Volume diário' : 'Volume por hora'}</h2><p>Total de eventos {days > 1 ? 'por dia' : 'por hora'} · maior valor em destaque</p></div>
          </div>
          <VolumeBars items={bars} />
        </section>
      </div>

      <div class="grid-3">
        <section class="card">
          <div class="card-head"><div><h2>Distribuição por severidade</h2><p>1 = informativo · 5 = crítico</p></div></div>
          <SeverityBars values={data.by_severity} selected={severity} />
        </section>
        <section class="card">
          <div class="card-head"><div><h2>Participação por categoria</h2><p>Autenticação, rede e alertas no período</p></div></div>
          <CategoryShare values={data.by_category} />
        </section>
        <section class="card">
          <div class="card-head"><div><h2>Atividade</h2><p>Derivada da série horária consultada</p></div></div>
          {#if peakHour && busiest}
            <dl class="activity">
              <div><dt>Pico horário</dt><dd><strong>{fmtInt(peakHour.total)}</strong><small>eventos/h</small><span>{fmtDate(peakHour.t)} · {fmtHour(peakHour.t)}</span></dd></div>
              <div><dt>Média por hora</dt><dd><strong>{fmtInt(Math.round(avgHour))}</strong><small>eventos/h</small><span>{hours} horas no período</span></dd></div>
              <div><dt>Dia mais ativo</dt><dd><strong>{fmtDay(busiest[0])}</strong><small>{fmtWeekday(busiest[0])}</small><span>{fmtInt(busiest[1][3])} eventos</span></dd></div>
              <div><dt>Pico ÷ média</dt><dd><strong>{avgHour ? fmtRatio(peakHour.total / avgHour) : '—'}</strong><span>intensidade do pico</span></dd></div>
            </dl>
          {/if}
        </section>
      </div>
    {/if}
  </div>
{/if}

<style>
  .overview { display: grid; gap: 18px; transition: opacity 0.2s; }
  .overview.stale { opacity: 0.55; }

  .kpis { display: grid; grid-template-columns: 1.3fr repeat(3, 1fr); gap: 16px; }
  .kpi { display: flex; flex-direction: column; gap: 10px; padding: 16px 18px 16px; position: relative; }
  .kpi header { display: flex; align-items: center; gap: 9px; font-size: 12.5px; color: var(--text-2); font-weight: 500; }
  .kpi header .spinner { margin-left: auto; }
  .kpi-icon { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; background: var(--card-2); border: 1px solid var(--line-soft); color: var(--steel-text); }
  .kpi-icon.crit { color: var(--sev-5); }
  .value { font-size: 32px; font-weight: 650; letter-spacing: -0.025em; line-height: 1.05; color: var(--text); margin-top: 4px; }
  .value small { font-size: 15px; font-weight: 500; color: var(--text-2); margin-left: 4px; letter-spacing: 0; }
  .kpi footer { display: flex; justify-content: space-between; gap: 4px 10px; flex-wrap: wrap; font-size: 12px; color: var(--muted); margin-top: auto; }
  .kpi.hero { background: var(--hero); border-color: var(--hero-line); }
  .kpi.hero header { color: #c3cde0; }
  .kpi.hero .kpi-icon { background: rgba(255, 255, 255, 0.06); border-color: var(--hero-line); color: #c3cde0; }
  .kpi.hero .value { font-size: 44px; }
  .kpi.hero footer { color: #c3cde0; }
  .meter { height: 5px; border-radius: 3px; background: var(--card-3); overflow: hidden; }
  .meter span { display: block; height: 100%; min-width: 2px; border-radius: 3px; background: var(--steel); }
  .meter.crit span { background: var(--sev-5); }
  .kpi-link { position: absolute; top: 14px; right: 14px; display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%;
    background: var(--card-2); border: 1px solid var(--line); color: var(--accent-text); transition: background-color 0.15s, border-color 0.15s; }
  .kpi-link:hover { background: var(--accent-soft); border-color: var(--accent-line); }

  .grid-main { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 18px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }

  .activity { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--line-soft); border: 1px solid var(--line-soft); border-radius: 12px; overflow: hidden; }
  .activity > div { background: var(--card); padding: 13px 14px; display: grid; gap: 4px; }
  .activity dt { font-size: 11.5px; color: var(--muted); }
  .activity dd { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 6px; }
  .activity strong { font-size: 21px; font-weight: 650; letter-spacing: -0.02em; color: var(--text); }
  .activity small { font-size: 11.5px; color: var(--text-2); }
  .activity dd span { flex-basis: 100%; font-size: 11.5px; color: var(--muted); }

  @media (max-width: 1360px) {
    .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .grid-3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .grid-3 > :last-child { grid-column: 1 / -1; }
    .activity { grid-template-columns: repeat(4, 1fr); }
  }
  @media (max-width: 1100px) {
    .grid-main { grid-template-columns: 1fr; }
  }
  @media (max-width: 760px) {
    .grid-3 { grid-template-columns: 1fr; }
    .activity { grid-template-columns: 1fr 1fr; }
  }
  @media (max-width: 520px) {
    .kpis { grid-template-columns: 1fr; }
    .kpi.hero .value { font-size: 38px; }
  }
</style>
