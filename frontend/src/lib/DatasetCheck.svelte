<script lang="ts">
  import Icon from './Icon.svelte'
  import { ApiError, countDataset, SOURCE_LABEL, SOURCES, type Source } from './api'
  import { fmtInt, fmtMs } from './format'

  // Live check (not a benchmark): logical events loaded now in each database, as the sum of the
  // four weekly dashboards of the 28-day dataset window (PostgreSQL aggregates rows, Cassandra
  // reads its rollup). The two totals must match; nothing is cached or assumed.
  let { compact = false }: { compact?: boolean } = $props()
  type Result = { total: number; httpMs: number; dbMs: number }
  let status = $state<'idle' | 'running' | 'done' | 'error'>('idle')
  let results = $state<Partial<Record<Source, Result>>>({})
  let message = $state('')

  async function run() {
    status = 'running'
    results = {}
    try {
      for (const source of SOURCES) results = { ...results, [source]: await countDataset(source) }
      status = 'done'
    } catch (e) {
      message = e instanceof ApiError ? e.message : 'Falha inesperada.'
      status = 'error'
    }
  }
  const same = $derived(status === 'done' && results.postgresql?.total === results.cassandra?.total)
</script>

<div class="check" class:compact aria-live="polite">
  <button class="btn small" onclick={run} disabled={status === 'running'}>
    {#if status === 'running'}<span class="spinner"></span>Contando…{:else}<Icon name="target" size={14} />{compact ? 'Conferir massa' : 'Conferir massa nos dois bancos'}{/if}
  </button>
  {#if status === 'done' || (status === 'running' && Object.keys(results).length)}
    <ul>
      {#each SOURCES as s (s)}
        {@const r = results[s]}
        <li><span>{SOURCE_LABEL[s]}</span>{#if r}<strong class="num">{fmtInt(r.total)}</strong><em>{fmtMs(r.dbMs)} no banco</em>{:else}<em>…</em>{/if}</li>
      {/each}
    </ul>
    {#if status === 'done'}
      <p class={same ? 'ok' : 'bad'}><Icon name={same ? 'check' : 'x'} size={13} />{same ? 'Mesmo total nos dois bancos' : 'Totais diferentes: reconciliar antes de medir'}</p>
    {/if}
  {:else if status === 'error'}
    <p class="bad" role="alert"><Icon name="alert" size={13} />{message}</p>
  {:else if !compact}
    <p class="hint">Soma dos 4 painéis semanais (05/10–01/11) consultados agora: o PostgreSQL agrega as linhas e o Cassandra lê o rollup.</p>
  {/if}
</div>

<style>
  .check { display: grid; gap: 8px; justify-items: start; min-width: 0; }
  .check.compact .btn { width: 100%; white-space: normal; }
  ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; width: 100%; }
  li { display: grid; grid-template-columns: 1fr auto; column-gap: 8px; font-size: 12px; color: var(--text-2); }
  li strong { color: var(--text); font-weight: 650; text-align: right; }
  li em { grid-column: 1 / -1; font-style: normal; font-size: 11px; color: var(--muted); }
  p { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; line-height: 1.45; }
  .ok { color: var(--good); }
  .bad { color: var(--critical-text); }
  .hint { color: var(--muted); display: block; }
  .compact li em { display: none; }
</style>
