<script lang="ts">
  import { CATEGORIES, CATEGORY_LABEL } from './api'
  import { fmtInt, fmtPct } from './format'

  let { values }: { values: number[] } = $props()
  let width = $state(300)
  const total = $derived(values.reduce((a, b) => a + b, 0))
  const color = ['var(--cat-auth)', 'var(--cat-net)', 'var(--cat-alert)']
  const label = $derived(CATEGORIES.map((c, i) => `${CATEGORY_LABEL[c]} ${fmtInt(values[i])} (${fmtPct(values[i], total)})`).join(', '))
</script>

<div class="share">
  <div class="segments" role="img" aria-label={`Participação por categoria: ${label}`} bind:clientWidth={width}>
    {#each CATEGORIES as c, i}
      {#if values[i] > 0}
        <span style:flex-grow={values[i]} style:background={color[i]} title={`${CATEGORY_LABEL[c]}: ${fmtInt(values[i])} (${fmtPct(values[i], total)})`}>
          <!-- Printed only when the block is wide enough; otherwise legend/tooltip carry it. -->
          {#if (values[i] / total) * width >= 58}{fmtPct(values[i], total)}{/if}
        </span>
      {/if}
    {/each}
  </div>
  <ul class="legend">
    {#each CATEGORIES as c, i}
      <li><i style:background={color[i]}></i><span>{CATEGORY_LABEL[c]}</span><strong>{fmtInt(values[i])}</strong></li>
    {/each}
  </ul>
</div>

<style>
  .segments { display: flex; gap: 2px; height: 28px; }
  .segments span { border-radius: 4px; min-width: 3px; display: flex; align-items: center; padding-left: 8px; font-size: 12px; font-weight: 600; color: #fff; white-space: nowrap; }
  .legend { list-style: none; padding: 0; margin: 14px 0 0; display: grid; gap: 8px; }
  .legend li { display: grid; grid-template-columns: 10px 1fr auto; gap: 9px; align-items: center; font-size: 12px; color: var(--text-2); }
  .legend i { width: 10px; height: 10px; border-radius: 2px; }
  .legend strong { color: var(--text); font-variant-numeric: tabular-nums; font-weight: 600; }
</style>
