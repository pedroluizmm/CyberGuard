<script lang="ts">
  import { onMount, tick } from 'svelte'
  import BenchmarksView from './lib/BenchmarksView.svelte'
  import DatasetCheck from './lib/DatasetCheck.svelte'
  import EventExplorer from './lib/EventExplorer.svelte'
  import Icon, { type IconName } from './lib/Icon.svelte'
  import LiveCompare from './lib/LiveCompare.svelte'
  import OverviewView from './lib/OverviewView.svelte'
  import {
    CATEGORIES, CATEGORY_LABEL, describeProbe, getHealth, getRuntime, getStorageHealth,
    SEVERITY_LABEL, SOURCE_ICON, SOURCE_KIND, SOURCE_LABEL, SOURCES,
    type Category, type Health, type Runtime, type Source, type StorageHealth,
  } from './lib/api'

  // ---- navigation (hash-based so reload and the Back button keep the section) ----
  type View = 'overview' | 'investigate' | 'compare' | 'benchmarks'
  const views: { id: View; slug: string; label: string; icon: IconName; group: string; subtitle: string }[] = [
    { id: 'overview', slug: 'visao-geral', label: 'Visão geral', icon: 'grid', group: 'Monitoramento',
      subtitle: 'Indicadores e evolução dos eventos no período, consultados agora na fonte selecionada.' },
    { id: 'investigate', slug: 'investigacao', label: 'Investigação', icon: 'search', group: 'Monitoramento',
      subtitle: 'Linha do tempo por dispositivo, IP de origem ou severidade (Q1–Q3), com paginação por cursor.' },
    { id: 'compare', slug: 'comparacao', label: 'Comparação', icon: 'compare', group: 'Análise',
      subtitle: 'A mesma consulta executada agora nos dois bancos: tempos reais e verificação do resultado.' },
    { id: 'benchmarks', slug: 'benchmarks', label: 'Benchmarks', icon: 'chart', group: 'Análise',
      subtitle: 'Resultados experimentais gravados (E1–E6): histórico de 1 M, campanha de escala e comparação entre volumes.' },
  ]
  const groups = ['Monitoramento', 'Análise']
  const viewFromHash = (): View => views.find((v) => v.slug === location.hash.replace(/^#\/?/, ''))?.id ?? 'overview'
  let view = $state<View>(viewFromHash())
  const current = $derived(views.find((v) => v.id === view)!)
  let heading: HTMLHeadingElement | undefined = $state()

  async function go(next: View) {
    const slug = views.find((v) => v.id === next)!.slug
    if (location.hash.replace(/^#\/?/, '') !== slug) location.hash = slug
    view = next
    await tick()
    heading?.focus({ preventScroll: true })
    window.scrollTo({ top: 0 })
  }

  // ---- global filters (scope every query below the toolbar) ----
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
  const showFilters = $derived(view !== 'benchmarks')
  const showSource = $derived(view === 'overview' || view === 'investigate')

  // ---- service health (probes are not benchmark measurements) ----
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
  const sourceProbe = $derived(storage?.[source] ?? null)

  onMount(() => {
    const sync = () => { view = viewFromHash() }
    addEventListener('hashchange', sync)
    void checkHealth()
    return () => removeEventListener('hashchange', sync)
  })
</script>

<svelte:head><title>{current.label} · CyberGuard</title></svelte:head>

<a class="skip" href="#content">Pular para o conteúdo</a>
<div class="shell">
  <aside class="sidebar" aria-label="Navegação principal">
    <div class="brand">
      <span class="logo"><Icon name="shield" size={20} stroke={1.9} /></span>
      <span class="name">CyberGuard<small>Cassandra × PostgreSQL</small></span>
    </div>

    <nav class="nav" aria-label="Seções">
      {#each groups as group}
        <p class="eyebrow group">{group}</p>
        {#each views.filter((v) => v.group === group) as v}
          <a href={`#${v.slug}`} class:active={view === v.id} aria-current={view === v.id ? 'page' : undefined}
            onclick={(e) => { e.preventDefault(); void go(v.id) }}>
            <Icon name={v.icon} size={18} /><span>{v.label}</span>
          </a>
        {/each}
      {/each}
    </nav>

    <section class="services" aria-live="polite" aria-label="Estado dos serviços">
      <div class="services-head">
        <p class="eyebrow">Serviços</p>
        <button class="btn ghost icon" onclick={checkHealth} disabled={checking} aria-label="Verificar serviços novamente" title="Verificar novamente">
          {#if checking}<span class="spinner"></span>{:else}<Icon name="refresh" size={15} />{/if}
        </button>
      </div>
      <p class="svc" class:up={!!health} class:down={apiDown}>
        <i></i><span>API</span><em>{health ? `v${health.version} · ${health.build ?? '—'}` : checking ? 'verificando…' : 'indisponível'}</em>
      </p>
      {#each SOURCES as s}
        {@const p = storage?.[s]}
        <p class="svc" class:up={p?.status === 'up'} class:down={p?.status === 'down'} class:unknown={!checking && !p}>
          <i></i><span>{SOURCE_LABEL[s]}</span>
          <em>{checking ? 'verificando…' : !p ? 'não verificado' : p.status === 'up' ? 'conectado' : describeProbe(p.error)}</em>
        </p>
      {/each}
    </section>

    <div class="dataset">
      <span class="dataset-icon"><Icon name="layers" size={16} /></span>
      <div class="dataset-body">
        <p><strong>Dados sintéticos</strong>Massa de 05/10 a 01/11/2026 e amostra de 06 a 08/11/2026. Horários em UTC.</p>
        <DatasetCheck compact />
      </div>
    </div>
    <p class="credit">UNIFOR · Banco de Dados NoSQL<br />Projeto 3 · 2026</p>
  </aside>

  <div class="main">
    <header class="topbar">
      <div class="title">
        <p class="crumbs"><span>CyberGuard</span><Icon name="right" size={13} /><span>{current.group}</span></p>
        <h1 tabindex="-1" bind:this={heading}>{current.label}</h1>
        <p class="subtitle">{current.subtitle}</p>
      </div>
      {#if showSource}
        <div class="source" role="radiogroup" aria-label="Fonte de dados consultada">
          {#each SOURCES as s}
            <button role="radio" aria-checked={source === s} class:on={source === s} onclick={() => (source = s)}>
              <span class="src-icon"><Icon name={SOURCE_ICON[s]} size={17} /></span>
              <span class="src-text">{SOURCE_LABEL[s]}<small>{SOURCE_KIND[s]}</small></span>
            </button>
          {/each}
        </div>
      {:else if view === 'compare'}
        <p class="badge steel"><Icon name="compare" size={14} />Consulta os dois bancos</p>
      {/if}
    </header>

    {#if showFilters}
      <section class="toolbar" aria-label="Filtros da consulta">
        <div class="presets" role="group" aria-label="Atalhos de período (UTC)">
          <span class="toolbar-label"><Icon name="calendar" size={15} />Período</span>
          {#each presets as p}
            <button class="chip" class:on={start === p.start && days === p.days} aria-pressed={start === p.start && days === p.days}
              onclick={() => { start = p.start; days = p.days }}>{p.label}</button>
          {/each}
        </div>
        <div class="inputs">
          <label class="field">Início (UTC)<input type="date" bind:value={start} min="2000-01-01" max="2099-12-25" required /></label>
          <label class="field">Dias<select bind:value={days}>{#each [1, 2, 3, 4, 5, 6, 7] as d}<option value={d}>{d} {d === 1 ? 'dia' : 'dias'}</option>{/each}</select></label>
          {#if view !== 'investigate'}
            <label class="field">Categoria<select bind:value={category}><option value="">Todas</option>{#each CATEGORIES as c}<option value={c}>{CATEGORY_LABEL[c]}</option>{/each}</select></label>
            <label class="field">Severidade<select bind:value={severity}><option value="">Todas</option>{#each [1, 2, 3, 4, 5] as s}<option value={s}>{s} · {SEVERITY_LABEL[s - 1]}</option>{/each}</select></label>
          {/if}
        </div>
      </section>
    {/if}

    <main id="content" class="content">
      {#if showSource && sourceProbe?.status === 'down'}
        <p class="banner" role="alert"><Icon name="alert" size={16} /><span><strong>{SOURCE_LABEL[source]} indisponível</strong> ({describeProbe(sourceProbe.error)}). As consultas a esta fonte falharão até o serviço voltar. Troque a fonte ou reinicie o contêiner.</span></p>
      {/if}

      <div class="view" hidden={view !== 'overview'}>
        <OverviewView {source} {from} {to} {days} category={category || null} severity={severity === '' ? null : severity} oncompare={() => go('compare')} />
      </div>
      <div class="view" hidden={view !== 'investigate'}>
        <EventExplorer {source} {from} {to} />
      </div>
      <div class="view" hidden={view !== 'compare'}>
        <LiveCompare {from} {to} {days} category={category || null} severity={severity === '' ? null : severity} />
      </div>
      <div class="view" hidden={view !== 'benchmarks'}>
        <BenchmarksView />
      </div>
    </main>

    <footer class="footer">
      <span>{showSource ? `Fonte selecionada: ${SOURCE_LABEL[source]}` : view === 'compare' ? 'Fontes: PostgreSQL e Cassandra' : 'Resultados de benchmarks/results'}{runtime ? ` · API ${runtime.build}` : ''}</span>
      <span>Tempo “no banco” = Server-Timing da API (driver + banco) · HTTP = medido no navegador.</span>
    </footer>
  </div>
</div>

<style>
  /* ---- sidebar ---- */
  .brand { display: flex; align-items: center; gap: 11px; padding: 2px 6px 0; }
  .logo { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 11px; color: var(--accent-text);
    background: var(--accent-soft); border: 1px solid var(--accent-line); }
  .name { font-weight: 700; font-size: 16px; letter-spacing: -0.01em; display: grid; line-height: 1.2; }
  .name small { font-size: 11.5px; font-weight: 500; color: var(--muted); letter-spacing: 0; margin-top: 2px; }

  .nav { display: grid; gap: 3px; }
  .nav .group { padding: 10px 10px 6px; font-size: 10.5px; }
  .nav .group:first-child { padding-top: 0; }
  .nav a { position: relative; display: flex; align-items: center; gap: 11px; padding: 9px 11px; border-radius: 10px; color: var(--text-2);
    text-decoration: none; font-size: 14px; font-weight: 500; border: 1px solid transparent; transition: background-color 0.15s, color 0.15s; }
  .nav a:hover { background: var(--card); color: var(--text); }
  .nav a.active { background: var(--card); border-color: var(--line-soft); color: var(--text); }
  .nav a.active :global(.icon) { color: var(--accent-text); }
  .nav a.active::before { content: ""; position: absolute; left: -16px; top: 9px; bottom: 9px; width: 3px; border-radius: 0 3px 3px 0; background: var(--accent); }

  .services { display: grid; gap: 7px; padding: 14px; border: 1px solid var(--line-soft); border-radius: 12px; background: var(--bg); }
  .services-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 2px; }
  .services-head .btn { width: 28px; min-height: 28px; border-color: transparent; }
  .svc { display: grid; grid-template-columns: 8px auto 1fr; align-items: center; gap: 9px; font-size: 12.5px; color: var(--text-2); }
  .svc i { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .svc span { color: var(--text); font-weight: 500; }
  .svc em { font-style: normal; text-align: right; color: var(--muted); font-size: 12px; line-height: 1.3; }
  .svc.up i { background: var(--good); box-shadow: 0 0 0 3px rgba(63, 191, 127, 0.14); }
  .svc.down i { background: var(--critical); box-shadow: 0 0 0 3px rgba(224, 93, 93, 0.16); }
  .svc.down em { color: var(--critical-text); }
  /* "Não verificado" is unknown, not down: neutral hollow marker. */
  .svc.unknown i { background: transparent; border: 1.5px solid var(--muted); }

  .dataset { margin-top: auto; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px; padding: 14px; border-radius: 12px; background: var(--card); border: 1px solid var(--line-soft); }
  .dataset-icon { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; background: var(--steel-soft); color: var(--steel-text); }
  .dataset-body { display: grid; gap: 10px; min-width: 0; }
  .dataset p { font-size: 12px; color: var(--text-2); line-height: 1.5; }
  .dataset strong { display: block; color: var(--text); font-weight: 600; font-size: 12.5px; margin-bottom: 2px; }
  .credit { font-size: 11px; color: var(--muted); line-height: 1.55; padding: 0 6px; }

  /* ---- topbar ---- */
  .topbar { display: flex; justify-content: space-between; align-items: flex-end; gap: 18px; flex-wrap: wrap; padding: 22px 28px 18px; }
  .crumbs { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
  .crumbs span:last-child { color: var(--text-2); }
  .topbar h1 { font-size: 26px; font-weight: 650; letter-spacing: -0.02em; margin-top: 6px; outline: none; }
  .subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; max-width: 70ch; }

  .source { display: inline-flex; gap: 4px; padding: 4px; border: 1px solid var(--line); border-radius: 13px; background: var(--sidebar); }
  .source button { display: flex; gap: 10px; align-items: center; background: none; border: 1px solid transparent; border-radius: 10px;
    padding: 6px 14px 6px 8px; text-align: left; color: var(--text-2); transition: background-color 0.15s, color 0.15s; }
  .source button:hover { color: var(--text); background: var(--card); }
  .source button.on { background: var(--card-3); border-color: var(--line); color: var(--text); }
  .src-icon { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; background: var(--card-2); color: var(--text-2); }
  .source button.on .src-icon { background: var(--accent-soft); color: var(--accent-text); }
  .src-text { font-size: 13.5px; font-weight: 600; line-height: 1.25; }
  .src-text small { display: block; font-size: 11px; font-weight: 450; color: var(--muted); }

  /* ---- filter toolbar ---- */
  .toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px 20px; align-items: flex-end; margin: 0 28px; padding: 14px 16px;
    background: var(--card); border: 1px solid var(--line-soft); border-radius: var(--radius); box-shadow: var(--shadow); }
  .presets { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .toolbar-label { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); font-weight: 500; margin-right: 4px; }
  .inputs { display: flex; flex-wrap: wrap; gap: 10px; }
  .inputs select { min-width: 112px; }

  .banner { display: flex; gap: 10px; align-items: flex-start; border: 1px solid rgba(224, 93, 93, 0.4); background: rgba(224, 93, 93, 0.08);
    color: var(--critical-text); border-radius: 12px; padding: 12px 14px; font-size: 13px; margin-bottom: 18px; line-height: 1.5; }
  .banner :global(.icon) { margin-top: 2px; }
  .banner strong { color: var(--critical-text); }

  .footer { display: flex; justify-content: space-between; gap: 6px 16px; flex-wrap: wrap; padding: 14px 28px 22px; font-size: 11.5px; color: var(--muted); }

  /* ---- tablet & phone: the sidebar becomes a top bar ---- */
  @media (max-width: 1024px) {
    .shell { flex-direction: column; }
    .sidebar { width: auto; height: auto; position: static; flex-direction: row; flex-wrap: wrap; align-items: center; gap: 12px 18px;
      padding: 14px 16px; border-right: 0; border-bottom: 1px solid var(--line-soft); overflow: visible; }
    .nav { display: flex; gap: 4px; flex: 1 1 auto; overflow-x: auto; scrollbar-width: none; }
    .nav .group { display: none; }
    .nav a { padding: 8px 12px; white-space: nowrap; }
    .nav a.active::before { display: none; }
    .services { order: 3; width: 100%; display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 10px 12px; }
    .services-head { order: 9; margin: 0 0 0 auto; }
    .services-head .eyebrow { display: none; }
    .svc { grid-template-columns: 8px auto auto; }
    .dataset, .credit { display: none; }
    .topbar { padding: 18px 16px 14px; }
    .toolbar { margin: 0 16px; }
    .content { padding: 18px 16px 8px; }
    .footer { padding: 12px 16px 20px; }
  }
  @media (max-width: 640px) {
    .brand .name small { display: none; }
    .nav { order: 2; width: 100%; flex-basis: 100%; }
    .nav a { flex: 1; justify-content: center; padding: 8px 6px; font-size: 13px; gap: 7px; }
    .topbar h1 { font-size: 22px; }
    .source { width: 100%; }
    .source button { flex: 1; padding-right: 8px; }
    .inputs { width: 100%; }
    .inputs .field { flex: 1 1 130px; }
    .inputs input, .inputs select { width: 100%; min-width: 0; }
  }
  @media (max-width: 420px) {
    .nav { gap: 2px; }
    .nav a { padding: 8px 2px; font-size: 12px; }
    .nav a :global(.icon) { display: none; }
  }
</style>
