<script lang="ts">
  import { onMount } from 'svelte'
  import BenchmarkPanel from './BenchmarkPanel.svelte'
  import DatasetCheck from './DatasetCheck.svelte'
  import Icon from './Icon.svelte'
  import ScaleComparison from './ScaleComparison.svelte'
  import { ApiError, getBenchmarks, type BenchmarkSummary, type RunSet } from './api'
  import { fmtEvents, fmtUtc } from './format'

  // Recorded results only (benchmarks/results/summary.json via the API). Live measurements live in
  // the "Comparação" section; the live dataset check below is labelled as such.
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

  type Scenario = { id: string; group: string; label: string; caption: string; set?: RunSet }
  const campaign = $derived(summary?.campaigns?.escala ?? null)
  const sizes = $derived(campaign?.sizes ?? [])
  const largest = $derived(sizes.length ? sizes[sizes.length - 1].logical_events : 0)
  const day = (iso: string | undefined) => (iso ? fmtUtc(iso).slice(0, 5) : '—')
  const scenarios = $derived.by<Scenario[]>(() => {
    if (!summary) return []
    const out: Scenario[] = [{
      id: 'historico', group: 'Histórico', label: `${fmtEvents(Number(summary.main.environment?.dataset?.logical_events ?? 1_000_000))} · ${day(summary.main.finished_at)}`,
      caption: 'Execuções originais da Task 04 (E1–E6, N+1 e durabilidade), preservadas sem alteração.', set: summary,
    }]
    for (const s of sizes) {
      out.push({
        id: `escala-${s.logical_events}`, group: 'Campanha de escala', label: `${fmtEvents(s.logical_events)} · ${day(s.main.finished_at)}`,
        caption: s.logical_events === sizes[0].logical_events
          ? 'Baseline da campanha, medido antes da ampliação, com o mesmo código e protocolo dos volumes maiores.'
          : s.logical_events === largest ? 'Maior volume carregado e validado nos dois bancos.' : 'Marco intermediário da ampliação.',
        set: s,
      })
    }
    if (sizes.length >= 2) out.push({ id: 'comparacao', group: 'Análise', label: `${fmtEvents(sizes[0].logical_events)} × ${fmtEvents(largest)}`, caption: 'Como cada operação reage ao crescimento da massa.' })
    return out
  })
  const groups = $derived([...new Set(scenarios.map((s) => s.group))])
  let picked = $state<string | null>(null)
  const active = $derived(scenarios.find((s) => s.id === picked) ?? scenarios.find((s) => s.id === 'comparacao') ?? scenarios[0])
</script>

{#if status === 'loading'}
  <p class="sr-only" role="status">Carregando resultados medidos…</p>
  <div class="card" aria-hidden="true"><div class="skeleton" style="height:84px"></div></div>
  <div class="card" aria-hidden="true"><div class="skeleton" style="height:360px"></div></div>
{:else if status === 'missing'}
  <div class="card state">
    <h2><span class="icon-wrap"><Icon name="flask" size={17} /></span>Nenhum benchmark executado</h2>
    <p>Rode <code>python benchmarks/run_benchmarks.py</code> com a API em build release. Nada é exibido sem medição real.</p>
  </div>
{:else if status === 'error'}
  <div class="card state error" role="alert">
    <h2><span class="icon-wrap"><Icon name="alert" size={17} /></span>Resultados indisponíveis</h2>
    <p>Não foi possível carregar os resultados: {message}</p>
    <button class="btn" onclick={load}><Icon name="refresh" size={15} />Tentar novamente</button>
  </div>
{:else if summary && active}
  <section class="card scenario-bar" aria-label="Cenário experimental">
    <div class="pick">
      <p class="eyebrow">Cenário experimental · resultados gravados</p>
      <div class="groups">
        {#each groups as group (group)}
          <div class="group" role="group" aria-label={group}>
            <span class="group-label">{group}</span>
            {#each scenarios.filter((s) => s.group === group) as s (s.id)}
              <button class="chip" class:on={active.id === s.id} aria-pressed={active.id === s.id} onclick={() => (picked = s.id)}>{s.label}</button>
            {/each}
          </div>
        {/each}
      </div>
      <p class="caption"><Icon name="info" size={14} />{active.caption} Fonte: <code>benchmarks/results</code>; não são medições ao vivo (para medir agora, use a seção Comparação).</p>
    </div>
    <div class="live">
      <p class="eyebrow">Ao vivo · massa ativa</p>
      <DatasetCheck />
    </div>
  </section>

  {#if active.id === 'comparacao' && campaign}
    <ScaleComparison {campaign} />
  {:else if active.set}
    {#key active.id}<BenchmarkPanel set={active.set} />{/key}
  {/if}
{/if}

<style>
  .scenario-bar { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 18px 24px; align-items: start; }
  .pick { display: grid; gap: 10px; min-width: 0; }
  .groups { display: flex; flex-wrap: wrap; gap: 10px 22px; }
  .group { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
  .group-label { font-size: 12px; color: var(--muted); font-weight: 550; margin-right: 2px; }
  .caption { display: flex; gap: 7px; align-items: flex-start; font-size: 12px; color: var(--text-2); line-height: 1.55; }
  .caption :global(.icon) { flex-shrink: 0; margin-top: 2px; color: var(--steel-text); }
  .live { display: grid; gap: 8px; padding-left: 20px; border-left: 1px solid var(--line-soft); }
  @media (max-width: 900px) {
    .scenario-bar { grid-template-columns: 1fr; }
    .live { padding-left: 0; border-left: 0; padding-top: 14px; border-top: 1px solid var(--line-soft); }
  }
</style>
