<script lang="ts">
  import { SEVERITY_LABEL } from './api'
  import { fmtInt, fmtPct } from './format'

  let { values, selected = null }: { values: number[]; selected?: number | null } = $props()
  const total = $derived(values.reduce((a, b) => a + b, 0))
  const peak = $derived(Math.max(1, ...values))
</script>

<ol class="bars" aria-label="Eventos por severidade">
  {#each values as value, i}
    {@const share = fmtPct(value, total)}
    <li class:dim={selected !== null && selected !== i + 1} title={`Severidade ${i + 1} (${SEVERITY_LABEL[i]}): ${fmtInt(value)} eventos, ${share}`}>
      <span class="label"><b>{i + 1}</b>{SEVERITY_LABEL[i]}</span>
      <span class="track">
        <span class="bar" style:width={`${(value / peak) * 100}%`} style:background={`var(--sev-${i + 1})`}></span>
        <span class="value">{fmtInt(value)} <small>{share}</small></span>
      </span>
    </li>
  {/each}
</ol>

<style>
  .bars { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
  li { display: grid; grid-template-columns: 112px 1fr; align-items: center; gap: 12px; transition: opacity .2s; }
  li.dim { opacity: .35; }
  .label { font-size: 12px; color: var(--text-2); display: flex; gap: 8px; align-items: baseline; }
  .label b { color: var(--text); font-variant-numeric: tabular-nums; width: 10px; }
  .track { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .bar { display: block; height: 14px; min-width: 2px; border-radius: 0 4px 4px 0; flex-shrink: 0; max-width: calc(100% - 110px); }
  .value { font-size: 12px; color: var(--text); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .value small { color: var(--muted); margin-left: 4px; }
</style>
