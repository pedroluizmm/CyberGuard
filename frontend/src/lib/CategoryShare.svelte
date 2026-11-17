<script lang="ts">
  import { CATEGORIES, CATEGORY_LABEL } from './api'
  import { fmtInt, fmtPct } from './format'

  let { values }: { values: number[] } = $props()
  const total = $derived(values.reduce((a, b) => a + b, 0))
  const color = ['var(--cat-auth)', 'var(--cat-net)', 'var(--cat-alert)']
  const label = $derived(CATEGORIES.map((c, i) => `${CATEGORY_LABEL[c]} ${fmtInt(values[i])} (${fmtPct(values[i], total)})`).join(', '))
</script>

<div class="share">
  <div class="total"><strong>{fmtInt(total)}</strong><span>eventos em {values.filter((v) => v > 0).length} {values.filter((v) => v > 0).length === 1 ? 'categoria' : 'categorias'}</span></div>
  <div class="segments" role="img" aria-label={`Participação por categoria: ${label}`}>
    {#each CATEGORIES as c, i (c)}
      {#if values[i] > 0}
        <span style:flex-grow={values[i]} style:background={color[i]} title={`${CATEGORY_LABEL[c]}: ${fmtInt(values[i])} (${fmtPct(values[i], total)})`}></span>
      {/if}
    {/each}
  </div>
  <ul class="legend">
    {#each CATEGORIES as c, i (c)}
      <li class:zero={values[i] === 0}>
        <i style:background={color[i]}></i><span>{CATEGORY_LABEL[c]}</span>
        <strong>{fmtInt(values[i])}</strong><em>{fmtPct(values[i], total)}</em>
      </li>
    {/each}
  </ul>
</div>

<style>
  .total { display: flex; align-items: baseline; gap: 8px; margin-bottom: 14px; }
  .total strong { font-size: 24px; font-weight: 650; letter-spacing: -0.02em; }
  .total span { font-size: 12px; color: var(--muted); }
  /* 2 px surface gap between segments; rounded ends. */
  .segments { display: flex; gap: 2px; height: 12px; }
  .segments span { border-radius: 4px; min-width: 3px; }
  .legend { list-style: none; padding: 0; margin: 18px 0 0; display: grid; gap: 2px; }
  .legend li { display: grid; grid-template-columns: 10px 1fr auto 52px; gap: 10px; align-items: center; font-size: 12.5px; color: var(--text-2);
    padding: 8px 0; border-bottom: 1px solid var(--line-soft); }
  .legend li:last-child { border-bottom: 0; }
  .legend li.zero { opacity: 0.45; }
  .legend i { width: 10px; height: 10px; border-radius: 3px; }
  .legend strong { color: var(--text); font-variant-numeric: tabular-nums; font-weight: 600; }
  .legend em { font-style: normal; color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }
</style>
