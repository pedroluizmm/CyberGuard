<script lang="ts" module>
  export type BarItem = { key: string; label: string; value: number; detail: string }
</script>

<script lang="ts">
  import { fmtCompact, fmtInt, niceTicks } from './format'

  // One series (total volume) in one hue; the largest bar is emphasised in blue-gray.
  let { items }: { items: BarItem[] } = $props()

  const height = 300
  const m = { top: 24, right: 6, bottom: 26, left: 42 }
  let width = $state(360)
  let hover = $state<number | null>(null)

  const innerW = $derived(Math.max(60, width - m.left - m.right))
  const innerH = height - m.top - m.bottom
  const max = $derived(Math.max(1, ...items.map((d) => d.value)))
  const peak = $derived(items.findIndex((d) => d.value === max))
  const ticks = $derived(niceTicks(max, 4))
  const top = $derived(ticks[ticks.length - 1] || 1)
  const band = $derived(innerW / Math.max(1, items.length))
  const barW = $derived(Math.max(3, Math.min(44, band * 0.62)))
  const x = (i: number) => m.left + i * band + (band - barW) / 2
  const y = (v: number) => m.top + innerH - (v / top) * innerH
  // Rounded data-end only (4 px), square at the baseline.
  function path(i: number, v: number) {
    const x0 = x(i), y0 = y(v), h = m.top + innerH - y0, r = Math.min(4, barW / 2, h)
    return `M${x0},${m.top + innerH}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}H${x0 + barW - r}Q${x0 + barW},${y0} ${x0 + barW},${y0 + r}V${m.top + innerH}Z`
  }
  const every = $derived(Math.max(1, Math.ceil(34 / band)))
  const summary = $derived(items.map((d) => `${d.detail}: ${fmtInt(d.value)}`).join('; '))
  const active = $derived(hover === null ? null : items[hover])
</script>

<div class="bars" bind:clientWidth={width}>
  <svg {width} {height} role="img" aria-label={`Volume de eventos. ${summary}`}>
    {#each ticks as t (t)}
      <line class="grid" x1={m.left} x2={m.left + innerW} y1={y(t)} y2={y(t)} />
      <text class="tick" x={m.left - 8} y={y(t)} text-anchor="end" dominant-baseline="middle">{fmtCompact(t)}</text>
    {/each}
    {#each items as d, i (d.key)}
      {#if d.value > 0}
        <path d={path(i, d.value)} class="bar" class:peak={i === peak} class:hot={hover === i} />
      {/if}
      {#if i === peak}
        <text class="peak-label" x={x(i) + barW / 2} y={y(d.value) - 8} text-anchor="middle">{fmtCompact(d.value)}</text>
      {/if}
      {#if i % every === 0}
        <text class="tick" x={x(i) + barW / 2} y={height - 8} text-anchor="middle">{d.label}</text>
      {/if}
      <!-- Hit target: the whole column, wider than the mark. -->
      <rect class="hit" x={m.left + i * band} y={m.top} width={band} height={innerH}
        role="presentation" onpointerenter={() => (hover = i)} onpointerleave={() => (hover = null)} />
    {/each}
    <line class="axis" x1={m.left} x2={m.left + innerW} y1={m.top + innerH} y2={m.top + innerH} />
  </svg>
  {#if active && hover !== null}
    <div class="tooltip" class:flip={x(hover) > width * 0.6} style:left={`${x(hover) + barW / 2}px`} style:top={`${Math.max(4, y(active.value) - 64)}px`} role="status">
      <p>{active.detail}</p><strong>{fmtInt(active.value)}</strong><span> eventos</span>
    </div>
  {/if}
</div>

<style>
  .bars { position: relative; width: 100%; }
  svg { display: block; overflow: visible; }
  .grid { stroke: var(--grid); stroke-width: 1; }
  .axis { stroke: var(--axis); stroke-width: 1; }
  .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .bar { fill: var(--bar-muted); transition: fill 0.15s; }
  .bar.peak { fill: var(--steel); }
  .bar.hot { fill: #56607a; }
  .bar.peak.hot { fill: #8197bb; }
  .peak-label { fill: var(--text); font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .hit { fill: transparent; }
  .tooltip { position: absolute; transform: translateX(10px); background: var(--card-3); border: 1px solid var(--line); border-radius: 10px;
    padding: 8px 11px; pointer-events: none; box-shadow: 0 10px 28px rgba(0, 0, 0, 0.5); z-index: 2; white-space: nowrap; font-size: 12px; }
  .tooltip.flip { transform: translateX(calc(-100% - 10px)); }
  .tooltip p { color: var(--muted); font-size: 11px; margin-bottom: 3px; }
  .tooltip strong { font-size: 14px; color: var(--text); font-variant-numeric: tabular-nums; }
  .tooltip span { color: var(--text-2); }
</style>
