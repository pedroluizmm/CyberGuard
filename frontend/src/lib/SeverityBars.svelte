<script lang="ts">
  import { SEVERITY_LABEL } from './api'
  import { fmtInt, fmtPct } from './format'

  // Ordinal ramp (one hue, monotone lightness): brighter = more severe. Number + name always shown.
  let { values, selected = null }: { values: number[]; selected?: number | null } = $props()
  const total = $derived(values.reduce((a, b) => a + b, 0))
  const peak = $derived(Math.max(1, ...values))
</script>

<ol class="sev-bars" aria-label="Eventos por severidade">
  {#each values as value, i (i)}
    {@const share = fmtPct(value, total)}
    <li class:dim={selected !== null && selected !== i + 1} title={`Severidade ${i + 1} (${SEVERITY_LABEL[i]}): ${fmtInt(value)} eventos, ${share}`}>
      <span class="label"><span class="sev" class:light={i >= 2} style:--c={`var(--sev-${i + 1})`}>{i + 1}</span>{SEVERITY_LABEL[i]}</span>
      <span class="track"><span class="fill" style:width={`${(value / peak) * 100}%`} style:background={`var(--sev-${i + 1})`}></span></span>
      <span class="value">{fmtInt(value)}<small>{share}</small></span>
    </li>
  {/each}
</ol>

<style>
  .sev-bars { list-style: none; margin: 0; padding: 0; display: grid; gap: 13px; }
  li { display: grid; grid-template-columns: 118px minmax(40px, 1fr) auto; align-items: center; gap: 12px; transition: opacity 0.2s; }
  li.dim { opacity: 0.35; }
  .label { display: flex; align-items: center; gap: 9px; font-size: 12.5px; color: var(--text-2); }
  .label .sev { width: 22px; height: 22px; font-size: 11.5px; border-radius: 6px; }
  .track { height: 10px; border-radius: 0 5px 5px 0; background: var(--card-2); overflow: hidden; }
  .fill { display: block; height: 100%; min-width: 2px; border-radius: 0 4px 4px 0; }
  .value { font-size: 12.5px; color: var(--text); font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; min-width: 92px; }
  .value small { color: var(--muted); margin-left: 6px; font-size: 11.5px; }
  @media (max-width: 420px) {
    li { grid-template-columns: 1fr auto; }
    .track { grid-column: 1 / -1; grid-row: 2; }
  }
</style>
